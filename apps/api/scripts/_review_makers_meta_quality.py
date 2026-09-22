# -*- coding: utf-8 -*-
"""Flag weak / suspicious maker intros and colloquial names for user review."""
from __future__ import annotations
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "apps/maps/makers/makers.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
makers = doc.get("makers") or {}

WEAK_INTRO = re.compile(
    r"较少见|小众厂牌|需具体|由前缀目录同步|风格多元$|风格多元。$|综合|待确认|不明"
)
# Known contested / rough translations from our batches
SUSPECT_KEYS = {
    "犬马", "理念口袋", "菲奇", "中心村", "欧派", "印斯塔", "彼得斯", "大莫卡",
    "光荣任务", "施虐村", "天堂电视", "小菜", "突然エロ盛宴", "业力",
    "水上商场", "冰淇淋男", "情色卡", "迷你姆", "有问题的Z世代",
    "投稿市场素人去Q", "胸部酱", "A子桑", "队小子", "肛门视频",
    "数字方舟", "红热果酱", "精液狂热",
}

weak = []
suspect_card = []
short_intro = []
no_zh_but_ja = []
dup_intro = {}

for key, ent in makers.items():
    if not isinstance(ent, dict):
        continue
    card = str(ent.get("card") or "").strip()
    intro = str(ent.get("intro") or "").strip()
    i18n = ent.get("i18n") or []
    if not intro:
        weak.append((key, card, "(无介绍)"))
        continue
    if WEAK_INTRO.search(intro) or len(intro) < 12:
        weak.append((key, card, intro))
    if len(intro) < 18 and key not in [w[0] for w in weak]:
        short_intro.append((key, card, intro))
    # card matches suspect colloquial
    for s in SUSPECT_KEYS:
        if s in card or any(s in str(x) for x in i18n):
            suspect_card.append((key, card, intro[:60]))
            break
    # dup intros
    dup_intro.setdefault(intro, []).append(key)

print(f"makers: {len(makers)}")
print(f"\n=== 介绍偏弱/占位 ({len(weak)}) ===")
for i, (k, c, intro) in enumerate(sorted(weak, key=lambda x: x[0])[:40], 1):
    print(f"{i:2d}. [{k}] card={c} | {intro}")
if len(weak) > 40:
    print(f"… +{len(weak)-40}")

print(f"\n=== 译名可能需打磨 ({len(suspect_card)}) ===")
seen = set()
for k, c, intro in suspect_card:
    if k in seen:
        continue
    seen.add(k)
    print(f"- [{k}] card={c} | {intro}…")

print("\n=== 完全相同介绍（可能敷衍）===")
n_dup = 0
for intro, keys in sorted(dup_intro.items(), key=lambda x: -len(x[1])):
    if len(keys) < 3:
        continue
    n_dup += 1
    if n_dup <= 8:
        print(f"×{len(keys)}: {intro[:50]}…")
        print(f"   keys: {', '.join(keys[:8])}")
print(f"dup groups (>=3): {n_dup}")
