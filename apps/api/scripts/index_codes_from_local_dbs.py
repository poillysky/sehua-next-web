# -*- coding: utf-8 -*-
"""Sehua + Bitmagnet 单次全表扫 → 七区真实番号。

相对旧版优化：
1. 准度：拒年份伪流水 / FC2 过长 ID；写回前用 robust_serial_max 砍离群
2. 补缺：素人数字头别名（406FCDSS←FCDSS）；长前缀走 extract；同前缀多区都写
3. 未命中分类写入报告，不按前缀 SQL
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app import bitmagnet_pg  # noqa: E402
from app import pg  # noqa: E402
from app import prefix_catalog_store as store  # noqa: E402
from app import prefix_ranges as pr  # noqa: E402
from app.region_meta import REGION_ORDER, std_prefix  # noqa: E402
from app.search_av import is_western_studio_prefix  # noqa: E402
from app.search_av import (  # noqa: E402
    _clamp_std_code_digits,
    code_sort_key,
    extract_maker_codes,
    resolve_maker_shape,
)

REPORT = ROOT / "data" / "_debug" / "prefix-codes-from-local-dbs.json"
SPECIAL_SHAPES = {"fc2", "fc2ppv", "date6", "alnum_id", "western_date", "western_ep"}
DIGIT_HEAD_RE = re.compile(r"^(\d{2,3})([A-Z]{2,14})$")
# 允许更长厂牌前缀（FELLATIOJAPAN=14）
LONG_CODE_RE = re.compile(
    r"(?:^|[^A-Z0-9])([A-Z]{2,20}|\d{2,3}[A-Z]{2,14}|[A-Z]+\d+[A-Z]*)[-_\s]?(\d{2,6})(?![0-9])",
    re.I,
)


@lru_cache(maxsize=8192)
def clean_prefix(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", std_prefix(raw).replace("-", ""))


@lru_cache(maxsize=8192)
def _shape(pref: str) -> str:
    return resolve_maker_shape(pref)


def is_special(pref: str) -> bool:
    if _shape(pref) in SPECIAL_SHAPES:
        return True
    return clean_prefix(pref) in {clean_prefix(x) for x in pr.SKIP_PREFIXES}


def special_needles(pref: str) -> tuple[str, ...]:
    u = pref.upper()
    if u in {"FC2", "FC2PPV"}:
        return ("FC2",)
    if u == "H0930":
        return ("H0930", "KI20", "KI19")
    if u == "H4610":
        return ("H4610", "4610")
    if u == "C0930":
        return ("C0930", "CI20", "CI19")
    if u == "PACOMA":
        return ("PACO", "PACOPACO")
    if u == "SMMIRACLE":
        return ("SM-MIRACLE", "SMMIRACLE")
    if u == "FELLATIOJAPAN":
        return ("FELLATIOJAPAN", "FELLATIO")
    if u == "ORECZ":
        return ("ORECZ", "230ORECZ", "ORECO")
    if u == "ROSELIPFETISH":
        return ("ROSELIP",)
    return (u,)


def accept_std_serial(pref: str, n: int) -> bool:
    """准度门闩：去掉年份伪号与离谱大号（HEYZO 等高压水号前缀放行年份段）。"""
    if n <= 0:
        return False
    # 高流水真号前缀（无码站）可到 2000+
    if pref in {"HEYZO", "KIN8", "XXXAV", "NYOSHIN"}:
        return n < 100000
    if 1990 <= n <= 2035:
        return False
    if n >= 10000 and pref.isalpha() and len(pref) <= 4 and pref not in {
        "NHDT",
        "NHDTB",
        "NHDTA",
        "BDSR",
        "HODV",
        "JKSR",
        "ENFD",
    }:
        return False
    if n >= 100000:
        return False
    return True


def accept_std_code(pref: str, code: str) -> bool:
    """标准形番号：PREFIX-纯数字；拒 HEYZO-1913L / JVID-2023 / JVID-34D。"""
    pref = clean_prefix(pref)
    c = str(code or "").strip().upper()
    if not c:
        return False
    shape = _shape(pref)
    if shape != "std":
        return True
    dm = DIGIT_HEAD_RE.match(pref)
    if dm:
        letter = dm.group(2)
        if not re.fullmatch(
            rf"(?:{re.escape(pref)}|{re.escape(letter)})-\d{{2,6}}", c
        ):
            return False
        n = int(c.rsplit("-", 1)[-1])
        return accept_std_serial(letter, n)
    if not re.fullmatch(rf"{re.escape(pref)}-\d{{2,6}}", c):
        return False
    n = int(c.rsplit("-", 1)[-1])
    return accept_std_serial(pref, n)


# 跨区同前缀：按标题语境分流（有码 MDS=宇宙企画；国产用 MDSR，若误挂 MDS 也走国产语境）
CHINA_CTX_RE = re.compile(
    r"麻豆|国产|國產|madou|传媒|傳媒|91制片|糖心|果冻|swag|jvid|md社|传媒映画",
    re.I,
)
JAPAN_CTX_RE = re.compile(
    r"宇宙企画|有码|有碼|無碼|无码|moodyz|madonna|fhd|censored|caribbean|heyzo|1pondo|一本道",
    re.I,
)
# 明确归属：扫描时只写入该区（另一区需靠语境命中才写）
PREFIX_HOME_REGION = {
    "MDS": "japan_censored",  # 宇宙企画；国产线是 MDSR
}


def guess_code_regions(
    text: str, pref: str, candidate_regions: list[str]
) -> list[str]:
    """多区同前缀时，按文本语境决定写入哪些区。"""
    if len(candidate_regions) <= 1:
        return list(candidate_regions)
    key = clean_prefix(pref)
    # 欧美厂牌双挂时只写 western，避免 PURETABOO 等进日本有码
    if is_western_studio_prefix(key) and "western" in candidate_regions:
        return ["western"]
    home = PREFIX_HOME_REGION.get(key)
    china_hit = bool(CHINA_CTX_RE.search(text or ""))
    japan_hit = bool(JAPAN_CTX_RE.search(text or ""))
    out: list[str] = []
    if china_hit and not japan_hit:
        out = [r for r in candidate_regions if r == "china"]
    elif japan_hit and not china_hit:
        out = [r for r in candidate_regions if r != "china"]
    elif home and home in candidate_regions:
        out = [home]
    else:
        # 写真/有码双挂（REBD 等）两侧都保留；有码+国产冲突默认只写非 china
        if "china" in candidate_regions and any(
            r.startswith("japan_") for r in candidate_regions
        ):
            out = [r for r in candidate_regions if r != "china"]
        else:
            out = list(candidate_regions)
    return out or list(candidate_regions)


def accept_fc2_code(code: str) -> bool:
    m = re.search(r"(\d+)$", code)
    if not m:
        return False
    d = m.group(1)
    return 5 <= len(d) <= 8


def accept_western_code(code: str) -> bool:
    # 拒分辨率伪号
    if re.search(r"\.(?:720|1080|2160|480)(?:\D|$)", code):
        return False
    return True


def format_std(pref: str, n: int) -> str:
    pad = 3 if n < 1000 else (4 if n < 10000 else len(str(n)))
    return f"{pref}-{str(n).zfill(pad)}"


def ingest_line(
    text: str,
    want_std: set[str],
    letter_aliases: dict[str, list[str]],
    long_std: set[str],
    long_std_re: re.Pattern[str] | None,
    special_re: re.Pattern[str] | None,
    needle_to_prefs: dict[str, list[str]],
    prefix_regions: dict[str, list[str]],
    bucket: dict[str, dict[str, set[str]]],
) -> None:
    if not text or len(text) < 4:
        return
    upper = text.upper()

    def add(pref: str, code: str) -> None:
        c = str(code or "").strip().upper()
        if not c:
            return
        shape = _shape(pref)
        if shape == "std" and not accept_std_code(pref, c):
            return
        if shape in {"fc2", "fc2ppv"} and not accept_fc2_code(c):
            return
        if shape in {"western_date", "western_ep"} and not accept_western_code(c):
            return
        key = clean_prefix(pref)
        regs = guess_code_regions(text, key, prefix_regions.get(key) or ["*"])
        slot = bucket[key]
        for rid in regs:
            slot[rid].add(c)

    for m in LONG_CODE_RE.finditer(upper):
        p = clean_prefix(m.group(1))
        targets: list[str] = []
        if p in want_std:
            targets.append(p)
        for cat in letter_aliases.get(p, ()):
            if cat not in targets:
                targets.append(cat)
        dm = DIGIT_HEAD_RE.match(p)
        if dm:
            letter = dm.group(2)
            if letter in want_std and letter not in targets:
                targets.append(letter)
        if not targets:
            continue
        clamp_pref = dm.group(2) if dm else p
        clamped = _clamp_std_code_digits(
            clamp_pref, m.group(2), following=upper[m.end() : m.end() + 12]
        )
        if not clamped:
            continue
        try:
            n = int(clamped)
        except ValueError:
            continue
        if not accept_std_serial(clamp_pref, n):
            continue
        real_code = format_std(clamp_pref if dm else p, n)
        for cat in targets:
            if cat == p and not dm:
                add(cat, format_std(cat, n))
            else:
                add(cat, real_code)

    # 超长厂牌前缀：合并正则一次命中，避免逐前缀扫全文
    if long_std_re is not None:
        hit_long = {m.group(0).upper() for m in long_std_re.finditer(upper)}
        for pref in hit_long:
            if pref in long_std:
                for code in extract_maker_codes(text, pref):
                    add(pref, code)

    if not special_re:
        return
    hit_prefs: set[str] = set()
    for m in special_re.finditer(upper):
        for pref in needle_to_prefs.get(m.group(0), ()):
            hit_prefs.add(pref)
    for pref in hit_prefs:
        for code in extract_maker_codes(text, pref):
            add(pref, code)


def filter_outlier_codes(pref: str, codes: list[str]) -> list[str]:
    """形态门闩 + robust 主簇砍离群高号（std）。"""
    shape = _shape(pref)
    codes = [c for c in codes if shape != "std" or accept_std_code(pref, c)]
    if shape != "std" or len(codes) < 8:
        return codes
    serial_map: dict[int, list[str]] = defaultdict(list)
    for c in codes:
        m = re.search(r"-(\d+)$", c)
        if not m:
            continue
        serial_map[int(m.group(1))].append(c)
    if len(serial_map) < 8:
        return codes
    rob = pr.robust_serial_max(serial_map.keys())
    if rob <= 0:
        return codes
    kept = []
    for c in codes:
        m = re.search(r"-(\d+)$", c)
        if not m:
            kept.append(c)
            continue
        n = int(m.group(1))
        if n <= rob:
            kept.append(c)
    return kept or codes


def codes_to_serials(pref: str, codes: list[str]) -> list[int]:
    out: set[int] = set()
    shape = _shape(pref)
    for c in codes:
        if shape in {"fc2", "fc2ppv"}:
            m = re.search(r"(\d{5,8})$", c)
            if m:
                out.add(int(m.group(1)))
            continue
        m = re.search(rf"(?:{re.escape(pref)}|[A-Z0-9]+)-(\d+)$", c, re.I)
        if m:
            out.add(int(m.group(1)))
            continue
        if shape in {"western_date", "western_ep"}:
            digits = re.findall(r"\d+", c)
            if len(digits) >= 3 and len(digits[0]) == 4:
                try:
                    out.add(int("".join(digits[:3])))
                except ValueError:
                    pass
    return sorted(out)


def _merge_bucket(
    dst: dict[str, dict[str, set[str]]],
    src: dict[str, dict[str, set[str]]],
) -> None:
    for key, regs in src.items():
        slot = dst[key]
        for rid, codes in regs.items():
            slot[rid] |= codes


def _ingest_chunk(
    texts: list[str],
    want_std: set[str],
    letter_aliases: dict[str, list[str]],
    long_std: set[str],
    long_std_re: re.Pattern[str] | None,
    special_re: re.Pattern[str] | None,
    needle_to_prefs: dict[str, list[str]],
    prefix_regions: dict[str, list[str]],
) -> dict[str, dict[str, set[str]]]:
    bucket: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for text in texts:
        ingest_line(
            text,
            want_std,
            letter_aliases,
            long_std,
            long_std_re,
            special_re,
            needle_to_prefs,
            prefix_regions,
            bucket,
        )
    # defaultdict → 普通 dict，便于跨线程合并
    return {k: {rid: set(codes) for rid, codes in regs.items()} for k, regs in bucket.items()}


def _fetch_sehua_texts() -> list[str]:
    rows = pg.query(
        """
        SELECT COALESCE(r.filename,'') AS filename,
               COALESCE(rs.title,'') AS title
        FROM ed2k_resources r
        LEFT JOIN LATERAL (
          SELECT title FROM resource_sources
          WHERE hash = r.hash ORDER BY created_at DESC LIMIT 1
        ) rs ON TRUE
        """
    )
    out: list[str] = []
    for row in rows:
        fn = str(row.get("filename") or "")
        title = str(row.get("title") or "")
        if fn or title:
            out.append(f"{fn}\n{title}" if title else fn)
    return out


def _fetch_bitmagnet_texts(table: str, col: str, lim: int) -> list[str]:
    brows = bitmagnet_pg.query(
        f'SELECT COALESCE("{col}",\'\') AS txt FROM "{table}" LIMIT {int(lim)}'
    )
    return [str(row.get("txt") or "") for row in brows if row.get("txt")]


def _process_texts_parallel(
    texts: list[str],
    *,
    label: str,
    stage: str,
    pct_lo: float,
    pct_hi: float,
    want_std: set[str],
    letter_aliases: dict[str, list[str]],
    long_std: set[str],
    long_std_re: re.Pattern[str] | None,
    special_re: re.Pattern[str] | None,
    needle_to_prefs: dict[str, list[str]],
    prefix_regions: dict[str, list[str]],
    bucket: dict[str, dict[str, set[str]]],
    emit: Callable[..., None],
) -> None:
    n = len(texts)
    if n == 0:
        emit(f"{label} 0/0", stage=stage, done=0, total=0, percent=pct_lo)
        return
    emit(f"{label} 0/{n:,}", stage=stage, done=0, total=n, percent=pct_lo)
    workers = max(4, min(12, (os.cpu_count() or 4)))
    chunk = max(2_000, min(12_000, n // (workers * 2) or n))
    chunks = [texts[i : i + chunk] for i in range(0, n, chunk)]
    done = 0
    last_t = 0.0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fut_sizes = {
            pool.submit(
                _ingest_chunk,
                ch,
                want_std,
                letter_aliases,
                long_std,
                long_std_re,
                special_re,
                needle_to_prefs,
                prefix_regions,
            ): len(ch)
            for ch in chunks
        }
        for fut in as_completed(fut_sizes):
            part = fut.result()
            _merge_bucket(bucket, part)
            done += fut_sizes[fut]
            now = time.monotonic()
            if done >= n or now - last_t >= 0.6:
                last_t = now
                pct = pct_lo + (pct_hi - pct_lo) * (done / max(n, 1))
                emit(
                    f"{label} {done:,}/{n:,}",
                    stage=stage,
                    done=done,
                    total=n,
                    percent=pct,
                )
    emit(
        f"{label} {n:,}/{n:,}",
        stage=stage,
        done=n,
        total=n,
        percent=pct_hi,
    )


def scan_all(
    want_std: set[str],
    letter_aliases: dict[str, list[str]],
    long_std: set[str],
    special_re: re.Pattern[str] | None,
    needle_to_prefs: dict[str, list[str]],
    prefix_regions: dict[str, list[str]],
    on_progress=None,
) -> tuple[dict[str, dict[str, set[str]]], int, int]:
    def emit(
        phase: str,
        *,
        stage: str = "",
        done: int | None = None,
        total: int | None = None,
        percent: float | None = None,
    ) -> None:
        payload = {
            "phase": phase,
            "stage": stage,
            "done": done,
            "total": total,
            "percent": None if percent is None else round(float(percent), 1),
        }
        if on_progress:
            on_progress(payload)
        else:
            print(phase, flush=True)

    long_std_re = (
        re.compile("|".join(re.escape(p) for p in sorted(long_std, key=len, reverse=True)))
        if long_std
        else None
    )

    bucket: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    bit_sources = (
        ("torrents", "name", 2_000_000),
        ("content", "title", 200_000),
        ("content", "original_title", 200_000),
    )

    emit("色花堂查询中…", stage="sehua", percent=2)
    # 色花查询与 Bitmagnet 三路查询并行，缩短总等待
    with ThreadPoolExecutor(max_workers=4) as io_pool:
        sehua_fut = io_pool.submit(_fetch_sehua_texts)
        bit_futs = {
            io_pool.submit(_fetch_bitmagnet_texts, table, col, lim): (table, col, lim)
            for table, col, lim in bit_sources
        }
        try:
            sehua_texts = sehua_fut.result()
        except Exception as e:  # noqa: BLE001
            emit(f"色花堂查询失败: {e}", stage="sehua", percent=3)
            raise
        sehua_n = len(sehua_texts)
        emit(
            f"色花堂已取 {sehua_n:,} 行 · 解析中…",
            stage="sehua",
            done=0,
            total=sehua_n,
            percent=3,
        )
        _process_texts_parallel(
            sehua_texts,
            label="色花堂",
            stage="sehua",
            pct_lo=3,
            pct_hi=70,
            want_std=want_std,
            letter_aliases=letter_aliases,
            long_std=long_std,
            long_std_re=long_std_re,
            special_re=special_re,
            needle_to_prefs=needle_to_prefs,
            prefix_regions=prefix_regions,
            bucket=bucket,
            emit=emit,
        )
        del sehua_texts

        emit("Bitmagnet 扫描中…", stage="bitmagnet", percent=72)
        bit_n = 0
        # 按完成顺序处理，谁先查完谁先解析
        pending = dict(bit_futs)
        src_total = len(pending)
        finished = 0
        while pending:
            done_futs = [f for f in pending if f.done()]
            if not done_futs:
                # 等任意一个
                for f in as_completed(pending):
                    done_futs = [f]
                    break
            for fut in done_futs:
                table, col, lim = pending.pop(fut)
                base_pct = 72 + (finished / max(src_total, 1)) * 20
                try:
                    texts = fut.result()
                except Exception as e:  # noqa: BLE001
                    emit(
                        f"跳过 {table}.{col}: {e}",
                        stage="bitmagnet",
                        percent=base_pct,
                    )
                    finished += 1
                    continue
                n = len(texts)
                bit_n += n
                span = 20 / max(src_total, 1)
                _process_texts_parallel(
                    texts,
                    label=f"Bitmagnet {table}.{col}",
                    stage="bitmagnet",
                    pct_lo=base_pct,
                    pct_hi=base_pct + span,
                    want_std=want_std,
                    letter_aliases=letter_aliases,
                    long_std=long_std,
                    long_std_re=long_std_re,
                    special_re=special_re,
                    needle_to_prefs=needle_to_prefs,
                    prefix_regions=prefix_regions,
                    bucket=bucket,
                    emit=emit,
                )
                finished += 1

    return bucket, sehua_n, bit_n


def run_local_db_index(on_progress: Callable[[Any], None] | None = None) -> dict:
    """双库单次全表扫，写回 catalog。可供 CLI / API 调用。"""

    def emit(
        phase: str,
        *,
        stage: str = "",
        done: int | None = None,
        total: int | None = None,
        percent: float | None = None,
    ) -> None:
        payload = {
            "phase": phase,
            "stage": stage,
            "done": done,
            "total": total,
            "percent": None if percent is None else round(float(percent), 1),
        }
        if on_progress:
            on_progress(payload)
        else:
            print(phase, flush=True)

    emit("加载目录…", stage="prepare", percent=1)
    doc = store.load_catalog(force=True)
    locations: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    want: set[str] = set()
    for rid in REGION_ORDER:
        for p, ent in (doc["regions"][rid].get("prefixes") or {}).items():
            key = clean_prefix(p)
            want.add(key)
            locations[key].append((rid, ent))

    special_prefs = sorted(p for p in want if is_special(p))
    want_std = {p for p in want if p not in set(special_prefs)}
    long_std = {p for p in want_std if p.isalpha() and len(p) > 12}

    letter_aliases: dict[str, list[str]] = defaultdict(list)
    for p in want_std:
        m = DIGIT_HEAD_RE.match(p)
        if m:
            letter_aliases[m.group(2)].append(p)

    needle_to_prefs: dict[str, list[str]] = {}
    for p in special_prefs:
        for n in special_needles(p):
            needle_to_prefs.setdefault(n.upper(), []).append(p)
    needles = sorted(needle_to_prefs.keys(), key=len, reverse=True)
    special_re = (
        re.compile("|".join(re.escape(n) for n in needles)) if needles else None
    )

    emit(
        f"目录 {len(want)} 前缀 · 标准 {len(want_std)} · 特殊 {len(special_prefs)}",
        stage="prepare",
        done=len(want),
        total=len(want),
        percent=2,
    )

    prefix_regions = {k: [rid for rid, _ in locs] for k, locs in locations.items()}

    bucket, sehua_n, bit_n = scan_all(
        want_std,
        dict(letter_aliases),
        long_std,
        special_re,
        needle_to_prefs,
        prefix_regions,
        on_progress=on_progress,
    )

    emit("写回目录…", stage="write", percent=95)
    updated = cleared = 0
    by_region = {rid: {"hit": 0, "codes": 0, "miss": 0} for rid in REGION_ORDER}
    miss_notes = []

    def codes_for_region(key: str, rid: str, multi: bool) -> list[str]:
        slots = bucket.get(key) or {}
        raw: set[str] = set()
        if multi:
            raw |= slots.get(rid) or set()
            # 单区命中标记 "*" 不并入冲突前缀，避免串区
        else:
            for _rid, s in slots.items():
                raw |= s
        return sorted(filter_outlier_codes(key, sorted(raw)), key=code_sort_key)

    for key, locs in locations.items():
        multi = len(locs) > 1
        for rid, ent in locs:
            codes = codes_for_region(key, rid, multi)
            prefs = doc["regions"][rid]["prefixes"]
            if codes:
                serials = codes_to_serials(key, codes)
                latest = max(codes, key=code_sort_key)
                ent = dict(ent)
                ent.update(
                    {
                        "codes": codes,
                        "serials": serials,
                        "serial_max_hint": serials[-1] if serials else 0,
                        "latest_code": latest,
                        "status": "active",
                        "integrity": "local_db_index",
                        "verified_at": store._now(),
                        "sources": sorted(
                            set(
                                list(ent.get("sources") or [])
                                + ["local-db", "bitmagnet"]
                            )
                        ),
                    }
                )
                shape = _shape(key)
                if shape == "fc2ppv":
                    ent["format"] = "FC2-PPV-{num}"
                elif shape == "fc2":
                    ent["format"] = "FC2-{num}"
                prefs[key] = store._normalize_prefix_entry(key, ent)
                updated += 1
                by_region[rid]["hit"] += 1
                by_region[rid]["codes"] += len(codes)
            else:
                ent = dict(ent)
                ent.update(
                    {
                        "codes": [],
                        "serials": [],
                        "serial_max_hint": 0,
                        "latest_code": "",
                        "integrity": "local_db_miss",
                        "verified_at": store._now(),
                    }
                )
                prefs[key] = store._normalize_prefix_entry(key, ent)
                cleared += 1
                by_region[rid]["miss"] += 1
                miss_notes.append({"region": rid, "prefix": key})

    store.save_catalog(doc)
    summary = store.public_summary(doc)
    report = {
        "mode": "one_pass_v3_parallel",
        "sehua_rows": sehua_n,
        "bitmagnet_rows": bit_n,
        "updated": updated,
        "cleared_miss": cleared,
        "by_region": by_region,
        "misses": miss_notes,
        "summary": summary,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    emit(
        f"完成 · 更新 {updated} · 未命中 {cleared} · 番号 {summary.get('code_total')}",
        stage="done",
        done=updated,
        total=len(want),
        percent=100,
    )
    return report


def main() -> None:
    report = run_local_db_index()
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    print(f"wrote {REPORT}", flush=True)


if __name__ == "__main__":
    main()
