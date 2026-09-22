# -*- coding: utf-8 -*-
"""Add EN aliases for JET / Momotaro so studio wall blurbs resolve."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "apps/maps/makers/makers.json"

doc = json.loads(PATH.read_text(encoding="utf-8"))
aliases = doc.setdefault("aliases", {})
makers = doc.setdefault("makers", {})

ALIASES = {
    "JET Eizou": "JET映像",
    "JET Eizou / JET映像": "JET映像",
    "Momotaro": "桃太郎映像",
    "Momotaro / 桃太郎映像": "桃太郎映像",
    "TME": "桃太郎映像",
}
for a, c in ALIASES.items():
    aliases[a] = c

# 英文名写入 i18n，便于索引注册
jet = makers.get("JET映像")
if isinstance(jet, dict):
    jet["i18n"] = ["JET映像", "JET映像", "JET Eizou"]
momo = makers.get("桃太郎映像")
if isinstance(momo, dict):
    momo["i18n"] = ["桃太郎映像出版", "桃太郎映像出版", "Momotaro"]

PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("aliases added", list(ALIASES))
print("JET i18n", jet.get("i18n") if jet else None)
print("桃太郎 i18n", momo.get("i18n") if momo else None)
