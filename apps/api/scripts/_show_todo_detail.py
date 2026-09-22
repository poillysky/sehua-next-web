import json
from pathlib import Path
ROOT = Path(r"E:\Project\sehua-next-web")
data = json.loads((ROOT/"apps/api/scripts/_scrap_prefix_intro_todo.json").read_text(encoding="utf-8"))
makers = data["makers"]
# show weak maker intros
print("=== WEAK/MISSING MAKER INTROS (full text) ===")
for m in makers:
    if m["maker_intro"] == "ok":
        continue
    print(f"\n[{m['maker_intro']}] {m['maker_key']} card={m['card']!r} codes={m['code_count']} prefs={m['prefix_count']}")
    print(f"  intro: {m['maker_text']!r}")
    print(f"  prefixes: {', '.join(f'{p}×{c}' for p,c,_ in m['prefixes'])}")

# prefixes missing only
prefs = data["prefixes"]
miss = [x for x in prefs if x["prefix_intro"]=="missing"]
print("\n=== MISSING PREFIX INTRO ===")
for x in miss:
    print(f"{x['prefix']}\t{x['count']}\t{x['maker_key'] or x['maker_raw']}")
