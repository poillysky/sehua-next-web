# -*- coding: utf-8 -*-
"""素人区随机抽测：看各数据源命中/封面贡献。"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT))

REGION = "日本素人"
RNG = random.Random(20260918)

# (label, code, maker_folder) — round3：新链冒烟随机组
CASES: list[tuple[str, str, str]] = [
    ("SIRO", "SIRO-3408", "SIRO"),
    ("SIRO", "SIRO-3258", "SIRO"),
    ("LUXU", "LUXU-1217", "LUXU"),
    ("LUXU", "LUXU-0592", "LUXU"),
    ("MAAN", "MAAN-602", "MAAN"),
    ("MAAN", "MAAN-611", "MAAN"),
    ("MIUM", "MIUM-651", "MIUM"),
    ("MIUM", "MIUM-534", "MIUM"),
    ("GANA", "GANA-2319", "GANA"),
    ("GANA", "GANA-2261", "GANA"),
    ("ARA", "ARA-484", "ARA"),
    ("ARA", "ARA-427", "ARA"),
    ("SCUTE", "SCUTE-1127", "SCUTE"),
    ("SCUTE", "SCUTE-1054", "SCUTE"),
    ("SQTE", "SQTE-628", "SQTE"),
    ("SQTE", "SQTE-406", "SQTE"),
    ("DCV", "DCV-251", "DCV"),
    ("DCV", "DCV-187", "DCV"),
    ("NTK", "NTK-390", "NTK"),
    ("NTK", "NTK-292", "NTK"),
]


def main() -> int:
    from app.scrap_library import embed as embed_svc
    from app.scrap_library.enrich import enrich_one_row
    from app.scrap_library.enrich_strategy import get_strategy
    from PIL import Image

    chain = (get_strategy().get("regionSources") or {}).get("japan_amateur") or []
    root = embed_svc.resolve_root(embed_svc.get_settings().get("root"))
    print(f"chain={chain}")
    print(f"cases={len(CASES)}")
    print("-" * 96)

    src_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"hit": 0, "miss": 0, "fail": 0, "poster": 0, "ms_sum": 0, "ms_n": 0}
    )
    field_wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cover_wins: dict[str, int] = defaultdict(int)
    ok_n = fail_n = 0
    rows: list[str] = []

    for pref, code, maker in CASES:
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
        except Exception as e:  # noqa: BLE001
            fail_n += 1
            line = f"FAIL {pref:6} {code:14} EXC {type(e).__name__}: {e}"
            print(line)
            rows.append(line)
            continue
        ms = int((time.perf_counter() - t0) * 1000)

        # source timings from result or sidecar
        timings = list(res.get("sourceTimings") or [])
        if not timings:
            logp = folder / f"{code}.log"
            if logp.is_file():
                try:
                    sidecar = json.loads(logp.read_text(encoding="utf-8"))
                    timings = list(sidecar.get("sourceTimings") or [])
                    if not res.get("coverSource"):
                        res["coverSource"] = sidecar.get("coverSource") or ""
                    if not res.get("fieldSources"):
                        res["fieldSources"] = sidecar.get("fields")  # may differ
                except Exception:  # noqa: BLE001
                    pass

        for t in timings:
            if not isinstance(t, dict):
                continue
            sid = str(t.get("id") or "").strip() or "?"
            st = src_stats[sid]
            err = str(t.get("error") or "")
            if t.get("ok"):
                st["hit"] += 1
            elif any(x in err for x in ("未找到", "搜索无结果", "番号格式")):
                st["miss"] += 1
            else:
                st["fail"] += 1
            if t.get("poster"):
                st["poster"] += 1
            try:
                st["ms_sum"] += int(t.get("ms") or 0)
                st["ms_n"] += 1
            except Exception:  # noqa: BLE001
                pass

        fs = res.get("fieldSources") if isinstance(res.get("fieldSources"), dict) else {}
        if not fs:
            # from sidecar fields list
            logp = folder / f"{code}.log"
            if logp.is_file():
                try:
                    sidecar = json.loads(logp.read_text(encoding="utf-8"))
                    for f in sidecar.get("fields") or []:
                        if isinstance(f, dict) and f.get("source") and f.get("id"):
                            field_wins[str(f["id"])][str(f["source"])] += 1
                except Exception:  # noqa: BLE001
                    pass
        else:
            for fid, sid in fs.items():
                if sid:
                    field_wins[str(fid)][str(sid)] += 1

        poster = folder / "poster.jpg"
        poster_ok = False
        pw = ph = 0
        pb = 0
        if poster.is_file():
            pb = poster.stat().st_size
            try:
                with Image.open(poster) as im:
                    pw, ph = im.size
                poster_ok = pb >= 256 and pw >= 32 and ph >= 32
            except Exception:  # noqa: BLE001
                poster_ok = False

        csrc = str(res.get("coverSource") or "").strip()
        # infer from log line / attempts
        if not csrc and poster_ok:
            logp = folder / f"{code}.log"
            if logp.is_file():
                txt = logp.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"cover\.commit · source=([^\s·]+)", txt)
                if m:
                    csrc = m.group(1)
                else:
                    # NFO cover host heuristic
                    nfo = folder / f"{code}.nfo"
                    if nfo.is_file():
                        nt = nfo.read_text(encoding="utf-8", errors="replace")
                        if "image.mgstage.com" in nt:
                            csrc = "mgstage"
                        elif "fourhoi.com" in nt:
                            csrc = "miss_av"
                        elif "jav321.com" in nt:
                            csrc = "jav321"
                        elif "javbus" in nt or "seejav" in nt:
                            csrc = "javbus"
        if poster_ok and csrc:
            cover_wins[csrc] += 1
        elif poster_ok:
            cover_wins["(unknown)"] += 1

        enrich_ok = bool(res.get("ok")) and poster_ok
        status = "OK" if enrich_ok else "FAIL"
        if enrich_ok:
            ok_n += 1
        else:
            fail_n += 1
        hits = [
            str(t.get("id"))
            for t in timings
            if isinstance(t, dict) and t.get("ok")
        ]
        line = (
            f"{status:4} {pref:6} {code:14} {ms:5}ms  "
            f"poster={poster_ok}({pb}b {pw}x{ph}) coverSrc={csrc or '-'}  "
            f"hits={hits}"
        )
        print(line)
        if not enrich_ok:
            print(f"     err={res.get('error') or res.get('coverFail') or ''}")
        rows.append(line)

    print("-" * 96)
    print(f"TOTAL ok={ok_n} fail={fail_n} / {len(CASES)}")
    print()
    print("=== 源命中（详情 scrape）===")
    print(f"{'source':12} {'hit':>4} {'miss':>5} {'fail':>5} {'poster':>6} {'avgMs':>7}")
    for sid in chain:
        st = src_stats.get(sid) or {}
        n = int(st.get("ms_n") or 0)
        avg = int(st.get("ms_sum") or 0) // n if n else 0
        print(
            f"{sid:12} {int(st.get('hit') or 0):4} {int(st.get('miss') or 0):5} "
            f"{int(st.get('fail') or 0):5} {int(st.get('poster') or 0):6} {avg:7}"
        )
    # any extra
    for sid, st in sorted(src_stats.items()):
        if sid in chain:
            continue
        n = int(st.get("ms_n") or 0)
        avg = int(st.get("ms_sum") or 0) // n if n else 0
        print(
            f"{sid:12} {int(st.get('hit') or 0):4} {int(st.get('miss') or 0):5} "
            f"{int(st.get('fail') or 0):5} {int(st.get('poster') or 0):6} {avg:7}"
        )

    print()
    print("=== 字段定稿源（有贡献次数）===")
    for fid in ("title", "overview", "actors", "studio", "poster", "tags"):
        wins = field_wins.get(fid) or {}
        if not wins:
            continue
        top = sorted(wins.items(), key=lambda x: -x[1])
        print(f"  {fid:10} " + ", ".join(f"{s}={n}" for s, n in top[:6]))

    print()
    print("=== 封面实际落盘来源 coverSource ===")
    for s, n in sorted(cover_wins.items(), key=lambda x: -x[1]):
        print(f"  {s:16} {n}")

    out = API_ROOT / "_gap_reports" / "e2e_amateur_source_probe.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = [
        f"TOTAL ok={ok_n} fail={fail_n} / {len(CASES)}",
        f"chain={chain}",
        "cover_wins=" + json.dumps(dict(cover_wins), ensure_ascii=False),
        "src_stats="
        + json.dumps({k: dict(v) for k, v in src_stats.items()}, ensure_ascii=False),
    ]
    out.write_text("\n".join(rows + [""] + summary), encoding="utf-8")
    print(f"report={out}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
