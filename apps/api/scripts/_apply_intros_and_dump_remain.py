# -*- coding: utf-8 -*-
"""Apply batch intros; dump ALL remaining no-intro prefixes."""
from __future__ import annotations
import json, importlib, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

PATH = ROOT / "apps/maps/prefixes/prefixes.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
prefs = doc.setdefault("prefixes", {})

INTROS = {
    "MFCS": "MOON FORCE 2nd，素人个拍中出系列",
    "CADV": "クリスタル映像主线，企画・合集",
    "SUKE": "訳ありZ世代，年轻素人真实记录",
    "MADV": "クリスタル映像，企画・合集旁支",
    "DDK": "ドグマ旁支，硬核拘束・调教",
    "AMBI": "プラネットプラス，美少女・企画系",
    "HOKS": "FAプロ，剧情・人妻・熟女",
    "PTS": "ピーターズ，素人搭讪・レズ・エステ",
    "TIKB": "チキチキカマー/妄想族，恶搞・特殊向",
    "ASW": "AVS collector's，着衣フェチ・妄想系",
    "CRNX": "クリスタル映像，新线/旁支",
    "EZD": "プレステージ早期/旁支线",
    "FTHTD": "FALENO TUBE，FALENO配信系列",
    "DVDPS": "ディープス早期主线",
    "EROFV": "エロVR，VR情色系列",
    "OKAX": "おかず。，KMP企画・合集",
    "PIYO": "ひよこ，ロリ・清纯美少女",
    "CWPBD": "Caribbeancom Premium，加勒比无码高端",
    "ELO": "エロチカ，剧情・凌辱系",
    "INSTV": "HMN WORKS，いんすた素人个拍",
    "413INSTV": "いんすた，素人SNS风格中出",
    "DMOW": "ドグマ旁支，M男・痴女系",
    "KAM": "カルマ，盗撮・真实记录",
    "210AKO": "A子さん，特定素人系列",
    "AMCP": "WORLD PG，动态漫画/モーションアニメ",
    "299EWDX": "E★人妻DX，人妻素人升级版",
    "413INST": "いんすた，素人个拍中出",
    "OKAD": "おかず。，KMP企画主线",
    "ALD": "桃太郎映像出版，企画・ドキュメント",
    "BEAF": "あいすまん，素人轻松向",
    "SUJI": "姦乱者/妄想族，硬核凌辱向",
    "ACRN": "PoRO，动态漫画剧情向",
    "BLOR": "ブロッコリー/妄想族，巨乳变化球",
    "765ORECS": "俺の素人-Z- SECOND IMPACT，素人真实中出升级",
    "CMV": "シネマジック，SM・紧缚专业",
    "RVG": "グローリークエスト，硬核合集/精选",
    "DGCEMD": "セレブの友，人妻・NTR旁支",
    "GTJ": "ドグマ旁支，拘束・调教",
    "MEKO": "熟女LABO，熟女匹配・中出",
    "AGAV": "SEX Agent/妄想族，特工/剧情向",
}

for pref, intro in INTROS.items():
    ent = prefs.get(pref)
    if not isinstance(ent, dict):
        prefs[pref] = {"intro": intro}
        print(f"NEW {pref}")
    else:
        ent = dict(ent)
        ent["intro"] = intro
        prefs[pref] = ent
        print(f"SET {pref}")

doc["prefixes"] = dict(sorted(prefs.items(), key=lambda x: x[0]))
PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"applied {len(INTROS)}")

from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map", "makers_doc", "maker_intro_map", "maker_i18n_map"):
    f = getattr(maps_paths, fn, None)
    if hasattr(f, "cache_clear"):
        f.cache_clear()
import app.prefix.maker_names as mn
importlib.reload(mn)

from app.core.region_meta import REGION_ORDER, REGION_META
from app.prefix import catalog_store as store

cat = store.load_catalog(force=True)

def code_count(e):
    for k in ("code_count", "codes", "count"):
        v = e.get(k)
        if isinstance(v, int):
            return v
        if isinstance(v, list):
            return len(v)
    return 0

remain = []
for rid in REGION_ORDER:
    for pref, e in (cat["regions"][rid].get("prefixes") or {}).items():
        specific = (mn.PREFIX_INTRO.get(pref) or "").strip()
        resolved = (mn.resolve_maker_intro_for_prefix(pref) or "").strip()
        if specific:
            continue
        if resolved:
            continue  # has maker fallback — user asked 无介绍优先; dump pure none first
        maker = str((e or {}).get("maker") or "")
        n = code_count(e or {})
        remain.append((n, pref, rid, maker))

remain.sort(key=lambda x: (-x[0], x[1]))
print(f"\n=== 剩余：无专属且无回退 全部 {len(remain)} ===")
for i, (n, pref, rid, maker) in enumerate(remain, 1):
    print(f"{i:3d}. {pref} | {maker}  [{REGION_META[rid]['label']}]")
