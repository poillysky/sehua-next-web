# -*- coding: utf-8 -*-
"""刮削库元数据补全：按配置片商源拉详情 → 写回 NFO/封面 → 重嵌入。"""

from __future__ import annotations

import logging
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import scrap_library_embed as embed_svc
from .ai_config import resolve_embed_config
from .ai_embed import encode_texts_sync
from .db import get_meta_pool, media_dir
from .scrap_library_nfo import parse_nfo

log = logging.getLogger(__name__)

_ENRICH_KINDS = (
    "no_local",
    "no_media",
    "no_actress",
    "no_studio",
    "no_plot",
    "thin_title",
)

# 完整补齐：封面 + 女优/片商/剧情/标题等元数据缺口
_DEFAULT_ENRICH_KINDS = tuple(_ENRICH_KINDS)

_JUNK_TITLE_MARKERS = (
    "会员登入",
    "會員登入",
    "会员登录",
    "請先登入",
    "请先登录",
    "login",
    "sign in",
    "just a moment",
    "attention required",
    "access denied",
    "403 forbidden",
    "404",
    "cloudflare",
)

_JUNK_ACTORS = frozenset(
    {
        "女优",
        "女優",
        "演员",
        "演員",
        "actor",
        "actress",
        "未知",
        "暫無",
        "暂无",
        "有碼",
        "有码",
        "無碼",
        "无码",
        "注册一个新帐户",
        "忘記密碼?",
        "忘记密码?",
        "登入你的帐户",
        "登入你的帳戶",
    }
)

_JUNK_ACTOR_SUBSTR = (
    "登入",
    "登录",
    "密码",
    "密碼",
    "注册",
    "註冊",
    "排行",
    "login",
    "password",
    "sign in",
    "forgot",
)


