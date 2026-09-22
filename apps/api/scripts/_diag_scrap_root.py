"""诊断四：真实刮削库根 + 各分区实际 NFO/条目规模。只读。"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.scrap_library import embed as embed_svc  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_diag_root.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


st = embed_svc.get_settings()
w("settings =", st)
root = Path(str(st.get("resolved") or ""))
w("resolved root =", root, "exists=", root.is_dir())
w("")

if root.is_dir():
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if d.name.startswith("_"):
            continue
        pref = [p for p in d.iterdir() if p.is_dir()]
        n_codes = 0
        n_nfo = 0
        n_folders = 0
        for p in pref:
            for c in p.iterdir():
                if c.is_dir():
                    n_folders += 1
                    if any(c.glob("*.nfo")):
                        n_nfo += 1
            n_codes += 1
        w(
            f"{d.name:12s} prefixes={n_codes:5d} codeDirs={n_folders:6d} withNFO={n_nfo:6d} "
            f"noNFO={n_folders - n_nfo:6d}"
        )
else:
    w("(根不存在)")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
