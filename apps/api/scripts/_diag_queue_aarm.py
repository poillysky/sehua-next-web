# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.core.db import init_db, get_meta_pool
from app.scrap_library import embed as embed_svc
from app.scrap_library import enrich as enrich_svc

init_db()
root = embed_svc.resolve_root(embed_svc.get_settings().get("root")).resolve()
print("root children", [p.name for p in root.iterdir()])
jp = next((p for p in root.iterdir() if p.is_dir() and "有码" in p.name), None)
print("jp", jp)
if jp:
    aarm = jp / "AARM"
    print("aarm exists", aarm.is_dir())
    if aarm.is_dir():
        dirs = [x.name for x in sorted(aarm.iterdir()) if x.is_dir()]
        print("aarm dir count", len(dirs), "sample", dirs[:10])
        print("aarm nfo", len(list(aarm.rglob("*.nfo"))))

pool = get_meta_pool()
with pool.connection() as conn, conn.cursor() as cur:
    cur.execute(
        """
        SELECT status, COUNT(*) AS n FROM enrich_queue_log
        WHERE region=%s AND code LIKE %s
        GROUP BY status ORDER BY status
        """,
        ("japan_censored", "AARM-%"),
    )
    print("AARM status", [dict(r) for r in cur.fetchall()])
    cur.execute(
        """
        SELECT code, status, COALESCE(source,'') AS source
        FROM enrich_queue_log
        WHERE region=%s AND code LIKE %s
        ORDER BY code LIMIT 12
        """,
        ("japan_censored", "AARM-%"),
    )
    print("AARM rows", [dict(r) for r in cur.fetchall()])
    cur.execute(
        """
        SELECT code, status FROM enrich_queue_log
        WHERE region=%s AND status='pending'
        ORDER BY code ASC LIMIT 15
        """,
        ("japan_censored",),
    )
    print("pending by code", [dict(r) for r in cur.fetchall()])
    cur.execute(
        """
        SELECT code, status FROM enrich_queue_log
        WHERE region=%s AND status='pending'
        ORDER BY id ASC LIMIT 15
        """,
        ("japan_censored",),
    )
    print("pending by id", [dict(r) for r in cur.fetchall()])

st = enrich_svc.get_enrich_status()
print("running", st.get("running"), "phase", st.get("phase"), "halt", st.get("halt"))
print("currentRegion", st.get("currentRegion"))
cps = st.get("checkpoints") or {}
for k, v in cps.items():
    if isinstance(v, dict):
        print(
            "cp",
            k,
            "mode",
            v.get("mode"),
            "ok",
            v.get("ok"),
            "failed",
            v.get("failed"),
            "remaining",
            v.get("remaining") or v.get("remainingCount"),
            "queueInLog",
            v.get("queueInLog"),
        )
qc = st.get("queueCounts") or {}
print("queueCounts", qc)
cur = st.get("current") or {}
print("current", cur.get("code"), cur.get("status"))
q = st.get("queue") or []
print("mem queue head", [(x.get("code"), x.get("status")) for x in q[:12] if isinstance(x, dict)])
