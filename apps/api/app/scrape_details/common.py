# -*- coding: utf-8 -*-
"""刮削详情公共工具（对齐 MDCS htmlUtils + 统一写库字段）。"""

from __future__ import annotations

import re
import threading
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.core.year_utils import year_search as year_from

DetailDict = dict[str, Any]

# 线程本地「同一份 html 只解析一次」缓存。
#
# 背景（第八轮实测，`_diag_cpu_profile.py`）：各源把**同一份 html 反复传给
# 多个 `_parse_*(html)` helper** —— mgstage 一条详情要调度 14 次全量 lxml 解析
# （品番/メーカー/レーベル/シリーズ/配信開始日/商品発売日/収録時間/出演 + 
# title/outline/genres/cover/extrafanart/rating）。单番号 CPU 里
# bs4+soupsieve 占比 ~96%，我们自己业务代码只有 ~100ms —— 这是刮削吞吐的
# 第一瓶颈，而且它随「命中率高的番号族」放大，表现为「越刮越慢 + 假超时」。
#
# 键用**对象身份**（`is`）：同一次 scrape_detail 里各 helper 拿到的是同一个
# str 对象。线程本地 + 单条，跨番号不保留解析树（BeautifulSoup 树很占内存），
# 抓取线程用完随线程回收，无跨线程共享故不需要锁。
_tls = threading.local()


def strip_tags(s: str) -> str:
    import html as _html

    t = _html.unescape(str(s or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)).strip()


def code_key(s: str) -> str:
    return re.sub(r"[-_\s]", "", str(s or "")).upper()


def fold_code(s: str) -> str:
    """对齐 MDCX/Amane：去掉 - _ . 空白后大写，供 URL/番号精确匹配。"""
    return re.sub(r"[-_.\s]", "", str(s or "")).upper()


def parse_fc2_id(code: str) -> tuple[str, str] | None:
    """`FC2-PPV-1234567` / `FC2-1234567` → `("1234567", "FC2-1234567")`。

    fc2 / fd2ppv 两个详情源共用：番号形态一致，展示/落盘统一 ``FC2-{id}``。
    """
    m = re.search(r"FC2[-_]?PPV[-_]?(\d+)", code, re.I) or re.search(
        r"FC2[-_]?(\d+)", code, re.I
    )
    if not m:
        return None
    fid = m.group(1)
    return fid, f"FC2-{fid}"


def fc2_slug_variants(code: str) -> list[str]:
    """站点 URL / 搜索用的 FC2 形态：优先 ``fc2-ppv-{id}``（MissAV 等站真实 slug）。

    目录已归一成 ``FC2-{n}`` 后，若先打 ``fc2-{n}`` 可能命中薄页（标题仅 ``FC2-PPV``），
    必须把 PPV slug 放前面，否则重刮挂不上标题/封面。
    """
    parsed = parse_fc2_id(code)
    if not parsed:
        return []
    fid, _canon = parsed
    out: list[str] = []
    for raw in (
        f"fc2-ppv-{fid}",
        f"fc2ppv-{fid}",
        f"fc2ppv{fid}",
        f"fc2-{fid}",
        f"fc2{fid}",
    ):
        if raw not in out:
            out.append(raw)
    return out


# JavBus 无码 date6 站内常见品牌前缀（路径/search 用，小写）
_JAVBUS_DATE6_BRANDS: dict[str, tuple[str, ...]] = {
    "1PON": ("1pondo", "pondo"),
    "CARIB": ("caribbeancom", "caribbean"),
    "CARIBPR": ("caribbeancompr", "caribpr"),
    "10MU": ("10musume", "musume"),
    "PACO": ("pacopacomama", "paco"),
}

# 综合站搜索常用 date6 变体（裸日期 + 品牌 slug；与 code_equiv 折叠键无关）
_DATE6_SEARCH_BRANDS: dict[str, tuple[str, ...]] = {
    "1PON": ("1pondo", "pondo", "_1pondo"),
    "CARIB": ("caribbeancom", "caribbean", "carib"),
    "CARIBPR": ("caribbeancompr", "caribpr"),
    "10MU": ("10musume", "musume", "10mu"),
    "PACO": ("pacopacomama", "paco"),
}


