# -*- coding: utf-8 -*-
"""Sehua + Bitmagnet 单次全表扫 → 七区真实番号。

相对旧版优化：
1. 准度：拒年份伪流水 / FC2 过长 ID；写回前用 robust_serial_max 砍离群
2. 补缺：素人数字头别名（406FCDSS←FCDSS）；长前缀走 extract；同前缀多区都写
3. 未命中分类写入报告，不按前缀 SQL
4. 写回：与旧 codes 取并集再去脏；本轮 0 命中不清空旧番号（减少误删）
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
from app.prefix.code_read import resolve_code_read  # noqa: E402
from app.core.region_meta import REGION_ORDER, std_prefix  # noqa: E402
from app.search.av import is_western_studio_prefix  # noqa: E402
from app.search.av import (  # noqa: E402
    code_sort_key,
    extract_maker_codes,
    resolve_maker_shape,
)
from app import search_av as _search_av  # noqa: E402


REPORT = ROOT / "data" / "debug" / "prefix-codes-from-local-dbs.json"
SPECIAL_SHAPES = {"fc2", "fc2ppv", "date6", "alnum_id", "western_date", "western_ep"}
DIGIT_HEAD_RE = re.compile(r"^(\d{2,3})([A-Z]{2,14})$")
# 左侧边界不含 -/_ ：避免 jukujo-club-983 被当成 CLUB-983
# 号后不得再跟字母数字：避免 gs544om8 / Start720p 粘连
LONG_CODE_RE = re.compile(
    r"(?:^|[^A-Z0-9\-_])([A-Z]{2,20}|\d{2,3}[A-Z]{2,14}|[A-Z]+\d+[A-Z]*)[-_\s]?(\d{2,6})(?![A-Z0-9])",
    re.I,
)
# 分辨率伪号：Ellies Fresh Start 720p → START-720
_RESOLUTION_SERIALS = frozenset({360, 480, 720, 1080, 1440, 2160})
_RES_FOLLOW_RE = re.compile(r"^P(?:[^A-Z]|$)", re.I)


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


def _profile_for(pref: str, profiles: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    key = clean_prefix(pref)
    if profiles and key in profiles:
        return profiles[key]
    if profiles:
        dm = DIGIT_HEAD_RE.match(key)
        if dm and dm.group(2) in profiles:
            return profiles[dm.group(2)]
    return resolve_code_read(key)


def accept_std_serial(
    pref: str,
    n: int,
    profile: dict[str, Any] | None = None,
) -> bool:
    """准度门闩：按前缀 code_read 硬顶 + 拒年份伪号/离谱大号。"""
    if n <= 0:
        return False
    prof = profile or resolve_code_read(pref)
    max_serial = prof.get("max_serial")
    if max_serial is not None:
        try:
            if n > int(max_serial):
                return False
        except (TypeError, ValueError):
            pass
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


def accept_std_code(
    pref: str,
    code: str,
    profile: dict[str, Any] | None = None,
) -> bool:
    """标准形番号：PREFIX-纯数字；拒 HEYZO-1913L / JVID-2023 / JVID-34D。"""
    pref = clean_prefix(pref)
    c = str(code or "").strip().upper()
    if not c:
        return False
    shape = _shape(pref)
    if shape != "std":
        return True
    prof = profile or resolve_code_read(pref)
    dm = DIGIT_HEAD_RE.match(pref)
    if dm:
        letter = dm.group(2)
        if not re.fullmatch(
            rf"(?:{re.escape(pref)}|{re.escape(letter)})-\d{{2,6}}", c
        ):
            return False
        n = int(c.rsplit("-", 1)[-1])
        return accept_std_serial(letter, n, prof)
    if not re.fullmatch(rf"{re.escape(pref)}-\d{{2,6}}", c):
        return False
    n = int(c.rsplit("-", 1)[-1])
    return accept_std_serial(pref, n, prof)


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
    "MKY": "japan_censored",  # 有码 MOODYZ；国产麻豆撞前缀，语境不清默认有码
}

# 本轮扫描：MKY 语境不清却默认写入有码的番号（人工抽查）
_mky_collision_suspects: set[str] = set()


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
        # MKY 撞名：语境不清走默认有码时打嫌疑标记
        if key == "MKY" and home == "japan_censored" and not china_hit and not japan_hit:
            # 调用方在 ingest 里按 code 登记；此处只返回区
            pass
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


def format_std(pref: str, n: int, profile: dict[str, Any] | None = None) -> str:
    prof = profile or resolve_code_read(pref)
    pad = int(prof.get("pad") or 0)
    if pad <= 0:
        pad = 3 if n < 1000 else (4 if n < 10000 else len(str(n)))
    width = max(pad, len(str(n)))
    return f"{pref}-{str(n).zfill(width)}"


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
    profiles: dict[str, dict[str, Any]] | None = None,
) -> None:
    if not text or len(text) < 4:
        return
    upper = text.upper()

    def add(pref: str, code: str) -> None:
        c = str(code or "").strip().upper()
        if not c:
            return
        shape = _shape(pref)
        prof = _profile_for(pref, profiles)
        if shape == "std" and not accept_std_code(pref, c, prof):
            return
        if shape in {"fc2", "fc2ppv"} and not accept_fc2_code(c):
            return
        if shape in {"western_date", "western_ep"} and not accept_western_code(c):
            return
        key = clean_prefix(pref)
        cand = prefix_regions.get(key) or ["*"]
        regs = guess_code_regions(text, key, cand)
        # MKY 撞名：语境不清默认有码 → 嫌疑标记
        if (
            key == "MKY"
            and "japan_censored" in regs
            and "china" in cand
            and not CHINA_CTX_RE.search(text or "")
            and not JAPAN_CTX_RE.search(text or "")
        ):
            _mky_collision_suspects.add(c)
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
        prof = _profile_for(clamp_pref, profiles)
        following = upper[m.end() : m.end() + 12]
        clamped = _search_av._clamp_std_code_digits(
            clamp_pref,
            m.group(2),
            following=following,
            profile=prof,
        )
        if not clamped:
            continue
        try:
            n = int(clamped)
        except ValueError:
            continue
        # Start 720p / xxx 1080p → 拒分辨率伪流水
        if n in _RESOLUTION_SERIALS and _RES_FOLLOW_RE.match(following):
            continue
        if not accept_std_serial(clamp_pref, n, prof):
            continue
        real_code = format_std(clamp_pref if dm else p, n, prof)
        for cat in targets:
            if cat == p and not dm:
                add(cat, format_std(cat, n, _profile_for(cat, profiles)))
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


def filter_outlier_codes(
    pref: str,
    codes: list[str],
    profile: dict[str, Any] | None = None,
) -> list[str]:
    """按前缀 code_read：硬顶 + robust / 主宽度离群过滤。"""
    shape = _shape(pref)
    prof = profile or resolve_code_read(pref)
    codes = [c for c in codes if shape != "std" or accept_std_code(pref, c, prof)]
    if shape != "std":
        return codes

    max_serial = prof.get("max_serial")
    if max_serial is not None:
        try:
            cap = int(max_serial)
            capped: list[str] = []
            for c in codes:
                m = re.search(r"-(\d+)$", c)
                if not m or int(m.group(1)) <= cap:
                    capped.append(c)
            codes = capped
        except (TypeError, ValueError):
            pass

    if str(prof.get("outlier") or "robust") == "none":
        return codes

    serial_map: dict[int, list[str]] = defaultdict(list)
    for c in codes:
        m = re.search(r"-(\d+)$", c)
        if not m:
            continue
        serial_map[int(m.group(1))].append(c)
    nums = list(serial_map.keys())
    if len(nums) < 3:
        return codes

    prefer = prof.get("prefer_digit_len")
    try:
        prefer_n = int(prefer) if prefer is not None else 0
    except (TypeError, ValueError):
        prefer_n = 0

    rob = pr.robust_serial_max(nums) if len(nums) >= 5 else max(nums)
    if rob <= 0:
        return codes

    # 主宽度优先：std3_dmm → 三位数；amateur4/std4 → 四位数；std3_open 不钉死位数
    if prefer_n in {3, 4}:
        bound = 10 ** prefer_n
        low = [n for n in nums if n < bound]
        high = sorted(n for n in nums if n >= bound)
        if len(low) >= 3:
            rob_low = pr.robust_serial_max(low) if len(low) >= 5 else max(low)
            attach = False
            low_ratio = len(low) / max(1, len(nums))
            gap_abs = int(getattr(pr, "SERIAL_GAP_ABS", 50) or 50)
            near_cap = bound + (50 if prefer_n == 3 else 500)
            if high and rob_low > 0 and low_ratio >= 0.35:
                if high[0] <= rob_low + gap_abs and high[0] <= near_cap:
                    near = [n for n in high if n <= high[0] + 200]
                    if len(near) >= max(5, int(0.08 * len(low))):
                        attach = True
                        rob = max(rob_low, pr.robust_serial_max(low + near))
            if not attach and (low_ratio >= 0.35 or (high and high[0] - rob_low > gap_abs)):
                rob = rob_low
            elif not attach and not high:
                rob = min(rob, rob_low)

    if max_serial is not None:
        try:
            rob = min(rob, int(max_serial))
        except (TypeError, ValueError):
            pass

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
    profiles: dict[str, dict[str, Any]] | None = None,
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
            profiles,
        )
    # defaultdict → 普通 dict，便于跨线程合并
    return {k: {rid: set(codes) for rid, codes in regs.items()} for k, regs in bucket.items()}


_SEHUA_SQL = """
SELECT COALESCE(r.filename,'') AS filename,
       COALESCE(rs.title,'') AS title
