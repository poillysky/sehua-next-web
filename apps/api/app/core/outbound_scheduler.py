"""出站调度：全局闸 + 按 host 并发/间距 + host 退避（成熟爬虫模型）。

目标：多番号 × 多源 × 封面并发时，跨站并行拉满、同站排队，
避免全局一把锁互踩或抢槽假失败。
"""

from __future__ import annotations

import logging
import math
import random
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

# 取消令牌的轮询步长：等槽期间每 0.2s 醒一次看是否已被上层放弃。
# 取 0.2s 是折中——比单源超时（≥18s）小两个数量级，几乎不影响抢槽成功率，
# 又足以让「早停后放弃的在飞源」在 0.2s 内退出，不再等到槽位后白发一次请求。
_CANCEL_POLL_SEC = 0.2


class OutboundCancelled(Exception):
    """等槽期间被上层取消（源早停 / 暂停 / 停止）。

    语义：本次请求彻底放弃，**不得**再发出站请求。
    与 TimeoutError 区分：超时是「等不到槽」，取消是「不需要槽了」。
    """


def _is_cancelled(cancel: Any) -> bool:
    try:
        return cancel is not None and bool(cancel.is_set())
    except Exception:  # noqa: BLE001
        return False


class OutboundBusy(TimeoutError):
    """等槽 / 限速 / 退避超出了**排队预算** —— 这次请求压根没轮到发，不是源故障。

    为什么要单独一个类型：`TimeoutError` 的既有语义是「等不到槽」，但
    `enrich._classify_source_failure` 只按消息里的 `timeout` 判定 → 排队被记成
    `down`（源不可用）→ 高优先源静默降级 + 误挂补抓标记（mgstage 433 次假 down 的根因之一）。

    继承 `TimeoutError` 是为了兼容既有 `except TimeoutError` 分支（行为不变）；
    需要区分时用**类名**或消息里的 `outbound busy` 标记 —— 两者都留着，
    因为异常可能被中间层重新包装成 `RuntimeError(str(e))` 而丢掉类名。
    """


class SlotWaitMeter:
    """出站等槽记账：**只累计「没在发请求」的时间**（pause / pacing / 抢槽 / 退避）。

    用途：把策略「单源超时」从**墙钟**改成**工作耗时** ——
    `enrich._one` 每 0.25s 轮询 `wait_now()`，用「墙钟 − 等槽」判真超时。
    否则 `th.join(timeout=单源超时)` 会把排队算进单源超时，源明明 3.4s 能返回
    也被记成 `down`。

    线程本地创建、**跨线程只读观测**：写值方（fetch 线程）与取值方（池线程）
    共享同一个对象，所以只做单字段赋值（GIL 下安全），不做复合原子操作。
    """

    __slots__ = ("total", "waiting_since", "acquired", "slot_timeout")

    def __init__(self) -> None:
        self.total = 0.0  # 累计等槽秒数（已结算的部分）
        self.waiting_since = 0.0  # >0 表示此刻正在等槽（monotonic 起点）
        self.acquired = 0  # 成功拿到槽的次数；0 = 压根没轮到发请求
        # 排队预算耗尽（OutboundBusy）的次数。第十一轮用：源自己可能
        # `except Exception: return None` 把这个信号吞成「未找到」，
        # 记账是唯一可靠的痕迹 → `enrich` 用它把假 miss 改回 busy。
        self.slot_timeout = 0

    def wait_now(self) -> float:
        """含「此刻正在等」的累计等槽秒数。"""
        w = float(self.total)
        since = float(self.waiting_since)
        if since > 0.0:
            w += max(0.0, time.monotonic() - since)
        return w


_meter_tls = threading.local()


def set_thread_slot_meter(meter: SlotWaitMeter | None) -> None:
    """把「本线程的出站等槽记账对象」绑到线程上（None = 解绑）。"""
    if meter is None:
        if hasattr(_meter_tls, "meter"):
            delattr(_meter_tls, "meter")
        return
    _meter_tls.meter = meter


def thread_slot_meter() -> SlotWaitMeter | None:
    return getattr(_meter_tls, "meter", None)


# 单个番号同时要抓的源数（第十七轮实测：10 个启用源均 1 请求；按 9 计留余量）
ITEM_SOURCES_PER_JOB = 9
# 其中走直连 api 通道的占比（dmm / r18dev / libredmm / jav321 这四类）
API_SOURCE_RATIO = 1.0 / 3.0
# 上表 page/api 两行所对应的 itemWorkers —— 改这两个常量的前提是同步改公式输入
CAPS_BASELINE_ITEM_WORKERS = 4

