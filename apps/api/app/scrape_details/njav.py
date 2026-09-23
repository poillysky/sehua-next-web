# -*- coding: utf-8 -*-
"""NJAV / 123AV 详情刮削（对齐 MDCS njav.ts）。"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote

from .common import (
    abs_url,
    amateur_digit_board_prefixes,
    clean_title,
    code_equiv,
    date6_search_variants,
    fc2_slug_variants,
    fetch_html,
    is_junk_cover_url,
    is_junk_title,
    make_detail,
    soup,
    std_code,
    strip_tags,
)
from app.core import detail_path_cache

DEFAULT_BASE = "https://123av.com/ja"
DETAIL_SUFFIX_RE = re.compile(
    r"-(?:uncensored-leaked|uncensored-leak|english-subtitle|chinese-subtitle)$",
    re.I,
)
SOURCE = "njav"


def njav_code_candidates(code: str) -> list[str]:
    """直链 / 搜索候选：pad / 素人加板号 / 剥板号 / 无码 date6 / FC2-PPV。"""
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
            if parsed.shape == "std" and parsed.prefix and len(parsed.parts) >= 2:
                pref = str(parsed.prefix).upper()
                num = str(parsed.parts[1])
                _add(std_code_key(parsed.canonical, pad=3))
                _add(std_code_key(parsed.canonical, pad=4))
                # 裸字母号 → 加数字板号（HMDN-332 → 328HMDN-332）
                if not re.match(r"^\d{2,3}[A-Z]", pref):
                    for board in amateur_digit_board_prefixes(pref):
                        _add(f"{board}-{num}")
                        _add(std_code_key(f"{board}-{num}", pad=3))
    except Exception:  # noqa: BLE001
        pass
    for v in date6_search_variants(raw):
        _add(v)
    for v in fc2_slug_variants(raw):
        _add(v)
        _add(v.upper())
    m = re.search(r"(?:FC2[-_]?PPV[-_]?|FC2[-_]?)(\d+)", raw, re.I)
    if m:
        fid = m.group(1)
        _add(f"FC2-PPV-{fid}")
        _add(f"FC2-{fid}")
    return out


def _path_slugs(code: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def _add(v: str) -> None:
        s = str(v or "").strip().lower()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s)

    for cand in njav_code_candidates(code):
        if re.match(r"^fc2", cand, re.I):
            for v in fc2_slug_variants(cand):
                _add(v)
        # date6 裸下划线必须保留（062014_830）
        if "_" in cand and re.search(r"\d{6}_\d+", cand):
            _add(cand)
        _add(cand)
        _add(cand.replace("_", "-"))
        _add(re.sub(r"[-_]", "", cand))
    return out


def _locale_base(base_url: str) -> str:
    raw = str(base_url or DEFAULT_BASE).rstrip("/")
    if re.search(r"/(ja|en|cn|zh|ko)(?:/|$)", raw, re.I):
        return raw
    return f"{raw}/ja"


def _pick_detail_href(html: str, code: str) -> str:
    want = {s.lower() for s in _path_slugs(code)}
    hrefs: list[str] = []
    for pat in (
        r'href=["\']([^"\']*/v/[^"\'#?]+)["\']',
        r'href=["\']([^"\']*/videos/[^"\'#?]+)["\']',
        r'class=["\'][^"\']*(?:box-item|detail)[^"\']*["\'][^>]*>[\s\S]*?href=["\']([^"\']+)["\']',
    ):
        hrefs.extend(m.group(1) for m in re.finditer(pat, html or "", re.I))

    scored: list[tuple[str, int]] = []
    for h in dict.fromkeys(hrefs):
        path = h.split("?")[0].lower()
        slug = path.rstrip("/").split("/")[-1] if path else ""
        score = 0
        if DETAIL_SUFFIX_RE.search(slug):
            score -= 80
        if slug in want or any(code_equiv(slug, c) for c in njav_code_candidates(code)):
            score += 100
        if re.search(r"/search/", path, re.I):
            score -= 50
        if re.search(r"uncensored", slug, re.I):
            score -= 20
        scored.append((h, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0] if scored and scored[0][1] >= 100 else ""


def _is_detail_html(html: str, code: str) -> bool:
    if not html or len(html) < 4000:
        return False
    if re.search(r"123av\.com に移転|moved__title|404 — 123AV", html[:12000], re.I):
        return False
    m = re.search(r"<dt>コード</dt>\s*<dd[^>]*>([^<]+)<", html, re.I) or re.search(
        r"<dt>代码</dt>\s*<dd[^>]*>([^<]+)<", html, re.I
    )
    page_code = strip_tags(m.group(1) if m else "")
    if page_code:
        if any(code_equiv(page_code, c) for c in njav_code_candidates(code)):
            pass
        else:
            return False
    return bool(
        re.search(r'class=["\']watch__title["\']', html)
        or re.search(r'class=["\']watch__info-row["\']', html)
        or (re.search(r'id=["\']player["\']', html) and re.search(r"detail-item", html))
    )


def _parse_info_rows(html: str) -> dict[str, list[str]]:
    doc = soup(html)
    out: dict[str, list[str]] = {}
    for el in doc.select("div.watch__info-row"):
        dt = el.select_one("dt")
        key = strip_tags(dt.get_text() if dt else "")
        chips = [strip_tags(a.get_text()) for a in el.select("dd a.chip") if strip_tags(a.get_text())]
        if chips:
            out[key] = chips
            continue
        dd = el.select_one("dd")
        if not dd:
            continue
        # clone text without children
        plain_parts: list[str] = []
        for child in dd.children:
            if getattr(child, "name", None) is None:
                plain_parts.append(str(child))
        plain = strip_tags("".join(plain_parts))
        if plain:
            out[key] = [plain]
    return out


def _parse_legacy_rows(html: str) -> dict[str, list[str]]:
    doc = soup(html)
    out: dict[str, list[str]] = {}
    for el in doc.select("div.detail-item > div"):
        spans = el.select("span")
        if not spans:
            continue
        key = re.sub(r"[:：\s]", "", strip_tags(spans[0].get_text()))
        links: list[str] = []
        plain = ""
        if len(spans) > 1:
            links = [strip_tags(a.get_text()) for a in spans[1].select("a") if strip_tags(a.get_text())]
            plain = strip_tags(spans[1].get_text())
        if re.search(r"女優|女优|Actress", key, re.I):
            out["出演者"] = links if links else ([plain] if plain else [])
        elif re.search(r"ジャンル|类型|Genre", key, re.I):
            out["ジャンル"] = links
        elif re.search(r"メーカー|片商|Maker", key, re.I):
            val = plain or (links[0] if links else "")
            if val:
                out["メーカー"] = [val]
        elif re.search(r"シリーズ|系列|Series", key, re.I):
            val = plain or (links[0] if links else "")
            if val:
                out["シリーズ"] = [val]
        elif re.search(r"コード|番号|Code", key, re.I):
            if plain:
                out["コード"] = [plain]
        elif re.search(r"公開日|发行|Release", key, re.I):
            if plain:
                out["発売日"] = [plain]
        elif re.search(r"再生時間|时长|Duration", key, re.I):
            if plain:
                out["再生時間"] = [plain]
    return out


def _first_row(rows: dict[str, list[str]], *keys: str) -> str:
    for k in keys:
        vals = rows.get(k) or []
        if vals and str(vals[0]).strip():
            return str(vals[0]).strip()
    return ""


def _row_list(rows: dict[str, list[str]], *keys: str) -> list[str]:
    for k in keys:
        vals = rows.get(k)
        if vals:
            return list(vals)
    return []


def _parse_cover(html: str, page_url: str) -> str | None:
    decoded = html.replace("\\u002F", "/").replace("\\u0026", "&")
    m = re.search(r"https?://icdn\.123av\.me/[^\"'\\\s]+cover\.jpg[^\"'\\\s]*", decoded, re.I) or re.search(
        r"poster=https%3A%2F%2Ficdn\.123av\.me[^\"'\\]+cover\.jpg[^\"'\\]*", decoded, re.I
    )
    if m:
        url = m.group(0)
        if url.startswith("poster="):
            url = unquote(url[len("poster=") :])
        return abs_url(url, page_url) or url
    doc = soup(html)
    player = doc.select_one("#player")
    poster = (player.get("data-poster") if player else "") or ""
    if poster:
        return abs_url(poster, page_url)
    return None


def _parse_title(html: str, code: str) -> str:
    doc = soup(html)
    h1 = doc.select_one("h1.watch__title") or doc.select_one("h1")
    raw = strip_tags(h1.get_text() if h1 else "")
    if not raw:
        tm = re.search(r"<title>([^<]+)</title>", html, re.I)
        raw = re.sub(r"\s*—\s*123AV.*", "", tm.group(1) if tm else "", flags=re.I)
    std = std_code(code)
    pat = re.escape(std).replace(r"\-", "[-]?")
    title = re.sub(rf"^{pat}\s*[—–-]\s*", "", raw, flags=re.I).strip()
    title = re.sub(rf"^{pat}\s*", "", title, flags=re.I).strip()
    return clean_title(title, std)


def scrape_detail(code: str, *, base_url: str = "", cookie: str = "", api_key: str = "") -> dict:
    del api_key
    std = std_code(code)
    if not std:
        raise RuntimeError("番号为空")

    base = _locale_base(base_url or DEFAULT_BASE)
    if not base:
        raise RuntimeError("未配置网站地址")

    referer = f"{base}/"

    def _build(detail_html: str, detail_url: str) -> dict:
        """校验 + 解析 + 构造（搜索路径与缓存路径共用）。失败抛 RuntimeError。"""
        if not detail_html or len(detail_html) < 2000:
            raise RuntimeError("详情页无响应")
        if not _is_detail_html(detail_html, std):
            raise RuntimeError("解析失败")

        rows = _parse_info_rows(detail_html)
        if not rows:
            rows = _parse_legacy_rows(detail_html)

        title = _parse_title(detail_html, std)
        # 与 miss_av / dmm / jav321 / javday 及 make_detail 口径一致：
        # 单字/占位标题（站点标题本身就短）只清空标题，不打死整源；
        # 详情页有效性已由 _is_detail_html 校验，真·空页由下方 (not title and not cover and ...) 拦住。
        if title and is_junk_title(title):
            title = ""

        actors = _row_list(rows, "出演者", "女優", "女优", "Actress")[:20]
        # 站点偶发半角片假名（倉本ｽﾐﾚ）→ 全角，便于后续映射
        import unicodedata

        actors = [unicodedata.normalize("NFKC", a) for a in actors if a]
        tags = []
        for g in _row_list(rows, "ジャンル", "类型", "Genre") + _row_list(rows, "タグ", "标签", "Tag"):
            if g and g not in tags:
                tags.append(g)
        tags = tags[:40]

        studio = _first_row(rows, "メーカー", "片商", "Maker") or None
        premiered = (_first_row(rows, "発売日", "发行日", "Release", "公開日") or "")[:10] or None

        doc = soup(detail_html)
        desc = doc.select_one("div.description p")
        plot = strip_tags(desc.get_text() if desc else "")
        if not plot or len(plot) < 12:
            plot = ""

        cover = _parse_cover(detail_html, detail_url)
        if cover and is_junk_cover_url(cover):
            cover = None

        if not title and not cover and not actors and not tags:
            raise RuntimeError("解析失败")

        return make_detail(
            source="njav",
            code=std,
            title=title or None,
            poster=cover,
            studio=studio,
            actors=actors,
            tags=tags,
            overview=plot or None,
            date=premiered,
            extra={"website": detail_url},
        )

    # 第十六轮：详情路径缓存命中 → 直接抓详情，跳过搜索（重复刮省 1 请求）。
    # _is_detail_html 校验不过回落搜索；坏缓存最多浪费 1 请求，不会错绑。
    cached_path = detail_path_cache.lookup("njav", std)
    if cached_path:
        try:
            cached_url = abs_url(cached_path, f"{base}/") or cached_path
            cached_html = fetch_html(
                cached_url, referer=referer, cookie=cookie or None, source_id="njav"
            )
            return _build(cached_html or "", cached_url)
        except Exception:
            pass  # 缓存失效 → 回落直链/搜索

    # 直链 /v/{slug}（FC2-PPV、328HMDN 等站内形态）
    last_err: Exception | None = None
    for slug in _path_slugs(std):
        url = f"{base}/v/{quote(slug)}"
        try:
            html = fetch_html(url, referer=referer, cookie=cookie or None, source_id=SOURCE)
            if html and _is_detail_html(html, std):
                detail_path_cache.remember("njav", std, f"/v/{slug}")
                return _build(html, url)
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue

    # 搜索：多候选关键词（FC2 裸号 / 板号）
    detail_path = ""
    search_url = ""
    for kw in njav_code_candidates(std):
        search_url = f"{base}/search?keyword={quote(kw)}"
        try:
            search_html = fetch_html(
                search_url, referer=referer, cookie=cookie or None, source_id=SOURCE
            )
        except Exception as e:
            last_err = e
            continue
        if not search_html or len(search_html) < 2000:
            continue
        detail_path = _pick_detail_href(search_html, std)
        if detail_path:
            break

    if not detail_path:
        raise RuntimeError(f"未找到" + (f": {last_err}" if last_err else ""))

    detail_url = abs_url(detail_path, f"{base}/") or detail_path
    detail_path_cache.remember("njav", std, detail_path)
    try:
        detail_html = fetch_html(
            detail_url, referer=search_url or referer, cookie=cookie or None, source_id=SOURCE
        )
    except Exception as e:
        raise RuntimeError(f"详情页无响应: {e}") from e

    return _build(detail_html or "", detail_url)
