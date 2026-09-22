# -*- coding: utf-8 -*-
"""恢复误删的素人数字头前缀，并从本地库重扫番号。"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.search import bitmagnet_pg  # noqa: E402
from app.core import pg  # noqa: E402
from app.prefix import catalog_store as store  # noqa: E402
from app.prefix import maker_names as names  # noqa: E402
from app.prefix import ranges as pr  # noqa: E402
from app.search.av import (  # noqa: E402
    _clamp_std_code_digits,
    code_sort_key,
    extract_maker_codes,
)

# 误从素人区删掉的 MGStage 数字头（本身是独立素人前缀）
RESTORE = [
    "107SODS",
    "107START",
    "112SVVRT",
    "136SW",
    "201KDMN",
    "326KFNE",
    "406FCDSS",
    "406FNS",
    "406FSDSS",
    "406FSVSS",
    "513DLDSS",
    "554SPIVR",
]

# 厂牌：按发行厂，但留在素人区（数字头渠道）
MAKER_HINT = {
    "107SODS": "SOD Create",
    "107START": "SOD Create",
    "112SVVRT": "Sadistic Village",
    "136SW": "AKNR",
    "201KDMN": "SOD Create",
    "326KFNE": "SOD Create",
    "406FCDSS": "FALENO",
    "406FNS": "FALENO",
    "406FSDSS": "FALENO",
    "406FSVSS": "FALENO",
    "513DLDSS": "DAHLIA",
    "554SPIVR": "Sadistic Village",
}

CODE_RE = re.compile(
    r"(?:^|[^A-Z0-9])([A-Z]{2,20}|\d{2,3}[A-Z]{2,14}|[A-Z]+\d+[A-Z]*)[-_\s]?(\d{2,6})(?![0-9])",
    re.I,
)


def clean(p: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", p.upper())


def scan_one(pref: str) -> set[str]:
    """只抽本前缀精确命中（112SVVRT-001，不吞 SVVRT）。"""
    out: set[str] = set()
    want = clean(pref)
    pat = f"%{pref}%"

    def eat(text: str) -> None:
        if not text:
            return
        upper = text.upper()
        # extract_maker_codes 对本前缀
        for c in extract_maker_codes(text, pref):
            cu = str(c).strip().upper()
            if cu.startswith(want + "-") or cu.startswith(want):
                out.add(cu)
        # 精确 CODE_RE：前缀必须整段等于 want（含数字头）
        for m in CODE_RE.finditer(upper):
            p = clean(m.group(1))
            if p != want:
                continue
            clamped = _clamp_std_code_digits(
                p, m.group(2), following=upper[m.end() : m.end() + 12]
            )
            if not clamped:
                continue
            n = int(clamped)
            if n <= 0:
                continue
            pad = 3 if n < 1000 else (4 if n < 10000 else len(str(n)))
            out.add(f"{want}-{str(n).zfill(pad)}")

    rows = pg.query(
        """
        SELECT COALESCE(r.filename,'') AS f, COALESCE(rs.title,'') AS t
        FROM ed2k_resources r
        LEFT JOIN LATERAL (
          SELECT title FROM resource_sources
          WHERE hash = r.hash ORDER BY created_at DESC LIMIT 1
        ) rs ON TRUE
        WHERE COALESCE(r.filename,'') ILIKE %s
           OR COALESCE(rs.title,'') ILIKE %s
        LIMIT 50000
        """,
        [pat, pat],
    )
    for r in rows:
        eat(f"{r.get('f')}\n{r.get('t')}")

    for table, col, lim in (
        ("torrents", "name", 200000),
        ("content", "title", 50000),
    ):
        try:
            brows = bitmagnet_pg.query(
                f'SELECT COALESCE("{col}",\'\') AS txt FROM "{table}" '
                f"WHERE COALESCE(\"{col}\",'') ILIKE %s LIMIT %s",
                [pat, lim],
            )
        except Exception as e:  # noqa: BLE001
            print(f"  bit {table} skip {e}", flush=True)
            continue
        for r in brows:
            eat(str(r.get("txt") or ""))

    return out


def main() -> None:
    doc = store.load_catalog(force=True)
    ama = doc["regions"]["japan_amateur"]["prefixes"]
    print("restore amateur digit prefixes…", flush=True)

    for pref in RESTORE:
        print(f"  scan {pref} …", flush=True)
        codes = sorted(scan_one(pref), key=code_sort_key)
        serials = sorted(
            {
                int(m.group(1))
                for c in codes
                if (m := re.search(rf"^{re.escape(pref)}-(\d+)$", c, re.I))
            }
        )
        hint = MAKER_HINT.get(pref, "")
        raw = {
            "maker": hint,
            "pad": 3,
            "format": "{prefix}-{num}",
            "codes": codes,
            "serials": serials,
            "serial_max_hint": serials[-1] if serials else 0,
            "latest_code": max(codes, key=code_sort_key) if codes else "",
            "sources": ["local-db", "bitmagnet"],
            "status": "active",
            "integrity": "local_db_index" if codes else "local_db_miss",
            "verified_at": store._now(),
            "notes": "MGStage 素人数字头渠道（与字母有码前缀并存）",
        }
        resolved = names.resolve_maker_names(pref, existing=raw)
        pe = store._normalize_prefix_entry(pref, {**raw, **resolved})
        for k in (
            "codes",
            "serials",
            "latest_code",
            "serial_max_hint",
            "notes",
            "sources",
            "verified_at",
            "integrity",
            "status",
        ):
            if raw.get(k) not in (None, [], ""):
                pe[k] = raw[k]
        if pe.get("codes"):
            pe["code_count"] = len(pe["codes"])
        pe["maker"] = names.clamp_maker_label(pe.get("maker") or hint)
        ama[pref] = pe
        print(
            f"    → {len(codes)} codes latest={pe.get('latest_code')} maker={pe.get('maker')}",
            flush=True,
        )

    # 确保映射表里有这些键（避免以后再丢厂牌）
    # 直接写 catalog 即可

    store.save_catalog(doc)
    print(
        "amateur count",
        len(doc["regions"]["japan_amateur"]["prefixes"]),
        flush=True,
    )


if __name__ == "__main__":
    main()
