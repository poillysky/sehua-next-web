# -*- coding: utf-8 -*-
"""对比 DMM aws / digital / mono 封面 URL 成功率，用于调整试下顺序。"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict

from app.core.db import get_meta_pool
from app.scrap_library import embed as embed_svc
from app.scrap_library.cover_scrape import probe_cover_bytes
from app.scrap_library.embed import _fetch_cover_bytes

CID_RE = re.compile(
    r"(?:pics\.dmm\.co\.jp|awsimgsrc\.dmm\.co\.jp/pics_dig)"
    r"/digital/video/([^/]+)/\1(?:p[sl])\.jpg",
    re.I,
)


def short_cid(cid: str) -> str:
    return re.sub(r"^([a-z]+)0+(\d+)$", r"\1\2", cid, flags=re.I)


def ok_bytes(data: bytes | None) -> tuple[bool, str]:
    if not data:
        return False, "fetch_fail"
    try:
        if embed_svc._is_blank_cover_bytes(data):  # noqa: SLF001
            return False, "blank"
    except Exception:
        pass
    p = probe_cover_bytes(data)
    w, h = int(p.get("width") or 0), int(p.get("height") or 0)
    se = int(p.get("shortEdge") or 0)
    if se < 160:
        return False, f"too_small:{w}x{h}"
    return True, f"{w}x{h}"


def try_url(url: str) -> dict:
    t0 = time.perf_counter()
    got = _fetch_cover_bytes(url)
    ms = int((time.perf_counter() - t0) * 1000)
    data = got[0] if got else None
    good, reason = ok_bytes(data)
    return {"ok": good, "reason": reason, "ms": ms, "url": url}


def main() -> None:
    embed_svc.ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT code, cover_url
            FROM {embed_svc.TABLE}
            WHERE coalesce(cover_url, '') <> ''
              AND (cover_url ILIKE '%dmm%' OR cover_url ILIKE '%awsimgsrc%')
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 25
            """
        )
        rows = [dict(r) for r in cur.fetchall()]

    stats: dict[str, dict] = defaultdict(lambda: {"ok": 0, "n": 0, "ms": []})
    per_code: list[dict] = []

    for row in rows:
        code = str(row.get("code") or "")
        cover = str(row.get("cover_url") or "")
        m = CID_RE.search(cover)
        if m:
            cid = m.group(1)
        else:
            m2 = re.search(r"/digital/video/([^/]+)/", cover, re.I)
            if not m2:
                print(f"skip {code}: no cid")
                continue
            cid = m2.group(1)
        sc = short_cid(cid)
        variants = [
            ("aws_ps", f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}ps.jpg"),
            ("aws_pl", f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}pl.jpg"),
            ("dig_ps", f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}ps.jpg"),
            ("dig_pl", f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}pl.jpg"),
            ("mono_s_ps", f"https://pics.dmm.co.jp/mono/movie/adult/{sc}/{sc}ps.jpg"),
            ("mono_f_ps", f"https://pics.dmm.co.jp/mono/movie/adult/{cid}/{cid}ps.jpg"),
            ("mono_s_pl", f"https://pics.dmm.co.jp/mono/movie/adult/{sc}/{sc}pl.jpg"),
            ("mono_f_pl", f"https://pics.dmm.co.jp/mono/movie/adult/{cid}/{cid}pl.jpg"),
        ]
        row_out: dict = {"code": code, "cid": cid, "results": {}, "first_ok": None}
        for name, url in variants:
            r = try_url(url)
            stats[name]["n"] += 1
            if r["ok"]:
                stats[name]["ok"] += 1
                stats[name]["ms"].append(r["ms"])
                if row_out["first_ok"] is None:
                    row_out["first_ok"] = name
            row_out["results"][name] = f"{r['ok']}:{r['reason']}:{r['ms']}ms"
            time.sleep(0.05)
        per_code.append(row_out)
        print(f"{code} cid={cid} first={row_out['first_ok']}")

    print("\n=== SUCCESS RATE ===")
    for name in [
        "aws_ps",
        "aws_pl",
        "dig_ps",
        "dig_pl",
        "mono_s_ps",
        "mono_f_ps",
        "mono_s_pl",
        "mono_f_pl",
    ]:
        s = stats[name]
        rate = (100.0 * s["ok"] / s["n"]) if s["n"] else 0.0
        avg = int(sum(s["ms"]) / len(s["ms"])) if s["ms"] else 0
        print(f"{name:10} {s['ok']:2}/{s['n']:2} = {rate:5.1f}%  avg_ok_ms={avg}")

    print("\n=== first_ok (loop order starts aws_ps) ===")
    for k, v in Counter(x["first_ok"] for x in per_code).most_common():
        print(k, v)

    def sim_order(order_names: list[str]) -> tuple[int, float, int, int]:
        pos_hist: list[int] = []
        fails = 0
        for row in per_code:
            pos = None
            for i, name in enumerate(order_names, 1):
                cell = row["results"].get(name, "")
                if cell.startswith("True:"):
                    pos = i
                    break
            if pos is None:
                fails += 1
            else:
                pos_hist.append(pos)
        avg_pos = (sum(pos_hist) / len(pos_hist)) if pos_hist else 0.0
        first_hit = sum(1 for p in pos_hist if p == 1)
        return fails, avg_pos, first_hit, len(pos_hist)

    orders = {
        "aws_ps > aws_pl > mono_s_ps > mono_f_ps": [
            "aws_ps",
            "aws_pl",
            "mono_s_ps",
            "mono_f_ps",
            "dig_ps",
            "dig_pl",
        ],
        "mono_s_ps > mono_f_ps > aws_ps > aws_pl": [
            "mono_s_ps",
            "mono_f_ps",
            "aws_ps",
            "aws_pl",
            "dig_ps",
            "dig_pl",
        ],
        "aws_ps > mono_s_ps > aws_pl > mono_f_ps": [
            "aws_ps",
            "mono_s_ps",
            "aws_pl",
            "mono_f_ps",
        ],
        "dig_ps > aws_ps > mono_s_ps": [
            "dig_ps",
            "aws_ps",
            "mono_s_ps",
            "dig_pl",
            "aws_pl",
            "mono_f_ps",
        ],
    }
    print("\n=== ORDER SIMULATION ===")
    for label, order in orders.items():
        fails, avg_pos, first_hit, n_ok = sim_order(order)
        print(label)
        print(
            f"  fails={fails} avg_tries={avg_pos:.2f} "
            f"first_ok={first_hit}/{n_ok}"
        )


if __name__ == "__main__":
    main()