def date6_search_variants(
    code: str, *, brands: dict[str, tuple[str, ...]] | None = None
) -> list[str]:
    """无码 date6 搜索/路径候选：``062014_830`` / ``1pondo_…`` 等。

    ``code_equiv`` 不把裸日期与 ``1PON-…`` 视为等价，综合站必须显式扩候选。
    """
    raw = str(code or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def _add(s: str) -> None:
        t = str(s or "").strip()
        if t and t not in out:
            out.append(t)

    try:
        from app.search.av import parse_maker_code

        parsed = parse_maker_code(raw)
    except Exception:  # noqa: BLE001
        return []
    if not (parsed and parsed.shape == "date6" and len(parsed.parts) >= 3):
        return []
    label, d6, nnn = parsed.parts[0], parsed.parts[1], parsed.parts[2]
    _add(f"{d6}_{nnn}")
    _add(f"{d6}-{nnn}")
    table = brands if brands is not None else _DATE6_SEARCH_BRANDS
    for brand in table.get(str(label).upper(), ()):
        b = str(brand or "").strip()
        if not b:
            continue
        _add(f"{b}_{d6}_{nnn}")
        _add(f"{b}-{d6}_{nnn}")
        _add(f"{b}-{d6}-{nnn}")
        if not b.startswith("_"):
            _add(f"_{b}_{d6}_{nnn}")
    return out


# 目录不可用时的常见素人板号（japan_amateur 前缀反查失败时兜底）
AMATEUR_FALLBACK_BOARD_PREFIX: dict[str, list[str]] = {
    "LUXU": ["259LUXU"],
    "GANA": ["200GANA"],
    "MIUM": ["300MIUM"],
    "MAAN": ["300MAAN"],
    "NTK": ["300NTK"],
    "DCV": ["277DCV"],
    "HMDN": ["328HMDN"],
}


def amateur_digit_board_prefixes(letters: str) -> list[str]:
    """字母前缀 → 带数字板号的完整前缀（如 LUXU → 259LUXU）。"""
    letters_u = re.sub(r"[^A-Z0-9]", "", str(letters or "").upper())
    if not letters_u:
        return []
    out: list[str] = []
    try:
        from app.prefix import catalog_store as store

        doc = store.load_catalog(force=False)
        prefs = (
            ((doc.get("regions") or {}).get("japan_amateur") or {}).get("prefixes") or {}
        )
        for k in prefs:
            ku = str(k or "").upper()
            if re.fullmatch(rf"\d{{2,3}}{re.escape(letters_u)}", ku):
                if ku not in out:
                    out.append(ku)
    except Exception:  # noqa: BLE001
        pass
    if not out:
        for hit in AMATEUR_FALLBACK_BOARD_PREFIX.get(letters_u) or []:
            if hit not in out:
                out.append(hit)
    return out


def append_amateur_board_variants(add, code: str) -> None:
    """对 ``add(str)`` 追加素人加板 / 剥板变体。"""
    raw = str(code or "").strip()
    if not raw:
        return
    std = std_code(raw).upper()
    bare = re.fullmatch(r"([A-Z]{2,12})-(\d{1,6})", std)
    if bare:
        letters, num = bare.group(1), bare.group(2)
        for board_pref in amateur_digit_board_prefixes(letters):
            add(f"{board_pref}-{num}")
            add(f"{board_pref}-{num.zfill(3)}")
            add(f"{board_pref}-{num.zfill(4)}")
    boarded = re.fullmatch(r"(\d{2,3})([A-Z]{2,12})-(\d{1,6})", std)
    if boarded:
        add(f"{boarded.group(2)}-{boarded.group(3)}")
        add(f"{boarded.group(2)}-{boarded.group(3).zfill(3)}")
        add(f"{boarded.group(2)}-{boarded.group(3).zfill(4)}")


def append_std_pad_variants(add, code: str) -> None:
    """对 ``add(str)`` 追加 parse canonical + pad3/4。"""
    raw = str(code or "").strip()
    if not raw:
        return
    try:
        from app.search.av import parse_maker_code, std_code_key

        parsed = parse_maker_code(raw)
        if parsed and parsed.canonical:
            add(parsed.canonical)
            add(std_code_key(parsed.canonical, pad=3))
            add(std_code_key(parsed.canonical, pad=4))
    except Exception:  # noqa: BLE001
        pass


def javbus_code_candidates(code: str) -> list[str]:
    """JavBus 详情路径候选：有码补零变体 + 无码 date6 slug。

    详情页是 ``GET {base}/{path}``，站点对 pad / 下划线 / 品牌前缀敏感；
    与 ``code_equiv`` 对齐，避免 ``SONE-15``、``1PON-062014-830`` 直接 404。
    """
    raw = str(code or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def _add(s: str) -> None:
        t = str(s or "").strip()
        if t and t not in out:
            out.append(t)

    _add(raw)
    _add(raw.upper())
    _add(raw.replace("_", "-").upper())
    _add(raw.replace("-", "_"))

    parsed = None
    pad_key = None
    try:
        from app.search.av import parse_maker_code, std_code_key as pad_key

        parsed = parse_maker_code(raw)
    except Exception:  # noqa: BLE001
        parsed = None

    if parsed and parsed.shape == "std" and parsed.canonical:
        can = parsed.canonical
        _add(can)
        if pad_key is not None:
            for pad in (3, 4):
                try:
                    _add(pad_key(can, pad=pad))
                except Exception:  # noqa: BLE001
                    pass
        m = re.fullmatch(r"([A-Z0-9]+)-(\d+)", can, re.I)
        if m:
            n = int(m.group(2))
            pref = m.group(1).upper()
            _add(f"{pref}-{n}")
            # 显式 3/4 位：NAMH-0028 → NAMH-028（std_code_key 会保留源串位数）
            for w in (3, 4):
                _add(f"{pref}-{n:0{w}d}")
    elif parsed and parsed.shape == "date6" and len(parsed.parts) >= 3:
        label, d6, nnn = parsed.parts[0], parsed.parts[1], parsed.parts[2]
        _add(f"{label}-{d6}-{nnn}")
        _add(f"{label}-{d6}_{nnn}")
        _add(f"{label}_{d6}_{nnn}")
        _add(f"{d6}-{nnn}")
        _add(f"{d6}_{nnn}")
        for brand in _JAVBUS_DATE6_BRANDS.get(label.upper(), ()):
            _add(f"{brand}-{d6}_{nnn}")
            _add(f"{brand}-{d6}-{nnn}")
            _add(f"{brand}_{d6}_{nnn}")
    elif pad_key is not None:
        try:
            glued = raw.upper().replace("_", "-")
            _add(pad_key(glued, pad=3))
            _add(pad_key(glued, pad=4))
        except Exception:  # noqa: BLE001
            pass

    return out[:20]


def western_code_candidates(code: str) -> list[str]:
    """欧美点分日候选：``STUDIO.YYYY.MM.DD`` ↔ ``STUDIO.YY.MM.DD``。

    不依赖厂牌白名单（AVHeat 上常见 BrazzersExxtra / WeLiveTogether 等子系列键）。
    """
    raw = str(code or "").strip()
    if not raw:
        return []
    out: list[str] = []

    def _add(s: str) -> None:
        t = str(s or "").strip()
        if t and t not in out:
            out.append(t)

    _add(raw)
    try:
        from app.search.av import parse_maker_code

        parsed = parse_maker_code(raw)
    except Exception:  # noqa: BLE001
        parsed = None
    if parsed and parsed.shape == "western_date" and len(parsed.parts) == 4:
        key, yyyy, mo, d = parsed.parts
        _add(f"{key}.{yyyy}.{mo}.{d}")
        if re.fullmatch(r"20\d{2}|19\d{2}", yyyy):
            _add(f"{key}.{yyyy[2:]}.{mo}.{d}")
        return out

    # 未知厂牌：仍按点分日拆 YYYY / YY
    m = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9]*)[._\-](19\d{2}|20\d{2})[._\-](\d{2})[._\-](\d{2})",
        raw,
    )
    if m:
        key, yyyy, mo, d = m.group(1), m.group(2), m.group(3), m.group(4)
        _add(f"{key}.{yyyy}.{mo}.{d}")
        _add(f"{key}.{yyyy[2:]}.{mo}.{d}")
        return out
    m = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9]*)[._\-](\d{2})[._\-](\d{2})[._\-](\d{2})",
        raw,
    )
    if m:
        key, yy, mo, d = m.group(1), m.group(2), m.group(3), m.group(4)
        if yy not in ("19", "20"):
            _add(f"{key}.{yy}.{mo}.{d}")
            _add(f"{key}.20{yy}.{mo}.{d}")
    return out