# 封面全局槽相对「真实峰值并发」的余量。
# 峰值 = itemWorkers × COVER_BATCH_WORKERS（封面是在番号工人里**同步** `.result()` 等结果的，
# 见 `enrich._download_covers`，所以不是异步池，会乘起来）。
#
# 1.25（基线恒等 20）→ 1.5（基线 24）：第二十一轮调高，依据是**现场实测到的
# `slot_blocked`**（报告 §二十一）。原 1.25 只算了「本进程 itemWorkers × 批并发」
# 这一路来源，漏掉了同样取 `kind="cover"` 全局槽的旁路调用方（列表/详情封面代理），
# 峰值一叠加就先于站点限流触顶 → 抢槽 TimeoutError → 记成 `slot_blocked`
# （看起来像图床故障，实际是**自己人挤自己人**）。
# 1.5 的余量正好覆盖那部分旁路流量；仍然只动**全局**槽，
# `pics.dmm.co.jp per_host=4` 这类站点保护不变，所以不会多打上游。
COVER_SLOT_HEADROOM = 1.5


def _cover_batch_workers() -> int:
    """封面每番号的并发候选数 —— **惰性读** `cover_download`，不复制数值。

    为什么惰性读而不是复制常量：第十七轮 D5 的教训就是「同一个需求量在两处
    各写各的常量」，两边一改就超订。这里让封面槽跟着 `COVER_BATCH_WORKERS`
    自动走，改封面并发只需改一个地方。
    兜底值 4 仅在极端情况（循环导入 / 模块缺失）下生效，有单测锁住真实读取。
    """
    try:
        from app.scrap_library.cover_download import COVER_BATCH_WORKERS

        return max(1, int(COVER_BATCH_WORKERS))
    except Exception:  # noqa: BLE001
        return 4


def cover_cap_for_item_workers(item_workers: int) -> int:
    """由 itemWorkers 推封面全局槽。

    为什么封面**必须**进公式（第十九轮发现）：`_KIND_GLOBAL["cover"]` 原来固定 20，
    而 `apply_item_workers()` 只重算 page/api。于是 itemWorkers 一抬就有：

        itemWorkers=4  → 峰值 16  ≤ 20  ✅（当前，刚好不挤兑）
        itemWorkers=8  → 峰值 32  > 20  ❌ 超订 1.6×
        itemWorkers=16 → 峰值 64  > 20  ❌ 超订 3.2×

    超订的直接后果不是「变慢」而是**误判**：抢不到封面槽抛 `TimeoutError`，
    被上层写成 `slot_blocked`（见 `cover_download._fetch`），看起来像图床有问题。
    **所以顺序必须是「先让 cover 进公式，再抬 itemWorkers」**，反过来先把封面挤死。

    ⚠️ 与 page/api 同理：这里只动**全局**槽。站点保护仍由 `per_host` /
    `min_interval`（如 `pics.dmm.co.jp` per_host=4）承担，所以抬高全局上限
    并不会多打上游 —— 只是让全局槽不再先于站点限流触顶。
    """
    n = max(int(item_workers), int(CAPS_BASELINE_ITEM_WORKERS))
    return int(math.ceil(n * _cover_batch_workers() * COVER_SLOT_HEADROOM))


def caps_for_item_workers(item_workers: int) -> dict[str, int]:
    """由「同时处理的番号数」推出 page / api 全局槽上限。

    第十七轮 D5 发现：`page=24 + api=12 = 36` 与 `itemWorkers=4 × 9 源 = 36 路`
    是**刻意凑出来的 1:1**，但两处常量各写各的 —— 只抬 itemWorkers 会变成
    2× 超订（`waitMs` 上涨、可能触发 busy），只抬槽位则白占资源。
    这里把那个巧合改成公式，让扩容只有一个入口：

        demand = item_workers × ITEM_SOURCES_PER_JOB
        api    = round(demand × API_SOURCE_RATIO)
        page   = demand − api

    自证：n=4 → demand 36 → api 12 / page 24，**与历史常量逐字相同**（有单测锁住）；
    cover 侧 n=4 → 20，同样等于历史常量。
    换句话说，itemWorkers=4 时本函数是恒等变换，行为不变；只有在调大
    itemWorkers 时才真正生效。

    ⚠️ 只动**全局**槽，绝不动 `_KIND_HOST` 的 per_host —— 保护单个站点的是
    per_host 与 min_interval，全局槽只决定「同时在打多少个不同 host」。这是
    扩容不会打爆上游的原因，改公式时别把这条丢了。
    """
    n = max(1, int(item_workers))
    demand = n * int(ITEM_SOURCES_PER_JOB)
    api = max(6, int(round(demand * API_SOURCE_RATIO)))
    page = max(8, demand - api)
    return {"page": page, "api": api, "cover": cover_cap_for_item_workers(n)}


