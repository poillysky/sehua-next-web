"""Maker-prefix code index — practical port of sehua-search prefixResources."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from . import pg
from .pg import ResourceDbUnavailable
from .resource_format import PUBLIC_RESOURCE_FILTER
from .search_av import (
    code_sort_key,
    is_western_studio_prefix,
    parse_maker_code,
)
from .search_constants import escape_ilike

log = logging.getLogger(__name__)

# 扫库上限：与库内命中对齐的硬顶；构建不得再降（降了会扫漏）
PREFIX_SCAN_ROW_CAP = 20000
# 构建与前台同一上限；速度靠并行 workers，不靠砍行数
PREFIX_SCAN_ROW_CAP_BUILD = PREFIX_SCAN_ROW_CAP
# 前台点进单前缀：20s；一键/全量并行时抬到 BUILD 超时
PREFIX_SCAN_TIMEOUT = "20s"
PREFIX_SCAN_TIMEOUT_BUILD = "90s"
PREFIX_CACHE_TTL_S = 300

_scan_timeout_lock = threading.Lock()
_scan_timeout_override: str | None = None
_scan_row_cap_override: int | None = None


def set_prefix_scan_timeout(timeout: str | None) -> str | None:
    """临时覆盖 statement_timeout（如全量构建）；返回旧值便于还原。"""
    global _scan_timeout_override
    with _scan_timeout_lock:
        prev = _scan_timeout_override
        _scan_timeout_override = (timeout or "").strip() or None
        return prev


def set_prefix_scan_row_cap(cap: int | None) -> int | None:
    """临时覆盖扫库行上限；返回旧值。"""
    global _scan_row_cap_override
    with _scan_timeout_lock:
        prev = _scan_row_cap_override
        if cap is None or int(cap) <= 0:
            _scan_row_cap_override = None
        else:
            _scan_row_cap_override = max(500, min(int(PREFIX_SCAN_ROW_CAP), int(cap)))
        return prev


def _active_scan_timeout() -> str:
    with _scan_timeout_lock:
        return _scan_timeout_override or PREFIX_SCAN_TIMEOUT


def _active_scan_row_cap(*, for_prefix: str | None = None) -> int:
    with _scan_timeout_lock:
        base = int(_scan_row_cap_override or PREFIX_SCAN_ROW_CAP)
    # FC2 体量大且多 pattern 分桶；构建降 cap 会从 ~4800 砍到三千出头
    if for_prefix and _is_fc2_prefix(for_prefix):
        return PREFIX_SCAN_ROW_CAP
    return base
# 每番号保留的帖文上限；满时按中文分替换，避免只留最新日文帖
PREFIX_POSTS_PER_CODE = 24
# 同 hash 多源会放大结果行数；1 足够（ORDER BY 已中文优先）
PREFIX_SOURCES_PER_HASH = 1
# 中文补扫：大区全量重建时额外一枪/前缀仍贵，默认关；需要时再开
PREFIX_ZH_BOOST_ROW_CAP = 3000
PREFIX_ZH_BOOST_ENABLED = False


def _prefix_result_row_cap(for_prefix: str | None = None) -> int:
    """最终行数上限；SOURCES=1 时与 ROW_CAP 相同。"""
    return _active_scan_row_cap(for_prefix=for_prefix) * max(
        1, PREFIX_SOURCES_PER_HASH
    )

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _is_fc2_prefix(prefix: str) -> bool:
    p = str(prefix or "").strip().upper()
    return p in {"FC2", "FC2PPV"}


def prefix_like_patterns(prefix: str) -> list[str]:
    raw = str(prefix or "").strip()
    p_upper = raw.upper()
    if not raw:
        return []
    if p_upper == "FC2PPV":
        return [
            "FC2PPV%",
            "%FC2PPV%",
            "%FC2-PPV%",
            "%FC2 PPV%",
            "FC2-PPV%",
            "FC2 PPV%",
        ]
    if p_upper == "FC2":
        return ["FC2-%", "%FC2-%", "FC2 %", "%FC2 %"]
    esc = escape_ilike(raw)
    if is_western_studio_prefix(raw):
        # 欧美常见 Studio.yy.mm.dd / Studio-yyyy…；短站名禁止裸 %RK%，否则全表扫超时。
        out = [
            f"%{esc}.%",
            f"%{esc}-%",
            f"%{esc}_%",
            f"{esc}.%",
            f"{esc}-%",
            f"{esc}_%",
        ]
        if len(raw) >= 5:
            out.extend([f"%{esc} %", f"{esc} %", f"%{esc}%"])
        return out
    return [f"{esc}-%", f"%{esc}-%"]


def prefix_exclude_like_patterns(prefix: str) -> list[str]:
    p = str(prefix or "").strip().upper()
    if p == "FC2":
        return [
            "%FC2PPV%",
            "FC2PPV%",
            "%FC2-PPV%",
            "FC2-PPV%",
            "%FC2 PPV%",
            "FC2 PPV%",
        ]
    if p == "BLACKED":
        return ["%BlackedRaw%", "%BLACKEDRAW%", "%blackedraw%"]
    return []


def _append_cover_fallbacks(
    prev: list[str], nxt: list[str], *, code: str = ""
) -> list[str]:
    from .pack_bleed import image_url_matches_maker_code, is_jacket_cover_url

    out = list(prev)
    seen = set(out)
    for u in nxt:
        if not u or u in seen:
            continue
        # 合集帖备用图：拒其它番号的 DMM/netcdn 夹克
        if (
            code
            and is_jacket_cover_url(u)
            and not image_url_matches_maker_code(u, code)
        ):
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= 6:
            break
    # 合并后再把脆弱图床沉底，保证 coverUrl 优先稳图
    return _prefer_stable_cover_urls(out)


def _strip_shared_junk_covers(items: list[dict[str, Any]]) -> None:
    url_codes: dict[str, set[str]] = {}
    for it in items:
        for u in it.get("coverUrls") or []:
            if not u:
                continue
            url_codes.setdefault(u, set()).add(it["code"])
    junk = {url for url, codes in url_codes.items() if len(codes) >= 4}
    if not junk:
        return
    for it in items:
        nxt = [u for u in (it.get("coverUrls") or []) if u not in junk]
        if len(nxt) == len(it.get("coverUrls") or []):
            continue
        it["coverUrls"] = nxt[:6]
        it["coverUrl"] = it["coverUrls"][0] if it["coverUrls"] else None


BT_BOARD_ROOT_FID_SET = {
    "2",
    "36",
    "37",
    "38",
    "39",
    "103",
    "104",
    "107",
    "151",
    "152",
    "160",
}


def _is_bt_board_fid(fid: Any) -> bool:
    raw = str(fid or "").strip()
    if not raw:
        return False
    root = raw.split(":", 1)[0]
    return root in BT_BOARD_ROOT_FID_SET


def _created_at_ms(v: Any) -> float:
    if v is None:
        return 0.0
    if hasattr(v, "timestamp"):
        try:
            return float(v.timestamp()) * 1000
        except Exception:
            return 0.0
    try:
        from datetime import datetime

        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000
    except Exception:
        return 0.0
    return 0.0


def _sort_like_search(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """搜索类排序：sehua 主库优先，BT 只作补充。"""
    indexed = list(enumerate(rows))

    def key(pair: tuple[int, dict[str, Any]]) -> tuple[int, float, int]:
        i, row = pair
        non_bt_first = 1 if _is_bt_board_fid(row.get("board_fid")) else 0
        return non_bt_first, -_created_at_ms(row.get("created_at")), i

    indexed.sort(key=key)
    return [row for _, row in indexed]


def _sort_for_prefix_cover(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """本地索引生成：sehua 主库优先，BT 只补空缺；同源内按 created_at 新→旧。"""
    indexed = list(enumerate(rows))
    indexed.sort(
        key=lambda pair: (
            1 if _is_bt_board_fid(pair[1].get("board_fid")) else 0,
            -_created_at_ms(pair[1].get("created_at")),
            pair[0],
        )
    )
    return [row for _, row in indexed]


def _is_gif_url(url: str) -> bool:
    path = str(url or "").lower().split("?", 1)[0]
    return path.endswith(".gif")


# TLS 握手直接断 / 长期不可达的图床：有其它源时不要排第一（避免干等 onError）
_FLAKY_COVER_HOST_RE = re.compile(
    r"xms45\.com|"
    r"imghost\.biz|"
    r"gifyu\.com|"
    r"imagetwist\.com",
    re.I,
)


def _is_flaky_cover_host(url: str) -> bool:
    return bool(_FLAKY_COVER_HOST_RE.search(url or ""))


def _prefer_stable_cover_urls(urls: list[str]) -> list[str]:
    """稳定图床在前，脆弱图床垫后；有稳定源时首张就不会卡 TLS。"""
    good = [u for u in urls if u and not _is_flaky_cover_host(u)]
    flaky = [u for u in urls if u and _is_flaky_cover_host(u)]
    return good + flaky


def _prefix_tile_covers(
    code: str, images: Any, *, pack: bool = False
) -> list[str]:
    """番号格封面：按番号过滤片商夹克（防合集串图），静图优先，脆弱图床后置。"""
    from .pack_bleed import image_url_matches_maker_code, pick_covers_for_code

    ordered = pick_covers_for_code(str(code or ""), images, limit=4)
    if pack:
        # 合集帖预览常混多番号：只留能对上本番号的夹克，避免锁死错图
        matched = [
            u for u in ordered if image_url_matches_maker_code(u, str(code or ""))
        ]
        ordered = matched
    if not ordered:
        return []
    stills = [u for u in ordered if not _is_gif_url(u)]
    pool = stills or ordered
    return _prefer_stable_cover_urls(pool)[:4]


def _has_still_cover(urls: list[str] | None) -> bool:
    return any(u and not _is_gif_url(u) for u in (urls or []))


def _is_japan_censored_style_prefix(prefix: str) -> bool:
    """字母品番前缀（非 FC2 / 欧美站名）按有码原则挑封面。"""
    raw = str(prefix or "").strip()
    if not raw or _is_fc2_prefix(raw) or is_western_studio_prefix(raw):
        return False
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,11}", raw))


def _is_domestic_or_clear_uncensored_row(row: dict[str, Any]) -> bool:
    """有码风格前缀：封面只取日本有码白名单内的帖。"""
    from .region_board_allowlist import board_fid_allowed

    fid = str(row.get("board_fid") or "").strip()
    if not board_fid_allowed(fid, "japan_censored"):
        return True
    return False


def _post_zh_keep_score(desc: str, title: str, *, code: str = "") -> int:
    """收帖优先级（热路径：禁止 clean_forum_zh_title，只用廉价假壳判断）。"""
    from .pack_bleed import get_description_field
    from .scrape_forum_title import is_fake_forum_title_fast

    d = str(desc or "")
    t = str(title or "")
    if not d.strip() and not t.strip():
        return -1

    film = str(
        get_description_field(d, "影片名称")
        or get_description_field(d, "影片名稱")
        or ""
    ).strip()
    title_fake = bool(t) and is_fake_forum_title_fast(t, code)
    film_fake = bool(film) and is_fake_forum_title_fast(film, code)
    film_ok = bool(film) and not film_fake
    title_ok = bool(t) and not title_fake
    # 帖题/影片名都是假壳 → 不占桶
    if not film_ok and not title_ok:
        return -100

    score = 0
    if "出演女优" in d or "出演女優" in d or "演出者" in d or "出演者" in d:
        score += 70
    if film_ok:
        score += 80
    elif "影片名称" in d or "影片名稱" in d:
        score += 20
    elif "资源名称" in d or "资源名稱" in d:
        score += 30
    if title_ok:
        score += 40
    elif title_fake:
        score -= 80

    # 只看题/片名短文本，避免整段 description 数汉字拖慢
    tip = f"{film}\n{t}"
    cjk = sum(1 for ch in tip if "\u4e00" <= ch <= "\u9fff")
    kana = any("\u3040" <= ch <= "\u30ff" for ch in tip)
    if title_ok or film_ok:
        if cjk >= 6 and not kana:
            score += 100
        elif cjk >= 4:
            score += 35
    if kana:
        score -= 50
    score += min(cjk, 40)
    return score


def _append_title_post(
    bucket: list[dict[str, Any]],
    post: dict[str, Any],
    *,
    code: str = "",
    cap: int = PREFIX_POSTS_PER_CODE,
) -> None:
    """桶未满则追加；已满则用更高分替换最弱一条。假壳帖不进桶。"""
    if cap <= 0:
        return
    new_sc = _post_zh_keep_score(
        str(post.get("description") or ""),
        str(post.get("title") or ""),
        code=code,
    )
    if new_sc < 0:
        return
    item = {
        "description": post.get("description") or "",
        "title": post.get("title") or "",
        "_ks": new_sc,
    }
    if len(bucket) < cap:
        bucket.append(item)
        return
    worst_i = 0
    worst_sc = int(bucket[0].get("_ks") or 0)
    for i in range(1, len(bucket)):
        sc = int(bucket[i].get("_ks") or 0)
        if sc < worst_sc:
            worst_sc = sc
            worst_i = i
    if new_sc > worst_sc:
        bucket[worst_i] = item


def _rows_to_prefix_index(
    prefix: str,
    rows: list[dict[str, Any]],
    *,
    region: str | None = None,
) -> dict[str, Any]:
    # 封面 = 点进番号后默认列表第一条的预览图（created_at 新→旧）
    from .forum_seed import pick_forum_seed_from_posts
    from .pack_bleed import get_description_field
    from .region_board_allowlist import board_fid_allowed, normalize_region

    ordered = _sort_for_prefix_cover(rows)
    region_key = normalize_region(region)
    from .maker_fs import indexes_forum_actors
    from .pack_bleed import own_maker_codes_for_index_row

    want_actors = indexes_forum_actors(region_key or region)
    # 无 region 时：有码风格前缀仍排除国产/明确无码（旧行为）
    skip_foreign = (not region_key) and _is_japan_censored_style_prefix(prefix)
    by_code: dict[str, dict[str, Any]] = {}
    posts_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in ordered:
        fid = str(row.get("board_fid") or "").strip()
        # 封面：仅本分区；标题：全站同番号帖都可参与（便于讨论区中文译名）
        cover_ok = True
        if region_key and not board_fid_allowed(fid, region_key):
            cover_ok = False
        if skip_foreign and _is_domestic_or_clear_uncensored_row(row):
            cover_ok = False
        desc = str(row.get("description") or "")
        post_title = str(row.get("title") or "").strip()
        filename = str(row.get("filename") or "").strip()
        # 标题只用帖题；文件名仅参与抽码，不当标题兜底（非正常宁缺）
        seed_title = post_title
        # 抽码：文件名/帖题 + 【影片名称】/【资源名称】（描述里常有番号）
        film = str(
            get_description_field(desc, "影片名称")
            or get_description_field(desc, "影片名稱")
            or ""
        ).strip()
        resource = str(
            get_description_field(desc, "资源名称")
            or get_description_field(desc, "资源名稱")
            or ""
        ).strip()
        codes, pack = own_maker_codes_for_index_row(
            prefix=prefix,
            filename=filename,
            title=post_title,
            film=film,
            resource=resource,
            description=desc,
            hash_=str(row.get("hash") or "") or None,
            ed2k_links=row.get("ed2k_links"),
            ed2k_link=str(row.get("ed2k_link") or "") or None,
        )
        if not codes:
            continue
        for code in codes:
            code = _std_code_key(code, pad=0)
            if not code:
                continue
            # 合集帖：共享描述/女优属其中一部，勿灌进本资源以外的番号
            if (desc.strip() or seed_title) and not pack:
                _append_title_post(
                    posts_by_code.setdefault(code, []),
                    {"description": desc, "title": seed_title},
                    code=code,
                )
            if not cover_ok:
                continue
            covers = _prefix_tile_covers(
                code, row.get("preview_images"), pack=pack
            )
            prev = by_code.get(code)
            if not prev:
                # 无预览图也收录番号；有图时再填封面
                by_code[code] = {
                    "code": code,
                    "coverUrl": covers[0] if covers else None,
                    "coverUrls": covers,
                }
                continue
            if not covers:
                continue
            # 列表首条锁定；后排只补备用。脆弱图床沉底后刷新 coverUrl
            if _has_still_cover(covers) and not _has_still_cover(
                prev.get("coverUrls")
            ):
                by_code[code] = {
                    "code": code,
                    "coverUrl": covers[0],
                    "coverUrls": covers,
                }
            else:
                merged = _append_cover_fallbacks(
                    list(prev.get("coverUrls") or []), covers, code=code
                )
                prev["coverUrls"] = merged
                prev["coverUrl"] = merged[0] if merged else None
    # 仅保留本分区已收录番号的标题；讨论区中文可覆盖日文
    for code, entry in by_code.items():
        posts = posts_by_code.get(code) or []
        # 多帖桶：中文分高的先扫，保证聚合窗口内中文优先
        posts = sorted(
            posts,
            key=lambda p: -int(
                p.get("_ks")
                if "_ks" in p
                else _post_zh_keep_score(
                    str(p.get("description") or ""),
                    str(p.get("title") or ""),
                    code=code,
                )
            ),
        )
        seed = pick_forum_seed_from_posts(
            code,
            posts,
            max_posts=PREFIX_POSTS_PER_CODE,
            want_actors=want_actors,
        )
        title = str(seed.get("title") or "").strip()
        actors = (
            seed.get("actors")
            if want_actors and isinstance(seed.get("actors"), list)
            else []
        )
        # pick_forum_seed_from_posts 已保证可索引或空
        if title:
            entry["forumTitle"] = title
        if want_actors and actors:
            entry["forumActors"] = [str(a) for a in actors if str(a).strip()]
    items = sorted(by_code.values(), key=lambda it: code_sort_key(it["code"]))
    _strip_shared_junk_covers(items)
    return {"items": items, "matchedRows": len(rows)}


def _collect_posts_by_code_from_rows(
    prefix: str, rows: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """从扫库行抽番号→帖桶（只收标题，不碰封面）。合集不灌共享描述。"""
    from .pack_bleed import get_description_field, own_maker_codes_for_index_row

    posts_by_code: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        desc = str(row.get("description") or "")
        post_title = str(row.get("title") or "").strip()
        filename = str(row.get("filename") or "").strip()
        seed_title = post_title
        film = str(
            get_description_field(desc, "影片名称")
            or get_description_field(desc, "影片名稱")
            or ""
        ).strip()
        resource = str(
            get_description_field(desc, "资源名称")
            or get_description_field(desc, "资源名稱")
            or ""
        ).strip()
        codes, pack = own_maker_codes_for_index_row(
            prefix=prefix,
            filename=filename,
            title=post_title,
            film=film,
            resource=resource,
            description=desc,
            hash_=str(row.get("hash") or "") or None,
            ed2k_links=row.get("ed2k_links"),
            ed2k_link=str(row.get("ed2k_link") or "") or None,
        )
        if pack or not codes:
            continue
        for code in codes:
            code = _std_code_key(code, pad=0)
            if not code:
                continue
            if desc.strip() or seed_title:
                _append_title_post(
                    posts_by_code.setdefault(code, []),
                    {"description": desc, "title": seed_title},
                    code=code,
                )
    return posts_by_code


def _scan_prefix_zh_boost_rows(prefix: str) -> list[dict[str, Any]]:
    """专扫中文帖题补译名（只扫 title，避免 description ILIKE 拖垮索引）。"""
    if not PREFIX_ZH_BOOST_ENABLED:
        return []
    needle = str(prefix or "").strip()
    if not needle:
        return []
    contains = f"%{escape_ilike(needle)}-%"
    # 仅 title：通常有 trigram/btree 可用；description 全表 ILIKE 是上次变慢主因
    sql = f"""
