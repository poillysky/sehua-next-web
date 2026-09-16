#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 MDCx mapping_actor.xml（+ 可选 Actress.db）生成 sehua 用 actors.zh-CN.json。

输出：apps/maps/scrape/actors.zh-CN.json（唯一完整表；人工修正也直接改此文件）
策略（偏稳，宁漏勿错）：
- 标准名取 zh_cn，再 zhconv → 简体
- 丢弃占位/泛化词（女优/素人/错误…）
- 丢弃含「誤認注意」「同名異人」的别名
- 无假名且繁简不等的「汉字↔汉字」别名默认跳过（防羽田希→羽月希）
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # sehua-next-web
API = Path(__file__).resolve().parents[1]
DEFAULT_XML = API / "_local_refs" / "mdcx" / "mapping_actor.xml"
DEFAULT_DB = API / "_local_refs" / "mdcx" / "Actress-20250220.db"
# 兼容旧探针目录（若尚未整理）
_LEGACY_XML = API / "_gap_reports" / "_mdcx_mapping_actor.xml"
_LEGACY_DB = API / "_gap_reports" / "_mdcx_Actress-20250220.db"
if not DEFAULT_XML.is_file() and _LEGACY_XML.is_file():
    DEFAULT_XML = _LEGACY_XML
if not DEFAULT_DB.is_file() and _LEGACY_DB.is_file():
    DEFAULT_DB = _LEGACY_DB
SEED = ROOT / "apps" / "maps" / "scrape" / "actors.zh-CN.json"
OUT = SEED

KANA_RE = re.compile(r"[\u3040-\u30ff]")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

PLACEHOLDER_NAMES = frozenset(
    {
        "女优",
        "女優",
        "av女优",
        "av女優",
        "素人",
        "别人",
        "別人",
        "错误",
        "錯誤",
        "未知",
        "不明",
        "无",
        "無",
        "n/a",
        "na",
        "null",
        "none",
        "-",
        "—",
        "－",
    }
)

SKIP_KEYWORD_MARKERS = ("誤認注意", "同名異人", "誤認", "误认")

# MDCX 源里没有、只在主表上人工维护的字段；重导时按旧表带回（见 _carry_over_manual_fields）
# avatar 跟标准名走；drop/role/sex 跟具体键走
MANUAL_FIELDS = ("avatar", "drop", "role", "sex")


def to_zh_cn(s: str) -> str:
    t = str(s or "").strip()
    if not t:
        return ""
    try:
        import zhconv

        t = zhconv.convert(t, "zh-cn").strip()
    except Exception:
        pass
    # 人名常见误转：篠/筱 被转成生僻「筿」
    t = t.replace("筿", "筱")
    return t


def atomic_write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _is_placeholder(name: str) -> bool:
    n = to_zh_cn(name).casefold()
    if not n:
        return True
    if n in {x.casefold() for x in PLACEHOLDER_NAMES}:
        return True
    if n in {"av女优", "女优", "素人"}:
        return True
    return False


def _keyword_blocked(k: str) -> bool:
    if not k or not k.strip():
        return True
    if any(m in k for m in SKIP_KEYWORD_MARKERS):
        return True
    if _is_placeholder(k):
        return True
    return False


def _kana_ratio(s: str) -> float:
    t = str(s or "")
    if not t:
        return 0.0
    k = len(KANA_RE.findall(t))
    return k / max(1, len(t))


