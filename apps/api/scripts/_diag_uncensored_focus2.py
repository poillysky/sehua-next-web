"""无码区专项（修正版）：真实盘面番号 × 源实测 + 封面下载失败原因。只读。"""
from __future__ import annotations

import io
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

import app.core.detail_path_cache as dpc  # noqa: E402
import app.core.site_mirror as sm  # noqa: E402
import app.scrape.sources_settings as ss  # noqa: E402
from app.core import db as dbmod  # noqa: E402
from app.scrap_library import embed as embed_svc  # noqa: E402

dpc.remember = lambda *a, **k: None  # type: ignore[assignment]
sm.remember = lambda *a, **k: None  # type: ignore[assignment]
ss._remember_live = lambda *a, **k: None  # type: ignore[assignment]

from app.scrape_details import fetch_detail_for_source  # noqa: E402

OUT = os.path.join(ROOT_DIR, "_diag_uncensored2.txt")
buf = io.StringIO()


def w(*a):
    print(*a, file=buf)


root = Path(str(embed_svc.get_settings().get("resolved") or ""))
udir = root / "日本无码"

w("=" * 84)
w("A) 磁盘真实无码番号 + 队列状态")
w("=" * 84)
disk: list[str] = []
with dbmod.connect() as conn:
    qmap = {
        str(r["code"]).upper(): (str(r["status"]), str(r["error"] or ""), str(r["source"] or ""))
        for r in conn.execute(
            "SELECT code, status, error, source FROM enrich_queue_log WHERE region='japan_uncensored'"
        ).fetchall()
    }
if udir.is_dir():
    for pref in sorted(udir.iterdir()):
        if not pref.is_dir():
            continue
        for c in sorted(pref.iterdir()):
            if not c.is_dir():
                continue
            disk.append(c.name)
            st = qmap.get(c.name.upper(), ("(不在队列)", "", ""))
            nfo = len(list(c.glob("*.nfo")))
            jpg = [p.name for p in c.glob("*.jpg")]
            w(
                f"   {c.name:20s} nfo={nfo} jpg={jpg}  队列={st[0]} err={st[1][:24]} src={st[2]}"
            )
w(f"   磁盘真实无码番号共 {len(disk)} 个")

pool = ss.enabled_enrich_sources(region="japan_uncensored")
w("")
w("   当前无码源池: " + ", ".join(r["id"] for r in pool))
w("   （磁盘上全部是 10MU-* 天然むすめ番号，只有 10musume 站能命中）")

w("")
w("=" * 84)
w("B) 每个真实番号 × 源 实测（当前池 + 10musume）")
w("=" * 84)
extra = ["10musume"]


def _one(sid: str, code: str) -> dict:
    try:
        ctx = ss.resolve_fetch_context(sid)
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "ok": False, "err": f"配置不可用: {str(e)[:60]}"}
    try:
        d = fetch_detail_for_source(
            sid, code, base_url=ctx["baseUrl"], cookie=ctx["cookie"], api_key=ctx["apiKey"]
        )
        return {
            "sid": sid,
            "ok": bool(str((d or {}).get("title") or "")),
            "title": str((d or {}).get("title") or "")[:44],
            "cover": str((d or {}).get("poster") or (d or {}).get("cover_url") or ""),
        }
    except Exception as e:  # noqa: BLE001
        return {"sid": sid, "ok": False, "err": str(e)[:70]}


ids = [str(r["id"]) for r in pool] + extra
for code in disk:
    res = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_one, s, code) for s in ids]
        for f in as_completed(futs, timeout=180):
            res.append(f.result())
    okn = sum(1 for r in res if r.get("ok"))
    w(f"   ### {code}   命中 {okn}/{len(res)}")
    for r in sorted(res, key=lambda x: (not x.get("ok"), x["sid"])):
        if r.get("ok"):
            w(f"        ✓ {r['sid']:16s} {r['title']}")
        else:
            w(f"        ✗ {r['sid']:16s} {r.get('err', '(空结果)')}")
    # 封面下载实测（用 10musume 给的 cover）
    u = next((r.get("cover") for r in res if r.get("ok") and r.get("cover")), "")
    if u:
        try:
            got = embed_svc._fetch_cover_bytes(u, slot_timeout=15.0)
            if got:
                raw, ctype = got
                blank = embed_svc._is_blank_cover_bytes(raw)
                w(f"        封面 {u[:70]} → {len(raw)}B {ctype} blank={blank}")
            else:
                w(f"        封面 {u[:70]} → 下载返回 None（被拒：<1024B / 异常）")
        except Exception as e:  # noqa: BLE001
            w(f"        封面 {u[:70]} → 异常 {str(e)[:70]}")
    w("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(buf.getvalue())
