"""Pack-bleed / multi-resource alignment — port of sehua-search utils/resource.ts.

Smoke (manual)::

    from app.pack_bleed import format_size_gb, is_pack_bleed_item, links_for_resource_hash
    from app.resource_format import format_resource

    h1 = "A" * 32
    h2 = "B" * 32
    links = [
        f"ed2k://|file|JUR-024.mp4|1073741824|{h1}|/",
        f"ed2k://|file|IPZZ-001.mp4|2147483648|{h2}|/",
    ]
    row = {
        "hash": h1,
        "filename": "JUR-024.mp4",
        "size": 1073741824,
        "ed2k_link": links[0],
        "ed2k_links": links,
        "title": "BT种子合集 打包",
        "description": "【资源名称】：IPZZ-001\\n【出演女优】：foo",
        "preview_images": [
            "https://jp.netcdn.space/digital/video/ipzz001/ipzz001pl.jpg",
            "https://jp.netcdn.space/digital/video/jur00024/jur00024pl.jpg",
        ],
        "created_at": 0,
        "updated_at": 0,
    }
    assert is_pack_bleed_item(
        row["title"], row["filename"], row["description"], row["hash"],
        row["ed2k_link"], row["ed2k_links"],
    )
    out = format_resource(row)
    assert len(out["ed2k_links"]) == 1 and h1.lower() in out["ed2k_links"][0].lower()
    assert out["title"] == "JUR-024.mp4"
    assert all("jur" in u.lower() for u in out["preview_images"])
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from .search_av import normalize_maker_code, parse_maker_code

MAX_PREVIEW_IMAGES = 5

ED2K_LINK_RE = re.compile(
    r"ed2k://\|file\|([^|]+)\|(\d+)\|([A-Fa-f0-9]{32})\|",
    re.I,
)
MAGNET_HASH_RE = re.compile(
    r"magnet:\?xt=urn:btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})",
    re.I,
)

IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|gif|webp|bmp)(\?|#|$)", re.I)

INVALID_IMAGE_MARKERS = (
    "filetype",
    "hrline",
    "smiley",
    "/static/image/common/",
    "static/image/",
    "avatar",
    "attachment/common/",
    "usergroup_icon",
    "groupicon",
    "favicon",
)

FORUM_COVER_HOST_RE = re.compile(
    r"sehuatang\.(net|org)|picdcd\.com|adipcd\.com|pkapic\.cc|imgccc\.com|"
    r"11img\.com|yichkp\.com|ewrewej\.la|ymawv\.la|ldkms\.la|qpic\.ws|"
    r"gdvdvb\.com|img906\.com|microsoftsa\.com|xunse\.pics|023pic3\.cc|"
    r"pic26077\.cc|pic2607a\.cc|pic505hz\.cc|pid505st\.cc",
    re.I,
)

UNRELIABLE_COVER_HOST_RE = re.compile(
    r"dmm\.co\.jp|netcdn\.space|imagetwist\.com|gifyu\.com|imghost\.biz",
    re.I,
)

DISPLAY_DESCRIPTION_LABELS = (
    "资源名称",
    "影片名称",
    "资源大小",
    "出演女优",
    "资源类型",
    "是否有码",
    "有无水印",
    "资源数量",
    "解压密码",
)

DESCRIPTION_LABEL_ALIASES = {
    "有无第三方水印": "有无水印",
    "影片容量": "资源大小",
    "影片大小": "资源大小",
    "文件大小": "资源大小",
    "提取密码": "解压密码",
    "资源密码": "解压密码",
    "资源解压密码": "解压密码",
    "影片名稱": "影片名称",
    "作品名称": "影片名称",
    "作品名稱": "影片名称",
    "片名": "影片名称",
    "資源名稱": "资源名称",
    "资源名": "资源名称",
    "女优名称": "出演女优",
    "女优": "出演女优",
    "女優": "出演女优",
    "女優名": "出演女优",
    "女优名": "出演女优",
    "AV女优": "出演女优",
    "AV女優": "出演女优",
    "演员": "出演女优",
    "主演": "出演女优",
    "演出者": "出演女优",
    "出演者": "出演女优",
    "出演": "出演女优",
    "表演者": "出演女优",
    "艺人": "出演女优",
    "演员姓名": "出演女优",
}


def format_size_gb(size: int | float) -> str:
    """API pack-bleed description size text: ``X.XXGB``."""
    try:
        n = float(size)
    except Exception:
        return ""
    if n <= 0:
        return ""
    return f"{(n / 1024 / 1024 / 1024):.2f}GB"


def is_public_download_link(link: str | None) -> bool:
    lower = (link or "").strip().lower()
    if not lower or lower.startswith("unavailable://"):
        return False
    if lower.startswith("ed2k://") or lower.startswith("magnet:"):
        return True
    return "115cdn.com/s/" in lower or "115.com/s/" in lower


def parse_ed2k_link(link: str) -> dict[str, Any] | None:
    m = ED2K_LINK_RE.search(link or "")
    if not m:
        return None
    name = m.group(1)
    try:
        name = unquote(name)
    except Exception:
        pass
    return {
        "filename": name,
        "size": int(m.group(2)),
        "hash": m.group(3).upper(),
        "link": link,
    }


def parse_magnet_link(link: str) -> dict[str, Any] | None:
    """解析磁力：infohash + 可选 dn（文件名）/ xl（大小）。"""
    raw = (link or "").strip()
    m = MAGNET_HASH_RE.search(raw)
    if not m:
        return None
    info_hash = m.group(1)
    # 40 位 hex 统一大写；32 位 base32 也原样保留供展示
    if len(info_hash) == 40:
        info_hash = info_hash.upper()
    out: dict[str, Any] = {"hash": info_hash, "link": raw}
    try:
        # magnet:?xt=...&dn=...&xl=... （dn 可能 URL 编码）
        q = raw.split("?", 1)[-1] if "?" in raw else ""
        params: dict[str, list[str]] = {}
        for part in q.split("&"):
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            key = unquote(k).lower()
            params.setdefault(key, []).append(v)
        dn_list = params.get("dn") or []
        if dn_list:
            name = unquote(dn_list[0].replace("+", " ")).strip()
            if name:
                out["filename"] = name
        xl_list = params.get("xl") or []
        if xl_list:
            try:
                out["size"] = int(xl_list[0])
            except ValueError:
                pass
    except Exception:
        pass
    return out


def normalize_ed2k_links(
    ed2k_links: Any = None,
    fallback_link: str | None = None,
) -> list[str]:
    if isinstance(ed2k_links, (list, tuple)) and ed2k_links:
        raw = [str(x) for x in ed2k_links if x]
    elif fallback_link:
        raw = [fallback_link]
    else:
        raw = []
    out: list[str] = []
    seen: set[str] = set()
    for link in raw:
        link = str(link).strip()
        if not link or link in seen:
            continue
        if not is_public_download_link(link):
            continue
        seen.add(link)
        out.append(link)
    return out


def link_matches_hash(link: str | None, hash_: str | None) -> bool:
    h = (hash_ or "").strip().upper()
    if not h:
        return True
    raw = (link or "").strip()
    if not raw:
        return False
    ed2k = parse_ed2k_link(raw)
    if ed2k and ed2k.get("hash"):
        return str(ed2k["hash"]).upper() == h
    magnet = parse_magnet_link(raw)
    if magnet and magnet.get("hash"):
        return str(magnet["hash"]).upper() == h
    return True


def links_for_resource_hash(
    hash_: str | None,
    ed2k_links: Any = None,
    fallback_link: str | None = None,
) -> list[str]:
    """Current-hash download links; drop sibling hashes from pack rows."""
    primary = (fallback_link or "").strip()
    from_meta = normalize_ed2k_links(ed2k_links, None)

    out: list[str] = []
    seen: set[str] = set()

    def push(link: str) -> None:
        if not link or link in seen:
            return
        low = link.lower()
        if not (
            is_public_download_link(link) or low.startswith("unavailable://")
        ):
            return
        seen.add(link)
        out.append(link)

    if primary:
        push(primary)
    for link in from_meta:
        push(link)

    if not out and primary:
        return [primary]

    h = (hash_ or "").strip().upper()
    if not h:
        return out

    hashable = [
        link
        for link in out
        if (parse_ed2k_link(link) or {}).get("hash")
        or (parse_magnet_link(link) or {}).get("hash")
    ]
    if not hashable:
        return out

    matched = []
    for link in out:
        ed2k = parse_ed2k_link(link)
        magnet = parse_magnet_link(link)
        if (ed2k and ed2k.get("hash")) or (magnet and magnet.get("hash")):
            if link_matches_hash(link, h):
                matched.append(link)
        # drop non-hashable when hashable siblings exist
    if matched:
        return matched
    return [primary] if primary else []


def distinct_download_hash_count(
    ed2k_links: Any = None,
    fallback_link: str | None = None,
) -> int:
    raw = normalize_ed2k_links(ed2k_links, fallback_link)
    hashes: set[str] = set()
    for link in raw:
        ed2k = parse_ed2k_link(link)
        magnet = parse_magnet_link(link)
        h = None
        if ed2k and ed2k.get("hash"):
            h = str(ed2k["hash"]).upper()
        elif magnet and magnet.get("hash"):
            h = str(magnet["hash"]).upper()
        if h:
            hashes.add(h)
    return len(hashes)


def format_description_lines(description: str | None) -> list[dict[str, str]]:
    text = (description or "").strip()
    if not text:
        return []

    seen: set[str] = set()
    collected: list[dict[str, str]] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        m = re.match(r"^【([^】]+)】(.*)$", line)
        if not m:
            continue
        raw_label = m.group(1).strip()
        if not raw_label:
            continue
        label = DESCRIPTION_LABEL_ALIASES.get(raw_label, raw_label)
        if label in seen:
            continue
        value = re.sub(r"^[:：]+", "", m.group(2).strip())
        if not value:
            continue
        seen.add(label)
        collected.append({"label": label, "value": value})

    if not collected:
        return []

    preferred = {lab: i for i, lab in enumerate(DISPLAY_DESCRIPTION_LABELS)}
    known = [row for row in collected if row["label"] in preferred]
    rest = [row for row in collected if row["label"] not in preferred]
    known.sort(key=lambda r: preferred.get(r["label"], 0))
    return known + rest


def get_description_field(description: str | None, label: str) -> str | None:
    for row in format_description_lines(description):
        if row["label"] == label:
            return row["value"]
    return None


def first_maker_code_in(text: str) -> str | None:
    raw = normalize_maker_code(text or "")
    if not raw:
        return None
    whole = parse_maker_code(raw)
    if whole:
        return whole.canonical
    re_codes = re.compile(
        r"(?:^|[^A-Za-z0-9])([A-Za-z]{2,15}[-_\s]?\d{2,8}|FC2[-_\s]?PPV[-_\s]?\d{5,10})(?![0-9])",
        re.I,
    )
    for m in re_codes.finditer(raw):
        parsed = parse_maker_code(m.group(1))
        if parsed:
            return parsed.canonical
    return None


def resource_names_align(a: str, b: str) -> bool:
    ca = first_maker_code_in(a)
    cb = first_maker_code_in(b)
    if ca and cb:
        return ca == cb
    na = (a or "").strip().lower()
    nb = (b or "").strip().lower()
    if not na or not nb:
        return False
    return na == nb or (nb[:24] in na) or (na[:24] in nb)


def is_pack_style_title(title: str) -> bool:
    return bool(re.search(r"BT种子|合集|黑客最新|\d+\s*部|部1080|打包", title or "", re.I))


def own_maker_codes_for_index_row(
    *,
    prefix: str,
    filename: str | None,
    title: str | None,
    film: str | None = None,
    resource: str | None = None,
    description: str | None = None,
    hash_: str | None = None,
    ed2k_links: Any = None,
    ed2k_link: str | None = None,
) -> tuple[list[str], bool]:
    """索引抽码：合集只认本资源子文件，不把帖题里兄弟番号混进来。

    返回 (codes, is_pack)。
    - 合集：仅 filename + 当前 hash 对应的 ed2k 文件名
    - 非合集：filename / 帖题 / 影片名称 / 资源名称（旧行为）
    """
    from .search_av import extract_maker_codes

    name = str(filename or "").strip()
    post_title = str(title or "").strip()
    film_s = str(film or "").strip()
    resource_s = str(resource or "").strip()
    pack = is_pack_bleed_item(
        post_title,
        name,
        description,
        hash_,
        ed2k_link=ed2k_link,
        ed2k_links=ed2k_links,
    ) or is_pack_style_title(post_title)

    if pack:
        texts: list[str] = []
        if name:
            texts.append(name)
        for link in links_for_resource_hash(hash_, ed2k_links, ed2k_link):
            parsed = parse_ed2k_link(link) or {}
            fn = str(parsed.get("filename") or "").strip()
            if fn:
                texts.append(fn)
        blob = "\n".join(texts)
        codes = extract_maker_codes(blob, prefix) if blob else []
        # 本文件抽不到、且文件名本身无任何番号时：帖题本前缀唯一可认
        if not codes and post_title and not first_maker_code_in(name):
            title_codes = extract_maker_codes(post_title, prefix)
            if len(title_codes) == 1:
                codes = title_codes
        return codes, True

    blob = "\n".join(s for s in (name, post_title, film_s, resource_s) if s)
    if not blob:
        return [], False
    return extract_maker_codes(blob, prefix), False


def is_pack_bleed_item(
    title: str | None,
    name: str | None,
    description: str | None,
    hash_: str | None,
    ed2k_link: str | None = None,
    ed2k_links: Any = None,
) -> bool:
    name_s = (name or "").strip()
    title_s = (title or "").strip()
    from_desc = (
        get_description_field(description, "资源名称")
        or get_description_field(description, "影片名称")
        or ""
    )
    if distinct_download_hash_count(ed2k_links, ed2k_link) > 1:
        return True
    if name_s and from_desc and not resource_names_align(from_desc, name_s):
        return True
    if name_s and is_pack_style_title(title_s) and not resource_names_align(title_s, name_s):
        return True
    return False


def _path_contains_needle(path: str, needle: str) -> bool:
    """路径含番号 cid；排除 1sone00968 误命中 sone00968。"""
    if not needle:
        return False
    pos = 0
    while pos < len(path):
        idx = path.find(needle, pos)
        if idx < 0:
            return False
        if idx > 0 and path[idx - 1].isdigit():
            pos = idx + 1
            continue
        after = idx + len(needle)
        if after < len(path) and path[after].isdigit():
            pos = idx + 1
            continue
        return True
    return False


def image_url_matches_maker_code(url: str, code: str) -> bool:
    raw = str(code or "").strip()
    if not raw or not url:
        return False
    compact = re.sub(r"[-_\s]", "", raw).lower()
    parsed = parse_maker_code(raw)
    prefix = (parsed.prefix if parsed else "").lower()
    num_raw = ""
    if parsed and parsed.parts:
        num_raw = parsed.parts[-1]
    num = re.sub(r"^0+", "", num_raw) or num_raw
    needles = {
        compact,
        raw.lower(),
        raw.replace("-", "").lower(),
    }
    if prefix and num:
        needles.add(f"{prefix}{num}")
        needles.add(f"{prefix}{num.zfill(3)}")
        needles.add(f"{prefix}{num.zfill(5)}")
    path = re.sub(r"[^a-z0-9./_-]", "", url.lower())
    return any(n and _path_contains_needle(path, n) for n in needles)


def guess_netcdn_jacket_urls(code: str) -> list[str]:
    raw = str(code or "").strip().upper()
    if not raw:
        return []
    if re.match(r"^FC2", raw) or re.match(r"^\d+$", raw):
        return []
    m = re.match(r"^([A-Z]{2,15})[-_\s]?(\d{2,5})$", raw)
    if not m:
        return []
    prefix = m.group(1).lower()
    num = re.sub(r"^0+", "", m.group(2)) or "0"
    pad = num.zfill(5)
    cid = f"{prefix}{pad}"
    return [f"https://jp.netcdn.space/digital/video/{cid}/{cid}pl.jpg"]


def is_valid_preview_url(src: str) -> bool:
    lower = (src or "").lower()
    if any(marker in lower for marker in INVALID_IMAGE_MARKERS):
        return False
    if ".txt" in lower:
        return False
    return bool(
        IMAGE_EXT_RE.search(lower)
        or "/tupian/forum/" in lower
        or lower.startswith("/covers/")
    )


def is_jacket_cover_url(url: str) -> bool:
    u = (url or "").lower()
    if u.startswith("/covers/") or "/covers/" in u:
        return True
    if re.search(r"netcdn\.space|pics\.dmm\.co\.jp|\.dmm\.co\.jp", u):
        return True
    if re.search(r"[/_\-]pl\.(jpe?g|png|webp)(\?|#|$)", u):
        return True
    return False


def is_forum_cover_host(url: str) -> bool:
    return bool(FORUM_COVER_HOST_RE.search(url or ""))


def is_unreliable_cover_host(url: str) -> bool:
    return bool(UNRELIABLE_COVER_HOST_RE.search(url or ""))


def filter_preview_images_in_order(
    images: Any = None,
    limit: int = MAX_PREVIEW_IMAGES,
) -> list[str]:
    out: list[str] = []
    for src in images or []:
        s = str(src or "").strip()
        if not s or not is_valid_preview_url(s):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def gallery_preview_images(images: Any = None) -> list[str]:
    """优先片商/论坛图；若全被不稳定图床过滤（写真 OAE 常仅 imghost）则回退原序。"""
    ordered = filter_preview_images_in_order(images, MAX_PREVIEW_IMAGES)
    preferred = [
        u
        for u in ordered
        if is_jacket_cover_url(u)
        or is_forum_cover_host(u)
        or not is_unreliable_cover_host(u)
    ]
    return preferred or ordered


def pick_covers_for_code(
    code: str,
    images: Any = None,
    limit: int = 4,
) -> list[str]:
    imgs = gallery_preview_images(images)[
        : max(limit, MAX_PREVIEW_IMAGES)
    ]
    if not imgs:
        return []
    matched = [u for u in imgs if image_url_matches_maker_code(u, code)]
    if matched:
        return matched[:limit]
    out: list[str] = []
    seen: set[str] = set()
    for u in imgs:
        if not u or u in seen:
            continue
        if is_jacket_cover_url(u) and not image_url_matches_maker_code(u, code):
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= limit:
            return out
    if out:
        return out
    return guess_netcdn_jacket_urls(code)[:limit]


def pick_previews_for_resource(
    hash_: str,
    name: str | None,
    ed2k_links: Any = None,
    fallback_link: str | None = None,
    preview_images: Any = None,
    title: str | None = None,
) -> list[str]:
    imgs = [str(u) for u in (preview_images or []) if u]
    # 写真等：文件名常是艺名（RION），番号在标题里
    code = (
        first_maker_code_in(name or "")
        or first_maker_code_in(title or "")
        or first_maker_code_in(
            "\n".join(
                (parse_ed2k_link(l) or {}).get("filename") or ""
                for l in normalize_ed2k_links(ed2k_links, fallback_link)
            )
        )
    )

    if code and imgs:
        # 优先：URL 明确含当前番号（合集多图时勿把兄弟图混进 by_code）
        matched = [
            u
            for u in gallery_preview_images(imgs)
            if image_url_matches_maker_code(u, code)
        ]
        if matched:
            return matched[:MAX_PREVIEW_IMAGES]
        by_code = pick_covers_for_code(code, imgs, MAX_PREVIEW_IMAGES)
        if by_code:
            return by_code

    raw_links = normalize_ed2k_links(ed2k_links, fallback_link)
    h = str(hash_ or "").strip().upper()
    if h and imgs and raw_links:
        idx = next(
            (i for i, link in enumerate(raw_links) if link_matches_hash(link, h)),
            -1,
        )
        if idx >= 0 and idx < len(imgs) and imgs[idx]:
            return gallery_preview_images([imgs[idx]])

    if code:
        guesses = guess_netcdn_jacket_urls(code)
        if guesses:
            return guesses
    return gallery_preview_images(imgs) if len(imgs) == 1 else []
