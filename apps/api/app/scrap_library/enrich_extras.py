# -*- coding: utf-8 -*-
"""刮削合并后处理：I41–I52 择优逻辑（标题剥尾、facet、卖家、次要字段）。"""

from __future__ import annotations

import re
from typing import Any

# 从 tags 抽出、不进 genre 的信号
_BADGE_TAG_MAP: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(中文字幕|中字|字幕|chinese\s*subtitle|cn\s*sub)$", re.I), "cnsub"),
    (re.compile(r"^(無碼流出|无码流出|流出|leak)$", re.I), "leak"),
    (re.compile(r"^(破解|破解版|uncensored\s*crack)$", re.I), "crack"),
    (re.compile(r"^(無碼|无码|uncensored)$", re.I), "uncensored"),
    (re.compile(r"^(有碼|有码|censored)$", re.I), "censored"),
    (re.compile(r"^(4k|uhd|2160p|8k)$", re.I), "hd"),
    (re.compile(r"^(1080p|720p|高清|hd)$", re.I), "hd"),
]

_DEF_PAT = re.compile(r"\b(8k|4k|uhd|2160p|1080p|720p)\b", re.I)
_CN_SUB_TITLE = re.compile(r"(中文字幕|中字|[-_\s]C\b)", re.I)
_LEAK_TITLE = re.compile(r"(流出|破解)", re.I)


def apply_field_language(merged: dict[str, Any], *, field_language: dict[str, str]) -> None:
    """I41：按策略调整定稿 title/overview 与 Ja 对照。"""
    title_pref = str((field_language or {}).get("title") or "prefer_zh").strip().lower()
    ov_pref = str((field_language or {}).get("overview") or "prefer_zh").strip().lower()

    if title_pref == "prefer_ja":
        ja = str(merged.get("titleJa") or "").strip()
        zh = str(merged.get("title") or "").strip()
        if ja:
            if zh and zh != ja and not _looks_ja(zh):
                merged["titleZh"] = zh
            merged["title"] = ja
    # prefer_zh / zh_or_translate：现有中文池逻辑已处理；zh_or_translate 留给 LLM 门禁

    if ov_pref == "prefer_ja":
        ja = str(merged.get("overviewJa") or "").strip()
        zh = str(merged.get("overview") or "").strip()
        if ja:
            if zh and zh != ja and not _looks_ja(zh):
                merged["overviewZh"] = zh
            merged["overview"] = ja


def _looks_ja(text: str) -> bool:
    t = str(text or "")
    return bool(re.search(r"[\u3040-\u30ff]", t))


def strip_title_actor_suffix(title: str, actors: list[str]) -> str:
    """I43：剥标题尾演员名（定稿后可选）。"""
    t = str(title or "").strip()
    if not t or not actors:
        return t
    names = sorted({str(a).strip() for a in actors if str(a).strip()}, key=len, reverse=True)
    for name in names:
        if len(name) < 2:
            continue
        # 尾部空格/全角空格 + 名
        for sep in (" ", "　", " - ", "-"):
            suffix = f"{sep}{name}"
            if t.endswith(suffix):
                t = t[: -len(suffix)].rstrip(" -　")
                break
        if t.endswith(name) and len(t) > len(name) + 2:
            # 仅当名前有分隔痕迹
            prev = t[: -len(name)]
            if prev.endswith((" ", "　", "-", "—", "·")):
                t = prev.rstrip(" -—·　")
    return t.strip() or str(title or "").strip()


def strip_title_code_prefix(title: str, code: str) -> str:
    """I43：剥标题番号前缀。"""
    t = str(title or "").strip()
    c = str(code or "").strip().upper()
    if not t or not c:
        return t
    # ABC-123 / ABC123 开头
    pat = re.compile(
        rf"^\s*{re.escape(c)}\s*[-:：]?\s*",
        re.I,
    )
    out = pat.sub("", t).strip()
    if not out:
        return t
    # 无横杠形态
    compact = c.replace("-", "")
    if compact and compact != c:
        pat2 = re.compile(rf"^\s*{re.escape(compact)}\s*[-:：]?\s*", re.I)
        out2 = pat2.sub("", out).strip()
        if out2:
            out = out2
    return out or t


