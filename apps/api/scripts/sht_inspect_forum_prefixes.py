# -*- coding: utf-8 -*-
"""Inspect sehuatang forum multi-level types + 有码 list prefixes."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from bs4 import BeautifulSoup

from app import outbound_http as o

OUT = ROOT / "data" / "debug"
LIVE = OUT / "sht_forum_types_live.json"

CODE_RE = re.compile(r"\b([A-Z]{2,10})-?(\d{2,5})\b", re.I)
FC2_RE = re.compile(r"\bFC2[-_ ]?(?:PPV[-_ ]?)?(\d{5,8})\b", re.I)
SKIP = {
    "HTTP",
    "HTTPS",
    "HTML",
    "MP4",
    "DVD",
    "HD",
    "FHD",
    "4K",
    "VR",
    "BT",
    "ED2K",
    "MKV",
    "VIP",
}


def main() -> None:
    for fid in (36, 104):
        path = OUT / f"sht_fid_{fid}.html"
        if not path.exists():
            continue
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
        print(f"\n--- fid {fid} type links ---")
        for a in soup.select("a[href*=typeid]")[:12]:
            href = a.get("href") or ""
            tid_m = re.search(r"typeid=(\d+)", href)
            text = a.get_text(strip=True)
            title = a.get("title")
            print(f"  text={text!r} title={title!r} tid={tid_m.group(1) if tid_m else None}")

    page = o.fetch_page(
        "https://www.sehuatang.net/forum.php?mod=forumdisplay&fid=37",
        referer="https://www.sehuatang.net/forum.php",
        timeout=28.0,
    )
    html = page.html or ""
    (OUT / "sht_fid_37.html").write_text(html, encoding="utf-8")
    soup = BeautifulSoup(html, "lxml")
    titles: list[str] = []
    seen: set[str] = set()
    for a in soup.select("a.s.xst, a[href*=thread-]"):
        t = a.get_text(" ", strip=True)
        if not t or len(t) < 4 or t in seen:
            continue
        seen.add(t)
        titles.append(t)
    print(f"\n有码原创 titles ({len(titles)}):")
    for t in titles[:20]:
        print(" ", t[:100])

    pref: Counter[str] = Counter()
    for t in titles:
        for m in CODE_RE.finditer(t):
            p = m.group(1).upper()
            if p not in SKIP:
                pref[p] += 1
        if FC2_RE.search(t):
            pref["FC2"] += 1
    print("\n有码列表页前缀 Top:", pref.most_common(20))

    # normalize live names (strip trailing counts)
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    print("\n=== 前缀向子分类汇总 ===")
    for row in live:
        types = row["types"]
        if not types:
            print(f"[{row['fid']}] {row['board']}: （无子分类）")
            continue
        names = []
        for t in types:
            name = re.sub(r"\s+\d+\s*$", "", t["name"]).strip()
            names.append(f"{t['typeid']}:{name}")
        print(f"[{row['fid']}] {row['board']}: {len(names)} → " + ", ".join(n.split(":", 1)[1] for n in names[:12])
              + (" …" if len(names) > 12 else ""))


if __name__ == "__main__":
    main()
