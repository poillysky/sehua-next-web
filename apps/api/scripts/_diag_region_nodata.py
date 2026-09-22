"""诊断：五区刮削「大量无数据」——队列表状态与错误归因。

只读。输出到 _diag_region_nodata.txt (UTF-8)。
"""
from __future__ import annotations

import io
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import db as dbmod  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag_region_nodata.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


REGIONS = ["japan_censored", "japan_uncensored", "japan_amateur", "fc2", "china", "western"]

with dbmod.connect() as conn:
    # 1. 每区状态分布
    w("=" * 70)
    w("1) enrich_queue_log 分区 × 状态")
    w("=" * 70)
    rows = conn.execute(
        """
        SELECT region, status, COUNT(*) AS n
        FROM enrich_queue_log
        GROUP BY region, status
        ORDER BY region, n DESC
        """
    ).fetchall()
    per = defaultdict(Counter)
    for r in rows:
        per[r["region"]][r["status"]] = r["n"]
    for rid in REGIONS + [k for k in per if k not in REGIONS]:
        c = per.get(rid)
        if not c:
            w(f"{rid:20s} (空)")
            continue
        tot = sum(c.values())
        parts = " ".join(f"{k}={v}({v*100//max(tot,1)}%)" for k, v in c.most_common())
        w(f"{rid:20s} total={tot:7d}  {parts}")

    # 2. fail 行的 error 归因（近 5000 条/区）
    w("")
    w("=" * 70)
    w("2) fail 行 error 归因（每区最新 5000 条 fail）")
    w("=" * 70)
    for rid in REGIONS:
        w(f"--- {rid} ---")
        try:
            fr = conn.execute(
                """
                SELECT code, source, error, detail_title, gaps_json, item_id
                FROM enrich_queue_log
                WHERE region = %s AND status = 'fail'
                ORDER BY id DESC LIMIT 5000
                """,
                (rid,),
            ).fetchall()
        except Exception as e:  # noqa: BLE001
            w(f"  查询失败: {e}")
            continue
        if not fr:
            w("  (无 fail 行)")
            continue
        ec = Counter()
        for r in fr:
            msg = (r["error"] or "").strip()
            msg = msg[:120] if msg else "(空 error)"
            ec[msg] += 1
        for msg, n in ec.most_common(15):
            w(f"  {n:5d}  {msg}")
        w(f"  样例 code/source: " + ", ".join(
            f"{r['code']}|{r['source']}" for r in fr[:12] if r["code"]
        ))

    # 3. done 行的 detail_title 空率（真·无数据判定）
    w("")
    w("=" * 70)
    w("3) done/pending 行 detail_title 空率")
    w("=" * 70)
    for rid in REGIONS:
        rr = conn.execute(
            """
            SELECT
              COUNT(*) FILTER (WHERE status='done') AS done_n,
              COUNT(*) FILTER (WHERE status='done' AND COALESCE(detail_title,'')='') AS done_blank,
              COUNT(*) FILTER (WHERE status='pending') AS pend_n,
              COUNT(*) FILTER (WHERE status='fail') AS fail_n,
              COUNT(*) AS tot
            FROM enrich_queue_log WHERE region = %s
            """,
            (rid,),
        ).fetchone()
        if not rr or not rr["tot"]:
            w(f"{rid:20s} (空)")
            continue
        done_n = rr["done_n"] or 0
        blank = rr["done_blank"] or 0
        pct = (blank * 100 // done_n) if done_n else 0
        w(
            f"{rid:20s} tot={rr['tot']:7d} done={done_n:7d} done标题空={blank:6d}({pct}%) "
            f"pending={rr['pend_n']:6d} fail={rr['fail_n']:6d}"
        )

    # 4. 各区样例番号（看命名）
    w("")
    w("=" * 70)
    w("4) 各区样例番号 / item_id（最新 15 条）")
    w("=" * 70)
    for rid in REGIONS:
        sr = conn.execute(
            """
            SELECT code, item_id, status FROM enrich_queue_log
            WHERE region = %s AND COALESCE(code,'') <> ''
            ORDER BY id DESC LIMIT 15
            """,
            (rid,),
        ).fetchall()
        w(f"{rid:20s} " + ", ".join(f"{r['code']}[{r['status']}]" for r in sr))

    # 5. 源级统计（fail 行 source 分布）
    w("")
    w("=" * 70)
    w("5) fail 行 source 分布（每区）")
    w("=" * 70)
    for rid in REGIONS:
        sr = conn.execute(
            """
            SELECT COALESCE(NULLIF(source,''),'(空)') AS s, COUNT(*) AS n
            FROM enrich_queue_log
            WHERE region = %s AND status='fail'
            GROUP BY s ORDER BY n DESC LIMIT 12
            """,
            (rid,),
        ).fetchall()
        if not sr:
            w(f"{rid:20s} (无)")
            continue
        w(f"{rid:20s} " + ", ".join(f"{r['s']}={r['n']}" for r in sr))

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
