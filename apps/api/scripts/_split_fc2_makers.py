# -*- coding: utf-8 -*-
import json
from pathlib import Path

p = Path(r"E:/Project/sehua-next-web/apps/maps/makers/makers.json")
doc = json.loads(p.read_text(encoding="utf-8"))
aliases = doc.setdefault("aliases", {})
makers = doc.setdefault("makers", {})

for a in ["FC2 PPV", "FC2PPV", "FC2-PPV", "FC2_PPV"]:
    if aliases.get(a) == "FC2":
        del aliases[a]

makers["FC2-PPV"] = {
    "card": "FC2-PPV",
    "i18n": ["FC2-PPV / 付费同人", "FC2-PPV", "FC2-PPV"],
    "intro": "FC2 付费同人（PPV）配信，按作品贩卖的素人・个人撮影为主。",
}
aliases["FC2PPV"] = "FC2-PPV"
aliases["FC2 PPV"] = "FC2-PPV"
aliases["FC2_PPV"] = "FC2-PPV"

fc2 = makers.get("FC2") if isinstance(makers.get("FC2"), dict) else {}
fc2["card"] = "FC2"
fc2["i18n"] = ["FC2 / 同人平台", "FC2", "FC2"]
fc2["intro"] = "FC2 同人平台，个人撮影与素人配信（非 PPV 前缀）。"
makers["FC2"] = fc2

p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print("ok", "FC2-PPV" in makers, aliases.get("FC2PPV"))