def _western_date_fold_key(code: str) -> str | None:
    """欧美完整日折叠键：``STUDIO + YYYY + MM + DD``（两位年补 20）。"""
    raw = str(code or "").strip()
    m = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9]*)[._\-](19\d{2}|20\d{2})[._\-](\d{2})[._\-](\d{2})",
        raw,
    )
    if m:
        return f"{m.group(1).upper()}{m.group(2)}{m.group(3)}{m.group(4)}"
    m = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9]*)[._\-](\d{2})[._\-](\d{2})[._\-](\d{2})",
        raw,
    )
    if m and m.group(2) not in ("19", "20"):
        return f"{m.group(1).upper()}20{m.group(2)}{m.group(3)}{m.group(4)}"
    return None


def _code_bucket(folded: str) -> tuple[str, int, str] | None:
    """把折叠后的番号拆成 (字母前缀, 数字, 尾字母)，数字去掉前导零。"""
    # FC2 / FC2PPV 同一数字视为同号（目录归一后与站点 PPV slug 对齐）
    m_fc2 = re.fullmatch(r"FC2(?:PPV)?0*(\d+)", str(folded or ""))
    if m_fc2:
        return ("FC2", int(m_fc2.group(1)), "")
    m = re.fullmatch(r"([A-Z]+)0*(\d+)([A-Z]?)", str(folded or ""))
    if not m:
        return None
    return (m.group(1), int(m.group(2)), m.group(3))


