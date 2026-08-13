"""番号前缀 1..N 上限：按库内最大流水号估算，每日 00:00 增量刷新。

运行时缓存：`data/prefix-code-ranges.json`（可写，不依赖 Next 打包）。
种子：`apps/web/src/config/prefix-code-ranges.json`（首次无缓存时拷贝）。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .db import ROOT, db_path

log = logging.getLogger(__name__)

HEADROOM_MIN = 10
HEADROOM_PCT = 0.03
ROUND_STEP = 10
# 流水号离群：大空洞后的孤立高号（如 MIMK 密到 286 却冒出 726）不进 db_max
SERIAL_GAP_ABS = 50
SERIAL_GAP_REL = 0.35
SERIAL_CLUSTER_MIN = 3
SERIAL_CLUSTER_MIN_FRAC = 0.05

WEB_SEED = (
    ROOT / "apps" / "web" / "src" / "config" / "prefix-code-ranges.json"
)
MAKERS_FILES = (
    ROOT / "apps" / "web" / "src" / "config" / "av-makers.japan.json",
    ROOT / "apps" / "web" / "src" / "config" / "av-makers.china.json",
    ROOT / "apps" / "web" / "src" / "config" / "av-makers.western.json",
)

SKIP_PREFIXES = {
    "FC2",
    "FC2PPV",
    "CARIB",
    "CARIBPR",
    "1PON",
    "HEYZO",
    "TOKYOHOT",
    "H0930",
    "C0930",
    "H4610",
    "10MU",
    "PACO",
    "XXX-AV",
    "HEYDOUGA",
    "MESUBUTA",
    "KIN8",
    "SPERMMANIA",
    "RHJ",
    "GACHINCO",
    "COSPURI",
    "BRAZZERS",
    "BLACKED",
    "BLACKEDRAW",
    "TUSHY",
    "VIXEN",
    "DEEPER",
    "REALITYKINGS",
    "RK",
    "NAUGHTYAMERICA",
    "BANGBROS",
    "BANGBUS",
    "MOFOS",
    "FAKETAXI",
    "FAKEHUB",
    "EVILANGEL",
    "JULESJORDAN",
    "ADULTTIME",
    "DORCEL",
    "PRIVATE",
    "ONLYFANS",
    "MANYVIDS",
    "DIGITALPLAYGROUND",
    "ELEGANTANGEL",
    "LETHALHARDCORE",
    "ANALVIDS",
    "KINK",
    "PUBLICAGENT",
    "FAMILYSTROKES",
    "TEAMSKEET",
    "BRATTYSIS",
    "NUBILES",
    "NUBILEFILMS",
    "LEGALPORNO",
    "TUSHYRAW",
    "RKPRIME",
    "SEXMEX",
    "PORNWORLD",
    "MILFY",
    "WICKED",
    "SEXART",
    "WATCH4BEAUTY",
    "PLAYBOYPLUS",
    "DORCELCLUB",
    "JVID",
}

NOISE = {
    "HD",
    "FHD",
    "UHD",
    "MP4",
    "AVI",
    "MKV",
    "WMV",
    "CH",
    "CD",
    "PART",
    "VOL",
    "DVD",
    "ISO",
    "X264",
    "X265",
    "HEVC",
    "AAC",
    "H264",
    "H265",
    "WEB",
    "DL",
    "BD",
    "PDF",
    "ZIP",
    "RAR",
    "THE",
    "AND",
    "FOR",
}

CODE_RE = re.compile(
    r"(?:^|[^A-Z0-9])([A-Z]{2,12}|\d{2,3}[A-Z]{2,10}|[A-Z]+\d+[A-Z]*)[-_\s]?(\d{2,6})(?![0-9])",
    re.I,
)

_lock = threading.Lock()
_doc: dict[str, Any] | None = None
_stop = threading.Event()
_thread: threading.Thread | None = None


def cache_path() -> Path:
    return db_path().parent / "prefix-code-ranges.json"


def norm_prefix(prefix: str) -> str:
    return str(prefix or "").strip().upper().replace("_", "-")


def estimate_to(db_max: int) -> int:
    if db_max <= 0:
        return 0
    buf = max(HEADROOM_MIN, int(db_max * HEADROOM_PCT + 0.999))
    raw = db_max + buf
    return ((raw + ROUND_STEP - 1) // ROUND_STEP) * ROUND_STEP


def robust_serial_max(nums: list[int] | set[int]) -> int:
    """从流水号集合取稳健上限：丢掉大空洞后的稀疏离群点。

    例：…285,286,726 → 主簇止于 286，忽略 726。
    空隙阈值 max(50, 0.35*前号)；取够大簇（≥max(3,总数5%)）中最高号。
    """
    uniq = sorted({int(n) for n in nums if int(n) > 0})
    if not uniq:
        return 0
    if len(uniq) == 1:
        return uniq[0]

    clusters: list[list[int]] = [[uniq[0]]]
    for x in uniq[1:]:
        prev = clusters[-1][-1]
        thr = max(SERIAL_GAP_ABS, int(prev * SERIAL_GAP_REL))
        if x - prev > thr:
            clusters.append([x])
        else:
            clusters[-1].append(x)

    total = len(uniq)
    min_size = max(
        SERIAL_CLUSTER_MIN, int(total * SERIAL_CLUSTER_MIN_FRAC + 0.999)
    )
    candidates = [c for c in clusters if len(c) >= min_size]
    if not candidates:
        candidates = [max(clusters, key=len)]
    best = max(candidates, key=lambda c: c[-1])
    return int(best[-1])


_china_prefixes_cache: set[str] | None = None


def load_china_prefixes() -> set[str]:
    """国产厂牌前缀（麻豆等常用四位补零：MDSR-0002）。"""
    global _china_prefixes_cache
    if _china_prefixes_cache is not None:
        return _china_prefixes_cache
    path = ROOT / "apps" / "web" / "src" / "config" / "av-makers.china.json"
    out: set[str] = set()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for m in data:
                for p in m.get("prefixes") or []:
                    k = norm_prefix(p)
                    if k:
                        out.add(k)
        except Exception:
            log.exception("load china prefixes failed")
    _china_prefixes_cache = out
    return out


def choose_pad(prefix: str, to: int) -> int:
    if re.match(r"^\d", prefix):
        return 4 if to < 10000 else max(4, len(str(to)))
    # 国产不要全区强制 4：JD 帖题是 JD-150，MDSR 才是 MDSR-0002
    # 具体位数由扫库后按前缀主宽度回写；此处默认 3
    return 3


def load_maker_prefixes() -> list[str]:
    keys: list[str] = []
    for path in MAKERS_FILES:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for m in data:
            for p in m.get("prefixes") or []:
                keys.append(norm_prefix(p))
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _empty_doc() -> dict[str, Any]:
    return {
        "version": "dbmax-daily-v2",
        "updated": "",
        "principle": (
            "to 由库内流水主簇稳健上限 + 余量估算；"
            "大空洞后的离群高号不计；每日增量上调，离群修正可下调"
        ),
        "format": "CODE = PREFIX + '-' + zeroPad(n, pad)",
        "ranges": {},
        "skip": sorted(SKIP_PREFIXES),
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("ranges"), dict):
            return raw
    except Exception:
        log.exception("read prefix ranges failed: %s", path)
    return None


def _write_doc(doc: dict[str, Any]) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def ensure_loaded() -> dict[str, Any]:
    global _doc
    with _lock:
        if _doc is not None:
            return _doc
        cached = _read_json(cache_path())
        if cached:
            _doc = cached
            return _doc
        seed = _read_json(WEB_SEED)
        if seed:
            _doc = seed
            _write_doc(_doc)
            log.info("prefix ranges seeded from web config → %s", cache_path())
            return _doc
        _doc = _empty_doc()
        _write_doc(_doc)
        return _doc


def scan_db_maxima(known: set[str]) -> dict[str, int]:
    """扫库得到各前缀稳健流水上限（忽略大空洞后的离群高号）。"""
    from . import pg

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
    serials: dict[str, set[int]] = defaultdict(set)
    for row in rows:
        text = f"{row['filename']}\n{row['title']}".upper()
        for m in CODE_RE.finditer(text):
            p = m.group(1).upper().replace("_", "-")
            if p not in known or p in NOISE or p in SKIP_PREFIXES:
                continue
            try:
                raw_num = m.group(2)
                # 按规范位数截断，避免 EBWH-061100cm → 61100 污染上限
                from .search_av import _clamp_std_code_digits

                end = m.end()
                clamped = _clamp_std_code_digits(
                    p, raw_num, following=text[end : end + 12]
                )
                if not clamped:
                    continue
                n = int(clamped)
            except ValueError:
                continue
            if n <= 0 or n > 999999:
                continue
            serials[p].add(n)

    maxima: dict[str, int] = {}
    for p, nums in serials.items():
        raw_max = max(nums) if nums else 0
        rob = robust_serial_max(nums)
        if raw_max > rob >= 1:
            log.info(
                "prefix %s robust max %s (raw max %s trimmed)",
                p,
                rob,
                raw_max,
            )
        if rob > 0:
            maxima[p] = rob
    return maxima


def refresh_from_db(*, incremental: bool = True) -> dict[str, Any]:
    """扫库刷新上限。incremental 默认只上调；稳健上限明显低于旧值时可下调（离群修正）。"""
    global _doc
    prefixes = load_maker_prefixes()
    known = {
        p
        for p in prefixes
        if p not in SKIP_PREFIXES and p.replace("-", "") not in SKIP_PREFIXES
    }
    log.info("prefix ranges refresh start (prefixes=%s incremental=%s)", len(known), incremental)
    t0 = time.time()
    maxima = scan_db_maxima(known)
    elapsed = time.time() - t0

    # 锁外准备旧表，避免与 ensure_loaded 嵌套加锁
    ensure_loaded()
    with _lock:
        prev = dict((_doc or {}).get("ranges") or {})
        ranges: dict[str, dict[str, Any]] = {}
        skip = sorted(
            {
                p
                for p in prefixes
                if p in SKIP_PREFIXES or p.replace("-", "") in SKIP_PREFIXES
            }
        )
        bumped = 0
        trimmed = 0
        for p in prefixes:
            if p in SKIP_PREFIXES or p.replace("-", "") in SKIP_PREFIXES:
                continue
            db_max = int(maxima.get(p) or 0)
            old = prev.get(p) or {}
            old_to = int(old.get("to") or 0)
            old_from = int(old.get("from") or 1) or 1
            old_db = int(old.get("db_max") or 0)

            if db_max > 0:
                est = estimate_to(db_max)
                outlier_trim = bool(
                    incremental
                    and old_to > 0
                    and db_max < old_db
                    and est < old_to
                    and (old_db - db_max) >= SERIAL_GAP_ABS
                )
                if incremental and not outlier_trim:
                    to = max(est, old_to)
                else:
                    to = est
                if to > old_to:
                    bumped += 1
                elif to < old_to and (outlier_trim or not incremental):
                    trimmed += 1
                source = f"db_max={db_max} → to={to}"
                if outlier_trim:
                    source += " (outlier trim)"
            elif old_to > 0:
                to = old_to
                source = str(old.get("source") or f"keep to={to}")
            else:
                to = 99
                source = "default 1..99（库内无命中）"

            frm = 1
            if db_max <= 0 and old_from > 1:
                frm = old_from
                if to < frm:
                    to = frm

            entry: dict[str, Any] = {
                "from": frm,
                "to": to,
                "pad": (
                    max(1, min(8, int(old.get("pad") or 3)))
                    if old.get("padLocked")
                    else choose_pad(p, to)
                ),
                "source": source,
            }
            if old.get("padLocked"):
                entry["padLocked"] = True
            if db_max > 0:
                entry["db_max"] = db_max
            ranges[p] = entry

        doc = {
            "version": "dbmax-daily-v2",
            "updated": date.today().isoformat(),
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "principle": (
                "to 由库内流水主簇稳健上限 + 余量估算；"
                "大空洞后的离群高号不计；每日增量上调，离群修正可下调"
            ),
            "format": "CODE = PREFIX + '-' + zeroPad(n, pad)",
            "ranges": dict(sorted(ranges.items())),
            "skip": skip,
        }
        _doc = doc
        _write_doc(doc)

    log.info(
        "prefix ranges refresh done in %.1fs hits=%s bumped=%s trimmed=%s → %s",
        elapsed,
        len(maxima),
        bumped,
        trimmed,
        cache_path(),
    )
    return doc


def set_pad(prefix: str, pad: int, *, lock: bool = True) -> dict[str, Any] | None:
    """设置前缀规范位数；lock=True 时每日扫库不覆盖 pad。"""
    global _doc
    key = norm_prefix(prefix)
    if not key or key in SKIP_PREFIXES:
        return None
    width = max(1, min(8, int(pad or 3)))
    ensure_loaded()
    with _lock:
        assert _doc is not None
        ranges = dict(_doc.get("ranges") or {})
        entry = dict(
            ranges.get(key)
            or {
                "from": 1,
                "to": 99,
                "pad": width,
                "source": "user-pad",
            }
        )
        entry["pad"] = width
        if lock:
            entry["padLocked"] = True
        else:
            entry.pop("padLocked", None)
        entry["source"] = str(entry.get("source") or "user-pad")
        ranges[key] = entry
        _doc = {
            **_doc,
            "ranges": dict(sorted(ranges.items())),
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        _write_doc(_doc)
    # 同步本地 maker-fs 索引里的 pad（若有）
    try:
        from . import maker_fs

        maker_fs.sync_prefix_pad(key, width)
    except Exception:
        log.debug("sync maker-fs pad %s failed", key, exc_info=True)
    return get_range(key)


def get_range(prefix: str) -> dict[str, Any] | None:
    key = norm_prefix(prefix)
    if not key:
        return None
    doc = ensure_loaded()
    if key in set(doc.get("skip") or []) or key in SKIP_PREFIXES:
        return None
    r = (doc.get("ranges") or {}).get(key)
    if not r:
        # 无缓存条目时仍返回默认可编辑骨架，便于 UI 设定位数
        return {
            "prefix": key,
            "from": 1,
            "to": 99,
            "pad": choose_pad(key, 99),
            "total": 99,
            "db_max": None,
            "source": "default",
            "padLocked": False,
            "updated": doc.get("updated") or doc.get("updated_at"),
            "sample": f"{key}-{1:0{choose_pad(key, 99)}d}",
        }
    frm = max(1, int(r.get("from") or 1))
    to = max(frm, int(r.get("to") or frm))
    pad = max(1, min(8, int(r.get("pad") or 3)))
    return {
        "prefix": key,
        "from": frm,
        "to": to,
        "pad": pad,
        "total": to - frm + 1,
        "db_max": r.get("db_max"),
        "source": r.get("source"),
        "padLocked": bool(r.get("padLocked")),
        "updated": doc.get("updated") or doc.get("updated_at"),
        "sample": f"{key}-{1:0{pad}d}",
    }


def needs_daily_refresh() -> bool:
    doc = ensure_loaded()
    updated = str(doc.get("updated") or "")[:10]
    return updated != date.today().isoformat()


def _seconds_until_next_midnight() -> float:
    now = datetime.now().astimezone()
    tomorrow = now.date() + timedelta(days=1)
    nxt = datetime.combine(tomorrow, datetime.min.time(), tzinfo=now.tzinfo)
    return max(1.0, (nxt - now).total_seconds())


def _scheduler_loop() -> None:
    log.info("prefix ranges daily scheduler started (next run ~00:00 local)")
    # 启动补跑：缓存不是今天的则后台扫一次
    try:
        if needs_daily_refresh():
            log.info("prefix ranges stale → catch-up refresh")
            refresh_from_db(incremental=True)
    except Exception:
        log.exception("prefix ranges catch-up refresh failed")

    while not _stop.is_set():
        wait = _seconds_until_next_midnight()
        log.info("prefix ranges next refresh in %.0fs", wait)
        if _stop.wait(wait):
            break
        try:
            refresh_from_db(incremental=True)
        except Exception:
            log.exception("prefix ranges daily refresh failed")


def start_daily_scheduler() -> None:
    global _thread
    ensure_loaded()
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_scheduler_loop,
        name="prefix-ranges-daily",
        daemon=True,
    )
    _thread.start()


def stop_daily_scheduler() -> None:
    _stop.set()
