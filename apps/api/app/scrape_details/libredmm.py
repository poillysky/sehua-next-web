# -*- coding: utf-8 -*-
"""LibreDMM 详情刮削（对齐 MDCS libredmm.ts）。"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

from .common import (
    append_amateur_board_variants,
    code_equiv,
    fetch_json,
    make_detail,
    strip_tags,
)

DEFAULT_BASE = "https://www.libredmm.com"


def libredmm_code_candidates(code: str) -> list[str]:
    """LibreDMM ``/movies/{code}.json`` 路径候选。

    站点对 pad / 分盘尾缀 / 素人数字板号敏感：``IPZZ-599C`` 会 not_found，
    ``259LUXU-001`` 常要落到 ``LUXU-001``；裸 ``LUXU-001`` 也需加板号试探。
    """
    raw = str(code or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def _add(s: str) -> None:
        t = str(s or "").strip().upper().replace("_", "-")
        if t and t not in out:
            out.append(t)

    _add(raw)
    try:
        from app.search.av import parse_maker_code, std_code_key

        parsed = parse_maker_code(raw)
        if parsed and parsed.shape == "std" and parsed.canonical:
            can = parsed.canonical
            _add(can)
            _add(std_code_key(can, pad=3))
            _add(std_code_key(can, pad=4))
            m = re.fullmatch(r"([A-Z0-9]+)-(\d+)", can, re.I)
            if m:
                n = int(m.group(2))
                pref = m.group(1).upper()
                _add(f"{pref}-{n}")
                for w in (3, 4):
                    _add(f"{pref}-{n:0{w}d}")
            # 素人：保留数字板号写法（259LUXU-001）
            glued = re.sub(r"[-_\s]", "", raw).upper()
            m2 = re.fullmatch(r"(\d{2,3})([A-Z]{2,20})(\d{2,10})", glued)
            if m2:
                _add(f"{m2.group(1)}{m2.group(2)}-{int(m2.group(3))}")
                _add(f"{m2.group(1)}{m2.group(2)}-{m2.group(3)}")
    except Exception:  # noqa: BLE001
        # 兜底：剥单字母分盘尾缀
        m = re.match(r"^([A-Z]{2,12})-(\d{1,6})(?:[-_.]?[A-Z]{1,4})?$", raw.upper())
        if m:
            _add(f"{m.group(1)}-{int(m.group(2))}")
            _add(f"{m.group(1)}-{int(m.group(2)):03d}")

    append_amateur_board_variants(_add, raw)
    return out[:20]


def _prefer_pl_cover(url: str | None) -> str | None:
    u = str(url or "").strip()
    if not u:
        return None
    return re.sub(r"ps\.jpg(\?|$)", r"pl.jpg\1", u, flags=re.I)


def _parse_hit(raw: Any, code: str) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    err = str(raw.get("err") or "")
    if err and err != "ok":
        return None

    title = str(raw.get("title") or "").strip()
    cover = _prefer_pl_cover(raw.get("cover_image_url")) or _prefer_pl_cover(
        raw.get("thumbnail_image_url")
    )

    actors: list[str] = []
    for a in raw.get("actresses") or []:
        if not isinstance(a, dict):
            continue
        name = re.sub(r"\s+\d+歳.*$", "", str(a.get("name") or ""), flags=re.U).strip()
        if name:
            actors.append(name)

    nid = str(raw.get("normalized_id") or "").strip()
    if nid and not code_equiv(nid, code):
        # 分盘尾缀 / 补零：再与候选基号比一次
        matched = False
        for cand in libredmm_code_candidates(code):
            if code_equiv(nid, cand):
                matched = True
                break
        if not matched:
            return None

    if not title and not cover:
        return None

    plot = re.sub(
        r"\s+",
        " ",
        strip_tags(
            str(raw.get("description") or raw.get("comment") or raw.get("subtitle") or "")
        ),
    ).strip()

    premiered = str(raw.get("date") or "")[:10]
    date = premiered if re.match(r"^\d{4}-\d{2}-\d{2}", premiered) else None

    makers = raw.get("makers") or []
    studio = str(makers[0] if makers else "").strip() or None
    labels = raw.get("labels") or []
    publisher = str(labels[0] if labels else "").strip() or None

    series_raw = raw.get("series")
    if isinstance(series_raw, list):
        series = str(series_raw[0] if series_raw else "").strip() or None
    else:
        series = str(series_raw or "").strip() or None

    runtime_raw = raw.get("minute")
    if not isinstance(runtime_raw, (int, float)):
        runtime_raw = raw.get("runtime")
    runtime = int(runtime_raw) if isinstance(runtime_raw, (int, float)) else None
    if runtime is not None and not (0 < runtime < 600):
        runtime = None

    genres = []
    for g in raw.get("genres") or []:
        gs = str(g).strip()
        if gs and not re.match(r"^(サンプル動画|デジタル配信)$", gs, re.I):
            genres.append(gs)

    return {
        "title": title or None,
        "overview": plot if len(plot) >= 12 else None,
        "actors": actors,
        "tags": genres,
        "studio": studio,
        "publisher": publisher,
        "series": series,
        "runtime": runtime,
        "date": date,
        "poster": cover,
    }


def _detail_from_hit(code: str, hit: dict[str, Any]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if hit.get("publisher"):
        extra["publisher"] = hit["publisher"]
    if hit.get("series"):
        extra["series"] = hit["series"]
    if hit.get("runtime") is not None:
        extra["runtime"] = hit["runtime"]
    return make_detail(
        source="libredmm",
        code=code,
        title=hit.get("title"),
        poster=hit.get("poster"),
        studio=hit.get("studio"),
        actors=hit.get("actors") or [],
        tags=hit.get("tags") or [],
        overview=hit.get("overview"),
        date=hit.get("date"),
        extra=extra or None,
    )


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")

    candidates = libredmm_code_candidates(code)
    if not candidates:
        raise RuntimeError("番号为空")
    display = candidates[0]

    def _try_movie(code_u: str) -> dict[str, Any] | None:
        movie_url = f"{base}/movies/{quote(code_u)}.json"
        for i in range(5):
            try:
                data = fetch_json(movie_url, cookie=cookie or None, source_id="libredmm")
            except Exception:  # noqa: BLE001
                data = None
            if isinstance(data, dict):
                err = str(data.get("err") or "")
                if err == "processing":
                    time.sleep(1.2 + i * 0.4)
                    continue
                if err == "not_found":
                    return None
                hit = _parse_hit(data, code_u)
                if hit and (hit.get("title") or hit.get("poster")):
                    return _detail_from_hit(display, hit)
            if i < 2:
                time.sleep(0.8)
                continue
            break
        return None

    for cand in candidates:
        hit = _try_movie(cand)
        if hit is not None:
            return hit

    # search 回退：按候选依次试（search 返回单条详情同构 JSON）
    last_err: Exception | None = None
    for cand in candidates[:6]:
        try:
            search_data = fetch_json(
                f"{base}/search.json?q={quote(cand)}",
                cookie=cookie or None,
                source_id="libredmm",
            )
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
        from_search = _parse_hit(search_data, cand)
        if from_search and (from_search.get("title") or from_search.get("poster")):
            return _detail_from_hit(display, from_search)

    if last_err is not None:
        raise RuntimeError(f"未找到: {last_err}") from last_err
    raise RuntimeError("未找到")