def code_equiv(a: str, b: str) -> bool:
    """番号等价判定：忽略分隔符/大小写，并容忍数字段**前导零补齐差异**。

    例：`NAMH-0028` ≡ `NAMH-028`；`ABC-001` ≡ `ABC-1`；
    ``FC2-976194`` ≡ ``FC2-PPV-976194``；
    素人板号 ``259LUXU-001`` ≡ ``LUXU-001``（``parse_maker_code`` 剥板号后同键）。
    欧美 ``BLACKED.2026.01.15`` ≡ ``BLACKED.26.01.15``（YYYY ↔ YY）。
    仅在「字母前缀 + 数字 + 可选尾字母」结构相同时才放宽，避免 `ABF0051`
    被当成 `ABF-005`（数字续写是另一个番号，仍判不等）。
    国产保留数字前缀的前缀（如 ``91CM``）不会误剥成 ``CM``。
    """
    fa, fb = fold_code(a), fold_code(b)
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    # 显式 FC2 ↔ FC2-PPV（fold 后 FC2PPV976194 vs FC2976194）
    pa, pb = parse_fc2_id(a), parse_fc2_id(b)
    if pa and pb and pa[0].lstrip("0") == pb[0].lstrip("0"):
        return True
    # 欧美点分日：YYYY ↔ YY（不要求厂牌白名单）
    wa, wb = _western_date_fold_key(a), _western_date_fold_key(b)
    if wa and wb and wa == wb:
        return True
    # 素人数字板号 / pad：259LUXU-001 ≡ LUXU-001；SONE-15 ≡ SONE-015
    try:
        from app.search.av import parse_maker_code, std_code_key

        ma, mb = parse_maker_code(a), parse_maker_code(b)
        if (
            ma
            and mb
            and ma.shape == "std"
            and mb.shape == "std"
            and ma.canonical
            and mb.canonical
            and std_code_key(ma.canonical, pad=3) == std_code_key(mb.canonical, pad=3)
        ):
            return True
        if (
            ma
            and mb
            and ma.shape == "western_date"
            and mb.shape == "western_date"
            and ma.canonical
            and mb.canonical
            and ma.canonical == mb.canonical
        ):
            return True
    except Exception:
        pass
    ba, bb = _code_bucket(fa), _code_bucket(fb)
    if ba is None or bb is None:
        return False
    if ba != bb:
        return False
    # 国产厂牌：数字段前导零常有语义（MDX-0001 ≠ 日系 MDX-001），禁止剥零桶判等。
    # fold 已不等时走到此处；国产只认上文 std_code_key / 全等，不再放行。
    try:
        from app.prefix.ranges import load_china_prefixes
        from app.search.av import parse_maker_code

        china = {str(x).upper() for x in (load_china_prefixes() or set())}
        ma, mb = parse_maker_code(a), parse_maker_code(b)
        for parsed in (ma, mb):
            pref = str(getattr(parsed, "prefix", "") or "").upper()
            if pref and pref in china:
                return False
    except Exception:
        pass
    return True


def folded_code_matches(
    candidate: str,
    code: str,
    *,
    mode: str = "endswith",
) -> bool:
    """candidate 为 href / path / 页面番号文本。

    - exact: 折叠后全等（或末段 slug 全等）
    - endswith: 末段 slug 折叠等于番号，或番号后仅为非数字续缀（_CD1 / U）；
      拒绝 ABF0051 这类数字续写误命中
    """
    want = fold_code(code)
    if not want:
        return False
    raw = str(candidate or "").strip()
    if not raw:
        return False

    def _slug_ok(slug: str) -> bool:
        sf = fold_code(slug.split("?")[0].split("#")[0])
        if not sf:
            return False
        if sf == want:
            return True
        if mode == "exact":
            return False
        if not sf.startswith(want):
            return False
        rest = sf[len(want) :]
        # 数字续写 → 另一番号（ABF0051）；下划线/字母后缀可接受
        if rest[:1].isdigit():
            return False
        return True

    if _slug_ok(raw):
        return True
    try:
        path = urlparse(
            raw if "://" in raw else f"http://local{raw if raw.startswith('/') else '/' + raw}"
        ).path
    except Exception:  # noqa: BLE001
        path = raw
    parts = [p for p in str(path or "").split("/") if p]
    if parts and _slug_ok(parts[-1]):
        return True
    # MDCX: .../ABF005_xxx
    hay = fold_code(raw)
    return (want + "_") in hay


def pick_href_by_folded_code(
    candidates: list[str] | tuple[str, ...],
    code: str,
) -> str | None:
    """首个 path 折叠后命中番号的 href；无命中则 None（禁止 first-hit 兜底）。"""
    for href in candidates:
        h = str(href or "").strip()
        if not h:
            continue
        if folded_code_matches(h, code, mode="endswith"):
            return h
    return None


def page_mentions_code(html: str, code: str) -> bool:
    want = fold_code(code) or code_key(code)
    if not want:
        return False
    # 边界：避免 ABF005 ⊂ ABF0051；用非字母数字包围
    hay = fold_code(html)
    if want not in hay:
        return False
    for m in re.finditer(re.escape(want), hay):
        left = hay[m.start() - 1] if m.start() > 0 else ""
        right = hay[m.end()] if m.end() < len(hay) else ""
        if left.isalnum() or right.isdigit():
            continue
        return True
    return False


