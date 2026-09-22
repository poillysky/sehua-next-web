# -*- coding: utf-8 -*-
from __future__ import annotations

from urllib.parse import quote

from app.makers import settings as ms
from app.core import outbound_http as o


def peek(label: str, url: str, **kw) -> str:
    try:
        p = o.fetch_page(url, timeout=18.0, **kw)
        html = p.html or ""
        final = getattr(p, "final_url", None) or url
        print(f"{label}: len={len(html)} final={final}", flush=True)
        return html
    except Exception as e:  # noqa: BLE001
        print(f"{label}: ERR {e}", flush=True)
        return ""


def main() -> None:
    bases = list(ms.javbus_bases())[:2]
    cookie = ms.javbus_cookie() or None
    print("javbus bases", bases, flush=True)
    for b in bases[:1]:
        peek("javbus home", b + "/", cookie=cookie)
        peek("javbus AKNR", f"{b}/search/{quote('AKNR')}", cookie=cookie)
        peek("javbus MDS", f"{b}/search/{quote('MDS')}", cookie=cookie)
        peek("javbus ARA", f"{b}/search/{quote('ARA')}", cookie=cookie)

    peek("javdb AKNR", "https://javdb.com/search?q=AKNR&f=all")
    peek("javdb ARA", "https://javdb.com/search?q=ARA&f=all")
    peek(
        "javlib AKNR",
        "https://www.javlibrary.com/cn/vl_searchbyid.php?keyword=AKNR",
    )
    peek("123av AKNR", "https://123av.com/ja/search?keyword=AKNR")
    peek("avsox AKNR", "https://avsox.click/cn/search/AKNR")
    peek("missav2 AKNR", "https://missav.ai/cn/search/AKNR")


if __name__ == "__main__":
    main()
