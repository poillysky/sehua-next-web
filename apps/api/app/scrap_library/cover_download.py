# -*- coding: utf-8 -*-
"""封面最终版下载：字段优先池 → URL 升级 → 并发打分早停 → 分区裁切 → 原尺寸落盘。

对齐 COVER_LOGIC.md 最终版。
"""

from __future__ import annotations

import io
import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

log = logging.getLogger(__name__)

# 低质量源殿后（全局池排序时压到末尾）
_LOW_QUALITY_SOURCES = frozenset(
    {
        "miss_av",
        "javday",
        "njav",
        "freejavbt",
        "sevenmmtv",
        "avsox",
        "avmoo",
    }
)
# 兜底源：优先池不够时，全局补充必须至少留 1 席（否则被 jav321 等慢 CDN 挤掉）
_FALLBACK_COVER_SOURCES = frozenset(
    {
        "miss_av",
        "freejavbt",
        "javday",
        "njav",
        "avsox",
    }
)
# 已知不稳图床：排序殿后 + 短超时（见 cover_focus_routes._is_slow_cover_host）
_UNSTABLE_COVER_HOST_NEEDLES = (
    "jav321.com",
)

# 仅挡图标/追踪像素级废图；有效封面有图即落盘（不再卡 600×800）
MIN_DISK_WIDTH = 32
MIN_DISK_HEIGHT = 32

# 覆盖旧图：新分至少高这么多
SCORE_OVERWRITE_DELTA = 5.0

# 优先池最高分达到此值且能落盘 → 不再补全局（与批量 early_score 对齐）
# 旧值 85 导致 80 分早停后仍打全局，封面互相挤槽、越跑越慢
PRIORITY_GOOD_ENOUGH = 78.0
# 从全局池额外补试的 URL 数（优先池不够用时；含 1 席兜底源）
GLOBAL_SUPPLEMENT_N = 3
# 已有合格候选且尝试次数达到此值 → 强制收工（少打低质尾部）
FORCE_STOP_AFTER_TRIES = 3


def _host_unstable(url: str) -> bool:
    u = (url or "").lower()
    return any(n in u for n in _UNSTABLE_COVER_HOST_NEEDLES)


def pick_global_supplement(
    global_pool: list[dict[str, str]],
    *,
    used: set[str],
    take_n: int,
) -> list[dict[str, str]]:
    """全局补充：沿用池内排序（调用方已把不稳 CDN 殿后），并强制留 1 席兜底源。

    素人 e2e：jav321 CDN 超时后 miss_av 有 poster 却从未被试 —— 因其
    `_LOW_QUALITY` 排到 900，而 GLOBAL_SUPPLEMENT 只取前 2 个高优 URL。

    席位规则：非兜底源先占 n-1，最后一席优先 `miss_av`，再及其它
    `_FALLBACK_COVER_SOURCES`（避免 freejavbt 占兜底席却仍把 miss_av 挤掉）。
    """
    n = max(0, int(take_n))
    if n <= 0 or not global_pool:
        return []
    avail = [
        e
        for e in global_pool
        if str(e.get("url") or "").strip()
        and str(e.get("url") or "").strip() not in used
    ]
    if not avail:
        return []

    def _sid(e: dict[str, str]) -> str:
        return str(e.get("source") or "").strip().lower()

    reserved: dict[str, str] | None = None
    if n >= 2:
        # 优先 miss_av，再按 FALLBACK 集合出现顺序
        prefer = ("miss_av",) + tuple(
            s for s in sorted(_FALLBACK_COVER_SOURCES) if s != "miss_av"
        )
        for want in prefer:
            for e in avail:
                if _sid(e) == want:
                    reserved = e
                    break
            if reserved is not None:
                break

    primary = [e for e in avail if e is not reserved]
    room = n - (1 if reserved is not None else 0)
    out = list(primary[: max(0, room)])
    if reserved is not None:
        out.append(reserved)
    return out[:n]