SELECT
  r.hash,
  r.filename,
  r.created_at,
  rs.title,
  rs.description,
  rs.preview_images,
  rs.board_fid,
  rs.board_name,
  rs.ed2k_links
FROM resource_sources rs
JOIN ed2k_resources r ON r.hash = rs.hash
WHERE TRUE
{PUBLIC_RESOURCE_FILTER}
  AND rs.title ILIKE %s ESCAPE '\\'
  AND rs.title ~ '[一-龥]'
  AND rs.title !~ '[ぁ-んァ-ン]'
ORDER BY rs.created_at DESC NULLS LAST
LIMIT %s
"""
    try:
        return _query_prefix_scan(sql, [contains, PREFIX_ZH_BOOST_ROW_CAP])
    except Exception as err:
        log.warning("prefix zh boost scan %s failed: %s", needle, err)
        return []


def _apply_zh_title_boost(
    prefix: str, indexed: dict[str, Any], *, region: str | None = None
) -> dict[str, Any]:
    """对尚无中文题的番号，用中文补扫结果重选 forumTitle。"""
    from .forum_seed import pick_forum_seed_from_posts
    from .maker_fs import indexes_forum_actors
    from .scrape_forum_title import is_fake_forum_title, is_likely_chinese

    if not PREFIX_ZH_BOOST_ENABLED:
        return indexed

    want_actors = indexes_forum_actors(region)

    items = indexed.get("items")
    if not isinstance(items, list) or not items:
        return indexed
    need = [
        it
        for it in items
        if isinstance(it, dict)
        and (
            not str(it.get("forumTitle") or "").strip()
            or is_fake_forum_title(
                str(it.get("forumTitle") or ""), str(it.get("code") or "")
            )
            or not is_likely_chinese(str(it.get("forumTitle") or ""))
        )
    ]
    # 几乎都已是中文则跳过补扫
    if not need or len(need) < max(3, len(items) // 50):
        return indexed

    boost_rows = _scan_prefix_zh_boost_rows(prefix)
    if not boost_rows:
        return indexed
    posts_by_code = _collect_posts_by_code_from_rows(prefix, boost_rows)
    if not posts_by_code:
        return indexed

    # AARM-015 / AARM-15 对齐
    posts_norm: dict[str, list[dict[str, Any]]] = {}
    for code, posts in posts_by_code.items():
        key = _std_code_key(code)
        bucket = posts_norm.setdefault(key, [])
        for p in posts:
            _append_title_post(bucket, p, code=code)

    upgraded = 0
    for it in need:
        code = str(it.get("code") or "").strip()
        posts = posts_norm.get(_std_code_key(code)) or posts_by_code.get(code) or []
        if not posts:
            continue
        posts = sorted(
            posts,
            key=lambda p: -int(
                p.get("_ks")
                if "_ks" in p
                else _post_zh_keep_score(
                    str(p.get("description") or ""),
                    str(p.get("title") or ""),
                    code=code,
                )
            ),
        )
        seed = pick_forum_seed_from_posts(
            code,
            posts,
            max_posts=PREFIX_POSTS_PER_CODE,
            want_actors=want_actors,
        )
        title = str(seed.get("title") or "").strip()
        if not is_likely_chinese(title) or is_fake_forum_title(title, code):
            continue
        actors = (
            seed.get("actors") if isinstance(seed.get("actors"), list) else []
        )
        # 女优名不当中文补译：会把日文正片标题冲掉
        from .forum_seed import (
            _looks_like_bare_actor_title,
            _title_is_actor_echo,
        )

        if _title_is_actor_echo(title, [str(a) for a in actors if str(a).strip()]):
            continue
        # 人名形短串一律不补；空标题时也不许用女优名填坑
        if _looks_like_bare_actor_title(title):
            continue
        it["forumTitle"] = title
        if want_actors:
            if actors:
                it["forumActors"] = [str(a) for a in actors if str(a).strip()]
            else:
                it.pop("forumActors", None)
        else:
            it.pop("forumActors", None)
        upgraded += 1

    if upgraded:
        log.info(
            "prefix %s zh-boost: +%s chinese titles (from %s rows)",
            prefix,
            upgraded,
            len(boost_rows),
        )
    indexed["zhBoostRows"] = len(boost_rows)
    indexed["zhBoostUpgraded"] = upgraded
    return indexed


def _query_prefix_scan(sql: str, params: list[Any]) -> list[dict[str, Any]]:
    pool = pg.get_pool()
    timeout = _active_scan_timeout()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            try:
                cur.execute(f"SET LOCAL statement_timeout = '{timeout}'")
                cur.execute(sql, params)
                rows = list(cur.fetchall()) if cur.description else []
                cur.execute("COMMIT")
                return rows
            except Exception:
                try:
                    cur.execute("ROLLBACK")
                except Exception:
                    pass
                raise


# 中文（含影片名称且无假名）硬优先，再影片名称/女优/单链/多图
_PREFIX_META_LATERAL = f"""
LEFT JOIN LATERAL (
  SELECT title, description, preview_images, board_fid, board_name, ed2k_links
  FROM resource_sources
  WHERE hash = r.hash
  ORDER BY
    CASE
      WHEN (description ILIKE '%%影片名称%%' OR description ILIKE '%%影片名稱%%')
        AND description ~ '[一-龥]'
        AND description !~ '[ぁ-んァ-ン]' THEN 0
      WHEN title ~ '[一-龥]' AND title !~ '[ぁ-んァ-ン]' THEN 1
      WHEN description ILIKE '%%影片名称%%'
        OR description ILIKE '%%影片名稱%%' THEN 2
      ELSE 3
    END,
    CASE
      WHEN description ILIKE '%%出演女优%%'
        OR description ILIKE '%%出演女優%%' THEN 0
      ELSE 1
    END,
    CASE WHEN coalesce(array_length(ed2k_links, 1), 0) <= 1 THEN 0 ELSE 1 END,
    coalesce(array_length(preview_images, 1), 0) DESC,
    created_at DESC
  LIMIT {int(PREFIX_SOURCES_PER_HASH)}
) rs ON true
"""

# 前缀扫库统一选出：含 hash / ed2k，便于合集只认本资源子文件
_PREFIX_ROW_SELECT = """
  r.hash,
  r.filename,
  r.created_at,
  rs.title,
  rs.description,
  rs.preview_images,
  rs.board_fid,
  rs.board_name,
  rs.ed2k_links
