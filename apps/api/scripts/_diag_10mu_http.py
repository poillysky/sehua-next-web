"""10musume 封面 http vs https 原始探测。只读。"""
from __future__ import annotations

import io
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import httpx  # noqa: E402

OUT = os.path.join(ROOT_DIR, "_diag_10mu_http.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

urls = [
    "http://www.10musume.com/moviepages/122609_01/images/str.jpg",
    "https://www.10musume.com/moviepages/122609_01/images/str.jpg",
    "http://www.10musume.com/moviepages/122711_01/images/str.jpg",
]

for u in urls:
    for follow in (True, False):
        try:
            r = httpx.get(
                u, headers={"User-Agent": UA, "Referer": u.split("/moviepages")[0] + "/"},
                timeout=15.0, follow_redirects=follow, verify=False,
            )
            w(
                f"follow={follow} {u[:56]:56s} → {r.status_code} len={len(r.content)} "
                f"ctype={r.headers.get('content-type')} loc={r.headers.get('location')}"
            )
        except Exception as e:  # noqa: BLE001
            w(f"follow={follow} {u[:56]:56s} → 异常 {str(e)[:80]}")
    w("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
