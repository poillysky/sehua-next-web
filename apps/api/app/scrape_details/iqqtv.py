# -*- coding: utf-8 -*-
"""iQQTV 详情刮削（对齐 MDCS iqqtv.ts · CN/JP 双页）。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from app.core import detail_path_cache

from .common import (
    abs_url,
    clean_title,
    code_equiv,
    fetch_html,
    fetch_html_result,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    page_mentions_code,
    parse_fc2_id,
    pick_og_image,
    std_code,
    strip_tags,
    soup,
)

DEFAULT_ROOT = "https://iqqk4.quest"
SOURCE = "iqqtv"

TITLE_TRAILING_MARKERS = {
    "HD",
    "FHD",
    "UHD",
    "SD",
    "VR",
    "2K",
    "4K",
    "720P",
    "1080P",
    "2160P",
}
OUTLINE_PREFIX = re.compile(r"^(?:简介|簡介|介绍|介紹|紹介)\s*[:：]?\s*")
JUNK_TITLE_RE = re.compile(r"克破|无码破解|無碼破解|无码流出|無碼流出|马赛克破坏|馬賽克破壞", re.I)
WEB_NUMBER_PREFIX = re.compile(
    r"^(?:_?1pondo|1pon|caribbeancom(?:pr)?|carib|pacopacomama|pacoma|paco|10musume|10mu)[_-]*",
    re.I,
)
WEB_NUMBER_SUFFIX = re.compile(r"^(?=.*\d)[a-z0-9]+(?:[-_][a-z0-9]+)*$", re.I)

# 站内无码 date6 标题尾常写成 ``_1pondo_062014_830`` / ``062014_830``
_IQQTV_DATE6_BRANDS: dict[str, tuple[str, ...]] = {
    "1PON": ("1pondo", "_1pondo", "pondo"),
    "CARIB": ("caribbeancom", "carib"),
    "CARIBPR": ("caribbeancompr", "caribpr"),
    "10MU": ("10musume", "10mu"),
    "PACO": ("pacopacomama", "paco"),
}


def iqqtv_code_candidates(code: str) -> list[str]:
    """搜索词：原串 / 素人剥板号 / FC2 变体 / 无码 date6（``062014_830``、``_1pondo_…``）。"""
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
            _add(std_code_key(parsed.canonical, pad=3))
            _add(std_code_key(parsed.canonical, pad=4))
        if parsed and parsed.shape == "date6" and len(parsed.parts) >= 3:
            label, d6, nnn = parsed.parts[0], parsed.parts[1], parsed.parts[2]
            _add(f"{d6}_{nnn}")
            _add(f"{d6}-{nnn}")
            for brand in _IQQTV_DATE6_BRANDS.get(label.upper(), ()):
                _add(f"{brand}_{d6}_{nnn}")
                _add(f"_{brand}_{d6}_{nnn}" if not brand.startswith("_") else f"{brand}_{d6}_{nnn}")
                _add(f"{brand}-{d6}_{nnn}")
    except Exception:  # noqa: BLE001
        pass
    fc2 = parse_fc2_id(raw)
    if fc2:
        fid, canon = fc2
        _add(canon)
        _add(f"FC2-PPV-{fid}")
        _add(f"FC2PPV-{fid}")
        _add(f"FC2PPV{fid}")
        _add(fid)
    return out


def match_iqqtv_number(text: str, number: str) -> bool:
    """MDCX number.match_number：BF-002 不匹配 ABF-002；另容忍板号/FC2/date6 等价。"""
    hay = str(text or "")
    num = str(number or "").strip()
    if not num or not hay:
        return False
    if re.match(r"^\d", num):
        if num.upper() in hay.upper():
            return True
    else:
        esc = re.escape(num)
        if re.search(rf"(?<![A-Z0-9]){esc}(?![A-Z0-9])", hay, re.I):
            return True
    # 标题尾 / 内嵌番号用 code_equiv（259LUXU≡LUXU、FC2≡FC2PPV）
    for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", hay):
        if code_equiv(tok, num):
            return True
    # 无码：标题常 ``_1pondo_062014_830`` / ``062014_830``，与 ``1PON-062014-830`` 不等价折叠
    try:
        from app.search.av import parse_maker_code

        parsed = parse_maker_code(num)
        if parsed and parsed.shape == "date6" and len(parsed.parts) >= 3:
            d6, nnn = parsed.parts[1], parsed.parts[2]
            label = parsed.parts[0].upper()
            brands = _IQQTV_DATE6_BRANDS.get(label, ())
            brand_alt = "|".join(
                re.escape(b.lstrip("_")) for b in brands if b
            )
            if brand_alt and re.search(
                rf"(?<![A-Za-z0-9])_?(?:{brand_alt})[_-]?{re.escape(d6)}[_-]{re.escape(nnn)}(?![A-Za-z0-9])",
                hay,
                re.I,
            ):
                return True
            if re.search(
                rf"(?<![A-Za-z0-9]){re.escape(d6)}[_-]{re.escape(nnn)}(?![A-Za-z0-9])",
                hay,
                re.I,
            ):
                return True
    except Exception:  # noqa: BLE001
        pass
    return False

def _iqqtv_page_mentions(html: str, code: str) -> bool:
    """详情页番号校验：标准 mentions + 标题内板号/FC2/date6 等价。"""
    if page_mentions_code(html, code):
        return True
    doc = soup(html)
    h1 = doc.select_one("h1.h4.b, h1")
    title = strip_tags(h1.get_text()) if h1 else ""
    if title and match_iqqtv_number(title, code):
        return True
    # og / 副标题偶发带番号
    for el in doc.select("title, meta[property='og:title']"):
        raw = el.get("content") if el.name == "meta" else el.get_text()
        if match_iqqtv_number(strip_tags(str(raw or "")), code):
            return True
    return False


def junk_iqqtv_title(title: str) -> bool:
    return bool(JUNK_TITLE_RE.search(title or ""))


def get_iqqtv_real_title(title: str) -> str:
    parts = title.strip().split()
    if len(parts) > 1 and parts[-1].upper() in TITLE_TRAILING_MARKERS:
        parts.pop()
    return " ".join(parts).strip()


def _clean_iqqtv_web_number_token(value: str) -> str:
    result = str(value or "").strip()
    result = re.sub(r"-PPV$", "", result, flags=re.I)
    result = WEB_NUMBER_PREFIX.sub("", result)
    return result.strip().lstrip("_-")


def _same_iqqtv_web_number(left: str, right: str) -> bool:
    a = re.sub(r"[-_]", "", _clean_iqqtv_web_number_token(left)).upper()
    b = re.sub(r"[-_]", "", _clean_iqqtv_web_number_token(right)).upper()
    return bool(a and b and a == b)


def _looks_like_iqqtv_web_number(value: str) -> bool:
    return bool(WEB_NUMBER_SUFFIX.match(_clean_iqqtv_web_number_token(value)))


def remove_iqqtv_web_number_suffix(title: str, number: str) -> str:
    t = title.strip()
    if not t:
        return ""
    parts = t.split()
    if len(parts) < 2:
        return t
    suffix = parts[-1]
    if _looks_like_iqqtv_web_number(suffix) and _same_iqqtv_web_number(suffix, number):
        return " ".join(parts[:-1]).strip()
    return t


def _clean_iqqtv_page_title(raw: str, number: str) -> str:
    title = get_iqqtv_real_title(remove_iqqtv_web_number_suffix(raw.strip(), number))
    title = re.sub(r"\s*iQQTV\s*.*$", "", title, flags=re.I).strip()
    title = clean_title(title, number)
    if not title or is_junk_title(title) or junk_iqqtv_title(title):
        return ""
    return title


def parse_iqqtv_outline(html: str) -> str:
    doc = soup(html)
    result = ""
    intro = doc.select_one('div[class*="intro"] p')
    if intro:
        result = strip_tags(intro.get_text())
    if not result:
        for el in doc.select("p"):
            t = strip_tags(el.get_text())
            if re.search(r"简介|簡介|介绍|介紹|紹介", t):
                result = t
                break
    result = re.sub(r"[\r\n\t]", "", result)
    result = OUTLINE_PREFIX.sub("", result)
    result = result.split("*根据分发")[0].strip()
    if not result or junk_iqqtv_title(result):
        return ""
    return result if len(result) >= 2 else ""


def get_iqqtv_real_url(html: str, number: str) -> str:
    doc = soup(html)
    for span in doc.select("span.title"):
        a = span.find("a")
        if not a:
            continue
        href = a.get("href") or ""
        title = a.get("title") or ""
        if not href or not title:
            continue
        if not match_iqqtv_number(title, number) or junk_iqqtv_title(title):
            continue
        return href
    return ""


def parse_iqqtv_detail_html(html: str, code: str, page_url: str) -> dict[str, Any]:
    std = std_code(code)
    doc = soup(html)
    h1 = doc.select_one("h1.h4.b")
    raw_title = strip_tags(h1.get_text()) if h1 else ""
    title = _clean_iqqtv_page_title(raw_title, std)

    actors: list[str] = []
    for el in doc.select('a[href*="actor"] span'):
        n = strip_tags(el.get_text())
        if n and len(n) < 40 and n not in actors:
            actors.append(n)

    genres: list[str] = []
    for el in doc.select('.tag-info a[href*="tag"], a[href*="s_type=tag"]'):
        n = strip_tags(el.get_text())
        if not n or len(n) > 24 or re.search(r"更多|全部|类别", n, re.I) or n in genres:
            continue
        genres.append(n)

    studio_el = doc.select_one('a[href*="fac"] [itemprop="name"]')
    studio = strip_tags(studio_el.get_text()) if studio_el else ""
    if len(studio) > 60:
        studio = ""

    series_el = doc.select_one('a[href*="series"]')
    series = strip_tags(series_el.get_text()) if series_el else ""
    if len(series) < 2 or is_junk_title(series):
        series = ""

    plot = parse_iqqtv_outline(html)
    date_el = doc.select_one("div.date")
    date_raw = strip_tags(date_el.get_text()).replace("/", "-") if date_el else ""
    dm = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_raw)
    premiered = (
        f"{dm.group(1)}-{int(dm.group(2)):02d}-{int(dm.group(3)):02d}" if dm else ""
    )

    img = doc.select_one('img[itemprop="image"]')
    cover = pick_og_image(html) or (
        abs_url(img.get("src"), page_url) if img and img.get("src") else None
    )
    if cover and is_junk_cover_url(cover):
        cover = None

    return {
        "title": title or None,
        "plot": plot or None,
        "actors": actors,
        "genres": genres,
        "studio": studio or None,
        "series": series or None,
        "premiered": premiered or None,
        "website": page_url,
        "coverUrl": cover,
    }


def _root(base_url: str) -> str:
    raw = str(base_url or DEFAULT_ROOT).strip().rstrip("/")
    if not raw:
        return DEFAULT_ROOT
    return re.sub(r"/(cn|ja|en|zh|jp)/?$", "", raw, flags=re.I).rstrip("/") or DEFAULT_ROOT


def _lang_bases(root: str) -> tuple[str, str]:
    base = root.rstrip("/")
    if re.search(r"/cn$", base, re.I):
        return re.sub(r"/cn$", "/jp", base, flags=re.I), base
    return f"{base}/jp", f"{base}/cn"


def scrape_detail(
    code: str, *, base_url: str = "", cookie: str = "", api_key: str = ""
) -> dict[str, Any]:
    del api_key
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")

    root = _root(base_url or DEFAULT_ROOT)
    if base_url:
        try:
            from app.core import site_mirror

            site_mirror.remember("iqqtv", root, discovered_from=root)
        except Exception:
            pass

    jp_base, cn_base = _lang_bases(root)
    ck = cookie or None

    def _fetch_pair(rel: str, referer: str) -> tuple[str, str, str, str]:
        """抓详情页。中文优先；日文仅在中文缺标题时补，避免双页串行把单源预算吃光。

        跑久后卡顿主因：4 路番号 × iqqtv 双页 = 同站 page 槽打满，放弃后 curl
        僵尸仍占槽 → 全员顶满 15s 超时。减半请求 + 取消令牌同线程生效。
        """
        from app.core.outbound_http import thread_is_cancelled

        jp_url = abs_url(f"/jp/{rel}", f"{jp_base}/") or f"{jp_base}/{rel}"
        cn_url = abs_url(f"/cn/{rel}", f"{cn_base}/") or f"{cn_base}/{rel}"

        def _fetch(url: str) -> str:
            if thread_is_cancelled():
                raise RuntimeError("已放弃(早停)")
            return fetch_html(url, referer=referer, cookie=ck, source_id=SOURCE)

        cn_html = _fetch(cn_url)
        if not cn_html or len(cn_html) < 800 or not _iqqtv_page_mentions(cn_html, std):
            # 中文页不可用再试日文
            if thread_is_cancelled():
                raise RuntimeError("中文详情不可用")
            jp_html = _fetch(jp_url)
            if not jp_html or len(jp_html) < 800 or not _iqqtv_page_mentions(jp_html, std):
                raise RuntimeError("日文详情不可用")
            return jp_html, jp_html, jp_url, jp_url

        # 中文已够用：默认不再拉日文（标题/剧情合并侧偏 CN）
        cn_parsed_title = ""
        try:
            cn_parsed_title = str(
                parse_iqqtv_detail_html(cn_html, std, cn_url).get("title") or ""
            ).strip()
        except Exception:
            cn_parsed_title = ""
        if cn_parsed_title:
            return cn_html, cn_html, cn_url, cn_url

        if thread_is_cancelled():
            raise RuntimeError("中文无标题且已放弃")
        jp_html = _fetch(jp_url)
        if not jp_html or len(jp_html) < 800 or not _iqqtv_page_mentions(jp_html, std):
            raise RuntimeError("日文详情不可用")
        return jp_html, cn_html, jp_url, cn_url

    def _build_detail(
        jp_html: str, cn_html: str, jp_url: str, cn_url: str
    ) -> dict[str, Any]:
        jp = parse_iqqtv_detail_html(jp_html, std, jp_url)
        cn = parse_iqqtv_detail_html(cn_html, std, cn_url)
        if not cn.get("title") and not jp.get("title"):
            raise RuntimeError("未找到标题")

        cover = cn.get("coverUrl") or jp.get("coverUrl")
        actors = cn.get("actors") or jp.get("actors") or []
        genres = cn.get("genres") or jp.get("genres") or []
        title_jp = jp.get("title") or cn.get("title")
        title_zh = cn.get("title") or jp.get("title")
        plot = cn.get("plot") or jp.get("plot")
        original_plot = jp.get("plot") or cn.get("plot")

        return make_detail(
            source=SOURCE,
            code=std,
            # 合并侧偏中文：title 优先 CN，日文进 originalTitle
            title=title_zh or title_jp,
            poster=cover,
            studio=(cn.get("studio") or jp.get("studio")),
            actors=list(actors),
            tags=list(genres),
            overview=plot,
            date=(cn.get("premiered") or jp.get("premiered")),
            extra={
                "titleZh": title_zh,
                "originalTitle": title_jp,
                "originalPlot": original_plot,
                "series": cn.get("series") or jp.get("series"),
                "website": cn_url,
            },
        )

    def _from_rel(rel: str, referer: str) -> dict[str, Any]:
        jp_html, cn_html, jp_url, cn_url = _fetch_pair(rel, referer)
        return _build_detail(jp_html, cn_html, jp_url, cn_url)

    # 第十六轮：详情路径缓存命中 → 直接抓双页，跳过搜索（重复刮省最慢的 1 请求）。
    # 页面校验不过 → 抛错回落下方搜索并刷新缓存；坏缓存最多浪费 1 请求，不会错绑。
    cached_rel = detail_path_cache.lookup(SOURCE, std)
    if cached_rel:
        try:
            return _from_rel(cached_rel, f"{jp_base}/")
        except Exception:
            pass

    detail_path = ""
    search_url = f"{jp_base}/search.php?kw={quote(std)}"
    saw_html = False
    last_err: Exception | None = None
    for cand in iqqtv_code_candidates(std):
        search_url = f"{jp_base}/search.php?kw={quote(cand)}"
        try:
            search_html, landed = fetch_html_result(
                search_url,
                referer=f"{jp_base}/",
                cookie=ck,
                source_id=SOURCE,
            )
        except Exception as e:
            last_err = e
            continue

        if landed:
            try:
                from app.core import site_mirror

                host = re.match(r"https?://[^/]+", landed)
                if host:
                    site_mirror.remember(
                        "iqqtv", host.group(0), discovered_from=search_url
                    )
                    root = _root(host.group(0))
                    jp_base, cn_base = _lang_bases(root)
            except Exception:
                pass

        if not search_html or len(search_html) < 400:
            continue
        saw_html = True

        # 用原始 std 做等价匹配（cand 可能是剥板号 / date6 / FC2PPV）
        detail_path = get_iqqtv_real_url(search_html, std)
        if detail_path:
            break

    if not detail_path:
        if not saw_html and last_err is not None:
            raise RuntimeError(f"搜索失败: {last_err}") from last_err
        raise RuntimeError("搜索无结果" if saw_html else "搜索无响应")

    rel = re.sub(r"^/(cn|jp)/", "", detail_path, flags=re.I).lstrip("/")
    # 第十六轮：记住详情路径（uuid 对同番号稳定），重复刮直接走缓存跳过搜索
    detail_path_cache.remember(SOURCE, std, rel)
    return _from_rel(rel, search_url)
