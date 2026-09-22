# -*- coding: utf-8 -*-
"""enrich_merge —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

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
import app.scrap_library.enrich_detail as _enrich_detail
import app.scrap_library.enrich_sidecar as _enrich_sidecar
import app.scrap_library.enrich_text as _enrich_text
from app.scrap_library.enrich_junk import _JUNK_TITLE_MARKERS
from app.scrap_library.enrich_job_control import _fill_mode_to_job_mode
from app.scrap_library.enrich_runtime import (
    _enrich_job,
    _enrich_lock,
    _persist_enrich_runtime,
    _strategy_epoch,
    _strategy_epoch_mu,
    bump_strategy_epoch,
    notify_enrich_watchers,
)


def _halt_kind() -> str | None:
    with _enrich._enrich_lock:
        halt = _enrich._enrich_job.get("halt")
        if halt in {"pause", "stop"}:
            return str(halt)
        if _enrich._enrich_job.get("cancel"):
            # 旧 cancel 视为暂停（保留进度）
            return "pause"
        return None


def current_strategy_epoch() -> int:
    with _enrich._strategy_epoch_mu:
        return int(_enrich._strategy_epoch)


def _note_strategy_hot_if_needed(region: str = "") -> None:
    """若策略刚保存过：本条起用新源，打一条日志（整轮只提示一次）。"""
    ep = current_strategy_epoch()
    if ep <= 0:
        return
    with _enrich._enrich_lock:
        applied = int(_enrich._enrich_job.get("strategyEpochApplied") or 0)
        if ep <= applied:
            return
        _enrich._enrich_job["strategyEpochApplied"] = ep
        running = bool(_enrich._enrich_job.get("running"))
    srcs = _enrich_detail._detail_sources(region=region)
    ids = [str(s.get("id") or "").strip() for s in srcs if str(s.get("id") or "").strip()]
    label = " → ".join(ids[:14]) if ids else "(无启用源)"
    if len(ids) > 14:
        label += "…"
    tip = f"策略热更新 · 本条起用新数据源 · {label}"
    _enrich._push_log(tip, region=region or "")
    if running:
        try:
            _enrich.notify_enrich_watchers(force=True)
        except Exception:  # noqa: BLE001
            pass


def apply_live_strategy(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """策略刚保存：暂停任务同步 fillMode；运行中 bump epoch，下一番号热切源。

    详情/封面/超时本就按 get_strategy 热读；此处负责提示 + 检查点 mode。
    """
    try:
        from app.scrap_library.enrich_strategy import get_strategy

        data = cfg if isinstance(cfg, dict) else get_strategy()
    except Exception:  # noqa: BLE001
        data = cfg if isinstance(cfg, dict) else {}
    mode_norm = _enrich._fill_mode_to_job_mode(str((data or {}).get("fillMode") or ""))
    ep = _enrich.bump_strategy_epoch()
    mode_changed = False
    paused_like = False
    running = False
    regions: list[str] = []
    cur_region = ""
    with _enrich._enrich_lock:
        running = bool(_enrich._enrich_job.get("running"))
        cur_region = str(_enrich._enrich_job.get("currentRegion") or "").strip()
        prev_mode = str(_enrich._enrich_job.get("jobMode") or "")
        if prev_mode != mode_norm:
            _enrich._enrich_job["jobMode"] = mode_norm
            mode_changed = True
        # 强制下一番号重新打热更新日志
        _enrich._enrich_job["strategyEpochApplied"] = max(0, ep - 1)
        cps = dict(_enrich._enrich_job.get("checkpoints") or {})
        new_cps: dict[str, Any] = {}
        for rid, cp in cps.items():
            if not isinstance(cp, dict):
                continue
            row = dict(cp)
            if str(row.get("mode") or "") != mode_norm:
                row["mode"] = mode_norm
                mode_changed = True
            new_cps[str(rid)] = row
            regions.append(str(rid))
        if new_cps:
            _enrich._enrich_job["checkpoints"] = new_cps
        phase = str(_enrich._enrich_job.get("phase") or "")
        halt = _enrich._enrich_job.get("halt")
        paused_like = bool(new_cps) or phase == "paused" or halt == "pause"
        if paused_like:
            prog = dict(_enrich._enrich_job.get("progress") or {})
            prog["label"] = "已暂停 · 新策略已生效"
            _enrich._enrich_job["progress"] = prog
            if phase == "paused" or halt == "pause":
                _enrich._enrich_job["phase"] = "paused"
        elif running:
            prog = dict(_enrich._enrich_job.get("progress") or {})
            if prog:
                prog["label"] = str(prog.get("label") or "补齐中") + " · 策略已更新"
                _enrich._enrich_job["progress"] = prog
    if mode_changed:
        try:
            _enrich._persist_enrich_runtime()
        except Exception:  # noqa: BLE001
            pass
    # 无论 mode 是否变（可能只改了数据源），都提示
    if running:
        tip = f"策略已热更新 #{ep} · 下一番号起用新数据源/超时（{mode_norm}）"
        _enrich._push_log(tip, region=cur_region or (regions[0] if regions else ""))
    elif paused_like:
        tip = f"策略已更新 · 续跑用最新配置（{mode_norm}）"
        if regions:
            for rid in regions[:8]:
                _enrich._push_log(tip, region=rid)
        else:
            _enrich._push_log(tip)
    else:
        _enrich._push_log(f"策略已保存（{mode_norm}）")
    try:
        _enrich.notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "applied": True,
        "epoch": ep,
        "mode": mode_norm,
        "paused": paused_like,
        "running": running,
    }


def _field_priority_applies(region: str = "") -> bool:
    """字段优先级仅对有码区生效；其它区只看「优先级设置(全局)」分区源。"""
    try:
        from app.scrape.sources_settings import resolve_enrich_region_id

        return resolve_enrich_region_id(region) == "japan_censored"
    except Exception:  # noqa: BLE001
        return False


def _strategy_field_priority(field: str, *, region: str = "") -> list[str] | None:
    if region and not _field_priority_applies(region):
        return None
    try:
        from app.scrap_library.enrich_strategy import get_strategy
        from app.scrape.sources_settings import is_provider_enabled

        fp = get_strategy().get("fieldPriority") or {}
        chain = fp.get(field) if isinstance(fp, dict) else None
        if isinstance(chain, list) and chain:
            # 总开关关闭的源：配置里可留着，合并时一律跳过
            return [str(x) for x in chain if is_provider_enabled(str(x))]
    except Exception:  # noqa: BLE001
        pass
    return None


def _strategy_region_sources(region: str, *, code: str = "") -> list[str]:
    try:
        from app.scrap_library.enrich_strategy import (
            region_sources_for,
            uncensored_official_for_code,
        )
        from app.scrape.sources_settings import (
            is_provider_enabled,
            resolve_enrich_region_id,
        )

        base = [
            s
            for s in (region_sources_for(region) or [])
            if is_provider_enabled(s)
        ]
        rid = resolve_enrich_region_id(region)
        if rid == "japan_uncensored" and code:
            official = [
                s
                for s in (uncensored_official_for_code(code) or [])
                if is_provider_enabled(s)
            ]
            if official:
                seen: set[str] = set()
                out: list[str] = []
                for sid in list(official) + base:
                    if not sid or sid in seen:
                        continue
                    seen.add(sid)
                    out.append(sid)
                return out
        return base
    except Exception:  # noqa: BLE001
        return []


def _merge_source_allowed(source_id: str) -> bool:
    """合并候选是否可用：本地伪源放行；真实站须开着总开关。"""
    sid = str(source_id or "").strip()
    if not sid:
        return False
    # 本地伪源 / 映射表：不走数据源总开关
    if (
        sid.startswith("local_")
        or sid.startswith("mdcx_")
        or sid in {"manual", "nfo", "cache", "mdcx_c_number"}
    ):
        return True
    try:
        from app.scrape.sources_settings import is_provider_enabled

        return is_provider_enabled(sid)
    except Exception:  # noqa: BLE001
        return True


def _pick_by_field_priority(
    candidates: list[tuple[str, str, int]],
    field: str,
    *,
    min_score: int | None = None,
    region: str = "",
) -> tuple[str, str] | None:
    """字段优先级选值。

    有码区：
    1) 字段配置源（设置「字段优先级」）按顺序 —— 已关总开关的跳过
    2) 番号类型全局源（设置「全局优先级」）按顺序 —— 同上
    3) 其余站按可信度链；配置/全局阶段有数据即用

    其它区：跳过字段优先级，只走全局分区源 + 可信度链。
    """
    import app.scrape.source_catalog as catalog

    usable = [
        (catalog.canonicalize_id(sid), str(val or "").strip(), int(score))
        for sid, val, score in candidates
        if str(val or "").strip() and _merge_source_allowed(str(sid or ""))
    ]
    if not usable:
        return None

    by_sid: dict[str, list[tuple[str, int]]] = {}
    for sid, val, score in usable:
        by_sid.setdefault(sid, []).append((val, score))

    preferred = [
        catalog.canonicalize_id(s)
        for s in (_strategy_field_priority(field, region=region) or [])
        if catalog.canonicalize_id(s)
    ]
    pref_seen: set[str] = set()
    preferred_u: list[str] = []
    for sid in preferred:
        if sid not in pref_seen:
            pref_seen.add(sid)
            preferred_u.append(sid)

    region_chain: list[str] = []
    region_seen: set[str] = set()
    for sid in _strategy_region_sources(region):
        cs = catalog.canonicalize_id(sid)
        if cs and cs not in region_seen and cs not in pref_seen:
            region_seen.add(cs)
            region_chain.append(cs)

    def _first_ok(sids: list[str], *, use_margin: bool) -> tuple[str, str] | None:
        best_score = max(sc for _s, _v, sc in usable)
        for sid in sids:
            for val, score in by_sid.get(sid) or []:
                if min_score is not None and score < min_score:
                    continue
                if field == "overview" and score < 0:
                    continue
                if use_margin:
                    if field == "title":
                        margin = 8
                    elif field == "overview":
                        margin = 5
                    else:
                        margin = 35
                    if best_score - score > margin:
                        continue
                return val, sid
        return None

    # 1) 字段配置源
    if preferred_u:
        hit = _first_ok(preferred_u, use_margin=False)
        if hit:
            return hit

    # 2) 番号类型全局有序源
    if region_chain:
        hit = _first_ok(region_chain, use_margin=False)
        if hit:
            return hit

    # 3) 其余
    chain = catalog.field_priority_chain(
        field, override=preferred_u or None
    )
    skip = pref_seen | region_seen
    rest = [
        s
        for s in chain
        if s not in skip and _merge_source_allowed(s)
    ]
    hit = _first_ok(rest, use_margin=True)
    if hit:
        return hit

    return _enrich_text._pick_best_str(usable)


def _merge_got(
    sources: list[dict[str, Any]],
    got: dict[str, dict[str, Any]],
    *,
    region: str = "",
    probe: bool = False,
) -> dict[str, Any] | None:
    """多源字段级可信合并：每字段取 trust+质量 最高；女优/标签并集。

    probe=True：早停探测用轻量合并（跳过标签精修/extras），避免 as_completed
    主线程被反复全量合并拖死。
    """
    import app.scrape.source_catalog as catalog

    try:
        from app.scrap_library.enrich_strategy import local_map_mode

        actors_map_mode = local_map_mode("actors")
        tags_map_mode = local_map_mode("tags")
    except Exception:  # noqa: BLE001
        actors_map_mode = "fallback"
        tags_map_mode = "fallback"
    actors_map_on = actors_map_mode != "off"
    tags_map_on = tags_map_mode != "off"

    order_hit: list[str] = []
    details: list[tuple[str, dict[str, Any]]] = []
    for src in sources:
        raw_id = str(src.get("id") or "")
        sid = catalog.canonicalize_id(raw_id)
        detail = got.get(sid) or got.get(raw_id)
        if not detail:
            continue
        key = sid or raw_id
        order_hit.append(key)
        details.append((key, dict(detail)))
    if not details:
        # got 可能只按返回 id 存、sources 顺序不同：兜底遍历 got
        for sid, detail in got.items():
            if not detail:
                continue
            cid = catalog.canonicalize_id(str(sid))
            order_hit.append(cid)
            details.append((cid, dict(detail)))
    if not details:
        return None

    code = ""
    for _, d in details:
        code = str(d.get("code") or d.get("id") or "").strip().upper()
        if code:
            break

    details, rejected_ids = _enrich_detail._identity_gate_details(code, details)
    if not details:
        return None

    title_cands: list[tuple[str, str, int]] = []
    studio_cands: list[tuple[str, str, int]] = []
    maker_cands: list[tuple[str, str, int]] = []
    overview_cands: list[tuple[str, str, int]] = []
    date_cands: list[tuple[str, str, int]] = []
    year_cands: list[tuple[str, str, int]] = []
    poster_cands_scored: list[tuple[str, str, int]] = []
    # 封面候选（带源站），供下载阶段优先池/全局池
    poster_entries: list[dict[str, str]] = []
    actor_lists: list[tuple[str, list[str], int]] = []
    tag_lists: list[tuple[str, list[str], int]] = []
    all_poster_urls: list[str] = []

    for sid, d in details:
        title = str(d.get("title") or "").strip()
        if title:
            title_cands.append((sid, title, _enrich_text._score_title(title, code=code, source_id=sid)))
        # 部分源（iqqtv）把中文标题放在 extra.titleZh
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        title_zh = str((extra or {}).get("titleZh") or "").strip()
        if title_zh and title_zh != title:
            title_cands.append(
                (sid, title_zh, _enrich_text._score_title(title_zh, code=code, source_id=sid))
            )
        # code-titles 映射不在此注入：源站先合并定稿，再于 _enrich._apply_mdcx_maps 优选/兜底/强制
        studio = str(d.get("studio") or "").strip()
        if studio:
            studio_cands.append((sid, studio, _enrich_text._score_studio(studio, source_id=sid)))
        maker = str(d.get("maker") or d.get("studio") or "").strip()
        if maker:
            maker_cands.append(
                (sid, maker, catalog.field_trust(sid, "maker") + (6 if maker else 0))
            )
        overview = str(d.get("overview") or "").strip()
        if overview:
            # 先收集原文，女优定稿后再打分（防串台剧情）
            overview_cands.append((sid, overview, 0))
        date_s = str(d.get("date") or "").strip()
        if date_s:
            date_cands.append((sid, date_s, _enrich_text._score_date(date_s, source_id=sid)))
        year = str(d.get("year") or "").strip()
        if year:
            year_cands.append((sid, year, _enrich_text._score_year(year, source_id=sid)))
        poster = str(d.get("posterUrl") or d.get("poster") or "").strip()
        for u in list(d.get("posterCandidates") or []) + [poster]:
            s = str(u or "").strip()
            if s.startswith(("http://", "https://")):
                if s not in all_poster_urls:
                    all_poster_urls.append(s)
                poster_entries.append({"source": sid, "url": s})
        if poster.startswith(("http://", "https://")):
            poster_cands_scored.append(
                (sid, poster, _enrich_text._score_poster(poster, source_id=sid))
            )
        actors = _enrich._clean_actors(d.get("actors"))
        # fetch 阶段已 polish 的源不再重跑；未标记的（E2E/预取）才映射
        if actors and not d.get("_actorsPolished"):
            try:
                from app.scrape.metadata_optimize import polish_actress_names

                directors: list[str] = []
                d0 = str(d.get("director") or "").strip()
                if d0:
                    directors.append(d0)
                for raw_d in d.get("directors") or []:
                    if isinstance(raw_d, dict):
                        n = str(raw_d.get("name") or "").strip()
                    else:
                        n = str(raw_d or "").strip()
                    if n:
                        directors.append(n)
                actors = polish_actress_names(
                    actors,
                    exclude=directors,
                    enable_mapping=actors_map_on,
                )
            except Exception:  # noqa: BLE001
                pass
        if actors:
            actor_lists.append((sid, actors, _enrich_text._score_actors(actors, source_id=sid)))
        tags = [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()]
        if tags:
            tag_lists.append((sid, tags, _enrich_text._score_tags(tags, source_id=sid)))

    # 本地番号→女优映射（av_metadata 导出）：作为候选源参与共识投票，
    # provider 们都没给出演员时兜底；与 mdcx_c_number 标题兜底同规格。
    if (
        actors_map_on
        and code
        and not any(sid == "local_code_actors" for sid, _a, _s in actor_lists)
    ):
        try:
            from app.core.maps_paths import lookup_code_actors
            from app.scrape.metadata_optimize import polish_actress_names

            local_actors = polish_actress_names(
                list(lookup_code_actors(code)), enable_mapping=True
            )
            local_actors = _enrich._clean_actors(local_actors)
            if local_actors:
                actor_lists.append(
                    (
                        "local_code_actors",
                        local_actors,
                        _enrich_text._score_actors(local_actors, source_id="local_code_actors"),
                    )
                )
        except Exception:  # noqa: BLE001
            pass

    field_sources: dict[str, str] = {}
    merged: dict[str, Any] = {"code": code} if code else {}
    if rejected_ids:
        merged["identityRejected"] = list(rejected_ids)

    # 标量字段：字段优先级链首个合格非空（Amane）；女优仍用共识投票
    # 标题：有可用中文时跳过假名原文，避免 airav 等中文位源回落日文占链首、再烧 LLM
    title_pick_cands = title_cands
    usable_zh_titles = [
        (sid, t, sc)
        for sid, t, sc in title_cands
        if _enrich_text._zh_prefer_bonus(str(t or "")) > 0
        # 标题允许轻度 ○ 伏字罚分（kind=title）；真机翻腔仍 < -20 踢出
        and _enrich_text._mt_junk_penalty(str(t or ""), kind="title") >= -20
        and not _enrich._title_is_thin(str(t or ""), code)
    ]
    if usable_zh_titles:
        title_pick_cands = usable_zh_titles
    picked = _pick_by_field_priority(title_pick_cands, "title", region=region)
    if picked:
        title_v, title_src = picked
        merged["title"] = _enrich_text._strip_trailing_alt_code(
            _enrich_text._normalize_merged_title(title_v), code
        )
        field_sources["title"] = title_src
    # 定稿仍空或仍薄：回落全候选里「规范化后仍可用」的最高分
    if _enrich._title_is_thin(str(merged.get("title") or ""), code) and title_cands:
        ranked = sorted(title_cands, key=lambda x: -x[2])
        for sid, raw, _sc in ranked:
            cand = _enrich_text._strip_trailing_alt_code(_enrich_text._normalize_merged_title(str(raw or "")), code)
            if _enrich._title_is_thin(cand, code):
                continue
            merged["title"] = cand
            field_sources["title"] = sid
            break
    # 色花堂标题覆盖改在合并末尾 _enrich._apply_mdcx_maps（对齐 MDCX translate_title_outline）
    # 保留最佳日文标题，供机翻过烂时 LLM 回译（须与定稿标题兼容）
    jp_title_cands = [
        (sid, t, sc)
        for sid, t, sc in title_cands
        if _enrich_text._has_kana(str(t or ""))
    ]
    if jp_title_cands:
        jp_picked = _pick_by_field_priority(jp_title_cands, "title", region=region)
        ja = ""
        if jp_picked:
            ja = str(jp_picked[0] or "").strip()
        if not ja:
            jp_title_cands.sort(key=lambda x: -x[2])
            ja = str(jp_title_cands[0][1] or "").strip()
        final_t = str(merged.get("title") or "").strip()
        # 日文标题若有多源共识，则即便与「中文机翻定稿」措辞不同也采信：
        # 否则后续标题门禁会把全部日文源挡在标签/剧情合并之外，导致内容塌缩
        # （NSPS-015：定稿是 miss_av 机翻，titleJa 空 → 只剩 miss_av 的 3 个标签）。
        ja_votes = 0
        if ja:
            for _jid, _jt, _jsc in jp_title_cands:
                tt = str(_jt or "").strip()
                if not tt:
                    continue
                if tt == ja or _enrich_text._titles_compatible(
                    tt, ja, actors=_enrich_text._actor_hints_from_titles([tt, ja])
                ):
                    ja_votes += 1
        if ja and (
            not final_t
            or _enrich_text._has_kana(final_t)
            or _enrich_text._titles_compatible(ja, final_t, actors=_enrich_text._actor_hints_from_titles([ja, final_t]))
            or ja_votes >= 2
        ):
            merged["titleJa"] = ja
    picked = _pick_by_field_priority(studio_cands, "studio", region=region)
    if picked:
        merged["studio"], field_sources["studio"] = picked
    picked = _pick_by_field_priority(maker_cands, "maker", region=region)
    if picked:
        merged["maker"], field_sources["maker"] = picked
    elif merged.get("studio"):
        merged["maker"] = merged["studio"]
        field_sources["maker"] = field_sources.get("studio") or ""
    # 合并后再映射展示名（评分仍用源站原串，避免映射后改分）
    studio_raw = str(merged.get("studio") or "").strip()
    maker_raw = str(merged.get("maker") or "").strip()
    if studio_raw:
        merged["studio"] = _enrich._polish_studio_name(studio_raw)
    if maker_raw:
        if maker_raw == studio_raw:
            merged["maker"] = str(merged.get("studio") or "")
        else:
            merged["maker"] = _enrich._polish_studio_name(maker_raw)
    elif merged.get("studio"):
        merged["maker"] = merged["studio"]
    # overview 延后到女优共识后再选
    picked = _pick_by_field_priority(date_cands, "date", region=region)
    if picked:
        merged["date"], field_sources["date"] = picked
    picked = _pick_by_field_priority(year_cands, "year", region=region)
    if picked:
        merged["year"], field_sources["year"] = picked

    # 封面：候选按质量排序；主图沿 poster 优先级链；下载用带 source 的详细列表
    all_poster_urls.sort(key=_enrich_cover._poster_rank, reverse=True)
    if all_poster_urls:
        merged["posterCandidates"] = all_poster_urls[:8]
    # 去重保序；再按「字段优先级 · 海报」排序，下载优先池严格跟设置
    seen_pu: set[str] = set()
    detailed: list[dict[str, str]] = []
    for ent in poster_entries:
        u = ent.get("url") or ""
        if u in seen_pu:
            continue
        seen_pu.add(u)
        detailed.append(ent)
    poster_fp = [
        catalog.canonicalize_id(s)
        for s in (_strategy_field_priority("poster", region=region) or [])
        if catalog.canonicalize_id(s)
    ]
    poster_fp_rank = {sid: i for i, sid in enumerate(poster_fp)}

    def _poster_entry_key(ent: dict[str, str]) -> tuple[int, int]:
        sid = catalog.canonicalize_id(str(ent.get("source") or ""))
        src_i = poster_fp_rank.get(sid, 10_000)
        return (src_i, -_enrich_cover._poster_rank(str(ent.get("url") or "")))

    detailed.sort(key=_poster_entry_key)
    if detailed:
        merged["posterCandidatesDetailed"] = detailed[:32]
    best_poster = _pick_by_field_priority(poster_cands_scored, "poster", region=region)
    if best_poster:
        merged["posterUrl"], field_sources["poster"] = best_poster
    elif all_poster_urls:
        merged["posterUrl"] = all_poster_urls[0]
        field_sources["poster"] = ""

    # 女优：跨源「共识」合并——先各源映射到标准名，再按出现源数投票。
    # 避免 javlibrary 错页女优与正确源并集成一长串（SDMUA-008 案例）。
    # 身份门禁已清空的源（无 title）不参与女优投票。
    actors_out: list[str] = []
    rejected_set = {str(x) for x in (rejected_ids or [])}
    actor_lists = [
        (sid, names, sc)
        for sid, names, sc in actor_lists
        if sid not in rejected_set and names
    ]
    # 二次过滤：该源标题已被 gate 清空则跳过
    # （local_code_actors 是番号精确键入的本地映射，身份安全，豁免标题过滤）
    titles_alive = {
        sid
        for sid, d in details
        if str(d.get("title") or "").strip()
        or (
            isinstance(d.get("extra"), dict)
            and str((d.get("extra") or {}).get("titleZh") or "").strip()
        )
    }
    titles_alive.add("local_code_actors")
    if titles_alive:
        actor_lists = [
            (sid, names, sc)
            for sid, names, sc in actor_lists
            if sid in titles_alive
        ]
    if actor_lists:
        from collections import Counter

        actor_lists.sort(key=lambda x: x[2], reverse=True)
        field_sources["actors"] = actor_lists[0][0]
        # 按身份键投票（日/中/别名同人只算一票/源）
        vote: Counter[str] = Counter()
        display_for: dict[str, str] = {}
        order_ids: list[str] = []
        for _sid, names, _sc in actor_lists:
            seen_src: set[str] = set()
            for a in _enrich_text._unique_identity_names(list(names or [])):
                _disp, kid = _enrich_text._actress_disp_id(a)
                if not kid or kid in seen_src:
                    continue
                seen_src.add(kid)
                if kid not in display_for:
                    display_for[kid] = a
                    order_ids.append(kid)
                vote[kid] += 1
        n_src = len(actor_lists)
        need = 3 if n_src >= 5 else 2
        consensus_ids = [kid for kid in order_ids if vote[kid] >= need]
        if consensus_ids:
            actors_out = [display_for[kid] for kid in consensus_ids][:12]
            # 高分源名单是共识超集时并入缺员（身份去重）
            top_names = _enrich_text._unique_identity_names(list(actor_lists[0][1] or []))
            cons_ids = set(consensus_ids)
            top_ids = {_enrich_text._actress_disp_id(a)[1] for a in top_names}
            if cons_ids and cons_ids <= top_ids and len(top_names) > len(actors_out):
                actors_out = top_names[:12]
        else:
            title_src = str(field_sources.get("title") or "")
            prefer = next(
                (names for sid, names, _sc in actor_lists if sid == title_src),
                None,
            )
            actors_out = _enrich_text._unique_identity_names(
                list(prefer or actor_lists[0][1])
            )[:12]
    # 标题用 × 点名的女优：演员栏常漏（SDMU-088 四人只刮到两人）→ 并入
    title_hay = " ".join(
        [
            str(merged.get("title") or ""),
            str(merged.get("titleJa") or ""),
            *[str(t) for _sid, t, _sc in title_cands[:12]],
        ]
    )
    title_names = _enrich_text._names_from_title_pairs(title_hay)
    if title_names:
        try:
            from app.scrape.metadata_optimize import polish_actress_names

            mentioned = polish_actress_names(
                title_names, enable_mapping=actors_map_on
            )
            mentioned_ids = {
                _enrich_text._actress_disp_id(n)[1] for n in mentioned if _enrich_text._actress_disp_id(n)[1]
            }
            have = list(actors_out)
            have_ids = {
                _enrich_text._actress_disp_id(n)[1] for n in have if _enrich_text._actress_disp_id(n)[1]
            }
            for _sid, names, _sc in actor_lists:
                for n in names:
                    ns = str(n or "").strip()
                    kid = _enrich_text._actress_disp_id(ns)[1]
                    if ns and kid in mentioned_ids and kid not in have_ids:
                        have.append(ns)
                        have_ids.add(kid)
            for n in mentioned:
                kid = _enrich_text._actress_disp_id(n)[1]
                if kid and kid not in have_ids:
                    have.append(n)
                    have_ids.add(kid)
            if have:
                actors_out = _enrich_text._unique_identity_names(have)[:12]
        except Exception:  # noqa: BLE001
            for n in title_names:
                if n not in actors_out:
                    actors_out.append(n)
            actors_out = _enrich_text._unique_identity_names(actors_out)[:12]
    # 收口映射一次：别名/繁简收敛 + 去重（身份主名，不强制中文）
    try:
        from app.scrape.metadata_optimize import polish_actress_names

        polished = polish_actress_names(
            actors_out, enable_mapping=actors_map_on
        )
        merged["actors"] = polished if polished else _enrich_text._unique_identity_names(actors_out)
    except Exception:  # noqa: BLE001
        merged["actors"] = _enrich_text._unique_identity_names(actors_out)

    # 按身份簇+各源人数收口（不再从标题尾猜人名）
    actor_lists_for_alias = actor_lists
    try:
        raw_sides: list[tuple[str, list[str], int]] = []
        for sid, d in details:
            raw_a = _enrich._clean_actors(d.get("actors"))
            if not raw_a:
                continue
            sc = next((s2 for s, n, s2 in actor_lists if s == sid), 0)
            raw_sides.append((sid, raw_a, int(sc or 0)))
        if raw_sides:
            actor_lists_for_alias = raw_sides + [
                (sid, names, sc)
                for sid, names, sc in actor_lists
                if sid not in {s for s, _, _ in raw_sides}
            ]
    except Exception:  # noqa: BLE001
        pass
    pair_n = len(
        _enrich_text._unique_identity_names(_enrich_text._names_from_title_pairs(title_hay) if title_hay else [])
    )
    collapsed, alias_extra = _enrich_text._collapse_few_actress_variants(
        list(merged.get("actors") or []),
        actor_lists_for_alias,
        title_pair_n=pair_n,
    )
    if collapsed and not merged.get("actorsMapForced"):
        merged["actors"] = collapsed
    # 最终再按身份去重，防止别名残留双写
    merged["actors"] = _enrich_text._unique_identity_names(list(merged.get("actors") or []))[:12]
    if (
        alias_extra
        and len(merged["actors"]) == 1
        and not merged.get("actorsMapForced")
    ):
        # 供女优档案 upsert：主名以外的跨源异写
        primary_fold = merged["actors"][0].casefold()
        merged["actorAliases"] = [
            a for a in alias_extra if a and a.casefold() != primary_fold
        ][:16]
        field_sources["actorsNote"] = "singleton_collapse"
    elif "actorAliases" in merged:
        merged.pop("actorAliases", None)

    # 剧情：结合本片女优名单，惩罚串入其他女优名的中文灌水剧情（STAR-795）
    # 并丢弃与已选标题明显不是同一作品的源剧情（ABF-005：ジュポニカ错页）
    allowed_for_plot: list[str] = list(merged.get("actors") or [])
    for _sid, names, _sc in actor_lists:
        for a in names:
            s = str(a or "").strip()
            if s and s not in allowed_for_plot:
                allowed_for_plot.append(s)
    for a in alias_extra or []:
        s = str(a or "").strip()
        if s and s not in allowed_for_plot:
            allowed_for_plot.append(s)
    title_by_sid: dict[str, str] = {}
    for sid, t, _sc in title_cands:
        prev = title_by_sid.get(sid) or ""
        if len(str(t or "")) > len(prev):
            title_by_sid[sid] = str(t or "")
    anchors = [
        str(merged.get("title") or "").strip(),
        str(merged.get("titleJa") or "").strip(),
    ]
    anchors = [a for a in anchors if a]

    def _overview_source_ok(sid: str) -> bool:
        if not anchors:
            return True
        st = title_by_sid.get(sid) or ""
        if not st:
            return True
        acts = list(merged.get("actors") or [])
        return any(_enrich_text._titles_compatible(st, a, actors=acts) for a in anchors)

    overview_scored = [
        (
            sid,
            ov,
            _enrich_text._score_overview(ov, source_id=sid, allowed_actors=allowed_for_plot)
            + (
                -80
                if (
                    str(merged.get("title") or "").strip()
                    and str(ov or "").strip()
                    and (
                        str(ov).strip() == str(merged.get("title") or "").strip()
                        or (
                            len(str(ov).strip()) <= len(str(merged.get("title") or "").strip())
                            + 4
                            and str(merged.get("title") or "").strip() in str(ov).strip()
                            and len(str(ov).strip()) < 40
                        )
                    )
                )
                else 0
            ),
        )
        for sid, ov, _ in overview_cands
        if _overview_source_ok(sid)
    ]
    # 空壳水印被打到负分后：若标题门禁又挡掉日文长剧情，只剩伪剧情 → 回落全源最高分
    overview_usable = [x for x in overview_scored if int(x[2]) >= 0]
    if not overview_usable:
        overview_scored = [
            (
                sid,
                ov,
                _enrich_text._score_overview(ov, source_id=sid, allowed_actors=allowed_for_plot),
            )
            for sid, ov, _ in overview_cands
        ]
        overview_usable = [x for x in overview_scored if int(x[2]) >= 0] or list(
            overview_scored
        )
    # 与标题同规：有可用中文剧情时只在中文池里走优先级链，避免链首日文
    # 以 margin≤5 反压更高分中文（XRW-394：airav_io@120 日文压过 miss_av@125 中文）。
    overview_pick_cands = overview_usable
    usable_zh_ovs = [
        (sid, ov, sc)
        for sid, ov, sc in overview_usable
        if _enrich_text._zh_prefer_bonus(str(ov or "")) > 0
        and _enrich_text._mt_junk_penalty(str(ov or "")) >= 0
    ]
    if usable_zh_ovs:
        overview_pick_cands = usable_zh_ovs
    picked = _pick_by_field_priority(overview_pick_cands, "overview", region=region)
    if picked:
        ov_v, ov_src = picked
        # 链首仍可能是水印空壳（负分）：强制换成全源最高分
        pick_sc = next(
            (
                int(sc)
                for sid, ov, sc in overview_pick_cands
                if sid == ov_src and ov == ov_v
            ),
            -10_000,
        )
        if pick_sc < 0 and overview_pick_cands:
            best = max(overview_pick_cands, key=lambda x: int(x[2]))
            if int(best[2]) > pick_sc:
                ov_v, ov_src = best[1], best[0]
        merged["overview"] = _enrich_text._normalize_merged_overview(ov_v)
        field_sources["overview"] = ov_src
    jp_ov = [
        (sid, ov, sc)
        for sid, ov, sc in overview_scored
        if _enrich_text._has_kana(str(ov or "")) and int(sc) >= 0
    ]
    if jp_ov:
        jp_picked = _pick_by_field_priority(jp_ov, "overview", region=region)
        ja_ov = str((jp_picked[0] if jp_picked else "") or "").strip()
        if not ja_ov:
            jp_ov.sort(key=lambda x: -x[2])
            ja_ov = str(jp_ov[0][1] or "").strip()
        final_ov = str(merged.get("overview") or "").strip()
        if ja_ov and (
            not final_ov
            or _enrich_text._has_kana(final_ov)
            or _enrich_text._titles_compatible(
                ja_ov[:80],
                final_ov[:80],
                actors=list(merged.get("actors") or []),
            )
        ):
            merged["overviewJa"] = ja_ov

    tags_out: list[str] = []
    seen_t: set[str] = set()
    if tag_lists:
        # 标签：配置优先源整套打底（顺序如 JavBus→AVBase）；否则按分最高源打底
        tag_lists = [
            (sid, tags, sc)
            for sid, tags, sc in tag_lists
            if _overview_source_ok(sid) and _merge_source_allowed(str(sid))
        ]
        pref_tags = [
            catalog.canonicalize_id(s)
            for s in (_strategy_field_priority("tags", region=region) or [])
            if catalog.canonicalize_id(s)
        ]
        # 字段未配标签源时：用番号类型全局顺序打底
        if not pref_tags:
            pref_tags = [
                catalog.canonicalize_id(s)
                for s in _strategy_region_sources(region)
                if catalog.canonicalize_id(s)
            ]
        if pref_tags:
            by_tags = {
                catalog.canonicalize_id(sid): (list(tags), int(sc))
                for sid, tags, sc in tag_lists
            }
            ordered_tags: list[tuple[str, list[str], int]] = []
            seen_tag_src: set[str] = set()
            for sid in pref_tags:
                hit = by_tags.get(sid)
                if hit and sid not in seen_tag_src:
                    ordered_tags.append((sid, hit[0], hit[1]))
                    seen_tag_src.add(sid)
            for sid, tags, sc in sorted(tag_lists, key=lambda x: -x[2]):
                cs = catalog.canonicalize_id(sid)
                if cs not in seen_tag_src:
                    ordered_tags.append((cs, list(tags), int(sc)))
                    seen_tag_src.add(cs)
            tag_lists = ordered_tags
        else:
            tag_lists.sort(key=lambda x: x[2], reverse=True)
        if tag_lists:
            field_sources["tags"] = tag_lists[0][0]
        base_zh = 0
        for i, (_sid, tags, _sc) in enumerate(tag_lists):
            for raw in tags:
                t = _enrich_text._normalize_tag_alias(str(raw or "").strip())
                if not t:
                    continue
                # 字形归一（繁简/异体/日文旧字），再去重：
                # 否则「穿衣幹砲」与「穿衣干炮」等异体会同时留在合并结果里
                t = _enrich_text._fold_tag_variant(t)
                # 已有足够中文底时，跳过带假名的日文标签
                if i > 0 and base_zh >= 3 and _enrich_text._has_kana(t):
                    continue
                k = t.casefold()
                if k in seen_t:
                    continue
                seen_t.add(k)
                tags_out.append(t)
                if _enrich_text._zh_prefer_bonus(t) > 0:
                    base_zh += 1
                if len(tags_out) >= 24:
                    break
            if len(tags_out) >= 24:
                break
        if not probe:
            try:
                from app.scrape.metadata_optimize import (
                    code_prefix,
                    polish_tag_names,
                )

                # 排除集用「全源女优名并集」(allowed_for_plot)，而非只排最终 merged 名单：
                # 合集/BEST 里没进最终名单的女优名也会被源站当标签塞进来
                # （CJOB-134：javbus 标签含 ERINA/AIKA/久留木玲，落在最终 12 人名单外 → 漏删）
                # 注意：禁止在热路径 clear_map_cache——多番号并发会反复冷加载
                # actors/tags 大表，把早停探测拖到几十秒。
                tags_out = polish_tag_names(
                    tags_out,
                    exclude=list(allowed_for_plot) + list(title_names or []),
                    prefix=code_prefix(code),
                    enable_mapping=tags_map_on,
                )
            except Exception:  # noqa: BLE001
                pass
    merged["tags"] = tags_out

    # 禁止从标签/标题硬套女优：无 <actor>/actors 字段则保持空

    contrib = list(dict.fromkeys(order_hit))
    merged["sources"] = contrib
    merged["source"] = field_sources.get("title") or (
        contrib[0] if contrib else merged.get("source")
    )
    merged["provider"] = merged.get("source")
    merged["resolvedSources"] = contrib
    merged["fieldSources"] = {k: v for k, v in field_sources.items() if v}

    if probe:
        # 早停探测：只补色花堂标题（常为中文，可免等 airav），不做标签/演员二次精修
        if code:
            try:
                from app.core.maps_paths import lookup_code_title

                mapped = str(lookup_code_title(code) or "").strip()
                cur = str(merged.get("title") or "").strip()
                if mapped and (
                    not cur
                    or _enrich._title_is_thin(cur, code)
                    or (
                        _enrich_text._zh_prefer_bonus(mapped) > 0
                        and _enrich_text._zh_prefer_bonus(cur) <= 0
                    )
                ):
                    if cur and _enrich_text._has_kana(cur) and not merged.get("titleJa"):
                        merged["titleJa"] = cur
                    merged["title"] = _enrich_text._strip_trailing_alt_code(
                        _enrich_text._normalize_merged_title(mapped), code
                    )
                    fs = dict(merged.get("fieldSources") or {})
                    fs["title"] = "mdcx_c_number"
                    merged["fieldSources"] = fs
                    merged["titleMapApplied"] = True
            except Exception:  # noqa: BLE001
                pass
        # 轻量补系列/发行/官网等，供早停判断「元数据是否已齐」
        try:
            from app.scrap_library.enrich_extras import pick_secondary_fields

            for k, v in pick_secondary_fields(details).items():
                if v and not merged.get(k):
                    merged[k] = v
        except Exception:  # noqa: BLE001
            pass
        return merged

    # MDCX 映射段：色花堂标题 → 演员 → 标签 → 简介换行（封面下载之前）
    merged = _enrich._apply_mdcx_maps(merged, code=code) or merged

    # I41–I52 择优后处理
    try:
        from app.scrap_library.enrich_extras import apply_merge_extras

        apply_merge_extras(
            merged,
            details=details,
            actor_lists=list(actor_lists or []),
            region=region,
        )
    except Exception:  # noqa: BLE001
        pass
    # extras 可能改标题/女优：再收口一次映射，保证表最终生效
    merged = _enrich._apply_mdcx_maps(merged, code=code) or merged
    return merged


_FIELD_LAUNCH_ORDER: tuple[str, ...] = (
    "title",
    "overview",
    "actors",
    "studio",
    "maker",
    "poster",
    "tags",
)


def _merge_enrich_sidecar_into_item(
    item: dict[str, Any],
    *,
    folder: Path | None = None,
    region: str = "",
) -> dict[str, Any]:
    """把本地 {CODE}.log 合并进队列行（不覆盖已有源耗时）。"""
    if not isinstance(item, dict):
        return item
    has_timings = isinstance(item.get("sourceTimings"), list) and bool(
        item.get("sourceTimings")
    )
    has_src_fields = isinstance(item.get("fields"), list) and any(
        isinstance(f, dict) and str(f.get("source") or "").strip()
        for f in (item.get("fields") or [])
    )
    if has_timings and has_src_fields:
        return item

    fol = folder
    if fol is None:
        fol = _enrich_detail._resolve_enrich_folder(
            region=region or str(item.get("region") or ""),
            code=str(item.get("code") or ""),
            item_id=str(
                item.get("itemId")
                or item.get("relPath")
                or item.get("rel_path")
                or ""
            ),
        )
    if fol is None:
        return item
    data = _enrich_sidecar.read_enrich_sidecar(fol, code=str(item.get("code") or ""))
    if not data:
        return item

    if not has_timings and isinstance(data.get("sourceTimings"), list):
        item["sourceTimings"] = list(data.get("sourceTimings") or [])
    if not item.get("fields") and isinstance(data.get("fields"), list):
        item["fields"] = list(data.get("fields") or [])
    elif (
        not has_src_fields
        and isinstance(data.get("fields"), list)
        and data.get("fields")
    ):
        item["fields"] = list(data.get("fields") or [])

    src = str(item.get("source") or "").strip()
    side_src = str(data.get("source") or "").strip()
    if side_src and (not src or src in {"local_scan", "scan", "log_recover", "recover"}):
        item["source"] = side_src

    if not str(item.get("detailTitle") or "").strip():
        title = str(data.get("detailTitle") or "").strip()
        if title:
            item["detailTitle"] = title[:300]

    for k in (
        "posterDownloaded",
        "vectorSynced",
        "vectorSkipped",
        "coverMs",
        "actressMs",
        "vectorMs",
        "fetchMs",
        "totalMs",
        "partialOk",
    ):
        if item.get(k) is None and data.get(k) is not None:
            item[k] = data.get(k)

    if data.get("gapsAfter") and not item.get("gapsAfter"):
        item["gapsAfter"] = list(data.get("gapsAfter") or [])
    return item


def _set_text_if_empty(parent: ET.Element, tag: str, value: str, *, force: bool = False) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    el = parent.find(tag)
    cur = "".join(el.itertext()).strip() if el is not None else ""
    if cur and not force:
        return False
    node = _enrich_detail._ensure_child(parent, tag)
    node.text = text
    return True


def _merge_list_tags(
    parent: ET.Element, tag: str, values: list[str], *, max_n: int = 16
) -> bool:
    existing = {
        "".join(el.itertext()).strip().casefold()
        for el in parent.findall(tag)
        if "".join(el.itertext()).strip()
    }
    changed = False
    for raw in values:
        v = str(raw or "").strip()
        if not v or v.casefold() in existing:
            continue
        el = ET.SubElement(parent, tag)
        el.text = v
        existing.add(v.casefold())
        changed = True
        if len(existing) >= max_n:
            break
    return changed


def _merge_actors(parent: ET.Element, names: list[str], *, max_n: int = 12) -> bool:
    # 先清掉已写入的标签/登录页噪声，再合并新名单
    pruned = _enrich_text._prune_junk_actors(parent)
    existing: set[str] = set()
    for a in parent.findall("actor"):
        nm = a.find("name")
        if nm is None:
            continue
        text = "".join(nm.itertext()).strip()
        if text:
            existing.add(text.casefold())
    changed = pruned
    for raw in _enrich._clean_actors(names):
        name = str(raw or "").strip()
        if not name or name.casefold() in existing:
            continue
        actor = ET.SubElement(parent, "actor")
        nm_el = ET.SubElement(actor, "name")
        nm_el.text = name
        existing.add(name.casefold())
        changed = True
        if len(existing) >= max_n:
            break
    return changed


def merge_nfo_with_detail(
    nfo_path: Path,
    detail: dict[str, Any],
    *,
    overwrite: bool = False,
    force_fields: set[str] | None = None,
    existing_root: ET.Element | None = None,
    existing_fields: dict[str, Any] | None = None,
    old_bytes: bytes | None = None,
) -> bool:
    """增量仅补空；覆盖模式写入新值。最终按 MDCx 参考布局整文件重排写出。

    force_fields：增量下仍强制写回的字段名集合（title/overview/actors/…）。
    existing_root / existing_fields / old_bytes：调用方已读过文件时跳过二次解析。
    """
    if existing_fields is not None:
        fields = existing_fields
        if old_bytes is None:
            old_bytes = b""
    else:
        old_bytes = b"" if old_bytes is None else old_bytes
        root = existing_root
        if root is None:
            if nfo_path.is_file():
                try:
                    old_bytes = nfo_path.read_bytes()
                    root = ET.fromstring(
                        old_bytes.decode("utf-8", errors="replace")
                    )
                except Exception:
                    root = ET.Element("movie")
            else:
                root = ET.Element("movie")
        if root.tag.lower() != "movie":
            movie = root.find("movie")
            root = movie if movie is not None else ET.Element("movie")
        code_pre = str(detail.get("code") or detail.get("id") or "").strip().upper()
        fields = _enrich.fields_from_movie_root(root, code_fallback=code_pre)

    force = bool(overwrite)
    ff = {str(x).strip().lower() for x in (force_fields or set()) if str(x).strip()}

    def _force(*keys: str) -> bool:
        return force or any(k in ff for k in keys)

    def _put(key: str, value: str, *, do_force: bool) -> None:
        v = str(value or "").strip()
        if not v:
            return
        cur = str(fields.get(key) or "").strip()
        if cur and not do_force:
            return
        fields[key] = v

    code = str(detail.get("code") or detail.get("id") or "").strip().upper()
    if code:
        _put("num", code, do_force=force)

    title = str(detail.get("title") or "").strip()
    if title and title.upper() != code and not any(
        m in title.casefold() for m in (x.casefold() for x in _enrich._JUNK_TITLE_MARKERS)
    ):
        cur_title = str(fields.get("title") or "")
        force_title = _force("title") or _enrich._title_is_thin(cur_title, code)
        if title.strip() and not _enrich._title_is_thin(title, code):
            _put("title", title, do_force=force_title)

    studio = _enrich._polish_studio_name(
        str(detail.get("studio") or detail.get("maker") or "").strip()
    )
    if studio:
        _put("studio", studio, do_force=_force("studio"))
        _put("maker", studio, do_force=_force("studio"))

    director = str(detail.get("director") or "").strip()
    if not director:
        for d in detail.get("directors") or []:
            if isinstance(d, dict):
                n = str(d.get("name") or "").strip()
            else:
                n = str(d or "").strip()
            if n:
                director = n
                break
    if director:
        _put("director", director, do_force=force)

    runtime = str(detail.get("runtime") or "").strip()
    if runtime:
        _put("runtime", runtime, do_force=force)

    score = str(detail.get("score") or detail.get("rating") or "").strip()
    if score:
        _put("rating", score, do_force=force)
        # 派生分数字段随 rating 刷新
        if force or not str(fields.get("criticrating") or "").strip():
            fields["criticrating"] = ""
            fields["ratings_value"] = ""

    title_ja = str(detail.get("titleJa") or "").strip()
    if title_ja:
        _put("originaltitle", title_ja, do_force=_force("title"))
        if _force("title") or not str(fields.get("sorttitle") or "").strip():
            fields["sorttitle"] = title_ja

    overview_ja = str(detail.get("overviewJa") or "").strip()
    if overview_ja:
        _put("originalplot", overview_ja, do_force=_force("overview"))

    plot = str(detail.get("overview") or "").strip()
    if plot:
        _put("plot", plot, do_force=_force("overview"))
        _put("outline", plot, do_force=_force("overview"))
        if _force("overview") or not str(fields.get("originalplot") or "").strip():
            # 无日文剧情时用中文填 originalplot（参考库常三者同文）
            if not overview_ja:
                _put("originalplot", plot, do_force=_force("overview"))

    year = str(detail.get("year") or "").strip()
    if year:
        _put("year", year, do_force=force)
    date_s = str(detail.get("date") or "").strip()
    if date_s:
        _put("premiered", date_s, do_force=force)
        _put("releasedate", date_s, do_force=force)
        _put("release", date_s, do_force=force)
        if force or not str(fields.get("tagline") or "").strip():
            fields["tagline"] = f"发行日期: {date_s}"
        if not year and len(date_s) >= 4 and date_s[:4].isdigit():
            _put("year", date_s[:4], do_force=force)

    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    if poster.startswith(("http://", "https://")):
        _put("cover", poster, do_force=_force("poster"))

    series = str(detail.get("series") or detail.get("set") or "").strip()
    if series:
        _put("series", series, do_force=force)
    publisher = str(
        detail.get("publisher") or detail.get("label") or ""
    ).strip()
    if publisher:
        _put("publisher", publisher, do_force=force)
        _put("label", publisher, do_force=force)
    trailer = str(
        detail.get("trailer") or detail.get("trailerUrl") or ""
    ).strip()
    if trailer:
        _put("trailer", trailer, do_force=force)
    website = str(detail.get("website") or detail.get("url") or "").strip()
    if website:
        _put("website", website, do_force=force)

    actors = _enrich._clean_actors(detail.get("actors"))
    actors_all = _enrich._clean_actors(detail.get("actorsAll"))
    if actors_all and not actors:
        actors = list(actors_all)
    # 禁止从 tags/标题硬套女优
    try:
        from app.scrape.metadata_optimize import polish_actress_names

        ban = [director] if director else []
        actors = polish_actress_names(actors, exclude=ban)
    except Exception:  # noqa: BLE001
        pass
    if _force("actors"):
        fields["actors"] = list(actors)
    elif actors:
        existing = [str(a).strip() for a in (fields.get("actors") or []) if str(a).strip()]
        # 已有 actor 也滤一遍垃圾标签
        existing = _enrich._clean_actors(existing)
        seen = {a.casefold() for a in existing}
        for a in actors:
            if a.casefold() not in seen:
                existing.append(a)
                seen.add(a.casefold())
        fields["actors"] = existing
    else:
        # 无真实女优：清掉历史上从标签写入的垃圾 <actor>
        existing = _enrich._clean_actors(
            [str(a).strip() for a in (fields.get("actors") or []) if str(a).strip()]
        )
        fields["actors"] = existing

    tags = _enrich_text._clean_tags(detail.get("tags"))
    # 已是女优的人名不再留在 genre
    act_fold = {
        str(a).casefold()
        for a in (fields.get("actors") or actors or [])
        if str(a).strip()
    }
    if act_fold:
        tags = [t for t in tags if t.casefold() not in act_fold]
    if _force("tags"):
        fields["genres"] = list(tags)
    elif tags:
        existing_g = [
            str(g).strip() for g in (fields.get("genres") or []) if str(g).strip()
        ]
        seen_g = {g.casefold() for g in existing_g}
        for t in tags:
            if t.casefold() not in seen_g and t.casefold() not in act_fold:
                existing_g.append(t)
                seen_g.add(t.casefold())
        fields["genres"] = existing_g

    # 默认图文件名（参考库固定）
    fields.setdefault("poster", "poster.jpg")
    fields.setdefault("thumb", "thumb.jpg")
    fields.setdefault("fanart", "fanart.jpg")
    fields.setdefault("countrycode", "JP")
    fields.setdefault("customrating", "JP-18+")
    fields.setdefault("mpaa", "JP-18+")

    if not str(fields.get("num") or "").strip() and not nfo_path.is_file():
        return False

    new_root = _enrich.build_mdcx_nfo_root(fields)
    new_bytes = format_nfo_xml(new_root)
    if old_bytes and old_bytes == new_bytes:
        return False
    # 无旧文件且几乎空壳
    if not old_bytes and not str(fields.get("num") or "").strip():
        return False
    _enrich.write_nfo(nfo_path, new_root)
    return True
