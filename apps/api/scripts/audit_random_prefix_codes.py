# -*- coding: utf-8 -*-
"""七区随机抽样审核：前缀↔番号格式 + 双库存在性（按前缀批量查）。"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import bitmagnet_pg  # noqa: E402
from app import pg  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app.core.region_meta import REGION_ORDER, std_prefix  # noqa: E402
from app.search.av import resolve_maker_shape  # noqa: E402

OUT = ROOT / "data" / "debug" / "prefix-random-sample-audit.json"
DIGIT_HEAD_RE = re.compile(r"^(\d{2,3})([A-Z]{2,14})$")
SEED = 20260906
PREFIXES_PER_REGION = 10
CODES_PER_PREFIX = 5


def clean_prefix(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", std_prefix(raw).replace("-", ""))


def codes_of(ent: dict) -> list[str]:
    return [str(c).strip().upper() for c in (ent.get("codes") or []) if str(c).strip()]


def code_matches_prefix(prefix: str, code: str) -> tuple[bool, str]:
    pref = clean_prefix(prefix)
    c = code.strip().upper()
    if not c:
        return False, "empty_code"
    shape = resolve_maker_shape(pref)

    if shape in {"fc2", "fc2ppv"}:
        if re.fullmatch(r"FC2(?:-PPV)?-\d{5,8}", c):
            return True, "fc2"
        return False, "fc2_shape_mismatch"

    if shape == "date6":
        if re.search(r"\d{6}", c):
            return True, "date6"
        return False, "date6_mismatch"

    if shape in {"western_date", "western_ep", "alnum_id"}:
        core = pref[: min(6, len(pref))]
        compact = re.sub(r"[^A-Z0-9]", "", c)
        if core and core in compact:
            return True, shape
        if re.search(r"[A-Z0-9].*\d", c):
            return True, f"{shape}_loose"
        return False, f"{shape}_mismatch"

    dm = DIGIT_HEAD_RE.match(pref)
    if dm:
        letter = dm.group(2)
        if re.fullmatch(rf"(?:{re.escape(pref)}|{re.escape(letter)})-\d{{2,6}}", c):
            return True, "digit_head_ok"
        return False, "digit_head_mismatch"

    if re.fullmatch(rf"{re.escape(pref)}-\d{{2,6}}", c):
        m = re.search(r"-(\d+)$", c)
        n = int(m.group(1)) if m else 0
        if 1990 <= n <= 2035 and pref not in {"HEYZO", "KIN8", "XXXAV", "NYOSHIN"}:
            return False, "year_as_serial"
        return True, "std_ok"

    if re.fullmatch(rf"\d{{2,3}}{re.escape(pref)}-\d{{2,6}}", c):
        return True, "std_with_digit_head_on_code"

    return False, "std_mismatch"


def _needles_for_code(code: str) -> list[str]:
    out = [code, code.replace("-", "")]
    if code.startswith("FC2"):
        out.append(code.replace("-", " "))
        out.append(code.replace("-", "_"))
    # dedupe preserve order
    seen = set()
    uniq = []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def db_hits_batch(codes: list[str]) -> dict[str, dict]:
    """一次查出一批番号是否在双库出现。"""
    result = {c: {"sehua": False, "bit": False, "example": ""} for c in codes}
    if not codes:
        return result

    needles: list[str] = []
    code_of_needle: dict[str, str] = {}
    for c in codes:
        for n in _needles_for_code(c):
            needles.append(n)
            code_of_needle[n.upper()] = c

    # Sehua filename
    try:
        rows = pg.query(
            """
            SELECT filename AS t FROM ed2k_resources
            WHERE filename ILIKE ANY(%s)
            LIMIT 80
            """,
            [[f"%{n}%" for n in needles]],
        )
        for r in rows:
            blob = str(r.get("t") or "").upper()
            for n, c in code_of_needle.items():
                if n in blob.replace("-", "").replace("_", " ") or n in blob:
                    result[c]["sehua"] = True
                    if not result[c]["example"]:
                        result[c]["example"] = str(r.get("t") or "")[:120]
    except Exception as e:  # noqa: BLE001
        print(f"  sehua batch warn: {e}", flush=True)
        # fallback per-code filename only
        for c in codes:
            for n in _needles_for_code(c):
                rows = pg.query(
                    "SELECT filename AS t FROM ed2k_resources WHERE filename ILIKE %s LIMIT 1",
                    [f"%{n}%"],
                )
                if rows:
                    result[c]["sehua"] = True
                    result[c]["example"] = str(rows[0].get("t") or "")[:120]
                    break

    missing = [c for c in codes if not result[c]["sehua"]]
    if missing:
        miss_needles = []
        miss_map = {}
        for c in missing:
            for n in _needles_for_code(c):
                miss_needles.append(n)
                miss_map[n.upper()] = c
        try:
            brows = bitmagnet_pg.query(
                """
                SELECT name AS t FROM torrents
                WHERE name ILIKE ANY(%s)
                LIMIT 80
                """,
                [[f"%{n}%" for n in miss_needles]],
            )
            for r in brows:
                blob = str(r.get("t") or "").upper()
                for n, c in miss_map.items():
                    if n in blob.replace("-", "").replace("_", " ") or n in blob:
                        result[c]["bit"] = True
                        if not result[c]["example"]:
                            result[c]["example"] = str(r.get("t") or "")[:120]
        except Exception as e:  # noqa: BLE001
            print(f"  bit batch warn: {e}", flush=True)
            for c in missing:
                for n in _needles_for_code(c):
                    try:
                        rows = bitmagnet_pg.query(
                            "SELECT name AS t FROM torrents WHERE name ILIKE %s LIMIT 1",
                            [f"%{n}%"],
                        )
                    except Exception:
                        rows = []
                    if rows:
                        result[c]["bit"] = True
                        result[c]["example"] = str(rows[0].get("t") or "")[:120]
                        break

    return result


def sample_list(items: list, k: int, rng: random.Random) -> list:
    if not items:
        return []
    if len(items) <= k:
        return list(items)
    return rng.sample(items, k)


def full_format_sweep(doc: dict) -> dict:
    """全量格式扫一遍（快），按区汇总坏例。"""
    out = {}
    for rid in REGION_ORDER:
        bad = []
        ok_n = bad_n = 0
        for p, e in (doc["regions"][rid].get("prefixes") or {}).items():
            for c in codes_of(e):
                good, reason = code_matches_prefix(p, c)
                if good:
                    ok_n += 1
                else:
                    bad_n += 1
                    if len(bad) < 15:
                        bad.append({"prefix": p, "code": c, "reason": reason})
        out[rid] = {
            "ok": ok_n,
            "bad": bad_n,
            "rate": round(ok_n / max(ok_n + bad_n, 1), 4),
            "bad_examples": bad,
        }
    return out


def main() -> None:
    rng = random.Random(SEED)
    doc = store.load_catalog(force=True)

    print("full format sweep…", flush=True)
    format_sweep = full_format_sweep(doc)
    for rid, st in format_sweep.items():
        print(
            f"  sweep {rid:16} ok={st['ok']} bad={st['bad']} ({st['rate']:.1%})",
            flush=True,
        )

    by_region: dict = {}
    totals = {
        "prefixes_sampled": 0,
        "codes_checked": 0,
        "format_ok": 0,
        "format_bad": 0,
        "db_ok": 0,
        "db_miss": 0,
    }
    format_bad_examples = []
    db_miss_examples = []

    print("random sample + db…", flush=True)
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        nonempty = [(p, e) for p, e in prefs.items() if codes_of(e)]
        empty = [p for p, e in prefs.items() if not codes_of(e)]
        picked = sample_list(nonempty, PREFIXES_PER_REGION, rng)

        region_rows = []
        reg_stats = {
            "prefix_total": len(prefs),
            "with_codes": len(nonempty),
            "empty": len(empty),
            "empty_sample": sample_list(empty, min(3, len(empty)), rng),
            "sampled_prefixes": 0,
            "codes_checked": 0,
            "format_ok": 0,
            "format_bad": 0,
            "db_ok": 0,
            "db_miss": 0,
        }

        for prefix, ent in sorted(picked, key=lambda x: x[0]):
            codes = codes_of(ent)
            picked_codes = sample_list(codes, CODES_PER_PREFIX, rng)
            fmt_rows = []
            ok_codes = []
            for code in picked_codes:
                ok, reason = code_matches_prefix(prefix, code)
                reg_stats["codes_checked"] += 1
                totals["codes_checked"] += 1
                if ok:
                    reg_stats["format_ok"] += 1
                    totals["format_ok"] += 1
                    ok_codes.append(code)
                else:
                    reg_stats["format_bad"] += 1
                    totals["format_bad"] += 1
                    if len(format_bad_examples) < 50:
                        format_bad_examples.append(
                            {
                                "region": rid,
                                "prefix": prefix,
                                "code": code,
                                "reason": reason,
                            }
                        )
                fmt_rows.append(
                    {"code": code, "format_ok": ok, "format_reason": reason}
                )

            hits = db_hits_batch(ok_codes)
            for row in fmt_rows:
                c = row["code"]
                if not row["format_ok"]:
                    row.update(
                        {"in_sehua": False, "in_bitmagnet": False, "example": ""}
                    )
                    continue
                h = hits.get(c) or {}
                sehua = bool(h.get("sehua"))
                bit = bool(h.get("bit"))
                row["in_sehua"] = sehua
                row["in_bitmagnet"] = bit
                row["example"] = h.get("example") or ""
                if sehua or bit:
                    reg_stats["db_ok"] += 1
                    totals["db_ok"] += 1
                else:
                    reg_stats["db_miss"] += 1
                    totals["db_miss"] += 1
                    if len(db_miss_examples) < 50:
                        db_miss_examples.append(
                            {"region": rid, "prefix": prefix, "code": c}
                        )

            region_rows.append(
                {
                    "prefix": prefix,
                    "maker": ent.get("maker") or "",
                    "code_count": len(codes),
                    "shape": resolve_maker_shape(clean_prefix(prefix)),
                    "sample_codes": [x["code"] for x in fmt_rows],
                    "format_ok": all(x["format_ok"] for x in fmt_rows),
                    "db_ok": all(
                        (x.get("in_sehua") or x.get("in_bitmagnet"))
                        for x in fmt_rows
                        if x["format_ok"]
                    ),
                    "details": fmt_rows,
                }
            )
            reg_stats["sampled_prefixes"] += 1
            totals["prefixes_sampled"] += 1
            print(f"  {rid:16} {prefix}", flush=True)

        by_region[rid] = {"stats": reg_stats, "samples": region_rows}
        print(
            f"{rid:16} sample={reg_stats['sampled_prefixes']:2} "
            f"codes={reg_stats['codes_checked']:3} "
            f"fmt={reg_stats['format_ok']}/{reg_stats['codes_checked']} "
            f"db={reg_stats['db_ok']}/{reg_stats['format_ok']}",
            flush=True,
        )

    report = {
        "seed": SEED,
        "policy": {
            "prefixes_per_region": PREFIXES_PER_REGION,
            "codes_per_prefix": CODES_PER_PREFIX,
            "checks": [
                "full_format_sweep",
                "random_format",
                "random_db_batch_exists",
            ],
        },
        "format_sweep": format_sweep,
        "totals": totals,
        "format_ok_rate": round(
            totals["format_ok"] / max(totals["codes_checked"], 1), 4
        ),
        "db_ok_rate_among_format_ok": round(
            totals["db_ok"] / max(totals["format_ok"], 1), 4
        ),
        "format_bad_examples": format_bad_examples,
        "db_miss_examples": db_miss_examples,
        "by_region": by_region,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("—", flush=True)
    print(
        f"SAMPLE codes={totals['codes_checked']} "
        f"format_ok={totals['format_ok']} ({report['format_ok_rate']:.1%}) "
        f"db_ok={totals['db_ok']} ({report['db_ok_rate_among_format_ok']:.1%} of format_ok)",
        flush=True,
    )
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
