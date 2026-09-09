# -*- coding: utf-8 -*-
"""从 AVWikiDB 同步厂牌 ↔ 前缀关系到七区 catalog。

策略（保守，不覆盖你已维护的展示名）：
1. 对区内已有前缀拉 `/work/{PREFIX}/`，回填 `maker_ja`，并记录 avwikidb 来源
2. 收集命中的 FANZA makerId，拉 `/maker/{id}/` 的 `prefixes[]`
3. 把同厂牌下缺失且达标的前缀补进 catalog（空番号，留给双库扫描填）

默认只动 `japan_censored`；有码厂牌页噪声大，新前缀要求 movieCount 达标。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable

from . import prefix_catalog_store as store
from . import prefix_maker_names as maker_names
from .region_meta import std_prefix
from .scrape_details.common import fetch_html

log = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]

DEFAULT_BASE = "https://avwikidb.com"
SOURCE = "avwikidb"

_NEXT_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.I | re.S,
)

# 明显非品番噪声
_BLOCK_PREFIX = {
    "HTTP",
    "HTTPS",
    "HTML",
    "JSON",
    "PAGE",
    "HOME",
    "NULL",
    "TRUE",
    "FALSE",
    "JPEG",
    "WEBP",
    "PNG",
    "JPG",
    "CSS",
    "WWW",
    "COM",
    "NET",
    "ORG",
    "CDN",
    "IMG",
    "PIC",
    "URL",
    "API",
    "GET",
    "POST",
    "AND",
    "THE",
    "FOR",
    "FROM",
    "WITH",
    "THIS",
    "THAT",
    "DATE",
    "TIME",
    "YEAR",
    "MONTH",
    "WEEK",
    "DAY",
    "VR",
    "DVD",
    "BD",
    "HD",
}

_PREFIX_OK = re.compile(r"^[0-9]{0,3}[A-Z]{2,12}$")


def _progress(cb: ProgressCb | None, msg: str) -> None:
    if cb:
        cb(msg)
    else:
        log.info("%s", msg)


def _page_props(url: str) -> dict[str, Any]:
    html = fetch_html(url, referer=f"{DEFAULT_BASE}/", source_id=SOURCE)
    m = _NEXT_RE.search(html or "")
    if not m:
        raise RuntimeError("页面无结构化数据")
    try:
        nd = json.loads(m.group(1))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("结构化数据解析失败") from e
    props = ((nd.get("props") or {}).get("pageProps") or {})
    return props if isinstance(props, dict) else {}


def _accept_prefix(raw: str) -> str:
    p = std_prefix(raw)
    if not p or p in _BLOCK_PREFIX:
        return ""
    if not _PREFIX_OK.match(p):
        return ""
    return p


def _makers_from_work(props: dict[str, Any]) -> list[dict[str, Any]]:
    rows = props.get("makers")
    out: list[dict[str, Any]] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        mid = row.get("id") or row.get("fanzaMakerId")
        if not name:
            continue
        out.append(
            {
                "id": int(mid) if mid is not None else 0,
                "name": name,
                "amateur": bool(row.get("amateur")),
            }
        )
    return out


def _merge_sources(ent: dict[str, Any]) -> list[str]:
    return sorted(set(list(ent.get("sources") or []) + [SOURCE]))


def _apply_maker_ja(
    ent: dict[str, Any], *, pref: str, maker_ja: str
) -> dict[str, Any]:
    """回填日文厂牌；展示名优先走既有 i18n / 已维护 label。"""
    cur = dict(ent)
    ja = str(maker_ja or "").strip()
    if ja:
        cur["maker_ja"] = ja
    cur["sources"] = _merge_sources(cur)
    names = maker_names.resolve_maker_names(pref, existing=cur)
    # 已有中英展示时不因日文回填整段改写；仅空时用解析结果
    if not str(cur.get("maker") or "").strip():
        cur["maker"] = names.get("maker") or ""
    if not str(cur.get("maker_zh") or "").strip():
        cur["maker_zh"] = names.get("maker_zh") or ""
    if not str(cur.get("maker_en") or "").strip():
        cur["maker_en"] = names.get("maker_en") or ""
    if ja:
        cur["maker_ja"] = ja
    elif names.get("maker_ja"):
        cur["maker_ja"] = names["maker_ja"]
    return cur


def sync_maker_prefix_map(
    *,
    region: str = "japan_censored",
    prefixes: list[str] | None = None,
    limit: int = 0,
    expand: bool = True,
    min_movie_count: int = 5,
    sleep_s: float = 0.05,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """同步厂牌↔前缀。返回统计。"""
    if region not in store.load_catalog().get("regions", {}):
        raise ValueError(f"unknown region: {region}")

    doc = store.load_catalog(force=True)
    bucket = doc["regions"][region]["prefixes"]
    keys = [std_prefix(p) for p in prefixes] if prefixes else sorted(bucket.keys())
    keys = [k for k in keys if k]
    if limit and limit > 0:
        keys = keys[:limit]

    refreshed = 0
    miss = 0
    err = 0
    maker_ids: dict[int, str] = {}  # fanzaMakerId or internal id → ja name
    # work page makers[].id 是站内 id；maker 详情 URL 用 fanzaMakerId
    # /work/ 返回的 id 实际可打开 /maker/{id}/（已验证 3152→S1 不对，45338 是 fanza）
    # 上面探测：maker/45338 是 GIGA 的 fanzaMakerId；work makers[].id=3152 也能？
    # 重新确认：SSIS makers id=3152；打开 /maker/3152/ 是否有效？

    _progress(on_progress, f"AVWikiDB · {region} · {len(keys)} 前缀")

    for i, pref in enumerate(keys, 1):
        ent = dict(bucket.get(pref) or store._normalize_prefix_entry(pref, {}))
        _progress(on_progress, f"[{i}/{len(keys)}] {pref} …")
        try:
            props = _page_props(f"{DEFAULT_BASE}/work/{pref}/")
            makers = _makers_from_work(props)
            if not makers:
                miss += 1
                _progress(on_progress, f"[{i}/{len(keys)}] -- {pref}")
                continue
            primary = makers[0]
            name_ja = primary["name"]
            mid = int(primary.get("id") or 0)
            # work.makers[].id 与 movies[].maker.fanzaMakerId 通常一致，均可打开 /maker/{id}/
            fanza_id = 0
            movies = props.get("movies")
            if isinstance(movies, list) and movies:
                m0 = movies[0] if isinstance(movies[0], dict) else {}
                mlist = m0.get("maker") if isinstance(m0, dict) else None
                if isinstance(mlist, list) and mlist and isinstance(mlist[0], dict):
                    fid = mlist[0].get("fanzaMakerId")
                    if fid:
                        fanza_id = int(fid)
            use_id = fanza_id or mid
            if use_id:
                maker_ids[use_id] = name_ja

            ent = _apply_maker_ja(ent, pref=pref, maker_ja=name_ja)
            if len(makers) > 1:
                alt = "、".join(m["name"] for m in makers[1:4])
                note = str(ent.get("notes") or "")
                tag = f"avwikidb相关:{alt}"
                if tag not in note:
                    ent["notes"] = (note + ("；" if note else "") + tag)[:300]
            bucket[pref] = store._normalize_prefix_entry(pref, ent)
            refreshed += 1
            _progress(
                on_progress,
                f"[{i}/{len(keys)}] OK {pref} → {name_ja}",
            )
        except Exception as e:  # noqa: BLE001
            err += 1
            _progress(on_progress, f"[{i}/{len(keys)}] ERR {pref} {e}")
        if sleep_s > 0:
            time.sleep(sleep_s)
        if i % 10 == 0 or i == len(keys):
            store.save_catalog(doc)

    added = 0
    skipped_low = 0
    if expand and maker_ids:
        ids = sorted(maker_ids.keys())
        _progress(on_progress, f"扩前缀 · {len(ids)} 厂牌")
        for j, mid in enumerate(ids, 1):
            name_ja = maker_ids[mid]
            _progress(on_progress, f"maker[{j}/{len(ids)}] {mid} {name_ja} …")
            try:
                props = _page_props(f"{DEFAULT_BASE}/maker/{mid}/")
                prefs = props.get("prefixes")
                if not isinstance(prefs, list):
                    # 可能误用了站内 id；跳过
                    continue
                maker_node = props.get("maker") if isinstance(props.get("maker"), dict) else {}
                name_ja = str(maker_node.get("name") or name_ja).strip() or name_ja
                for row in prefs:
                    if not isinstance(row, dict):
                        continue
                    p = _accept_prefix(str(row.get("prefix") or ""))
                    if not p:
                        continue
                    mc = int(row.get("movieCount") or 0)
                    if mc < max(1, int(min_movie_count)):
                        skipped_low += 1
                        continue
                    if p in bucket:
                        # 已有：可补日文名
                        cur = dict(bucket[p])
                        if not str(cur.get("maker_ja") or "").strip() and name_ja:
                            cur = _apply_maker_ja(cur, pref=p, maker_ja=name_ja)
                            bucket[p] = store._normalize_prefix_entry(p, cur)
                        continue
                    ent = _apply_maker_ja(
                        {
                            "prefix": p,
                            "maker_ja": name_ja,
                            "sources": [SOURCE],
                            "status": "active",
                            "integrity": "avwikidb",
                            "notes": f"avwikidb扩前缀 movieCount={mc}",
                        },
                        pref=p,
                        maker_ja=name_ja,
                    )
                    bucket[p] = store._normalize_prefix_entry(p, ent)
                    added += 1
                _progress(
                    on_progress,
                    f"maker[{j}/{len(ids)}] OK {name_ja} · +累计 {added}",
                )
            except Exception as e:  # noqa: BLE001
                _progress(on_progress, f"maker[{j}/{len(ids)}] ERR {mid} {e}")
            if sleep_s > 0:
                time.sleep(sleep_s)
            if j % 5 == 0 or j == len(ids):
                store.save_catalog(doc)

    store.save_catalog(doc)
    summary = store.public_summary(doc)
    return {
        "region": region,
        "mode": "avwikidb",
        "checked": len(keys),
        "refreshed": refreshed,
        "miss": miss,
        "error": err,
        "makers": len(maker_ids),
        "added": added,
        "skipped_low": skipped_low,
        "expand": expand,
        "summary": summary,
    }
