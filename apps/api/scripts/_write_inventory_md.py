# -*- coding: utf-8 -*-
from pathlib import Path
import json

d = json.loads(Path("scripts/_scrap_prefix_intro_todo.json").read_text(encoding="utf-8"))
lines = [
    "# 刮削库实际有番号 — 前缀×厂牌清单",
    "",
    f"- 前缀：**{len(d['prefixes'])}**",
    f"- 番号夹：**{sum(p['count'] for p in d['prefixes'])}**",
    f"- 厂牌：**{len(d['makers'])}**",
    f"- 前缀介绍：ok {sum(1 for p in d['prefixes'] if p['prefix_intro']=='ok')} / weak {sum(1 for p in d['prefixes'] if p['prefix_intro']=='weak')} / missing {sum(1 for p in d['prefixes'] if p['prefix_intro']=='missing')}",
    f"- 厂牌介绍：ok {sum(1 for m in d['makers'] if m['maker_intro']=='ok')} / weak {sum(1 for m in d['makers'] if m['maker_intro']=='weak')} / no_maker {sum(1 for m in d['makers'] if m['maker_intro']=='no_maker')}",
    "",
    "回填格式：",
    "- 厂牌：`MAKER|Key|俗称card|介绍`",
    "- 前缀：`前缀|介绍`",
    "",
]
for m in d["makers"]:
    lines.append(
        f"## {m['maker_key']} · card=`{m['card'] or '—'}` · 厂牌介绍={m['maker_intro']} · {m['prefix_count']}前缀/{m['code_count']}条"
    )
    if m.get("maker_text"):
        lines.append(f"> 现有：{m['maker_text']}")
    lines.append(f"MAKER|{m['maker_key']}|{m['card']}|")
    for pref, cnt, pi in m["prefixes"]:
        ent = next((x for x in d["prefixes"] if x["prefix"] == pref), None)
        ptext = (ent or {}).get("prefix_text") or ""
        tag = "" if pi == "ok" else f" ⚠{pi}"
        if ptext:
            lines.append(f"# {pref}×{cnt}{tag} 现有：{ptext}")
        else:
            lines.append(f"# {pref}×{cnt}{tag}")
        lines.append(f"{pref}|")
    lines.append("")

out = Path("scripts/_scrap_fill_template.md")
out.write_text("\n".join(lines), encoding="utf-8")
print("wrote", out, "bytes", out.stat().st_size)
