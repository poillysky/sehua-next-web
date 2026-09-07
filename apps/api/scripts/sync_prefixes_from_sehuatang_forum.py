# -*- coding: utf-8 -*-
"""从色花堂论坛多级子分类 + 有码列表页合并前缀进七区 catalog/seed。"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from bs4 import BeautifulSoup  # noqa: E402

from app import outbound_http as o  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app.region_meta import REGION_META, REGION_ORDER, std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"
FORUM_TS = ROOT / "apps" / "web" / "src" / "config" / "sehuatangForum.ts"
LIVE = ROOT / "data" / "_debug" / "sht_forum_types_live.json"
REPORT = ROOT / "data" / "_debug" / "prefix-sehuatang-forum-sync.json"

SRC = "sehuatangForum"
TAG = "色花堂论坛子分类"

# 子分类显示名 → (region, prefix, maker?)；非字母数字名需映射
NAME_MAP: dict[str, tuple[str, str, str]] = {
    "FC2PPV": ("fc2", "FC2PPV", "FC2 PPV"),
    "FC2": ("fc2", "FC2", "FC2"),
    "HEYZO": ("japan_uncensored", "HEYZO", "HEYZO"),
    "加勒比系列": ("japan_uncensored", "CARIB", "Caribbeancom"),
    "加勒比系": ("japan_uncensored", "CARIB", "Caribbeancom"),
    "加勒比PPV": ("japan_uncensored", "CARIBPR", "Caribbeancom Premium"),
    "一本道系列": ("japan_uncensored", "1PON", "1pondo"),
    "一本道系": ("japan_uncensored", "1PON", "1pondo"),
    "10musume": ("japan_uncensored", "10MU", "10musume"),
    "10musu": ("japan_uncensored", "10MU", "10musume"),
    "pacoma": ("japan_uncensored", "PACO", "Pacopacomama"),
    "heyppv": ("japan_uncensored", "HEYPPV", "HeyPPV"),
    "xxx-av": ("japan_uncensored", "XXXAV", "xxx-av"),
    "エッチな0930": ("japan_uncensored", "H0930", "エッチな0930"),
    "エッチな4610": ("japan_uncensored", "H4610", "エッチな4610"),
    "金髪天國": ("japan_uncensored", "KIN8", "Kin8tengoku"),
    "legsjapan": ("japan_uncensored", "LEGSJAPAN", "Legs Japan"),
    "uralesbian": ("japan_uncensored", "URALESBIAN", "Ura Lesbian"),
    "fellatiojapan": ("japan_uncensored", "FELLATIOJAPAN", "Fellatio Japan"),
    "spermmania": ("japan_uncensored", "SPERMMANIA", "Sperm Mania"),
    "handjobjapan": ("japan_uncensored", "HANDJOBJAPAN", "Handjob Japan"),
    "urabukkake": ("japan_uncensored", "URABUKKAKE", "Ura Bukkake"),
    "sm-miracle": ("japan_uncensored", "SMMIRACLE", "sm-miracle"),
    "roselip-fetish": ("japan_uncensored", "ROSELIP", "roselip-fetish"),
    "japornxxx": ("japan_uncensored", "JAPORNXXX", "japornxxx"),
    "cospuri": ("japan_uncensored", "COSPURI", "cospuri"),
    "女体のしんぴ": ("japan_uncensored", "NYOSHIN", "女体のしんぴ"),
    # 素人有码系列
    "SIRO": ("japan_amateur", "SIRO", "シロウトTV"),
    "259LUXU": ("japan_amateur", "259LUXU", "ラグジュTV"),
    "300MIUM": ("japan_amateur", "300MIUM", "みうめい"),
    "332NAMA": ("japan_amateur", "332NAMA", ""),
    "326EVA": ("japan_amateur", "326EVA", ""),
    "328HMDN": ("japan_amateur", "328HMDN", ""),
    "336KNB": ("japan_amateur", "336KNB", ""),
    "200GANA": ("japan_amateur", "200GANA", "ナンパTV"),
    "300MAAN": ("japan_amateur", "300MAAN", "マジ軟派"),
    "300NTK": ("japan_amateur", "300NTK", ""),
    "390JAC": ("japan_amateur", "390JAC", "Jackson"),
    "326SCP": ("japan_amateur", "326SCP", ""),
    "230OREX": ("japan_amateur", "230OREX", "俺の素人"),
    "G-area": ("japan_amateur", "GAREA", "G-area"),
    "Mywife": ("japan_amateur", "MYWIFE", "Mywife"),
    "S-cute": ("japan_amateur", "SCUTE", "S-Cute"),
    "himemix": ("japan_amateur", "HIMEMIX", "himemix"),
    "siro-hame": ("japan_amateur", "SIROHAME", "siro-hame"),
    "getchu": ("japan_amateur", "GETCHU", "getchu"),
    "r-file": ("japan_amateur", "RFILE", "r-file"),
    "giga-web": ("japan_amateur", "GIGAWEB", "giga-web"),
}

# 题材/非前缀子类：跳过（含「栏目名≠番号前缀」）
SKIP_NAMES = {
    "国产无码",
    "主播录制",
    "360水滴",
    "厕所偷拍",
    "店長推薦",
    "无码流出",
    "无码破解",
    "盗窃系列",
    "其他系列",
    "有码",
    "无码",
    "有码高清",
    "无码高清",
    "日本写真",
    "国产写真",
    # 论坛栏目名，不是 CODE-123 前缀
    "东京热",
    "熟女俱樂部",
    "人妻斬り",
    "本生素人TV",
    "レズのしんぴ",
    "knights-visual",
}

BLOCK = {
    "HTTP",
    "HTTPS",
    "HTML",
    "MP4",
    "DVD",
    "HD",
    "FHD",
    "VIP",
    "BT",
    "MKV",
    "WWW",
    "COM",
    "NET",
    "ORG",
    "CDN",
    "IMG",
    "PIC",
    "URL",
    "API",
    "AND",
    "THE",
    "FOR",
    "FROM",
    "WITH",
    "THIS",
    "THAT",
    "DATE",
    "TIME",
    "YEAR",
    "PAGE",
    "HOME",
    "NULL",
}

CODE_RE = re.compile(
    r"(?<![A-Z0-9])([0-9]{0,3}[A-Z]{2,12})[-_ ]?(\d{2,5})(?![A-Z0-9])",
    re.I,
)


def clean_prefix(raw: str) -> str:
    p = re.sub(r"[^A-Z0-9]", "", std_prefix(raw).replace("-", ""))
    if len(p) < 2 or len(p) > 14:
        return ""
    if p in BLOCK or p.isdigit():
        return ""
    return p


def strip_count(name: str) -> str:
    # 仅去掉「空格+帖数」尾缀（如 FC2PPV 20746）；勿吃掉 FC2 / H0930 末尾数字
    return re.sub(r"\s+\d+\s*$", "", (name or "").strip()).strip()


def load_forum_types() -> list[dict[str, Any]]:
    """优先 live JSON；否则从 sehuatangForum.ts 抽 types。"""
    if LIVE.exists():
        return json.loads(LIVE.read_text(encoding="utf-8"))
    text = FORUM_TS.read_text(encoding="utf-8")
    boards: list[dict[str, Any]] = []
    for m in re.finditer(
        r'board\((\d+),\s*"([^"]+)"(?:,\s*\[(.*?)\])?\)',
        text,
        re.S,
    ):
        fid, bname, body = m.group(1), m.group(2), m.group(3) or ""
        types = []
        for tm in re.finditer(r'\["(\d+)",\s*"([^"]+)"\]', body):
            types.append({"typeid": tm.group(1), "name": tm.group(2)})
        boards.append({"fid": int(fid), "board": bname, "types": types})
    return boards


def resolve_type(name: str, *, board_fid: int) -> tuple[str, str, str] | None:
    raw = strip_count(name)
    if not raw or raw in SKIP_NAMES or "三级" in raw or "四级" in raw or "写真" in raw:
        return None
    if raw in NAME_MAP:
        return NAME_MAP[raw]
    # 纯前缀形态：SIRO / 259LUXU / pacoma
    key = clean_prefix(raw)
    if not key:
        return None
    if board_fid == 104 or re.match(r"^\d{2,3}[A-Z]", key):
        return ("japan_amateur", key, "")
    if board_fid == 36:
        if key.startswith("FC2"):
            return ("fc2", key, "")
        return ("japan_uncensored", key, "")
    return None


def merge_one(
    bucket: dict[str, Any],
    rid: str,
    prefix: str,
    *,
    maker: str,
    note_tag: str,
) -> str:
    """返回 added|touched|skip"""
    key = clean_prefix(prefix)
    if not key:
        return "skip"
    if key in bucket:
        cur = bucket[key]
        srcs = set(cur.get("sources") or [])
        srcs.add(SRC)
        cur["sources"] = sorted(srcs)
        if maker and not cur.get("maker"):
            cur["maker"] = maker
        notes = str(cur.get("notes") or "")
        if note_tag not in notes:
            cur["notes"] = (notes + f" · {note_tag}").strip(" ·")
        serials = list(cur.get("serials") or [])
        bucket[key] = store._normalize_prefix_entry(key, {**cur, "serials": serials})
        if serials:
            bucket[key]["serials"] = serials
            bucket[key] = store._normalize_prefix_entry(key, bucket[key])
        return "touched"
    pad = 0 if rid in {"fc2", "china", "western", "japan_uncensored"} else 3
    if re.match(r"^\d{2,3}[A-Z]", key):
        pad = 3
    ent = {
        "maker": maker,
        "pad": pad,
        "format": "{prefix}-{num}" if rid != "fc2" else ("FC2-PPV-{num}" if key == "FC2PPV" else "FC2-{num}"),
        "sources": [SRC],
        "serials": [],
        "notes": note_tag,
        "status": "active",
        "integrity": "unknown",
    }
    bucket[key] = store._normalize_prefix_entry(key, ent)
    return "added"


def harvest_censored_list(pages: int = 5) -> Counter[str]:
    counts: Counter[str] = Counter()
    for page in range(1, pages + 1):
        url = (
            "https://www.sehuatang.net/forum.php?mod=forumdisplay&fid=37"
            if page == 1
            else f"https://www.sehuatang.net/forum.php?mod=forumdisplay&fid=37&page={page}"
        )
        try:
            html = o.fetch_page(
                url,
                referer="https://www.sehuatang.net/forum.php",
                timeout=28.0,
            ).html or ""
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL fid37 p{page}: {e}", flush=True)
            continue
        soup = BeautifulSoup(html, "lxml")
        texts: list[str] = []
        for a in soup.select("a.s.xst"):
            t = a.get_text(" ", strip=True)
            if t:
                texts.append(t)
        n = 0
        for t in texts:
            for m in CODE_RE.finditer(t):
                p = clean_prefix(m.group(1))
                if not p:
                    continue
                # 列表里素人前缀归 amateur，其余有码
                counts[p] += 1
                n += 1
        print(f"  OK fid37 p{page} titles={len(texts)} codes={n}", flush=True)
    return counts


def region_for_list_prefix(p: str) -> str:
    if p.startswith("FC2"):
        return "fc2"
    if re.match(r"^\d{2,3}[A-Z]", p):
        return "japan_amateur"
    if p in {"SIRO", "LUXU", "MAAN", "MIUM", "GANA", "NTK", "JAC", "ORE", "SCUTE", "ARA"}:
        return "japan_amateur"
    return "japan_censored"


def sync_seed_from_catalog() -> None:
    doc = store.load_catalog(force=True)
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    regions = seed.setdefault("regions", {})
    for rid in REGION_ORDER:
        meta = REGION_META[rid]
        prefs = (doc["regions"].get(rid) or {}).get("prefixes") or {}
        out: dict[str, Any] = {}
        for key, ent in sorted(prefs.items()):
            row = {
                "maker": ent.get("maker") or "",
                "pad": int(ent.get("pad") or 0),
                "format": ent.get("format") or "{prefix}-{num}",
                "sources": list(ent.get("sources") or ["site"]),
                "serials": [],
            }
            if ent.get("dmm_digit") not in (None,):
                row["dmm_digit"] = ent.get("dmm_digit")
            if ent.get("notes"):
                row["notes"] = ent["notes"]
            if ent.get("maker_ja"):
                row["maker_ja"] = ent["maker_ja"]
            out[key] = row
        regions[rid] = {"id": rid, "label": meta["label"], "prefixes": out}
    seed["principle"] = "authority-site + curated seeds; runtime harvest fills serials"
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    boards = load_forum_types()
    doc = store.load_catalog(force=True)
    stats: dict[str, dict[str, int]] = {
        rid: {"added": 0, "touched": 0} for rid in REGION_ORDER
    }
    from_types: list[dict[str, str]] = []

    print("=== 论坛子分类 → 前缀 ===", flush=True)
    for board in boards:
        fid = int(board.get("fid") or 0)
        bname = str(board.get("board") or "")
        for t in board.get("types") or []:
            name = strip_count(str(t.get("name") or ""))
            hit = resolve_type(name, board_fid=fid)
            if not hit:
                continue
            rid, prefix, maker = hit
            bucket = doc["regions"][rid]["prefixes"]
            note = f"{TAG}:{bname}/{name}"
            action = merge_one(bucket, rid, prefix, maker=maker, note_tag=note)
            if action == "skip":
                continue
            stats[rid][action] += 1
            from_types.append(
                {
                    "fid": str(fid),
                    "board": bname,
                    "type": name,
                    "region": rid,
                    "prefix": clean_prefix(prefix),
                    "action": action,
                }
            )
            print(f"  {action:7} {rid:18} {clean_prefix(prefix):14} ← {bname}/{name}", flush=True)

    print("\n=== 亚洲有码列表抽前缀 (fid=37) ===", flush=True)
    counts = harvest_censored_list(5)
    from_list: list[dict[str, Any]] = []
    # 至少出现 2 次；单次仅收较长厂牌前缀（≥4 字母），减少短噪声
    for pref, n in counts.most_common():
        if n >= 2:
            pass
        elif pref.isalpha() and len(pref) >= 4:
            pass
        else:
            continue
        rid = region_for_list_prefix(pref)
        bucket = doc["regions"][rid]["prefixes"]
        note = f"色花堂有码列表×{n}"
        action = merge_one(bucket, rid, pref, maker="", note_tag=note)
        if action == "skip":
            continue
        stats[rid][action] += 1
        from_list.append({"prefix": pref, "count": n, "region": rid, "action": action})
        if action == "added":
            print(f"  added   {rid:18} {pref:14} ×{n}", flush=True)

    store.save_catalog(doc)
    sync_seed_from_catalog()

    summary = {
        rid: {
            **stats[rid],
            "total": len(doc["regions"][rid]["prefixes"]),
        }
        for rid in REGION_ORDER
    }
    report = {
        "from_types": from_types,
        "from_list_added_or_touched": from_list,
        "summary": summary,
        "type_added": sum(1 for x in from_types if x["action"] == "added"),
        "type_touched": sum(1 for x in from_types if x["action"] == "touched"),
        "list_added": sum(1 for x in from_list if x["action"] == "added"),
        "list_touched": sum(1 for x in from_list if x["action"] == "touched"),
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n=== 汇总 ===", flush=True)
    print(
        f"子分类: +{report['type_added']} new, ~{report['type_touched']} annotated",
        flush=True,
    )
    print(
        f"有码列表: +{report['list_added']} new, ~{report['list_touched']} annotated",
        flush=True,
    )
    for rid, s in summary.items():
        if s["added"] or s["touched"]:
            print(
                f"  {rid}: +{s['added']} ~{s['touched']} total={s['total']}",
                flush=True,
            )
    print("report", REPORT, flush=True)


if __name__ == "__main__":
    main()
