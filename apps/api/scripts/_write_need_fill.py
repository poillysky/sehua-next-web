# -*- coding: utf-8 -*-
from pathlib import Path
import json

d = json.loads(Path("scripts/_scrap_prefix_intro_todo.json").read_text(encoding="utf-8"))

# compact: all prefixes sorted by count
lines = ["前缀\t数量\t厂牌Key\tcard\t前缀介绍\t厂牌介绍"]
for x in sorted(d["prefixes"], key=lambda i: (-i["count"], i["prefix"])):
    lines.append(
        f"{x['prefix']}\t{x['count']}\t{x['maker_key'] or '-'}\t{x['card'] or '-'}\t{x['prefix_intro']}\t{x['maker_intro']}"
    )
Path("scripts/_scrap_prefix_all.tsv").write_text("\n".join(lines), encoding="utf-8")

# no_maker + weak makers first for user
need_m = [m for m in d["makers"] if m["maker_intro"] != "ok"]
need_p = [p for p in d["prefixes"] if p["prefix_intro"] != "ok"]
lines2 = [
    f"# 优先待补",
    f"厂牌需补 {len(need_m)}（weak {sum(1 for m in need_m if m['maker_intro']=='weak')} / 无厂牌 {sum(1 for m in need_m if m['maker_intro']=='no_maker')}）",
    f"前缀需补 {len(need_p)}（weak {sum(1 for p in need_p if p['prefix_intro']=='weak')} / missing {sum(1 for p in need_p if p['prefix_intro']=='missing')}）",
    "",
    "## 无厂牌映射（先定厂牌名+俗称+介绍）",
]
for m in need_m:
    if m["maker_intro"] != "no_maker":
        continue
    ps = ", ".join(f"{p}×{c}" for p, c, _ in m["prefixes"])
    lines2.append(f"- {m['maker_key']} → {ps}")
lines2.append("")
lines2.append("## 厂牌介绍偏短/需加厚（MAKER|Key|card|介绍）")
for m in need_m:
    if m["maker_intro"] != "weak":
        continue
    ps = ", ".join(f"{p}×{c}" for p, c, _ in m["prefixes"])
    lines2.append(f"MAKER|{m['maker_key']}|{m['card']}|  # 现有：{m['maker_text']} | {ps}")
lines2.append("")
lines2.append("## 前缀介绍 missing（前缀|介绍）")
for p in sorted(need_p, key=lambda i: (-i["count"], i["prefix"])):
    if p["prefix_intro"] != "missing":
        continue
    lines2.append(f"{p['prefix']}|  # ×{p['count']} {p['maker_key'] or p['maker_raw'] or '-'}")
lines2.append("")
lines2.append("## 前缀介绍 weak（前缀|介绍）按数量")
for p in sorted(need_p, key=lambda i: (-i["count"], i["prefix"])):
    if p["prefix_intro"] != "weak":
        continue
    lines2.append(
        f"{p['prefix']}|  # ×{p['count']} {p['maker_key'] or '-'} 现有：{p['prefix_text']}"
    )

Path("scripts/_scrap_need_fill.md").write_text("\n".join(lines2), encoding="utf-8")
print("ok", len(d["prefixes"]), len(need_m), len(need_p))
