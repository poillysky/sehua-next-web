# -*- coding: utf-8 -*-
"""Enter sehuatang forum.php via outbound fetch_page (safe=1 + safeid→_safe)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core import outbound_http as o

OUT = ROOT / "data" / "debug"
URL = "https://www.sehuatang.net/forum.php"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("URL", URL, flush=True)
    print("proxy", bool(o.resolve_scrape_proxy_url()), flush=True)

    page = o.fetch_page(URL, timeout=25.0, fresh_probe=False)
    html = page.html or ""
    title_m = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    title = re.sub(r"\s+", " ", title_m.group(1)).strip()[:80] if title_m else ""
    gate = o.is_r18_safe_shell(html)
    ok = (
        not gate
        and len(html) > 8000
        and ("Discuz" in html or "fid=" in html or "forum-" in html)
    )
    print(
        f"via={page.via} len={len(html)} gate={gate} title={title!r}",
        flush=True,
    )
    (OUT / "sht_forum_curl.html").write_text(html, encoding="utf-8")

    boards: dict[str, str] = {}
    for m in re.finditer(
        r'forum\.php\?mod=forumdisplay&fid=(\d+)[^"\']*["\'][^>]*>([^<]+)<',
        html,
        re.I,
    ):
        fid, name = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        if name and fid not in boards:
            boards[fid] = name
    for m in re.finditer(r'forum-(\d+)-\d+\.html["\'][^>]*>([^<]+)<', html, re.I):
        fid, name = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        if name and fid not in boards:
            boards[fid] = name

    print("boards", len(boards), flush=True)
    for fid in sorted(boards, key=int)[:20]:
        print(f"  {fid:>4}  {boards[fid]}", flush=True)
    if len(boards) > 20:
        print(f"  … +{len(boards) - 20} more", flush=True)

    print("ENTER_OK" if ok else "ENTER_FAIL", flush=True)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
