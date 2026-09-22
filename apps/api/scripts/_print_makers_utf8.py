# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
data = json.loads(Path("scripts/_scrap_prefix_intro_todo.json").read_text(encoding="utf-8"))
makers = data["makers"]
prefs = data["prefixes"]
print(f"PREFIXES={len(prefs)} CODES={sum(p['count'] for p in prefs)} MAKERS={len(makers)}")
print(
    "PREFIX_STATUS",
    {k: sum(1 for p in prefs if p["prefix_intro"] == k) for k in ["ok", "weak", "missing"]},
)
print(
    "MAKER_STATUS",
    {k: sum(1 for m in makers if m["maker_intro"] == k) for k in ["ok", "weak", "no_maker"]},
)
print("---MAKERS---")
for m in makers:
    ps = " ".join(f"{p}x{c}" for p, c, _ in m["prefixes"])
    print(
        f"{m['maker_key']}|{m['card']}|{m['maker_intro']}|{m['prefix_count']}|{m['code_count']}|{ps}"
    )
print("---NEED_PREFIX---")
for x in sorted(
    [p for p in prefs if p["prefix_intro"] != "ok"],
    key=lambda i: (-i["count"], i["prefix"]),
):
    print(
        f"{x['prefix']}|{x['count']}|{x['maker_key'] or x['maker_raw'] or '-'}|{x['prefix_intro']}|{x['prefix_text']}"
    )
