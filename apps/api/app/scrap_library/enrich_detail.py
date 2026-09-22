# -*- coding: utf-8 -*-
"""enrich_detail —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from fastapi import HTTPException
import app.scrap_library.embed as embed_svc
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import get_meta_pool, media_dir
from app.scrap_library import enrich_log_sink
from app.scrap_library.nfo import (
    build_mdcx_nfo_root,
    fields_from_movie_root,
    format_nfo_xml,
    parse_nfo,
    write_nfo,
)
from app.scrap_library import enrich_monitor as enrich_mon

import app.scrap_library.enrich as _enrich
import app.scrap_library.enrich_cover as _enrich_cover
import app.scrap_library.enrich_merge as _enrich_merge
import app.scrap_library.enrich_retry as _enrich_retry
import app.scrap_library.enrich_scan as _enrich_scan
import app.scrap_library.enrich_text as _enrich_text
from app.scrap_library.enrich import (_CN_WAIT_BUDGET_SEC, _GAP_FIELD_PRIORITY_KEYS, _JUNK_TITLE_MARKERS, _META_FILL_SOURCE_IDS, _META_WAIT_BUDGET_SEC, _SOFT_SUCCESS_GAPS, _SOURCE_COOLDOWN_LOCK, _SOURCE_COOLDOWN_UNTIL, _SOURCE_DOWN_STREAK, _SOURCE_WORKERS_MAX, _SUCCESS_BLOCK_GAPS, _cn_text_ids_in_batch, _enrich_job, _enrich_lock, _hydrate_queue_item_from_library, _maybe_llm_fill_zh, _set_progress, log, notify_enrich_watchers)


def _detail_usable(detail: dict[str, Any] | None, *, code: str) -> bool:
    """拒绝登录页/盾页等脏详情，避免写坏 NFO。"""
    if not detail or not isinstance(detail, dict):
        return False
    code_u = str(code or detail.get("code") or "").strip().upper()
    title = str(detail.get("title") or "").strip()
    title_l = title.casefold()
    if not title:
        return False
    if any(m in title_l for m in (x.casefold() for x in _JUNK_TITLE_MARKERS)):
        return False
    if _enrich._title_is_thin(title, code_u) and not (
        detail.get("posterUrl") or detail.get("overview") or _enrich._clean_actors(detail.get("actors"))
    ):
        return False
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    overview = str(detail.get("overview") or "").strip()
    studio = str(detail.get("studio") or detail.get("maker") or "").strip()
    actors = _enrich._clean_actors(detail.get("actors"))
    tags = _enrich_text._clean_tags(detail.get("tags"), fold=False)  # 源侧：勿折叠，保留繁简信息给评分
    code_in_title = bool(code_u) and code_u.casefold() in title_l
    # 至少有一项可用信号
    if poster.startswith(("http://", "https://")):
        return True
    if overview and len(overview) >= 12:
        return True
    if studio and actors:
        return True
    if actors and (code_in_title or len(title) >= 8):
        return True
    if studio and code_in_title and len(title) > len(code_u) + 2:
        return True
    if tags and code_in_title and len(title) > len(code_u) + 2:
        return True
    return False


def _detail_from_local_folder(
    folder: Path,
    *,
    code: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    """从本地番号目录 NFO + poster 生成展示 detail / fields。

    转移进来的 MDCx NFO 与本系统刮削 NFO 同格式；原先详情只认「刮削结果/向量库」，
    且封面必须是 http 才算有 —— 本地 poster.jpg 会被误报成「无」。
    """
    code_u = str(code or folder.name or "").strip().upper()
    local_ok = False
    try:
        local_ok = bool(_enrich_cover._local_poster_ok(folder))
    except Exception:  # noqa: BLE001
        poster = folder / "poster.jpg"
        local_ok = bool(poster.is_file() and poster.stat().st_size >= 400)
    detail: dict[str, Any] = {"code": code_u}
    fields = _fields_after_local_write(
        folder,
        detail,
        local_cover_ok=local_ok,
        poster_url="",
    )
    title = ""
    for f in fields:
        if str(f.get("id") or "") == "title":
            title = str(f.get("value") or "").strip()
            break
    if not title:
        nfo = _find_nfo(folder)
        meta = parse_nfo(nfo) if nfo else None
        if isinstance(meta, dict):
            title = str(meta.get("title") or "").strip()
            code_u = str(meta.get("num") or code_u).strip().upper() or code_u
    out_detail = {
        "code": code_u,
        "title": title,
        "detailTitle": title[:300] if title else "",
        "posterDownloaded": local_ok,
    }
    return out_detail, fields, local_ok


def _backfill_queue_item_detail(item: dict[str, Any], *, region: str) -> dict[str, Any]:
    """成功/失败空壳：从 NFO/元库补字段（只补展示；不覆盖已有源耗时/选用源）。"""
    if not isinstance(item, dict):
        return item
    st = str(item.get("status") or "").strip().lower()
    if st not in {"done", "fail"}:
        return item
    fields = item.get("fields")
    has_fields = isinstance(fields, list) and len(fields) > 0
    has_src_fields = has_fields and any(
        isinstance(f, dict) and str(f.get("source") or "").strip()
        for f in fields
    )
    has_timings = isinstance(item.get("sourceTimings"), list) and bool(
        item.get("sourceTimings")
    )
    title = str(item.get("detailTitle") or "").strip()
    # 已有刮削结果（带选用源或源耗时）→ 不回填、不写库
    if (has_src_fields or has_timings) and title:
        if not has_timings:
            item = _enrich_merge._merge_enrich_sidecar_into_item(item, region=region)
        return item
    # local_scan 空壳：先读番号目录 enrich.log
    if not has_timings:
        item = _enrich_merge._merge_enrich_sidecar_into_item(item, region=region)
        has_timings = isinstance(item.get("sourceTimings"), list) and bool(
            item.get("sourceTimings")
        )
        fields = item.get("fields")
        has_fields = isinstance(fields, list) and len(fields) > 0
        has_src_fields = has_fields and any(
            isinstance(f, dict) and str(f.get("source") or "").strip()
            for f in (fields or [])
        )
        title = str(item.get("detailTitle") or "").strip()
        if (has_src_fields or has_timings) and title:
            return item
    if has_fields and title and not has_src_fields and not has_timings:
        # 仅有 NFO 级字段：仍试本地 enrich.log 补源耗时
        item = _enrich_merge._merge_enrich_sidecar_into_item(item, region=region)
        return item
    hydrated = _hydrate_queue_item_from_library(
        code=str(item.get("code") or ""),
        region=region,
        item_id=str(item.get("itemId") or ""),
    )
    if not hydrated:
        return _enrich_merge._merge_enrich_sidecar_into_item(item, region=region)
    if hydrated.get("detailTitle") and not title:
        item["detailTitle"] = hydrated["detailTitle"]
    if hydrated.get("itemId") and not item.get("itemId"):
        item["itemId"] = hydrated["itemId"]
    # 本步明确跳过向量时，不要用库里「已有向量行」改成已同步
    if item.get("vectorSkipped"):
        item["vectorSynced"] = False
    elif hydrated.get("vectorSynced") is not None and item.get("vectorSynced") is None:
        item["vectorSynced"] = hydrated.get("vectorSynced")
    if not has_fields and hydrated.get("fields"):
        item["fields"] = hydrated["fields"]
    elif (
        hydrated.get("fields")
        and not has_src_fields
        and not has_timings
        and str(item.get("source") or "").strip()
        in {"", "local_scan", "scan", "log_recover", "recover"}
    ):
        # 本地扫描空壳字段（全「无」）用 NFO 覆盖
        item["fields"] = hydrated["fields"]
    if hydrated.get("posterDownloaded"):
        if item.get("posterDownloaded") is None or (
            not has_src_fields and not has_timings
        ):
            item["posterDownloaded"] = hydrated.get("posterDownloaded")
    src = str(item.get("source") or "").strip()
    if src in {"log_recover", "recover"}:
        item["source"] = str(hydrated.get("source") or "").strip()
    # 本地 enrich.log 优先补源耗时（向量/NFO 没有）
    item = _enrich_merge._merge_enrich_sidecar_into_item(item, region=region)
    # 只写回缺失的展示字段；绝不传空 sourceTimings（避免冲掉真结果）
    try:
        persist: dict[str, Any] = {
            "logId": item.get("logId"),
            "itemId": item.get("itemId"),
            "code": item.get("code"),
            "status": st,
            "gaps": list(item.get("gaps") or []),
            "error": item.get("error") or "",
            "source": item.get("source") or "",
            "detailTitle": item.get("detailTitle") or "",
        }
        if item.get("fetchMs") is not None:
            persist["fetchMs"] = item.get("fetchMs")
        if item.get("posterDownloaded") is not None:
            persist["posterDownloaded"] = item.get("posterDownloaded")
        if item.get("vectorSynced") is not None:
            persist["vectorSynced"] = item.get("vectorSynced")
        if item.get("vectorSkipped") is not None:
            persist["vectorSkipped"] = item.get("vectorSkipped")
        if item.get("fields"):
            persist["fields"] = item.get("fields")
        if item.get("sourceTimings"):
            persist["sourceTimings"] = item.get("sourceTimings")
        for k in ("coverMs", "actressMs", "vectorMs", "totalMs"):
            if item.get(k) is not None:
                persist[k] = item.get(k)
        _enrich._queue_log_update_row(persist, region=region)
    except Exception:  # noqa: BLE001
        pass
    return item


def _collect_nfo_folders_parallel(
    dirs: list[Path],
    root: Path,
    *,
    workers: int = 8,
) -> list[tuple[str, Path]]:
    """按前缀目录并行枚举 *.nfo 父目录，返回去重后的 (rel, folder)。"""
    prefixes: list[Path] = []
    for base in dirs:
        try:
            kids = [p for p in base.iterdir() if p.is_dir()]
        except Exception:  # noqa: BLE001
            kids = []
        if kids:
            prefixes.extend(kids)
        else:
            # 分区下无子目录时直接扫 base
            prefixes.append(base)
    if not prefixes:
        return []

    def _scan_prefix(prefix: Path) -> list[tuple[str, Path]]:
        local: list[tuple[str, Path]] = []
        try:
            it = prefix.rglob("*.nfo")
        except Exception:  # noqa: BLE001
            return local
        for nfo in it:
            folder = nfo.parent
            try:
                rel = folder.relative_to(root).as_posix()
            except ValueError:
                continue
            local.append((rel, folder))
        return local

    nw = max(1, min(int(workers or 8), 16, len(prefixes)))
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=nw) as pool:
        for chunk in pool.map(_scan_prefix, prefixes, chunksize=1):
            for rel, folder in chunk:
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                out.append((rel, folder))
    return out


def _classify_disk_gaps(gaps: list[str] | None) -> str:
    """本地缺口 → done / soft / fail。

    缺封面/空标题 → fail；缺女优/片商 → soft；其余（含缺剧情/外链/中文标题）→ done。
    """
    gs = [str(g) for g in (gaps or []) if str(g).strip()]
    if not gs:
        return "done"
    if any(g in _SUCCESS_BLOCK_GAPS for g in gs):
        return "fail"
    if any(g in _SOFT_SUCCESS_GAPS for g in gs):
        return "soft"
    return "done"


def _detail_field_rows(detail: dict[str, Any] | None) -> list[dict[str, Any]]:
    """E2E 风格字段表：是否采到 + 预览值 + 最终选用源。"""
    d = detail if isinstance(detail, dict) else {}
    fs = d.get("fieldSources") if isinstance(d.get("fieldSources"), dict) else {}
    actors = [str(a).strip() for a in (d.get("actors") or []) if str(a).strip()]
    tags = [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()]
    title = str(d.get("title") or "").strip()
    studio = str(d.get("studio") or d.get("maker") or "").strip()
    overview = str(d.get("overview") or "").strip()
    poster = str(d.get("posterUrl") or d.get("poster") or "").strip()
    year = str(d.get("year") or "").strip()
    date_s = str(d.get("date") or "").strip()
    code = str(d.get("code") or d.get("id") or "").strip().upper()

    def src_of(*keys: str) -> str:
        for k in keys:
            v = str(fs.get(k) or "").strip()
            if v:
                return v
        return ""

    def row(
        fid: str,
        label: str,
        ok: bool,
        value: str = "",
        *,
        source: str = "",
    ) -> dict[str, Any]:
        return {
            "id": fid,
            "label": label,
            "ok": bool(ok),
            "value": (value or "")[:120],
            "source": str(source or "").strip(),
        }

    return [
        row("code", "番号", bool(code), code),
        row(
            "title",
            "标题",
            bool(title) and title.casefold() != code.casefold(),
            title,
            source=src_of("title"),
        ),
        row(
            "poster",
            "封面",
            poster.startswith(("http://", "https://")),
            poster if poster.startswith(("http://", "https://")) else (poster or ""),
            source=src_of("poster"),
        ),
        row(
            "actors",
            "女优",
            bool(actors),
            "、".join(actors[:6]),
            source=src_of("actors"),
        ),
        row(
            "studio",
            "片商",
            bool(studio),
            studio,
            source=src_of("studio", "maker"),
        ),
        row(
            "overview",
            "剧情",
            len(overview) >= 12,
            overview[:80],
            source=src_of("overview"),
        ),
        row("year", "年份", bool(year), year, source=src_of("year")),
        row("date", "日期", bool(date_s), date_s, source=src_of("date")),
        row(
            "tags",
            "标签",
            bool(tags),
            "、".join(tags[:8]),
            source=src_of("tags"),
        ),
    ]


def _fields_after_local_write(
    folder: Path,
    detail: dict[str, Any] | None,
    *,
    local_cover_ok: bool,
    poster_url: str = "",
) -> list[dict[str, Any]]:
    """写回后按本地 NFO 刷新字段表，避免早停没采到剧情却误报「缺剧情」。"""
    d = dict(detail) if isinstance(detail, dict) else {}
    nfo = _find_nfo(folder)
    meta = parse_nfo(nfo) if nfo else None
    if isinstance(meta, dict) and meta:
        plot = str(meta.get("plot") or meta.get("overview") or "").strip()
        title = str(meta.get("title") or "").strip()
        studio = str(meta.get("studio") or meta.get("maker") or "").strip()
        actors = [
            str(a).strip()
            for a in (meta.get("actors") or [])
            if str(a or "").strip()
        ]
        tags = [
            str(t).strip()
            for t in (meta.get("genres") or meta.get("tags") or [])
            if str(t or "").strip()
        ]
        cover = str(meta.get("cover_url") or meta.get("cover") or "").strip()
        year = str(meta.get("year") or "").strip()
        date_s = str(
            meta.get("premiered")
            or meta.get("releasedate")
            or meta.get("date")
            or ""
        ).strip()
        code_u = str(meta.get("num") or d.get("code") or folder.name).strip().upper()
        if plot:
            d["overview"] = plot
        if title:
            d["title"] = title
        if studio:
            d["studio"] = studio
        if actors:
            d["actors"] = actors
        if tags:
            d["tags"] = tags
        if cover:
            d["posterUrl"] = cover
        if year:
            d["year"] = year
        if date_s:
            d["date"] = date_s
        if code_u:
            d["code"] = code_u

    fields = _detail_field_rows(d)
    fs = d.get("fieldSources") if isinstance(d.get("fieldSources"), dict) else {}
    poster_src = str((fs or {}).get("poster") or "").strip()
    for f in fields:
        fid = str(f.get("id") or "")
        if fid != "poster":
            if not str(f.get("source") or "").strip():
                alt = "maker" if fid == "studio" else fid
                src = str((fs or {}).get(fid) or (fs or {}).get(alt) or "").strip()
                if src:
                    f["source"] = src
            continue
        if poster_src and not str(f.get("source") or "").strip():
            f["source"] = poster_src
        if local_cover_ok:
            f["ok"] = True
            f["value"] = "已落盘"
        else:
            f["ok"] = False
            remote = str(f.get("value") or poster_url or "").strip()
            f["value"] = (
                f"空图/未落盘 · {remote[:80]}" if remote else "无封面"
            )
    return fields


def _source_in_cooldown(sid: str) -> bool:
    key = str(sid or "").strip().lower()
    if not key:
        return False
    with _SOURCE_COOLDOWN_LOCK:
        until = float(_SOURCE_COOLDOWN_UNTIL.get(key) or 0.0)
    return time.monotonic() < until


def _note_source_fetch_outcome(sid: str, *, kind: str) -> None:
    key = str(sid or "").strip().lower()
    if not key:
        return
    with _SOURCE_COOLDOWN_LOCK:
        if kind == "hit":
            _SOURCE_DOWN_STREAK[key] = 0
            _SOURCE_COOLDOWN_UNTIL.pop(key, None)
            return
        if kind != "down":
            return
        n = int(_SOURCE_DOWN_STREAK.get(key) or 0) + 1
        _SOURCE_DOWN_STREAK[key] = n
        if n >= int(_enrich_retry._SOURCE_COOLDOWN_STREAK):
            _SOURCE_COOLDOWN_UNTIL[key] = time.monotonic() + float(
                _enrich_retry._SOURCE_COOLDOWN_SEC
            )
            _SOURCE_DOWN_STREAK[key] = 0
            log.info(
                "enrich source cooldown sid=%s for %.0fs (down streak)",
                key,
                _enrich_retry._SOURCE_COOLDOWN_SEC,
            )


def _src_give_up_reason(
    *,
    elapsed: float,
    waited: float,
    work_budget: float,
    queue_budget: float,
) -> str:
    """单源放弃判定（纯函数，便于单测锁语义）。返回 ""/「down」/「busy」。

    - 工作耗时 = `elapsed - waited`（墙钟 − 等出站槽/限速/退避）
    - 工作耗时 ≥ 工作预算 → `down`：源真的慢/挂
    - 墙钟 ≥ 工作预算 + 排队预算 → `busy`：一直没轮到发请求，**不是源故障**

    顺序有意义：先判 down 再判 busy —— 若两者都超，说明「确实干活干太久」。
    """
    if elapsed - waited >= work_budget:
        return "down"
    if elapsed >= work_budget + queue_budget:
        return "busy"
    return ""


def _classify_source_failure(err: Any) -> str:
    """源失败四分类：miss（源没这条番号）/ down（源不可用）/ busy（排队未及）/ cancelled（主动放弃）。

    只有 down / busy 才值得补抓；miss 说明源侧确实没有，重抓只是浪费出站槽。
    ⚠️ busy 的语义是「**我们这边**没轮到发请求」（出站槽/限速/退避/过盾通道排满），
    源本身是好的 —— 所以它**不得**计入任何源健康度/退避逻辑，
    但仍要进 `degradedByDown`（高优先源没拿到 = 本轮降级取值，该回头补）。

    另有第五类 **cooldown**（源不健康被主动暂避），**不经过本函数**：
    它在 `_one` 的冷却早退分支上直接产出，由 `_run_pool` 单独归集。
    别把 cooldown 折进 busy —— 那是源健康度结论，busy 不是（见 `_one` 注释）。
    """
    name = err.__class__.__name__ if isinstance(err, BaseException) else ""
    # 类名优先，其次消息标记：中间层可能把异常包成 RuntimeError(str(e)) 丢掉类名
    if name == "OutboundCancelled":
        return "cancelled"
    if name == "OutboundBusy":
        return "busy"
    if isinstance(err, BaseException):
        sc = getattr(err, "status_code", None)
        if isinstance(sc, int):
            if sc in (404, 410):
                return "miss"
            if sc == 429 or sc >= 500:
                return "down"
        s = str(err)
    else:
        s = str(err or "")
    low = s.lower()
    # 排队未及：必须在 "timeout" 之前判 —— OutboundBusy 是 TimeoutError 子类，
    # 消息里也带 timeout，否则会被归成 down。
    if "outbound busy" in low or "排队未及" in s:
        return "busy"
    # 过盾通道排满（curl 直连失败后无 flare 名额）同样是「没轮到」，不是过盾站坏了
    if "繁忙" in s:
        return "busy"
    if "cancel" in low or "取消" in s:
        return "cancelled"
    if "timeout" in low or "timed out" in low or "超时" in s:
        return "down"
    if low.startswith("rejected"):
        # 源页面拿到了但判为不可用（多为别的番号的占位页）→ 源侧没有这条
        return "miss"
    for hint in _enrich_retry._MISS_HINTS:
        if hint in s or hint in low:
            return "miss"
    return "down"


def _safe_local_gaps(folder: Path) -> list[str]:
    """`_local_folder_gaps` 的安全包装（失败时按空处理，不打断流程）。"""
    try:
        _, gaps = _enrich_scan._local_folder_gaps(folder)
        return list(gaps or [])
    except Exception:  # noqa: BLE001
        return []


def _detail_sources(*, region: str = "", code: str = "") -> list[dict[str, Any]]:
    """数据源页：六区对应分组 ∩ 已启用 ∩ 有详情实现，按目录顺序。"""
    import app.scrape.sources_settings as scrape_src

    return list(scrape_src.enabled_enrich_sources(region=region, code=code) or [])


def _identity_gate_details(
    code: str,
    details: list[tuple[str, dict[str, Any]]],
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """身份门禁（对齐 MDCX：不对的整页不进字段池）。

    返回 (kept_details, rejected_source_ids)。
    错页源仍可贡献封面 URL，但清空 title/overview/actors/tags。
    """
    if not details:
        return [], []

    code_u = str(code or "").strip().upper()
    prelim: list[tuple[str, dict[str, Any], bool]] = []
    for sid, d in details:
        dd = dict(d)
        usable = _detail_usable(dd, code=code_u)
        title = str(dd.get("title") or "").strip()
        weak = (not usable) or _enrich._title_is_thin(title, code_u)
        prelim.append((sid, dd, weak))

    title_scores: list[tuple[str, str, int]] = []
    for sid, d, weak in prelim:
        if weak:
            continue
        t = str(d.get("title") or "").strip()
        if not t:
            continue
        title_scores.append(
            (sid, t, _enrich_text._score_title(t, code=code_u, source_id=sid))
        )
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        tzh = str((extra or {}).get("titleZh") or "").strip()
        if tzh and tzh != t:
            title_scores.append(
                (sid, tzh, _enrich_text._score_title(tzh, code=code_u, source_id=sid))
            )

    if len(title_scores) < 2:
        return [(sid, d) for sid, d, _ in prelim], []

    title_scores.sort(key=lambda x: -x[2])
    seed = title_scores[0][1]
    # 簇多数防错页抢锚（RBD-035：airav/airav_io/iqqtv 镜像同一错页且分最高，
    # 旧 seed=纯最高分 → 7 家真源被整批拒、合并锚定到错页片）。
    # 贪心聚簇（按分数序入簇，簇代表=簇内最高分题）；仅当最大簇比种子所在簇
    # 多 ≥2 个源时才改用最大簇内最高分为种子，差距小则维持旧行为（SCPX-287：
    # 单源中文意译 vs 2 源官名，不换锚，仍由「≥2 源同题日文作第二锚」兜底）。
    _all_hints = _enrich_text._actor_hints_from_titles([t for _s, t, _c in title_scores])
    _extra_anchor = ""
    _clusters: list[list[tuple[str, str, int]]] = []
    for _sid, _t, _sc in title_scores:
        for _cl in _clusters:
            if _enrich_text._titles_compatible(_t, _cl[0][1], actors=_all_hints):
                _cl.append((_sid, _t, _sc))
                break
        else:
            _clusters.append([(_sid, _t, _sc)])
    if len(_clusters) >= 2:
        _seed_cl = next(
            (c for c in _clusters if any(m[1] == seed for m in c)),
            None,
        )
        _top = max(_clusters, key=lambda c: len({m[0] for m in c}))
        _top_n = len({m[0] for m in _top})
        _seed_n = len({m[0] for m in _seed_cl}) if _seed_cl else 0
        _acts_by_sid = {
            _sid: {
                _enrich_text._fold(str(a).strip())
                for a in (_d.get("actors") or [])
                if str(a or "").strip()
            }
            for _sid, _d, _w in prelim
        }
        _old_acts = (
            set().union(*(_acts_by_sid.get(m[0] or "", set()) for m in _seed_cl))
            if _seed_cl
            else set()
        )
        _new_acts = set().union(
            *(_acts_by_sid.get(m[0] or "", set()) for m in _top)
        )
        _overlap = bool(_old_acts & _new_acts)
        _top_title = _top[0][1] if _top else ""
        # 换锚：① 最大簇比种子簇多 ≥2 源（RBD-035）；或
        # ② 种子是单源中文、≥2 源日文同题且标题不兼容且女优无交集
        #    （MDM-003：miss_av「恋爱咖啡馆」错绑日本有码月刊マダム）
        _switch = False
        if _seed_cl is not None and _top is not _seed_cl and _top_n >= 2:
            if _top_n - _seed_n >= 2:
                _switch = True
            elif (
                _seed_n == 1
                and not _overlap
                and not _enrich_text._has_kana(seed)
                and _enrich_text._has_kana(_top_title)
                and not _enrich_text._titles_compatible(seed, _top_title, actors=_all_hints)
            ):
                _switch = True
        if _switch:
            seed = _top_title
            if _overlap:
                _extra_anchor = _seed_cl[0][1]
    # 锚点只能是 seed，以及与 seed 兼容的日文标题。
    # 禁止把不兼容的假名错页（如ジュポニカ）也塞进 anchors，否则错页自证通过。
    seed_hints = _enrich_text._actor_hints_from_titles([seed])
    anchors = [seed]
    for _sid, t, _sc in title_scores:
        if t == seed or not _enrich_text._has_kana(t):
            continue
        if _enrich_text._titles_compatible(t, seed, actors=seed_hints):
            anchors.append(t)
            break
    # 簇换锚但有「同片证据」（女优重叠）时保留的旧种子锚（FAX-185 miss_av 烂机翻）
    if _extra_anchor and all(_extra_anchor != a for a in anchors):
        anchors.append(_extra_anchor)
    # 中文自由译常与日文官名零交集：尚未挂日文锚时，用 ≥2 源同题日文作第二锚，
    # 避免误杀女优（案例 SCPX-287 传播妹意译 vs マドンナ官名）。
    if not any(_enrich_text._has_kana(a) for a in anchors):
        from collections import Counter

        def _jp_title_key(t: str) -> str:
            s = re.sub(r"\s*[（(]\s*DOD\s*[）)]\s*$", "", str(t or "").strip(), flags=re.I)
            return s

        jp_votes: Counter[str] = Counter()
        jp_sample: dict[str, str] = {}
        for _sid, t, _sc in title_scores:
            if not _enrich_text._has_kana(t):
                continue
            k = _jp_title_key(t)
            # 素人短官名（2～3 假名）也要能成簇，否则中文意译种子会误杀女优（MUKD-244）
            if len(k) < 2:
                continue
            jp_votes[k] += 1
            jp_sample.setdefault(k, t)
        for k, cnt in jp_votes.most_common(3):
            if cnt < 2:
                break
            anchors.append(jp_sample[k])
            break
    hints = _enrich_text._actor_hints_from_titles(
        [
            seed,
            *anchors,
            *[
                t
                for _s, t, _c in title_scores[:8]
                if _enrich_text._titles_compatible(t, seed, actors=seed_hints)
            ],
        ]
    )

    kept: list[tuple[str, dict[str, Any]]] = []
    rejected: list[str] = []
    for sid, d, weak in prelim:
        if weak:
            w = dict(d)
            w["title"] = ""
            w["overview"] = ""
            w["actors"] = []
            w["tags"] = []
            if isinstance(w.get("extra"), dict):
                ex = dict(w["extra"])
                ex.pop("titleZh", None)
                w["extra"] = ex
            kept.append((sid, w))
            continue
        t = str(d.get("title") or "").strip()
        if not t:
            kept.append((sid, d))
            continue
        ok = any(
            _enrich_text._titles_compatible(t, a, actors=hints) for a in anchors if a
        )
        if not ok:
            # 标题机翻/意译与日文官名不兼容，但女优与锚点簇有交集 → 同片，保留
            # （OERO/DOJN：miss_av 长中文题被拒后剧情一并清空）
            def _act_keys(names: list[Any] | None) -> set[str]:
                out: set[str] = set()
                for a in names or []:
                    s = str(a or "").strip()
                    if not s:
                        continue
                    # miss_av「さつきさん 27歳…」只取首段
                    head = re.split(r"[\s　(/（]", s, maxsplit=1)[0].strip() or s
                    for piece in (s, head):
                        out.add(_enrich_text._fold(piece))
                        _d2, kid = _enrich_text._actress_disp_id(piece)
                        if kid:
                            out.add(kid.casefold())
                        if _d2:
                            out.add(_enrich_text._fold(_d2))
                return out

            src_acts = _act_keys(list(d.get("actors") or []))
            if src_acts:
                anchor_acts: set[str] = set()
                for _sid2, _d2, _w2 in prelim:
                    if _w2:
                        continue
                    t2 = str(_d2.get("title") or "").strip()
                    if not t2:
                        continue
                    if any(
                        _enrich_text._titles_compatible(t2, a, actors=hints) for a in anchors if a
                    ):
                        anchor_acts |= _act_keys(list(_d2.get("actors") or []))
                if src_acts & anchor_acts:
                    ok = True
        if ok:
            kept.append((sid, d))
            continue
        rejected.append(sid)
        w = dict(d)
        w["title"] = ""
        w["overview"] = ""
        w["actors"] = []
        w["tags"] = []
        if isinstance(w.get("extra"), dict):
            ex = dict(w["extra"])
            ex.pop("titleZh", None)
            w["extra"] = ex
        kept.append((sid, w))
    return kept, rejected


def _detail_has_poster(detail: dict[str, Any] | None, *, strict: bool = False) -> bool:
    """是否有封面 URL。strict=True（补封面早停）时拒绝单条弱 digital 占位。"""
    if not detail:
        return False
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    if not poster.startswith(("http://", "https://")):
        return False
    if not strict:
        return True
    cands = [
        str(u).strip()
        for u in list(detail.get("posterCandidates") or []) + [poster]
        if str(u or "").strip().startswith(("http://", "https://"))
    ]
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for u in cands:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    ranks = [_enrich_cover._poster_rank(u) for u in uniq]
    if ranks and max(ranks) >= 4:
        return True
    hosts: set[str] = set()
    for u in uniq:
        try:
            from urllib.parse import urlparse

            h = (urlparse(u).netloc or "").lower()
            if h:
                hosts.add(h)
        except Exception:
            pass
    # 至少两个不同站封面互证，才够早停（单条 pl/digital 常是空图）
    if len(hosts) >= 2 and ranks and max(ranks) >= 3:
        return True
    return False


def _detail_has_actors(detail: dict[str, Any] | None) -> bool:
    if not detail:
        return False
    return bool(_enrich._clean_actors(detail.get("actors")))


def _detail_satisfies_gaps(
    detail: dict[str, Any] | None,
    gaps: list[str] | None = None,
    *,
    code: str = "",
) -> bool:
    """按本条缺口判断是否可提前收工；缺口字段齐了才停，避免丢掉稍后返回的源。"""
    if not detail:
        return False
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    # 无显式缺口：至少封面+女优（兼容旧逻辑）
    if not gap_set:
        return _detail_has_poster(detail) and _detail_has_actors(detail)

    if ("no_local" in gap_set or "no_media" in gap_set) and not _detail_has_poster(
        detail, strict=True
    ):
        return False
    if "no_actress" in gap_set and not _detail_has_actors(detail):
        return False
    if "no_studio" in gap_set and not str(
        detail.get("studio") or detail.get("maker") or ""
    ).strip():
        return False
    if "no_plot" in gap_set and len(str(detail.get("overview") or "").strip()) < 12:
        return False
    if "thin_title" in gap_set and _enrich._title_is_thin(
        str(detail.get("title") or ""), code or str(detail.get("code") or "")
    ):
        return False
    # ⚠️ `no_zh_title` **刻意不在这里判**（第二十一轮修正）。
    # 它曾是硬闸门：标题非中文就一律不许早停。但 dmm / avbase 这类源给出的是
    # 日文标题（含假名 → `_zh_prefer_bonus` 恒为 0），**永远不可能**满足这条，
    # 于是这些番号必然等到全部源回或超时 —— 早停对它们完全失效（现场 12% 的号）。
    # 正确归属是 `_may_early_stop` 的「中文源等待」逻辑：等中文源跑完即放行，
    # 而不是无限等所有源（含注定给不出中文的那几个）。
    # 反证：把它加回来 → `test_no_zh_title_is_not_a_hard_gate` 与
    # `test_no_zh_title_releases_after_cn_sources_done` 双双 FAILED（后者直接
    # 复现了「中文源已全跑完仍不许放行」的死锁）。
    return True


def _prioritize_batch_for_gaps(
    batch: list[dict[str, Any]],
    gaps: list[str] | None,
    *,
    region: str = "",
) -> list[dict[str, Any]]:
    """按缺口对应的 fieldPriority 配置提权，其余保持 regionSources 原序。

    仅有码区生效；其它区保持 batch 原序（只看全局分区源）。
    例：缺标题/剧情时先发 fieldPriority.title/overview 里的站，
    避免 regionSources 开头的站占满波次槽、字段优先站迟迟发不出。
    """
    if len(batch) <= 1:
        return list(batch)
    if not _enrich_merge._field_priority_applies(region):
        return list(batch)
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    if not gap_set:
        return list(batch)

    needed_fields: set[str] = set()
    for gap in gap_set:
        needed_fields.update(_GAP_FIELD_PRIORITY_KEYS.get(gap, ()))
    if not needed_fields:
        return list(batch)
    field_keys = [fk for fk in _enrich_merge._FIELD_LAUNCH_ORDER if fk in needed_fields]
    # 配置里有、但不在预置序的字段：按需追加
    for fk in sorted(needed_fields):
        if fk not in field_keys:
            field_keys.append(fk)

    try:
        from app.scrap_library.enrich_strategy import get_strategy
        import app.scrape.source_catalog as catalog

        fp = get_strategy().get("fieldPriority") or {}
    except Exception:  # noqa: BLE001
        return list(batch)
    if not isinstance(fp, dict):
        return list(batch)

    prefer_ids: list[str] = []
    seen_ids: set[str] = set()
    for fk in field_keys:
        raw = fp.get(fk)
        if not isinstance(raw, list):
            continue
        for item in raw:
            sid = catalog.canonicalize_id(str(item or ""))
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                prefer_ids.append(sid)
    if not prefer_ids:
        return list(batch)

    by_id: dict[str, dict[str, Any]] = {}
    for src in batch:
        sid = catalog.canonicalize_id(str(src.get("id") or ""))
        if sid and sid not in by_id:
            by_id[sid] = src

    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for sid in prefer_ids:
        hit = by_id.get(sid)
        if hit is not None:
            out.append(hit)
            used.add(sid)
    for src in batch:
        sid = catalog.canonicalize_id(str(src.get("id") or ""))
        if sid in used:
            continue
        out.append(src)
        if sid:
            used.add(sid)
    return out


def _detail_meta_incomplete(detail: dict[str, Any] | None) -> bool:
    """系列 / 发行 / 官网 任一仍缺则视为元数据未齐（预告可选，不挡早停）。"""
    if not detail or not isinstance(detail, dict):
        return True
    series = str(detail.get("series") or detail.get("set") or "").strip()
    publisher = str(detail.get("publisher") or detail.get("label") or "").strip()
    website = str(detail.get("website") or detail.get("url") or "").strip()
    return not (series and publisher and website.startswith(("http://", "https://")))


def _may_early_stop(
    detail: dict[str, Any] | None,
    gaps: list[str] | None,
    *,
    code: str,
    batch: list[dict[str, Any]],
    finished: set[str],
    meta_wait: dict[str, float] | None = None,
) -> bool:
    """缺口齐了才可早停；缺标题/剧情时**有界**等中文源；元数据未齐时**有界**等 DMM/MGS 等。

    meta_wait：本番号的等待状态（调用方持有，跨多次调用累计）。
    键：`since`/`logged`（元数据）、`cn_since`/`cn_logged`（中文源）。
    传 `None` = 旧行为（无限等），便于 A/B 与反证；生产路径必须传。
    """
    import app.scrape.source_catalog as catalog

    if not _detail_satisfies_gaps(detail, gaps, code=code):
        return False
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    # 中文源等待集合。`no_zh_title` 与 `thin_title` 是**同一诉求的两种表述**
    # （标题还没有中文），必须一起处理 —— 第二十一轮修正前它缺席此集合，
    # 却又被 `_detail_satisfies_gaps` 当硬闸门，于是这些番号既不享受
    # 「中文源跑完就放行」，也不被允许早停，只能活活等到全部源超时。
    need_zh = bool(gap_set & {"thin_title", "no_plot", "no_zh_title"})
    if need_zh and detail:
        title_ok = True
        plot_ok = True
        if "thin_title" in gap_set:
            title_ok = _enrich_text._zh_prefer_bonus(str(detail.get("title") or "")) > 0
        if "no_zh_title" in gap_set:
            title_ok = title_ok and not _enrich_text._title_lacks_zh(
                str(detail.get("title") or ""), code
            )
        if "no_plot" in gap_set:
            plot_ok = _enrich_text._zh_prefer_bonus(str(detail.get("overview") or "")) > 0
        if not (title_ok and plot_ok):
            pending = _cn_text_ids_in_batch(batch) - finished
            if pending:
                if meta_wait is None:
                    return False
                now = time.monotonic()
                since = meta_wait.get("cn_since")
                if since is None:
                    meta_wait["cn_since"] = now
                    return False
                if (now - float(since)) < _CN_WAIT_BUDGET_SEC:
                    return False
                if not meta_wait.get("cn_logged"):
                    meta_wait["cn_logged"] = 1.0
                    log.info(
                        "enrich %s cn-wait budget %.1fs expired, early-stop "
                        "pending_cn=%s (中文标题/剧情可能本就缺失)",
                        code,
                        _CN_WAIT_BUDGET_SEC,
                        ",".join(sorted(pending)),
                    )
    # 主缺口已齐，但系列/发行/官网仍缺：若本批还有元数据源未回，**在预算内**继续等。
    # 预算用尽即放行早停 —— 否则「本来就没有系列」的番号会永远等不到早停。
    if _detail_meta_incomplete(detail):
        pending_meta: set[str] = set()
        for src in batch:
            sid = catalog.canonicalize_id(str(src.get("id") or ""))
            if not sid or sid in finished:
                continue
            if sid in _META_FILL_SOURCE_IDS:
                pending_meta.add(sid)
        if pending_meta:
            if meta_wait is None:
                return False
            now = time.monotonic()
            since = meta_wait.get("since")
            if since is None:
                # 第一次需要等：起表，先让快源（dmm/libredmm）把窗口用起来
                meta_wait["since"] = now
                return False
            if (now - float(since)) < _META_WAIT_BUDGET_SEC:
                return False
            if not meta_wait.get("logged"):
                meta_wait["logged"] = 1.0
                log.info(
                    "enrich %s meta-wait budget %.1fs expired, early-stop "
                    "pending_meta=%s (series/publisher/website 可能本就缺失)",
                    code,
                    _META_WAIT_BUDGET_SEC,
                    ",".join(sorted(pending_meta)),
                )
    return True


def _gaps_likely_ready(
    got: dict[str, dict[str, Any]],
    gaps: list[str] | None,
    *,
    code: str = "",
) -> bool:
    """早停廉价闸：跨源 OR 字段是否已可能齐，未齐则跳过整次 `_merge_got`。"""
    if not got:
        return False
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    details = list(got.values())
    if not gap_set:
        return any(
            _detail_has_poster(d) and _detail_has_actors(d) for d in details
        ) or (
            any(_detail_has_poster(d) for d in details)
            and any(_detail_has_actors(d) for d in details)
        )
    if ("no_local" in gap_set or "no_media" in gap_set) and not any(
        _detail_has_poster(d, strict=True) for d in details
    ):
        return False
    if "no_actress" in gap_set and not any(_detail_has_actors(d) for d in details):
        return False
    if "no_studio" in gap_set and not any(
        str(d.get("studio") or d.get("maker") or "").strip() for d in details
    ):
        return False
    if "no_plot" in gap_set and not any(
        len(str(d.get("overview") or "").strip()) >= 12 for d in details
    ):
        return False
    if "thin_title" in gap_set and not any(
        not _enrich._title_is_thin(str(d.get("title") or ""), code or str(d.get("code") or ""))
        for d in details
    ):
        return False
    return True


def _fetch_detail(
    code: str,
    *,
    region: str = "",
    wait_all: bool = False,
    gaps: list[str] | None = None,
    adaptive_first: bool = False,
    fast_zh: bool = False,
) -> dict[str, Any] | None:
    """对匹配且已启用的数据源按策略并发拉详情，再按字段可信度合并最优。

    wait_all=True：不按缺口早停（极少用）。
    gaps：缺口字段齐了才允许早停。
    adaptive_first=True：强制先跑自适应源，缺口未齐再跑过盾（详情单刷）。
    fast_zh=True：批量刮削用机翻短超时，避免 LLM 拖死番号槽。
    """
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    import app.scrap_library.enrich_strategy as strat
    import app.scrape.sources_settings as scrape_src
    from app.scrape_details import fetch_detail_for_source

    code_u = str(code or "").strip().upper()
    if not code_u:
        return None
    sources = _detail_sources(region=region, code=code_u)
    if not sources:
        log.info(
            "enrich: no enabled sources for region=%r groups=%s",
            region,
            scrape_src.enrich_groups_for_region(region),
        )
        return None

    cfg = strat.get_strategy()
    mode = str(cfg.get("mode") or "adaptive_first")
    if adaptive_first and mode == "parallel_all":
        mode = "adaptive_first"
    include_flare = bool(cfg.get("includeFlare", True))
    adapt_cfg = int(cfg.get("adaptiveWorkers") if cfg.get("adaptiveWorkers") is not None else 0)
    flare_cfg = int(cfg.get("flareWorkers") if cfg.get("flareWorkers") is not None else 0)
    timeout_sec = int(cfg.get("perSourceTimeoutSec") or 28)
    timeout_sec = max(5, min(180, timeout_sec))
    # 过盾/已知慢源单独封顶，避免拖死番号槽
    flare_timeout_cap = min(18, timeout_sec)
    # 勿每条都推「单源超时」——易被误认为真超时刷屏；只打一次 info
    log.info(
        "enrich %s perSourceTimeout=%ss flareCap=%ss",
        code_u,
        timeout_sec,
        flare_timeout_cap,
    )

    adaptive = [s for s in sources if str(s.get("access") or "") != "proxy_flare"]
    flare = [s for s in sources if str(s.get("access") or "") == "proxy_flare"]
    if not include_flare or mode == "adaptive_only":
        flare = []

    adapt_n = strat.resolve_pool_workers(adapt_cfg, len(adaptive))
    flare_n = strat.resolve_pool_workers(flare_cfg, len(flare)) if flare else 0
    from app.core.container_budget import cap_parallel as _cap_parallel

    if adapt_n:
        adapt_n = _cap_parallel(
            min(adapt_n, int(_SOURCE_WORKERS_MAX)),
            tight=4,
            small=8,
            hard=int(_SOURCE_WORKERS_MAX),
        )
    if flare_n:
        flare_n = _cap_parallel(
            min(flare_n, int(_SOURCE_WORKERS_MAX)),
            tight=2,
            small=4,
            hard=int(_SOURCE_WORKERS_MAX),
        )
    # 对齐 mdc-ng：单番号匹配源全开并发；出站压力交给 host/global 调度，
    # 不再因 itemWorkers 把单条压成 3 路（否则墙钟≈慢源串行、越跑越像超时）。

    if mode == "adaptive_only":
        pools = [("adaptive", adaptive, adapt_n)]
    elif mode == "adaptive_first":
        pools = [("adaptive", adaptive, adapt_n), ("flare", flare, flare_n)]
    else:
        # parallel_all：该番号匹配源一起并发；adaptiveWorkers=0 则全开
        all_batch = adaptive + flare
        all_n = strat.resolve_pool_workers(adapt_cfg, len(all_batch))
        from app.core.container_budget import cap_parallel as _cap_parallel

        all_n = (
            _cap_parallel(
                min(all_n, int(_SOURCE_WORKERS_MAX)),
                tight=4,
                small=8,
                hard=int(_SOURCE_WORKERS_MAX),
            )
            if all_n
            else 0
        )
        pools = [("all", all_batch, all_n)]
        log.info(
            "enrich %s parallel_all workers=%s/%s (cfg=%s)",
            code_u,
            all_n,
            len(all_batch),
            adapt_cfg,
        )

    if mode != "parallel_all":
        log.info(
            "enrich %s region=%r mode=%s sources=%s adapt=%s/%s flare=%s/%s",
            code_u,
            region,
            mode,
            len(sources),
            adapt_n,
            len(adaptive),
            flare_n,
            len(flare),
        )

    timings: list[dict[str, Any]] = []
    timings_lock = threading.Lock()
    t_fetch0 = time.perf_counter()

    def _timings_snapshot() -> list[dict[str, Any]]:
        with timings_lock:
            return [dict(r) for r in timings]

    def _publish_timings() -> None:
        """把当前源耗时推到 live current + 对应队列行（支持多番号并发）。"""
        rows = _timings_snapshot()
        with _enrich_lock:
            cur = _enrich_job.get("current")
            if isinstance(cur, dict):
                code_cur = str(cur.get("code") or "").strip().upper()
                if not code_cur or code_cur == code_u:
                    nxt = dict(cur)
                    nxt["sourceTimings"] = rows
                    if code_u:
                        nxt["code"] = code_u
                    _enrich_job["current"] = nxt
            # 队列行也写源耗时，点开任一「处理中」都能看实时进度
            queue = list(_enrich_job.get("queue") or [])
            changed = False
            for i, r in enumerate(queue):
                if not isinstance(r, dict):
                    continue
                if str(r.get("code") or "").strip().upper() != code_u:
                    continue
                queue[i] = {**r, "sourceTimings": rows}
                changed = True
                break
            if changed:
                _enrich_job["queue"] = queue
        try:
            enrich_mon.touch_sources(code=code_u, sources=rows)
            notify_enrich_watchers()
        except Exception:  # noqa: BLE001
            pass

    def _upsert_timing(row: dict[str, Any]) -> None:
        sid = str(row.get("id") or "")
        with timings_lock:
            for i, r in enumerate(timings):
                if str(r.get("id") or "") == sid:
                    timings[i] = {**r, **row}
                    break
            else:
                timings.append(dict(row))
        _publish_timings()

    def _mark_pending_skipped(reason: str) -> None:
        with timings_lock:
            for i, r in enumerate(timings):
                st = str(r.get("status") or "")
                if st in {"pending", ""}:
                    timings[i] = {
                        **r,
                        "status": "skipped",
                        "ok": False,
                        "ms": int(r.get("ms") or 0),
                        "error": reason[:120],
                    }
        _publish_timings()

    # 预置全部启用源，保证 UI 能看到完整名单（含早停未跑完的）
    for src in sources:
        sid = str(src.get("id") or "").strip()
        if not sid:
            continue
        _upsert_timing(
            {
                "id": sid,
                "access": str(src.get("access") or ""),
                "ms": 0,
                "ok": False,
                "error": "",
                "actors": 0,
                "poster": False,
                "status": "pending",
            }
        )

    def _record_timing(
        *,
        sid: str,
        access: str,
        ms: float,
        ok: bool,
        err: str = "",
        actors: int = 0,
        has_poster: bool = False,
        kind: str = "",
        wait_ms: float = 0.0,
    ) -> None:
        row = {
            "id": sid,
            "access": access,
            "ms": int(round(ms)),
            # 等出站槽毫秒（第十一轮）：把「排队」从总耗时里显式分出来，
            # 生产上可直接看排队分布 —— 判断「最坏 2× 单源预算」到底是常态还是尾巴。
            "waitMs": int(round(max(0.0, float(wait_ms or 0.0)))),
            "ok": bool(ok),
            "error": (err or "")[:120],
            "actors": int(actors),
            "poster": bool(has_poster),
            "status": "done" if ok else "fail",
            # miss（源没这条番号）/ down（源不可用）/ busy（我们没轮到）/ cancelled（主动放弃）：
            # 只有 down / busy 会让整条番号进入「补抓」提示，见 _finish_one。
            "kind": kind or ("hit" if ok else ""),
        }
        _upsert_timing(row)
        status = "ok" if ok else f"fail:{row['error'] or '-'}"
        extras = []
        if ok:
            if has_poster:
                extras.append("封面")
            if actors:
                extras.append(f"女优×{actors}")
        _enrich._push_log(
            f"{sid} {row['ms']}ms {status}"
            + (f" · {'/'.join(extras)}" if extras else "")
        )
        done_n = sum(
            1
            for r in _timings_snapshot()
            if str(r.get("status") or "") in {"done", "fail"}
        )
        _set_progress(
            stage="enrich",
            label=f"{sid} {row['ms']}ms",
            done=done_n,
            total=max(len(sources), done_n),
        )

    # 本番号本轮 fetch 的取消令牌：早停/暂停后置位，让被放弃的在飞源
    # 立刻从出站等槽队列里退出（详见 _run_pool）。
    _fetch_ctx: dict[str, Any] = {"cancel": None}
    # 本番号的「元数据有界等待」状态（详见 _META_WAIT_BUDGET_SEC）。
    # 必须跨多次 `_may_early_stop` 调用累计，所以放在本函数作用域而非函数内部。
    _meta_wait: dict[str, float] = {}

    def _one(src: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str, str]:
        import app.core.outbound_http as outbound_http

        sid = str(src.get("id") or "")
        access = str(src.get("access") or "")
        # 过盾源用更短超时，减轻单番号槽位被盾站占满
        src_timeout = float(timeout_sec)
        if access == "proxy_flare":
            src_timeout = float(min(flare_timeout_cap, timeout_sec))
        # iqqtv 曾双页串行易顶满预算；即便已改中文优先，仍略收紧工作超时，
        # 让放弃后的 curl 僵尸更快释放 page 槽。
        if sid == "iqqtv":
            src_timeout = float(min(src_timeout, 12.0))
        t0 = time.perf_counter()
        if _source_in_cooldown(sid):
            # ⚠️ 用**独立 kind**，不能记成 busy。
            # `busy` 的既定语义是「**我们这边**没轮到发请求（出站槽/限速/退避/过盾通道排满）」，
            # 因此**不计入源健康度**；而 cooldown 恰恰是 `_note_source_fetch_outcome`
            # 依据 down 连击算出来的**源健康度**结论（见其 docstring）。
            # 混用会让 `sourcesBusy` 把「源不健康被主动跳过」报成「排队未及」，
            # 前端/诊断读到的原因与事实相反（第十七轮 D3）。
            # 待遇与 down 一致：仍要补抓（进 degradedByDown），但不重复计 streak。
            err_c = "cooldown:源暂避"
            _record_timing(
                sid=sid,
                access=access,
                ms=0,
                ok=False,
                err=err_c,
                kind="cooldown",
            )
            return sid, None, err_c, "cooldown"
        try:
            applied = scrape_src.apply_provider_link_for_fetch(sid)
        except Exception as e:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000
            _record_timing(
                sid=sid, access=access, ms=ms, ok=False, err=f"link:{e}", kind="down"
            )
            _note_source_fetch_outcome(sid, kind="down")
            return sid, None, f"link:{e}", "down"

        # 本源等槽记账：由 fetch 线程写、本线程（池线程）读 —— 用「墙钟 − 等槽」
        # 判断真超时，别把「排队等出站槽」算成源超时。
        meter = outbound_http.new_slot_wait_meter()
        # 等槽预算与工作预算解耦（详见 outbound_http.source_queue_budget）
        queue_budget = float(outbound_http.source_queue_budget(src_timeout))
        # 本源专属取消令牌：放弃后立刻把僵尸线程从等槽队列里摘出来，
        # 不牵连同池其它源（池级令牌见 _fetch_ctx）。
        src_cancel = threading.Event()
        cancel_pair = _enrich_retry._CancelPair(_fetch_ctx.get("cancel"), src_cancel)

        holder: dict[str, Any] = {}

        def _run_fetch() -> None:
            # TLS 必须在真正发请求的线程里设置
            # adaptive_first：自适应源只直连；过盾留给 flare 池，避免 curl→FS 回落占满单飞
            allow_flare = bool(include_flare)
            if mode == "adaptive_first" and access != "proxy_flare":
                allow_flare = False
            elif mode == "adaptive_only":
                allow_flare = False
            outbound_http.set_thread_allow_flare(allow_flare)
            outbound_http.set_thread_request_timeout(float(src_timeout))
            # 绑定取消令牌：置位后出站调度器不再为这个已放弃的源发请求
            outbound_http.set_thread_cancel_event(cancel_pair)
            outbound_http.set_thread_slot_meter(meter)
            try:
                detail = fetch_detail_for_source(
                    sid,
                    code_u,
                    base_url=str(applied.get("baseUrl") or src.get("baseUrl") or ""),
                    cookie=str(applied.get("cookie") or src.get("cookie") or ""),
                    api_key=str(applied.get("apiKey") or src.get("apiKey") or ""),
                )
                holder["detail"] = detail
            except Exception as e:  # noqa: BLE001
                holder["error"] = e
            finally:
                outbound_http.set_thread_request_timeout(None)
                outbound_http.set_thread_cancel_event(None)
                outbound_http.set_thread_slot_meter(None)

        _upsert_timing(
            {
                "id": sid,
                "access": access,
                "ms": 0,
                "waitMs": 0,
                "ok": False,
                "error": "",
                "actors": 0,
                "poster": False,
                "status": "running",
            }
        )
        th = threading.Thread(
            target=_run_fetch,
            name=f"enrich-src-{sid}",
            daemon=True,
        )
        th.start()
        # 放弃判据（第十轮）：用**工作耗时**而不是墙钟。
        #   工作耗时 = 墙钟 − 等出站槽时间（SlotWaitMeter 记账）
        #   ① 工作耗时 ≥ 单源预算 → down（源真的慢/挂）
        #   ② 墙钟 ≥ 单源预算 + 排队预算 → busy（始终没轮到发请求）
        # 只调大 join 超时是把「假超时」变成「假成功」，所以这里必须记账后判定。
        give_up = ""
        while th.is_alive():
            th.join(timeout=_enrich_retry._SRC_GIVEUP_POLL_SEC)
            if not th.is_alive():
                break
            give_up = _src_give_up_reason(
                elapsed=time.perf_counter() - t0,
                waited=float(meter.wait_now()),
                work_budget=src_timeout,
                queue_budget=queue_budget,
            )
            if give_up:
                break
        ms = (time.perf_counter() - t0) * 1000
        applied_access = str(applied.get("access") or access)

        if give_up:
            # 丢弃该源结果（后台线程可能仍在跑，但合并不再采纳）；
            # 置本源令牌 → 它若还在等槽会在 ≤0.2s 内退出，不再占槽/发无用请求。
            src_cancel.set()
            # 分类：早停被主动放弃 ≠ 源故障；「从没拿到过槽」= 没轮到（详见 _give_up_kind）
            t_kind = _enrich._give_up_kind(
                give_up=give_up,
                acquired=int(meter.acquired),
                cancelled=_enrich_retry._is_cancelled(),
            )
            if t_kind == "busy":
                err_t = f"busy:排队未及 {int(ms)}ms"
            else:
                err_t = f"timeout:{int(src_timeout)}s"
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=err_t,
                kind=t_kind,
                wait_ms=float(meter.wait_now()) * 1000,
            )
            _note_source_fetch_outcome(sid, kind=t_kind)
            return sid, None, err_t, t_kind

        err_obj = holder.get("error")
        if err_obj is not None:
            if isinstance(err_obj, HTTPException):
                err_s = str(err_obj.detail)
            else:
                err_s = str(err_obj)
            err_kind = _enrich._refine_kind_with_meter(
                _classify_source_failure(err_obj),
                slot_timeout=int(getattr(meter, "slot_timeout", 0)),
            )
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=err_s,
                kind=err_kind,
                wait_ms=float(meter.wait_now()) * 1000,
            )
            _note_source_fetch_outcome(sid, kind=err_kind)
            return sid, None, err_s, err_kind

        detail = holder.get("detail")
        if not _detail_usable(detail, code=code_u):
            title = str((detail or {}).get("title") or "")[:40]
            err_r = f"rejected:{title}"
            miss_kind = _enrich._refine_kind_with_meter(
                "miss", slot_timeout=int(getattr(meter, "slot_timeout", 0))
            )
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=err_r,
                # 源正常响应、只是没有这条番号（或返回了别的番号的页面）→ miss，不必补抓；
                # 但若本次出站排到过超时（痕迹在记账里），「未找到」可能是被吞掉的 busy。
                kind=miss_kind,
                wait_ms=float(meter.wait_now()) * 1000,
            )
            _note_source_fetch_outcome(sid, kind=miss_kind)
            return sid, None, err_r, "miss"
        detail = dict(detail)
        try:
            from app.scrape.metadata_optimize import polish_actress_names
            from app.scrap_library.enrich_strategy import local_map_mode

            directors: list[str] = []
            d0 = str(detail.get("director") or "").strip()
            if d0:
                directors.append(d0)
            for raw_d in detail.get("directors") or []:
                if isinstance(raw_d, dict):
                    n = str(raw_d.get("name") or "").strip()
                else:
                    n = str(raw_d or "").strip()
                if n:
                    directors.append(n)
            detail["actors"] = polish_actress_names(
                _enrich._clean_actors(detail.get("actors")),
                exclude=directors,
                enable_mapping=local_map_mode("actors") != "off",
            )
            detail["_actorsPolished"] = True
        except Exception:  # noqa: BLE001
            detail["actors"] = _enrich._clean_actors(detail.get("actors"))
            detail["_actorsPolished"] = False
        # 源侧明细标签：**不折叠**字形。此处结果会喂给 `_score_tags`
        # （via `_merge_got` 读 `d.get("tags")`），提前折叠会让繁中源
        # 失去「繁体惩罚」而反压简中源（案例 ACHJ-078）。输出侧折叠在合并主循环做。
        detail["tags"] = _enrich_text._clean_tags(detail.get("tags"), fold=False)
        detail["source"] = detail.get("source") or sid
        detail["provider"] = detail.get("provider") or sid
        detail["resolvedBase"] = applied.get("baseUrl") or src.get("baseUrl")
        detail["access"] = applied.get("access") or src.get("access")
        _record_timing(
            sid=sid,
            access=str(detail.get("access") or access),
            ms=ms,
            ok=True,
            actors=len(detail.get("actors") or []),
            has_poster=_detail_has_poster(detail),
            kind="hit",
            wait_ms=float(meter.wait_now()) * 1000,
        )
        _note_source_fetch_outcome(sid, kind="hit")
        return sid, detail, "", "hit"

    def _run_pool(
        label: str, batch: list[dict[str, Any]], workers: int
    ) -> tuple[
        dict[str, dict[str, Any]],
        list[str],
        set[str],
        set[str],
        set[str],
        set[str],
    ]:
        """返回 (命中详情, 错误串, down 源, miss 源, busy 源, cooldown 源)。

        后四者把「源挂了」「源没这条番号」「我们没轮到」「源不健康被主动暂避」
        分开，别混：
          - down / busy / **cooldown** → 补抓需要（cooldown 是源健康度结论，
            下轮可能已恢复；且进 `degradedByDown` 才会被回头修）
          - miss / cancelled → 不需要补抓（重抓只白占出站槽）
        ⚠️ cooldown 单列的理由见 `_one` 里冷却分支的注释：busy 不算健康度，
        cooldown 算，混用会把「源不健康」报成「排队未及」。
        """
        if not batch or workers <= 0:
            return {}, [], set(), set(), set(), set()
        got: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        down_ids: set[str] = set()
        miss_ids: set[str] = set()
        busy_ids: set[str] = set()
        cooldown_ids: set[str] = set()
        finished: set[str] = set()
        # 每池独立令牌：adaptive 池收尾时置位，只回收本池被放弃的在飞源，
        # 不误伤随后的 flare 池（两池串行，见 _fetch_detail 的 pools）
        cancel_ev = threading.Event()
        _fetch_ctx["cancel"] = cancel_ev
        ordered = _prioritize_batch_for_gaps(batch, gaps, region=region)
        # 对齐 mdc-ng：匹配源一次全开并发；workers=配置上限（0→全开）
        n = max(1, min(workers, len(ordered)))
        pool = ThreadPoolExecutor(
            max_workers=n, thread_name_prefix=f"enrich-{label}"
        )
        futs = {pool.submit(_one, src): src for src in ordered}
        early = False
        probe_keys: frozenset[str] | None = None
        probe_merged: dict[str, Any] | None = None
        gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
        need_zh = bool(gap_set & {"thin_title", "no_plot", "no_zh_title"})
        _enrich._push_log(
            f"开跑 · {label} ×{len(ordered)} · workers={n} · 全开并发"
        )
        try:
            pending = set(futs.keys())
            while pending:
                # 暂停/停止：立刻收手，别再为已无意义的番号占出站槽
                if _enrich_retry._is_cancelled():
                    log.info(
                        "enrich %s halt-abandon pool=%s inflight=%s",
                        code_u,
                        label,
                        len(pending),
                    )
                    break
                done_set, pending = wait(
                    pending,
                    timeout=0.5,
                    return_when=FIRST_COMPLETED,
                )
                if not done_set:
                    continue
                for fut in done_set:
                    try:
                        sid, detail, err, kind = fut.result(timeout=0.1)
                    except Exception as e:  # noqa: BLE001
                        errors.append(str(e))
                        continue
                    if sid:
                        finished.add(str(sid))
                    if detail:
                        got[sid] = detail
                        if not wait_all and _gaps_likely_ready(
                            got, gaps, code=code_u
                        ):
                            if need_zh:
                                # 与 `_may_early_stop` 的 need_zh 集合同源：
                                # `no_zh_title` 同样表示「标题还没有中文」，也要等中文源
                                title_need = bool(
                                    gap_set & {"thin_title", "no_zh_title"}
                                )
                                plot_need = "no_plot" in gap_set
                                zh_ready = (
                                    not title_need or _enrich_text._got_has_zh_title(got)
                                ) and (not plot_need or _enrich_text._got_has_zh_plot(got))
                                cn_pending = (
                                    _cn_text_ids_in_batch(ordered) - finished
                                )
                                # 有界等中文源：预算内才跳过早停探测。
                                # 否则 iqqtv「搜索无结果」12~20s 会钉死墙钟。
                                if not zh_ready and cn_pending:
                                    now_cn = time.monotonic()
                                    if _meta_wait.get("cn_since") is None:
                                        _meta_wait["cn_since"] = now_cn
                                    if (
                                        now_cn - float(_meta_wait["cn_since"])
                                    ) < _CN_WAIT_BUDGET_SEC:
                                        continue
                            keys_now = frozenset(got.keys())
                            if keys_now != probe_keys:
                                probe_merged = _enrich_merge._merge_got(
                                    ordered, got, region=region, probe=True
                                )
                                probe_keys = keys_now
                            if probe_merged and _may_early_stop(
                                probe_merged,
                                gaps,
                                code=code_u,
                                batch=ordered,
                                finished=finished,
                                meta_wait=_meta_wait,
                            ):
                                early = True
                                log.info(
                                    "enrich %s early-stop pool=%s hits=%s gaps=%s",
                                    code_u,
                                    label,
                                    ",".join(got.keys()),
                                    ",".join(gaps or []) or "-",
                                )
                                abandoned = max(
                                    0, len(futs) - len(finished)
                                )
                                _enrich._push_log(
                                    f"早停 · {label} · 已齐 gaps={','.join(gaps or []) or '-'} · "
                                    f"命中 {','.join(got.keys())}"
                                    + (
                                        f" · 放弃在飞 {abandoned}（取消令牌，不再占用出站槽）"
                                        if abandoned
                                        else ""
                                    )
                                )
                                break
                    elif err:
                        errors.append(f"{sid}:{err}")
                        # 只有「源不可用 / 我们没轮到」才值得补抓：miss 是源侧确实
                        # 没这条番号，重抓只会白占出站槽（这就是「高优先源抖动 →
                        # 静默降级」的判别点）；busy 是出站槽/限速/过盾通道排满，
                        # 源没坏，但本轮确实没拿到 → 也要补，否则降级取值没人回头修。
                        if kind == "down" and sid:
                            down_ids.add(str(sid))
                        elif kind == "miss" and sid:
                            miss_ids.add(str(sid))
                        elif kind == "busy" and sid:
                            busy_ids.add(str(sid))
                        elif kind == "cooldown" and sid:
                            cooldown_ids.add(str(sid))
                if early:
                    break
        finally:
            # 关键顺序：先置取消令牌，再放池。
            # 被放弃的在飞源此前会堵在出站信号量上，等到槽位后仍会真发一次请求
            # （≤单源超时），把 page 全局槽（默认 20）从活番号手里抢走 ——
            # itemWorkers×源数 可达 100 路，这就是「越刮越慢 + 假超时」的来源。
            # 置位后它们在 ≤0.2s 内抛 OutboundCancelled 退出，不占槽、不发请求。
            cancel_ev.set()
            if _fetch_ctx.get("cancel") is cancel_ev:
                _fetch_ctx["cancel"] = None
            for f in futs:
                f.cancel()
            # 不等剩余慢请求；池线程随后自行结束（已无出站占用）
            pool.shutdown(wait=False, cancel_futures=True)
            if early:
                _mark_pending_skipped("早停跳过")
        if early:
            errors = [e for e in errors if "cancelled" not in e.lower()]
        return got, errors, down_ids, miss_ids, busy_ids, cooldown_ids

    got_all: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    down_all: set[str] = set()
    busy_all: set[str] = set()
    miss_all: set[str] = set()
    cooldown_all: set[str] = set()
    for label, batch, workers in pools:
        if not batch:
            continue
        # adaptive_first：本条缺口已齐再跳过 Flare（标题/剧情未拿中文时仍进过盾池）
        if (
            mode == "adaptive_first"
            and label == "flare"
            and _may_early_stop(
                _enrich_merge._merge_got(sources, got_all, region=region, probe=True),
                gaps,
                code=code_u,
                batch=batch,
                finished=set(got_all.keys()),
                meta_wait=_meta_wait,
            )
        ):
            log.info(
                "enrich %s skip flare pool (gaps satisfied: %s)",
                code_u,
                ",".join(gaps or []) or "-",
            )
            _enrich._push_log("跳过过盾池 · 缺口已齐")
            # 仅把本池（过盾）里还 pending 的标跳过
            flare_ids = {str(s.get("id") or "") for s in batch}
            with timings_lock:
                for i, r in enumerate(timings):
                    if str(r.get("id") or "") in flare_ids and str(
                        r.get("status") or ""
                    ) in {"pending", ""}:
                        timings[i] = {
                            **r,
                            "status": "skipped",
                            "ok": False,
                            "error": "跳过过盾池",
                        }
            _publish_timings()
            break
        part, errs, part_down, part_miss, part_busy, part_cooldown = _run_pool(
            label, batch, workers
        )
        got_all.update(part)
        errors.extend(errs)
        down_all |= part_down
        miss_all |= part_miss
        busy_all |= part_busy
        cooldown_all |= part_cooldown

    _mark_pending_skipped("未完成")
    fetch_ms = int(round((time.perf_counter() - t_fetch0) * 1000))
    # 保持启用源目录顺序，方便对照「全部数据源」
    by_id = {str(r.get("id") or ""): r for r in _timings_snapshot()}
    timings_sorted = [
        by_id[str(s.get("id") or "")]
        for s in sources
        if str(s.get("id") or "") in by_id
    ]
    # 兜底：不在 sources 里但已有记录的也附上
    seen = {str(r.get("id") or "") for r in timings_sorted}
    for r in _timings_snapshot():
        sid = str(r.get("id") or "")
        if sid and sid not in seen:
            timings_sorted.append(r)
    if timings_sorted:
        finished = [
            r
            for r in timings_sorted
            if str(r.get("status") or "") in {"done", "fail"}
        ]
        finished.sort(key=lambda r: int(r.get("ms") or 0), reverse=True)
        top = " · ".join(
            f"{r['id']} {r['ms']}ms{'✓' if r.get('ok') else '✗'}"
            for r in finished[:6]
        )
        if top:
            _enrich._push_log(f"耗时排行 · {top}")
        skip_n = sum(
            1 for r in timings_sorted if str(r.get("status") or "") == "skipped"
        )
        _enrich._push_log(
            f"拉详情合计 {fetch_ms}ms · 源 {len(timings_sorted)} 个"
            + (f" · 跳过 {skip_n}" if skip_n else "")
        )
    if not got_all:
        if errors:
            log.info("enrich detail miss %s: %s", code_u, "; ".join(errors[:6]))
        return None

    try:
        enrich_mon.set_phase(code=code_u, phase="write")
        enrich_mon.touch_sources(code=code_u, sources=_timings_snapshot())
        notify_enrich_watchers()
    except Exception:  # noqa: BLE001
        pass
    t_merge0 = time.perf_counter()
    merged = _enrich_merge._merge_got(sources, got_all, region=region)
    if merged is None:
        return None
    merge_ms = int(round((time.perf_counter() - t_merge0) * 1000))
    try:
        enrich_mon.touch_sources(code=code_u, sources=_timings_snapshot())
        notify_enrich_watchers()
    except Exception:  # noqa: BLE001
        pass
    # 批量：跳过串行译文（机翻/LLM 可占 10–30s+ 番号槽）；中文靠源站合并+映射
    # 单刷/覆盖：可走 LLM 补中文
    if not fast_zh:
        merged = _maybe_llm_fill_zh(merged) or merged
        try:
            enrich_mon.touch_sources(code=code_u, sources=_timings_snapshot())
            notify_enrich_watchers()
        except Exception:  # noqa: BLE001
            pass
        # LLM 可能改写标题/剧情：映射表再盖一次（对齐 MDCX：映射在译后仍以表为准）
        merged = (
            _enrich._apply_mdcx_maps(
                merged, code=str(merged.get("code") or code_u or "")
            )
            or merged
        )
    merged["sourceTimings"] = timings_sorted
    merged["fetchMs"] = fetch_ms
    merged["mergeMs"] = merge_ms
    # ⚠️ 「源挂了 / 我们没轮到」≠「源没有这条番号」：只有前者才值得补抓。
    # 判据：某个**没拿到**的源（down 故障 / busy 排队未及 / cooldown 源不健康被暂避）
    # 在优先级上高于所有命中源 → 本轮属于「降级取值」（高优先源抖动/被排队挤掉/
    # 被冷却跳过，结果来自更低优先的源），该番号进补抓提示；若只是尾部低优先源
    # 抖动而头部源已命中，则不打扰（否则会大面积误入重试队列）。
    # cooldown 必须并进来：它和 down 同源（由 down 连击触发），漏掉就没人回头补。
    _prio = {str(s.get("id") or ""): i for i, s in enumerate(sources)}
    _hit_ids = {str(k) for k in got_all.keys()}
    _best_hit = min((_prio.get(i, len(sources)) for i in _hit_ids), default=None)
    degraded_by_down: list[str] = []
    if _best_hit is not None:
        degraded_by_down = sorted(
            sid
            for sid in (down_all | busy_all | cooldown_all)
            if _prio.get(sid, len(sources)) < _best_hit
        )
    merged["sourcesDown"] = sorted(str(x) for x in down_all)
    merged["sourcesBusy"] = sorted(str(x) for x in busy_all)
    merged["sourcesCooldown"] = sorted(str(x) for x in cooldown_all)
    merged["sourcesMiss"] = sorted(str(x) for x in miss_all)
    merged["degradedByDown"] = degraded_by_down
    if degraded_by_down:
        log.info(
            "enrich %s degraded hit=%s down=%s busy=%s cooldown=%s",
            code_u,
            ",".join(sorted(_hit_ids)),
            ",".join(sorted(down_all)),
            ",".join(sorted(busy_all)),
            ",".join(sorted(cooldown_all)),
        )
        _enrich._push_log(
            f"降级取值 · 高优先源未拿到 {','.join(degraded_by_down)} · "
            f"命中 {','.join(sorted(_hit_ids)) or '-'}",
            region=region,
        )
    log.info(
        "enrich detail %s mode=%s ok=%s/%s hits=%s fetch=%sms merge=%sms top=%s llm=%s fast_zh=%s",
        code_u,
        mode,
        len(got_all),
        len(sources),
        ",".join(str(x) for x in (merged.get("resolvedSources") or [])[:8]),
        fetch_ms,
        merge_ms,
        ",".join(f"{r['id']}:{r['ms']}" for r in timings_sorted[:5]),
        ",".join(merged.get("llmTranslated") or []) or "-",
        bool(fast_zh),
    )
    return merged


def _find_nfo(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    preferred = [
        folder / "movie.nfo",
        folder / f"{folder.name}.nfo",
    ]
    for p in preferred:
        if p.is_file():
            return p
    nfos = sorted(folder.glob("*.nfo"))
    return nfos[0] if nfos else None


def _ensure_child(parent: ET.Element, tag: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    return el


def _resolve_enrich_folder(
    *,
    region: str = "",
    code: str = "",
    item_id: str = "",
) -> Path | None:
    """只看刮削库磁盘：rel 路径 / 分区/厂牌/番号。"""
    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root")).resolve()
    rid = _enrich._queue_log_region(region)
    code_u = str(code or "").strip().upper()
    iid = str(item_id or "").replace("\\", "/").strip().strip("/")

    def _ok_dir(p: Path) -> Path | None:
        try:
            q = p.resolve()
            q.relative_to(root)
        except ValueError:
            return None
        return q if q.is_dir() else None

    # 队列 itemId 经常就是相对目录
    if iid:
        hit = _ok_dir(root / iid)
        if hit:
            return hit
        try:
            embed_svc.ensure_schema()
            pool = get_meta_pool()
            with pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT rel_path FROM {embed_svc.TABLE}
                    WHERE item_id = %s
                    LIMIT 1
                    """,
                    (iid,),
                )
                row = cur.fetchone()
            if row:
                rel = str(
                    (row.get("rel_path") if isinstance(row, dict) else row[0]) or ""
                ).replace("\\", "/").strip().strip("/")
                if rel:
                    hit = _ok_dir(root / rel)
                    if hit:
                        return hit
        except Exception:  # noqa: BLE001
            pass

    if not code_u:
        return None
    # FC2：前缀夹是 FC2 / FC2-PPV，不能用 split('-',1)（会把 FC2-PPV-x 拆成 FC2）
    rid_n = str(rid or region or "").strip().casefold()
    if rid_n in {"fc2", "fc2ppv"} or code_u.startswith("FC2"):
        from app.core.region_meta import fc2_fs_prefix, normalize_fc2_code

        code_n = normalize_fc2_code(code_u)
        pref = fc2_fs_prefix(code=code_n)
        for base in _enrich_scan._region_local_dirs(root, rid or region):
            for cand in (
                base / pref / code_n,
                base / "FC2-PPV" / code_n,
                base / "FC2PPV" / code_n,
                base / "FC2" / code_n,
                base / code_n,
                base / code_u,
            ):
                hit = _ok_dir(cand)
                if hit:
                    return hit
        return None
    prefix = code_u.split("-", 1)[0] if "-" in code_u else code_u
    for base in _enrich_scan._region_local_dirs(root, rid or region):
        for cand in (base / prefix / code_u, base / code_u):
            hit = _ok_dir(cand)
            if hit:
                return hit
    return None
