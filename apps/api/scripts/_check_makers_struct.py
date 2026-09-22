import json
from pathlib import Path
ROOT = Path(r"E:\Project\sehua-next-web")
makers = json.loads((ROOT/"apps/maps/makers/makers.json").read_text(encoding="utf-8"))
print("top keys", list(makers.keys())[:20])
mm = makers.get("makers") or makers
print("n makers", len(mm))
# find Madonna / S1 / PRESTIGE
for needle in ["Madonna", "麦当娜", "S1", "PRESTIGE", "MOODYZ", "溜池", "Tameike", "SOD"]:
    hits = [k for k in mm if needle.lower() in k.lower()]
    print(needle, "->", hits[:8])
# sample one known
for k in list(mm.keys())[:2]:
    print("KEY", k, "=>", json.dumps(mm[k], ensure_ascii=False)[:300])
# how many have intro
ok=0; weak=0; miss=0
for k,v in mm.items():
    if not isinstance(v,dict):
        miss+=1; continue
    intro = (v.get("intro") or "").strip()
    i18n = v.get("i18n") or {}
    zh = ""
    if isinstance(i18n, dict):
        zh_part = i18n.get("zh") or i18n.get("zh-CN") or {}
        if isinstance(zh_part, dict):
            zh = (zh_part.get("intro") or zh_part.get("name") or "").strip()
        elif isinstance(zh_part, str):
            zh = zh_part.strip()
    text = intro or zh
    card = v.get("card") or {}
    colloq = ""
    if isinstance(card, dict):
        colloq = (card.get("zh") or card.get("name") or card.get("colloquial") or "").strip()
    if text and "公开资料有限" not in text and len(text)>=8:
        ok+=1
    elif text:
        weak+=1
    else:
        miss+=1
print("maker intro ok/weak/miss", ok, weak, miss)
# card presence
has_card=sum(1 for v in mm.values() if isinstance(v,dict) and v.get("card"))
print("has_card", has_card, "/", len(mm))
