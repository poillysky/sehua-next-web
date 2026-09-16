#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 MDCX 全部映射资源导入本项目唯一完整表（apps/maps/scrape/）。

源（apps/api/_local_refs/mdcx/，不进 git）：
  - mapping_actor.xml + Actress-*.db  → apps/maps/scrape/actors.zh-CN.json
  - mapping_info.xml                 → apps/maps/scrape/tags.zh-CN.json
  - c_number.json                    → apps/maps/scrape/code-titles.json

用法（apps/api）:
  .venv/Scripts/python.exe scripts/import_mdcx_maps.py
  .venv/Scripts/python.exe scripts/import_mdcx_maps.py --skip-actors
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API = Path(__file__).resolve().parents[1]
MDCX = API / "_local_refs" / "mdcx"

SEED_TAGS = ROOT / "apps" / "maps" / "scrape" / "tags.zh-CN.json"
OUT_TAGS = SEED_TAGS
OUT_TITLES = ROOT / "apps" / "maps" / "scrape" / "code-titles.json"

INFO_XML = MDCX / "mapping_info.xml"
C_NUMBER = MDCX / "c_number.json"

DELETE_NAMES = frozenset({"删除", "刪除", "削除", "delete", "DELETE"})


def to_zh_cn(s: str) -> str:
    t = str(s or "").strip()
    if not t:
        return ""
    try:
        import zhconv

        t = zhconv.convert(t, "zh-cn").strip()
    except Exception:
        pass
    return t.replace("筿", "筱")


def atomic_write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def load_json_obj(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def import_tags_from_info() -> dict[str, object]:
    if not INFO_XML.is_file():
        raise FileNotFoundError(f"missing {INFO_XML}")
    root = ET.fromstring(INFO_XML.read_bytes().decode("utf-8"))
    built: dict[str, object] = {}
    stats = {"rows": 0, "drop_keys": 0, "map_keys": 0}

    for a in root.findall("a"):
        stats["rows"] += 1
        zh = to_zh_cn(a.attrib.get("zh_cn") or "")
        tw = (a.attrib.get("zh_tw") or "").strip()
        jp = (a.attrib.get("jp") or "").strip()
        keywords = [
            p.strip()
            for p in (a.attrib.get("keyword") or "").split(",")
            if p.strip()
        ]
        keys: list[str] = []
        for x in (tw, jp, *keywords):
            if x:
                keys.append(x)
                xs = to_zh_cn(x)
                if xs and xs != x:
                    keys.append(xs)

        is_drop = zh in DELETE_NAMES or (a.attrib.get("zh_cn") or "").strip() in DELETE_NAMES
        if is_drop:
            for k in keys:
                if k in DELETE_NAMES:
                    continue
                built[k] = {"drop": True}
                stats["drop_keys"] += 1
            continue

        if not zh:
            continue
        # 标准名自身不需要映射
        for k in keys:
            if not k or k == zh or k in DELETE_NAMES:
                continue
            built[k] = zh
            stats["map_keys"] += 1
        # 也写入繁体标准名 → 简体
        if tw and to_zh_cn(tw) == zh and tw != zh:
            built[tw] = zh
            stats["map_keys"] += 1

    # 只维护主表；人工修正直接改 tags.zh-CN.json
    ordered = {
        k: built[k] for k in sorted(built.keys(), key=lambda s: (str(s).casefold(), str(s)))
    }
    atomic_write_json(SEED_TAGS, ordered)
    print(
        json.dumps(
            {
                "tags": {
                    **stats,
                    "final": len(ordered),
                    "path": str(SEED_TAGS),
                }
            },
            ensure_ascii=False,
        )
    )
    return ordered


def import_code_titles() -> int:
    if not C_NUMBER.is_file():
        print(f"skip c_number: missing {C_NUMBER}")
        return 0
    raw = json.loads(C_NUMBER.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("c_number.json must be object")
    # 规范化 key：大写番号；过滤纯日期/无数字
    out: dict[str, str] = {}
    for k, v in raw.items():
        key = str(k or "").strip().upper()
        title = str(v or "").strip()
        if not key or not title:
            continue
        if not re.search(r"\d", key):
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", key):
            continue
        out[key] = title
    ordered = {k: out[k] for k in sorted(out.keys())}
    atomic_write_json(OUT_TITLES, ordered)
    print(
        json.dumps(
            {
                "code_titles": {
                    "source": len(raw),
                    "final": len(ordered),
                    "path": str(OUT_TITLES),
                }
            },
            ensure_ascii=False,
        )
    )
    return len(ordered)


def import_actors(*, no_db: bool = False) -> int:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_actor_map_from_mdcx",
        API / "scripts" / "build_actor_map_from_mdcx.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load build_actor_map_from_mdcx.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old = sys.argv[:]
    try:
        sys.argv = ["build_actor_map_from_mdcx.py"] + (["--no-db"] if no_db else [])
        return int(mod.main() or 0)
    finally:
        sys.argv = old


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-actors", action="store_true")
    ap.add_argument("--skip-tags", action="store_true")
    ap.add_argument("--skip-titles", action="store_true")
    ap.add_argument("--no-db", action="store_true", help="actors 构建时不用 Actress.db")
    args = ap.parse_args()

    if not MDCX.is_dir():
        print(f"missing mdcx refs dir: {MDCX}", file=sys.stderr)
        return 2

    if not args.skip_actors:
        rc = import_actors(no_db=args.no_db)
        if rc:
            return rc

    if not args.skip_tags:
        import_tags_from_info()

    if not args.skip_titles:
        import_code_titles()

    print("import_mdcx_maps: done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