"""


def _scan_likes_via_hash_cte(
    needle: str,
    likes: list[str],
    excludes: list[str],
    *,
    region: str | None = None,
) -> dict[str, Any]:
    """多 pattern 走 hash CTE；板区分区在 Python 侧过滤封面，标题可跨板取中文。"""
    from .region_board_allowlist import normalize_region

    if not likes:
        return {"items": [], "matchedRows": 0}

    # region 仅传给 _rows_to_prefix_index 做封面过滤
    _ = normalize_region(region)
    cap = _active_scan_row_cap(for_prefix=needle)
    if _is_fc2_prefix(needle):
        # 多 pattern 时勿再 /2，否则每路过窄丢番号
        per = max(5000, cap // max(1, len(likes)))
    else:
        per = max(800, cap // max(1, len(likes) * 2))

    union_parts: list[str] = []
    params: list[Any] = []
    for pat in likes:
        union_parts.append(
            f"""
  (
    SELECT r.hash
    FROM ed2k_resources r
    WHERE TRUE
    {PUBLIC_RESOURCE_FILTER}
      AND r.filename ILIKE %s ESCAPE '\\'
    LIMIT %s
  )"""
        )
        params.extend([pat, per])
        union_parts.append(
            f"""
  (
    SELECT rs.hash
    FROM resource_sources rs
    WHERE rs.title ILIKE %s ESCAPE '\\'
    LIMIT %s
  )"""
        )
        params.extend([pat, per])

    exclude_sql = ""
    for ex in excludes:
        exclude_sql += """
  AND COALESCE(r.filename, '') NOT ILIKE %s ESCAPE '\\'
  AND COALESCE(rs.title, '') NOT ILIKE %s ESCAPE '\\'"""
        params.extend([ex, ex])

    sql = f"""
