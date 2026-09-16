# -*- coding: utf-8 -*-
"""Audit MDCx→program NFO conversion progress + quality issues."""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.scrap_library import embed as embed_svc
from app.scrap_library.enrich import _clean_actors
from app.scrap_library.nfo import actors_from_mdcx_side_channels, _looks_like_actress_token

REGION = (sys.argv[1] if len(sys.argv) > 1 else "日本有码").strip()
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0  # 0 = all

settings = embed_svc.get_settings()
base = embed_svc.resolve_root(settings.get("root")).resolve() / REGION
if not base.is_dir():
    print(f"missing: {base}")
    sys.exit(2)

# progress counters
total = 0
program = 0  # has actor_all or numbered actor children under actor
mdcx_style = 0  # has genre but no actor_all / structured actor
no_actor = 0
parse_fail = 0
skipped_empty = 0

# issue buckets
junk_actors: list[tuple[str, str, str]] = []  # code, actor, path
slash_actors: list[tuple[str, str, str]] = []
empty_title: list[str] = []
missing_num: list[str] = []
genre_as_only_actor_channel: list[str] = []  # still only genre, no actor tags
actor_count_hist = Counter()
suspect_short: list[tuple[str, str, str]] = []  # 1-char JP names etc
multi_slash_in_genre_actorish: Counter = Counter()
# re-detect: if we re-run actors_from_mdcx on current tree, would we drop someone already stored?
would_drop: list[tuple[str, str, str]] = []
# actors that look like titles / plot fragments
titleish: list[tuple[str, str, str]] = []

TITLEISH_RE = re.compile(
    r"(出轨|寝取|NTR|乱伦|近亲|中出|无码|有码|自拍|偷拍|剧情|合集|BEST|总集|作品集|"
    r"特典|限定|独家|完整版|高清|字幕|中文字幕|破解|无修正)",
    re.I,
)

def is_program(root: ET.Element) -> bool:
    if root.find("actor_all") is not None:
        return True
    a = root.find("actor")
    if a is not None and (a.find("name") is not None or a.find("thumb") is not None):
        # program uses <actor><name>..</name></actor> OR flat numbered under actor
        if list(a):
            return True
    # numbered flat: <actor><1>x</1></actor> style also program
    return False


def extract_actors(root: ET.Element) -> list[str]:
    out: list[str] = []
    aa = (root.findtext("actor_all") or "").strip()
    if aa:
        for p in re.split(r"[,，、/|]+", aa):
            p = p.strip()
            if p:
                out.append(p)
    # also <actor><name>
    for a in root.findall("actor"):
        n = (a.findtext("name") or "").strip()
        if n:
            out.append(n)
        for ch in list(a):
            if ch.tag == "name":
                continue
            t = (ch.text or "").strip()
            if t and ch.tag.isdigit():
                out.append(t)
    # dedupe preserve order
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def walk_nfos(root: Path):
    for p in root.rglob("*.nfo"):
        yield p


print(f"scanning {base} ...", flush=True)
for nfo in walk_nfos(base):
    total += 1
    if LIMIT and total > LIMIT:
        total -= 1
        break
    if total % 5000 == 0:
        print(f"  ... {total} files", flush=True)
    try:
        raw = nfo.read_text(encoding="utf-8", errors="replace")
        if not raw.strip():
            skipped_empty += 1
            continue
        tree = ET.fromstring(raw)
    except Exception:
        parse_fail += 1
        continue

    code = (tree.findtext("num") or tree.findtext("id") or nfo.stem or "").strip()
    title = (tree.findtext("title") or "").strip()
    if not title:
        empty_title.append(str(nfo))
    if not (tree.findtext("num") or "").strip():
        missing_num.append(code or str(nfo))

    actors = extract_actors(tree)
    has_genre = tree.find("genre") is not None
    prog = is_program(tree) or bool(actors)

    if prog and actors:
        program += 1
        actor_count_hist[len(actors)] += 1
        for a in actors:
            if "/" in a or "／" in a:
                slash_actors.append((code, a, str(nfo)))
            cleaned = _clean_actors([a])
            if not cleaned:
                junk_actors.append((code, a, str(nfo)))
            elif TITLEISH_RE.search(a) or len(a) >= 20:
                titleish.append((code, a, str(nfo)))
            elif len(a) == 1:
                suspect_short.append((code, a, str(nfo)))
            elif not _looks_like_actress_token(a, code=code):
                # kept by _clean_actors but fails actress-token heuristic → soft suspect
                titleish.append((code, f"?{a}", str(nfo)))
        # also: actors present that would be dropped if we re-clean the whole list
        reclean = _clean_actors(actors)
        if len(reclean) < len(actors):
            dropped = [x for x in actors if x not in reclean]
            for d in dropped:
                would_drop.append((code, d, str(nfo)))
    elif has_genre and not actors:
        mdcx_style += 1
        # try detect what actors_from_mdcx would pull — if many, still unconverted
        try:
            genres = [(g.text or "").strip() for g in tree.findall("genre") if (g.text or "").strip()]
            tags = [(t.text or "").strip() for t in tree.findall("tag") if (t.text or "").strip()]
            detected = actors_from_mdcx_side_channels(genres=genres, tags=tags, title=title)
            if detected:
                genre_as_only_actor_channel.append(f"{code}: {detected}")
        except Exception:
            pass
    else:
        no_actor += 1

print("=== PROGRESS ===")
print(f"region={REGION}")
print(f"total_nfo={total}")
print(f"program_with_actors={program}")
print(f"mdcx_genre_no_actor={mdcx_style}")
print(f"no_actor_no_genre_or_empty={no_actor}")
print(f"parse_fail={parse_fail} empty={skipped_empty}")
if total:
    print(f"converted_pct={100.0 * program / total:.2f}%")
    print(f"still_mdcx_pct={100.0 * mdcx_style / total:.2f}%")

print("\n=== ACTOR COUNT HIST (top) ===")
for k, v in sorted(actor_count_hist.items())[:15]:
    print(f"  actors={k}: {v}")

print(f"\n=== ISSUES ===")
print(f"junk_actor_names={len(junk_actors)}")
print(f"would_drop_on_reclean={len(would_drop)}")
print(f"slash_in_actor={len(slash_actors)}")
print(f"titleish_or_long_actor={len(titleish)}")
print(f"one_char_actor={len(suspect_short)}")
print(f"empty_title={len(empty_title)}")
print(f"missing_num={len(missing_num)}")
print(f"mdcx_still_detectable_actors={len(genre_as_only_actor_channel)}")

def show(label, rows, n=25):
    print(f"\n--- {label} (show {min(n, len(rows))}/{len(rows)}) ---")
    for r in rows[:n]:
        print(" | ".join(str(x) for x in (r if isinstance(r, tuple) else (r,))))

show("junk_actors", junk_actors)
show("would_drop", would_drop)
show("slash_actors", slash_actors)
show("titleish", titleish)
show("one_char", suspect_short)
show("mdcx still convertible sample", genre_as_only_actor_channel, 30)
show("empty_title sample", empty_title, 10)