def std_code(raw: str) -> str:
    s = str(raw or "").strip().upper().replace("_", "-")
    if not s:
        return ""
    if "-" not in s:
        m = re.match(r"^([A-Z]{1,12})(\d{2,}[A-Z0-9-]*)$", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
    return s


def with_https(url: str) -> str:
    """补全协议头（``//`` 开头补 https），并把 JSON 里的 ``\\/`` 还原为 ``/``。"""
    s = str(url or "").strip().replace("\\/", "/")
    if not s:
        return ""
    if s.startswith("//"):
        return f"https:{s}"
    return s


def build_fanza_trailer(sample: str) -> str:
    """把 FANZA 的 hls 预览地址转成可直接播放的 mp4 预览。

    ``dmm`` 与 ``freejavbt`` 曾各写一份逐字节相同的实现，此处收敛为唯一版本。
    """
    raw = with_https(sample)
    if not raw:
        return ""
    if re.search(r"\.mp4(?:[?#].*)?$", raw, re.I):
        return raw
    trailer = re.sub(r"hlsvideo", "litevideo", raw, flags=re.I)
    if re.search(r"/pv/", trailer, re.I) and re.search(r"playlist\.m3u8", trailer, re.I):
        return ""
    m = re.search(r"/([^/]+)/playlist\.m3u8", trailer, re.I)
    if m:
        return re.sub(r"playlist\.m3u8", f"{m.group(1)}_sm_w.mp4", trailer, flags=re.I)
    return ""


def abs_url(href: str | None, base: str) -> str | None:
    u = str(href or "").strip()
    if not u:
        return None
    if u.startswith(("http://", "https://")):
        return u
    if u.startswith("//"):
        return f"https:{u}"
    try:
        root = base if base.endswith("/") else base + "/"
        return urljoin(root, u)
    except Exception:
        b = base.rstrip("/")
        return f"{b}{u if u.startswith('/') else '/' + u}"


def clean_title(raw: str, code: str) -> str:
    t = strip_tags(raw)
    if code:
        t = re.sub(rf"\b{re.escape(code)}\b", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def is_junk_title(s: str) -> bool:
    t = str(s or "").strip()
    if not t or len(t) < 2:
        return True
    return bool(re.match(r"^(undefined|null|n/a|unknown|untitled)$", t, re.I))


def is_junk_cover_url(url: str) -> bool:
    return bool(re.search(r"/(?:logo|icon|avatar|placeholder|1x1|blank)\.", url, re.I))


def collect_by_re(html: str, pattern: str | re.Pattern[str]) -> list[str]:
    out: list[str] = []
    for m in re.finditer(pattern, html or ""):
        if not m.lastindex:
            continue
        val = strip_tags(m.group(1) or "")
        if val and val not in out:
            out.append(val)
    return out


def pick_og_image(html: str) -> str | None:
    m = re.search(
        r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.I,
    ) or re.search(
        r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
        html,
        re.I,
    )
    return m.group(1) if m else None


def pick_og_title(html: str) -> str:
    m = re.search(
        r'property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.I,
    ) or re.search(
        r'content=["\']([^"\']+)["\']\s+property=["\']og:title["\']',
        html,
        re.I,
    )
    return strip_tags(m.group(1)) if m else ""


def soup(html: str) -> BeautifulSoup:
    """解析 HTML —— **同一份 html 在同一线程内只解析一次**。

    ⚠️ 返回的是**共享只读**树：调用方只能查询（select/find/get_text），
    禁止 `decompose()` / `extract()` / `append()` 等变异，否则会污染同一次
    抓取里后续 helper 看到的内容。现有 helper 全部是只读查询。

    不同内容、或不同线程 → 各解析一次，语义与旧实现完全一致。
    """
    s = html or ""
    hit = getattr(_tls, "soup_entry", None)
    if hit is not None and hit[0] is s:
        return hit[1]
    doc = BeautifulSoup(s, "lxml")
    _tls.soup_entry = (s, doc)
    return doc


def make_detail(
    *,
    source: str,
    code: str,
    title: str | None = None,
    poster: str | None = None,
    studio: str | None = None,
    actors: list[str] | None = None,
    tags: list[str] | None = None,
    overview: str | None = None,
    date: str | None = None,
    year: str | None = None,
    extra: dict[str, Any] | None = None,
) -> DetailDict:
    code_s = std_code(code) or str(code or "").strip().upper()
    title_s = clean_title(title or "", code_s) if title else ""
    if is_junk_title(title_s):
        title_s = ""
    poster_s = str(poster or "").strip() or None
    if poster_s and is_junk_cover_url(poster_s):
        poster_s = None
    actors_l = [a for a in (actors or []) if str(a).strip()]
    tags_l = [t for t in (tags or []) if str(t).strip()]
    out: DetailDict = {
        "source": source,
        "provider": source,
        "id": code_s,
        "code": code_s,
        "title": title_s or code_s,
        "posterUrl": poster_s,
        "studio": (studio or "").strip() or None,
        "maker": (studio or "").strip() or None,
        "actors": actors_l[:20],
        "tags": tags_l[:40],
        "overview": (overview or "").strip() or None,
        "date": (date or "").strip()[:10] or None,
        "year": year or year_from(date),
    }
    if extra:
        out.update(extra)
    # directors ↔ director 归一（DMM/avbase 等只给数组，javbus/NFO 读单数字段）
    dir_s = str(out.get("director") or "").strip()
    dirs_raw = out.get("directors")
    dir_names: list[str] = []
    if isinstance(dirs_raw, list):
        for d in dirs_raw:
            if isinstance(d, dict):
                n = str(d.get("name") or "").strip()
            else:
                n = str(d or "").strip()
            if n and n not in dir_names:
                dir_names.append(n)
    if not dir_s and dir_names:
        out["director"] = dir_names[0]
    elif dir_s and not dir_names:
        out["directors"] = [dir_s]
    return out


def _page_fetch(
    url: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    access: str | None = None,
    fast: bool = False,
):
    from app.makers import settings as makers_settings
    from app.core.outbound_http import fetch_page, looks_blocked_html

    sid = source_id
    # 与数据源测链一致：优先调用方传入 / 目录 access，再回退 makers
    mode = str(access or "").strip()
    if not mode:
        try:
            from app.scrape import sources_settings as scrape_src

            if sid:
                mode = scrape_src.catalog_access(sid)
        except Exception:
            mode = ""
    if not mode:
        mode = makers_settings.provider_access(sid) if sid else "proxy_adaptive"
    page = fetch_page(
        url,
        referer=referer,
        cookie=cookie or None,
        access=mode,
        timeout=12.0 if fast else 28.0,
        source_id=sid,
    )
    text = page.html or ""
    if len(text) < 200:
        raise RuntimeError("页面过短")
    if looks_blocked_html(text) and len(text) < 12000:
        raise RuntimeError("站点盾拦截")
    return page


def fetch_html(
    url: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    access: str | None = None,
    fast: bool = False,
) -> str:
    """走与数据源测链相同的出站拉页（代理 / access / Cookie）。"""
    return (
        _page_fetch(
            url,
            referer=referer,
            cookie=cookie,
            source_id=source_id,
            access=access,
            fast=fast,
        ).html
        or ""
    )


def fetch_html_result(
    url: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    access: str | None = None,
    fast: bool = False,
) -> tuple[str, str]:
    """返回 (html, final_url)。"""
    page = _page_fetch(
        url,
        referer=referer,
        cookie=cookie,
        source_id=source_id,
        access=access,
        fast=fast,
    )
    return page.html or "", page.final_url or url


def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    referer: str | None = None,
) -> Any:
    import json as _json

    from app.core.outbound_http import (
        api_slot,
        curl_request,
        resolve_scrape_proxy_url,
        thread_request_timeout,
    )

    hdrs = {
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        **(headers or {}),
    }
    if cookie:
        hdrs["Cookie"] = cookie
    if referer:
        hdrs["Referer"] = referer
    elif source_id:
        try:
            site = prepare_provider_site(source_id)
            hdrs.setdefault("Referer", site["baseUrl"].rstrip("/") + "/")
        except Exception:
            pass
    proxy = resolve_scrape_proxy_url()
    # 请求超时跟随线程本地「单源预算」：原来硬编码 28s，而 `enrich._one` 按策略
    # 的 perSourceTimeoutSec 判 down（默认 28、过盾 18）→ 预算更小时请求还在跑，
    # 变成没人收的僵尸线程。取两者较小值即「源侧不许比我们的预算更久」。
    budget = thread_request_timeout()
    to = 28.0 if not budget or float(budget) <= 0 else min(28.0, float(budget))
    # 第十一轮：走 kind="api" 出站通道（有界并发 + 等槽记账 + 早停令牌）
    with api_slot(url, timeout=to):
        r = curl_request(
            "GET",
            url,
            headers=hdrs,
            timeout=to,
            verify=False,
            proxy=proxy,
            use_panel_proxy=True,
        )
    text = (getattr(r, "text", None) or "").strip()
    if not text:
        raise RuntimeError("empty json")
    return _json.loads(text)


def fetch_post_form(
    url: str,
    body: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    source_id: str | None = None,
    timeout: float = 20.0,
) -> str:
    """对齐 MDCS fetchPostForm：面板代理 + Cookie（不支持强制 Flare）。

    第十一轮：整段尝试走 `kind="api"` 出站通道（有界并发 + 等槽记账 +
    早停令牌），请求超时跟随线程本地单源预算。
    """
    from app.core.outbound_http import (
        api_slot,
        looks_blocked_html,
        resolve_scrape_proxy_url,
        thread_request_timeout,
    )

    access = ""
    if source_id:
        try:
            from app.scrape import sources_settings as scrape_src

            access = scrape_src.catalog_access(source_id)
        except Exception:
            access = ""
    if access == "proxy_flare":
        raise RuntimeError("fetchPostForm 不支持 proxy_flare")

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    }
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie

    proxy = resolve_scrape_proxy_url()
    budget = thread_request_timeout()
    to = float(timeout)
    if budget and float(budget) > 0:
        to = min(to, float(budget))
    with api_slot(url, timeout=to):
        try:
            from curl_cffi import requests as creq

            kwargs: dict[str, Any] = {
                "headers": headers,
                "data": body,
                "timeout": to,
                "allow_redirects": True,
                "verify": False,
                "impersonate": "chrome124",
            }
            if proxy:
                kwargs["proxy"] = proxy
            r = creq.post(url, **kwargs)
            text = str(getattr(r, "text", "") or "")
            if int(getattr(r, "status_code", 500) or 500) < 400 and len(text) > 200:
                if not looks_blocked_html(text):
                    return text
        except Exception:
            pass

        try:
            import httpx

            opts: dict[str, Any] = {
                "timeout": to,
                "follow_redirects": True,
                "verify": False,
                "trust_env": False,
            }
            if proxy:
                opts["proxy"] = proxy
            with httpx.Client(**opts) as client:
                r2 = client.post(url, content=body, headers=headers)
            text = r2.text or ""
            if r2.status_code < 400 and len(text) > 200 and not looks_blocked_html(text):
                return text
        except Exception:
            pass

    raise RuntimeError(f"HTTP POST 失败 {url}")


