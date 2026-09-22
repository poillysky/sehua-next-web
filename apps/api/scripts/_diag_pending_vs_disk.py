"""诊断五：pending 队列 vs 本地磁盘实体 匹配率 + 向量库分区规模。只读。"""
from __future__ import annotations

import io
import os
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import db as dbmod  # noqa: E402
from app.scrap_library import embed as embed_svc  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag_match.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


REGIONS = ["japan_censored", "japan_uncensored", "japan_amateur", "fc2", "china", "western"]
root = Path(str(embed_svc.get_settings().get("resolved") or ""))

# 分区目录名（中文标签）→ 磁盘目录
DIRS = {}
for d in root.iterdir() if root.is_dir() else []:
    if d.is_dir() and not d.name.startswith("_"):
        DIRS[d.name] = d

w("磁盘分区目录:", list(DIRS.keys()))
w("")

# 建立「分区 → 全部番号夹名集合」
names_by_dir: dict[str, set[str]] = {}
for name, d in DIRS.items():
    s: set[str] = set()
    for pref in d.iterdir():
        if pref.is_dir():
            for c in pref.iterdir():
                if c.is_dir():
                    s.add(c.name.upper())
    names_by_dir[name] = s
    w(f"{name}: 番号夹 {len(s)}")
w("")

# 区域 → 磁盘目录名
REG_DIR = {
    "japan_censored": "日本有码",
    "japan_uncensored": "日本无码",
    "japan_amateur": "日本素人",
    "fc2": "FC2",
    "china": "国产无码",
    "western": None,
}

w("=" * 78)
w("A) enrich_queue_log pending 抽样 vs 本地番号夹 命中率（每区 300 条，缺则全取）")
w("=" * 78)
with dbmod.connect() as conn:
    for rid in REGIONS:
        rows = conn.execute(
            "SELECT code FROM enrich_queue_log WHERE region=%s AND status='pending' "
            "ORDER BY random() LIMIT 300",
            (rid,),
        ).fetchall()
        codes = [str(r["code"] or "").upper() for r in rows if r["code"]]
        dirname = REG_DIR.get(rid)
        if not codes or not dirname:
            w(f"{rid:20s} pending抽样={len(codes):4d} 本地无该分区目录 → 命中 0")
            continue
        have = names_by_dir.get(dirname) or set()
        hit = sum(1 for c in codes if c in have)
        w(
            f"{rid:20s} pending抽样={len(codes):4d} 本地命中={hit:4d} "
            f"({hit*100//max(len(codes),1)}%)  本地夹总数={len(have)}"
        )

    w("")
    w("=" * 78)
    w("B) 向量库 scrap_library_embed 分区规模")
    w("=" * 78)
    try:
        rows = conn.execute(
            "SELECT region, COUNT(*) AS n FROM scrap_library_embed GROUP BY region ORDER BY n DESC"
        ).fetchall()
        for r in rows:
            w(f"   {str(r['region']):20s} {r['n']}")
        if not rows:
            w("   (空)")
    except Exception as e:  # noqa: BLE001
        w(f"   查询失败: {e}")
        try:
            cols = conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='scrap_library_embed'"
            ).fetchall()
            w("   列: " + ", ".join(str(c["column_name"]) for c in cols))
        except Exception as e2:  # noqa: BLE001
            w(f"   列查询失败: {e2}")

    w("")
    w("=" * 78)
    w("C) FC2 fail「仍缺:封面」抽样 → 本地是否存在 + 是否有封面文件")
    w("=" * 78)
    rows = conn.execute(
        "SELECT code, item_id, error FROM enrich_queue_log "
        "WHERE region='fc2' AND status='fail' ORDER BY id DESC LIMIT 200"
    ).fetchall()
    ec = Counter(str(r["error"])[:40] for r in rows)
    for k, v in ec.most_common(6):
        w(f"   {v:5d}  {k}")
    fc2dir = DIRS.get("FC2")
    ex = 0
    nocover = 0
    if fc2dir:
        for r in rows[:50]:
            code = str(r["code"] or "").upper()
            num = code.replace("FC2-PPV-", "").replace("FC2-", "")
            found = None
            for pref in fc2dir.iterdir():
                if not pref.is_dir():
                    continue
                cand = pref / code
                if cand.is_dir():
                    found = cand
                    break
                cand2 = pref / f"FC2-{num}"
                if cand2.is_dir():
                    found = cand2
                    break
            if found:
                ex += 1
                if not any(found.glob("*.jpg")):
                    nocover += 1
    w(f"   抽样 50 条 fail：本地找到番号夹 {ex}；其中无 jpg 封面 {nocover}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