def extract_facets_and_badges(
    *,
    tags: list[str],
    title: str = "",
    region: str = "",
) -> tuple[list[str], list[str], dict[str, Any]]:
    """I47/I50：从标签/标题抽出 badge 与 facet，返回 (clean_tags, badges, facets)。"""
    badges: list[str] = []
    seen_b: set[str] = set()
    clean: list[str] = []
    facets: dict[str, Any] = {
        "cnsub": False,
        "definition": "",
        "mosaic": "",
    }

    def _add_badge(b: str) -> None:
        if b and b not in seen_b:
            seen_b.add(b)
            badges.append(b)

    for raw in tags or []:
        t = str(raw or "").strip()
        if not t:
            continue
        hit = False
        for pat, badge in _BADGE_TAG_MAP:
            if pat.match(t):
                _add_badge(badge)
                if badge == "cnsub":
                    facets["cnsub"] = True
                if badge == "hd" and not facets["definition"]:
                    m = _DEF_PAT.search(t)
                    facets["definition"] = (m.group(1).upper() if m else "HD")
                if badge in {"uncensored", "censored", "leak", "crack"}:
                    facets["mosaic"] = badge
                hit = True
                break
        if not hit:
            clean.append(t)

    hay = str(title or "")
    if _CN_SUB_TITLE.search(hay):
        facets["cnsub"] = True
        _add_badge("cnsub")
    if _LEAK_TITLE.search(hay):
        _add_badge("leak")
    m = _DEF_PAT.search(hay)
    if m and not facets["definition"]:
        facets["definition"] = m.group(1).upper()
        _add_badge("hd")

    rid = str(region or "").strip().lower()
    if rid == "japan_uncensored" and "uncensored" not in seen_b:
        _add_badge("uncensored")
        facets["mosaic"] = facets["mosaic"] or "uncensored"
    if rid == "japan_censored" and "censored" not in seen_b and not facets["mosaic"]:
        facets["mosaic"] = "censored"

    return clean, badges, facets


def pick_fc2_seller(details: list[tuple[str, dict[str, Any]]]) -> str:
    """I44：从源详情里取 FC2 卖家。"""
    for _sid, d in details:
        for key in ("seller", "maker", "studio", "publisher"):
            v = str(d.get(key) or "").strip()
            if v and not v.upper().startswith("FC2"):
                return v
        # actors 里偶发只有卖家一人且像店铺名
        acts = d.get("actors") or []
        if isinstance(acts, list) and len(acts) == 1:
            a = str(acts[0] or "").strip()
            if a and ("販売" in a or "seller" in a.lower() or len(a) <= 24):
                return a
    return ""


def pick_secondary_fields(
    details: list[tuple[str, dict[str, Any]]],
) -> dict[str, str]:
    """次要字段：director / runtime / score / series / publisher / trailer / website。

    跨源「缺则补」：主源没有时，后面源有就取。不阻断主流程。
    """
    out: dict[str, str] = {}

    def _need(key: str) -> bool:
        return not str(out.get(key) or "").strip()

    def _put(key: str, value: str) -> None:
        v = str(value or "").strip()
        if v and _need(key):
            out[key] = v

    for _sid, d in details:
        if not isinstance(d, dict):
            continue
        if _need("director"):
            director = str(d.get("director") or "").strip()
            if not director:
                for x in d.get("directors") or []:
                    if isinstance(x, dict):
                        director = str(x.get("name") or "").strip()
                    else:
                        director = str(x or "").strip()
                    if director:
                        break
            _put("director", director)
        if _need("runtime"):
            rt = d.get("runtime") or d.get("duration") or d.get("length")
            if rt is not None and str(rt).strip():
                s = str(rt).strip()
                m = re.search(r"(\d{2,4})", s)
                _put("runtime", m.group(1) if m else s[:16])
        if _need("score"):
            sc = d.get("score") or d.get("rating") or d.get("ratingValue")
            if sc is not None and str(sc).strip():
                try:
                    f = float(str(sc).strip())
                    if 0 < f <= 10:
                        _put("score", f"{f:.2f}".rstrip("0").rstrip("."))
                except ValueError:
                    pass
        if _need("series"):
            series = str(d.get("series") or d.get("set") or "").strip()
            # 拒掉纯占位
            if series and series not in {"-", "—", "N/A", "n/a"}:
                _put("series", series)
        if _need("publisher"):
            pub = str(d.get("publisher") or d.get("label") or "").strip()
            if pub:
                _put("publisher", pub)
        if _need("label"):
            lab = str(d.get("label") or d.get("publisher") or "").strip()
            if lab:
                _put("label", lab)
        if _need("trailer"):
            trail = str(
                d.get("trailer") or d.get("trailerUrl") or d.get("preview") or ""
            ).strip()
            if trail.startswith(("http://", "https://")):
                _put("trailer", trail)
        if _need("website"):
            web = str(
                d.get("website") or d.get("url") or d.get("pageUrl") or ""
            ).strip()
            if web.startswith(("http://", "https://")):
                _put("website", web)
        # 系列/发行/官网齐了就可提前结束扫源；预告可选
        if (
            not _need("director")
            and not _need("runtime")
            and not _need("score")
            and not _need("series")
            and not _need("publisher")
            and not _need("website")
        ):
            break
    # label 与 publisher 互相同步
    if out.get("publisher") and not out.get("label"):
        out["label"] = out["publisher"]
    if out.get("label") and not out.get("publisher"):
        out["publisher"] = out["label"]
    return out