# 进程级：详情与封面分槽，避免 5 路刮详情把封面槽抢光（或反过来）
_KIND_GLOBAL: dict[str, int] = {
    # page / api / cover 的默认值 = caps_for_item_workers(4)（2026-09-16 对齐 itemWorkers=4；
    # 2026-09-17 第十八轮改为公式推导，默认值不变；第十九轮把 **cover 也纳入公式**）。
    # 运行期由 `OutboundScheduler.apply_item_workers()` 按实际 itemWorkers 覆盖。
    # ⚠️ 上限逻辑见 §十五：再往上先看 sourceTimings[].waitMs 分布，别拍脑袋。
    "page": 24,
    # 封面：4 番号 × 4 候选 × 1.5 余量 = 24。**别再写死** —— 它随 itemWorkers 缩放，
    # 否则抬并发时封面会先于站点限流触顶，失败被记成 slot_blocked（第十九轮）。
    # 余量 1.25→1.5 的理由见 `COVER_SLOT_HEADROOM` 上方注释（第二十一轮）。
    "cover": 24,
    "ui": 8,
    # 直连 API（JSON / GraphQL / POST 表单）：第十一轮新增。
    # 原来 r18dev / libredmm / dmm / jav321 这些源**根本不走调度器** ——
    # 既不受并发上限约束，也不进 SlotWaitMeter（导致源真超时被误记成 busy）。
    "api": 12,
}

# kind → 每 host 默认并发 / 最小间隔（秒）
_KIND_HOST: dict[str, dict[str, float]] = {
    "page": {"per_host": 3, "min_interval": 0.06},
    # 封面：批量多番号同 CDN；略放宽并发、缩短间距，靠短槽超时防饿死
    "cover": {"per_host": 6, "min_interval": 0.02},
    "ui": {"per_host": 2, "min_interval": 0.0},
    # API：站点小、响应快，但突发更敏感 → 同站 2 路 + 50ms 间距
    "api": {"per_host": 2, "min_interval": 0.05},
}

# 已知图床/官网：略收紧，防短时打爆
_HOST_OVERRIDES: dict[str, dict[str, float]] = {
    "pics.dmm.co.jp": {"per_host": 4, "min_interval": 0.05},
    "awsimgsrc.dmm.co.jp": {"per_host": 5, "min_interval": 0.04},
    "image.mgstage.com": {"per_host": 5, "min_interval": 0.03},
    "www.mgstage.com": {"per_host": 2, "min_interval": 0.08},
    # r18.dev 官方约定：**单线程 + ≥0.45s 间隔**（并发会 429/封）。
    # 这条原来只在手动探针里遵守，生产路径（r18dev.py → fetch_json）没实现 ——
    # 第十一轮把它落到调度器上（覆盖对所有 kind 生效，而 r18.dev 只出现在 api 通道）。
    "r18.dev": {"per_host": 1, "min_interval": 0.45},
    # iqqtv 镜像站：双页时代易把 page 槽打满；限 2 路 + 间距，防跑久后集体超时
    "iqqk4.quest": {"per_host": 2, "min_interval": 0.12},
    "www.iqqk4.quest": {"per_host": 2, "min_interval": 0.12},
    "iqq5.xyz": {"per_host": 2, "min_interval": 0.12},
    "www.iqq5.xyz": {"per_host": 2, "min_interval": 0.12},
    "iqq6.xyz": {"per_host": 2, "min_interval": 0.12},
    "www.iqq6.xyz": {"per_host": 2, "min_interval": 0.12},
}