def _clean_actors(names: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = str(raw or "").strip()
        if not name or len(name) > 40:
            continue
        key = name.casefold()
        if key in _JUNK_ACTORS or key in seen:
            continue
        if name in _JUNK_TITLE_MARKERS:
            continue
        if any(s in name for s in _JUNK_ACTOR_SUBSTR):
            continue
        seen.add(key)
        out.append(name)
    return out

_JUNK_TAGS = frozenset(
    {
        "中文",
        "vr",
        "有码",
        "有碼",
        "无码",
        "無碼",
        "会员",
        "登入",
        "登录",
        "首页",
        "home",
        "jav",
        "av",
    }
)


def _clean_tags(tags: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = str(raw or "").strip()
        if not tag or len(tag) > 30:
            continue
        key = tag.casefold()
        if key in _JUNK_TAGS or key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


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
    if _title_is_thin(title, code_u) and not (
        detail.get("posterUrl") or detail.get("overview") or _clean_actors(detail.get("actors"))
    ):
        return False
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    overview = str(detail.get("overview") or "").strip()
    studio = str(detail.get("studio") or detail.get("maker") or "").strip()
    actors = _clean_actors(detail.get("actors"))
    tags = _clean_tags(detail.get("tags"))
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


_enrich_lock = threading.Lock()
_enrich_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}


def get_enrich_status() -> dict[str, Any]:
    with _enrich_lock:
        return {
            "running": bool(_enrich_job["running"]),
            "phase": _enrich_job.get("phase") or "",
            "progress": _enrich_job.get("progress"),
            "log": list(_enrich_job.get("log") or [])[-12:],
            "result": _enrich_job.get("result"),
            "error": _enrich_job.get("error"),
        }


def _push_log(msg: str) -> None:
    with _enrich_lock:
        log_list = list(_enrich_job.get("log") or [])
        log_list.append(str(msg))
        _enrich_job["log"] = log_list[-40:]


def _set_progress(**kwargs: Any) -> None:
    with _enrich_lock:
        cur = dict(_enrich_job.get("progress") or {})
        cur.update(kwargs)
        _enrich_job["progress"] = cur
        if kwargs.get("label"):
            _enrich_job["phase"] = str(kwargs["label"])


def _detail_sources(*, region: str = "") -> list[dict[str, Any]]:
    """数据源页：七区对应分组 ∩ 已启用 ∩ 有详情实现，按目录顺序。"""
    from . import scrape_sources_settings as scrape_src

    return list(scrape_src.enabled_enrich_sources(region=region) or [])


def _poster_rank(url: str) -> int:
    """封面 URL 质量：mono 实图 > 一般 pl > digital 占位。"""
    u = str(url or "").strip().lower()
    if not u.startswith(("http://", "https://")):
        return 0
    if "/mono/movie/" in u:
        return 5
    if "jdbstatic.com/covers" in u or "/cover" in u:
        return 4
    if u.endswith("pl.jpg") or "_b.jpg" in u or "bigImage" in u:
        return 3
    # DMM digital 常返回很小的空图，合并时勿压过 mono
    if "/digital/video/" in u:
        return 1
    return 2


def _merge_detail_fields(
    base: dict[str, Any], extra: dict[str, Any]
) -> dict[str, Any]:
    """并发结果按目录顺序合并：只补空，不覆盖已有非空（封面按质量可升级）。"""
    out = dict(base)
    for key in (
        "title",
        "studio",
        "maker",
        "overview",
        "date",
        "year",
    ):
        cur = out.get(key)
        empty = cur is None or (isinstance(cur, str) and not str(cur).strip())
        if empty and extra.get(key):
            out[key] = extra.get(key)
    # 封面：允许更高质量 URL 覆盖占位；保留候选供下载回退
    cur_p = str(out.get("posterUrl") or "").strip()
    new_p = str(extra.get("posterUrl") or extra.get("poster") or "").strip()
    cands: list[str] = []
    for u in list(out.get("posterCandidates") or []) + list(
        extra.get("posterCandidates") or []
    ) + [cur_p, new_p]:
        s = str(u or "").strip()
        if s.startswith(("http://", "https://")) and s not in cands:
            cands.append(s)
    cands.sort(key=_poster_rank, reverse=True)
    if cands:
        out["posterCandidates"] = cands[:8]
        out["posterUrl"] = cands[0]
    # title 过空时允许用更好标题覆盖
    code = str(out.get("code") or extra.get("code") or "")
    if _title_is_thin(str(out.get("title") or ""), code) and extra.get("title"):
        if not _title_is_thin(str(extra.get("title") or ""), code):
            out["title"] = extra.get("title")
    actors = list(out.get("actors") or [])
    seen = {str(a).casefold() for a in actors}
    for a in extra.get("actors") or []:
        s = str(a or "").strip()
        if s and s.casefold() not in seen:
            actors.append(s)
            seen.add(s.casefold())
    out["actors"] = actors[:20]
    tags = list(out.get("tags") or [])
    seen_t = {str(t).casefold() for t in tags}
    for t in extra.get("tags") or []:
        s = str(t or "").strip()
        if s and s.casefold() not in seen_t:
            tags.append(s)
            seen_t.add(s.casefold())
    out["tags"] = tags[:40]
    # 记录贡献源
    contrib = list(out.get("sources") or [])
    src = str(extra.get("source") or extra.get("provider") or "")
    if src and src not in contrib:
        contrib.append(src)
    out["sources"] = contrib
    return out


def _detail_has_poster(detail: dict[str, Any] | None) -> bool:
    if not detail:
        return False
    return bool(str(detail.get("posterUrl") or "").strip())


def _merge_got(
    sources: list[dict[str, Any]], got: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    merged: dict[str, Any] | None = None
    order_hit: list[str] = []
    for src in sources:
        sid = str(src.get("id") or "")
        detail = got.get(sid)
        if not detail:
            continue
        order_hit.append(sid)
        if merged is None:
            merged = dict(detail)
            merged["sources"] = [sid]
            p0 = str(merged.get("posterUrl") or "").strip()
            if p0 and not merged.get("posterCandidates"):
                merged["posterCandidates"] = [p0]
        else:
            merged = _merge_detail_fields(merged, detail)
    if merged is None:
        return None
    merged["source"] = order_hit[0] if order_hit else merged.get("source")
    merged["provider"] = merged.get("source")
    merged["resolvedSources"] = order_hit
    return merged


def _fetch_detail(code: str, *, region: str = "") -> dict[str, Any] | None:
    """对匹配且已启用的数据源按策略并发拉详情，再按目录顺序合并补空。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from . import scrap_enrich_strategy as strat
    from . import scrape_sources_settings as scrape_src
    from .scrape_details import fetch_detail_for_source

    code_u = str(code or "").strip().upper()
    if not code_u:
        return None
    sources = _detail_sources(region=region)
    if not sources:
        log.info(
            "enrich: no enabled sources for region=%r groups=%s",
            region,
            scrape_src.enrich_groups_for_region(region),
        )
        return None

    cfg = strat.get_strategy()
    mode = str(cfg.get("mode") or "parallel_all")
    include_flare = bool(cfg.get("includeFlare", True))
    adapt_cfg = int(cfg.get("adaptiveWorkers") if cfg.get("adaptiveWorkers") is not None else 0)
    flare_cfg = int(cfg.get("flareWorkers") if cfg.get("flareWorkers") is not None else 0)

    adaptive = [s for s in sources if str(s.get("access") or "") != "proxy_flare"]
    flare = [s for s in sources if str(s.get("access") or "") == "proxy_flare"]
    if not include_flare or mode == "adaptive_only":
        flare = []

    adapt_n = strat.resolve_pool_workers(adapt_cfg, len(adaptive))
    flare_n = strat.resolve_pool_workers(flare_cfg, len(flare)) if flare else 0

    if mode == "adaptive_only":
        pools = [("adaptive", adaptive, adapt_n)]
    elif mode == "adaptive_first":
        pools = [("adaptive", adaptive, adapt_n), ("flare", flare, flare_n)]
    else:
        # parallel_all：该番号匹配源一起并发；adaptiveWorkers=0 则全开
        all_batch = adaptive + flare
        all_n = strat.resolve_pool_workers(adapt_cfg, len(all_batch))
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

    def _one(src: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str]:
        from . import outbound_http

        # 与「包含过盾源」开关一致：关则禁止本线程内 curl 失败再打 Flare
        outbound_http.set_thread_allow_flare(include_flare)
        sid = str(src.get("id") or "")
        try:
            applied = scrape_src.apply_provider_link_for_fetch(sid)
        except Exception as e:  # noqa: BLE001
            return sid, None, f"link:{e}"
        try:
            detail = fetch_detail_for_source(
                sid,
                code_u,
                base_url=str(applied.get("baseUrl") or src.get("baseUrl") or ""),
                cookie=str(applied.get("cookie") or src.get("cookie") or ""),
                api_key=str(applied.get("apiKey") or src.get("apiKey") or ""),
            )
            if not _detail_usable(detail, code=code_u):
                return sid, None, f"rejected:{(detail or {}).get('title')}"
            detail = dict(detail)
            detail["actors"] = _clean_actors(detail.get("actors"))
            detail["tags"] = _clean_tags(detail.get("tags"))
            detail["source"] = detail.get("source") or sid
            detail["provider"] = detail.get("provider") or sid
            detail["resolvedBase"] = applied.get("baseUrl") or src.get("baseUrl")
            detail["access"] = applied.get("access") or src.get("access")
            return sid, detail, ""
        except HTTPException as e:
            return sid, None, str(e.detail)
        except Exception as e:  # noqa: BLE001
            return sid, None, str(e)

    def _run_pool(
        label: str, batch: list[dict[str, Any]], workers: int
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        if not batch or workers <= 0:
            return {}, []
        got: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        n = max(1, min(workers, len(batch)))
        pool = ThreadPoolExecutor(
            max_workers=n, thread_name_prefix=f"enrich-{label}"
        )
        futs = [pool.submit(_one, src) for src in batch]
        early = False
        try:
            for fut in as_completed(futs):
                try:
                    sid, detail, err = fut.result()
                except Exception as e:  # noqa: BLE001
                    errors.append(str(e))
                    continue
                if detail:
                    got[sid] = detail
                    # 已有可用封面就提前收工，别等最慢源/过盾拖满超时
                    if _detail_has_poster(detail):
                        early = True
                        log.info(
                            "enrich %s early-stop pool=%s hit=%s poster",
                            code_u,
                            label,
                            sid,
                        )
                        break
                elif err:
                    errors.append(f"{sid}:{err}")
        finally:
            for f in futs:
                f.cancel()
            # 不阻塞等剩余慢请求（过盾 45s+）；后台线程自然结束
            pool.shutdown(wait=False, cancel_futures=True)
        if early:
            errors = [e for e in errors if "cancelled" not in e.lower()]
        return got, errors

    got_all: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for label, batch, workers in pools:
        if not batch:
            continue
        # adaptive_first：已有封面则跳过 Flare 池，避免无意义过盾
        if (
            mode == "adaptive_first"
            and label == "flare"
            and _detail_has_poster(_merge_got(sources, got_all))
        ):
            log.info("enrich %s skip flare pool (poster already)", code_u)
            break
        part, errs = _run_pool(label, batch, workers)
        got_all.update(part)
        errors.extend(errs)

    if not got_all:
        if errors:
            log.info("enrich detail miss %s: %s", code_u, "; ".join(errors[:6]))
        return None

    merged = _merge_got(sources, got_all)
    if merged is None:
        return None
    log.info(
        "enrich detail %s mode=%s ok=%s/%s hits=%s",
        code_u,
        mode,
        len(got_all),
        len(sources),
        ",".join(str(x) for x in (merged.get("resolvedSources") or [])[:8]),
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


def _title_is_thin(title: str, code: str) -> bool:
    t = str(title or "").strip()
    c = str(code or "").strip()
    if not t:
        return True
    if len(t) < 4:
        return True
    if c and t.casefold() == c.casefold():
        return True
    return False


def _set_text_if_empty(parent: ET.Element, tag: str, value: str, *, force: bool = False) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    el = parent.find(tag)
    cur = "".join(el.itertext()).strip() if el is not None else ""
    if cur and not force:
        return False
    node = _ensure_child(parent, tag)
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
    existing: set[str] = set()
    for a in parent.findall("actor"):
        nm = a.find("name")
        if nm is None:
            continue
        text = "".join(nm.itertext()).strip()
        if text:
            existing.add(text.casefold())
    changed = False
    for raw in names:
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


def merge_nfo_with_detail(nfo_path: Path, detail: dict[str, Any]) -> bool:
    """仅补空字段；返回是否有改动。"""
    if nfo_path.is_file():
        try:
            raw = nfo_path.read_text(encoding="utf-8", errors="replace")
            root = ET.fromstring(raw)
        except Exception:
            root = ET.Element("movie")
    else:
        root = ET.Element("movie")
    if root.tag.lower() != "movie":
        movie = root.find("movie")
        root = movie if movie is not None else ET.Element("movie")

    changed = False
    title = str(detail.get("title") or "").strip()
    code = str(detail.get("code") or detail.get("id") or "").strip().upper()
    studio = str(detail.get("studio") or detail.get("maker") or "").strip()
    plot = str(detail.get("overview") or "").strip()
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    year = str(detail.get("year") or "").strip()
    date_s = str(detail.get("date") or "").strip()
    actors = _clean_actors(detail.get("actors"))
    tags = _clean_tags(detail.get("tags"))

    if code:
        changed = _set_text_if_empty(root, "num", code) or changed
    if title and title.upper() != code and not any(
        m in title.casefold() for m in (x.casefold() for x in _JUNK_TITLE_MARKERS)
    ):
        cur_title = ""
        te = root.find("title")
        if te is not None:
            cur_title = "".join(te.itertext()).strip()
        force_title = _title_is_thin(cur_title, code)
        if title.strip() and not _title_is_thin(title, code):
            changed = (
                _set_text_if_empty(root, "title", title, force=force_title) or changed
            )
    if studio:
        changed = _set_text_if_empty(root, "studio", studio) or changed
        changed = _set_text_if_empty(root, "maker", studio) or changed
    if plot:
        changed = _set_text_if_empty(root, "plot", plot) or changed
        changed = _set_text_if_empty(root, "outline", plot) or changed
    if year:
        changed = _set_text_if_empty(root, "year", year) or changed
    if date_s:
        changed = _set_text_if_empty(root, "premiered", date_s) or changed
        changed = _set_text_if_empty(root, "releasedate", date_s) or changed
    if poster.startswith(("http://", "https://")):
        changed = _set_text_if_empty(root, "cover", poster) or changed
    if actors:
        changed = _merge_actors(root, actors) or changed
    if tags:
        changed = _merge_list_tags(root, "genre", tags) or changed

    if not changed and not nfo_path.is_file():
        # 新建空壳也算变更
        if code:
            _ensure_child(root, "num").text = code
            changed = True

    if not changed:
        return False

    nfo_path.parent.mkdir(parents=True, exist_ok=True)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    nfo_path.write_bytes(xml)
    return True


def _dmm_poster_fallbacks(url: str) -> list[str]:
    """digital 空图时尝试 mono 实图路径。"""
    u = str(url or "").strip()
    out: list[str] = []
    m = re.search(
        r"pics\.dmm\.co\.jp/digital/video/([^/]+)/\1pl\.jpg", u, re.I
    )
    if m:
        cid = m.group(1)
        # 常见：sspd00024 → sspd024；去掉中间多余 0
        short = re.sub(r"^([a-z]+)0+(\d+)$", r"\1\2", cid, flags=re.I)
        for name in (short, cid):
            out.append(f"https://pics.dmm.co.jp/mono/movie/adult/{name}/{name}pl.jpg")
            out.append(f"http://pics.dmm.co.jp/mono/movie/adult/{name}/{name}pl.jpg")
    return out


def _download_covers(
    folder: Path, cover_url: str | list[str]
) -> tuple[str, str]:
    """返回 (poster_rel, thumb_rel)；支持多候选 URL 依次尝试。"""
    raw_list = cover_url if isinstance(cover_url, list) else [cover_url]
    urls: list[str] = []
    for u in raw_list:
        s = str(u or "").strip()
        if not s.startswith(("http://", "https://")):
            continue
        if s not in urls:
            urls.append(s)
        for alt in _dmm_poster_fallbacks(s):
            if alt not in urls:
                urls.append(alt)
    # 质量高的先试
    urls.sort(key=_poster_rank, reverse=True)

    poster = ""
    thumb = ""
    used = ""
    for url in urls:
        poster = embed_svc.download_remote_poster(folder, url) or ""
        if poster:
            used = url
            break
    if not used:
        return "", ""

    thumb_file = folder / "thumb.jpg"
    if not thumb_file.is_file() or embed_svc._is_blank_cover_file(thumb_file):  # noqa: SLF001
        got = embed_svc._fetch_cover_bytes(used)  # noqa: SLF001
        if got:
            data, _ctype = got
            try:
                thumb_file.write_bytes(data)
                thumb = embed_svc._media_rel(thumb_file)  # noqa: SLF001
            except OSError:
                pass
    elif thumb_file.is_file():
        thumb = embed_svc._media_rel(thumb_file)  # noqa: SLF001
    return poster, thumb


def reingest_folder(folder: Path) -> dict[str, Any] | None:
    """单目录 NFO 重扫并写回向量库。"""
    nfo = _find_nfo(folder)
    if not nfo:
        return None
    cfg = resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        # 仅更新封面路径等元数据，不写向量
        meta = parse_nfo(nfo)
        return {"ok": True, "embedded": False, "title": meta.get("title")}

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    media_root = media_dir()
    scrap_rel = ""
    try:
        scrap_rel = root.relative_to(media_root.resolve()).as_posix()
    except ValueError:
        scrap_rel = (
            str(settings.get("root") or "scrap-library").replace("\\", "/").strip("/")
        )

    model = str(cfg["model"])
    dim = int(cfg["dim"])
    item = embed_svc._scan_one_nfo(  # noqa: SLF001
        nfo,
        root=root,
        model=model,
        dim=dim,
        media_root=media_root,
        scrap_rel=scrap_rel,
    )
    if not item:
        return None
    vecs = encode_texts_sync([item["source_text"]], query=False)
    if not vecs or len(vecs[0]) != dim:
        raise RuntimeError("向量编码失败")
    vec_lit = embed_svc._vec_literal(vecs[0])  # noqa: SLF001
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {embed_svc.TABLE}
              (item_id, region, prefix, code, rel_path, title,
               poster_path, thumb_path, fanart_path, cover_url,
               model, dim, content_sha, source_text, embedding, updated_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
            ON CONFLICT (item_id) DO UPDATE SET
              region = EXCLUDED.region,
              prefix = EXCLUDED.prefix,
              code = EXCLUDED.code,
              rel_path = EXCLUDED.rel_path,
              title = EXCLUDED.title,
              poster_path = EXCLUDED.poster_path,
              thumb_path = EXCLUDED.thumb_path,
              fanart_path = EXCLUDED.fanart_path,
              cover_url = EXCLUDED.cover_url,
              model = EXCLUDED.model,
              dim = EXCLUDED.dim,
              content_sha = EXCLUDED.content_sha,
              source_text = EXCLUDED.source_text,
              embedding = EXCLUDED.embedding,
              updated_at = now()
            """,
            (
                item["item_id"],
                item["region"],
                item["prefix"],
                item["code"],
                item["rel_path"],
                item["title"],
                item["poster_path"],
                item["thumb_path"],
                item["fanart_path"],
                item["cover_url"],
                item["model"],
                item["dim"],
                item["content_sha"],
                item["source_text"],
                vec_lit,
            ),
        )
        conn.commit()
    return {"ok": True, "embedded": True, "itemId": item["item_id"], "code": item["code"]}


def enrich_one_row(row: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    code = str(row.get("code") or "").strip().upper()
    rel = str(row.get("rel_path") or row.get("relPath") or "").strip().replace("\\", "/")
    gaps = list(row.get("gaps") or [])
    region = str(row.get("region") or "").strip()
    out: dict[str, Any] = {
        "code": code,
        "relPath": rel,
        "region": region,
        "gaps": gaps,
        "ok": False,
        "dryRun": dry_run,
    }
    if not code or not rel:
        out["error"] = "missing code/relPath"
        return out

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    folder = (root / rel).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError:
        out["error"] = "bad path"
        return out

    # 无显式 region 时从路径首段推断（日本有码/...）
    if not region and rel:
        region = rel.split("/", 1)[0].strip()
        out["region"] = region

    detail = _fetch_detail(code, region=region)
    if not detail:
        out["error"] = "detail_not_found"
        return out
    out["source"] = detail.get("source") or detail.get("provider")
    out["detailTitle"] = detail.get("title")

    if dry_run:
        out["ok"] = True
        out["wouldFill"] = {
            "title": bool(detail.get("title")),
            "studio": bool(detail.get("studio") or detail.get("maker")),
            "actors": len(detail.get("actors") or []),
            "tags": len(detail.get("tags") or []),
            "poster": bool(detail.get("posterUrl")),
            "overview": bool(detail.get("overview")),
        }
        return out

    nfo = _find_nfo(folder) or (folder / f"{folder.name}.nfo")
    changed = merge_nfo_with_detail(nfo, detail)
    poster_url = str(detail.get("posterUrl") or "").strip()
    poster_file = folder / "poster.jpg"
    blank_local = poster_file.is_file() and embed_svc._is_blank_cover_file(
        poster_file
    )
    need_cover = (
        "no_local" in gaps
        or "no_media" in gaps
        or blank_local
        or not poster_file.is_file()
    )
    if need_cover:
        cands = [
            str(u).strip()
            for u in (detail.get("posterCandidates") or [poster_url])
            if str(u or "").strip().startswith(("http://", "https://"))
        ]
        if not cands and poster_url:
            cands = [poster_url]
        if cands:
            got_p, got_t = _download_covers(folder, cands)
            if got_p or got_t:
                changed = True
                out["posterDownloaded"] = bool(got_p)
                out["coverTried"] = cands[:4]
    if not changed and not need_cover:
        # 仍尝试重嵌入以刷新路径
        pass
    try:
        rein = reingest_folder(folder)
        out["reingest"] = rein
        out["ok"] = True
        out["nfoChanged"] = changed
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
        out["nfoChanged"] = changed
    return out


def run_enrich(
    *,
    region: str = "japan_censored",
    kinds: list[str] | None = None,
    limit: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    kind_list = [k for k in (kinds or list(_DEFAULT_ENRICH_KINDS)) if k in _ENRICH_KINDS]
    if not kind_list:
        kind_list = list(_DEFAULT_ENRICH_KINDS)
    # limit<=0：全量缺图；预览默认抽样 30
    raw_lim = int(limit) if limit is not None else 0
    if dry_run and raw_lim <= 0:
        lim = 30
    elif raw_lim <= 0:
        lim = 0  # 全量
    else:
        lim = max(1, min(20_000, raw_lim))
    lim_label = "全部" if lim <= 0 else str(lim)
    from . import scrape_sources_settings as scrape_src

    groups = scrape_src.enrich_groups_for_region(region)
    sources = _detail_sources(region=region)
    from . import scrap_enrich_strategy as strat

    cfg = strat.get_strategy()
    include_flare = bool(cfg.get("includeFlare", True))
    if not include_flare:
        sources = [s for s in sources if str(s.get("access") or "") != "proxy_flare"]
    src_label = " → ".join(
        f"{s.get('id')}({s.get('baseUrl') or '-'})" for s in sources
    ) or "(无启用源)"
    _push_log(
        f"{'预览' if dry_run else '补全'} · {region or '全部'} · kinds={','.join(kind_list)} · limit={lim_label}"
    )
    _push_log(
        f"策略 · {cfg.get('mode')} · 过盾={'开' if include_flare else '关'} · "
        f"分组 · {'+'.join(groups) or '-'} · 数据源 · {src_label}"
    )
    _set_progress(stage="queue", percent=5, label="筛选缺口", done=0, total=0)

    # 合并多 kind 队列，去重
    seen: set[str] = set()
    queue: list[dict[str, Any]] = []
    fetch_lim = 0 if lim <= 0 else lim
    for kind in kind_list:
        rows = embed_svc.quality_items(region=region, kind=kind, limit=fetch_lim)
        for r in rows:
            iid = str(r.get("itemId") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            queue.append(r)
            if lim > 0 and len(queue) >= lim:
                break
        if lim > 0 and len(queue) >= lim:
            break

    _push_log(f"队列 {len(queue)} 条")
    _set_progress(
        stage="enrich", percent=10, label=f"处理 0/{len(queue)}", done=0, total=len(queue)
    )

    results: list[dict[str, Any]] = []
    ok_n = 0
    fail_n = 0
    for i, row in enumerate(queue):
        try:
            one = enrich_one_row(row, dry_run=dry_run)
            results.append(one)
            if one.get("ok"):
                ok_n += 1
            else:
                fail_n += 1
                _push_log(f"{one.get('code')}: {one.get('error') or 'fail'}")
        except Exception as e:  # noqa: BLE001
            fail_n += 1
            results.append(
                {
                    "code": row.get("code"),
                    "ok": False,
                    "error": str(e),
                }
            )
            _push_log(f"{row.get('code')}: {e}")
        done = i + 1
        pct = 10 + int(85 * done / max(1, len(queue)))
        _set_progress(
            stage="enrich",
            percent=min(95, pct),
            label=f"处理 {done}/{len(queue)}",
            done=done,
            total=len(queue),
        )

    summary = {
        "dryRun": dry_run,
        "region": region,
        "groups": list(groups),
        "kinds": kind_list,
        "queued": len(queue),
        "ok": ok_n,
        "failed": fail_n,
        "sources": [
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "group": s.get("group"),
                "baseUrl": s.get("baseUrl"),
            }
            for s in sources
        ],
        "items": results[:80],
    }
    _set_progress(stage="done", percent=100, label="完成", done=ok_n, total=len(queue))
    _push_log(f"完成 · 成功 {ok_n} · 失败 {fail_n}")
    return summary


def save_item_plot(*, item_id: str = "", plot: str = "") -> dict[str, Any]:
    """把中文剧情写入 NFO 并重嵌入落库（覆盖原 plot/outline）。"""
    iid = str(item_id or "").strip()
    plot_zh = str(plot or "").strip()
    # NFO/展示里常见的 HTML 换行转成纯文本
    plot_zh = re.sub(r"<br\s*/?>", "\n", plot_zh, flags=re.I)
    plot_zh = re.sub(r"&nbsp;", " ", plot_zh, flags=re.I)
    plot_zh = re.sub(r"\n{3,}", "\n\n", plot_zh).strip()
    if not iid:
        raise ValueError("itemId 必填")
    if len(plot_zh) < 2:
        raise ValueError("剧情太短")
    if len(plot_zh) > 4000:
        plot_zh = plot_zh[:4000]

    embed_svc.ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, rel_path, code, region, source_text
            FROM {embed_svc.TABLE}
            WHERE item_id = %s
            LIMIT 1
            """,
            (iid,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("条目不存在")
    d = dict(row) if isinstance(row, dict) else {}
    rel = str(d.get("rel_path") or "").replace("\\", "/").strip()
    if not rel:
        raise ValueError("缺少 rel_path")

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    folder = (root / rel).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError("bad path") from e
    if not folder.is_dir():
        raise ValueError("目录不存在")

    nfo = _find_nfo(folder) or (folder / f"{folder.name}.nfo")
    if nfo.is_file():
        try:
            raw = nfo.read_text(encoding="utf-8", errors="replace")
            root_el = ET.fromstring(raw)
        except Exception:
            root_el = ET.Element("movie")
    else:
        root_el = ET.Element("movie")
    if root_el.tag.lower() != "movie":
        movie = root_el.find("movie")
        root_el = movie if movie is not None else ET.Element("movie")

    # 原日文剧情备份到 plotoriginal（仅首次）
    cur_plot = ""
    pe = root_el.find("plot")
    if pe is not None:
        cur_plot = "".join(pe.itertext()).strip()
    if cur_plot and cur_plot != plot_zh:
        _set_text_if_empty(root_el, "plotoriginal", cur_plot, force=False)
    _set_text_if_empty(root_el, "plot", plot_zh, force=True)
    _set_text_if_empty(root_el, "outline", plot_zh, force=True)

    nfo.parent.mkdir(parents=True, exist_ok=True)
    xml = ET.tostring(root_el, encoding="utf-8", xml_declaration=True)
    nfo.write_bytes(xml)

    # 先把剧情写进 source_text，保证详情再打开就是中文；向量失败不挡落库
    prev_src = str(d.get("source_text") or "")
    plot_line = "剧情：" + re.sub(r"\s*\n\s*", " ", plot_zh).strip()
    if re.search(r"^剧情：", prev_src, flags=re.M):
        new_src = re.sub(
            r"^剧情：[\s\S]+?(?=\n[^\s][^：\n]*：|$)",
            plot_line,
            prev_src,
            count=1,
            flags=re.M,
        )
    else:
        new_src = (prev_src.rstrip() + "\n" + plot_line).strip()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {embed_svc.TABLE}
            SET source_text = %s, updated_at = now()
            WHERE item_id = %s
            """,
            (new_src, iid),
        )
        conn.commit()

    rein: dict[str, Any] | None = None
    rein_err = ""
    try:
        rein = reingest_folder(folder)
    except Exception as e:  # noqa: BLE001
        rein_err = str(e)
        log.warning("save_item_plot reingest failed item=%s: %s", iid, e)

    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, code, title, source_text, updated_at
            FROM {embed_svc.TABLE}
            WHERE item_id = %s
            LIMIT 1
            """,
            (iid,),
        )
        fresh = cur.fetchone()
    fd = dict(fresh) if isinstance(fresh, dict) else {}
    return {
        "ok": True,
        "itemId": iid,
        "code": str(fd.get("code") or d.get("code") or ""),
        "title": str(fd.get("title") or ""),
        "sourceText": str(fd.get("source_text") or new_src),
        "plot": plot_zh,
        "reingest": rein,
        "reingestError": rein_err or None,
    }


def start_enrich_job(
    *,
    region: str = "japan_censored",
    kinds: list[str] | None = None,
    limit: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    with _enrich_lock:
        if _enrich_job["running"]:
            raise RuntimeError("元数据补全已在运行")
        if embed_svc.get_job_status().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        _enrich_job.update(
            {
                "running": True,
                "phase": "starting",
                "progress": {
                    "stage": "prepare",
                    "done": 0,
                    "total": None,
                    "percent": 0,
                    "label": "starting",
                },
                "log": [],
                "result": None,
                "error": None,
            }
        )

    def run() -> None:
        try:
            result = run_enrich(
                region=region, kinds=kinds, limit=limit, dry_run=dry_run
            )
            with _enrich_lock:
                _enrich_job["result"] = result
                _enrich_job["phase"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("scrap library enrich failed")
            with _enrich_lock:
                _enrich_job["error"] = str(e)
                _enrich_job["phase"] = "error"
                log_list = list(_enrich_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _enrich_job["log"] = log_list[-40:]
        finally:
            with _enrich_lock:
                _enrich_job["running"] = False

    threading.Thread(target=run, name="scrap-library-enrich", daemon=True).start()
    return {"started": True}
