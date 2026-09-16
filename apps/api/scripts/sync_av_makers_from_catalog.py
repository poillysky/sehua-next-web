# -*- coding: utf-8 -*-
"""用 catalog 反哺 av-makers.japan.json：扩前缀 + 补中小厂牌。"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import prefix_maker_names as mn  # noqa: E402
from app.core.region_meta import std_prefix  # noqa: E402

AV = ROOT / "apps" / "maps" / "makers" / "av-makers.japan.json"
CAT = ROOT / "data" / "prefix" / "catalog" / "catalog.json"

SKIP_LABELS = {
    "Other Gravure / 其他写真",
    "REbecca / 丽贝卡",
    "Amateur Kikaku / 素人企划",
    "Other Censored / 其他有码",
}


def main() -> None:
    rows: list[dict] = json.loads(AV.read_text(encoding="utf-8"))
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    bucket = cat["regions"]["japan_censored"]["prefixes"]
    by_maker = {r["maker"]: r for r in rows}

    def canon_key(ent: dict) -> str:
        pref = std_prefix(ent.get("prefix") or "")
        base = mn.load_prefix_maker_base().get(pref, "")
        if base in by_maker:
            return base
        for k, (zh, ja, en) in mn.MAKER_I18N.items():
            label = mn.clamp_maker_label(mn.format_maker_label(zh, ja, en))
            if (
                ent.get("maker") == label
                or ent.get("maker_en") == en
                or ent.get("maker_ja") == ja
            ):
                for cand in (k, en, ja, zh):
                    if cand in by_maker:
                        return cand
        m = str(ent.get("maker") or "")
        return m if m in by_maker else ""

    groups: dict[str, list[str]] = defaultdict(list)
    unmatched: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for p, e in bucket.items():
        key = canon_key(e)
        if key:
            groups[key].append(p)
        else:
            unmatched[str(e.get("maker") or p)].append((p, e))

    expanded = 0
    for key, prefs in groups.items():
        row = by_maker[key]
        if row.get("kind") not in ("有码", "写真"):
            continue
        old = [std_prefix(x) for x in (row.get("prefixes") or [])]
        old_set = set(old)
        notes = row.setdefault("prefix_notes", {})
        for p in sorted(prefs):
            if p in old_set:
                continue
            old.append(p)
            old_set.add(p)
            expanded += 1
            if p not in notes:
                n = str((bucket[p].get("notes") or "").split("；")[0])
                n = n.split("·")[0].strip()
                if n and len(n) <= 24 and "集团" not in n and "IPPA" not in n:
                    notes[p] = n
        row["prefixes"] = old

    new_rows: list[dict] = []
    for label, items in sorted(unmatched.items(), key=lambda x: -len(x[1])):
        if label in SKIP_LABELS:
            continue
        prefs = sorted(p for p, _ in items)
        e0 = items[0][1]
        maker_name = (
            str(e0.get("maker_en") or e0.get("maker_ja") or e0.get("maker_zh") or label)
            .split("/")[0]
            .strip()
        )
        if not maker_name or maker_name in by_maker:
            maker_name = str(e0.get("maker_ja") or maker_name).strip()
            if not maker_name or maker_name in by_maker:
                continue
        zh = str(e0.get("maker_zh") or "").strip()
        desc = f"{maker_name}"
        if zh and zh not in desc:
            desc += f"（{zh}）"
        desc += "。由前缀目录同步补全。"
        row = {
            "maker": maker_name,
            "kind": "有码",
            "description": desc[:100],
            "prefixes": prefs,
            "cover_aspect": "2/3",
            "prefix_notes": {},
        }
        new_rows.append(row)
        by_maker[maker_name] = row

    out: list[dict] = []
    inserted = False
    for r in rows:
        if not inserted and r.get("kind") in ("素人", "无码", "FC2"):
            out.extend(new_rows)
            inserted = True
        out.append(r)
    if not inserted:
        out = rows + new_rows

    AV.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "expanded_prefix_links": expanded,
                "added_makers": len(new_rows),
                "new_makers": [r["maker"] for r in new_rows],
                "total_rows": len(out),
                "kind_有码": sum(1 for r in out if r.get("kind") == "有码"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