class OutboundScheduler:
    def __init__(self, *, global_limit: int | None = None) -> None:
        # 兼容旧参数：若传入则作为 page/cover 的下限地板
        floor = max(4, int(global_limit)) if global_limit else 0
        self._globals: dict[str, threading.Semaphore] = {
            k: threading.Semaphore(max(floor, n) if floor else n)
            for k, n in _KIND_GLOBAL.items()
        }
        self._mu = threading.Lock()
        self._host_sems: dict[str, threading.Semaphore] = {}
        self._host_limits: dict[str, int] = {}
        self._next_at: dict[str, float] = {}
        self._paused_until: dict[str, float] = {}
        self._client_mu = threading.Lock()
        self._clients: dict[str, httpx.Client] = {}
        # 早停/暂停回收的在飞请求数（可观测：抢槽前被取消的次数）
        self._cancelled_n = 0
        # 已应用的 itemWorkers（None = 还没按任务规模重算过槽位）
        self._applied_item_workers: int | None = None

    def apply_item_workers(self, item_workers: int) -> None:
        """按 itemWorkers 重算 page / api / cover 全局槽（幂等；**不动** host 级限流）。

        为什么要有这个入口：`page=24 + api=12 = 36` 与 `itemWorkers=4 × 9 源`
        的 1:1 是手工凑的，只抬 itemWorkers 会 2× 超订（第十六/十七轮反复踩）。
        改成公式后，扩容只需改策略里的 itemWorkers 一处。

        ⚠️ 第十九轮补上 **cover**：它原来固定 20、不随 itemWorkers 走，
        抬并发时这一格是全表最先触顶的（`itemWorkers × COVER_BATCH_WORKERS`）。
        只重算 page/api 等于把风险从详情挪到了封面。

        ⚠️ 只在**任务启动前**调用：此时没有在飞请求，换信号量是安全的。
        任务飞行中改 itemWorkers 不会自动生效（需重开任务）—— 刻意如此，
        否则已持有旧信号量对象的线程会把许可 release 到孤儿对象上，
        计数永久漂移。这也和「改 app/*.py 会硬重启」的既有约束一致。
        """
        n = int(item_workers or 0)
        if n <= 0:
            n = int(CAPS_BASELINE_ITEM_WORKERS)
        with self._mu:
            if self._applied_item_workers == n:
                return
            caps = caps_for_item_workers(n)
            for kind, cap in caps.items():
                self._globals[kind] = threading.Semaphore(int(cap))
            self._applied_item_workers = n
        log.info(
            "outbound caps applied · itemWorkers=%s page=%s api=%s cover=%s "
            "(per_host 不变，站点保护仍由 per_host/min_interval 承担)",
            n,
            caps["page"],
            caps["api"],
            caps["cover"],
        )

    def applied_item_workers(self) -> int:
        """当前槽位是按哪个 itemWorkers 算出来的（未应用过则返回基线值）。

        调用方（换号主循环）用它给「热更新并发」封顶：飞行中换信号量不安全，
        所以派发上限不得越过已经按规模算好的槽位，否则就是 2× 超订。
        """
        n = self._applied_item_workers
        return int(n) if n else int(CAPS_BASELINE_ITEM_WORKERS)

    @staticmethod
    def host_key(url_or_host: str) -> str:
        s = str(url_or_host or "").strip()
        if not s:
            return "_"
        if "://" in s:
            try:
                return (urlparse(s).hostname or "").lower() or "_"
            except Exception:
                return "_"
        return s.lower().split("/")[0].split(":")[0] or "_"

    def _limits_for(self, host: str, kind: str) -> tuple[int, float]:
        base = _KIND_HOST.get(kind) or _KIND_HOST["page"]
        per_host = int(base.get("per_host") or 3)
        interval = float(base.get("min_interval") or 0.0)
        for suffix, ov in _HOST_OVERRIDES.items():
            if host == suffix or host.endswith("." + suffix):
                if "per_host" in ov:
                    per_host = int(ov["per_host"])
                if "min_interval" in ov:
                    interval = float(ov["min_interval"])
                break
        return max(1, per_host), max(0.0, interval)

    def _host_sem(self, host: str, kind: str) -> threading.Semaphore:
        key = f"{kind}:{host or '_'}"
        per_host, _ = self._limits_for(host, kind)
        with self._mu:
            sem = self._host_sems.get(key)
            # 限额变更时重建（少见）
            if sem is None or self._host_limits.get(key) != per_host:
                sem = threading.Semaphore(per_host)
                self._host_sems[key] = sem
                self._host_limits[key] = per_host
            return sem

    def _raise_cancelled(self, what: str, *, kind: str = "", host: str = "") -> None:
        """取消的唯一出口：计数可观测 + 抛 OutboundCancelled。"""
        self._note_cancelled()
        detail = " ".join(x for x in (kind, host) if x)
        raise OutboundCancelled(f"cancelled {what}{(' ' + detail) if detail else ''}")

    def _wait_pause(
        self, host: str, deadline: float | None, cancel: Any = None
    ) -> None:
        while True:
            if _is_cancelled(cancel):
                self._raise_cancelled("while paused", host=host)
            with self._mu:
                until = float(self._paused_until.get(host) or 0.0)
            now = time.monotonic()
            if until <= now:
                return
            sleep_for = until - now
            if deadline is not None:
                left = deadline - now
                if left <= 0:
                    # 与 _pace 一致：host 退避/暂停也是「我们这边没轮到」，
                    # 不是源故障。原来抛裸 TimeoutError，消息里又只有「paused」，
                    # 分类器认不出 → 语义漂移。统一成 OutboundBusy。
                    raise OutboundBusy(f"outbound busy: host paused ({host})")
                sleep_for = min(sleep_for, left)
            if cancel is not None:
                sleep_for = min(sleep_for, _CANCEL_POLL_SEC)
            time.sleep(max(0.01, sleep_for))

    def _pace(
        self, host: str, kind: str, deadline: float | None, cancel: Any = None
    ) -> None:
        _, interval = self._limits_for(host, kind)
        if interval <= 0:
            return
        while True:
            if _is_cancelled(cancel):
                self._raise_cancelled("while pacing", host=host)
            with self._mu:
                now = time.monotonic()
                nxt = float(self._next_at.get(host) or 0.0)
                if now >= nxt:
                    self._next_at[host] = now + interval
                    return
                wait = nxt - now
            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise OutboundBusy(f"outbound busy: pacing host={host}")
                wait = min(wait, left)
            if cancel is not None:
                wait = min(wait, _CANCEL_POLL_SEC)
            time.sleep(max(0.001, wait))

    def note_status(self, url: str, status: int) -> None:
        """429/503：整 host 短暂退避，其它 host 继续。"""
        if status not in {429, 503}:
            return
        host = self.host_key(url)
        # Retry-After 未知时：0.8～2.2s + jitter
        delay = 0.8 + random.random() * 1.4
        until = time.monotonic() + delay
        with self._mu:
            prev = float(self._paused_until.get(host) or 0.0)
            self._paused_until[host] = max(prev, until)
        log.info("outbound throttle host=%s status=%s pause=%.2fs", host, status, delay)

    def note_retry_after(self, url: str, seconds: float) -> None:
        host = self.host_key(url)
        delay = max(0.2, min(30.0, float(seconds or 0)))
        until = time.monotonic() + delay
        with self._mu:
            prev = float(self._paused_until.get(host) or 0.0)
            self._paused_until[host] = max(prev, until)

    @contextmanager
    def slot(
        self,
        url: str,
        *,
        kind: str = "page",
        timeout: float | None = 60.0,
        cancel: Any = None,
    ) -> Iterator[None]:
        """占用出站槽：先 pacing/pause（不占槽），再 global → host。

        cancel：可选取消令牌（threading.Event）。置位后立即放弃等槽并抛
        `OutboundCancelled` —— 用于源早停/暂停后回收「僵尸在飞请求」：
        它们若继续排队，等到槽位后会真发一次请求，把 page 全局槽
        （默认 20）从活番号手里抢走，表现为越刮越慢 + 假超时失败。

        等槽超时抛 `OutboundBusy`（`TimeoutError` 子类）：语义是「排队没轮到」，
        **不是**源故障；同时会把耗时记进线程的 `SlotWaitMeter`（若已绑定），
        供调用方用「墙钟 − 等槽」判真正的源超时。
        """
        host = self.host_key(url)
        kind_n = str(kind or "page").strip().lower() or "page"
        if kind_n not in _KIND_HOST:
            kind_n = "page"
        deadline = (
            None if timeout is None else (time.monotonic() + max(0.5, float(timeout)))
        )
        to_s = "-" if timeout is None else f"{float(timeout):.1f}s"

        # 等槽记账：从进入 slot() 到拿到槽为止都算「没在发请求」
        meter = thread_slot_meter()
        t_wait0 = time.monotonic()
        settled = False
        if meter is not None:
            meter.waiting_since = t_wait0

        def _settle(count_acquired: bool) -> None:
            nonlocal settled
            if settled:
                return
            settled = True
            if meter is None:
                return
            meter.total += max(0.0, time.monotonic() - t_wait0)
            meter.waiting_since = 0.0
            if count_acquired:
                meter.acquired += 1

        try:
            self._wait_pause(host, deadline, cancel)
            self._pace(host, kind_n, deadline, cancel)

            def _acquire(sem: threading.Semaphore, what: str) -> None:
                if cancel is None:
                    # 无令牌：保持原语义（无限等 / 一次性按 deadline 等）
                    if deadline is None:
                        sem.acquire()
                        return
                    left = deadline - time.monotonic()
                    if left <= 0 or not sem.acquire(timeout=left):
                        raise OutboundBusy(
                            f"outbound busy: no {what} slot ({to_s}) "
                            f"kind={kind_n} host={host}"
                        )
                    return
                # 有令牌：短轮询，取消优先于抢槽
                while True:
                    if _is_cancelled(cancel):
                        self._raise_cancelled(
                            f"waiting {what}", kind=kind_n, host=host
                        )
                    left = None if deadline is None else deadline - time.monotonic()
                    if left is not None and left <= 0:
                        raise OutboundBusy(
                            f"outbound busy: no {what} slot ({to_s}) "
                            f"kind={kind_n} host={host}"
                        )
                    step = _CANCEL_POLL_SEC if left is None else min(
                        _CANCEL_POLL_SEC, left
                    )
                    if sem.acquire(timeout=step):
                        return

            g_sem = self._globals.get(kind_n) or self._globals["page"]
            _acquire(g_sem, "global")
            host_sem = self._host_sem(host, kind_n)
            try:
                _acquire(host_sem, "host")
            except Exception:
                g_sem.release()
                raise
            _settle(True)
            try:
                # 拿到槽后再验一次：从「拿到 global」到「拿到 host」之间可能已被取消，
                # 此时放掉槽直接退出，别浪费这次请求。
                if _is_cancelled(cancel):
                    self._raise_cancelled("after acquire", kind=kind_n, host=host)
                yield
            finally:
                host_sem.release()
                g_sem.release()
        except OutboundBusy:
            # 记账「排队预算耗尽」：源侧常把异常吞掉（`except Exception: return None`），
            # 只有这里留下的痕迹能证明「这次请求压根没发出去」。
            if meter is not None:
                meter.slot_timeout = int(meter.slot_timeout) + 1
            raise
        finally:
            _settle(False)

    def shared_client(
        self,
        *,
        proxy: str | None = None,
        verify: bool = False,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Client:
        """长寿命 Client（连接复用）。按 proxy/verify 分桶。"""
        proxy_s = str(proxy or "").strip()
        key = f"{'p' if proxy_s else 'd'}|{1 if verify else 0}|{proxy_s}"
        with self._client_mu:
            hit = self._clients.get(key)
            if hit is not None:
                return hit
            opts: dict[str, Any] = {
                "trust_env": False,
                "follow_redirects": True,
                "verify": verify,
                "timeout": timeout
                or httpx.Timeout(12.0, connect=3.0),
                "limits": httpx.Limits(
                    max_connections=max(24, sum(_KIND_GLOBAL.values()) + 4),
                    max_keepalive_connections=20,
                ),
            }
            if proxy_s:
                opts["proxy"] = proxy_s
            client = httpx.Client(**opts)
            self._clients[key] = client
            return client

    def _note_cancelled(self) -> None:
        with self._mu:
            self._cancelled_n = int(self._cancelled_n) + 1

    def stats(self) -> dict[str, Any]:
        with self._mu:
            paused = {
                h: max(0.0, u - time.monotonic())
                for h, u in self._paused_until.items()
                if u > time.monotonic()
            }
            return {
                "kindGlobal": dict(_KIND_GLOBAL),
                "hostGates": len(self._host_sems),
                "pausedHosts": paused,
                "clients": len(self._clients),
                "cancelledWaiters": int(self._cancelled_n),
            }


_scheduler: OutboundScheduler | None = None
_scheduler_mu = threading.Lock()


def get_scheduler() -> OutboundScheduler:
    global _scheduler
    with _scheduler_mu:
        if _scheduler is None:
            _scheduler = OutboundScheduler()
        return _scheduler


def reset_scheduler_for_tests() -> None:
    """单测用：关掉共享 Client，重建调度器。"""
    global _scheduler
    with _scheduler_mu:
        old = _scheduler
        _scheduler = None
    if old is not None:
        with old._client_mu:
            for c in list(old._clients.values()):
                try:
                    c.close()
                except Exception:  # noqa: BLE001
                    pass
            old._clients.clear()
