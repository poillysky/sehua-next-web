# -*- coding: utf-8 -*-
"""Apply A-group prefix intros to prefixes.json."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "apps/maps/prefixes/prefixes.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
prefs = doc.setdefault("prefixes", {})

INTROS = {
    "LUXU": "ラグジュTV，高端素人气质美女系列",
    "SCOP": "スクープ，ドキュメント・盗撮・企画系",
    "DDT": "ドグマ主线，硬核SM・拘束・深喉",
    "DOKS": "ドグマ旁支，偏ドキュメント・企画",
    "DDB": "ドグマ旁支，偏痴女・淫语系",
    "DOCP": "DOC主线，素人・街角・企画",
    "T28": "TMA主线，コスプレ・パロディ",
    "TYOD": "乱丸主线，极度痴女・白眼高潮",
    "MDTM": "宇宙企画，美少女・制服・清纯系",
    "IENE": "アイエナジー，企画・恶作剧・挑战系",
    "CEAD": "セレブの友，人妻・熟女・NTR",
    "HJMO": "はじめ企画，企画・监控・特殊玩法",
    "WNZ": "ワンズファクトリー旧番，中出・硬核",
    "HONB": "本中旁支，中出系",
    "MCSR": "ビッグモーカル，素人・人妻・ナンパ文档",
    "MUM": "ミニマム，娇小・ロリ系",
    "KTDS": "ケートライブ，ロリ・美少女",
    "MMB": "桃太郎映像出版，企画・ドキュメント",
    "NPS": "ピーターズ，ガチナンパ・素人搭讪",
    "CRPD": "クロス，硬核・凌辱・变态",
    "BKD": "ルビー，熟女・人妻",
    "REXD": "レッド，硬核・凌辱・监禁",
    "GOJU": "五十路ん，五十路熟女专业",
    "KITAIKE": "北池袋，素人个拍・ハメ撮り",
    "OKSN": "ABC/妄想族，巨乳故事系",
    "ATFB": "Fetish Box/妄想族，恋物・着衣フェチ",
    "PKPD": "妄想族子牌，企画系",
    "CHRV": "チェリーズれぼ/妄想族，爆乳妹系",
    "SGSR": "いきなりエロざんまい，素人再包装配信",
    "229SCUTE": "S-Cute，清新美少女・恋爱系",
    "230OREC": "俺の素人-Z-，素人真实中出",
    "230ORETD": "俺の素人-Z-，素人真实中出变体",
    "292MY": "舞ワイフ，人妻出轨・中出",
    "345SIMM": "しろうとまんまん，素人轻松真实",
    "355OPCYN": "おっぱいちゃん，巨乳素人",
    "420HOI": "素人ホイホイZ，素人搭讪中出",
    "435MFC": "MOON FORCE，美形素人ハメ撮り",
    "277DCV": "ドキュメンTV，文档风格素人",
    "594PRGO": "ペロンゲリオン，特殊/恶搞向",
    "285ENDX": "E★ナンパDX，搭讪素人升级版",
    "326FCT": "黒船，偏硬核素人",
    "324SRTD": "投稿マーケット素人イッてQ，素人投稿",
}

updated = created = 0
for pref, intro in INTROS.items():
    ent = prefs.get(pref)
    if not isinstance(ent, dict):
        prefs[pref] = {"intro": intro}
        created += 1
        print(f"NEW {pref}")
    else:
        ent = dict(ent)
        ent["intro"] = intro
        prefs[pref] = ent
        updated += 1
        print(f"SET {pref}")

# keep sorted keys for stability
doc["prefixes"] = dict(sorted(prefs.items(), key=lambda x: x[0]))
PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"\nupdated={updated} created={created} total_intros_now="
      f"{sum(1 for e in doc['prefixes'].values() if isinstance(e,dict) and str(e.get('intro') or '').strip())}")

# verify via reload
import importlib
from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map", "makers_doc", "maker_i18n_map", "maker_intro_map"):
    f = getattr(maps_paths, fn, None)
    if hasattr(f, "cache_clear"):
        f.cache_clear()
import app.prefix.maker_names as mn
importlib.reload(mn)
missing = []
for pref in INTROS:
    hit = (mn.PREFIX_INTRO.get(pref) or "").strip()
    if hit != INTROS[pref]:
        missing.append((pref, hit))
print("verify mismatches:", missing or "none")
for pref in ("LUXU", "DDT", "229SCUTE", "DOCP"):
    print(f"  resolve {pref}: {mn.resolve_maker_intro_for_prefix(pref)}")
