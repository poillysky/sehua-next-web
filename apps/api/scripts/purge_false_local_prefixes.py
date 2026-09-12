# -*- coding: utf-8 -*-
"""Purge false prefixes from local-db merge (English title words, 2-letter junk)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import prefix_catalog_store as store  # noqa: E402
from app import prefix_ranges as pr  # noqa: E402
from app.core.region_meta import REGION_META, REGION_ORDER, std_prefix  # noqa: E402

SEED = ROOT / "apps" / "web" / "src" / "config" / "prefix-catalog.seed.json"

# Common English words that appear in western torrent titles as fake "PREFIX-123"
EN_WORDS = {
    "DARKNESS",
    "AMBITION",
    "HEIGHTS",
    "DOUBLE",
    "VALLEY",
    "CIRCLE",
    "POWER",
    "APRIL",
    "COLLECTION",
    "SWORD",
    "WOMAN",
    "WOMEN",
    "POLE",
    "HARUKA",  # name not prefix
    "ANNIVERSARY",
    "ADVENTURES",
    "ABBYWINTERS",
    "ASSHOLEFEVER",
    "BABYSITTER",
    "PREMIERREMIX",
    "COMPLETE",
    "SPECIAL",
    "PREMIUM",
    "LIMITED",
    "EDITION",
    "VOLUME",
    "SEASON",
    "EPISODE",
    "CHAPTER",
    "PART",
    "SCENE",
    "STUDIO",
    "MOVIE",
    "FILM",
    "VIDEO",
    "PRIVATE",
    "PUBLIC",
    "SECRET",
    "FAMILY",
    "FRIENDS",
    "LOVERS",
    "COUPLE",
    "GIRLS",
    "GIRL",
    "BOYS",
    "BOY",
    "LADY",
    "LADIES",
    "QUEEN",
    "KING",
    "PRINCESS",
    "ANGEL",
    "DEVIL",
    "HEAVEN",
    "HELL",
    "PARADISE",
    "ISLAND",
    "HOUSE",
    "HOME",
    "ROOM",
    "NIGHT",
    "DAYS",
    "DAY",
    "WEEK",
    "MONTH",
    "YEAR",
    "TIME",
    "FIRST",
    "LAST",
    "BEST",
    "HOT",
    "WET",
    "BIG",
    "SMALL",
    "HARD",
    "SOFT",
    "DEEP",
    "RAW",
    "TRUE",
    "REAL",
    "FAKE",
    "NEW",
    "OLD",
    "YOUNG",
    "TEEN",
    "ADULT",
    "XXX",
    "PORN",
    "SEX",
    "LOVE",
    "LUST",
    "DESIRE",
    "PASSION",
    "PLEASURE",
    "FANTASY",
    "DREAM",
    "STORY",
    "TALES",
    "LEGEND",
    "MYTH",
    "MAGIC",
    "FORCE",
    "ACTION",
    "DRAMA",
    "COMEDY",
    "HORROR",
    "THRILLER",
    "ROMANCE",
    "MYSTERY",
    "CRIME",
    "JUSTICE",
    "REVENGE",
    "ESCAPE",
    "RETURN",
    "ORIGIN",
    "BEGINNING",
    "ENDING",
    "FINAL",
    "ULTIMATE",
    "EXTREME",
    "INTENSE",
    "WILD",
    "CRAZY",
    "DIRTY",
    "NAUGHTY",
    "SWEET",
    "HONEY",
    "SUGAR",
    "CANDY",
    "CREAM",
    "MILK",
    "JUICE",
    "WATER",
    "FIRE",
    "EARTH",
    "WIND",
    "LIGHT",
    "SHADOW",
    "SILVER",
    "GOLD",
    "DIAMOND",
    "CRYSTAL",
    "PEARL",
    "RUBY",
    "EMERALD",
    "SAPPHIRE",
    "AMBER",
    "JADE",
    "IVORY",
    "EBONY",
    "VELVET",
    "SILK",
    "SATIN",
    "LEATHER",
    "LATEX",
    "RUBBER",
    "PLASTIC",
    "METAL",
    "STEEL",
    "IRON",
    "STONE",
    "WOOD",
    "PAPER",
    "GLASS",
    "MIRROR",
    "WINDOW",
    "DOOR",
    "KEY",
    "LOCK",
    "CHAIN",
    "ROPE",
    "BOUND",
    "TIED",
    "OPEN",
    "CLOSED",
    "INSIDE",
    "OUTSIDE",
    "ABOVE",
    "BELOW",
    "UNDER",
    "OVER",
    "BETWEEN",
    "AMONG",
    "THROUGH",
    "ACROSS",
    "AROUND",
    "BEHIND",
    "BEFORE",
    "AFTER",
    "DURING",
    "WHILE",
    "UNTIL",
    "SINCE",
    "BECAUSE",
    "ALTHOUGH",
    "HOWEVER",
    "THEREFORE",
    "MOREOVER",
    "FURTHER",
    "ADDITION",
    "EXAMPLE",
    "INSTANCE",
    "SAMPLE",
    "TRAILER",
    "TEASER",
    "PREVIEW",
    "UNCENSORED",
    "CENSORED",
    "SUBTITLE",
    "SUBTITLES",
    "CHINESE",
    "JAPANESE",
    "ENGLISH",
    "KOREAN",
    "TAIWAN",
    "HONGKONG",
    "BEIJING",
    "SHANGHAI",
    "TOKYO",
    "OSAKA",
    "KYOTO",
    "AMERICA",
    "EUROPE",
    "ASIA",
    "WORLD",
    "GLOBAL",
    "INTERNATIONAL",
    "NATIONAL",
    "LOCAL",
    "ORIGINAL",
    "OFFICIAL",
    "DIGITAL",
    "ANALOG",
    "ONLINE",
    "OFFLINE",
    "STREAMING",
    "DOWNLOAD",
    "UPLOAD",
    "SHARE",
    "TORRENT",
    "MAGNET",
    "HASH",
    "FILE",
    "FOLDER",
    "ARCHIVE",
    "PACKAGE",
    "BUNDLE",
    "PACK",
    "SET",
    "SERIES",
    "SEASON",
    "DISC",
    "DISK",
    "DRIVE",
    "MEDIA",
    "FORMAT",
    "CODEC",
    "BITRATE",
    "RESOLUTION",
    "QUALITY",
    "HIGH",
    "LOW",
    "ULTRA",
    "SUPER",
    "HYPER",
    "MEGA",
    "GIGA",
    "TERA",
    "MINI",
    "MICRO",
    "MACRO",
    "FULL",
    "HALF",
    "QUARTER",
    "PERCENT",
    "NUMBER",
    "COUNT",
    "TOTAL",
    "SUM",
    "AVERAGE",
    "MAXIMUM",
    "MINIMUM",
    "MEDIUM",
    "STANDARD",
    "CUSTOM",
    "DEFAULT",
    "NORMAL",
    "ABNORMAL",
    "NATURAL",
    "ARTIFICIAL",
    "MANUAL",
    "AUTO",
    "AUTOMATIC",
    "RANDOM",
    "FIXED",
    "VARIABLE",
    "CONSTANT",
    "STATIC",
    "DYNAMIC",
    "ACTIVE",
    "PASSIVE",
    "POSITIVE",
    "NEGATIVE",
    "NEUTRAL",
    "MALE",
    "FEMALE",
    "HUMAN",
    "ANIMAL",
    "PLANT",
    "OBJECT",
    "THING",
    "STUFF",
    "MATTER",
    "MATERIAL",
    "SUBSTANCE",
    "ELEMENT",
    "COMPOUND",
    "MIXTURE",
    "SOLUTION",
    "PROBLEM",
    "QUESTION",
    "ANSWER",
    "RESULT",
    "OUTCOME",
    "EFFECT",
    "CAUSE",
    "REASON",
    "PURPOSE",
    "GOAL",
    "TARGET",
    "AIM",
    "OBJECTIVE",
    "MISSION",
    "TASK",
    "JOB",
    "WORK",
    "PLAY",
    "GAME",
    "SPORT",
    "MUSIC",
    "ART",
    "SCIENCE",
    "HISTORY",
    "FUTURE",
    "PRESENT",
    "PAST",
    "MOMENT",
    "SECOND",
    "MINUTE",
    "HOUR",
    "TODAY",
    "TOMORROW",
    "YESTERDAY",
    "MORNING",
    "EVENING",
    "AFTERNOON",
    "MIDNIGHT",
    "NOON",
    "DAWN",
    "DUSK",
    "SUNRISE",
    "SUNSET",
    "SPRING",
    "SUMMER",
    "AUTUMN",
    "WINTER",
    "FALL",
    "HALT",
    "GEN",
    "SAIT",
    "VAIAV",
    "ICMN",
    "CRVR",
    "HNTRZ",
    "HEIGHTS",
}


def clean(p: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", std_prefix(p).replace("-", ""))


def known_set() -> set[str]:
    out: set[str] = set()
    for name in (
        "av-makers.japan.json",
        "av-makers.china.json",
        "av-makers.western.json",
    ):
        data = json.loads(
            (ROOT / "apps/web/src/config" / name).read_text(encoding="utf-8")
        )
        for m in data:
            for p in m.get("prefixes") or []:
                out.add(clean(p))
    ranges = json.loads(
        (ROOT / "apps/web/src/config/prefix-code-ranges.json").read_text(
            encoding="utf-8"
        )
    )["ranges"]
    out |= {clean(k) for k in ranges}
    verify = json.loads(
        (ROOT / "data/_debug/dmm-prefix-verify.json").read_text(encoding="utf-8")
    )
    out |= {clean(x["prefix"]) for x in verify.get("ok_list") or []}
    # short but real
    out |= {clean(x) for x in ("BF", "SW", "PT", "DV", "GS", "AV", "AB", "ZK")}
    out |= {clean(x) for x in pr.SKIP_PREFIXES}
    return out


def looks_like_jav_prefix(p: str) -> bool:
    """Heuristic for real JAV/amateur shells (not English words)."""
    if p in EN_WORDS or p in pr.NOISE:
        return False
    if len(p) < 3:
        return False
    # digit-leading amateur: 200GANA / 259LUXU
    if re.fullmatch(r"\d{2,3}[A-Z]{2,8}", p):
        return True
    # classic letter prefixes 3-6 chars
    if re.fullmatch(r"[A-Z]{3,6}", p):
        # reject if looks like common English (vowel-heavy long-ish)
        vowels = sum(1 for ch in p if ch in "AEIOU")
        if len(p) >= 5 and vowels >= 3 and p in EN_WORDS:
            return False
        return True
    # china-ish
    if re.fullmatch(r"(MD|MKY|MDSR|MSD|91CM|TMW|JVID)[A-Z0-9]*", p):
        return True
    return False


def main() -> None:
    known = known_set()
    doc = store.load_catalog(force=True)
    removed: list[tuple[str, str, str]] = []

    for rid in REGION_ORDER:
        bucket = doc["regions"][rid]["prefixes"]
        for key in list(bucket.keys()):
            ent = bucket[key]
            if key in known:
                continue
            reason = ""
            if key in EN_WORDS or key in pr.NOISE:
                reason = "english/noise"
            elif len(key) <= 2:
                reason = "too_short"
            elif key.isalpha() and len(key) >= 7 and key not in known:
                # long pure english-like
                reason = "long_alpha"
            elif not looks_like_jav_prefix(key):
                reason = "not_javish"
            # keep if has maker from curated or serials harvested
            if reason and (ent.get("serials") or []):
                continue
            if reason and ent.get("maker") and "本地库" not in str(ent.get("notes") or ""):
                continue
            if reason:
                del bucket[key]
                removed.append((rid, key, reason))

    store.save_catalog(doc)

    seed = json.loads(SEED.read_text(encoding="utf-8"))
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid]["prefixes"]
        out = {}
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
            out[key] = row
        seed["regions"][rid] = {
            "id": rid,
            "label": REGION_META[rid]["label"],
            "prefixes": out,
        }
    SEED.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = store.public_summary()
    by_reason: dict[str, int] = {}
    for _, _, r in removed:
        by_reason[r] = by_reason.get(r, 0) + 1
    print("removed", len(removed), by_reason)
    for r in summary.get("regions") or []:
        print(f"{r['id']:18} prefixes={r.get('prefix_count')}")
    print("TOTAL", summary.get("prefix_total"))

    # re-audit quick
    allp = set()
    for rid in REGION_ORDER:
        allp |= set(doc["regions"][rid]["prefixes"])
    print("known_ratio", f"{100*len(allp & known)/max(1,len(allp)):.1f}%", len(allp & known), "/", len(allp))
    print("still_english_sample", sorted(allp & EN_WORDS)[:20])


if __name__ == "__main__":
    main()