FROM ed2k_resources r
LEFT JOIN LATERAL (
  SELECT title FROM resource_sources
  WHERE hash = r.hash ORDER BY created_at DESC LIMIT 1
) rs ON TRUE
"""

# 单批进内存的行数。整表 fetchall 会把 API 进程撑死，轮询变成 500。
_TEXT_CHUNK = 8_000


def _sehua_line(row: dict[str, Any]) -> str:
    fn = str(row.get("filename") or "")
    title = str(row.get("title") or "")
    if not (fn or title):
        return ""
    return f"{fn}\n{title}" if title else fn


def _iter_sehua_chunks():
    buf: list[str] = []
    for rows in pg.iter_batches(
        _SEHUA_SQL, batch_size=2_000, statement_timeout_ms=1_800_000
    ):
        for row in rows:
            line = _sehua_line(row)
            if line:
                buf.append(line)
        while len(buf) >= _TEXT_CHUNK:
            yield buf[:_TEXT_CHUNK]
            del buf[:_TEXT_CHUNK]
    if buf:
        yield buf


def _bitmagnet_sql(table: str, col: str, lim: int) -> str:
    if table == "torrent_contents":
        return f"""
            SELECT COALESCE(t.name, '') AS txt
            FROM torrent_contents tc
            JOIN torrents t ON t.info_hash = tc.info_hash
            WHERE COALESCE(t.name, '') <> ''
            LIMIT {int(lim)}
        """
    return (
        f'SELECT COALESCE("{col}",\'\') AS txt FROM "{table}" LIMIT {int(lim)}'
    )


def _iter_bitmagnet_chunks(table: str, col: str, lim: int):
    timeout_ms = 600_000 if table in {"torrent_contents", "torrents"} else 120_000
    buf: list[str] = []
    seen = 0
    for rows in bitmagnet_pg.iter_batches(
        _bitmagnet_sql(table, col, lim),
        batch_size=2_000,
        statement_timeout_ms=timeout_ms,
    ):
        for row in rows:
            if seen >= lim:
                break
            seen += 1
            txt = str(row.get("txt") or "")
            if txt:
                buf.append(txt)
            if len(buf) >= _TEXT_CHUNK:
                yield buf
                buf = []
        else:
            continue
        break
    if buf:
        yield buf


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
    profiles: dict[str, dict[str, Any]] | None = None,
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
                profiles,
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
    profiles: dict[str, dict[str, Any]] | None = None,
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
        # 真正解析过的种子 ≈ torrent_contents（约 290 万），join torrents.name
        ("torrent_contents", "name", 3_200_000),
    )

    emit("色花堂查询中…", stage="sehua", percent=2)
    sehua_n = 0
    try:
        for chunk in _iter_sehua_chunks():
            sehua_n += len(chunk)
            _process_texts_parallel(
                chunk,
                label="色花堂",
                stage="sehua",
                pct_lo=3,
                pct_hi=min(70.0, 3 + sehua_n / 80_000),
                want_std=want_std,
                letter_aliases=letter_aliases,
                long_std=long_std,
                long_std_re=long_std_re,
                special_re=special_re,
                needle_to_prefs=needle_to_prefs,
                prefix_regions=prefix_regions,
                bucket=bucket,
                emit=emit,
                profiles=profiles,
            )
    except Exception as e:  # noqa: BLE001
        emit(f"色花堂查询失败: {e}", stage="sehua", percent=3)
        raise
    emit(
        f"色花堂已处理 {sehua_n:,} 行",
        stage="sehua",
        done=sehua_n,
        total=sehua_n,
        percent=70,
    )

    emit("Bitmagnet 扫描中…", stage="bitmagnet", percent=72)
    bit_n = 0
    src_total = len(bit_sources)
    finished = 0
    for table, col, lim in bit_sources:
        base_pct = 72 + (finished / max(src_total, 1)) * 20
        span = 20 / max(src_total, 1)
        try:
            for chunk in _iter_bitmagnet_chunks(table, col, lim):
                bit_n += len(chunk)
                _process_texts_parallel(
                    chunk,
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
                    profiles=profiles,
                )
        except Exception as e:  # noqa: BLE001
            emit(
                f"跳过 {table}.{col}: {e}",
                stage="bitmagnet",
                percent=base_pct,
            )
        finished += 1

    return bucket, sehua_n, bit_n


def run_local_db_index(on_progress: Callable[[Any], None] | None = None) -> dict:
    """双库单次全表扫，写回 catalog。可供 CLI / API 调用。"""
    # 长驻 API 下本脚本每次热加载，但 app.* 可能仍是旧缓存；入口强制刷新。
    global resolve_code_read, _search_av, store, pr, code_sort_key, extract_maker_codes, resolve_maker_shape
    import importlib

    from app import prefix_catalog_store as _store_mod
    from app import prefix_code_read as _pcr_mod
    from app import prefix_ranges as _pr_mod
    from app import search_av as _sav_mod

    _pcr_mod = importlib.reload(_pcr_mod)
    _sav_mod = importlib.reload(_sav_mod)
    _pr_mod = importlib.reload(_pr_mod)
    _store_mod = importlib.reload(_store_mod)
    resolve_code_read = _pcr_mod.resolve_code_read
    _search_av = _sav_mod
    code_sort_key = _sav_mod.code_sort_key
    extract_maker_codes = _sav_mod.extract_maker_codes
    resolve_maker_shape = _sav_mod.resolve_maker_shape
    pr = _pr_mod
    store = _store_mod
    # 清掉 shape/prefix 缓存，避免绑到旧 resolve_maker_shape
    clean_prefix.cache_clear()
    _shape.cache_clear()

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
    global _mky_collision_suspects
    _mky_collision_suspects = set()
    doc = store.load_catalog(force=True)
    # 回填每个前缀的 code_read（缺失则推断）
    for rid in REGION_ORDER:
        prefs = doc["regions"][rid].get("prefixes") or {}
        for p, ent in list(prefs.items()):
            prefs[p] = store._normalize_prefix_entry(p, ent)

    locations: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    want: set[str] = set()
    profiles: dict[str, dict[str, Any]] = {}
    for rid in REGION_ORDER:
        for p, ent in (doc["regions"][rid].get("prefixes") or {}).items():
            key = clean_prefix(p)
            want.add(key)
            locations[key].append((rid, ent))
            if key not in profiles:
                profiles[key] = resolve_code_read(key, ent)

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
        profiles=profiles,
    )

    emit("写回目录…", stage="write", percent=95)
    updated = cleared = 0
    kept_miss = 0
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
        return sorted(raw, key=code_sort_key)

    def merge_codes(key: str, old_codes: list[Any], scanned: list[str]) -> list[str]:
        """旧号 ∪ 本轮扫到 → 准度过滤 → 离群裁剪。保留真号，丢掉明显脏号。"""
        prof = profiles.get(key) or resolve_code_read(key)
        merged: set[str] = set()
        for raw in list(old_codes or []) + list(scanned or []):
            c = str(raw or "").strip().upper()
            if not c:
                continue
            if not accept_std_code(key, c, prof):
                continue
            merged.add(c)
        if not merged:
            return []
        return sorted(
            filter_outlier_codes(key, sorted(merged), prof),
            key=code_sort_key,
        )

    for key, locs in locations.items():
        multi = len(locs) > 1
        prof = profiles.get(key) or resolve_code_read(key)
        for rid, ent in locs:
            scanned = codes_for_region(key, rid, multi)
            prefs = doc["regions"][rid]["prefixes"]
            old_codes = list(ent.get("codes") or [])
            codes = merge_codes(key, old_codes, scanned)
            if scanned:
                serials = codes_to_serials(key, codes)
                latest = max(codes, key=code_sort_key) if codes else ""
                hint = serials[-1] if serials else 0
                max_serial = prof.get("max_serial")
                if max_serial is not None and hint:
                    try:
                        hint = min(hint, int(max_serial))
                    except (TypeError, ValueError):
                        pass
                ent = dict(ent)
                ent.update(
                    {
                        "codes": codes,
                        "serials": serials,
                        "serial_max_hint": hint,
                        "latest_code": latest,
                        "code_read": str(prof.get("id") or ent.get("code_read") or ""),
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
                # MKY 撞名嫌疑：本轮语境不清默认写入有码的番号
                if key == "MKY" and rid == "japan_censored" and _mky_collision_suspects:
                    hit = sorted(c for c in codes if c in _mky_collision_suspects)
                    if hit:
                        note = str(ent.get("notes") or "")
                        tag = f"mky_collision_suspect×{len(hit)}"
                        if "mky_collision_suspect" not in note:
                            ent["notes"] = (note + " · " + tag).strip(" ·")
                        else:
                            ent["notes"] = re.sub(
                                r"mky_collision_suspect×\d+",
                                tag,
                                note,
                            )
                prefs[key] = store._normalize_prefix_entry(key, ent)
                updated += 1
                by_region[rid]["hit"] += 1
                by_region[rid]["codes"] += len(codes)
            else:
                # 本轮 0 命中：保留旧番号，只打 miss 标记（避免误清空真号）
                ent = dict(ent)
                if old_codes:
                    kept = merge_codes(key, old_codes, [])
                    serials = codes_to_serials(key, kept)
                    ent.update(
                        {
                            "codes": kept,
                            "serials": serials,
                            "serial_max_hint": serials[-1] if serials else 0,
                            "latest_code": max(kept, key=code_sort_key) if kept else "",
                            "code_read": str(
                                prof.get("id") or ent.get("code_read") or ""
                            ),
                            "integrity": "local_db_miss_keep",
                            "verified_at": store._now(),
                        }
                    )
                    kept_miss += 1
                    by_region[rid]["codes"] += len(kept)
                else:
                    ent.update(
                        {
                            "codes": [],
                            "serials": [],
                            "serial_max_hint": 0,
                            "latest_code": "",
                            "code_read": str(
                                prof.get("id") or ent.get("code_read") or ""
                            ),
                            "integrity": "local_db_miss",
                            "verified_at": store._now(),
                        }
                    )
                    cleared += 1
                prefs[key] = store._normalize_prefix_entry(key, ent)
                by_region[rid]["miss"] += 1
                miss_notes.append({"region": rid, "prefix": key})

    store.save_catalog(doc)
    summary = store.public_summary(doc)
    report = {
        "mode": "one_pass_v3_parallel_merge_keep",
        "sehua_rows": sehua_n,
        "bitmagnet_rows": bit_n,
        "updated": updated,
        "cleared_miss": cleared,
        "kept_miss": kept_miss,
        "by_region": by_region,
        "misses": miss_notes,
        "summary": summary,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    emit(
        f"完成 · 更新 {updated} · 未命中保留 {kept_miss} · 空前缀 {cleared}"
        f" · 番号 {summary.get('code_total')}",
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
