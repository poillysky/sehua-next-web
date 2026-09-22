# -*- coding: utf-8 -*-
"""MDCx maps / LLM fill / cover job pool (extracted from enrich.py)."""
from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import app.scrap_library.enrich as _enrich

log = logging.getLogger(__name__)
def _apply_mdcx_maps(
    detail: dict[str, Any] | None,
    *,
    code: str = "",
) -> dict[str, Any] | None:
    """对齐 MDCX scraper 映射段（字段合并之后、封面之前）：

    1. translate_title_outline · c_number 色花堂标题（开关开且命中 → 覆盖）
    2. translate_actor · 演员映射表
    3. translate_info · 标签映射表
    4. （本仓库）简介连续换行精简
    """
    if not detail:
        return detail
    code_u = str(code or detail.get("code") or "").strip()
    try:
        from app.scrap_library.enrich_strategy import local_map_bool, local_map_mode

        title_mode = local_map_mode("title")
        title_on = title_mode != "off"
        actors_on = local_map_mode("actors") != "off"
        tags_on = local_map_mode("tags") != "off"
        compact_nl = local_map_bool("compactOutlineNewlines")
    except Exception:  # noqa: BLE001
        title_mode = "prefer"
        title_on = actors_on = tags_on = compact_nl = True

    fs = (
        dict(detail["fieldSources"])
        if isinstance(detail.get("fieldSources"), dict)
        else {}
    )
    applied: list[str] = []

    # 1) 演员映射（MDCX translate_actor → map_actor_names）
    if actors_on:
        try:
            from app.scrape.metadata_optimize import polish_actress_names

            acts = [str(a).strip() for a in (detail.get("actors") or []) if str(a).strip()]
            if acts:
                polished = polish_actress_names(acts, enable_mapping=True)
                if polished:
                    detail["actors"] = _enrich._unique_identity_names(polished)[:12]
                    applied.append("actors")
            # 名单仍空：番号→女优表兜底（本仓库扩展）
            if not detail.get("actors") and code_u:
                from app.core.maps_paths import lookup_code_actors

                local_a = polish_actress_names(
                    list(lookup_code_actors(code_u) or []),
                    enable_mapping=True,
                )
                local_a = _enrich._clean_actors(local_a)
                if local_a:
                    detail["actors"] = _enrich._unique_identity_names(local_a)[:12]
                    fs["actors"] = "local_code_actors"
                    applied.append("actors_code")
        except Exception:  # noqa: BLE001
            pass

    # 2) 标签映射（MDCX translate_info）
    if tags_on:
        try:
            from app.scrape.metadata_optimize import code_prefix, polish_tag_names

            tags = [str(t).strip() for t in (detail.get("tags") or []) if str(t).strip()]
            if tags:
                detail["tags"] = polish_tag_names(
                    tags,
                    exclude=list(detail.get("actors") or []),
                    prefix=code_prefix(code_u),
                    enable_mapping=True,
                )
                applied.append("tags")
        except Exception:  # noqa: BLE001
            pass

    # 3) 简介换行精简（本仓库扩展）
    if compact_nl and detail.get("overview"):
        try:
            from app.scrape.metadata_optimize import compact_outline

            detail["overview"] = compact_outline(str(detail["overview"]))
            applied.append("outline_nl")
        except Exception:  # noqa: BLE001
            pass

    # 4) 剧情里的女优异写对齐（标题在映射优选后再对齐，见下）
    try:
        acts = list(detail.get("actors") or [])
        if acts and detail.get("overview"):
            detail["overview"] = _enrich._align_llm_text_actors(
                str(detail["overview"]), acts
            )
    except Exception:  # noqa: BLE001
        pass

    # 5) 色花堂中文标题：源站先定稿，再与映射比分优选（非强制、非纯兜底）
    if title_on and code_u:
        try:
            from app.core.maps_paths import lookup_code_title

            mapped = str(lookup_code_title(code_u) or "").strip()
            if mapped:
                cur = str(detail.get("title") or "").strip()
                use_map = False
                if title_mode == "force":
                    use_map = True
                elif title_mode == "fallback":
                    use_map = (not cur) or _title_is_thin(cur, code_u)
                else:
                    # prefer（默认）：哪个分高用哪个；平手留源站
                    # 演员映射已在上方跑完，用定稿女优压「标题尾错名」
                    use_map = _enrich._title_should_prefer_map(
                        cur,
                        mapped,
                        code=code_u,
                        allowed_actors=list(detail.get("actors") or []),
                    )
                if use_map:
                    if (
                        cur
                        and _enrich._has_kana(cur)
                        and not str(detail.get("titleJa") or "").strip()
                    ):
                        detail["titleJa"] = cur
                    detail["title"] = _enrich._strip_trailing_alt_code(
                        _enrich._normalize_merged_title(mapped), code_u
                    )
                    fs["title"] = "mdcx_c_number"
                    detail["titleMapApplied"] = True
                    if title_mode == "force":
                        detail["titleMapForced"] = True
                    applied.append("title")
        except Exception:  # noqa: BLE001
            pass

    # 6) 标题尾女优异写 → 定稿名（新有菜→桥本有菜），与女优栏一致
    try:
        acts = list(detail.get("actors") or [])
        if acts and detail.get("title"):
            aligned = _enrich._align_llm_text_actors(str(detail["title"]), acts)
            if aligned != str(detail.get("title") or ""):
                detail["title"] = aligned
                applied.append("title_actor")
    except Exception:  # noqa: BLE001
        pass

    if applied:
        detail["mapsApplied"] = applied
    detail["fieldSources"] = {k: v for k, v in fs.items() if v}
    return detail