_last_provider_hit: dict[str, float] = {}


def respect_provider_cooldown(source_id: str, cooldown_sec: float = 0) -> None:
    """对齐 MDCS respectProviderCooldown。"""
    import time

    sid = str(source_id or "").strip().lower()
    sec = float(cooldown_sec or 0)
    if not sid or sec <= 0:
        return
    last = _last_provider_hit.get(sid) or 0.0
    wait = last + sec - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_provider_hit[sid] = time.time()


def prepare_provider_site(
    source_id: str, *, fallback_base: str = ""
) -> dict[str, Any]:
    """对齐 MDCS prepareProviderFetch：baseUrl / cookie / access / 冷却。"""
    from app.scrape import source_catalog as catalog
    from app.scrape import sources_settings as scrape_src

    sid = catalog.canonicalize_id(source_id)
    meta = catalog.catalog_by_id().get(sid) or {}
    cooldown = float(meta.get("defaultCooldownSec") or 0)
    try:
        cfg = scrape_src.provider_settings(sid)
        if cfg.get("cooldownSec") is not None:
            cooldown = float(cfg.get("cooldownSec") or cooldown)
    except Exception:
        pass
    respect_provider_cooldown(sid, cooldown)

    try:
        ctx = scrape_src.resolve_fetch_context(sid)
        return {
            "id": sid,
            "baseUrl": str(ctx.get("baseUrl") or fallback_base or "").rstrip("/"),
            "cookie": str(ctx.get("cookie") or ""),
            "apiKey": str(ctx.get("apiKey") or ""),
            "access": str(ctx.get("access") or "proxy_adaptive"),
            "label": str(ctx.get("label") or sid),
        }
    except Exception:
        base = (
            scrape_src.effective_display_url(sid)
            or str(fallback_base or meta.get("defaultUrl") or "")
        ).rstrip("/")
        cfg = scrape_src.provider_settings(sid)
        return {
            "id": sid,
            "baseUrl": base,
            "cookie": str(cfg.get("cookie") or meta.get("defaultCookie") or ""),
            "apiKey": str(cfg.get("apiKey") or ""),
            "access": scrape_src.catalog_access(sid),
            "label": str(meta.get("label") or sid),
        }