def _prefer_chinese_name(*names: str) -> str:
    """多候选时优先：无假名 + 含汉字 + 已是简体。"""
    scored: list[tuple[tuple[int, int, int, int], str]] = []
    for raw in names:
        n = to_zh_cn(raw)
        if not n or _is_placeholder(n):
            continue
        scored.append(
            (
                (
                    0 if KANA_RE.search(n) else 1,
                    1 if CJK_RE.search(n) else 0,
                    1 if n == str(raw or "").strip() or n == to_zh_cn(raw) else 0,
                    len(CJK_RE.findall(n)),
                ),
                n,
            )
        )
    if not scored:
        return to_zh_cn(names[0]) if names else ""
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _safe_alias(alias: str, canonical: str, *, row_jp: str, row_tw: str) -> bool:
    """是否把 alias 映射到 canonical。偏保守。"""
    a = alias.strip()
    c = canonical.strip()
    if not a or not c or a == c:
        return False
    if _keyword_blocked(a):
        return False
    a_s, c_s = to_zh_cn(a), to_zh_cn(c)
    if a_s == c_s:
        return True  # 纯繁简
    # 不要把「已是中文汉字名」改成假名标准名（用户侧要中文）
    if CJK_RE.search(a) and not KANA_RE.search(a) and KANA_RE.search(c) and _kana_ratio(c) >= 0.3:
        return False
    # 同条繁体 → 简体：保留
    if a == row_tw and to_zh_cn(row_tw) == c_s:
        return True
    # jp 仅当含假名，或繁简等同于标准名时信任（防 jp=涼宮琴音 / zh_cn=白咲碧）
    if a == row_jp:
        if KANA_RE.search(a) or to_zh_cn(a) == c_s:
            return True
        # jp 也是无假名汉字且与标准名不同 → 高风险，不自动信
        if CJK_RE.search(a) and not KANA_RE.search(a) and a_s != c_s:
            return False
    # 含假名的别名通常是日文写法 / 旧艺名
    if KANA_RE.search(a):
        return True
    # 两边都是「无假名汉字名」且简体不同 → 高风险错并，跳过
    if CJK_RE.search(a) and CJK_RE.search(c) and not KANA_RE.search(a) and not KANA_RE.search(c):
        if a_s != c_s:
            return False
    return True


def _put(
    table: dict[str, dict],
    key: str,
    *,
    name: str,
    url: str = "",
    force: bool = False,
) -> bool:
    k = str(key or "").strip()
    n = str(name or "").strip()
    if not k or not n or k == n:
        return False
    if _is_placeholder(n) or _keyword_blocked(k):
        return False
    if (not force) and k in table:
        return False
    entry: dict = {"name": n, "zh": n}
    if url:
        entry["url"] = url
        if "javdb.com" in url:
            entry["javdb"] = url
    table[k] = entry
    return True


def from_mdcx_xml(xml_path: Path) -> tuple[dict[str, dict], dict[str, int]]:
    root = ET.fromstring(xml_path.read_text(encoding="utf-8"))
    table: dict[str, dict] = {}
    stats = {
        "rows": 0,
        "skipped_placeholder_rows": 0,
        "skipped_risky_aliases": 0,
        "added": 0,
    }
    for a in root.iter("a"):
        stats["rows"] += 1
        zh_raw = (a.attrib.get("zh_cn") or "").strip()
        tw = (a.attrib.get("zh_tw") or "").strip()
        jp = (a.attrib.get("jp") or "").strip()
        href = (a.attrib.get("href") or "").strip()
        kw_parts = [
            p.strip()
            for p in (a.attrib.get("keyword") or "").split(",")
            if p.strip() and not _keyword_blocked(p.strip())
        ]
        # 标准名：默认信任 zh_cn；仅当 zh_cn 偏假名时，才从同条中文别名里挑
        zh_s = to_zh_cn(zh_raw)
        if zh_s and CJK_RE.search(zh_s) and not KANA_RE.search(zh_s):
            canonical = zh_s
        else:
            canonical = _prefer_chinese_name(
                zh_raw,
                tw,
                *[p for p in kw_parts if CJK_RE.search(p) and not KANA_RE.search(p)],
            ) or zh_s
        if _is_placeholder(canonical) or not canonical:
            stats["skipped_placeholder_rows"] += 1
            continue
        url = href if href.startswith("http") else ""

        candidates: list[str] = []
        for x in (jp, tw, zh_raw, *kw_parts):
            if x:
                candidates.append(x)

        seen_local: set[str] = set()
        for raw_key in candidates:
            if raw_key in seen_local:
                continue
            seen_local.add(raw_key)
            if not _safe_alias(raw_key, canonical, row_jp=jp, row_tw=tw):
                # 仍允许繁简：raw→canonical 经 convert 相同已在 _safe_alias 处理
                if to_zh_cn(raw_key) != canonical and raw_key != canonical:
                    stats["skipped_risky_aliases"] += 1
                continue
            key = raw_key.strip()
            # 也写入简体化后的 key（若不同）
            keys = [key]
            key_s = to_zh_cn(key)
            if key_s and key_s != key:
                keys.append(key_s)
            for k in keys:
                if k == canonical:
                    continue
                if _put(table, k, name=canonical, url=url):
                    stats["added"] += 1
    return table, stats


