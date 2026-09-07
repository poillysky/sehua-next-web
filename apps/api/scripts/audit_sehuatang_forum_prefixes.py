# -*- coding: utf-8 -*-
"""Audit sehuatang-forum-synced prefixes: DMM + MGStage + known uncensored rules."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import outbound_http as o  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402

REPORT = ROOT / "data" / "_debug" / "prefix-sehuatang-forum-sync.json"
LIVE = ROOT / "data" / "_debug" / "sht_forum_types_live.json"
OUT = ROOT / "data" / "_debug" / "prefix-sehuatang-verify.json"

GQL = "https://api.video.dmm.co.jp/graphql"
QUERY = """
query ScrapDigitalContent($id: ID!) {
  ppvContent(id: $id) { id title maker { name } }
}
"""
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"

# 论坛栏目名 → 自造「伪前缀」（站点/系列名，不是通用 CODE-123 前缀）
WRONG_SHELLS = {
    "JUKUJO": "熟女俱樂部是栏目/站点，不是 JUKUJO- 番号前缀",
    "HITODUMA": "人妻斬り多为日期号，不是 HITODUMA-",
    "SHIROUTO": "本生素人TV 不是 SHIROUTO- 前缀",
    "LEZNYOSHIN": "自造；女体のしんぴ侧常用 nyoshin 日期形态",
    "TOKYOHOT": "东京热主流 nXXXX，极少 TOKYOHOT-NNN",
    "ROCKET": "厂牌名；番号多为 RCT/RCTD 等，不是 ROCKET-",
}

# 无码站壳：可保留为「来源标签」，但 format 不是标准 letter-num（记为 shell）
UNC_SHELL_OK = {
    "HEYZO",
    "CARIB",
    "CARIBPR",
    "1PON",
    "10MU",
    "PACO",
    "H0930",
    "H4610",
    "C0930",
    "KIN8",
    "NYOSHIN",
    "HEYPPV",
    "XXXAV",
    "SMMIRACLE",
    "ROSELIP",
    "LEGSJAPAN",
    "URALESBIAN",
    "FELLATIOJAPAN",
    "SPERMMANIA",
    "HANDJOBJAPAN",
    "URABUKKAKE",
    "JAPORNXXX",
    "COSPURI",
    "FC2",
    "FC2PPV",
}

KNOWN_DIGIT = {
    "ssis": [""],
    "ssni": [""],
    "midv": [""],
    "mist": [""],
    "mvg": [""],
    "spsf": [""],
    "rlmp": [""],
    "ktra": [""],
    "ekdv": [""],
    "gma": [""],
    "bagr": [""],
    "cemd": [""],
    "mkmp": [""],
    "royed": [""],
    "nact": [""],
    "roe": [""],
    "aldn": [""],
    "rctd": [""],
    "svvrt": [""],
    "avsa": [""],
    "jur": [""],
    "stars": ["1"],
    "dandy": ["1"],
}


def dmm_ok(http: httpx.Client, prefix: str) -> dict[str, Any]:
    series = re.sub(r"[^A-Za-z0-9]", "", prefix).lower()
    digits = KNOWN_DIGIT.get(series, ["", "1", "13", "h_068", "1"])
    tried = []
    for n in (1, 100, 500):
        num = str(n).zfill(5)
        for d in digits[:3]:
            cid = f"{d}{series}{num}" if d else f"{series}{num}"
            if cid in tried:
                continue
            tried.append(cid)
            try:
                r = http.post(
                    GQL,
                    json={
                        "operationName": "ScrapDigitalContent",
                        "variables": {"id": cid},
                        "query": QUERY,
                    },
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Origin": "https://video.dmm.co.jp",
                        "Referer": f"https://video.dmm.co.jp/av/content/?id={cid}",
                        "User-Agent": UA,
                    },
                    timeout=6.0,
                )
            except Exception as e:  # noqa: BLE001
                continue
            if r.status_code >= 400:
                continue
            data = (r.json() or {}).get("data") or {}
            content = data.get("ppvContent")
            if content and content.get("id"):
                maker = ((content.get("maker") or {}) or {}).get("name") or ""
                return {
                    "ok": True,
                    "cid": cid,
                    "title": (content.get("title") or "")[:80],
                    "maker": maker,
                }
            time.sleep(0.05)
    return {"ok": False, "tried": tried[:6]}


def mgstage_ok(prefix: str) -> dict[str, Any]:
    # e.g. 259LUXU-0001 / SIRO-5700
    samples = []
    if re.match(r"^\d{2,3}[A-Z]", prefix, re.I):
        samples = [f"{prefix}-0001", f"{prefix}-001", f"{prefix}-100"]
    else:
        samples = [f"{prefix}-0001", f"{prefix}-5000", f"{prefix}-100"]
    for code in samples:
        url = f"https://www.mgstage.com/product/product_detail/{code}/"
        try:
            page = o.fetch_page(
                url,
                cookie="adc=1",
                referer="https://www.mgstage.com/",
                timeout=18.0,
            )
            html = page.html or ""
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:100]}
        if "年齢認証" in html or "Age Verification" in html:
            continue
        if len(html) < 3000:
            continue
        if code.replace("-", "")[:6].lower() in html.lower() or "product_detail" in html:
            if "お探しのページ" in html or "404" in html[:1500]:
                continue
            title_m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
            t = re.sub(r"\s+", " ", title_m.group(1)).strip()[:70] if title_m else ""
            if "404" in t or "見つかり" in t:
                continue
            # soft ok if page is product-like
            if "product" in html.lower() and len(html) > 8000:
                return {"ok": True, "code": code, "title": t, "via": page.via}
    # search page
    q = prefix
    url = f"https://www.mgstage.com/search/cSearch.php?search_word={q}"
    try:
        page = o.fetch_page(url, cookie="adc=1", timeout=18.0)
        html = page.html or ""
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:100]}
    hits = re.findall(
        rf'href=["\'][^"\']*?/product_detail/({re.escape(prefix)}-\d{{2,5}})/',
        html,
        re.I,
    )
    if hits:
        return {"ok": True, "code": hits[0].upper(), "search_hits": len(hits), "via": page.via}
    return {"ok": False, "html": len(html)}


def main() -> None:
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    list_added = [
        x
        for x in (rep.get("from_list_added_or_touched") or [])
        if x.get("action") == "added" and x.get("region") == "japan_censored"
    ]
    type_added = [x for x in (rep.get("from_types") or []) if x.get("action") == "added"]
    amateur_types = [
        x
        for x in (rep.get("from_types") or [])
        if x.get("region") == "japan_amateur"
        and re.match(r"^\d{0,3}[A-Z]", x.get("prefix") or "")
    ]

    print("=== DMM check: list-added censored ===", flush=True)
    dmm_rows = []
    proxy = o.resolve_scrape_proxy_url() or None
    client_kw: dict[str, Any] = {"trust_env": False, "follow_redirects": True}
    if proxy:
        client_kw["proxy"] = proxy
        client_kw["verify"] = False
    with httpx.Client(**client_kw) as http:
        for item in list_added:
            pref = item["prefix"]
            if pref in WRONG_SHELLS:
                row = {
                    "prefix": pref,
                    "status": "wrong",
                    "reason": WRONG_SHELLS[pref],
                    "count": item.get("count"),
                }
            else:
                hit = dmm_ok(http, pref)
                row = {
                    "prefix": pref,
                    "status": "ok" if hit.get("ok") else "miss",
                    "count": item.get("count"),
                    **hit,
                }
            dmm_rows.append(row)
            print(
                f"  {row['status']:5} {pref:10} ×{item.get('count')} {row.get('cid') or row.get('reason') or ''}",
                flush=True,
            )

    print("\n=== MGStage check: key amateur ===", flush=True)
    am_probe = sorted(
        {
            x["prefix"]
            for x in amateur_types
            if x["prefix"]
            in {
                "SIRO",
                "259LUXU",
                "300MIUM",
                "200GANA",
                "300MAAN",
                "300NTK",
                "230OREX",
                "336KNB",
                "390JAC",
                "328HMDN",
                "326EVA",
                "332NAMA",
                "326SCP",
                "SCUTE",
                "MYWIFE",
                "GAREA",
                "SIROHAME",
            }
        }
    )
    # ensure core set even if not in from_types action
    for p in [
        "SIRO",
        "259LUXU",
        "300MIUM",
        "200GANA",
        "300MAAN",
        "300NTK",
        "230OREX",
        "336KNB",
        "390JAC",
        "328HMDN",
    ]:
        if p not in am_probe:
            am_probe.append(p)
    mgs_rows = []
    for pref in am_probe:
        hit = mgstage_ok(pref)
        row = {"prefix": pref, "status": "ok" if hit.get("ok") else "miss", **hit}
        mgs_rows.append(row)
        print(f"  {row['status']:5} {pref:10} {row.get('code') or row.get('error') or row.get('html')}", flush=True)

    print("\n=== type-added shells ===", flush=True)
    type_rows = []
    for item in type_added:
        pref = item["prefix"]
        if pref in WRONG_SHELLS:
            st = "wrong"
            reason = WRONG_SHELLS[pref]
        elif pref in UNC_SHELL_OK or item["region"] in {"fc2"}:
            st = "shell_ok"
            reason = "无码/FC2 站点壳或已知系列前缀"
        else:
            st = "review"
            reason = "需人工确认"
        type_rows.append({**item, "status": st, "reason": reason})
        print(f"  {st:9} {pref:14} {reason}", flush=True)

    # Coverage vs live forum types
    from scripts.sync_prefixes_from_sehuatang_forum import (  # noqa: E402
        clean_prefix,
        resolve_type,
        strip_count,
    )

    live = json.loads(LIVE.read_text(encoding="utf-8")) if LIVE.exists() else []
    doc = store.load_catalog(force=True)
    unmapped = []
    mapped_ok = []
    for board in live:
        fid = int(board["fid"])
        for t in board.get("types") or []:
            name = strip_count(str(t.get("name") or ""))
            hit = resolve_type(name, board_fid=fid)
            if not hit:
                if name and "三级" not in name and "四级" not in name and "写真" not in name:
                    unmapped.append({"fid": fid, "board": board["board"], "type": name})
                continue
            rid, pref, _ = hit
            key = clean_prefix(pref)
            mapped_ok.append(
                {
                    "type": name,
                    "prefix": key,
                    "region": rid,
                    "in_catalog": key in doc["regions"][rid]["prefixes"],
                }
            )

    summary = {
        "dmm_list_ok": sum(1 for x in dmm_rows if x["status"] == "ok"),
        "dmm_list_miss": sum(1 for x in dmm_rows if x["status"] == "miss"),
        "dmm_list_wrong": sum(1 for x in dmm_rows if x["status"] == "wrong"),
        "mgs_ok": sum(1 for x in mgs_rows if x["status"] == "ok"),
        "mgs_miss": sum(1 for x in mgs_rows if x["status"] == "miss"),
        "type_wrong": [x["prefix"] for x in type_rows if x["status"] == "wrong"],
        "type_shell_ok": [x["prefix"] for x in type_rows if x["status"] == "shell_ok"],
        "forum_types_mapped": len(mapped_ok),
        "forum_types_unmapped_non_genre": unmapped,
    }
    out = {
        "dmm_list": dmm_rows,
        "mgstage_amateur": mgs_rows,
        "type_added": type_rows,
        "summary": summary,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
