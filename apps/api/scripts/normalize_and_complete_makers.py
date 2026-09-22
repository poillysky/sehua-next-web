# -*- coding: utf-8 -*-
"""统一并补全 japan_censored 厂牌名（合并 IPPA/AVWikiDB 拆散的同厂标签）。

用法（apps/api）:
  python scripts/normalize_and_complete_makers.py
  python scripts/normalize_and_complete_makers.py --apply
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.prefix import catalog_store as store  # noqa: E402
from app.prefix import maker_names as maker_names  # noqa: E402
from app.core.region_meta import std_prefix  # noqa: E402

AV_MAKERS = ROOT / "apps" / "maps" / "makers" / "av-makers.japan.json"
IPPA_PARSED = ROOT / "data" / "debug" / "ippa_parsed_makers.json"

# 口语/日文别称 → MAKER_I18N 主 key
from app.core.maps_paths import studio_alias_map  # noqa: E402

HARD_ALIAS: dict[str, str] = studio_alias_map()


def _norm(s: str) -> str:
    t = str(s or "").casefold()
    t = re.sub(r"[\s　/_·・．.．（）()【】\[\]『』「」☆★*'\"\-–—]+", "", t)
    return t


def build_alias_index() -> dict[str, str]:
    """normalized alias → MAKER_I18N key。"""
    idx: dict[str, str] = {}

    def put(alias: str, canon: str) -> None:
        if not alias or not canon:
            return
        if canon not in maker_names.MAKER_I18N and canon not in HARD_ALIAS:
            # 允许 canon 本身是 key
            if canon not in maker_names.MAKER_I18N:
                # try resolve via HARD_ALIAS
                canon = HARD_ALIAS.get(canon, canon)
        if canon not in maker_names.MAKER_I18N:
            return
        for key in {alias, alias.strip(), _norm(alias)}:
            if key:
                idx[key] = canon
                idx[_norm(key)] = canon

    for k, (zh, ja, en) in maker_names.MAKER_I18N.items():
        put(k, k)
        put(zh, k)
        put(ja, k)
        put(en, k)
        # 「A / B」两侧
        for part in re.split(r"[/／]", zh or ""):
            put(part.strip(), k)

    for a, c in HARD_ALIAS.items():
        put(a, c if c in maker_names.MAKER_I18N else HARD_ALIAS.get(c, c))

    # IPPA 别称
    if IPPA_PARSED.exists():
        for row in json.loads(IPPA_PARSED.read_text(encoding="utf-8")):
            maker = str(row.get("maker") or "").strip()
            raw = str(row.get("maker_raw") or "").strip()
            alias = str(row.get("alias_zh") or "").strip()
            # 尝试挂到已有 canon
            canon = ""
            for cand in (maker, raw, alias):
                if not cand:
                    continue
                if cand in maker_names.MAKER_I18N:
                    canon = cand
                    break
                if cand in HARD_ALIAS:
                    canon = HARD_ALIAS[cand]
                    break
                n = _norm(cand)
                if n in idx:
                    canon = idx[n]
                    break
            if not canon:
                continue
            put(maker, canon)
            put(raw, canon)
            put(alias, canon)

    return idx


def resolve_canon(ent: dict[str, Any], alias_idx: dict[str, str]) -> str:
    def ok(c: str) -> str:
        if not c:
            return ""
        if c in maker_names.MAKER_I18N:
            return c
        if c in HARD_ALIAS:
            h = HARD_ALIAS[c]
            return h if h in maker_names.MAKER_I18N else ""
        return ""

    pref = std_prefix(ent.get("prefix") or "")
    if pref in maker_names.PREFIX_I18N:
        # PREFIX_I18N 存的是三语，不是 maker key；用 en/ja 反查
        zh, ja, en = maker_names.PREFIX_I18N[pref]
        for cand in (en, ja, zh):
            hit = ok(cand)
            if hit:
                return hit
            n = _norm(cand)
            if n in alias_idx:
                hit = ok(alias_idx[n])
                if hit:
                    return hit

    base = maker_names.load_prefix_maker_base().get(pref, "")
    hit = ok(base)
    if hit:
        return hit
    if _norm(base) in alias_idx:
        hit = ok(alias_idx[_norm(base)])
        if hit:
            return hit

    for field in ("maker_en", "maker_ja", "maker_zh", "maker"):
        raw = str(ent.get(field) or "").strip()
        if not raw:
            continue
        first = raw.split("/")[0].strip()
        for cand in (raw, first):
            hit = ok(cand)
            if hit:
                return hit
            n = _norm(cand)
            if n in alias_idx:
                hit = ok(alias_idx[n])
                if hit:
                    return hit
    return ""


def apply_canon(ent: dict[str, Any], canon: str) -> dict[str, Any]:
    if canon not in maker_names.MAKER_I18N:
        return dict(ent)
    zh, ja, en = maker_names.MAKER_I18N[canon]
    cur = dict(ent)
    cur["maker_zh"] = zh
    cur["maker_ja"] = ja
    cur["maker_en"] = en
    cur["maker"] = maker_names.clamp_maker_label(
        maker_names.format_maker_label(zh, ja, en)
    )
    # 保留 sources，标记规范化
    src = list(cur.get("sources") or [])
    if "maker-norm" not in src:
        src.append("maker-norm")
    cur["sources"] = sorted(set(src))
    return cur


def missing_av_makers_censored(bucket: dict[str, Any]) -> list[tuple[str, str]]:
    if not AV_MAKERS.exists():
        return []
    rows = json.loads(AV_MAKERS.read_text(encoding="utf-8"))
    out: list[tuple[str, str]] = []
    for row in rows:
        if row.get("kind") != "有码":
            continue
        maker = str(row.get("maker") or "").strip()
        for p in row.get("prefixes") or []:
            pref = std_prefix(p)
            if pref and pref not in bucket:
                out.append((pref, maker))
    return out


def run(*, apply: bool) -> dict[str, Any]:
    alias_idx = build_alias_index()
    doc = store.load_catalog(force=True)
    region = "japan_censored"
    bucket = doc["regions"][region]["prefixes"]

    before_labels = sorted(
        {str(e.get("maker") or "") for e in bucket.values() if e.get("maker")}
    )

    changed = 0
    canon_hits = 0
    canon_miss: list[str] = []
    label_before: dict[str, set[str]] = defaultdict(set)

    for pref, ent in list(bucket.items()):
        canon = resolve_canon(ent, alias_idx)
        if not canon:
            canon_miss.append(pref)
            continue
        canon_hits += 1
        label_before[canon].add(str(ent.get("maker") or ""))
        new_ent = apply_canon(ent, canon)
        new_ent["prefix"] = pref
        pe = store._normalize_prefix_entry(pref, new_ent)
        # preserve codes/serials already in normalize
        if pe.get("maker") != ent.get("maker") or pe.get("maker_zh") != ent.get(
            "maker_zh"
        ):
            changed += 1
        bucket[pref] = pe

    added = 0
    added_list: list[str] = []
    for pref, maker in missing_av_makers_censored(bucket):
        canon = maker if maker in maker_names.MAKER_I18N else HARD_ALIAS.get(maker, "")
        if canon not in maker_names.MAKER_I18N:
            # still add with resolve
            ent = {
                "prefix": pref,
                "maker": maker,
                "sources": ["av-makers", "maker-norm"],
                "status": "active",
                "integrity": "av-makers",
                "codes": [],
                "serials": [],
            }
            names = maker_names.resolve_maker_names(pref, existing=ent)
            ent.update(names)
        else:
            ent = apply_canon(
                {
                    "prefix": pref,
                    "sources": ["av-makers", "maker-norm"],
                    "status": "active",
                    "integrity": "av-makers",
                    "codes": [],
                    "serials": [],
                },
                canon,
            )
        bucket[pref] = store._normalize_prefix_entry(pref, ent)
        added += 1
        added_list.append(pref)

    after_labels = sorted(
        {str(e.get("maker") or "") for e in bucket.values() if e.get("maker")}
    )
    by_maker: dict[str, int] = defaultdict(int)
    for e in bucket.values():
        by_maker[str(e.get("maker") or "")] += 1

    summary = store.public_summary(doc)
    result = {
        "canon_hits": canon_hits,
        "canon_miss": len(canon_miss),
        "canon_miss_sample": canon_miss[:30],
        "labels_changed_entries": changed,
        "unique_makers_before": len(before_labels),
        "unique_makers_after": len(after_labels),
        "merged_examples": {
            k: sorted(v)
            for k, v in sorted(label_before.items(), key=lambda x: -len(x[1]))
            if len(v) > 1
        },
        "added_from_av_makers": added,
        "added_sample": added_list,
        "top_makers_after": sorted(by_maker.items(), key=lambda x: -x[1])[:25],
        "summary": summary,
        "applied": False,
    }
    if apply:
        store.save_catalog(doc)
        result["applied"] = True
        result["summary"] = store.public_summary()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    result = run(apply=args.apply)
    out = ROOT / "data" / "debug" / "maker_normalize_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "applied": result["applied"],
                "unique_makers": f"{result['unique_makers_before']} → {result['unique_makers_after']}",
                "entries_relabeled": result["labels_changed_entries"],
                "canon_hits": result["canon_hits"],
                "canon_miss": result["canon_miss"],
                "added_prefixes": result["added_from_av_makers"],
                "added_sample": result["added_sample"],
                "merged_examples": result["merged_examples"],
                "top_makers": result["top_makers_after"][:12],
                "japan_censored": next(
                    (
                        r
                        for r in (result.get("summary") or {}).get("regions") or []
                        if r.get("id") == "japan_censored"
                    ),
                    {},
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