def origin_of(base: str) -> str:
    try:
        u = urlparse(base)
        if u.scheme and u.netloc:
            return f"{u.scheme}://{u.netloc}"
    except Exception:
        pass
    return str(base or "").rstrip("/")


# ---------------------------------------------------------------------------
# 无码官网详情族 —— 共享契约
# ---------------------------------------------------------------------------
# 这一族曾经由「逐字复制的 scrape_detail」组成，两个子群：
#   · JSON 接口群：tenmusume(10musume) / onespondo(1pondo) / pacopacomama
#     —— 三站同走 `dyn/phpauto/movie_details`，字段完全一致。
#   · 官网 HTML 群：heydouga / heyzo / kin8 / nyoshin / tokyohot
#     —— 各自选择器不同，但「抓取 + 未找到判定」完全一致。
#
# 「目录 base 误配就回落官网」「空结果判未找到」「番号前缀归一」这些契约只要有
# 一处被单独修改就会静默漂移（一个源判未找到、别的源不判），因此在这里收敛成
# 唯一实现；各源只声明自己的差异。

_JSON_API_PATH = "/dyn/phpauto/movie_details/movie_id/{key}.json"


def as_str_list(val: Any) -> list[str]:
    """JSON 字段 → 去空白字符串列表（标量包成单元素表，空值给空表）。"""
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x or "").strip()]
    s = str(val or "").strip()
    return [s] if s else []


def official_base(
    base_url: str,
    default_base: str,
    *,
    require_domains: tuple[str, ...] = (),
) -> str:
    """目录里配的 base 若指向别的站，回落官网。

    `require_domains` 为空表示不做守卫（10musume）；否则任一词命中即认可
    （tokyohot 需要 `tokyo-hot` / `tokyohot` 两个写法）。
    """
    base = (base_url or default_base).rstrip("/") or default_base
    if require_domains and not any(d in base.lower() for d in require_domains):
        return default_base
    return base


def official_code(
    code: str,
    *,
    prefix: str,
    fallback: str,
    underscore_to_dash: bool = False,
) -> str:
    """番号归一：调用方番号带不上本站前缀时用 `fallback` 兜底。

    `code` 一律先 upper —— 原实现里 `re.match(r"^X", s, re.I)` 与
    `s.startswith("X")` 在大写串上等价，故这里只保留 `startswith`。
    """
    s = str(code or "").strip().upper()
    if underscore_to_dash:
        s = s.replace("_", "-")
    return s if s and s.startswith(prefix.upper()) else fallback