def enrich_from_actress_db(db_path: Path, table: dict[str, dict]) -> dict[str, int]:
    stats = {"db_pairs": 0, "added": 0, "skipped": 0}
    if not db_path.is_file():
        return stats
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            """
            SELECT n.Name, n.Alias, i.NameCN, i.Href
            FROM Names n
            JOIN Info i ON i.Name = n.Name
            WHERE i.NameCN IS NOT NULL AND trim(i.NameCN) != ''
            """
        ).fetchall()
    finally:
        con.close()

    for name_jp, alias, name_cn, href in rows:
        stats["db_pairs"] += 1
        canonical = to_zh_cn(str(name_cn or ""))
        if _is_placeholder(canonical):
            stats["skipped"] += 1
            continue
        url = ""
        href_s = str(href or "").strip()
        if href_s.startswith("http"):
            url = href_s
        elif href_s:
            url = f"https://www.minnano-av.com/{href_s.split('?')[0]}"

        for raw in (name_jp, alias):
            raw_s = str(raw or "").strip()
            if not raw_s:
                continue
            # DB 侧：已是简体中文名不要映回假名标准名
            if (
                CJK_RE.search(raw_s)
                and not KANA_RE.search(raw_s)
                and KANA_RE.search(canonical)
            ):
                stats["skipped"] += 1
                continue
            if not _safe_alias(raw_s, canonical, row_jp=str(name_jp or ""), row_tw=""):
                stats["skipped"] += 1
                continue
            for k in {raw_s, to_zh_cn(raw_s)}:
                if not k or k == canonical:
                    continue
                if _put(table, k, name=canonical, url=url):
                    stats["added"] += 1
    return stats


def _carry_over_manual_fields(path: Path, table: dict[str, dict]) -> dict[str, int]:
    """把旧表里的人工字段带回新表，避免 MDCX 重导整表重建时冲掉。

    锚点分两种：
    - **按 key**：``drop`` / ``role`` / ``sex`` —— 男优、导演等在具体键上打标
    - **按标准名**：``avatar`` —— 头像直链跟人走，别名换写法也不丢

    旧表里只有人工字段、新表已无该键时整条补回（人工新增条目）。
    返回 ``{"fields": n, "entries": n}``。
    """
    stats = {"fields": 0, "entries": 0}
    if not path.is_file():
        return stats
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return stats
    if not isinstance(old, dict):
        return stats

    keyed: dict[str, dict] = {}
    by_name: dict[str, str] = {}
    for k, v in old.items():
        if not isinstance(v, dict):
            continue
        fields = {f: v[f] for f in MANUAL_FIELDS if f in v}
        if not fields:
            continue
        keyed[str(k)] = fields
        avatar = str(fields.get("avatar") or "").strip()
        name = str(v.get("name") or "").strip()
        if avatar and name:
            by_name.setdefault(name, avatar)
    if not keyed:
        return stats

    for k, fields in keyed.items():
        entry = table.get(k)
        if entry is None:
            table[k] = dict(old[k])  # 人工条目整条补回
            stats["entries"] += 1
            continue
        for f, val in fields.items():
            if entry.get(f) != val:
                entry[f] = val
                stats["fields"] += 1

    for entry in table.values():
        if not isinstance(entry, dict) or "avatar" in entry:
            continue
        avatar = by_name.get(str(entry.get("name") or "").strip())
        if avatar:
            entry["avatar"] = avatar
            stats["fields"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", type=Path, default=DEFAULT_XML)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--no-db", action="store_true")
    args = ap.parse_args()

    if not args.xml.is_file():
        print(f"missing xml: {args.xml}", file=sys.stderr)
        return 2

    table, xml_stats = from_mdcx_xml(args.xml)
    db_stats = {"db_pairs": 0, "added": 0, "skipped": 0}
    if not args.no_db:
        db_stats = enrich_from_actress_db(args.db, table)

    carried = _carry_over_manual_fields(args.out, table)

    # 稳定排序写出（人工修正请直接改输出主表）
    ordered = {k: table[k] for k in sorted(table.keys(), key=lambda s: (s.casefold(), s))}
    atomic_write_json(args.out, ordered)

    drop_n = sum(
        1
        for v in ordered.values()
        if isinstance(v, dict)
        and (v.get("drop") or v.get("role") or str(v.get("sex") or "").lower() in {"m", "male"})
    )
    print(
        json.dumps(
            {
                "out": str(args.out),
                "entries": len(ordered),
                "drop_like": drop_n,
                "manual_carried": carried,
                "xml": xml_stats,
                "db": db_stats,
                "bytes": args.out.stat().st_size,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
