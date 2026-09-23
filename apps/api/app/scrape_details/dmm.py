# -*- coding: utf-8 -*-
"""DMM / FANZA 详情刮削（对齐 MDCS dmm.ts GraphQL）。"""

from __future__ import annotations

import re
from typing import Any

from .common import (
    build_fanza_trailer,
    clean_title,
    is_junk_title,
    make_detail,
    std_code,
    strip_tags,
    with_https,
)

GQL = "https://api.video.dmm.co.jp/graphql"
SITE = "https://www.dmm.co.jp"
SOURCE = "dmm"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DIGITAL_QUERY = """
query ScrapDigitalContent($id: ID!) {
  ppvContent(id: $id) {
    id
    title
    description
    packageImage { largeUrl mediumUrl }
    sample2DMovie { highestMovieUrl hlsMovieUrl }
    sampleVRMovie { highestMovieUrl }
    deliveryStartDate
    makerReleasedAt
    duration
    actresses { name }
    series { name }
    maker { name }
    label { name }
    genres { name }
    directors { name }
    sampleImages { number imageUrl }
  }
  reviewSummary(contentId: $id) {
    average
    total
  }
}
"""

_COMMON_PREFIXES = ("", "1", "13", "49", "436", "118", "55", "57", "83", "5642")


def _date_only(raw: Any) -> str | None:
    s = str(raw or "")[:10]
    return s if re.match(r"^\d{4}-\d{2}-\d{2}$", s) else None


# _with_https / _build_fanza_trailer 的唯一实现已收敛到 .common（保留旧名，调用点零改动）
_with_https = with_https
_build_fanza_trailer = build_fanza_trailer


def _pick_trailer(sample2d: dict | None, sample_vr: dict | None) -> str | None:
    cands: list[str] = []
    for src in (
        (sample_vr or {}).get("highestMovieUrl"),
        (sample2d or {}).get("highestMovieUrl"),
    ):
        u = _with_https(str(src or ""))
        if u and u not in cands:
            cands.append(u)
    hls = _build_fanza_trailer(str((sample2d or {}).get("hlsMovieUrl") or ""))
    if hls and hls not in cands:
        cands.append(hls)

    best = ""
    best_rank = -1
    ranks = [
        (re.compile(r"4k", re.I), 120),
        (re.compile(r"hhb", re.I), 100),
        (re.compile(r"mhb", re.I), 80),
        (re.compile(r"mmb", re.I), 60),
        (re.compile(r"sm", re.I), 40),
    ]
    for raw in cands:
        built = _build_fanza_trailer(raw)
        url = built or (_with_https(raw) if re.search(r"\.mp4(?:[?#].*)?$", _with_https(raw), re.I) else "")
        if not url or re.search(r"\.m3u8", url, re.I):
            continue
        rank = 20 if re.search(r"\.mp4", url, re.I) else 0
        for pat, r in ranks:
            if pat.search(url):
                rank = r
                break
        if rank > best_rank:
            best, best_rank = url, rank
    return best or None


def guess_dmm_cids(code_raw: str) -> list[str]:
    """CID 候选：优先 prefix_catalog_dmm.guess_digits，再补常见前缀。"""
    code = std_code(code_raw)
    if not code or re.match(r"^FC2", code, re.I):
        return []
    m = re.match(r"^([A-Z0-9]{2,10})-(\d{1,6})$", code, re.I)
    if not m:
        return []
    series = re.sub(r"[^A-Za-z0-9]", "", m.group(1)).lower()
    n = int(m.group(2))
    padded = str(n).zfill(5)

    digits: list[str] = []
    try:
        from app.prefix.catalog_dmm import guess_digits

        digits.extend(guess_digits(series))
    except Exception:
        digits.append("")
    for d in _COMMON_PREFIXES:
        if d not in digits:
            digits.append(d)

    out: list[str] = []
    seen: set[str] = set()
    for dig in digits:
        cid = f"{dig}{series}{padded}"
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def _post_graphql(cid: str, cookie: str = "") -> dict[str, Any] | None:
    from app.core.outbound_http import api_slot, curl_request, thread_request_timeout

    detail = f"https://video.dmm.co.jp/av/content/?id={cid}"
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://video.dmm.co.jp",
        "Referer": detail,
        "User-Agent": UA,
        "Accept": "application/json",
        "Cookie": cookie
        or "age_check_done=1; ckcy=1; cklg=ja; is_overseas=0",
    }
    # 请求超时跟随线程本地单源预算（原来硬编码 20s，与 enrich 的 down 判定不一致）
    budget = thread_request_timeout()
    to = 20.0 if not budget or float(budget) <= 0 else min(20.0, float(budget))
    try:
        # 第十一轮：走 kind="api" 出站通道，直连路径不再裸奔
        with api_slot(GQL, timeout=to):
            r = curl_request(
                "POST",
                GQL,
                headers=headers,
                json_body={
                    "operationName": "ScrapDigitalContent",
                    "variables": {"id": cid},
                    "query": DIGITAL_QUERY,
                },
                timeout=to,
                verify=False,
            )
    except Exception:
        return None
    if int(getattr(r, "status_code", 500) or 500) >= 400:
        return None
    try:
        data = (r.json().get("data") or {}) if hasattr(r, "json") else {}
    except Exception:
        return None
    hit = data.get("ppvContent") or None
    if not hit or not (hit.get("id") or hit.get("title")):
        return None
    return data