_TRAILING_ALT_CODE_RE = re.compile(
    r"(?:[\s　]+)([A-Za-z]{2,6}[-−–]?\d{2,5}[A-Za-z]?)\s*$"
)


def _polish_studio_name(name: str) -> str:
    """片商展示名：别名/假名 → makers.json（优先中文，其次英文品牌）。"""
    raw = str(name or "").strip()
    if not raw:
        return ""
    try:
        from app.scrap_library.studio_display_names import resolve_studio_display

        mapped = str(resolve_studio_display(raw) or "").strip()
        return mapped or raw
    except Exception:  # noqa: BLE001
        return raw


def _maybe_llm_fill_zh(
    detail: dict[str, Any] | None,
    *,
    prefer_llm: bool = True,
    timeout_sec: float = 90.0,
) -> dict[str, Any] | None:
    """机翻过烂或仅有日文时：大模型（失败再机翻级联）生成中文标题/剧情。"""
    if not detail:
        return detail
    try:
        from app.scrap_library.enrich_strategy import get_strategy

        strat = get_strategy()
    except Exception:  # noqa: BLE001
        strat = {}
    if not bool(strat.get("llmTranslateOnJunk", True)):
        return detail

    try:
        from app.translate.routes import translate_to_zh_sync
    except Exception as e:  # noqa: BLE001
        log.debug("llm fill import failed: %s", e)
        return detail

    fs = detail.get("fieldSources") if isinstance(detail.get("fieldSources"), dict) else {}
    fs = dict(fs)
    filled: list[str] = []
    t_lim = max(8.0, min(90.0, float(timeout_sec or 90.0)))

    title = str(detail.get("title") or "").strip()
    # 已采信映射标题时不再烧 LLM；优选模式下未采信则仍可译源站日文再比
    skip_title_llm = bool(
        detail.get("titleMapForced") or detail.get("titleMapApplied")
    )
    if (
        title
        and _enrich._text_needs_zh_llm(title, kind="title")
        and not skip_title_llm
    ):
        # 只译已校验日文：优先 titleJa；若定稿标题本身是日文也可
        src = str(detail.get("titleJa") or "").strip()
        if not src and _enrich._has_kana(title):
            src = title
        if src and _enrich._has_kana(src):
            try:
                got = translate_to_zh_sync(
                    src,
                    kind="title",
                    prefer_llm=prefer_llm,
                    timeout_sec=t_lim,
                )
                zh = _enrich._normalize_merged_title(str(got.get("text") or ""))
                eng = str(got.get("engine") or "llm")
                if _enrich._zh_fill_acceptable(zh, kind="title"):
                    detail["title"] = _enrich._strip_trailing_alt_code(
                        _enrich._align_llm_text_actors(
                            zh, list(detail.get("actors") or [])
                        ),
                        str(detail.get("code") or ""),
                    )
                    fs["title"] = f"llm:{eng}" if eng != "none" else fs.get("title") or "llm"
                    filled.append(f"title/{eng}")
            except Exception as e:  # noqa: BLE001
                log.info("enrich llm title fill skip: %s", e)

    overview = str(detail.get("overview") or "").strip()
    if overview and _enrich._text_needs_zh_llm(overview):
        src = str(detail.get("overviewJa") or "").strip()
        if not src and _enrich._has_kana(overview):
            src = overview
        if src and _enrich._has_kana(src) and len(src) >= 20:
            try:
                got = translate_to_zh_sync(
                    src,
                    kind="plot",
                    prefer_llm=prefer_llm,
                    timeout_sec=t_lim,
                )
                zh = _enrich._normalize_merged_overview(str(got.get("text") or ""))
                eng = str(got.get("engine") or "llm")
                if _enrich._zh_fill_acceptable(zh, kind="plot"):
                    detail["overview"] = _enrich._align_llm_text_actors(
                        zh, list(detail.get("actors") or [])
                    )
                    try:
                        from app.scrap_library.enrich_strategy import local_map_bool
                        from app.scrape.metadata_optimize import compact_outline

                        if local_map_bool("compactOutlineNewlines"):
                            detail["overview"] = compact_outline(
                                str(detail["overview"])
                            )
                    except Exception:  # noqa: BLE001
                        pass
                    fs["overview"] = f"llm:{eng}" if eng != "none" else fs.get("overview") or "llm"
                    filled.append(f"overview/{eng}")
            except Exception as e:  # noqa: BLE001
                log.info("enrich llm overview fill skip: %s", e)

    if filled:
        detail["fieldSources"] = {k: v for k, v in fs.items() if v}
        detail["llmTranslated"] = filled
        log.info("enrich llm fill %s → %s", detail.get("code") or "", ",".join(filled))
    return detail


