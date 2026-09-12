# -*- coding: utf-8 -*-
"""清理审核发现的脏番号，并恢复 MDS（有码·宇宙企画）空壳。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import prefix_catalog_store as store
from app.search.av import resolve_maker_shape

DIGIT_HEAD_RE = re.compile(r"^(\d{2,3})([A-Z]{2,14})$")


def accept_std_code(pref: str, code: str) -> bool:
    pref = re.sub(r"[^A-Z0-9]", "", pref.upper())
    c = code.strip().upper()
    shape = resolve_maker_shape(pref)
    if shape != "std":
        return True
    dm = DIGIT_HEAD_RE.match(pref)
    if dm:
        letter = dm.group(2)
        return bool(
            re.fullmatch(rf"(?:{re.escape(pref)}|{re.escape(letter)})-\d{{2,6}}", c)
        )
    if not re.fullmatch(rf"{re.escape(pref)}-\d{{2,6}}", c):
        return False
    n = int(c.rsplit("-", 1)[-1])
    if pref in {"HEYZO", "KIN8", "XXXAV", "NYOSHIN"}:
        return 0 < n < 100000
    if 1990 <= n <= 2035:
        return False
    return True


def main() -> None:
    doc = store.load_catalog(force=True)
    removed = []

    # HEYZO / JVID 等
    for rid, pref in (
        ("japan_uncensored", "HEYZO"),
        ("china", "JVID"),
    ):
        ent = (doc["regions"][rid].get("prefixes") or {}).get(pref)
        if not ent:
            continue
        old = list(ent.get("codes") or [])
        keep = [c for c in old if accept_std_code(pref, c)]
        drop = [c for c in old if c not in keep]
        if drop:
            ent = dict(ent)
            ent["codes"] = keep
            serials = []
            for c in keep:
                m = re.search(r"-(\d+)$", c)
                if m:
                    serials.append(int(m.group(1)))
            serials = sorted(set(serials))
            ent["serials"] = serials
            ent["serial_max_hint"] = serials[-1] if serials else 0
            ent["latest_code"] = keep[-1] if keep else ""
            ent["code_count"] = len(keep)
            ent["integrity"] = "local_db_index_cleaned"
            doc["regions"][rid]["prefixes"][pref] = store._normalize_prefix_entry(
                pref, ent
            )
            removed.append({"region": rid, "prefix": pref, "dropped": drop})

    # 国产 MKY 被扫成有码 MOODYZ 号：清空错挂
    mky_cn = (doc["regions"]["china"].get("prefixes") or {}).get("MKY")
    if mky_cn and (mky_cn.get("codes") or []) == ["MKY-047"]:
        ent = dict(mky_cn)
        ent.update(
            {
                "codes": [],
                "serials": [],
                "serial_max_hint": 0,
                "latest_code": "",
                "maker": "麻豆传媒",
                "integrity": "region_collision_cleared",
                "notes": "与有码 MKY(MOODYZ) 撞前缀；待按国产语境重扫",
            }
        )
        doc["regions"]["china"]["prefixes"]["MKY"] = store._normalize_prefix_entry(
            "MKY", ent
        )
        removed.append(
            {"region": "china", "prefix": "MKY", "dropped": ["MKY-047"], "reason": "collision"}
        )

    # 恢复有码 MDS（宇宙企画）；国产对应是 MDSR
    jp = doc["regions"]["japan_censored"].setdefault("prefixes", {})
    if "MDS" not in jp:
        jp["MDS"] = store._normalize_prefix_entry(
            "MDS",
            {
                "prefix": "MDS",
                "maker": "宇宙企画",
                "pad": 3,
                "format": "{prefix}-{num}",
                "sources": ["seed", "local-db"],
                "codes": [],
                "serials": [],
                "notes": "宇宙企画主线（勿与国产 MDSR/麻豆混淆）",
                "status": "active",
                "integrity": "restored_seed",
            },
        )
        removed.append({"region": "japan_censored", "prefix": "MDS", "restored": True})

    store.save_catalog(doc)
    print("done", removed)


if __name__ == "__main__":
    main()
