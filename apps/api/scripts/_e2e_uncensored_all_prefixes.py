# -*- coding: utf-8 -*-
"""无码全部前缀 e2e：每个逻辑前缀抽 2 个番号，走 enrich 写盘。

覆盖 catalog.seed japan_uncensored 去重后前缀 + TOKYOHOT（≈26）。
有专用站的走官网；其余走无码兜底链。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

REGION = "日本无码"

# 逻辑前缀（别名归并后 + TOKYOHOT）
LOGICAL_PREFIXES: list[tuple[str, tuple[str, ...], str]] = [
    # (logical_id, match_prefixes, maker_folder)
    ("10MU", ("10MU", "10MUSUME"), "10MUSUME"),
    ("1PON", ("1PON", "1PONDO"), "1PON"),
    ("C0930", ("C0930",), "C0930"),
    ("CARIB", ("CARIB", "CARIBPR"), "CARIB"),
    ("CWPBD", ("CWPBD",), "CWPBD"),
    ("FELLATIOJAPAN", ("FELLATIOJAPAN",), "FELLATIOJAPAN"),
    ("H0930", ("H0930",), "H0930"),
    ("H4610", ("H4610",), "H4610"),
    ("HANDJOBJAPAN", ("HANDJOBJAPAN",), "HANDJOBJAPAN"),
    ("HEYDOUGA", ("HEYDOUGA",), "HEYDOUGA"),
    ("HEYZO", ("HEYZO",), "HEYZO"),
    ("JAPORNXXX", ("JAPORNXXX",), "JAPORNXXX"),
    ("KIN8", ("KIN8", "KIN8TENGOKU"), "KIN8"),
    ("LAFBD", ("LAFBD",), "LAFBD"),
    ("LEGSJAPAN", ("LEGSJAPAN",), "LEGSJAPAN"),
    ("NYOSHIN", ("NYOSHIN",), "NYOSHIN"),
    ("PACO", ("PACO", "PACOMA"), "PACO"),
    ("RHJ", ("RHJ",), "RHJ"),
    ("ROSELIP", ("ROSELIP", "ROSELIPFETISH"), "ROSELIP"),
    ("SMD", ("SMD",), "SMD"),
    ("SMMIRACLE", ("SMMIRACLE",), "SMMIRACLE"),
    ("SPERMMANIA", ("SPERMMANIA",), "SPERMMANIA"),
    ("TOKYOHOT", ("TOKYOHOT", "TOKYO-HOT", "TOKYO"), "TOKYOHOT"),
    ("URABUKKAKE", ("URABUKKAKE",), "URABUKKAKE"),
    ("URALESBIAN", ("URALESBIAN",), "URALESBIAN"),
    ("XXXAV", ("XXXAV", "XXX-AV"), "XXXAV"),
]

# 已知可用兜底样例（库里没有时用）
FALLBACK_SAMPLES: dict[str, list[str]] = {
    "10MU": ["10MU-122817-01", "10MU-051124-01"],
    "1PON": ["1PON-062014-830", "1PON-010121-001"],
    "C0930": ["C0930-hitozuma1369", "C0930-hitozuma1300"],
    "CARIB": ["CARIB-010117-339", "CARIB-122216-001"],
    "H0930": ["H0930-ki260908", "H0930-ori1224"],
    "H4610": ["H4610-ki260908", "H4610-ki250101"],
    "HEYDOUGA": ["HEYDOUGA-4030-001", "HEYDOUGA-4223-001"],
    "HEYZO": ["HEYZO-2034", "HEYZO-1800"],
    "KIN8": ["KIN8-3500", "KIN8-3400"],
    "NYOSHIN": ["NYOSHIN-2500", "NYOSHIN-2400"],
    "PACO": ["PACO-122615-557", "PACO-010121-001"],
    "TOKYOHOT": ["TOKYOHOT-N1234", "TOKYOHOT-N1200"],
}


def _norm(code: str) -> str:
    return str(code or "").strip().upper().replace("_", "-")


def _match_logical(code: str) -> str | None:
    cu = _norm(code)
    # TOKYOHOT before generic TOKYO; HEYDOUGA before HEYZO
    ordered = sorted(LOGICAL_PREFIXES, key=lambda x: -max(len(p) for p in x[1]))
    for lid, prefs, _ in ordered:
        for p in prefs:
            if cu.startswith(p + "-") or cu == p:
                # avoid TOKYO matching non-hot if we used TOKYO alone — require HOT or N/K digit
                if lid == "TOKYOHOT":
                    if cu.startswith("TOKYOHOT") or cu.startswith("TOKYO-HOT"):
                        return lid
                    if re.match(r"^TOKYO-?[NK]?\d", cu):
                        return lid
                    continue
                return lid
    return None


def _collect_pool() -> dict[str, list[str]]:
    pool: dict[str, list[str]] = defaultdict(list)

    def add(code: str) -> None:
        cu = _norm(code)
        if not cu or len(cu) < 4:
            return
        lid = _match_logical(cu)
        if not lid:
            return
        if cu not in pool[lid]:
            pool[lid].append(cu)

    # maps code-titles
    ct = Path(__file__).resolve().parents[2] / "maps" / "scrape" / "code-titles.json"
    if ct.is_file():
        try:
            data = json.loads(ct.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in data.keys():
                    if k in ("version", "updated", "meta"):
                        continue
                    add(str(k))
            elif isinstance(data, list):
                for row in data:
                    if isinstance(row, dict):
                        add(str(row.get("code") or ""))
                    else:
                        add(str(row))
        except Exception as e:  # noqa: BLE001
            print(f"warn code-titles: {e}")

    # seed / harvest tsv if any
    for rel in (
        "maps/_export/region-maker-prefix.compact.tsv",
        "api/scripts/_scrap_prefix_all.tsv",
    ):
        p = Path(__file__).resolve().parents[2] / rel.replace("api/", "")
        if not p.is_file():
            p = API_ROOT.parent / rel.split("/", 1)[-1] if False else p
        # try apps root
        p2 = API_ROOT.parent / rel
        for cand in (p, p2, API_ROOT / "_scrap_prefix_all.tsv"):
            if cand.is_file():
                try:
                    for line in cand.read_text(encoding="utf-8", errors="replace").splitlines()[:50000]:
                        for m in re.finditer(r"\b([A-Z0-9][A-Z0-9\-]{3,})\b", line.upper()):
                            add(m.group(1))
                except Exception:
                    pass

    # disk library
    from app.scrap_library import embed as embed_svc

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    unc = root / REGION
    if unc.is_dir():
        for maker in unc.iterdir():
            if not maker.is_dir():
                continue
            for code_dir in maker.iterdir():
                if code_dir.is_dir():
                    add(code_dir.name)

    # DB / vector if available
    try:
        from app.core.db import connect

        conn = connect()
        cur = conn.cursor()
        for sql in (
            "SELECT code FROM scrap_library_items LIMIT 200000",
            "SELECT code FROM code_titles LIMIT 200000",
            "SELECT code FROM embed_meta LIMIT 200000",
            "SELECT DISTINCT code FROM scrap_codes LIMIT 200000",
        ):
            try:
                cur.execute(sql)
                for (c,) in cur.fetchall():
                    add(str(c))
            except Exception:
                continue
    except Exception as e:  # noqa: BLE001
        print(f"warn db: {e}")

    # fallbacks
    for lid, codes in FALLBACK_SAMPLES.items():
        for c in codes:
            add(c)

    return pool


def _pick_two(pool: dict[str, list[str]], *, seed: int = 42) -> list[tuple[str, str, str]]:
    rng = random.Random(seed)
    cases: list[tuple[str, str, str]] = []
    for lid, _prefs, maker in LOGICAL_PREFIXES:
        got = list(pool.get(lid) or [])
        # prefer FALLBACK order first
        preferred = [c for c in FALLBACK_SAMPLES.get(lid, []) if c in got]
        rest = [c for c in got if c not in preferred]
        rng.shuffle(rest)
        ordered = preferred + rest
        take = ordered[:2]
        if len(take) < 2:
            # duplicate pad only if we have 1 — still test what we have
            pass
        for c in take:
            cases.append((lid, c, maker))
    return cases


def _poster_info(path: Path) -> dict:
    out: dict = {"exists": path.is_file(), "bytes": 0, "w": 0, "h": 0, "ok": False}
    if not path.is_file():
        return out
    out["bytes"] = path.stat().st_size
    try:
        from PIL import Image

        with Image.open(path) as im:
            out["w"], out["h"] = im.size
    except Exception as e:  # noqa: BLE001
        out["err"] = str(e)
        return out
    out["ok"] = out["bytes"] >= 256 and out["w"] >= 32 and out["h"] >= 32
    out["landscape"] = out["w"] >= out["h"] if out["w"] and out["h"] else False
    return out


def _nfo_info(path: Path) -> dict:
    out: dict = {
        "exists": path.is_file(),
        "bytes": 0,
        "ok": False,
        "title": "",
        "studio": "",
        "actors": 0,
        "uniqueid": "",
    }
    if not path.is_file():
        return out
    out["bytes"] = path.stat().st_size
    try:
        root = ET.parse(path).getroot()
    except Exception as e:  # noqa: BLE001
        out["err"] = f"xml:{e}"
        return out
    title = (root.findtext("title") or "").strip()
    studio = (root.findtext("studio") or "").strip()
    uid = (root.findtext("num") or "").strip()
    if not uid:
        for el in root.findall("uniqueid"):
            uid = (el.text or "").strip()
            if uid:
                break
    actors = 0
    for a in root.findall("actor"):
        nm = a.findtext("name") or "".join(a.itertext())
        if str(nm or "").strip():
            actors += 1
    out.update(
        {
            "title": title[:60],
            "studio": studio[:40],
            "actors": actors,
            "uniqueid": uid,
        }
    )
    body = title
    for pref in (uid, path.stem):
        p = str(pref or "").strip()
        if p and body.upper().startswith(p.upper()):
            body = body[len(p) :].strip(" -_")
    title_ok = len(body) >= 2
    out["ok"] = bool(title) and bool(uid) and title_ok and out["bytes"] >= 200
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=2, help="每前缀抽几个")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-pool", action="store_true", help="只打印抽样池")
    args = ap.parse_args()

    pool = _collect_pool()
    print(f"logical_prefixes={len(LOGICAL_PREFIXES)}")
    missing = []
    for lid, _, _ in LOGICAL_PREFIXES:
        n = len(pool.get(lid) or [])
        print(f"  {lid:16} pool={n}")
        if n < 1:
            missing.append(lid)
    if args.dry_pool:
        return 0 if not missing else 1

    cases = _pick_two(pool, seed=int(args.seed))
    # trim to --per
    by: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for row in cases:
        by[row[0]].append(row)
    cases = []
    for lid, _, maker in LOGICAL_PREFIXES:
        cases.extend(by[lid][: max(1, int(args.per))])

    print(f"cases={len(cases)} missing_pool={missing}")
    print("-" * 88)

    from app.scrap_library import embed as embed_svc
    from app.scrap_library.enrich import enrich_one_row

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))

    ok_n = fail_n = skip_n = 0
    rows: list[str] = []
    for lid, code, maker in cases:
        rel = f"{REGION}/{maker}/{code}"
        folder = root / rel
        folder.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        try:
            res = enrich_one_row(
                {
                    "code": code,
                    "rel_path": rel.replace("\\", "/"),
                    "region": REGION,
                    "gaps": ["no_local", "no_media"],
                },
                overwrite=True,
                sync_vector=False,
            )
            ms = int((time.perf_counter() - t0) * 1000)
            nfo = _nfo_info(folder / f"{code}.nfo")
            if not nfo["exists"]:
                alt = list(folder.glob("*.nfo"))
                if alt:
                    nfo = _nfo_info(alt[0])
            poster = _poster_info(folder / "poster.jpg")
            enrich_ok = bool(res.get("ok"))
            all_ok = enrich_ok and nfo["ok"] and poster["ok"]
            status = "OK" if all_ok else "FAIL"
            if all_ok:
                ok_n += 1
            else:
                fail_n += 1
            line = (
                f"{status:4} {lid:16} {code:28} {ms:5}ms  "
                f"enrich={enrich_ok} nfo={nfo['ok']}({nfo['bytes']}b "
                f"actors={nfo['actors']})  "
                f"poster={poster['ok']}({poster['bytes']}b "
                f"{poster['w']}x{poster['h']})"
            )
            print(line)
            if nfo.get("title"):
                print(f"     title={nfo['title']}  studio={nfo['studio']}")
            if not all_ok:
                err = res.get("error") or res.get("coverError") or ""
                print(f"     err={err}")
            rows.append(line)
        except Exception as e:  # noqa: BLE001
            fail_n += 1
            ms = int((time.perf_counter() - t0) * 1000)
            print(f"FAIL {lid:16} {code:28} {ms:5}ms  EXC {type(e).__name__}: {e}")

    print("-" * 88)
    print(f"TOTAL ok={ok_n} fail={fail_n} skip={skip_n} / {len(cases)}")
    if missing:
        print(f"NO_POOL (无法抽号): {', '.join(missing)}")
    out_path = API_ROOT / "_gap_reports" / "e2e_uncensored_all_prefixes.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(
            rows
            + [
                f"TOTAL ok={ok_n} fail={fail_n} / {len(cases)}",
                f"NO_POOL={missing}",
            ]
        ),
        encoding="utf-8",
    )
    print(f"report={out_path}")
    return 0 if fail_n == 0 and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
