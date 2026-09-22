# -*- coding: utf-8 -*-
"""Playwright: open sehuatang portal, pass 18-gate / safe page, dump categories."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from playwright.sync_api import sync_playwright  # noqa: E402

from app.core import outbound_http as o  # noqa: E402

OUT = ROOT / "data" / "debug"
URL = "https://www.sehuatang.net/portal.php?mod=index&mobile=2"
URL_FORUM = "https://www.sehuatang.net/forum.php?mobile=2"


def proxy_for_pw() -> dict | None:
    raw = o.resolve_scrape_proxy_url() or ""
    if not raw:
        return None
    # http://host:port or http://user:pass@host:port
    m = re.match(r"(https?)://(?:([^:@]+):([^@]+)@)?([^:/]+):(\d+)", raw)
    if not m:
        return {"server": raw}
    scheme, user, pwd, host, port = m.groups()
    cfg = {"server": f"{scheme}://{host}:{port}"}
    if user:
        cfg["username"] = user
        cfg["password"] = pwd or ""
    return cfg


def click_age_or_enter(page) -> list[str]:
    """Try common 18+ / enter buttons. Return actions taken."""
    actions = []
    candidates = [
        "text=我已年满18岁",
        "text=已满18岁",
        "text=满18岁",
        "text=同意",
        "text=进入",
        "text=ENTER",
        "text=Enter",
        "text=18+",
        "text=我同意",
        "text=确认",
        "button:has-text('18')",
        "a:has-text('18')",
        "input[value*='18']",
        "a:has-text('进入')",
        "button:has-text('进入')",
        "a:has-text('同意')",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=800):
                loc.click(timeout=2000)
                actions.append(sel)
                page.wait_for_timeout(1500)
        except Exception:
            continue
    return actions


def dump_links(page) -> list[dict]:
    return page.evaluate(
        """() => {
          const out = [];
          const seen = new Set();
          for (const a of document.querySelectorAll('a[href]')) {
            const text = (a.innerText || a.textContent || '').trim().replace(/\\s+/g, ' ');
            const href = a.getAttribute('href') || '';
            if (!text || text.length > 60) continue;
            const key = text + '|' + href;
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({ text, href });
          }
          return out;
        }"""
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    proxy = proxy_for_pw()
    print("proxy", proxy, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            proxy=proxy,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                "Mobile/15E148 Safari/604.1"
            ),
            viewport={"width": 390, "height": 844},
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(45000)

        print("goto", URL, flush=True)
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        title = page.title()
        html1 = page.content()
        (OUT / "sht_pw_step1.html").write_text(html1, encoding="utf-8")
        print(f"step1 title={title!r} len={len(html1)} url={page.url}", flush=True)

        # wait for 荷马/safe scripts or CF
        for i in range(20):
            html = page.content()
            if "荷马" in html or "safeid" in html:
                print(f"  waiting safe/荷马… {i}", flush=True)
                page.wait_for_timeout(1500)
                continue
            if "challenge-platform" in html or "Just a moment" in html:
                print(f"  waiting CF… {i}", flush=True)
                page.wait_for_timeout(2000)
                continue
            break

        acts = click_age_or_enter(page)
        print("age clicks", acts, flush=True)
        page.wait_for_timeout(2500)

        # if still tiny, try forum.php
        html2 = page.content()
        (OUT / "sht_pw_step2.html").write_text(html2, encoding="utf-8")
        print(f"step2 title={page.title()!r} len={len(html2)} url={page.url}", flush=True)

        if len(html2) < 8000:
            print("goto forum", flush=True)
            page.goto(URL_FORUM, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            for i in range(15):
                html = page.content()
                if "荷马" in html or "safeid" in html or "Just a moment" in html:
                    page.wait_for_timeout(2000)
                    continue
                break
            acts2 = click_age_or_enter(page)
            print("age clicks2", acts2, flush=True)
            page.wait_for_timeout(2500)

        html = page.content()
        (OUT / "sht_pw_final.html").write_text(html, encoding="utf-8")
        print(f"final title={page.title()!r} len={len(html)} url={page.url}", flush=True)

        links = dump_links(page)
        # category-ish filter
        keys = (
            "区",
            "码",
            "素人",
            "FC2",
            "国产",
            "欧美",
            "写真",
            "原创",
            "BT",
            "高清",
            "字幕",
            "动漫",
            "主播",
            "无码",
            "有码",
            "亚洲",
            "VR",
            "4K",
            "韩国",
            "合集",
            "三级",
        )
        cats = [x for x in links if any(k in x["text"] for k in keys)]
        # also board links fid=
        boards = [
            x
            for x in links
            if "fid=" in x["href"] or "forum-" in x["href"] or "typeid=" in x["href"]
        ]

        report = {
            "url": page.url,
            "title": page.title(),
            "html_len": len(html),
            "cookies": context.cookies(),
            "category_links": cats[:200],
            "board_links": boards[:300],
            "all_links_sample": links[:100],
        }
        (OUT / "sht_pw_categories.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("cats", len(cats), "boards", len(boards), flush=True)
        for c in cats[:60]:
            print(f"  {c['text'][:28]:28} {c['href'][:90]}", flush=True)

        # screenshot
        page.screenshot(path=str(OUT / "sht_pw.png"), full_page=True)
        browser.close()
        print("saved", OUT / "sht_pw_categories.json", flush=True)


if __name__ == "__main__":
    main()