_CN_TEXT_SOURCE_IDS = frozenset(
    {
        "airav",
        "airav_io",
        "iqqtv",
        "javday",
        "miss_av",
        "sevenmmtv",
        "avsex",
        "lulubar",
    }
)


def _cn_text_ids_in_batch(batch: list[dict[str, Any]]) -> set[str]:
    import app.scrape.source_catalog as catalog

    out: set[str] = set()
    for src in batch:
        sid = catalog.canonicalize_id(str(src.get("id") or ""))
        if sid in _CN_TEXT_SOURCE_IDS:
            out.add(sid)
    return out


_GAP_FIELD_PRIORITY_KEYS: dict[str, tuple[str, ...]] = {
    "thin_title": ("title",),
    # 缺中文标题与「标题太薄」是同一诉求（都要 title 字段）→ 同样提权 title 源。
    # 不加这条时，只缺 `no_zh_title` 的号不会优先发车中文源，只能靠默认顺序兜底
    # （第二十一轮对齐；与 `_enrich._may_early_stop` 的 need_zh 集合同源）
    "no_zh_title": ("title",),
    "no_plot": ("overview",),
    "no_actress": ("actors",),
    "no_studio": ("studio", "maker"),
    "no_local": ("poster",),
    "no_media": ("poster",),
}


_META_FILL_SOURCE_IDS = frozenset(
    {
        "dmm",
        "mgstage",
        "r18dev",
        "jav321",
        "libredmm",
        "avbase",
        "avwikidb",
        "prestige",
    }
)


_META_WAIT_BUDGET_SEC = 1.2


_CN_WAIT_BUDGET_SEC = 2.8