WITH hashes AS (
{" UNION ".join(union_parts)}
)
SELECT
{_PREFIX_ROW_SELECT}
FROM hashes h
JOIN ed2k_resources r ON r.hash = h.hash
{_PREFIX_META_LATERAL}
WHERE TRUE
{PUBLIC_RESOURCE_FILTER}
{exclude_sql}
LIMIT %s
"""
    params.append(_prefix_result_row_cap(needle))
    t_sql = time.perf_counter()
    rows = _query_prefix_scan(sql, params)
    sql_ms = (time.perf_counter() - t_sql) * 1000
    t_py = time.perf_counter()
    indexed = _rows_to_prefix_index(needle, rows, region=region)
    indexed = _apply_zh_title_boost(needle, indexed, region=region)
    py_ms = (time.perf_counter() - t_py) * 1000
    log.debug(
        "prefix %s scan sql_ms=%.0f py_ms=%.0f matchedRows=%s items=%s",
        needle,
        sql_ms,
        py_ms,
        int(indexed.get("matchedRows") or 0),
        len(indexed.get("items") or []),
    )
    return indexed


def _scan_prefix_code_index(
    prefix: str, *, region: str | None = None
) -> dict[str, Any]:
    needle = str(prefix or "").strip()
    if not needle:
        return {"items": [], "matchedRows": 0}

    excludes = prefix_exclude_like_patterns(needle)
    use_anchored = (
        not _is_fc2_prefix(needle)
        and not is_western_studio_prefix(needle)
        and not excludes
    )

    if use_anchored:
        # 先扫 PREFIX-%（选择性更高），再补 %PREFIX-% / title，避免整段只有 leading-wildcard。
        # 板区分区在 Python 侧过滤封面；SQL 不限板，便于讨论区中文译名。
        esc = escape_ilike(needle)
        starts = f"{esc}-%"
        contains = f"%{esc}-%"
        cap = _active_scan_row_cap(for_prefix=needle)
        # 装饰前缀标题补扫：半量即可，多数命中已在 starts 桶
        tail = max(400, cap // 2)
        sql = f"""
