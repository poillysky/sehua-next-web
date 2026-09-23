# -*- coding: utf-8 -*-
"""MissAV 详情刮削（对齐 MDCS miss_av.ts）。"""

from __future__ import annotations

import re
from urllib.parse import quote

from .common import (
    abs_url,
    clean_title,
    code_equiv,
    fc2_slug_variants,
    fetch_html,
    fold_code,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    pick_og_image,
    soup,
    std_code,
    strip_tags,
)

DEFAULT_BASE = "https://missav123.com"
DETAIL_SUFFIX_RE = re.compile(
    r"-(?:uncensored-leak|uncensored|chinese-subtitle|english-subtitle|chinese|english)$",
    re.I,
)
SOURCE = "miss_av"

# 无码 date6：站内详情常是「裸日期」``062014_830``（``1pon-062014-830`` 404）
_MISSAV_DATE6_BRANDS: dict[str, tuple[str, ...]] = {
    "1PON": ("1pondo", "pondo"),
    "CARIB": ("caribbeancom", "caribbean", "carib"),
    "CARIBPR": ("caribbeancompr", "caribpr"),
    "10MU": ("10musume", "musume"),
    "PACO": ("pacopacomama", "paco"),
}


def miss_av_code_candidates(code: str) -> list[str]:
    """详情 / 搜索用番号：原串 / pad / 素人剥板号 / FC2 / 无码 date6 裸日期。"""
    raw = str(code or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def _add(val: str) -> None:
        s = str(val or "").strip()
        if s and s not in out:
            out.append(s)

    _add(raw)
    _add(std_code(raw))
    try:
        from app.search.av import parse_maker_code, std_code_key

        parsed = parse_maker_code(raw)
        if parsed and parsed.canonical:
            _add(parsed.canonical)
            if parsed.shape == "std":
                # 国产：勿生成短位数 pad（MDX-0001 → MDX-001 会错绑日系旧片）
                is_china = False
                try:
                    from app.prefix.ranges import load_china_prefixes

                    pref = str(parsed.prefix or "").upper()
                    is_china = bool(pref) and pref in {
                        str(x).upper() for x in (load_china_prefixes() or set())
                    }
                except Exception:  # noqa: BLE001
                    is_china = False
                if not is_china:
                    _add(std_code_key(parsed.canonical, pad=3))
                    _add(std_code_key(parsed.canonical, pad=4))
            if parsed.shape == "date6" and len(parsed.parts) >= 3:
                label, d6, nnn = parsed.parts[0], parsed.parts[1], parsed.parts[2]
                bare_us = f"{d6}_{nnn}"
                bare_hy = f"{d6}-{nnn}"
                _add(bare_us)
                _add(bare_hy)
                for brand in _MISSAV_DATE6_BRANDS.get(str(label).upper(), ()):
                    _add(f"{brand}-{d6}-{nnn}")
                    _add(f"{brand}_{d6}_{nnn}")
                    _add(f"{brand}-{bare_us}")
    except Exception:  # noqa: BLE001
        pass
    for v in fc2_slug_variants(raw):
        _add(v)
    return out


def _path_codes(code: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _add_slug(v: str) -> None:
        s = str(v or "").strip().lower()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s)

    for cand in miss_av_code_candidates(code):
        if re.match(r"^fc2", cand, re.I):
            for v in fc2_slug_variants(cand):
                _add_slug(v)
            _add_slug(re.sub(r"\s+", "-", cand))
        # date6 裸下划线必须保留（062014_830）；其余去杠 compact
        if "_" in cand and re.search(r"\d{6}_\d+", cand):
            _add_slug(cand)
        _add_slug(cand.replace("_", "-"))
        _add_slug(re.sub(r"[-_]", "", cand))
        _add_slug(cand)
    return out


def _looks_blocked(html: str) -> bool:
    head = (html or "")[:8000].lower()
    return bool(
        re.search(
            r"just a moment|attention required|cf-browser-verification|challenge-platform|enable javascript and cookies",
            head,
            re.I,
        )
    )


def _is_detail_html(html: str, code: str) -> bool:
    if not html or len(html) < 5000:
        return False
    if _looks_blocked(html):
        return False
    if not re.search(r'property=["\']og:type["\']\s+content=["\']video\.other["\']', html, re.I):
        return False
    std = std_code(code)
    m = re.search(r"<span>番号:</span>\s*<span[^>]*>([^<]+)<", html, re.I) or re.search(
        r"dvdId:\s*['\"]([^'\"]+)['\"]", html, re.I
    )
    page_code = strip_tags(m.group(1) if m else "")
    if page_code:
        # 候选含剥板号 / date6 裸日期；页码与任一候选等价即过（062014_830 ≡ 1PON-…）
        for cand in miss_av_code_candidates(code):
            if code_equiv(page_code, cand) or fold_code(page_code) == fold_code(cand):
                return True
        return False
    # 无「番号:」行：FC2 用数字 id；其它回落 token
    from .common import parse_fc2_id

    parsed = parse_fc2_id(std)
    if parsed:
        fid = parsed[0]
        return bool(
            re.search(rf"FC2[-_]?PPV[-_]?{re.escape(fid)}|FC2[-_]?{re.escape(fid)}", html[:80000], re.I)
        )
    for cand in miss_av_code_candidates(code):
        token = re.escape(std_code(cand) or cand).replace(r"\-", "[-]?")
        if token and re.search(token, html[:80000], re.I):
            return True
    return False


def _pick_detail_href(html: str, code: str) -> str:
    want_slugs = {
        s.lower().replace("_", "-") for s in miss_av_code_candidates(code)
    }
    want_slugs |= {s.replace("-", "") for s in list(want_slugs)}
    want_slugs |= {v.lower() for v in fc2_slug_variants(code)}
    hrefs = [m.group(1) for m in re.finditer(r'href=["\']([^"\']+/cn/[^"\'#?]+)["\']', html or "", re.I)]
    scored: list[tuple[str, int]] = []
    for h in dict.fromkeys(hrefs):
        path = h.split("?")[0].lower()
        slug = path.rstrip("/").split("/")[-1] if path else ""
        score = 0
        if DETAIL_SUFFIX_RE.search(slug):
            score -= 80
        if slug in want_slugs or any(code_equiv(slug, c) for c in miss_av_code_candidates(code)):
            score += 100
        # 禁止 startswith 模糊命中
        if re.search(r"/cn/search/", path, re.I):
            score -= 50
        if re.search(r"-uncensored-leak", slug, re.I):
            score -= 30
        if re.search(r"-chinese-subtitle|-english-subtitle", slug, re.I):
            score -= 10
        if re.search(r"/dm\d+/cn/", path, re.I):
            score += 5
        scored.append((h, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored and scored[0][1] >= 100 else ""


def _norm_label(raw: str) -> str:
    return re.sub(r"[:：\s]", "", strip_tags(raw))


def _label_hit(key: str, labels: list[str]) -> bool:
    k = _norm_label(key)
    if not k:
        return False
    # 排行榜/导航块常含「女优」字样，勿当详情女优行
    if re.search(r"排行|榜单|榜單|ranking|more|更多", k, re.I):
        return False
    wanted = {_norm_label(l) for l in labels if str(l).strip()}
    if k in wanted:
        return True
    # 允许「出演女优」等短前缀，拒绝「女优排行…」长串
    return any(
        k.endswith(w) and 0 < len(k) - len(w) <= 2 for w in wanted if w
    )


def _parse_label_links(html: str, labels: list[str]) -> list[str]:
    doc = soup(html)
    out: list[str] = []
    for el in doc.select("div.text-secondary"):
        spans = el.select("span")
        if not spans:
            continue
        key = strip_tags(spans[0].get_text())
        if not _label_hit(key, labels):
            continue
        for a in el.select("a.text-nord13"):
            t = re.sub(r"\s*\([^)]*\)\s*$", "", strip_tags(a.get_text())).strip()
            if t and t not in out:
                out.append(t)
    return out


def _parse_inline_value(html: str, labels: list[str]) -> str:
    doc = soup(html)
    out = ""
    for el in doc.select("div.text-secondary"):
        spans = el.select("span")
        if not spans:
            continue
        key = strip_tags(spans[0].get_text())
        if not _label_hit(key, labels):
            continue
        font = el.select_one("span.font-medium")
        if font is not None:
            out = strip_tags(font.get_text())
        else:
            raw = strip_tags(el.get_text())
            stripped = raw
            for lab in labels:
                stripped = re.sub(rf"^{re.escape(lab)}[:：]?", "", stripped)
            out = stripped.strip()
        break
    return out.strip()


def _parse_plot(html: str) -> str:
    m = re.search(r'property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', html, re.I) or re.search(
        r'content=["\']([^"\']+)["\']\s+property=["\']og:description["\']', html, re.I
    )
    plot = strip_tags(m.group(1) if m else "").strip()
    doc = soup(html)
    block = doc.select_one("div.line-clamp-2, div.line-clamp-none")
    from_body = strip_tags(block.get_text() if block else "").strip()
    if len(from_body) > len(plot):
        plot = from_body
    plot = re.sub(r"^\[[^\]]+\]\s*", "", plot).strip()
    if len(plot) < 20:
        return ""
    if re.search(r"免费高清|MissAV|在线看", plot, re.I) and len(plot) < 60:
        return ""
    return plot


def _parse_title(html: str, code: str) -> str:
    doc = soup(html)
    h1 = doc.select_one("h1.text-base, h1")
    raw = strip_tags(h1.get_text() if h1 else "")
    std = std_code(code)
    # 先剥 FC2 / FC2-PPV 全形态，避免「FC2-PPV-976194 中文…」被尾部 `-数字…` 裁成「FC2-PPV」
    from .common import parse_fc2_id

    parsed = parse_fc2_id(std)
    if parsed:
        fid = parsed[0]
        raw = re.sub(
            rf"^FC2[-_]?PPV[-_]?{re.escape(fid)}\s*",
            "",
            raw,
            flags=re.I,
        ).strip()
        raw = re.sub(rf"^FC2[-_]?{re.escape(fid)}\s*", "", raw, flags=re.I).strip()
    pat = re.escape(std).replace(r"\-", "[-]?")
    title = re.sub(rf"^{pat}\s*", "", raw, flags=re.I).strip()
    # 仅剥「空格+破折号+后缀」（系列/站点尾标）；勿碰番号内嵌的 -
    title = re.sub(r"\s+[-–—]\s+[^-–—]+$", "", title).strip()
    return clean_title(title, std)


def _parse_mosaic(html: str, page_url: str) -> str:
    blob = f"{page_url} {(html or '')[:12000]}"
    if re.search(r"-uncensored-leak|无码影片", blob, re.I):
        return "无码"
    if re.search(r"国产|chinese-av|chinese_av", (html or "")[:15000], re.I):
        return "国产"
    return "有码"


def _parse_detail(html: str, page_url: str, code: str) -> dict:
    if not _is_detail_html(html, code):
        raise RuntimeError("解析失败")
    std = std_code(code)
    title_zh = _parse_title(html, std)
    original = _parse_inline_value(html, ["标题", "標題"]) or ""
    title = title_zh or original
    # 单字/占位标题（案例 ONS-018：站点标题本身就是 `非`）不该打死整源。
    # 详情页有效性已由 _is_detail_html 校验（og:type + 番号 + 番号 token 三重），
    # 与 dmm/jav321/javday 及 make_detail 的兜底口径保持一致：
    # 标题清空，其余字段照常返回；真·空页由下方 (not title and not cover and ...) 拦住。
    if title and is_junk_title(title):
        title = ""

    actors = _parse_label_links(html, ["女优", "女優"])[:20]
    genres = _parse_label_links(html, ["类型", "類型"])[:40]
    directors = _parse_label_links(html, ["导演", "導演"])[:5]
    series = _parse_inline_value(html, ["系列"]) or None
    studio = _parse_inline_value(html, ["发行商", "發行商", "片商"]) or None
    publisher = _parse_inline_value(html, ["标籤", "標籤", "标签", "Label"]) or None
    m_date = re.search(
        r'property=["\']og:video:release_date["\']\s+content=["\']([^"\']+)["\']', html, re.I
    )
    premiered = (m_date.group(1) if m_date else "")[:10] or (
        _parse_inline_value(html, ["发行日期", "發行日期", "上映日期"])[:10] or None
    )
    m_dur = re.search(r'property=["\']og:video:duration["\']\s+content=["\'](\d+)["\']', html, re.I)
    runtime_sec = int(m_dur.group(1)) if m_dur else 0
    runtime = max(1, round(runtime_sec / 60)) if runtime_sec > 0 else None
    plot = _parse_plot(html)

    cover = pick_og_image(html) or ""
    if cover:
        cover = abs_url(cover, page_url) or cover
    if cover and is_junk_cover_url(cover):
        cover = None

    extra: dict = {
        "website": page_url,
        "mosaic": _parse_mosaic(html, page_url),
        "titleZh": title_zh or title or None,
    }
    if original and original != title:
        extra["originalTitle"] = original
    if publisher:
        extra["publisher"] = publisher
    if series:
        extra["series"] = series
    if directors:
        extra["director"] = directors[0]
        extra["directors"] = directors
    if runtime:
        extra["runtime"] = runtime

    if not title and not cover and not actors and not genres and not plot:
        raise RuntimeError("解析失败")

    return make_detail(
        source=SOURCE,
        code=std,
        title=title or None,
        poster=cover,
        studio=studio,
        actors=actors,
        tags=genres,
        overview=plot or None,
        date=premiered,
        extra=extra,
    )


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")
    base = (base_url or DEFAULT_BASE).rstrip("/")
    if not base:
        raise RuntimeError("未配置网站地址")
    referer = f"{base}/cn/"
    ck = cookie or None

    last_err: Exception | None = None
    thin_keep: dict | None = None
    for path_code in _path_codes(std):
        url = f"{base}/cn/{quote(path_code)}"
        try:
            html = fetch_html(url, referer=referer, cookie=ck, source_id=SOURCE)
            if not html or len(html) < 5000:
                continue
            parsed = _parse_detail(html, url, std)
            title = str(parsed.get("title") or "").strip()
            # 薄页（slug fc2-{n} 常只有「FC2-PPV」）继续试 fc2-ppv-{n}
            if title and not is_junk_title(title) and len(title) >= 8:
                return parsed
            if parsed.get("posterUrl") or parsed.get("overview") or parsed.get("actors"):
                thin_keep = thin_keep or parsed
                last_err = RuntimeError(f"薄标题:{title or '空'}")
            else:
                last_err = RuntimeError("解析失败")
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

    search_url = f"{base}/cn/search/{quote(std)}"
    try:
        search_html = fetch_html(search_url, referer=referer, cookie=ck, source_id=SOURCE)
    except Exception as e:
        if thin_keep is not None:
            return thin_keep
        raise RuntimeError(f"搜索无响应: {e}") from e
    if not search_html or len(search_html) < 5000:
        if thin_keep is not None:
            return thin_keep
        raise RuntimeError(f"搜索无响应: {last_err}")

    detail_path = _pick_detail_href(search_html, std)
    if not detail_path:
        if thin_keep is not None:
            return thin_keep
        raise RuntimeError("未找到")
    detail_url = abs_url(detail_path, base) or detail_path
    try:
        detail_html = fetch_html(detail_url, referer=search_url, cookie=ck, source_id=SOURCE)
    except Exception as e:
        if thin_keep is not None:
            return thin_keep
        raise RuntimeError(f"详情页无响应: {e}") from e
    if not detail_html or len(detail_html) < 5000:
        if thin_keep is not None:
            return thin_keep
        raise RuntimeError("详情页无响应")
    parsed = _parse_detail(detail_html, detail_url, std)
    title = str(parsed.get("title") or "").strip()
    if title and not is_junk_title(title) and len(title) >= 8:
        return parsed
    return thin_keep or parsed
