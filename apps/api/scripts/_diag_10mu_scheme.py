"""10musume 封面：http 原样 vs 强制 https，各试 3 次。只读。"""
from __future__ import annotations

import io
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from app.scrap_library import embed as embed_svc  # noqa: E402

OUT = os.path.join(ROOT_DIR, "_diag_10mu_scheme.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


CASES = [
    ("10MU-122609-01", "122609_01"),
    ("10MU-122714-01", "122714_01"),
    ("10MU-122912-02", "122912_02"),
    ("10MU-123009-01", "123009_01"),
    ("10MU-122711-01", "122711_01"),
    ("10MU-122817-01", "122817_01"),
]

for code, key in CASES:
    for scheme in ("http", "https"):
        u = f"{scheme}://www.10musume.com/moviepages/{key}/images/str.jpg"
        outs = []
        for i in range(3):
            try:
                got = embed_svc._fetch_cover_bytes(u, slot_timeout=12.0)
            except Exception as e:  # noqa: BLE001
                outs.append(f"异常({str(e)[:28]})")
                continue
            if not got:
                outs.append("None")
            else:
                outs.append(f"{len(got[0])}B")
        w(f"{code:18s} {scheme:6s} → {outs}")
    w("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
