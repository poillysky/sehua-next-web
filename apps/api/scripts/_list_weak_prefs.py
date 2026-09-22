# -*- coding: utf-8 -*-
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
d = json.loads(Path("scripts/_scrap_prefix_intro_todo.json").read_text(encoding="utf-8"))
weak = [p for p in d["prefixes"] if p["prefix_intro"] != "ok"]
print("weak", len(weak))
for p in sorted(weak, key=lambda x: (-x["count"], x["prefix"])):
    t = p["prefix_text"]
    print(f"{p['prefix']}|{p['count']}|len={len(t)}|{t}")
