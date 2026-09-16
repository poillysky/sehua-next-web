# -*- coding: utf-8 -*-
"""Watch harvest log → write auto-refreshing HTML + JSON progress."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "data" / "debug" / "prefix-latest-harvest.log"
OUT_HTML = ROOT / "data" / "debug" / "prefix-latest-progress.html"
OUT_JSON = ROOT / "data" / "debug" / "prefix-latest-progress.json"

STEP_RE = re.compile(r"\[(\d+)/(\d+)\]\s+(\S+)")
OK_RE = re.compile(r"\[(\d+)/(\d+)\]\s+OK\s+(\S+)")
MISS_RE = re.compile(r"\[(\d+)/(\d+)\]\s+--\s+(\S+)")
DONE_RE = re.compile(r"DONE\s+(\S+):\s+ok=(\d+)\s+miss=(\d+)")
REGION_RE = re.compile(r"========\s+(\S+)\s+========")


def parse(text: str) -> dict:
    region = ""
    for m in REGION_RE.finditer(text):
        region = m.group(1)
    cur = total = 0
    pref = ""
    last_line = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        last_line = line
        m = STEP_RE.search(line)
        if m:
            cur, total, pref = int(m.group(1)), int(m.group(2)), m.group(3)
    oks = OK_RE.findall(text)
    misses = MISS_RE.findall(text)
    dones = {m.group(1): {"ok": int(m.group(2)), "miss": int(m.group(3))} for m in DONE_RE.finditer(text)}
    recent_ok = [m[2] for m in oks[-8:]]
    pct = round(100.0 * cur / total, 1) if total else 0.0
    return {
        "updated_at": datetime.now().strftime("%H:%M:%S"),
        "region": region,
        "current": cur,
        "total": total,
        "percent": pct,
        "prefix": pref,
        "ok_count": len(oks),
        "miss_count": len(misses),
        "recent_ok": recent_ok,
        "regions_done": dones,
        "last_line": last_line[:120],
        "finished": "wrote" in text.lower() and "prefix-latest-codes.json" in text.lower(),
    }


def render_html(p: dict) -> str:
    bar = int(p["percent"] // 2)
    bar_s = "█" * bar + "░" * (50 - bar)
    recent = "".join(f"<li>{x}</li>" for x in p["recent_ok"])
    dones = "".join(
        f"<li>{k}: ok={v['ok']} miss={v['miss']}</li>" for k, v in p["regions_done"].items()
    )
    status = "完成" if p["finished"] else "运行中"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta http-equiv="refresh" content="2"/>
<title>前缀最新番号 · 进度</title>
<style>
body{{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;background:#111;color:#eee}}
h1{{font-size:1.25rem;font-weight:600}}
.meta{{color:#999;font-size:.9rem;margin-bottom:1rem}}
.bar{{font-family:ui-monospace,Consolas,monospace;letter-spacing:.05em;font-size:1rem}}
.big{{font-size:2rem;font-weight:700;margin:.5rem 0}}
.ok{{color:#6dce8a}}.miss{{color:#e0a060}}
ul{{padding-left:1.2rem;line-height:1.6}}
code{{background:#222;padding:.1rem .35rem;border-radius:4px}}
</style>
</head>
<body>
<h1>前缀最新番号收获进度</h1>
<div class="meta">自动刷新 · 每 2 秒 · 更新于 {p['updated_at']} · 状态 <b>{status}</b></div>
<div class="big">{p['current']} / {p['total']} <span style="font-size:1rem;color:#999">({p['percent']}%)</span></div>
<div class="bar">{bar_s}</div>
<p>当前区：<code>{p['region'] or '-'}</code> · 当前前缀：<code>{p['prefix'] or '-'}</code></p>
<p><span class="ok">命中 {p['ok_count']}</span> · <span class="miss">未命中 {p['miss_count']}</span></p>
<p>最近成功：</p>
<ul>{recent or '<li>—</li>'}</ul>
<p>已完成分区：</p>
<ul>{dones or '<li>—</li>'}</ul>
<p class="meta">末行：{p['last_line']}</p>
</body>
</html>
"""


def main() -> None:
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    print(f"watching {LOG}", flush=True)
    print(f"open {OUT_HTML}", flush=True)
    while True:
        text = LOG.read_text(encoding="utf-8", errors="replace") if LOG.exists() else ""
        p = parse(text)
        OUT_JSON.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        OUT_HTML.write_text(render_html(p), encoding="utf-8")
        print(
            f"\r{p['updated_at']} {p['region']} {p['current']}/{p['total']} ({p['percent']}%) ok={p['ok_count']} miss={p['miss_count']}   ",
            end="",
            flush=True,
        )
        if p["finished"]:
            print("\nDONE", flush=True)
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
