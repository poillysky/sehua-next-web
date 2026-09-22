"""诊断七：向量库(欧美/无码)行样例 —— 判断这些行的来源与 rel_path 是否真实存在。只读。"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import db as dbmod  # noqa: E402
from app.scrap_library import embed as embed_svc  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag_embed_rows.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


root = Path(str(embed_svc.get_settings().get("resolved") or ""))

with dbmod.connect() as conn:
    cols = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name='scrap_library_embed' ORDER BY ordinal_position"
    ).fetchall()
    w("列:", ", ".join(f"{c['column_name']}({c['data_type']})" for c in cols))
    w("")

    for reg in ("欧美无码", "日本无码", "日本素人", "国产无码"):
        w("=" * 78)
        w(f"### {reg}")
        w("=" * 78)
        try:
            rows = conn.execute(
                "SELECT * FROM scrap_library_embed WHERE region=%s ORDER BY updated_at DESC NULLS LAST LIMIT 8",
                (reg,),
            ).fetchall()
        except Exception as e:  # noqa: BLE001
            w(f"  查询失败: {e}")
            continue
        for r in rows:
            d = dict(r)
            rel = str(d.get("rel_path") or "")
            code = str(d.get("code") or d.get("num") or "")
            p = (root / rel) if rel else None
            exists = p.is_dir() if p is not None else None
            keep = {
                k: v
                for k, v in d.items()
                if k in ("code", "num", "region", "rel_path", "title", "updated_at", "created_at", "cover_url")
                and v not in (None, "")
            }
            w(f"  {keep}")
            if rel:
                w(f"      rel_exists={exists}  ({p})")
        w("")
        try:
            agg = conn.execute(
                "SELECT COUNT(*) AS n, MIN(updated_at) AS u0, MAX(updated_at) AS u1, "
                "COUNT(*) FILTER (WHERE COALESCE(rel_path,'')='') AS no_rel, "
                "COUNT(*) FILTER (WHERE COALESCE(title,'')='') AS no_title "
                "FROM scrap_library_embed WHERE region=%s",
                (reg,),
            ).fetchone()
            w(
                f"  行数={agg['n']} updated {agg['u0']} → {agg['u1']} "
                f"无rel_path={agg['no_rel']} 无title={agg['no_title']}"
            )
        except Exception as e:  # noqa: BLE001
            w(f"  聚合失败: {e}")
        w("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
