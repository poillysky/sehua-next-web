# -*- coding: utf-8 -*-
"""无码缺最新号：本地库（sehua + bitmagnet）搜；搜不到则删前缀。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import bitmagnet_pg  # noqa: E402
from app import pg  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402

# 前缀 → 额外搜词
ALIASES: dict[str, list[str]] = {
    "H0930": ["H0930", "h0930", "ki26", "エッチな0930"],
    "H4610": ["H4610", "h4610", "エッチな4610", "naughty4610"],
    "C0930": ["C0930", "c0930"],
    "NYOSHIN": ["nyoshin", "nymph", "女体のしんぴ"],
    "XXXAV": ["XXX-AV", "XXXAV", "xxx-av"],
    "HEYDOUGA": ["heydouga", "HEYDOUGA"],
    "HEYPPV": ["heyppv", "HEYPPV"],
    "COSPURI": ["cospuri", "COSPURI"],
    "FELLATIOJAPAN": ["fellatiojapan", "FellatioJapan"],
    "HANDJOBJAPAN": ["handjobjapan", "HandjobJapan"],
    "LEGSJAPAN": ["legsjapan", "LegsJapan"],
    "SPERMMANIA": ["spermmania", "SpermMania"],
    "URABUKKAKE": ["urabukkake", "UraBukkake"],
    "URALESBIAN": ["uralesbian", "UraLesbian"],
    "GACHI": ["gachinco", "GACHI", "ガチん娘"],
    "JAPORNXXX": ["japornxxx"],
    "RHJ": ["RHJ-", "redhotjam", "Red Hot Jam"],
    "ROSELIP": ["roselip", "RoseLip"],
    "ROSELIPFETISH": ["roselip", "roselip-fetish"],
    "SMMIRACLE": ["sm-miracle", "smmiracle", "e0"],
    "PT": [" PT-", "Tokyo Hot PT"],
    "271ZM": ["271ZM", "271zm"],
    "283ZM": ["283ZM"],
    "333ZM": ["333ZM"],
    "613ZM": ["613ZM"],
    "667ZM": ["667ZM"],
    "885ZM": ["885ZM"],
}


def sehua_texts(needles: list[str], limit: int = 8000) -> list[str]:
    clauses = []
    params: list[str] = []
    for n in needles:
        clauses.append("(upper(COALESCE(r.filename,'')) LIKE %s OR upper(COALESCE(rs.title,'')) LIKE %s)")
        params.extend([f"%{n.upper()}%", f"%{n.upper()}%"])
    where = " OR ".join(clauses)
    sql = f"""
        SELECT COALESCE(r.filename,'') AS filename,
               COALESCE(rs.title,'') AS title
        FROM ed2k_resources r
        LEFT JOIN LATERAL (
          SELECT title FROM resource_sources
          WHERE hash = r.hash ORDER BY created_at DESC LIMIT 1
        ) rs ON TRUE
        WHERE {where}
        LIMIT {int(limit)}
    """
    try:
        rows = pg.query(sql, params)
    except Exception as e:  # noqa: BLE001
        print(f"  sehua ERR {e}", flush=True)
        return []
    return [f"{r.get('filename') or ''}\n{r.get('title') or ''}" for r in rows]


def bitmagnet_texts(needles: list[str], limit: int = 8000) -> list[str]:
    out: list[str] = []
    try:
        # torrents.name + content.title
        for table, col in (("torrents", "name"), ("content", "title")):
            clauses = []
            params: list[str] = []
            for n in needles:
                clauses.append(f'upper(COALESCE("{col}",\'\')) LIKE %s')
                params.append(f"%{n.upper()}%")
            where = " OR ".join(clauses)
            sql = f'SELECT COALESCE("{col}",\'\') AS txt FROM "{table}" WHERE {where} LIMIT {int(limit // 2)}'
            try:
                rows = bitmagnet_pg.query(sql, params)
            except Exception as e:  # noqa: BLE001
                print(f"  bitmagnet {table}.{col} ERR {e}", flush=True)
                continue
            out.extend(str(r.get("txt") or "") for r in rows)
    except Exception as e:  # noqa: BLE001
        print(f"  bitmagnet ERR {e}", flush=True)
    return out


def date6_key(mmddyy: str) -> int:
    if len(mmddyy) != 6 or not mmddyy.isdigit():
        return 0
    mm, dd, yy = mmddyy[:2], mmddyy[2:4], mmddyy[4:6]
    return int(f"20{yy}{mm}{dd}")


def pick_latest(pref: str, blob: str) -> str:
    u = pref.upper()
    best = ""
    best_score = -1

    def consider(code: str, score: int) -> None:
        nonlocal best, best_score
        if score > best_score:
            best, best_score = code, score

    # H0930 official style kiYYMMDD
    if u == "H0930":
        for m in re.finditer(r"(?i)\bki(\d{6})\b", blob):
            d = m.group(1)  # YYMMDD
            score = int(f"20{d}")
            consider(f"ki{d}", score)
        for m in re.finditer(r"(?i)H0930[-_](\d{6})(?:[-_]([A-Z0-9]+))?", blob):
            d = m.group(1)
            score = date6_key(d) if len(d) == 6 else int(d)
            consider(m.group(0).upper().replace("_", "-"), score)

    if u == "H4610":
        for m in re.finditer(r"(?i)\b(?:h4610|4610)[-_]?([0-9]{6}[A-Z0-9_\-]*)", blob):
            consider(f"H4610-{m.group(1)}", 1)
        for m in re.finditer(r"(?i)\b([0-9]{6})[-_]([a-z0-9]{2,})\b", blob):
            # weak
            consider(f"H4610-{m.group(1)}_{m.group(2)}", date6_key(m.group(1)))

    if u == "C0930":
        for m in re.finditer(r"(?i)\bc0930[-_]?([0-9A-Z_\-]{4,})", blob):
            consider(f"C0930-{m.group(1)}", 1)
        for m in re.finditer(r"(?i)\bci?(\d{6})\b", blob):
            d = m.group(1)
            consider(f"ci{d}", int(f"20{d}"))

    if u == "NYOSHIN":
        for m in re.finditer(r"(?i)(?:nyoshin[-_]?|n(?:yoshin)?[-_]?)(\d{3,5})\b", blob):
            n = int(m.group(1))
            consider(f"n{n}", n)
        for m in re.finditer(r"(?i)/listpages/(\d+)_", blob):
            n = int(m.group(1))
            consider(f"n{n}", n)

    if u == "XXXAV":
        for m in re.finditer(r"(?i)(?:XXX-?AV|XXXAV)[-_ ]?(\d{3,6})", blob):
            n = int(m.group(1))
            consider(f"XXX-AV-{n}", n)

    if u == "HEYDOUGA":
        for m in re.finditer(r"(?i)heydouga[-_](\d+)[-_](\d+)", blob):
            a, b = int(m.group(1)), int(m.group(2))
            consider(f"HEYDOUGA-{a}-{b}", a * 10000 + b)

    if u == "HEYPPV":
        for m in re.finditer(r"(?i)(?:HEYPPV|heyzo[-_]?ppv)[-_]?(\d+)", blob):
            n = int(m.group(1))
            consider(f"HEYPPV-{n}", n)

    if u == "SMMIRACLE":
        for m in re.finditer(r"(?i)(?:e|sm-?miracle[-_]?e?)(\d{4})", blob):
            n = int(m.group(1))
            consider(f"e{n:04d}", n)

    if u == "TOKYO" or u == "PT":
        for m in re.finditer(r"(?i)\bn(\d{3,5})\b", blob):
            n = int(m.group(1))
            consider(f"n{n}", n)
        for m in re.finditer(r"(?i)\bPT[-_]?(\d{2,4})\b", blob):
            n = int(m.group(1))
            consider(f"PT-{n}", n)

    # generic PREFIX-N / PREFIX_N
    rx = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(pref)}[-_ ]?(\d{{2,6}})(?![A-Z0-9])")
    for m in rx.finditer(blob):
        n = int(m.group(1))
        consider(f"{pref.upper()}-{n}", n)

    # date slug PREFIX-MMDDYY
    rx2 = re.compile(
        rf"(?i)(?<![A-Z0-9]){re.escape(pref)}[-_](\d{{6}})[-_](\d{{1,3}})(?![A-Z0-9])"
    )
    for m in rx2.finditer(blob):
        d, s = m.group(1), m.group(2)
        consider(f"{pref.upper()}-{d}_{s}", date6_key(d) * 1000 + int(s))

    # brand sites often use Brand-####
    brands = {
        "LEGSJAPAN": r"(?i)legs[-_]?japan[-_]?(\d+)",
        "FELLATIOJAPAN": r"(?i)fellatio[-_]?japan[-_]?(\d+)",
        "HANDJOBJAPAN": r"(?i)handjob[-_]?japan[-_]?(\d+)",
        "SPERMMANIA": r"(?i)sperm[-_]?mania[-_]?(\d+)",
        "URALESBIAN": r"(?i)ura[-_]?lesbian[-_]?(\d+)",
        "URABUKKAKE": r"(?i)ura[-_]?bukkake[-_]?(\d+)",
        "COSPURI": r"(?i)cospuri[-_]?(\d+)",
        "ROSELIP": r"(?i)roselip[-_]?(\d+)",
        "ROSELIPFETISH": r"(?i)roselip[-_]?(?:fetish[-_]?)?(\d+)",
        "GACHI": r"(?i)gachi(?:nco)?[-_]?(\d+)",
        "JAPORNXXX": r"(?i)japornxxx[-_]?(\d+)",
        "RHJ": r"(?i)RHJ[-_]?(\d+)",
    }
    if u in brands:
        for m in re.finditer(brands[u], blob):
            n = int(m.group(1))
            consider(f"{u}-{n}", n)

    return best


def main() -> None:
    doc = store.load_catalog(force=True)
    prefs = doc["regions"]["japan_uncensored"]["prefixes"]
    miss = sorted(p for p, e in prefs.items() if not e.get("latest_code"))
    print(f"miss {len(miss)} → local-db then delete", flush=True)
    recovered: list[tuple[str, str]] = []
    deleted: list[str] = []

    for i, pref in enumerate(miss, 1):
        needles = ALIASES.get(pref, [pref])
        print(f"[{i}/{len(miss)}] {pref} needles={needles[:3]}", flush=True)
        texts = sehua_texts(needles) + bitmagnet_texts(needles)
        blob = "\n".join(texts)
        print(f"  hits_text={len(texts)} chars={len(blob)}", flush=True)
        code = pick_latest(pref, blob) if blob else ""
        if code:
            ent = prefs.get(pref) or {}
            pe = store._normalize_prefix_entry(
                pref,
                {
                    **ent,
                    "latest_code": code,
                    "status": "active",
                    "integrity": "local_db_latest",
                    "sources": sorted(set(list(ent.get("sources") or []) + ["local-db"])),
                    "verified_at": store._now(),
                    "notes": (str(ent.get("notes") or "") + " · 本地库确认").strip(" ·"),
                },
            )
            pe["latest_code"] = code
            prefs[pref] = pe
            recovered.append((pref, code))
            print(f"  OK {code}", flush=True)
        else:
            del prefs[pref]
            deleted.append(pref)
            print("  DELETE", flush=True)

    store.save_catalog(doc)
    # also prune from seed if present
    try:
        import json

        seed = json.loads(store.SEED_PATH.read_text(encoding="utf-8"))
        sp = seed["regions"]["japan_uncensored"]["prefixes"]
        for p in deleted:
            sp.pop(p, None)
        store.SEED_PATH.write_text(
            json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("seed pruned", len(deleted), flush=True)
    except Exception as e:  # noqa: BLE001
        print("seed prune skip", e, flush=True)

    print(f"\nrecovered={len(recovered)} deleted={len(deleted)}", flush=True)
    for p, c in recovered:
        print(f"  {p}: {c}")
    print("deleted:", ", ".join(deleted))
    s = store.public_summary(doc)
    u = next(r for r in s["regions"] if r["id"] == "japan_uncensored")
    print(f"日本无码: {u['prefix_count']} 前缀 · {u['code_count']} 番号", flush=True)


if __name__ == "__main__":
    main()