# 封面池并发（批量模式）。第十八轮实测（2026-09-17）：
#   `coverMs` p50=4033 / p90=4037 / max=15053 —— 平台状分布 = **波次结构**，不是图慢。
#   单独实测 DMM 封面 `pics.dmm.co.jp/.../{cid}pl.jpg` 成功 p50=752ms（10/10 命中），
#   所以 4s 平台 = ceil(5 候选 / 2 路) = 3 波 × ~1.34s。
# 取值 4 的依据（不是拍脑袋）：
#   - `ceil(5 候选 / 4 路) = 2 波`，是压到 2 波的最小取值（取 3 是 2 波但更慢）。
#   - 取 5 收益被主机信号量吃掉：DMM `pics.dmm.co.jp` `per_host=4`，第 5 路会排在
#     主机信号量上，墙钟不变却多占一个全局槽 → 只增加 slot_blocked 风险。
#   - 封面全局槽**不再是写死的 20**：第十九轮起由
#     `outbound_scheduler.cover_cap_for_item_workers()` = ceil(itemWorkers × 本常量 × 余量)
#     推导（余量见 `outbound_scheduler.COVER_SLOT_HEADROOM`；第二十一轮由 1.25 调到 1.5，
#     基线 4×4×1.5 = 24）。**改本常量会自动同步槽位**，别再去手工改
#     `_KIND_GLOBAL["cover"]` —— 那正是第十九轮修掉的坑。
COVER_BATCH_WORKERS = 4
# 单刷（非批量）保持 6：无并发同伴，多开只增加站点压力。
COVER_SINGLE_WORKERS = 6

# 抢槽超时（秒）= `outbound_scheduler.slot(..., kind="cover", timeout=…)` 的上限，
# 即「抢不到 cover 全局槽时最多干等多久」。
#
# ⚠️ 第二十一轮修正：原为 batch 5.0 / single 6.0，与下层 `_fetch_bytes_for_enrich`
# 的 docstring **直接冲突** —— 那里明写「timeout 为抢槽上限（批量应传 1～3s，
# 勿再等 45s 把封面预算拖死）」。现场取证（报告 §二十一）：
# 封面阶段 7~15s，而 5 候选 / 4 路 = **2 波**，2 × 5.0s = 10s 是**纯抢槽干等** ——
# coverMs 的平台状分布就是这么来的，跟图床快慢无关。
# 抢不到槽的正确反应是**尽快换下一条 URL**（`_fetch` 已把 slot_blocked 实现为换候选），
# 不是原地等满：等得越久全局槽越回不来（正反馈恶化）。
# 抽成模块常量是为了**可被测试锁定** —— 它当年悄悄涨到 5.0 正是因为藏在函数体里。
COVER_SLOT_TIMEOUT_BATCH = 2.0
COVER_SLOT_TIMEOUT_SINGLE = 4.0


