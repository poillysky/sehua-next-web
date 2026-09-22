# -*- coding: utf-8 -*-
"""无码专用站 e2e：直接写入 scrap-library/日本无码/<厂牌>/<番号>/。

用法：
  .venv\\Scripts\\python.exe scripts/_e2e_uncensored_official_write.py --group=1
  .venv\\Scripts\\python.exe scripts/_e2e_uncensored_official_write.py --group=2
  .venv\\Scripts\\python.exe scripts/_e2e_uncensored_official_write.py --group=3
  .venv\\Scripts\\python.exe scripts/_e2e_uncensored_official_write.py --only=heyzo,kin8
"""
from __future__ import annotations

import argparse
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

# 每前缀 2 个番号
CASES: list[tuple[str, str, str]] = [
    # (source_id, code, maker_folder)
    ("heyzo", "HEYZO-2034", "HEYZO"),
    ("heyzo", "HEYZO-1800", "HEYZO"),
    ("1pondo", "1PON-062014-830", "1PON"),
    ("1pondo", "1PON-010121-001", "1PON"),
    ("pacopacomama", "PACO-122615-557", "PACO"),
    ("pacopacomama", "PACO-010121-001", "PACO"),
    ("carib", "CARIB-010117-339", "CARIB"),
    ("carib", "CARIB-122216-001", "CARIB"),
    ("10musume", "10MU-122817-01", "10MUSUME"),
    ("10musume", "10MU-051124-01", "10MUSUME"),
    ("kin8", "KIN8-3500", "KIN8"),
    ("kin8", "KIN8-3400", "KIN8"),
    ("h0930", "H0930-ki260908", "H0930"),
    ("h0930", "H0930-ori1224", "H0930"),
    ("h4610", "H4610-ki260908", "H4610"),
    ("h4610", "H4610-ki250101", "H4610"),
    ("c0930", "C0930-hitozuma1369", "C0930"),
    ("c0930", "C0930-hitozuma1300", "C0930"),
    ("tokyohot", "TOKYOHOT-N1234", "TOKYOHOT"),
    ("tokyohot", "TOKYOHOT-N1200", "TOKYOHOT"),
    ("nyoshin", "NYOSHIN-2500", "NYOSHIN"),
    ("nyoshin", "NYOSHIN-2400", "NYOSHIN"),
    ("heydouga", "HEYDOUGA-4030-001", "HEYDOUGA"),
    ("heydouga", "HEYDOUGA-4223-001", "HEYDOUGA"),
]

GROUP_SIZE = 5
REGION = "日本无码"


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
    out["ok"] = out["bytes"] >= 8_000 and out["w"] >= 200 and out["h"] >= 200
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
        "plot": False,
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
    plot = (root.findtext("plot") or root.findtext("outline") or "").strip()
    out.update(
        {
            "title": title[:60],
            "studio": studio[:40],
            "actors": actors,
            "uniqueid": uid,
            "plot": len(plot) >= 8,
        }
    )
    body = title
    for pref in (uid, path.stem):
        p = str(pref or "").strip()
        if p and body.upper().startswith(p.upper()):
            body = body[len(p) :].strip(" -_")
    title_ok = len(body) >= 2
    out["ok"] = bool(title) and bool(uid) and title_ok and out["bytes"] >= 200
    out["title_ok"] = title_ok
    return out


def _select_cases(*, group: int, only: str) -> list[tuple[str, str, str]]:
    wanted = {s.strip() for s in only.split(",") if s.strip()}
    if wanted:
        return [c for c in CASES if c[0] in wanted]
    if group <= 0:
        return list(CASES)
    start = (group - 1) * GROUP_SIZE
    end = start + GROUP_SIZE
    return CASES[start:end]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--group",
        type=int,
        default=0,
        help="第几组（每组 5 个，从 1 起；0=全部）",
    )
    ap.add_argument("--only", default="", help="只测这些源，逗号分隔")
    args = ap.parse_args()

    from app.scrap_library import embed as embed_svc
    from app.scrap_library.enrich import enrich_one_row

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    cases = _select_cases(group=int(args.group or 0), only=str(args.only or ""))
    if not cases:
        print("no cases")
        return 1

    n_groups = (len(CASES) + GROUP_SIZE - 1) // GROUP_SIZE
    label = f"group={args.group}/{n_groups}" if args.group else "all"
    print(f"root={root}")
    print(f"{label} cases={len(cases)} → {REGION}/<厂牌>/<番号>/")
    print("-" * 88)

    ok_n = fail_n = 0
    rows: list[str] = []
    for sid, code, maker in cases:
        # 直接主目录：日本无码/HEYZO/HEYZO-2034/
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
                f"{status:4} {sid:12} {code:22} {ms:5}ms  "
                f"enrich={enrich_ok} nfo={nfo['ok']}({nfo['bytes']}b "
                f"actors={nfo['actors']})  "
                f"poster={poster['ok']}({poster['bytes']}b "
                f"{poster['w']}x{poster['h']} land={poster.get('landscape')})  "
                f"path={maker}/{code}"
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
            print(f"FAIL {sid:12} {code:22} {ms:5}ms  EXC {type(e).__name__}: {e}")

    print("-" * 88)
    print(f"TOTAL ok={ok_n} fail={fail_n} / {len(cases)}")
    out_path = API_ROOT / "_gap_reports" / "e2e_uncensored_official_write.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(rows + [f"TOTAL ok={ok_n} fail={fail_n} / {len(cases)}"]),
        encoding="utf-8",
    )
    print(f"report={out_path}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