WITH hashes AS (
  (
    SELECT r.hash
    FROM ed2k_resources r
    WHERE TRUE
    {PUBLIC_RESOURCE_FILTER}
      AND r.filename ILIKE %s ESCAPE '\\'
    LIMIT %s
  )
  UNION
  (
    SELECT r.hash
    FROM ed2k_resources r
    WHERE TRUE
    {PUBLIC_RESOURCE_FILTER}
      AND r.filename ILIKE %s ESCAPE '\\'
      AND r.filename NOT ILIKE %s ESCAPE '\\'
    LIMIT %s
  )
  UNION
  (
    SELECT rs.hash
    FROM resource_sources rs
    WHERE rs.title ILIKE %s ESCAPE '\\'
    LIMIT %s
  )
)
SELECT
{_PREFIX_ROW_SELECT}
FROM hashes h
JOIN ed2k_resources r ON r.hash = h.hash
{_PREFIX_META_LATERAL}
WHERE TRUE
{PUBLIC_RESOURCE_FILTER}
LIMIT %s
"""
        t_sql = time.perf_counter()
        rows = _query_prefix_scan(
            sql,
            [
                starts,
                cap,
                contains,
                starts,
                tail,
                contains,
                tail,
                _prefix_result_row_cap(needle),
            ],
        )
        sql_ms = (time.perf_counter() - t_sql) * 1000
        t_py = time.perf_counter()
        indexed = _rows_to_prefix_index(needle, rows, region=region)
        indexed = _apply_zh_title_boost(needle, indexed, region=region)
        py_ms = (time.perf_counter() - t_py) * 1000
        log.debug(
            "prefix %s scan sql_ms=%.0f py_ms=%.0f matchedRows=%s items=%s",
            needle,
            sql_ms,
            py_ms,
            int(indexed.get("matchedRows") or 0),
            len(indexed.get("items") or []),
        )
        return indexed

    likes = prefix_like_patterns(needle)
    return _scan_likes_via_hash_cte(
        needle, likes, excludes, region=region
    )


def _cache_key(prefix: str, region: str | None = None) -> str:
    p = str(prefix or "").strip().upper()
    r = str(region or "").strip().lower()
    return f"{p}|{r}" if r else p


def clear_prefix_cache(
    prefix: str | None = None, *, region: str | None = None
) -> None:
    if prefix is None:
        _cache.clear()
        return
    key = _cache_key(prefix, region)
    _cache.pop(key, None)
    # 兼容旧无 region 缓存键
    if region:
        _cache.pop(str(prefix or "").strip().upper(), None)


def _load_cached(
    prefix: str, bust: bool = False, *, region: str | None = None
) -> dict[str, Any]:
    key = _cache_key(prefix, region)
    now = time.time()
    if bust:
        _cache.pop(key, None)
    hit = _cache.get(key)
    if hit and now - hit[0] < PREFIX_CACHE_TTL_S:
        return hit[1]
    data = _scan_prefix_code_index(prefix, region=region)
    _cache[key] = (now, data)
    return data


def list_prefix_resources(
    prefix: str,
    *,
    limit: int = 60,
    offset: int = 0,
    bust: bool = False,
    region: str | None = None,
) -> dict[str, Any]:
    needle = str(prefix or "").strip()
    if not needle:
        return {"items": [], "total_count": 0, "matched_rows": 0}

    safe_limit = min(max(int(limit or 60), 1), 200)
    safe_offset = max(int(offset or 0), 0)

    try:
        indexed = _load_cached(needle, bust=bust, region=region)
        items = indexed["items"]
        page = [
            {
                "code": it["code"],
                "coverUrl": it.get("coverUrl"),
                "coverUrls": list(it.get("coverUrls") or []),
            }
            for it in items[safe_offset : safe_offset + safe_limit]
        ]
        return {
            "items": page,
            "total_count": len(items),
            "matched_rows": int(indexed.get("matchedRows") or 0),
        }
    except ResourceDbUnavailable:
        raise
    except Exception as err:
        log.exception("list_prefix_resources failed")
        raise RuntimeError(f"Failed to list prefix resources: {err}") from err


def _std_code_key(code: str, *, pad: int = 3) -> str:
    """统一番号键（委托 search_av.std_code_key：四位国产、丢分集）。"""
    from .search_av import std_code_key

    return std_code_key(code, pad=pad)


def covers_for_codes(
    prefix: str,
    codes: list[str],
    *,
    bust: bool = False,
    region: str | None = None,
) -> dict[str, Any]:
    """为预设番号格批量回填库内封面（无图则空；可按区裁板）。"""
    needle = str(prefix or "").strip()
    wanted = [str(c).strip() for c in (codes or []) if str(c).strip()]
    if not needle or not wanted:
        return {"prefix": needle, "items": []}

    indexed = _load_cached(needle, bust=bust, region=region)
    by_key: dict[str, dict[str, Any]] = {}
    for it in indexed.get("items") or []:
        key = _std_code_key(str(it.get("code") or ""))
        if not key or key in by_key:
            continue
        urls = [u for u in (it.get("coverUrls") or []) if u][:6]
        by_key[key] = {
            "code": it.get("code"),
            "coverUrl": urls[0] if urls else it.get("coverUrl"),
            "coverUrls": urls,
        }

    items: list[dict[str, Any]] = []
    for code in wanted[:200]:
        hit = by_key.get(_std_code_key(code))
        if hit:
            items.append(
                {
                    "code": code,
                    "coverUrl": hit.get("coverUrl"),
                    "coverUrls": list(hit.get("coverUrls") or []),
                }
            )
        else:
            items.append({"code": code, "coverUrl": None, "coverUrls": []})
    return {"prefix": needle, "items": items}
