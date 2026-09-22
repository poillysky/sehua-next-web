# -*- coding: utf-8 -*-
"""Apply remaining 84 prefix intros."""
from __future__ import annotations
import json, importlib, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

PATH = ROOT / "apps/maps/prefixes/prefixes.json"
doc = json.loads(PATH.read_text(encoding="utf-8"))
prefs = doc.setdefault("prefixes", {})

INTROS = {
    "SPZ": "ネクスト，素人・企画系",
    "ADZ": "クリスタル映像，企画・合集旁支",
    "534IND": "インディ，素人独立制作中出",
    "MMKZ": "MARRION，巨乳・单体向",
    "494SIKA": "白完素人，素人完整版系列",
    "AJVR": "アリスJAPAN VR系列",
    "FERA": "センタービレッジ，熟女人妻系",
    "HOMA": "h.m.p DORAMA，剧情向",
    "SYKH": "有閑ミセス/エマニエル，优雅人妻",
    "ANND": "アンナと花子，女同专业",
    "MKON": "かぐや姫Pt，美少女清新系",
    "MXBD": "マキシング，美少女单体",
    "MMGH": "SODクリエイト，魔镜号等企画",
    "NACX": "プラネットプラス，美少女企画",
    "OKB": "親父の個撮，着衣フェチ（ブルマ等）",
    "JUTA": "熟女JAPAN，熟女专业",
    "KCDA": "デジタルアーク，痴女・ギャル",
    "230OREMO": "俺の素人-Z-，素人真实中出",
    "NWF": "ワンズファクトリー，中出硬核",
    "318LADY": "LadyHunter，淑女猎人搭讪",
    "PYM": "ピーターズ，素人搭讪旁支",
    "DRPT": "電脳ラスプーチン，特殊题材",
    "ULT": "DOC，素人・街角企画",
    "URKK": "unfinished，美少女单体",
    "YMDS": "桃太郎映像出版，企画文档",
    "DNJR": "犬/妄想族，特殊向",
    "DSAM": "独占素人，素人独占配信",
    "MADM": "クリスタル映像，企画旁支",
    "ZUKO": "ズッコン/バッコン，乱交多人",
    "DSE": "ドリームチケット，企画系",
    "PARM": "アロマ企画，恋物・着衣",
    "CLO": "ケラ工房，小众特殊",
    "FCP": "DOC，素人企画旁支",
    "413INSTC": "いんすた，素人个拍变体",
    "NTRD": "中嶋興業，NTR・调教",
    "DWD": "ドグマ，痴女・淫语旁支",
    "AQSH": "アクアモール/エマニエル，人妻熟女",
    "ONSG": "ゲインコーポレーション，小众",
    "348NTR": "NTR.net，绿帽题材素人",
    "FWAY": "FAIR＆WAY，巨乳单体",
    "MMUS": "MARRION，巨乳旁支",
    "491TKWA": "ときわ映像，素人个拍",
    "DOA": "Bermuda，陵辱・紧缚",
    "DVEH": "ディープス，企画旁支",
    "JYMA": "熟女はつらいよ/熟女卍，熟女真实",
    "KBKD": "センタービレッジ，熟女旁支",
    "IBW": "I.B.WORKS，ロリ・制服美少女",
    "SGKI": "SHIGEKI，忍耐高潮企画",
    "BBTU": "ドグマ，爆乳・特殊旁支",
    "BEB": "痴女ヘブン，早期痴女线",
    "MESU": "センタービレッジ，熟女旁支",
    "NVH": "グローリークエスト，硬核旁支",
    "109IENFH": "IENFH（MGS素人），MGS素人系列",
    "HUBLK": "Hunter，企画・逆袭场景",
    "DVRT": "ディープス，企画旁支",
    "YUJ": "アタッカーズ，凌辱剧情",
    "MIBB": "ミル，小众",
    "DSOD": "ダスッ！，早期/旁支",
    "VENZ": "VENUS，人妻熟女",
    "MOON": "YONAKA，夜间背德剧情",
    "DANDYA": "DANDY，街头恶作剧旁支",
    "PRVR": "プレミアム VR系列",
    "PRTD": "プレミアム，剧情旁支",
    "SSHN": "SODクリエイト，旁支",
    "PID": "プレミアム，早期/旁支",
    "STZY": "SODクリエイト，旁支",
    "OPEN": "SODクリエイト，早期旁支",
    "FTAV": "SODクリエイト，旁支",
    "HISN": "SODクリエイト，旁支",
    "PRWF": "プレミアム，新线/旁支",
    "SYBI": "SODクリエイト，旁支",
    "EMOIS": "SODクリエイト，情感青春旁支",
    "KKBT": "SODクリエイト，旁支",
    "HSAM": "SODクリエイト，旁支",
    "SDABP": "SODクリエイト，青春线旁支",
    "FAD": "FAプロ，剧情人妻",
    "SETH": "SODクリエイト，旁支",
    "TIGR": "SODクリエイト，旁支",
    "083PPP": "パラダイステレビ，笑えるエロ企画",
    "PARATHD": "パラダイステレビ，频道配信主线",
    "ISCR": "SODクリエイト，旁支",
    "SDVS": "SODクリエイト，旁支",
    "ARSO": "Around，Around年龄层人妻",
    "SODVR": "SODクリエイト VR总称",
}

updated = created = 0
for pref, intro in INTROS.items():
    ent = prefs.get(pref)
    if not isinstance(ent, dict):
        prefs[pref] = {"intro": intro}
        created += 1
    else:
        ent = dict(ent)
        ent["intro"] = intro
        prefs[pref] = ent
        updated += 1

doc["prefixes"] = dict(sorted(prefs.items(), key=lambda x: x[0]))
PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
print(f"applied={len(INTROS)} updated={updated} created={created}")

from app.core import maps_paths
for fn in ("prefixes_doc", "prefix_intro_map", "maker_intro_map", "makers_doc", "maker_i18n_map"):
    f = getattr(maps_paths, fn, None)
    if hasattr(f, "cache_clear"):
        f.cache_clear()
import app.prefix.maker_names as mn
importlib.reload(mn)

from app.core.region_meta import REGION_ORDER
from app.prefix import catalog_store as store
cat = store.load_catalog(force=True)
none = []
for rid in REGION_ORDER:
    for pref, e in (cat["regions"][rid].get("prefixes") or {}).items():
        specific = (mn.PREFIX_INTRO.get(pref) or "").strip()
        resolved = (mn.resolve_maker_intro_for_prefix(pref) or "").strip()
        if not specific and not resolved:
            none.append(pref)
bad = [p for p, t in INTROS.items() if (mn.PREFIX_INTRO.get(p) or "").strip() != t]
print("verify bad:", bad or "none")
print(f"PREFIX_INTRO size={len(mn.PREFIX_INTRO)}")
print(f"remain no-specific+no-resolve={len(none)}")