def collect_actors_all(
    actor_lists: list[tuple[str, list[str], int]],
    *,
    limit: int = 24,
) -> list[str]:
    """I42：全源女优并集（展示名去重）。"""
    out: list[str] = []
    seen: set[str] = set()
    for _sid, names, _sc in actor_lists:
        for raw in names or []:
            a = str(raw or "").strip()
            if not a:
                continue
            key = a.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(a)
            if len(out) >= limit:
                return out
    return out


def apply_merge_extras(
    merged: dict[str, Any],
    *,
    details: list[tuple[str, dict[str, Any]]],
    actor_lists: list[tuple[str, list[str], int]],
    strategy: dict[str, Any] | None = None,
    region: str = "",
) -> dict[str, Any]:
    """在 `_merge_got` 末尾调用：语言偏好、剥标题、actorsAll、FC2、facet、次要字段。"""
    try:
        from app.scrap_library.enrich_strategy import get_strategy

        st = strategy if isinstance(strategy, dict) else get_strategy()
    except Exception:  # noqa: BLE001
        st = strategy if isinstance(strategy, dict) else {}

    code = str(merged.get("code") or "").strip().upper()
    rid = str(region or "").strip()
    if not rid and code.startswith("FC2"):
        rid = "fc2"

    # I42
    try:
        all_actors = collect_actors_all(actor_lists)
        if all_actors:
            merged["actorsAll"] = all_actors
    except Exception:  # noqa: BLE001
        pass

    # I44 FC2 卖家
    acts = [str(a).strip() for a in (merged.get("actors") or []) if str(a).strip()]
    if (rid == "fc2" or code.startswith("FC2")) and not acts:
        seller = pick_fc2_seller(details)
        if seller:
            merged["seller"] = seller
            if bool(st.get("fc2SellerAsActor", True)):
                merged["actors"] = [seller]
                merged["actorRole"] = "seller"
                acts = [seller]

    # I52：director/runtime/score + 系列/发行/预告/官网（主源缺则后源补）
    sec = pick_secondary_fields(details)
    for k, v in sec.items():
        if v and not merged.get(k):
            merged[k] = v
    # rating 别名：NFO 写 score；保留两者
    if merged.get("score") and not merged.get("rating"):
        merged["rating"] = merged["score"]

    # I47 / I50：从 tags 抽 badge/facet
    tags = list(merged.get("tags") or [])
    clean, badges, facets = extract_facets_and_badges(
        tags=tags,
        title=str(merged.get("title") or ""),
        region=rid,
    )
    merged["tags"] = clean
    if badges:
        merged["badges"] = badges
    for fk, fv in facets.items():
        if fv:
            merged[fk] = fv

    # I41 语言偏好（在 titleJa/overviewJa 齐备后）
    apply_field_language(
        merged,
        field_language=dict(st.get("fieldLanguage") or {}),
    )

    # I43 定稿后剥标题（两阶段：尾名补演员已完成）
    title = str(merged.get("title") or "").strip()
    if title:
        strip_actors = list(acts) + list(merged.get("actorsAll") or [])
        if bool(st.get("stripTitleActorSuffix")):
            title = strip_title_actor_suffix(title, strip_actors)
        if bool(st.get("stripTitleCodePrefix")):
            title = strip_title_code_prefix(title, code)
        merged["title"] = title

    # I48 偏好仅写入策略字段供前端；合并结果带 outlineShow 方便详情
    show = str(st.get("outlineShow") or "zh").strip().lower()
    if show in ("zh", "zh_jp", "jp_zh"):
        merged["outlineShow"] = show

    return merged


def compress_avatar_bytes(data: bytes, *, max_edge: int = 512, jpeg_q: int = 80) -> bytes:
    """I51：头像落盘前压缩。"""
    if not data or len(data) < 32:
        return data
    try:
        import io

        from PIL import Image, ImageOps

        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        elif im.mode == "L":
            im = im.convert("RGB")
        if im.width > max_edge or im.height > max_edge:
            im = im.copy()
            im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=jpeg_q, optimize=True, subsampling=2)
        out = buf.getvalue()
        return out if out else data
    except Exception:  # noqa: BLE001
        return data