def _title_is_thin(title: str, code: str) -> bool:
    t = str(title or "").strip()
    c = str(code or "").strip()
    if not t:
        return True
    if c and t.casefold() == c.casefold():
        return True
    # 素人/无垢等官名常为 2～3 假名（案例 MUKD-244「えれな」）；勿当空题拒写
    if len(t) < 2:
        return True
    # 过短中文残片机译（DV-673「高中部」、FLAV-072「双倍的」）
    if _enrich._has_han(t) and not _enrich._has_kana(t) and len(t) <= 6:
        return True
    # 纯片假名作品名（女体のしんぴ「オナサポ」）保留，不当空题
    if re.fullmatch(r"[ァ-ヴー]{3,8}", t):
        return False
    # 纯人名感短题（ONS-029「あいら」、STZY「百仁花」）：有更长候选时应让位
    if len(t) <= 4 and not re.search(r"[\s　、，。！!？?【】\[\]「」『』（）()]", t):
        return True
    return False


def _soft_retry_fill_actors(
    *,
    code: str,
    region: str,
    folder: Path,
    nfo: Path,
    detail: dict[str, Any],
) -> list[str]:
    """软成功缺女优时轻量二次拉取（只补 actors，不重跑封面/全字段）。"""
    code_u = str(code or "").strip().upper()
    if not code_u:
        return []
    if _enrich._clean_actors(detail.get("actors")):
        return _enrich._clean_actors(detail.get("actors"))
    try:
        more = _enrich._fetch_detail(
            code_u,
            region=region,
            wait_all=False,
            gaps=["no_actress"],
            adaptive_first=True,
            fast_zh=True,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("soft actress retry fetch failed %s: %s", code_u, e)
        return []
    actors = _enrich._clean_actors((more or {}).get("actors"))
    if not actors:
        return []
    detail["actors"] = actors
    fs = detail.get("fieldSources") if isinstance(detail.get("fieldSources"), dict) else {}
    fs = dict(fs or {})
    src = str((more or {}).get("source") or (more or {}).get("provider") or "").strip()
    if src:
        fs["actors"] = src
        detail["fieldSources"] = fs
    try:
        _enrich.merge_nfo_with_detail(
            nfo,
            {"actors": actors, "code": code_u, "fieldSources": fs},
            overwrite=False,
            force_fields={"actors"},
        )
    except Exception as e:  # noqa: BLE001
        log.debug("soft actress retry merge failed %s: %s", code_u, e)
        return actors
    _enrich._push_log(
        f"{code_u} · 软成功补女优 · {len(actors)} · {src or '-'}",
        region=region,
    )
    return actors


def _get_cover_job_pool():
    """封面独立任务池（同进程）；线程数按上限常开，实际并发由闸门限制。"""
    with _enrich._cover_job_pool_lock:
        if _enrich._cover_job_pool is None:
            from app.core.container_budget import cap_parallel

            cover_n = cap_parallel(
                int(_enrich._COVER_JOB_WORKERS),
                tight=2,
                small=4,
                hard=int(_enrich._COVER_JOB_WORKERS),
            )
            _enrich._cover_job_pool = ThreadPoolExecutor(
                max_workers=max(2, cover_n),
                thread_name_prefix="cover-job",
            )
        return _enrich._cover_job_pool


@contextmanager
def _cover_job_slot() -> Any:
    """限制同时进行的整番号封面任务数（可随 itemWorkers 热变）。"""
    target = _enrich._cover_job_workers_target()
    with _enrich._cover_gate_lock:
        _enrich._cover_gate_target = target
        while _enrich._cover_gate_inflight >= _enrich._cover_gate_target:
            _enrich._cover_gate_lock.wait(timeout=0.4)
            # 等待期间策略可能变：刷新目标
            _enrich._cover_gate_target = _enrich._cover_job_workers_target()
        _enrich._cover_gate_inflight += 1
    try:
        yield
    finally:
        with _enrich._cover_gate_lock:
            _enrich._cover_gate_inflight = max(0, int(_enrich._cover_gate_inflight) - 1)
            _enrich._cover_gate_lock.notify_all()
