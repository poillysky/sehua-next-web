"""诊断二：五区 enrich 日志尾部 + 检查点 + 重试提示。只读。"""
from __future__ import annotations

import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import db as dbmod  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag_logs.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


REGIONS = ["japan_censored", "japan_uncensored", "japan_amateur", "fc2", "china", "western"]

with dbmod.connect() as conn:
    w("=" * 78)
    w("A) enrich_logs 每区尾部 30 行（用户点「日志」看到的内容）")
    w("=" * 78)
    for rid in REGIONS:
        rows = conn.execute(
            "SELECT line, created_at FROM enrich_logs WHERE region = %s ORDER BY id DESC LIMIT 30",
            (rid,),
        ).fetchall()
        w(f"----- {rid}  (共 {len(rows)} 行取回) -----")
        for r in reversed(rows):
            w(f"   {r['created_at']}  {r['line']}")
        w("")

    w("=" * 78)
    w("B) enrich_retry_hint（有界重试提示）分区 × kind")
    w("=" * 78)
    try:
        rows = conn.execute(
            """
            SELECT region, kind, COUNT(*) AS n,
                   SUM(CASE WHEN giveup THEN 1 ELSE 0 END) AS giveup_n
            FROM enrich_retry_hint GROUP BY region, kind ORDER BY region, n DESC
            """
        ).fetchall()
        if not rows:
            w("  (空表)")
        for r in rows:
            w(f"  {r['region']:20s} kind={r['kind']:10s} n={r['n']:7d} giveup={r['giveup_n']}")
    except Exception as e:  # noqa: BLE001
        w(f"  查询失败: {e}")

    w("")
    w("=" * 78)
    w("C) pending 行样例 gaps_json（前 12 条/区）")
    w("=" * 78)
    for rid in REGIONS:
        rows = conn.execute(
            """
            SELECT code, item_id, gaps_json, source, error
            FROM enrich_queue_log
            WHERE region = %s AND status = 'pending'
            ORDER BY id DESC LIMIT 12
            """,
            (rid,),
        ).fetchall()
        w(f"----- {rid} -----")
        for r in rows:
            w(f"   {r['code']:24s} gaps={r['gaps_json'][:90]}")
        if not rows:
            w("   (无 pending)")
        w("")

    w("=" * 78)
    w("D) done 行样例（看是否真拿到数据）")
    w("=" * 78)
    for rid in REGIONS:
        rows = conn.execute(
            """
            SELECT code, detail_title, source, fetch_ms, gaps_json
            FROM enrich_queue_log
            WHERE region = %s AND status = 'done'
            ORDER BY id DESC LIMIT 10
            """,
            (rid,),
        ).fetchall()
        w(f"----- {rid} -----")
        for r in rows:
            w(f"   {r['code']:22s} src={str(r['source'])[:14]:14s} ms={r['fetch_ms']} title={str(r['detail_title'])[:60]}")
        if not rows:
            w("   (无 done)")
        w("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
