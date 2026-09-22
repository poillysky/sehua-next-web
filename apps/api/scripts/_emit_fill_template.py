# -*- coding: utf-8 -*-
"""Emit fillable paste blocks for user."""
import json
from pathlib import Path
ROOT = Path(r"E:\Project\sehua-next-web")
data = json.loads((ROOT/"apps/api/scripts/_scrap_prefix_intro_todo.json").read_text(encoding="utf-8"))
makers = data["makers"]
prefs = data["prefixes"]

# Write a clean fill template the user can edit and send back
lines = []
lines.append("# 刮削库实际有番号 — 待补模板")
lines.append("")
lines.append(f"前缀 {len(prefs)} 个 / 番号夹 {sum(p['count'] for p in prefs)} / 厂牌 {len(makers)} 个")
lines.append("")
lines.append("回填格式：")
lines.append("- 厂牌行：`MAKER|俗称card|厂牌介绍`")
lines.append("- 前缀行：`前缀|前缀介绍`（跟在对应厂牌下面）")
lines.append("")

for m in makers:
    mk = m["maker_key"]
    card = m["card"] or ""
    mi = m["maker_intro"]
    exist = m["maker_text"] or ""
    lines.append(f"## {mk}  ({m['prefix_count']}前缀 / {m['code_count']}条)  [{mi}]")
    if exist:
        lines.append(f"# 现有厂牌介绍：{exist}")
    lines.append(f"MAKER|{mk}|{card}|")
    for pref, cnt, pi in m["prefixes"]:
        # find existing prefix text
        ent = next((x for x in prefs if x["prefix"]==pref), None)
        ptext = (ent or {}).get("prefix_text") or ""
        tag = "" if pi=="ok" else f" [{pi}]"
        if ptext:
            lines.append(f"# {pref}×{cnt}{tag} 现有：{ptext}")
        else:
            lines.append(f"# {pref}×{cnt}{tag}")
        lines.append(f"{pref}|")
    lines.append("")

path = ROOT/"apps/api/scripts/_scrap_fill_template.txt"
path.write_text("\n".join(lines), encoding="utf-8")
print("wrote", path, "lines", len(lines))

# Also emit chat-friendly summary: maker list + all prefixes one per line with count
print("\n===== CHAT: ALL MAKERS =====")
for m in makers:
    prefs_s = " ".join(f"{p}×{c}" for p,c,_ in m["prefixes"])
    print(f"{m['maker_key']}\tcard={m['card'] or '-'}\tintro={m['maker_intro']}\t{prefs_s}")

print("\n===== CHAT: ALL PREFIXES (prefix\\tcount\\tmaker) =====")
for x in sorted(prefs, key=lambda i: (-i["count"], i["prefix"])):
    print(f"{x['prefix']}\t{x['count']}\t{x['maker_key'] or x['maker_raw'] or '-'}\tp={x['prefix_intro']}")
