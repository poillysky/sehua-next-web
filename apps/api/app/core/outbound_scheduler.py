"""出站调度：全局闸 + 按 host 并发/间距 + host 退避（成熟爬虫模型）。

目标：多番号 × 多源 × 封面并发时，跨站并行拉满、同站排队，
避免全局一把锁互踩或抢槽假失败。
"""

from __future__ import annotations

import logging
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


# 进程级：详情与封面分槽，避免 5 路刮详情把封面槽抢光（或反过来）
_KIND_GLOBAL: dict[str, int] = {
    # page 20→24（2026-09-16）：对齐 itemWorkers=4（4×10=40 路，其中 ~16 走 api 槽，
    # page 侧 ≈24 路）—— 供需 1:1，消除排队反噬（并发 10 曾比 5 慢一倍）。
    # ⚠️ 上限逻辑见 §十五：再往上先看 sourceTimings[].waitMs 分布，别拍脑袋。
    "page": 24,
    "cover": 20,
    "ui": 8,
    # 直连 API（JSON / GraphQL / POST 表单）：第十一轮新增。
    # 原来 r18dev / libredmm / dmm / jav321 这些源**根本不走调度器** ——
    # 既不受并发上限约束，也不进 SlotWaitMeter（导致源真超时被误记成 busy）。
    # 上限取 12：够 5 路番号各 2-3 个直连源并行；比 page 小是因为 API 站
    # （r18.dev / api.video.dmm.co.jp）对突发并发比详情页更敏感。
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