def fetch_official_html(
    url: str,
    *,
    base: str,
    source_id: str,
    cookie: str | None = None,
    min_len: int = 4000,
    must_contain: tuple[str, ...] = (),
    check_404_title: bool = True,
    age_gate: tuple[str, str] | None = None,
) -> str:
    """官网详情页统一抓取 + 统一的「未找到」判定（顺序与原实现逐字一致）。

    ① 抓取异常 → ``请求失败: …``
    ② 空 / 短于 `min_len` → 未找到
    ③ `check_404_title` 且命中 ``<title>404`` → 未找到
    ④ `age_gate=(门词, 页面标记)`：门词出现在前 4000 字符、且页面不含该标记
       → 未找到（tokyohot 的年龄确认页）
    ⑤ `must_contain` 非空且一个标记都没出现 → 未找到
    """
    try:
        html = fetch_html(url, referer=f"{base}/", cookie=cookie, source_id=source_id)
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e
    if not html or len(html) < min_len:
        raise RuntimeError("未找到")
    if check_404_title and re.search(r"<title[^>]*>\s*404\b", html, re.I):
        raise RuntimeError("未找到")
    if age_gate and age_gate[0] in html[:4000] and age_gate[1] not in html:
        raise RuntimeError("未找到")
    if must_contain and not any(m in html for m in must_contain):
        raise RuntimeError("未找到")
    return html


def scrape_official_json_detail(
    code: str,
    *,
    source: str,
    movie_key: str,
    default_base: str,
    studio: str,
    detail_path: str,
    cover_path: str,
    code_prefix: str,
    base_url: str = "",
    cookie: str = "",
    require_domains: tuple[str, ...] = (),
    year_from_premiered: bool = False,
    with_title_en: bool = False,
    with_rating: bool = False,
) -> DetailDict:
    """10musume / 1pondo / pacopacomama 共用的官网 JSON 详情实现。

    三站 `dyn/phpauto/movie_details` 字段一致，差异只有：域名守卫词、
    详情页 / 封面兜底路径模板（含 ``{key}``）、番号前缀，以及三个开关：

    - `year_from_premiered`：`Year` 缺失时回落 `Release` 前 4 位（1pondo / paco）
    - `with_title_en`：extra 带 `titleEn`（10musume）
    - `with_rating`：解析 `AvgRating` 写评分（10musume）
    """
    base = official_base(base_url, default_base, require_domains=require_domains)
    api_url = f"{base}{_JSON_API_PATH.format(key=movie_key)}"
    detail_url = f"{base}{detail_path.format(key=movie_key)}"

    try:
        data = fetch_json(
            api_url, cookie=cookie or None, source_id=source, referer=f"{base}/"
        )
    except Exception as e:
        raise RuntimeError(f"请求失败: {e}") from e
    if not isinstance(data, dict) or not data:
        raise RuntimeError("未找到")

    movie_id = str(data.get("MovieID") or "").strip().replace("-", "_")
    if movie_id and movie_id != movie_key:
        raise RuntimeError("未找到")

    title = str(data.get("Title") or data.get("TitleEn") or "").strip()
    if is_junk_title(title):
        title = ""
    actors = as_str_list(data.get("ActressesJa")) or as_str_list(data.get("Actor"))
    if not actors:
        actors = as_str_list(data.get("ActressesEn"))
    tags = as_str_list(data.get("UCNAME")) or as_str_list(data.get("UCNAMEEn"))
    overview = str(data.get("Desc") or data.get("DescEn") or "").strip()
    premiered = str(data.get("Release") or "").strip()[:10] or None
    year = str(data.get("Year") or "").strip() or None
    if not year and year_from_premiered and premiered:
        year = premiered[:4]
    series = str(data.get("Series") or data.get("SeriesEn") or "").strip()

    runtime: int | None = None
    try:
        sec = float(data.get("Duration") or 0)
        if sec > 0:
            runtime = max(1, round(sec / 60))
    except (TypeError, ValueError):
        runtime = None

    cover = (
        str(
            data.get("ThumbHigh")
            or data.get("ThumbUltra")
            or data.get("ThumbMed")
            or ""
        ).strip()
        or None
    )
    if cover and is_junk_cover_url(cover):
        cover = None
    if not cover:
        cover = f"{base}{cover_path.format(key=movie_key)}"

    gallery = as_str_list(data.get("Gallery"))
    extras = [u for u in gallery if u.startswith(("http://", "https://"))][:30]
    if not title and not cover and not actors:
        raise RuntimeError("未找到")

    code_u = official_code(
        code,
        prefix=code_prefix,
        fallback=f"{code_prefix}-{movie_key.replace('_', '-')}",
    )

    extra: dict[str, Any] = {
        "series": series or None,
        "website": detail_url,
        "mosaic": "无码",
        "runtime": runtime,
        "extrafanartUrls": extras or None,
        "originalPlot": overview or None,
    }
    if with_title_en:
        extra["titleEn"] = str(data.get("TitleEn") or "").strip() or None
    if with_rating:
        try:
            rating = float(data.get("AvgRating") or 0)
            if 0 < rating <= 5:
                extra.update(
                    {
                        "ratingValue": rating,
                        "ratingMax": 5,
                        "ratingSource": source,
                        "score": rating,
                    }
                )
        except (TypeError, ValueError):
            pass

    return make_detail(
        source=source,
        code=code_u,
        title=title or None,
        poster=cover,
        studio=studio,
        actors=actors,
        tags=tags,
        overview=overview or None,
        date=premiered,
        year=year,
        extra=extra,
    )
