# -*- coding: utf-8 -*-
"""国产区 e2e：写入 scrap-library/国产无码/<厂牌>/<番号>/。"""
from __future__ import annotations

import argparse
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

REGION = "国产无码"

CASES: list[tuple[str, str, str]] = [
    ("MD", "MD-0020", "MD"),
    ("MD", "MD-0021", "MD"),
    ("MSD", "MSD-005", "MSD"),
    ("MSD", "MSD-002", "MSD"),
    ("PMC", "PMC-002", "PMC"),
    ("PMC", "PMC-001", "PMC"),
    ("91CM", "91CM-013", "91CM"),
    ("91CM", "91CM-065", "91CM"),
    ("EMX", "EMX-001", "EMX"),
    ("EMX", "EMX-009", "EMX"),
    ("GDCM", "GDCM-002", "GDCM"),
    ("DOM", "DOM-001", "DOM"),
]


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
    actors = sum(
        1
        for a in root.findall("actor")
        if str(a.findtext("name") or "").strip()
    )
    out.update({"title": title[:60], "studio": studio[:40], "actors": actors})
    body = title
    for pref in (uid, path.stem):
        p = str(pref or "").strip()
        if p and body.upper().startswith(p.upper()):
            body = body[len(p) :].strip(" -_")
    out["ok"] = bool(title) and bool(uid) and len(body) >= 2 and out["bytes"] >= 200
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    wanted = {s.strip().upper() for s in args.only.split(",") if s.strip()}
    cases = [c for c in CASES if not wanted or c[0] in wanted]

    from app.scrap_library import embed as embed_svc
    from app.scrap_library.enrich import enrich_one_row
    from app.scrap_library.enrich_strategy import get_strategy

    chain = (get_strategy().get("regionSources") or {}).get("china")
    root = embed_svc.resolve_root(embed_svc.get_settings().get("root"))
    print(f"chain={chain}")
    print(f"root={root}")
    print(f"cases={len(cases)} → {REGION}/<厂牌>/<番号>/")
    print("-" * 88)

    ok_n = fail_n = 0
    rows: list[str] = []
    by: dict[str, list[str]] = {}
    for pref, code, maker in cases:
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
            by.setdefault(pref, []).append(status)
            hits = [
                str(t.get("id"))
                for t in (res.get("sourceTimings") or [])
                if isinstance(t, dict) and t.get("ok")
            ]
            line = (
                f"{status:4} {pref:6} {code:14} {ms:5}ms  "
                f"nfo={nfo['ok']} poster={poster['ok']}"
                f"({poster['bytes']}b {poster['w']}x{poster['h']} "
                f"land={poster.get('landscape')}) "
                f"src={res.get('coverSource') or '-'} hits={hits}"
            )
            print(line, flush=True)
            if nfo.get("title"):
                print(f"     title={nfo['title']}  studio={nfo['studio']}", flush=True)
            if not all_ok:
                print(f"     err={res.get('error') or res.get('coverFail') or ''}", flush=True)
            rows.append(line)
        except Exception as e:  # noqa: BLE001
            fail_n += 1
            by.setdefault(pref, []).append("FAIL")
            ms = int((time.perf_counter() - t0) * 1000)
            print(f"FAIL {pref:6} {code:14} {ms:5}ms  EXC {type(e).__name__}: {e}", flush=True)

    print("-" * 88)
    print(f"TOTAL ok={ok_n} fail={fail_n} / {len(cases)}")
    full = [p for p, rs in by.items() if rs.count("OK") == len(rs) and rs]
    partial = [p for p, rs in by.items() if 0 < rs.count("OK") < len(rs)]
    miss = [p for p, rs in by.items() if rs.count("OK") == 0]
    print(f"full_ok={full}")
    print(f"partial={partial}")
    print(f"miss={miss}")
    out = API_ROOT / "_gap_reports" / "e2e_china_write.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(
            rows
            + [
                f"TOTAL ok={ok_n} fail={fail_n} / {len(cases)}",
                f"chain={chain}",
                f"full_ok={full}",
                f"partial={partial}",
                f"miss={miss}",
            ]
        ),
        encoding="utf-8",
    )
    print(f"report={out}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
