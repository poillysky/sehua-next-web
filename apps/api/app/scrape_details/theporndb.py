# -*- coding: utf-8 -*-
"""ThePornDB 详情刮削（对齐 MDCS theporndb.ts）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from .common import clean_title, code_key, fetch_json, is_junk_title, make_detail, std_code, strip_tags

THEPORNDB_API_BASE = "https://api.theporndb.net"

WESTERN_STUDIO_ALIASES: dict[str, str] = {
    "puretaboo": "Pure Taboo",
    "rk": "Reality Kings",
    "sexmex": "SexMex",
    "pornworld": "Porn World",
}


def _looks_jav(code: str) -> bool:
    u = code.upper()
    if re.match(r"^FC2", u):
        return True
    if re.match(r"^[A-Z]{1,12}-\d{2,}", u):
        return True
    if re.match(r"^\d{2,3}[A-Z]{2,}-\d+", u):
        return True
    return False


def _build_search_queries(code: str) -> list[str]:
    raw = str(code or "").strip()
    out = [raw]
    m = re.match(r"^([A-Za-z][A-Za-z0-9]*)\.(\d{4})\.(\d{2})\.(\d{2})$", raw)
    if not m:
        return list(dict.fromkeys(out))
    studio_key, y, mo, d = m.group(1), m.group(2), m.group(3), m.group(4)
    studio = WESTERN_STUDIO_ALIASES.get(studio_key.lower()) or re.sub(
        r"([a-z0-9])([A-Z])", r"\1 \2", studio_key
    )
    iso = f"{y}-{mo}-{d}"
    out.extend([f"{studio} {iso}", studio, f"{studio_key} {iso}"])
    return list(dict.fromkeys(x for x in out if x))


def _score_western_date_hit(item: dict[str, Any], code: str) -> int:
    m = re.match(r"^([A-Za-z][A-Za-z0-9]*)\.(\d{4})\.(\d{2})\.(\d{2})$", code)
    if not m:
        return 0
    studio_key, y, mo, d = m.group(1), m.group(2), m.group(3), m.group(4)
    iso = f"{y}-{mo}-{d}"
    score = 0
    if str(item.get("date") or "")[:10] == iso:
        score += 80
    site = item.get("site") or {}
    site_name = str(site.get("name") or site.get("network") or "").lower()
    alias = (WESTERN_STUDIO_ALIASES.get(studio_key.lower()) or studio_key).lower()
    site_head = (site_name.split(":")[0] or "zzz").strip()
    if alias in site_name or site_head in alias:
        score += 40
    return score


def _score_hit(item: dict[str, Any], want: str, code: str) -> int:
    score = 0
    blob = " ".join(str(item.get(k) or "") for k in ("title", "sku", "external_id", "slug", "id"))
    key_blob = code_key(blob)
    if key_blob == want or want in key_blob:
        score += 100
    if code_key(str(item.get("sku") or "")) == want:
        score += 80
    if code_key(str(item.get("external_id") or "")) == want:
        score += 40
    if re.search(code.replace("-", "[-_]?"), blob, re.I):
        score += 30
    if item.get("image") or item.get("poster") or item.get("poster_image"):
        score += 5
    score += _score_western_date_hit(item, code)
    return score


def _build_search_paths(code: str) -> list[tuple[str, str]]:
    std = std_code(code) or code
    if _looks_jav(code):
        return [
            (f"/jav?q={quote(code)}&per_page=10", "jav"),
            (f"/jav?q={quote(std)}&per_page=10", "jav"),
            (f"/scenes?q={quote(code)}&per_page=5", "scenes"),
        ]
    paths: list[tuple[str, str]] = []
    for q in _build_search_queries(code):
        paths.append((f"/scenes?parse={quote(q)}&per_page=100", "scenes"))
    for q in _build_search_queries(code):
        paths.append((f"/movies?parse={quote(q)}&per_page=20", "movies"))
    return paths


def _auth_header(api_key: str) -> str:
    key = str(api_key or "").strip()
    if key.lower().startswith("bearer "):
        return key
    return f"Bearer {key}"


def _tpdb_get(path: str, api_key: str) -> Any:
    headers = {
        "Accept": "application/json",
        "Authorization": _auth_header(api_key),
    }
    try:
        return fetch_json(
            f"{THEPORNDB_API_BASE}{path}",
            headers=headers,
            source_id="theporndb",
        )
    except Exception:
        return None


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del base_url, cookie
    key = str(api_key or "").strip()
    if not key:
        raise RuntimeError("需要 ThePornDB API Key")

    raw_code = str(code or "").strip()
    if not raw_code:
        raise RuntimeError("番号为空")

    std = std_code(raw_code) or raw_code
    want = code_key(std)

    best: dict[str, Any] | None = None
    best_score = 0
    best_kind = "jav" if _looks_jav(raw_code) else "scenes"

    for path, kind in _build_search_paths(raw_code):
        raw = _tpdb_get(path, key)
        if not isinstance(raw, dict):
            continue
        data = raw.get("data")
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            sc = _score_hit(item, want, raw_code)
            if sc > best_score:
                best = item
                best_score = sc
                best_kind = kind
        if best_score >= 100:
            break

    if not best or best_score < 20:
        raise RuntimeError("未找到")

    sid = str(best.get("id") or "").strip()
    if sid:
        if best_kind == "jav":
            detail_path = f"/jav/{quote(sid)}"
        elif best_kind == "movies":
            detail_path = f"/movies/{quote(sid)}"
        else:
            detail_path = f"/scenes/{quote(sid)}"
        detail = _tpdb_get(detail_path, key)
        if isinstance(detail, dict) and isinstance(detail.get("data"), dict):
            best = detail["data"]

    title = clean_title(str(best.get("title") or ""), std)
    if not title or is_junk_title(title):
        raise RuntimeError("解析失败")

    actors: list[str] = []
    for p in best.get("performers") or []:
        if not isinstance(p, dict):
            continue
        parent = p.get("parent") if isinstance(p.get("parent"), dict) else {}
        name = str(parent.get("name") or p.get("name") or "").strip()
        if name and name not in actors:
            actors.append(name)

    tags = [str(t.get("name") or "").strip() for t in (best.get("tags") or []) if isinstance(t, dict)]
    tags = [t for t in tags if t][:30]

    site = best.get("site") if isinstance(best.get("site"), dict) else {}
    studio = str(site.get("name") or site.get("network") or "").strip() or None

    premiered = str(best.get("date") or "")[:10]
    date = premiered if re.match(r"^\d{4}-\d{2}-\d{2}", premiered) else None

    posters = best.get("posters") if isinstance(best.get("posters"), dict) else {}
    background = best.get("background") if isinstance(best.get("background"), dict) else {}
    cover = (
        posters.get("full")
        or posters.get("large")
        or best.get("poster_image")
        or best.get("poster")
        or best.get("image")
        or background.get("full")
        or background.get("large")
        or best.get("back_image")
        or None
    )
    cover = str(cover).strip() if cover else None

    plot = strip_tags(str(best.get("description") or ""))

    runtime: int | None = None
    dur = best.get("duration")
    if isinstance(dur, (int, float)) and dur > 0:
        runtime = int(round(dur / 60)) if dur > 600 else int(dur)

    directors: list[str] = []
    for d in best.get("directors") or []:
        if not isinstance(d, dict):
            continue
        name = str(d.get("name") or "").strip()
        if name and name not in directors:
            directors.append(name)

    rating_raw = best.get("rating")
    rating: float | None = None
    if isinstance(rating_raw, (int, float)) and rating_raw > 0:
        rating = float(rating_raw)

    website = str(best.get("url") or "").strip() or None
    trailer = str(best.get("trailer") or "").strip() or None

    extra: dict[str, Any] = {}
    if runtime and runtime > 0:
        extra["runtime"] = runtime
    if directors:
        extra["director"] = directors[0]
        extra["directors"] = directors
    if rating is not None:
        extra["rating"] = rating
    if website:
        extra["website"] = website
    if trailer:
        extra["trailer"] = trailer
        extra["trailerUrl"] = trailer

    return make_detail(
        source="theporndb",
        code=std,
        title=title,
        poster=cover,
        studio=studio,
        actors=actors[:20],
        tags=tags,
        overview=plot if len(plot) >= 12 else None,
        date=date,
        extra=extra or None,
    )
