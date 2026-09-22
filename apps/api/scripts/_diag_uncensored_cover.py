"""无码区：10musume 封面下载失败复核。只读（仅网络）。"""
from __future__ import annotations

import io
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import app.core.detail_path_cache as dpc  # noqa: E402
import app.core.site_mirror as sm  # noqa: E402
import app.scrape.sources_settings as ss  # noqa: E402
from app.scrap_library import embed as embed_svc  # noqa: E402

dpc.remember = lambda *a, **k: None  # type: ignore[assignment]
sm.remember = lambda *a, **k: None  # type: ignore[assignment]
ss._remember_live = lambda *a, **k: None  # type: ignore[assignment]

from app.scrape_details import fetch_detail_for_source  # noqa: E402

OUT = os.path.join(ROOT_DIR, "_diag_uncensored_cover.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


FAILED = ["10MU-122609-01", "10MU-122714-01", "10MU-122912-02", "10MU-123009-01"]
OK = ["10MU-122711-01", "10MU-122817-01"]

ctx = ss.resolve_fetch_context("10musume")
w("10musume base =", ctx["baseUrl"], " access =", ctx["access"])

for code in FAILED + OK:
    try:
        d = fetch_detail_for_source(
            "10musume",
            code,
            base_url=ctx["baseUrl"],
            cookie=ctx["cookie"],
            api_key=ctx["apiKey"],
        )
    except Exception as e:  # noqa: BLE001
        w(f"{code}: detail 失败 {e}")
        continue
    u = str((d or {}).get("posterUrl") or "")
    w(f"{code}: posterUrl={u}")
    if not u:
        w("    → 无 posterUrl")
        continue
    try:
        got = embed_svc._fetch_cover_bytes(u, slot_timeout=20.0)
    except Exception as e:  # noqa: BLE001
        w(f"    → 拉图异常: {str(e)[:90]}")
        continue
    if not got:
        w("    → 拉图返回 None（<1024B 或异常）")
        continue
    raw, ctype = got
    blank = embed_svc._is_blank_cover_bytes(raw)
    magic = embed_svc._image_magic_ok(raw)
    w(f"    → {len(raw)}B ctype={ctype} magic_ok={magic} blank={blank}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