def _sample_images(hit: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for row in hit.get("sampleImages") or []:
        url = str((row or {}).get("imageUrl") or "").strip()
        if url.startswith("http") and url not in urls:
            urls.append(url)

    def _num(u: str) -> int:
        m = re.search(r"-(\d+)\.", u)
        return int(m.group(1)) if m else 0

    return sorted(urls, key=_num)


def _parse_hit(data: dict[str, Any], code: str) -> dict[str, Any] | None:
    hit = data.get("ppvContent") or {}
    title = clean_title(str(hit.get("title") or ""), code)
    if title and is_junk_title(title):
        title = ""
    plot = re.sub(r"\s+", " ", strip_tags(str(hit.get("description") or ""))).strip()
    actors: list[str] = []
    for a in hit.get("actresses") or []:
        n = str((a or {}).get("name") or "").strip()
        if n and len(n) < 40 and n not in actors:
            actors.append(n)
    genres = [
        str((g or {}).get("name") or "").strip()
        for g in (hit.get("genres") or [])
        if str((g or {}).get("name") or "").strip()
        and len(str((g or {}).get("name") or "").strip()) < 40
    ]
    directors = [
        str((d or {}).get("name") or "").strip()
        for d in (hit.get("directors") or [])
        if str((d or {}).get("name") or "").strip()
        and len(str((d or {}).get("name") or "").strip()) < 40
    ]
    duration_sec = int(hit.get("duration") or 0) or 0
    runtime = round(duration_sec / 60) if duration_sec > 0 else None
    if runtime is not None and not (0 < runtime < 600):
        runtime = None
    cover = (
        str((hit.get("packageImage") or {}).get("largeUrl") or "").strip()
        or str((hit.get("packageImage") or {}).get("mediumUrl") or "").strip()
        or None
    )
    cid = str(hit.get("id") or "").strip()
    website = (
        f"https://www.dmm.co.jp/digital/videoa/-/detail/=/cid={cid}/" if cid else None
    )
    trailer = _pick_trailer(hit.get("sample2DMovie"), hit.get("sampleVRMovie"))
    review = data.get("reviewSummary") or {}
    review_avg = float(review.get("average") or 0)
    review_total = float(review.get("total") or 0)
    extras = _sample_images(hit)

    if not title and not cover:
        return None

    extra: dict[str, Any] = {
        "publisher": str((hit.get("label") or {}).get("name") or "").strip() or None,
        "series": str((hit.get("series") or {}).get("name") or "").strip() or None,
        "directors": directors or None,
        "runtime": runtime,
        "website": website,
        "trailerUrl": trailer,
        "extrafanartUrls": extras or None,
    }
    if cid:
        extra["publishNumber"] = cid.lower()
    if review_avg > 0:
        extra.update(
            {
                "score": review_avg * 2,
                "ratingValue": review_avg,
                "ratingMax": 5,
                "ratingSource": "dmm",
            }
        )
    if review_total > 0:
        extra["votes"] = str(int(review_total))

    return make_detail(
        source=SOURCE,
        code=code,
        title=title or None,
        poster=cover,
        studio=str((hit.get("maker") or {}).get("name") or "").strip() or None,
        actors=actors,
        tags=genres,
        overview=plot if len(plot) >= 12 else None,
        date=_date_only(hit.get("deliveryStartDate"))
        or _date_only(hit.get("makerReleasedAt")),
        extra=extra,
    )


def _cover_fallback(cid: str) -> str | None:
    """CDN 封面兜底（不探测可用性，仅拼 URL）。"""
    c = cid.lower()
    return f"https://pics.dmm.co.jp/digital/video/{c}/{c}pl.jpg"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict:
    del base_url, api_key
    code_s = std_code(code)
    if not code_s or re.match(r"^FC2", code_s, re.I):
        raise RuntimeError("番号格式无效")
    if not re.match(r"^([A-Z]{2,10})-(\d{2,6})$", code_s):
        raise RuntimeError("番号格式无效")

    variants = guess_dmm_cids(code_s)
    if not variants:
        raise RuntimeError("番号格式无效")

    for cid in variants:
        data = _post_graphql(cid, cookie=cookie)
        if not data:
            continue
        parsed = _parse_hit(data, code_s)
        if parsed:
            return parsed

    for cid in variants[:8]:
        cover = _cover_fallback(cid)
        if cover:
            return make_detail(
                source=SOURCE,
                code=code_s,
                poster=cover,
                extra={"error": "详情 GraphQL 无数据（仅封面）"},
            )

    raise RuntimeError("未找到")
