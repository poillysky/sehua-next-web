#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan scrap_library_embed actress names for unmerged aliases."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.core.db import init_db, get_meta_pool, debug_dir  # noqa: E402
from app.scrape.metadata_optimize import (  # noqa: E402
    _actor_maps,
    _fold_variant,
    _lookup_actor_hit,
    polish_actress_names,
)

ACTRESS_LINE = re.compile(r"^女优[：:](.+)$", re.M)
HAS_KANA = re.compile(r"[\u3040-\u30ff]")
CJK_ONLY = re.compile(r"^[\u4e00-\u9fff·・\s]+$")


def main() -> None:
    init_db()
    names: Counter[str] = Counter()
    rows_scanned = 0
    with_actress = 0
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_text FROM scrap_library_embed
            WHERE source_text LIKE %s
            """,
            ("%女优：%",),
        )
        while True:
            batch = cur.fetchmany(2000)
            if not batch:
                break
            for (src,) in batch:
                rows_scanned += 1
                m = ACTRESS_LINE.search(src or "")
                if not m:
                    continue
                with_actress += 1
                for part in re.split(r"[\s、,/|]+", m.group(1).strip()):
                    n = part.strip()
                    if n:
                        names[n] += 1

    print(f"rows_with_actress_line={with_actress} unique_names={len(names)}")

    table = _actor_maps("zh-CN")

    # Reverse index: canonical -> set of alias keys in map
    canon_to_aliases: dict[str, set[str]] = defaultdict(set)
    for k, v in table.items():
        if isinstance(v, dict):
            can = str(v.get("zh") or v.get("name") or "").strip()
        else:
            can = str(v or "").strip()
        if not can:
            continue
        canon_to_aliases[can].add(str(k).strip())
        canon_to_aliases[can].add(can)

    lib_set = set(names)

    # A) Map already knows merge, but library still has multiple spellings
    already_mapped_unmerged: list[dict] = []
    for can, aliases in canon_to_aliases.items():
        present = sorted({a for a in aliases if a in lib_set}, key=lambda x: -names[x])
        if len(present) >= 2:
            already_mapped_unmerged.append(
                {
                    "canonical": can,
                    "present": [{"name": n, "count": names[n]} for n in present],
                    "total": sum(names[n] for n in present),
                }
            )
    already_mapped_unmerged.sort(key=lambda x: -x["total"])

    # B) Names that polish to different canonical
    polish_diff = []
    for n, c in names.items():
        out = polish_actress_names([n])
        if out and out[0] != n:
            polish_diff.append({"from": n, "to": out[0], "count": c})
    polish_diff.sort(key=lambda x: -x["count"])

    # C) Likely ZH phonetic of a JP library name sharing surname (2 chars)
    # Only when ZH is unmapped and JP is mapped/present; given-name length similar
    phonetic_pairs: list[dict] = []
    jp_lib = [n for n in names if HAS_KANA.search(n)]
    zh_lib = [
        n
        for n in names
        if CJK_ONLY.match(n)
        and not HAS_KANA.search(n)
        and _lookup_actor_hit(n, table) is None
    ]

    # Common katakana→zh fragments seen in AV titles
    kana_zh_hints = [
        ("エレナ", ["艾雷娜", "艾蕾娜", "埃蕾娜", "埃莉娜"]),
        ("ショコラ", ["巧克力"]),
        ("まりな", ["茉莉奈", "玛丽奈"]),
        ("ほのか", ["穗花", "穗香"]),
        ("よつ葉", ["四叶"]),
        ("よつ叶", ["四叶"]),
        ("しほ", ["志保"]),
        ("はるか", ["春香", "遥"]),
        ("すず", ["铃"]),
        ("るり", ["瑠璃"]),
        ("いちか", ["一花"]),
        ("あずさ", ["亚澄", "亜澄", "梓"]),
        ("のぞみ", ["希", "望"]),
        ("このみ", ["好美"]),
    ]

    for zh in zh_lib:
        if len(zh) < 3:
            continue
        pref = _fold_variant(zh[:2])
        for jp in jp_lib:
            jp_f = _fold_variant(jp)
            if not (jp_f.startswith(pref) or jp.startswith(zh[:2])):
                continue
            # given-name match via hints
            given_zh = zh[2:]
            matched = False
            for kana, zhs in kana_zh_hints:
                if kana in jp and given_zh in zhs:
                    matched = True
                    break
            # also: JP given is kana-only and ZH given length 2-3
            if not matched:
                # weaker: same surname + zh given appears nowhere else as different person in map
                jp_given = jp[2:] if len(jp) > 2 else ""
                if HAS_KANA.fullmatch(jp_given or "x") and 1 <= len(given_zh) <= 3:
                    # require that polishing jp stays jp (or known), and no map hit for zh
                    matched = True
            if not matched:
                continue
            # score: prefer hint matches
            hint = any(
                kana in jp and given_zh in zhs for kana, zhs in kana_zh_hints
            )
            phonetic_pairs.append(
                {
                    "alias": zh,
                    "alias_count": names[zh],
                    "likely_canonical": jp,
                    "canon_count": names[jp],
                    "hint": hint,
                }
            )

    # dedupe alias keep best hint
    best: dict[str, dict] = {}
    for p in phonetic_pairs:
        a = p["alias"]
        old = best.get(a)
        if old is None or (p["hint"] and not old["hint"]) or (
            p["hint"] == old["hint"] and p["canon_count"] > old["canon_count"]
        ):
            best[a] = p
    phonetic_pairs = sorted(best.values(), key=lambda x: (-x["hint"], -x["alias_count"]))

    # High-confidence: hint=True
    high = [p for p in phonetic_pairs if p["hint"]]
    weak = [p for p in phonetic_pairs if not p["hint"]]

    out = {
        "unique_names": len(names),
        "rows_with_actress": with_actress,
        "already_mapped_but_unmerged_in_lib": already_mapped_unmerged[:80],
        "polish_would_rename": polish_diff[:80],
        "phonetic_high_confidence": high[:80],
        "phonetic_weak": weak[:40],
        "top_unmapped": [
            {"name": n, "count": c}
            for n, c in names.most_common()
            if _lookup_actor_hit(n, table) is None
        ][:80],
    }
    path = debug_dir() / "actress_alias_scan.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {path}")
    print("already_mapped_unmerged", len(already_mapped_unmerged))
    print("polish_would_rename", len(polish_diff))
    print("phonetic_high", len(high), "weak", len(weak))
    print("--- high confidence ---")
    for p in high[:30]:
        print(
            f"  {p['alias']} x{p['alias_count']} -> {p['likely_canonical']} x{p['canon_count']}"
        )
    print("--- already mapped but both in lib ---")
    for g in already_mapped_unmerged[:20]:
        print(g["canonical"], g["present"])


if __name__ == "__main__":
    main()
