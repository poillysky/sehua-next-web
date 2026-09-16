# -*- coding: utf-8 -*-
"""从 IPPA《编号及其片商对应表》xlsx 完善 japan_censored 厂牌↔前缀。

用法（在 apps/api 下）:
  python scripts/import_ippa_maker_map.py --xlsx "C:/Users/.../IPPA编号及其片商对应表.xlsx"
  python scripts/import_ippa_maker_map.py --xlsx ... --apply

策略（保守）:
- 解析「目前常用番号」→ status=active；仅出现在「历史使用番号」→ status=retired
- 已有前缀：补 sources=ippa；空 maker 字段时回填；不覆盖已有 codes/serials
- 新前缀：空番号入库，留给双库扫描；maker 走 i18n 解析
- 集团行（仅片商列）记入 notes，不当厂牌
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import prefix_catalog_store as store  # noqa: E402
from app import prefix_maker_names as maker_names  # noqa: E402
from app.core.region_meta import std_prefix  # noqa: E402

SOURCE = "ippa"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
CELL_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# 与 avwikidb 同口径
_PREFIX_OK = re.compile(r"^[0-9]{0,3}[A-Z]{2,12}$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]{2,14}")
_BLOCK = {
    "HTTP",
    "HTTPS",
    "HTML",
    "JSON",
    "VR",
    "DVD",
    "BD",
    "HD",
    "WWW",
    "COM",
    "NET",
    "ORG",
    "TOP",
    "JP",
    "AV",
    "IPPA",
    "WILL",
    "SOD",
    "HHH",
    "CA",
    "AND",
    "THE",
    "FOR",
    "FROM",
    "WITH",
    "ONE",  # 常为 ONED 演变叙述中的碎片；真前缀用 ONED
}

_GROUP_HINT = re.compile(r"(集团|集團|系|系列片商|旗下)")


def _col_row(ref: str) -> tuple[int, int]:
    m = re.match(r"([A-Z]+)(\d+)", ref or "")
    if not m:
        return 0, 0
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return col, int(m.group(2))


def _cell_value(el: ET.Element, ss: list[str]) -> str:
    t = el.attrib.get("t")
    v = el.find(f"{CELL_NS}v")
    is_el = el.find(f"{CELL_NS}is")
    if t == "s" and v is not None and v.text is not None:
        return ss[int(v.text)]
    if t == "inlineStr" and is_el is not None:
        return "".join(x.text or "" for x in is_el.iter(f"{CELL_NS}t"))
    if v is not None:
        return v.text or ""
    return ""


def load_sheet1_rows(xlsx: Path) -> list[dict[int, str]]:
    with zipfile.ZipFile(xlsx) as z:
        ss: list[str] = []
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            texts = [t.text or "" for t in si.iter(f"{CELL_NS}t")]
            ss.append("".join(texts))

        rows: dict[int, dict[int, str]] = defaultdict(dict)
        for _ev, el in ET.iterparse(z.open("xl/worksheets/sheet1.xml"), events=("end",)):
            if el.tag != f"{CELL_NS}c":
                continue
            c, r = _col_row(el.attrib.get("r", ""))
            if not r:
                el.clear()
                continue
            val = _cell_value(el, ss)
            if val != "":
                rows[r][c] = val
            el.clear()
    return [rows[r] for r in sorted(rows)]


def clean_maker_name(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    # 去掉全角/半角括号注释：ムーディーズ / IDEAPOCKET 等保留主名
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ・·-–—/")
    return s


def extract_prefixes(text: str) -> list[str]:
    """从常用/历史番号单元格抽出前缀。"""
    s = str(text or "")
    if not s.strip():
        return []
    # 去掉说明前缀
    s = re.sub(r"(VR番号|合集番号|旧番号|新番号)[:：]?", " ", s, flags=re.I)
    out: list[str] = []
    seen: set[str] = set()
    for tok in _TOKEN_RE.findall(s.upper()):
        p = std_prefix(tok)
        if not p or p in _BLOCK or not _PREFIX_OK.match(p):
            continue
        # 过滤纯数字 / 过短噪声
        if p.isdigit() or len(p) < 2:
            continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def parse_ippa(xlsx: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """返回 (有前缀的记录, 全部片商行含仅别称)。"""
    rows = load_sheet1_rows(xlsx)
    records: list[dict[str, Any]] = []
    all_makers: list[dict[str, Any]] = []
    group = ""
    for i, cols in enumerate(rows):
        if i == 0:
            continue  # header
        maker_raw = str(cols.get(1) or "").strip()
        alias_zh = str(cols.get(2) or "").strip()
        labels = str(cols.get(3) or "").strip()
        site = str(cols.get(5) or "").strip()
        ippa_id = str(cols.get(6) or "").strip()
        current = str(cols.get(7) or "").strip()
        historic = str(cols.get(8) or "").strip()
        notes = str(cols.get(11) or "").strip()
        trivia = str(cols.get(10) or "").strip()

        # 集团/分区标题行
        if maker_raw and not (ippa_id or current or historic or site):
            if _GROUP_HINT.search(maker_raw) or len(maker_raw) <= 40:
                group = maker_raw
            continue
        if not maker_raw:
            continue

        cur_prefs = extract_prefixes(current)
        his_prefs = extract_prefixes(historic)
        maker = clean_maker_name(maker_raw) or maker_raw
        row = {
            "maker_raw": maker_raw,
            "maker": maker,
            "alias_zh": alias_zh,
            "labels": labels,
            "site": site,
            "ippa_id": ippa_id,
            "group": group,
            "notes": notes,
            "trivia": trivia,
            "current": cur_prefs,
            "historic": his_prefs,
        }
        all_makers.append(row)
        if cur_prefs or his_prefs:
            records.append(row)
    return records, all_makers


def _merge_sources(ent: dict[str, Any]) -> list[str]:
    return sorted(set(list(ent.get("sources") or []) + [SOURCE]))


def _apply_names(
    ent: dict[str, Any],
    *,
    pref: str,
    maker: str,
    alias_zh: str,
) -> dict[str, Any]:
    cur = dict(ent)
    # 已有展示名优先；空时用 IPPA
    if not str(cur.get("maker") or "").strip():
        cur["maker"] = maker
    if alias_zh and not str(cur.get("maker_zh") or "").strip():
        cur["maker_zh"] = alias_zh
    if maker and not str(cur.get("maker_ja") or "").strip():
        # 片商列常含日文；仅当现有 ja 空时尝试
        if re.search(r"[\u3040-\u30ff]", maker):
            cur["maker_ja"] = maker
        elif not str(cur.get("maker_en") or "").strip():
            cur["maker_en"] = maker

    names = maker_names.resolve_maker_names(pref, existing=cur)
    # resolve 会按 PREFIX_I18N / MAKER_I18N 校正；保留其结果，但 alias 优先补 zh
    if alias_zh and (
        not names.get("maker_zh")
        or names.get("maker_zh") in ("其他有码", "その他有码")
    ):
        names["maker_zh"] = alias_zh
        names["maker"] = maker_names.clamp_maker_label(
            maker_names.format_maker_label(
                alias_zh, names.get("maker_ja") or "", names.get("maker_en") or maker
            )
        )
    for k in ("maker", "maker_zh", "maker_ja", "maker_en"):
        if names.get(k) and (
            not str(cur.get(k) or "").strip()
            or k == "maker" and str(cur.get(k) or "").startswith(pref)
        ):
            cur[k] = names[k]
        elif not str(cur.get(k) or "").strip() and names.get(k):
            cur[k] = names[k]
    # 强制合成展示（若仍空）
    if not str(cur.get("maker") or "").strip():
        cur["maker"] = names.get("maker") or maker or pref
    return cur


def build_prefix_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """prefix → meta（current 优先于 historic）。"""
    out: dict[str, dict[str, Any]] = {}
    for rec in records:
        for role, prefs in (("current", rec["current"]), ("historic", rec["historic"])):
            for p in prefs:
                prev = out.get(p)
                meta = {
                    "prefix": p,
                    "role": role,
                    "maker": rec["maker"],
                    "maker_raw": rec["maker_raw"],
                    "alias_zh": rec["alias_zh"],
                    "group": rec["group"],
                    "site": rec["site"],
                    "ippa_id": rec["ippa_id"],
                    "notes": rec["notes"],
                    "labels": rec["labels"],
                }
                if prev is None:
                    out[p] = meta
                    continue
                # current 覆盖 historic；同级保留先到（表内靠前大厂）
                if prev["role"] == "historic" and role == "current":
                    out[p] = meta
    return out


def _norm_key(s: str) -> str:
    t = str(s or "").casefold()
    t = re.sub(r"[\s　/_·・．.．（）()【】\[\]『』「」☆★*'\"-]+", "", t)
    return t


def enrich_aliases_by_maker(
    records: list[dict[str, Any]],
    bucket: dict[str, Any],
) -> list[str]:
    """无番号列的片商行：按厂牌名匹配已有前缀，回填空的国内别称。"""
    # 建 lookup：规范化厂牌名 → alias
    alias_by_maker: dict[str, str] = {}
    for rec in records:
        alias = str(rec.get("alias_zh") or "").strip()
        if not alias:
            continue
        for key in (rec.get("maker"), rec.get("maker_raw")):
            nk = _norm_key(str(key or ""))
            if nk and len(nk) >= 2:
                alias_by_maker.setdefault(nk, alias)

    touched: list[str] = []
    for pref, ent in list(bucket.items()):
        if str(ent.get("maker_zh") or "").strip():
            continue
        candidates = [
            ent.get("maker") or "",
            ent.get("maker_ja") or "",
            ent.get("maker_en") or "",
        ]
        hit = ""
        for c in candidates:
            nk = _norm_key(c)
            if not nk:
                continue
            if nk in alias_by_maker:
                hit = alias_by_maker[nk]
                break
            # 子串互含（S1 / S1 NO.1 STYLE）
            for mk, al in alias_by_maker.items():
                if mk in nk or nk in mk:
                    if min(len(mk), len(nk)) >= 3:
                        hit = al
                        break
            if hit:
                break
        if not hit:
            continue
        cur = dict(ent)
        cur["maker_zh"] = hit
        cur["sources"] = _merge_sources(cur)
        names = maker_names.resolve_maker_names(pref, existing=cur)
        if names.get("maker"):
            cur["maker"] = names["maker"]
        bucket[pref] = store._normalize_prefix_entry(pref, cur)
        touched.append(pref)
    return touched


def merge_into_catalog(
    prefix_map: dict[str, dict[str, Any]],
    records: list[dict[str, Any]] | None = None,
    *,
    region: str = "japan_censored",
    apply: bool = False,
) -> dict[str, Any]:
    doc = store.load_catalog(force=True)
    bucket = doc["regions"][region]["prefixes"]

    added: list[str] = []
    updated: list[str] = []
    retired_marked: list[str] = []
    skipped_same: list[str] = []
    alias_enriched: list[str] = []

    for pref, meta in sorted(prefix_map.items()):
        role = meta["role"]
        want_status = "active" if role == "current" else "retired"
        note_bits = []
        if meta.get("group"):
            note_bits.append(f"集团:{meta['group']}")
        if meta.get("ippa_id"):
            note_bits.append(f"IPPA:{meta['ippa_id']}")
        if meta.get("site"):
            note_bits.append(f"官网:{meta['site']}")
        if meta.get("notes"):
            note_bits.append(str(meta["notes"])[:120])
        note_join = "；".join(note_bits)

        if pref not in bucket:
            ent = _apply_names(
                {
                    "prefix": pref,
                    "maker": meta["maker"],
                    "maker_zh": meta.get("alias_zh") or "",
                    "sources": [SOURCE],
                    "status": want_status,
                    "integrity": "ippa",
                    "notes": note_join[:300],
                    "codes": [],
                    "serials": [],
                },
                pref=pref,
                maker=meta["maker"],
                alias_zh=meta.get("alias_zh") or "",
            )
            bucket[pref] = store._normalize_prefix_entry(pref, ent)
            added.append(pref)
            continue

        cur = dict(bucket[pref])
        before = json.dumps(
            {
                "maker": cur.get("maker"),
                "maker_zh": cur.get("maker_zh"),
                "maker_ja": cur.get("maker_ja"),
                "status": cur.get("status"),
                "sources": cur.get("sources"),
                "notes": cur.get("notes"),
            },
            ensure_ascii=False,
        )
        cur = _apply_names(
            cur,
            pref=pref,
            maker=meta["maker"],
            alias_zh=meta.get("alias_zh") or "",
        )
        cur["sources"] = _merge_sources(cur)

        # retired：仅当表内标为历史、且当前不是明确 active 常用时才降级
        # 已有 active + 本地有番号 → 不强制 retired（避免误伤仍在流通的旧前缀索引）
        code_n = store.effective_code_count(cur)
        if want_status == "retired" and str(cur.get("status") or "") == "active":
            if code_n == 0:
                cur["status"] = "retired"
                retired_marked.append(pref)
            else:
                # 保留 active，但 notes 标注历史
                tag = "ippa:历史番号"
                note = str(cur.get("notes") or "")
                if tag not in note:
                    cur["notes"] = (note + ("；" if note else "") + tag)[:300]
        elif want_status == "active" and str(cur.get("status") or "") in (
            "",
            "empty",
            "retired",
        ):
            cur["status"] = "active"

        if note_join:
            note = str(cur.get("notes") or "")
            # 轻量追加集团/IPPA，避免重复刷屏
            for bit in note_bits[:2]:
                if bit and bit not in note:
                    note = (note + ("；" if note else "") + bit)[:300]
            cur["notes"] = note

        after = json.dumps(
            {
                "maker": cur.get("maker"),
                "maker_zh": cur.get("maker_zh"),
                "maker_ja": cur.get("maker_ja"),
                "status": cur.get("status"),
                "sources": cur.get("sources"),
                "notes": cur.get("notes"),
            },
            ensure_ascii=False,
        )
        bucket[pref] = store._normalize_prefix_entry(pref, cur)
        if before != after:
            updated.append(pref)
        else:
            skipped_same.append(pref)

    if records:
        alias_enriched = enrich_aliases_by_maker(records, bucket)

    summary = store.public_summary(doc)
    result = {
        "region": region,
        "ippa_prefixes": len(prefix_map),
        "added": len(added),
        "updated": len(updated),
        "retired_marked": len(retired_marked),
        "unchanged": len(skipped_same),
        "alias_enriched": len(alias_enriched),
        "added_sample": added[:40],
        "updated_sample": updated[:40],
        "retired_sample": retired_marked[:40],
        "alias_sample": alias_enriched[:40],
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
    ap.add_argument("--xlsx", required=True, type=Path)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--region", default="japan_censored")
    args = ap.parse_args()
    xlsx: Path = args.xlsx
    if not xlsx.exists():
        print(f"missing xlsx: {xlsx}", file=sys.stderr)
        return 1

    records, all_makers = parse_ippa(xlsx)
    pmap = build_prefix_map(records)
    report_dir = ROOT / "data" / "debug"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "ippa_parsed_makers.json").write_text(
        json.dumps(all_makers, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "ippa_prefix_map.json").write_text(
        json.dumps(pmap, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    result = merge_into_catalog(
        pmap, all_makers, region=args.region, apply=args.apply
    )
    (report_dir / "ippa_merge_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "makers_with_prefixes": len(records),
                "makers_total": len(all_makers),
                "prefixes_from_ippa": len(pmap),
                "added": result["added"],
                "updated": result["updated"],
                "retired_marked": result["retired_marked"],
                "alias_enriched": result["alias_enriched"],
                "unchanged": result["unchanged"],
                "applied": result["applied"],
                "note": (
                    "IPPA表以片商/子品牌/IPPA编号为主；"
                    "「目前/历史番号」仅约25家大厂有填，其余行无品番前缀可导入"
                ),
                "japan_censored": next(
                    (
                        r
                        for r in (result.get("summary") or {}).get("regions") or []
                        if r.get("id") == "japan_censored"
                    ),
                    {},
                ),
                "added_sample": result["added_sample"],
                "retired_sample": result["retired_sample"],
                "alias_sample": result["alias_sample"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
