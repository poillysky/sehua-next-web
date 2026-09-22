"""无码区专项：pending 番号构成 / 源目录覆盖 / 真实盘面番号实测。只读。"""
from __future__ import annotations

import io
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.core.detail_path_cache as dpc  # noqa: E402
import app.core.site_mirror as sm  # noqa: E402
import app.scrape.source_catalog as cat  # noqa: E402
import app.scrape.sources_settings as ss  # noqa: E402
from app.core import db as dbmod  # noqa: E402

dpc.remember = lambda *a, **k: None  # type: ignore[assignment]
sm.remember = lambda *a, **k: None  # type: ignore[assignment]
ss._remember_live = lambda *a, **k: None  # type: ignore[assignment]

from app.scrape_details import fetch_detail_for_source  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_diag_uncensored.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


# ---------- 1) 源目录里有没有这些无码厂牌 ----------
w("=" * 80)
w("1) 源目录（SOURCE_CATALOG）对无码厂牌的覆盖")
w("=" * 80)
keys = ["1pon", "1pondo", "heyzo", "pacopacomama", "tokyo", "muramura", "carib", "10musume", "avsox", "heydouga", "kurofune", "gachinco"]
for k in keys:
    hits = [
        f"{e['id']}({e.get('label')})"
        for e in cat.SOURCE_CATALOG
        if k in str(e.get("id", "")).lower() or k in str(e.get("label", "")).lower() or k in str(e.get("notes", "")).lower()
    ]
    w(f"   {k:16s} → {hits or '（无对应站点实现）'}")

# ---------- 2) 无码 pending 番号构成 ----------
w("")
w("=" * 80)
w("2) 无码区 pending 番号前缀构成（Top 30）")
w("=" * 80)
with dbmod.connect() as conn:
    rows = conn.execute(
        "SELECT code FROM enrich_queue_log WHERE region='japan_uncensored' "
        "AND status='pending' AND COALESCE(code,'')<>''"
    ).fetchall()
    codes = [str(r["code"]).upper() for r in rows]
    pref = Counter(re.sub(r"[-_].*$", "", c) for c in codes)
    for p, n in pref.most_common(30):
        w(f"   {p:16s} {n}")

    w("")
    w("=" * 80)
    w("3) 无码区 done/fail 明细（全部）")
    w("=" * 80)
    rows = conn.execute(
        "SELECT code, status, error, source, detail_title FROM enrich_queue_log "
        "WHERE region='japan_uncensored' AND status IN ('done','fail','soft') ORDER BY status, code"
    ).fetchall()
    for r in rows:
        w(
            f"   {str(r['code']):20s} {str(r['status']):6s} src={str(r['source'] or '-'):12s} "
            f"err={str(r['error'] or '-')[:28]:28s} title={str(r['detail_title'] or '')[:40]}"
        )

# ---------- 4) 磁盘真实无码番号 ----------
w("")
w("=" * 80)
w("4) 磁盘上真实存在的无码番号（日本无码/*/*）")
w("=" * 80)
udir = Path(ROOT) / "media" / "scrap-library" / "日本无码"
disk_codes: list[str] = []
if udir.is_dir():
    for pref in sorted(udir.iterdir()):
        if not pref.is_dir():
            continue
        for c in sorted(pref.iterdir()):
            if c.is_dir():
                nfo = list(c.glob("*.nfo"))
                jpg = list(c.glob("*.jpg"))
                disk_codes.append(c.name)
                w(
                    f"   {c.name:22s} prefix={pref.name:10s} nfo={len(nfo)} "
                    f"jpg={len(jpg)} 存在={c.is_dir()}"
                )
else:
    w("   (无该目录)")

# ---------- 5) 真实盘面番号实测 ----------
w("")
w("=" * 80)
w("5) 真实盘面无码番号 × 源 实测（当前源池 vs 注入 10musume/carib）")
w("=" * 80)
pool = ss.enabled_enrich_sources(region="japan_uncensored")
w("   当前源池: " + ", ".join(r["id"] for r in pool))


def _run(sid: str, code: str) -> dict:
    try:
        ctx = ss.resolve_fetch_context(sid)
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "ok": False, "err": f"配置不可用: {e}"}
    try:
        d = fetch_detail_for_source(
            sid, code, base_url=ctx["baseUrl"], cookie=ctx["cookie"], api_key=ctx["apiKey"]
        )
        title = str((d or {}).get("title") or "")
        return {"sid": sid, "ok": bool(title), "title": title[:50]}
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "ok": False, "err": str(e)[:80]}


extra = ["10musume", "carib", "avsox"]
for code in disk_codes:
    ids = [str(r["id"]) for r in pool] + extra
    res = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_run, s, code) for s in ids]
        for f in as_completed(futs, timeout=180):
            res.append(f.result())
    okn = sum(1 for r in res if r.get("ok"))
    w(f"   ### {code}  命中 {okn}/{len(res)}")
    for r in sorted(res, key=lambda x: (not x.get("ok"), x["sid"])):
        if r.get("ok"):
            w(f"        ✓ {r['sid']:16s} {r['title']}")
        else:
            w(f"        ✗ {r['sid']:16s} {r.get('err','(空结果)')}")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