def upgrade_cover_urls(url: str) -> list[str]:
    """全局 URL 升级：小图规则 → 大图优先，保留原 URL 兜底。"""
    u = str(url or "").strip()
    if not u:
        return []
    from app.scrap_library.cover_scrape import rewrite_cover_url_for_quality

    cands = list(rewrite_cover_url_for_quality(u, "compact") or [])
    # 显式升级规则（最终版）
    extras: list[str] = []
    for a, b in (
        ("ps.jpg", "pl.jpg"),
        ("/thumbs/", "/covers/"),
        ("/thumb/", "/cover/"),
        ("/thumbs", "/covers"),
        ("/thumb", "/cover"),
        ("_s.jpg", "_b.jpg"),
        ("cover-t.jpg", "cover-n.jpg"),
        ("pb_e_", "pf_e_"),
        ("/pb_", "/pf_"),
    ):
        if a in u:
            extras.append(u.replace(a, b))
    out: list[str] = []
    seen: set[str] = set()
    for x in [*extras, *cands, u]:
        s = str(x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def score_cover_bytes(
    data: bytes,
    *,
    url: str = "",
    source: str = "",
    source_rank: int = 99,
    want_portrait: bool = True,
) -> dict[str, Any]:
    """评分总分 100：分辨率 + 图层 + 源优先级 + 宽高比。"""
    from app.scrap_library.cover_scrape import cover_url_layer, probe_cover_bytes

    info = probe_cover_bytes(data)
    w = int(info.get("width") or 0)
    h = int(info.get("height") or 0)
    blank = bool(info.get("blank"))
    out: dict[str, Any] = {
        "score": 0.0,
        "width": w,
        "height": h,
        "blank": blank,
        "layer": cover_url_layer(url),
        "ok": False,
        "parts": {},
    }
    # 硬空 / 不可读 / NOW PRINTING 一类占位图：直接不合格（勿早停误收）
    if w <= 0 or h <= 0 or blank:
        return out

    # 分辨率 0~40
    if w >= 800 and h >= 1100:
        res = 40.0
    else:
        # 相对目标 800×1100 线性封顶
        res = min(40.0, 40.0 * min(w / 800.0, 1.0) * 0.5 + 40.0 * min(h / 1100.0, 1.0) * 0.5)
        res = max(0.0, min(40.0, res))

    # 来源类型 pl/ps/其它
    layer = str(out["layer"] or "thumb")
    if layer == "pl":
        layer_s = 25.0
    elif layer == "ps":
        layer_s = 12.0
    else:
        layer_s = 5.0

    # 来源信任/优先级 0~20（rank 0 最好）
    rank = max(0, int(source_rank))
    if str(source or "").strip().lower() in _LOW_QUALITY_SOURCES:
        src_s = 0.0
    else:
        src_s = max(0.0, 20.0 - min(20.0, rank * 3.0))

    # 宽高比
    prop = (h / w) if w > 0 else 0.0
    aspect = 0.0
    native_pl_bonus = 0.0
    landscape_boost = 0.0
    if want_portrait:
        # 竖图 1.4~1.6 加分；略竖也给一点
        if 1.4 <= prop <= 1.6:
            aspect = 15.0
        elif prop >= 1.25:
            aspect = 8.0
        elif prop >= 1.05:
            aspect = 3.0
        elif prop < 1.0:
            # 可右裁横图：给基础分，避免 800×538 总停在 ~75 以下
            if w >= 750 and h >= 500 and layer == "pl":
                aspect = 5.0
                landscape_boost = 4.0  # 常见 DMM 横 pl 友好分
            elif w >= 700 and h >= 480:
                aspect = 3.0
        # 原生竖 pl：MDCX 用户最满意，额外加分鼓励早停留竖图
        if prop >= 1.25 and layer == "pl":
            native_pl_bonus = 8.0
    else:
        # 无码/国产/欧美：要横图
        if prop <= 0.85:
            aspect = 15.0
        elif prop < 1.0:
            aspect = 8.0
        else:
            aspect = 0.0  # 竖图本模式会跳过

    total = min(
        100.0, res + layer_s + src_s + aspect + native_pl_bonus + landscape_boost
    )
    out["parts"] = {
        "resolution": round(res, 1),
        "layer": layer_s,
        "source": round(src_s, 1),
        "aspect": aspect,
        "nativePlBonus": native_pl_bonus,
        "landscapeBoost": landscape_boost,
    }
    out["score"] = round(total, 1)
    out["ok"] = True
    return out


def meets_disk_min_size(width: int, height: int) -> bool:
    """落盘门槛：宽高均 ≥32（挡 1×1/图标）；有有效像素即允许落盘。"""
    return int(width or 0) >= MIN_DISK_WIDTH and int(height or 0) >= MIN_DISK_HEIGHT


def meets_processed_min_size(width: int, height: int) -> bool:
    """处理后地板：与落盘门槛一致，有图即收。"""
    return meets_disk_min_size(width, height)


def score_local_poster(path: Path, *, want_portrait: bool = True) -> float:
    """给已落盘 poster 打分，供覆盖比较。"""
    try:
        raw = path.read_bytes()
    except OSError:
        return -1.0
    if not raw:
        return -1.0
    info = score_cover_bytes(
        raw, url=path.name, source="local", source_rank=50, want_portrait=want_portrait
    )
    return float(info.get("score") or -1.0)


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower() or "_"
    except Exception:
        return "_"


def download_best_cover(
    folder: Path,
    entries: list[dict[str, str]],
    *,
    region: str = "",
    overwrite: bool = False,
    batch_mode: bool = False,
    field_priority: list[str] | None = None,
    region_sources: list[str] | None = None,
    cover_cfg: dict[str, Any] | None = None,
    log_fn: Callable[[str], None] | None = None,
    beat_fn: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """最终版封面下载主流程。

    entries: [{source, url}, ...]
    """
    from app.scrap_library import embed as embed_svc
    from app.scrap_library.cover_scrape import (
        cover_aspect_kind,
        cover_crop_for_region,
        normalize_cover_settings,
        process_cover_bytes,
        probe_cover_bytes,
    )

    def _log(msg: str) -> None:
        if log_fn:
            try:
                log_fn(msg)
            except Exception:  # noqa: BLE001
                pass

    def _beat() -> None:
        if beat_fn:
            try:
                beat_fn()
            except Exception:  # noqa: BLE001
                pass

    empty: dict[str, Any] = {
        "poster": "",
        "thumb": "",
        "tried": [],
        "attempts": [],
        "ok": False,
        "failReason": "no_candidates",
        "keptOld": False,
        "mode": "",
        "score": 0,
    }

    cfg = normalize_cover_settings(cover_cfg or {})
    crop_ratio = str(cfg.get("cropRatio") or "full")
    crop_mode = cover_crop_for_region(region, cfg)
    if crop_mode not in ("right", "face", "none"):
        crop_mode = "right"
    want_portrait = crop_mode in ("right", "face")
    empty["mode"] = crop_mode

    workers = COVER_BATCH_WORKERS if batch_mode else COVER_SINGLE_WORKERS
    # 抢槽超时：见 `COVER_SLOT_TIMEOUT_BATCH` / `_SINGLE` 上方说明。
    url_timeout = (
        COVER_SLOT_TIMEOUT_BATCH if batch_mode else COVER_SLOT_TIMEOUT_SINGLE
    )
    # 批量 78 / 单刷 75：对常见 DMM 横 pl（抬分后约 80+）更友好
    early_score = 78.0 if batch_mode else 75.0
    max_urls = 5 if batch_mode else 6

    poster_file = folder / "poster.jpg"
    existing_ok = False
    old_score = -1.0
    try:
        if poster_file.is_file() and not embed_svc._is_blank_cover_file(poster_file):  # noqa: SLF001
            existing_ok = True
            old_score = score_local_poster(poster_file, want_portrait=want_portrait)
    except Exception:  # noqa: BLE001
        existing_ok = False

    if existing_ok and not overwrite:
        # 仍允许更高分覆盖；先跑下载，最后比较
        pass

    # ---- 展开 + URL 升级 ----
    fp = [str(x).strip().lower() for x in (field_priority or []) if str(x).strip()]
    rs = [str(x).strip().lower() for x in (region_sources or []) if str(x).strip()]
    fp_rank = {sid: i for i, sid in enumerate(fp)}
    rs_rank = {sid: i for i, sid in enumerate(rs)}

    expanded: list[dict[str, str]] = []
    seen: set[str] = set()
    for ent in entries or []:
        if not isinstance(ent, dict):
            continue
        src = str(ent.get("source") or "").strip().lower()
        raw_u = str(ent.get("url") or "").strip()
        if not raw_u:
            continue
        for u in upgrade_cover_urls(raw_u):
            if u in seen:
                continue
            # http 有同 path https 时丢 http；反过来（http 先到）也要把 https
            # 形式占位，否则同一个图会以 http/https 两条身份各拉一次。
            if u.startswith("http://"):
                https_u = "https://" + u[len("http://") :]
                if https_u in seen:
                    continue
                seen.add(https_u)
            seen.add(u)
            expanded.append({"source": src, "url": u})

    if not expanded:
        if existing_ok:
            rel = embed_svc._media_rel(poster_file)  # noqa: SLF001
            return {
                **empty,
                "poster": rel or "",
                "ok": True,
                "keptOld": True,
                "failReason": "no_candidates",
                "score": old_score,
            }
        return empty

    def _src_rank(sid: str) -> int:
        s = str(sid or "").strip().lower()
        if s in fp_rank:
            return int(fp_rank[s])
        if s in rs_rank:
            return 100 + int(rs_rank[s])
        if s in _LOW_QUALITY_SOURCES:
            return 900
        return 500

    def _sort_key(e: dict[str, str]) -> tuple[int, int, int, str]:
        from app.scrap_library.cover_scrape import cover_url_layer

        u = e.get("url") or ""
        layer = cover_url_layer(u)
        layer_i = 0 if layer == "pl" else (1 if layer == "ps" else 2)
        unstable = 1 if _host_unstable(u) else 0
        return (unstable, _src_rank(e.get("source") or ""), layer_i, u)

    # 优先池 / 全局池
    if fp:
        priority = [e for e in expanded if (e.get("source") or "").lower() in fp_rank]
        global_pool = [
            e for e in expanded if (e.get("source") or "").lower() not in fp_rank
        ]
    else:
        priority = []
        global_pool = list(expanded)

    priority.sort(key=_sort_key)
    global_pool.sort(key=_sort_key)

    attempts: list[dict[str, Any]] = []
    tried: list[str] = []
    # 仅「真实拉取失败」累计；抢槽超时绝不封 host（否则一堵全军覆没）
    host_fail_n: dict[str, int] = {}
    HOST_FAIL_BLOCK = 3

    def _note(**kw: Any) -> None:
        attempts.append(dict(kw))

    def _fetch(url: str) -> tuple[bytes | None, dict[str, Any]]:
        host = _host_of(url)
        if int(host_fail_n.get(host) or 0) >= HOST_FAIL_BLOCK:
            return None, {"reason": "host_blocked", "elapsedMs": 0, "slotWait": False}
        t0 = time.perf_counter()
        try:
            got = embed_svc._fetch_cover_bytes(url, slot_timeout=url_timeout)  # noqa: SLF001
        except TimeoutError:
            # 槽位忙：换下一条 URL，不要拉黑整个图床
            ms = int((time.perf_counter() - t0) * 1000)
            return None, {
                "reason": "slot_blocked",
                "elapsedMs": ms,
                "slotWait": True,
            }
        except Exception:  # noqa: BLE001
            ms = int((time.perf_counter() - t0) * 1000)
            host_fail_n[host] = int(host_fail_n.get(host) or 0) + 1
            return None, {"reason": "download", "elapsedMs": ms, "slotWait": False}
        ms = int((time.perf_counter() - t0) * 1000)
        if not got:
            host_fail_n[host] = int(host_fail_n.get(host) or 0) + 1
            return None, {"reason": "download", "elapsedMs": ms, "slotWait": False}
        raw, ctype = got
        if "png" in (ctype or "").lower() or "webp" in (ctype or "").lower():
            try:
                from PIL import Image

                im = Image.open(io.BytesIO(raw))
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                elif im.mode == "L":
                    im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=90, optimize=True)
                raw = buf.getvalue()
            except Exception:  # noqa: BLE001
                pass
        try:
            # 占位空图（含较大 NOW PRINTING）一律丢弃，避免 80 分早停掐死其它源
            if embed_svc._is_blank_cover_bytes(raw):  # noqa: SLF001
                return None, {
                    "reason": "blank",
                    "elapsedMs": ms,
                    "slotWait": False,
                }
        except Exception:  # noqa: BLE001
            pass
        # 成功则清零该 host 失败计数
        if host in host_fail_n:
            host_fail_n[host] = 0
        meta = probe_cover_bytes(raw)
        meta["elapsedMs"] = ms
        meta["slotWait"] = False
        return raw, meta

    def _commit(raw: bytes, *, src_url: str, score: float) -> str | None:
        # none 模式拒绝竖图
        probe = probe_cover_bytes(raw)
        w, h = int(probe.get("width") or 0), int(probe.get("height") or 0)
        kind = cover_aspect_kind(w, h)
        if crop_mode == "none" and kind == "portrait":
            _note(
                url=src_url,
                status="reject",
                reason="portrait_skip",
                width=w,
                height=h,
                score=score,
            )
            return None
        # 最小尺寸看「裁切前」源图（仅挡图标级；有有效像素即落盘）
        if not meets_disk_min_size(w, h):
            _note(
                url=src_url,
                status="reject",
                reason="too_small",
                width=w,
                height=h,
                score=score,
            )
            return None
        # 横图才裁；竖图 process 内也会原样
        mode = crop_mode
        if want_portrait and kind in ("portrait", "square"):
            mode = "none"  # 原生竖图不裁
        poster_data = process_cover_bytes(
            raw,
            crop_mode=mode,
            quality="compact",
            crop_ratio=crop_ratio,
        )
        after = probe_cover_bytes(poster_data)
        aw, ah = int(after.get("width") or 0), int(after.get("height") or 0)
        # 裁后只挡空图/极小字节；不再卡分辨率
        if not meets_processed_min_size(aw, ah) or len(poster_data or b"") < 256:
            _note(
                url=src_url,
                status="reject",
                reason="blank_or_bad",
                width=aw,
                height=ah,
                score=score,
            )
            return None
        # 裁后仍判空图 → 拒绝（不再用体积豁免，否则占位图会假成功）
        try:
            after_blank = bool(after.get("blank")) or embed_svc._is_blank_cover_bytes(  # noqa: SLF001
                poster_data
            )
        except Exception:  # noqa: BLE001
            after_blank = bool(after.get("blank"))
        if after_blank:
            _note(
                url=src_url,
                status="reject",
                reason="blank_or_bad",
                width=aw,
                height=ah,
                score=score,
            )
            return None
        # 覆盖门槛
        if existing_ok and not overwrite:
            if score < old_score + SCORE_OVERWRITE_DELTA:
                _note(
                    url=src_url,
                    status="skip",
                    reason="score_not_better",
                    width=aw,
                    height=ah,
                    score=score,
                    oldScore=old_score,
                )
                return None
        dest = embed_svc._write_poster_jpg(folder, poster_data)  # noqa: SLF001
        if not dest:
            # 空白启发式误伤时直接写盘（尺寸已过门禁）
            try:
                if not folder.is_dir():
                    folder.mkdir(parents=True, exist_ok=True)
                dest_p = folder / "poster.jpg"
                tmp = folder / "poster.jpg.part"
                tmp.write_bytes(poster_data)
                tmp.replace(dest_p)
                dest = dest_p
            except OSError:
                dest = None
        if not dest:
            _note(url=src_url, status="reject", reason="write_fail", score=score)
            return None
        # 落盘后再验：占位图不得算成功（否则会 early_stop 掐死其它源）
        try:
            dest_p = Path(dest)
            if dest_p.is_file() and embed_svc._is_blank_cover_file(dest_p):  # noqa: SLF001
                dest_p.unlink(missing_ok=True)
                _note(
                    url=src_url,
                    status="reject",
                    reason="blank_or_bad",
                    width=aw,
                    height=ah,
                    score=score,
                )
                return None
        except Exception:  # noqa: BLE001
            pass
        # 只留 poster.jpg
        for name in ("thumb.jpg", "fanart.jpg", "landscape.jpg", "cover.jpg", "folder.jpg"):
            p = folder / name
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass
        rel = embed_svc._media_rel(dest)  # noqa: SLF001
        if not rel and Path(dest).is_file():
            rel = Path(dest).as_posix()
        return rel or None

    def _run_pool(
        pool_name: str, pool_entries: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        """并发打分；返回合格候选（含 raw），不落盘。"""
        if not pool_entries:
            return []
        _log(f"cover.pool · {pool_name} · n={len(pool_entries)} · workers={workers}")

        scored: list[dict[str, Any]] = []
        stop = False

        def _one(ent: dict[str, str]) -> dict[str, Any]:
            url = str(ent.get("url") or "")
            src = str(ent.get("source") or "")
            tried.append(url)
            raw, meta = _fetch(url)
            elapsed = int(meta.get("elapsedMs") or 0)
            if raw is None:
                reason = str(meta.get("reason") or "download")
                return {
                    "url": url,
                    "source": src,
                    "ok": False,
                    "reason": reason,
                    "elapsedMs": elapsed,
                    "slotWait": bool(meta.get("slotWait")),
                }
            sc = score_cover_bytes(
                raw,
                url=url,
                source=src,
                source_rank=_src_rank(src),
                want_portrait=want_portrait,
            )
            # none：竖图直接不合格
            if not want_portrait:
                kind = cover_aspect_kind(
                    int(sc.get("width") or 0), int(sc.get("height") or 0)
                )
                if kind == "portrait":
                    return {
                        "url": url,
                        "source": src,
                        "ok": False,
                        "reason": "portrait_skip",
                        "score": sc.get("score"),
                        "width": sc.get("width"),
                        "height": sc.get("height"),
                    }
            if not sc.get("ok"):
                return {
                    "url": url,
                    "source": src,
                    "ok": False,
                    "reason": "probe_fail",
                }
            return {
                "url": url,
                "source": src,
                "ok": True,
                "raw": raw,
                "score": float(sc.get("score") or 0),
                "width": sc.get("width"),
                "height": sc.get("height"),
                "parts": sc.get("parts"),
                "elapsedMs": elapsed,
            }

        n = max(1, min(workers, len(pool_entries)))
        from app.core.container_budget import cap_parallel

        n = cap_parallel(n, tight=2, small=3, hard=max(n, 1)) or 1
        finished = 0
        with ThreadPoolExecutor(max_workers=n, thread_name_prefix="cover-dl") as ex:
            futs = {ex.submit(_one, e): e for e in pool_entries}
            pending = set(futs.keys())
            while pending and not stop:
                done, pending = wait(
                    pending, timeout=0.35, return_when=FIRST_COMPLETED
                )
                if not done:
                    _beat()
                    continue
                _beat()
                for fut in done:
                    finished += 1
                    try:
                        row = fut.result()
                    except Exception as e:  # noqa: BLE001
                        _note(url="", status="fail", reason=str(e)[:80], pool=pool_name)
                        continue
                    url = str(row.get("url") or "")
                    if not row.get("ok"):
                        _note(
                            url=url,
                            source=str(row.get("source") or ""),
                            status="fail",
                            reason=str(row.get("reason") or "fail"),
                            pool=pool_name,
                            score=row.get("score"),
                            width=row.get("width"),
                            height=row.get("height"),
                            elapsedMs=row.get("elapsedMs"),
                            slotWait=row.get("slotWait"),
                        )
                        continue
                    score = float(row.get("score") or 0)
                    _note(
                        url=url,
                        source=str(row.get("source") or ""),
                        status="ok",
                        reason="",
                        pool=pool_name,
                        score=score,
                        width=row.get("width"),
                        height=row.get("height"),
                        elapsedMs=row.get("elapsedMs"),
                    )
                    scored.append(row)
                    disk_ok = meets_disk_min_size(
                        int(row.get("width") or 0), int(row.get("height") or 0)
                    )
                    if score >= early_score and disk_ok:
                        stop = True
                        _log(f"cover.early_stop · score={score} · {url[:80]}")
                        break
                    # 「合格」= 能过落盘最小尺寸；完成数≥4 才强制收工（勿用 tried，提交即计数会误杀 pl）
                    if (
                        disk_ok
                        and finished >= FORCE_STOP_AFTER_TRIES
                        and any(
                            meets_disk_min_size(
                                int(x.get("width") or 0), int(x.get("height") or 0)
                            )
                            for x in scored
                        )
                    ):
                        stop = True
                        _log(
                            f"cover.force_stop · finished={finished} · "
                            f"best={max(float(x.get('score') or 0) for x in scored)}"
                        )
                        break
                if stop:
                    for f in list(pending):
                        f.cancel()
                    try:
                        ex.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        pass
                    break

        # 能落盘的排前面，再按分数
        scored.sort(
            key=lambda r: (
                1
                if meets_disk_min_size(
                    int(r.get("width") or 0), int(r.get("height") or 0)
                )
                else 0,
                float(r.get("score") or 0),
            ),
            reverse=True,
        )
        return scored

    def _commit_best(scored: list[dict[str, Any]]) -> dict[str, Any] | None:
        for best in scored:
            rel = _commit(
                best["raw"],
                src_url=str(best.get("url") or ""),
                score=float(best.get("score") or 0),
            )
            if not rel:
                continue
            src = str(best.get("source") or "").strip()
            _log(
                f"cover.commit · source={src or '?'} · score={best.get('score')} · "
                f"url={str(best.get('url') or '')[:80]}"
            )
            return {
                "poster": rel,
                "thumb": "",
                "tried": list(tried),
                "attempts": list(attempts),
                "ok": True,
                "failReason": "",
                "keptOld": False,
                "mode": crop_mode,
                "score": float(best.get("score") or 0),
                "coverSource": src,
            }
        return None

    _log(
        f"cover.pick · mode={crop_mode} · early>={early_score} · "
        f"goodEnough>={PRIORITY_GOOD_ENOUGH} · candidates={len(expanded)}"
    )

    # 1) 优先池先跑；无字段优先时直接走全局
    all_scored: list[dict[str, Any]] = []
    if priority:
        pri_budget = min(max_urls, len(priority))
        all_scored.extend(_run_pool("priority", priority[:pri_budget]))
        # 池内已早停/够分且能落盘 → 立刻提交，禁止再打全局（越跑越慢主因）
        if all_scored:
            top = all_scored[0]
            top_score = float(top.get("score") or 0)
            top_ok = meets_disk_min_size(
                int(top.get("width") or 0), int(top.get("height") or 0)
            )
            if top_score >= early_score and top_ok:
                got_early = _commit_best(all_scored)
                if got_early and got_early.get("ok"):
                    _log(
                        f"cover.pool · commit early · score={top_score} · "
                        f"skip global"
                    )
                    return got_early
    elif global_pool:
        # 无字段优先：同样用稳定优先 + 兜底席，避免一上来全打 jav321
        take = pick_global_supplement(
            global_pool,
            used=set(),
            take_n=min(max_urls, len(global_pool)),
        )
        all_scored.extend(_run_pool("global", take))

    best_pri = float(all_scored[0]["score"]) if all_scored else -1.0
    best_disk_ok = bool(
        all_scored
        and meets_disk_min_size(
            int(all_scored[0].get("width") or 0),
            int(all_scored[0].get("height") or 0),
        )
    )
    need_more = True
    if priority and all_scored and best_pri >= PRIORITY_GOOD_ENOUGH and best_disk_ok:
        need_more = False
        _log(f"cover.pool · priority good enough · score={best_pri}")
    elif priority and all_scored and best_pri >= early_score and best_disk_ok:
        need_more = False
        _log(f"cover.pool · early skip global · score={best_pri}")
    elif not priority:
        # 已无字段优先，上面已跑全局
        need_more = False
    elif all_scored and best_pri >= early_score and best_disk_ok and not global_pool:
        need_more = False
    elif best_disk_ok and len(attempts) >= FORCE_STOP_AFTER_TRIES:
        # 已有能落盘的合格图且完成尝试够多 → 不再补全局
        need_more = False
        _log(
            f"cover.pool · force skip global · attempts={len(attempts)} · "
            f"priBest={best_pri}"
        )

    # 2) 优先池不够分/全灭 → 少量补全局
    if need_more and global_pool:
        used = {str(x.get("url") or "") for x in all_scored}
        used.update(tried)
        # ⚠️ 这里**不能用** `remain_budget = max_urls - len(tried)` 限额：
        # `tried` 里全是「已经花掉的尝试」（含失败），字段优先级配了 ≥max_urls
        # 个源时它必然被占满 → remain_budget 恒为 0 → 全局池永远拿不到机会。
        # 而走到 need_more 就说明优先池的结论**不够用**（全灭 / 最高分 <
        # early_score / 尺寸不达标 —— 上面每条 need_more=False 分支都要求
        # best_pri>=early_score 且 best_disk_ok），此时补全局是净收益：
        # 本可拿够分的全局源会被白白跳过，出中分封面甚至直接失败。
        # 所以只保留 GLOBAL_SUPPLEMENT_N 这个硬上限；且强制留 1 席兜底源。
        take_n = min(GLOBAL_SUPPLEMENT_N, len(global_pool))
        supp = pick_global_supplement(global_pool, used=used, take_n=take_n)
        if supp:
            srcs = ",".join(
                sorted({str(e.get("source") or "?") for e in supp})
            )
            _log(
                f"cover.pool · supplement global · n={len(supp)} · "
                f"srcs={srcs} · priBest={best_pri}"
            )
            all_scored.extend(_run_pool("global", supp))
            all_scored.sort(key=lambda r: float(r.get("score") or 0), reverse=True)

    got = _commit_best(all_scored)
    if got and got.get("ok"):
        return got

    # 槽位挤兑导致全空时：清 host 计数、放宽抢槽，再补试未成功的高优 URL
    slot_heavy = sum(
        1
        for a in attempts
        if str(a.get("reason") or "") in {"slot_blocked", "timeout", "host_blocked"}
    )
    if (not all_scored) and slot_heavy >= 2 and expanded:
        host_fail_n.clear()
        # ⚠️ 第二十一轮修正（原为 `url_timeout = max(url_timeout, 7.0)`）：
        # 这里的**抬高方向反了**。`slot_heavy >= 2` 恰恰说明 cover 槽已经不够用，
        # 此时把抢槽超时从 2s 抬到 7s，只会让本番号更久地占着 itemWorker 干等、
        # 并把全局槽继续榨干 —— 现场日志里的 `retry after slot pressure` 正是这条路径。
        # 保持收敛后的短超时（快速失败 + 立刻补试），让出站槽回流给其它在飞番号。
        used = set(tried)
        retry_pool = [e for e in (priority or expanded) if str(e.get("url") or "") not in used]
        if not retry_pool:
            retry_pool = list(expanded)[:4]
        take = min(4, len(retry_pool))
        if take:
            _log(f"cover.pool · retry after slot pressure · n={take}")
            all_scored.extend(_run_pool("retry", retry_pool[:take]))
            all_scored.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
            got = _commit_best(all_scored)
            if got and got.get("ok"):
                return got

    # 全失败：有旧图则 keep
    if existing_ok:
        rel = embed_svc._media_rel(poster_file)  # noqa: SLF001
        _log(f"cover_fail · keep_old · tried={len(tried)}")
        return {
            "poster": rel or "",
            "thumb": "",
            "tried": tried,
            "attempts": attempts,
            "ok": True,
            "failReason": "all_failed",
            "keptOld": True,
            "mode": crop_mode,
            "score": old_score,
        }

    # 汇总失败原因，便于 UI 区分「槽位堵」与「真下不动」
    reason_n: dict[str, int] = {}
    for a in attempts:
        r = str(a.get("reason") or "").strip() or "fail"
        reason_n[r] = int(reason_n.get(r) or 0) + 1
    fail = "all_failed"
    for prefer in (
        "blank",
        "slot_blocked",
        "timeout",
        "download",
        "host_blocked",
        "too_small",
        "write_fail",
    ):
        if reason_n.get(prefer):
            fail = prefer
            break
    if reason_n:
        detail = ",".join(f"{k}:{v}" for k, v in sorted(reason_n.items(), key=lambda x: -x[1])[:4])
        _log(f"cover_fail · {fail} · {detail} · tried={len(tried)}")
    return {
        **empty,
        "tried": tried,
        "attempts": attempts,
        "failReason": fail,
        "mode": crop_mode,
    }
