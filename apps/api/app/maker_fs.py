"""厂商区本地索引（maker-fs）L1。

目录规范::

    data/maker-fs/
      manifest.json
      regions.json              # 七区总览
      tree.json                 # 片区导航骨架（来自 boards.nav.json）
      r/{region}/
        index.json              # 该区番号前缀细表
        p/{PREFIX}/index.json   # 前缀范围 + 番号封面（URL）+ 影片名称
                                # （女优名仅日本有码 / 日本写真）

七区（与 boards.nav 片区 + 区域白名单对齐）::

    japan_censored   日本有码
    japan_gravure    日本写真   （读库 region=japan）
    japan_uncensored 日本无码
    japan_amateur    日本素人   （读库 japan_censored / 104 素人板）
    fc2              FC2        （读库 japan_uncensored · 104:536）
    china            国产无码
    western          欧美无码

运行时浏览只读上述文件，不查 Postgres。点开番号仍走现有 /search。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import ROOT

log = logging.getLogger(__name__)

# 导出并发：受 Postgres pool max_size=8 约束，留 2 给前台查询
DEFAULT_EXPORT_WORKERS = 8
DEFAULT_SKIP_FRESH_HOURS = 24

MAKER_FS_ROOT = ROOT / "data" / "maker-fs"
NAV_PATH = ROOT / "apps" / "web" / "src" / "config" / "boards.nav.json"

# 稳定 id → 展示名；db_region 供 prefix_service / 白名单查询
# 顺序即本地索引列表顺序
REGION_META: dict[str, dict[str, str]] = {
    "japan_censored": {
        "id": "japan_censored",
        "label": "日本有码",
        "db_region": "japan_censored",
        "navPath": "片区/日本/有码",
    },
    "japan_gravure": {
        "id": "japan_gravure",
        "label": "日本写真",
        "db_region": "japan",
        "navPath": "片区/日本/写真",
    },
    "japan_uncensored": {
        "id": "japan_uncensored",
        "label": "日本无码",
        "db_region": "japan_uncensored",
        "navPath": "片区/日本/无码",
    },
    "japan_amateur": {
        "id": "japan_amateur",
        "label": "日本素人",
        "db_region": "japan_amateur",
        "navPath": "片区/日本/素人",
    },
    "fc2": {
        "id": "fc2",
        "label": "FC2",
        "db_region": "fc2",
        "navPath": "片区/日本/FC2",
    },
    "china": {
        "id": "china",
        "label": "国产无码",
        "db_region": "china",
        "navPath": "片区/国产/无码",
    },
    "western": {
        "id": "western",
        "label": "欧美无码",
        "db_region": "western",
        "navPath": "片区/欧美/无码",
    },
}

REGION_ORDER = list(REGION_META.keys())

# 仅这两区把女优名写入 maker-fs 索引；其它区只保留标题
FORUM_ACTORS_INDEX_REGIONS = frozenset({"japan_censored", "japan_gravure"})

_build_lock = threading.Lock()
_meta_lock = threading.Lock()
_build_state: dict[str, Any] = {
    "running": False,
    "startedAt": "",
    "finishedAt": "",
    "message": "",
    "prefixes": 0,
    "prefixTotal": 0,
    "covers": 0,
    "skipped": 0,
    "workers": 0,
    "region": "",
    "currentPrefix": "",
    "updatedAt": "",
    # rid -> {done,total,covers,currentPrefix,updatedAt}
    "regionProgress": {},
}


def _empty_region_progress(total: int = 0) -> dict[str, Any]:
    return {
        "done": 0,
        "total": int(total or 0),
        "covers": 0,
        "currentPrefix": "",
        "active": [],
        "updatedAt": "",
    }


def _reset_build_progress(
    *,
    region: str = "",
    message: str = "",
    running: bool = False,
) -> None:
    """清空进度字段（入队 / 结束时调用；调用方须持 _meta_lock）。"""
    _build_state.update(
        {
            "running": running,
            "finishedAt": "" if running else _build_state.get("finishedAt") or "",
            "message": message,
            "prefixes": 0,
            "prefixTotal": 0,
            "covers": 0,
            "skipped": 0,
            "workers": 0,
            "region": region or "",
            "currentPrefix": "",
            "updatedAt": _now_iso() if running else "",
            "regionProgress": {},
        }
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _std_prefix(prefix: str) -> str:
    return str(prefix or "").strip().upper().replace("_", "-")


def _std_code_key(code: str, *, pad: int = 3) -> str:
    """统一番号键（委托 search_av.std_code_key：四位国产、丢分集/字母尾缀）。"""
    from .search_av import std_code_key

    return std_code_key(code, pad=pad)


def _index_format_matches(fmt: str, parsed_shape: str) -> bool:
    f = str(fmt or "").strip().lower()
    s = str(parsed_shape or "").strip().lower()
    if f == "date6":
        return s == "date6"
    if f in {"fc2", "fc2ppv"}:
        return s in {"fc2", "fc2ppv"}
    if f in {"western_date", "western_scene"}:
        return s in {"western_date", "western_scene", "western_ym", "western_year", "western_ep"}
    if f == "alnum_id":
        return s == "alnum_id"
    if f == "fixed_std":
        return s in {"fixed_std", "std"}
    return f == s


def _index_raw_under_prefix(raw: str, pref: str) -> str | None:
    """源串已落在本前缀（或别名）下时保留，并把 hub 收成 canonical。"""
    from .search_av import canonical_prefix, prefix_aliases

    ru = str(raw or "").strip().upper().replace("_", "-")
    pu = _std_prefix(pref)
    if not ru or not pu:
        return None
    hub = canonical_prefix(pu) or pu
    aliases = prefix_aliases(pu) | {pu, hub}
    if ru == pu or ru == hub or ru in aliases:
        return hub
    for a in sorted(aliases, key=len, reverse=True):
        if not a:
            continue
        if ru.startswith(f"{a}-"):
            return f"{hub}-{ru[len(a) + 1 :]}"
        if ru.startswith(f"{a}."):
            return f"{hub}.{ru[len(a) + 1 :]}"
    return None


def _index_prefix_belongs(
    pref: str,
    *,
    parsed_prefix: str,
    canonical: str,
    shape: str,
) -> bool:
    """非流水格式：判断解析结果是否属于当前索引前缀（含别名）。"""
    from .search_av import canonical_prefix, prefixes_equivalent

    pref_u = _std_prefix(pref)
    pp = _std_prefix(parsed_prefix)
    can = str(canonical or "").strip().upper()
    if not pref_u or not can:
        return False
    if prefixes_equivalent(pref_u, pp):
        return True
    hub = canonical_prefix(pref_u) or pref_u
    if shape in {"fc2", "fc2ppv"}:
        return can.startswith("FC2-") or can.startswith("FC2PPV")
    if shape == "date6":
        return can.startswith(f"{hub}-")
    if shape in {"western_date", "western_scene"}:
        return can.startswith(f"{hub}.") or can.startswith(f"{pref_u}.")
    if shape == "alnum_id":
        return can.startswith(f"{hub}-")
    if shape in {"fixed_std", "std"}:
        return can.startswith(f"{hub}-") or can.startswith(f"{pref_u}-")
    return False


def _extract_serial_for_prefix(raw: str, pref: str) -> tuple[int, str] | None:
    """抽出属于 pref 的流水号与原始数字串（保留前导零信息）。

    兼容：
    - SONE-015 / SONE-15C / ADN-749CH
    - 200GANA-409 ↔ GANA-409（素人数字头前缀）
    - GACHINCO ↔ GACHI 等 PREFIX_CANONICAL 别名
    返回 (n, num_s)；对不上则 None。
    """
    from .search_av import prefix_aliases

    pref_u = _std_prefix(pref)
    raw_u = str(raw or "").strip().upper().replace("_", "-")
    if not pref_u or not raw_u:
        return None
    # 分集尾巴
    raw_u = re.sub(r"(?<=\d)-(?:EP|E)?\d{1,2}$", "", raw_u, flags=re.I)

    def _hit(num_s: str) -> tuple[int, str] | None:
        if not num_s or not num_s.isdigit():
            return None
        return int(num_s), num_s

    tried = []
    for cand in [pref_u, *sorted(prefix_aliases(pref_u), key=len, reverse=True)]:
        if not cand or cand in tried:
            continue
        tried.append(cand)
        # 1) 完整前缀：200GANA-409 / 200GANA-409C
        m = re.fullmatch(rf"{re.escape(cand)}-(\d+)([A-Z]{{1,6}})?$", raw_u)
        if m:
            return _hit(m.group(1))

        # 2) 索引前缀带数字头，帖子只有字母前缀：pref=200GANA, raw=GANA-409C
        hm = re.fullmatch(r"(\d{2,3})([A-Z]{2,20})", cand)
        if hm:
            letter = hm.group(2)
            m = re.fullmatch(rf"{re.escape(letter)}-(\d+)([A-Z]{{1,6}})?$", raw_u)
            if m:
                return _hit(m.group(1))

        # 3) 索引前缀无数字头，源串带数字头：pref=GANA, raw=200GANA-409
        if not re.match(r"^\d", cand):
            m = re.fullmatch(
                rf"(\d{{2,3}}){re.escape(cand)}-(\d+)([A-Z]{{1,6}})?$", raw_u
            )
            if m:
                return _hit(m.group(2))

    return None


def _index_code_key(
    raw_code: str,
    *,
    pad: int,
    prefix: str,
    from_n: int = 1,
    to_n: int = 0,
) -> str | None:
    """片商索引规范键：按前缀格式识别，不漏素人数字头、不误吃异格式。

    - digit_pad：PREFIX-zeroPad；剥 -C/-CH；守 from..to；别名收成 folder/canonical
    - fixed_std：TOKYOHOT-n… / MESUBUTA-… / HEYZO-…；别名收成 canonical
    - date6 / fc2 / western / alnum：走解析 canonical，不做流水区间裁剪
    """
    from .search_av import (
        canonical_prefix,
        normalize_maker_code,
        parse_maker_code,
        prefix_format_meta,
    )

    pref = _std_prefix(prefix)
    if not pref:
        return None
    raw = normalize_maker_code(str(raw_code or "")).upper().replace("_", "-")
    if not raw:
        return None

    meta = prefix_format_meta(pref)
    fmt = str(meta.get("codeFormat") or "digit_pad")
    shape = str(meta.get("shape") or "std")
    hub = canonical_prefix(pref) or pref

    # 异形态：FC2 / 日期 / 字母编号 — 不做流水区间裁剪
    if fmt in {"western_date", "western_scene", "fc2", "fc2ppv", "date6", "alnum_id"}:
        parsed = parse_maker_code(raw)
        if (
            parsed
            and _index_format_matches(fmt, str(parsed.shape or ""))
            and _index_prefix_belongs(
                pref,
                parsed_prefix=str(parsed.prefix or ""),
                canonical=str(parsed.canonical or ""),
                shape=str(parsed.shape or shape),
            )
        ):
            return str(parsed.canonical or "").strip().upper() or None
        # 例：10MU-010123 缺第三段 → 保原文（hub 收成 canonical）
        return _index_raw_under_prefix(raw, pref)

    # fixed_std：专用解析优先，其次普通流水（HEYZO/KIN8）
    if fmt == "fixed_std":
        parsed = parse_maker_code(raw)
        if (
            parsed
            and _index_format_matches(fmt, str(parsed.shape or ""))
            and _index_prefix_belongs(
                pref,
                parsed_prefix=str(parsed.prefix or ""),
                canonical=str(parsed.canonical or ""),
                shape=str(parsed.shape or "fixed_std"),
            )
        ):
            return str(parsed.canonical or "").strip().upper() or None
        got = _extract_serial_for_prefix(raw, pref)
        if got:
            n, num_s = got
            if len(num_s) > len(str(n)):
                w = max(len(num_s), len(str(n)))
            else:
                w = max(len(str(n)), 1)
            return f"{hub}-{n:0{w}d}"
        return None

    # 流水号形态（有码 / 素人 digit_pad）
    width = max(1, min(8, int(pad or 3)))
    got = _extract_serial_for_prefix(raw, pref)
    if not got:
        return None
    n, num_s = got
    lo = max(1, int(from_n or 1))
    hi = max(0, int(to_n or 0))
    if n < lo:
        return None
    if hi > 0 and n > hi:
        return None
    # 已有前导零则保留宽度；短号按 pad 补
    if len(num_s) > len(str(n)):
        w = max(len(num_s), len(str(n)), width)
    else:
        w = max(width, len(str(n)))
    # digit_pad 用文件夹前缀（保留 200GANA 等数字 hub）
    return f"{pref}-{n:0{w}d}"


def _merge_cover_hit(
    into: dict[str, Any], incoming: dict[str, Any] | None
) -> dict[str, Any]:
    """合并同规范键的封面条目：有封面/标题/女优的优先补齐。"""
    if not isinstance(incoming, dict):
        return into
    out = dict(into) if isinstance(into, dict) else {}
    if not out.get("coverUrl") and incoming.get("coverUrl"):
        out["coverUrl"] = incoming.get("coverUrl")
    urls = [u for u in (out.get("coverUrls") or []) if u]
    for u in incoming.get("coverUrls") or []:
        if u and u not in urls:
            urls.append(u)
    if urls:
        out["coverUrls"] = urls[:2]
        if not out.get("coverUrl"):
            out["coverUrl"] = urls[0]
    if not out.get("forumTitle") and incoming.get("forumTitle"):
        out["forumTitle"] = incoming.get("forumTitle")
    acts = out.get("forumActors")
    if not (isinstance(acts, list) and acts):
        inc_acts = incoming.get("forumActors")
        if isinstance(inc_acts, list) and inc_acts:
            out["forumActors"] = list(inc_acts)
    return out


def _rekey_covers_to_pad(
    covers: dict[str, Any],
    *,
    prefix: str,
    pad: int,
    from_n: int = 1,
    to_n: int = 0,
) -> dict[str, Any]:
    """把 covers 键规范到索引标准形；非法/超区间丢弃；同键合并。"""
    out: dict[str, Any] = {}
    for raw, hit in (covers or {}).items():
        key = _index_code_key(
            str(raw),
            pad=pad,
            prefix=prefix,
            from_n=from_n,
            to_n=to_n,
        )
        if not key:
            continue
        if key in out and isinstance(out[key], dict):
            out[key] = _merge_cover_hit(out[key], hit if isinstance(hit, dict) else None)
        elif isinstance(hit, dict):
            out[key] = dict(hit)
        else:
            out[key] = {"coverUrl": None, "coverUrls": [], "file": None}
    return out


def _cover_aliases(code: str) -> list[str]:
    """同一条目的新旧键（兼容 BLACKED-260513 / BLACKED-2023）。"""
    key = _std_code_key(code)
    out: list[str] = []
    for c in (key, str(code or "").strip().upper()):
        if c and c not in out:
            out.append(c)
    try:
        from .search_av import parse_maker_code

        parsed = parse_maker_code(code)
        if not parsed:
            return out
        if parsed.canonical and parsed.canonical not in out:
            out.append(parsed.canonical)
        if parsed.shape == "western_date" and len(parsed.parts) == 2:
            ymd = parsed.parts[1]
            if len(ymd) == 6:
                legacy = f"{parsed.parts[0]}-{ymd}"
                if legacy not in out:
                    out.append(legacy)
        if parsed.shape in {"western_year", "western_ym", "western_ep"} and len(
            parsed.parts
        ) >= 2:
            # 旧索引常用横杠：BLACKED-2023
            legacy = f"{parsed.parts[0]}-{'-'.join(parsed.parts[1:])}"
            if legacy not in out:
                out.append(legacy)
    except Exception:
        pass
    return out


def _lookup_cover(covers: dict[str, Any], code: str) -> dict[str, Any] | None:
    for k in _cover_aliases(code):
        hit = covers.get(k)
        if isinstance(hit, dict):
            return hit
    return None


def ensure_root() -> Path:
    MAKER_FS_ROOT.mkdir(parents=True, exist_ok=True)
    return MAKER_FS_ROOT


def resolve_fs_region(region: str | None) -> str | None:
    """前端 / 白名单 region → maker-fs 目录 id。"""
    key = str(region or "").strip().lower()
    if not key:
        return None
    if key in ("japan", "gravure", "jp"):
        return "japan_gravure"
    if key in ("amateur", "素人"):
        return "japan_amateur"
    if key in ("fc2ppv",):
        return "fc2"
    if key in REGION_META:
        return key
    return None


def indexes_forum_actors(region: str | None) -> bool:
    """是否索引女优（仅日本有码 / 日本写真）。

    索引字段约定：
    - 日本有码 / 日本写真：副文案 = forumActors（女优）；另写 coverUrl
    - 其余区：副文案 = forumTitle（标题）；另写 coverUrl；不写 forumActors
    """
    rid = resolve_fs_region(region)
    return bool(rid and rid in FORUM_ACTORS_INDEX_REGIONS)


def _normalize_forum_actors_field(actors_raw: Any) -> list[str] | None:
    """列表展示用：映射表标准名；无有效名返回 None。"""
    if not isinstance(actors_raw, list) or not actors_raw:
        return None
    actors = [str(a).strip() for a in actors_raw if str(a).strip()]
    if not actors:
        return None
    try:
        from .scrape_metadata_optimize import normalize_actor_names

        actors = normalize_actor_names(actors)
    except Exception:
        pass
    return actors or None


def db_region_for(fs_region: str | None) -> str | None:
    meta = REGION_META.get(str(fs_region or ""))
    if not meta:
        return None
    return meta["db_region"]


def region_dir(fs_region: str) -> Path:
    rid = resolve_fs_region(fs_region) or str(fs_region or "").strip()
    return ensure_root() / "r" / rid


def region_index_path(fs_region: str) -> Path:
    return region_dir(fs_region) / "index.json"


def prefix_dir(prefix: str, fs_region: str | None = None) -> Path:
    p = _std_prefix(prefix)
    rid = resolve_fs_region(fs_region)
    if rid:
        return region_dir(rid) / "p" / p
    return ensure_root() / "p" / p  # 旧布局兼容


def prefix_index_path(prefix: str, fs_region: str | None = None) -> Path:
    return prefix_dir(prefix, fs_region) / "index.json"


def manifest_path() -> Path:
    return ensure_root() / "manifest.json"


def regions_overview_path() -> Path:
    return ensure_root() / "regions.json"


def tree_path() -> Path:
    return ensure_root() / "tree.json"


def overrides_path() -> Path:
    return ensure_root() / "prefix-overrides.json"


_PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,24}$")


def _validate_prefix(raw: str) -> str:
    p = _std_prefix(raw)
    if not p or not _PREFIX_RE.fullmatch(p):
        raise ValueError("主番号格式无效（字母数字与连字符，如 SONE）")
    return p


def load_prefix_overrides() -> dict[str, Any]:
    data = read_json(overrides_path())
    if not data:
        return {"version": 1, "regions": {}}
    regions = data.get("regions")
    if not isinstance(regions, dict):
        data["regions"] = {}
    return data


def save_prefix_overrides(data: dict[str, Any]) -> None:
    global _nav_prefix_order_cache
    payload = {
        "version": 1,
        "updatedAt": _now_iso(),
        "regions": data.get("regions") if isinstance(data.get("regions"), dict) else {},
    }
    write_json(overrides_path(), payload)
    _nav_prefix_order_cache = None


def apply_prefix_overrides(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """导航前缀 ⊕ 人工增删（removed / extra）⊕ boardNames 覆盖。"""
    ov = load_prefix_overrides().get("regions") or {}
    removed: dict[str, set[str]] = {}
    for rid, cfg in ov.items():
        if not isinstance(cfg, dict):
            continue
        removed[str(rid)] = {
            _std_prefix(x)
            for x in (cfg.get("removed") or [])
            if _std_prefix(str(x))
        }

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        rid = str(entry.get("region") or "")
        prefix = _std_prefix(str(entry.get("prefix") or ""))
        if not rid or not prefix:
            continue
        if prefix in removed.get(rid, set()):
            continue
        key = (rid, prefix)
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(entry))

    for rid, cfg in ov.items():
        if rid not in REGION_META or not isinstance(cfg, dict):
            continue
        for ex in cfg.get("extra") or []:
            if isinstance(ex, str):
                prefix = _std_prefix(ex)
                board_name = "自定义"
                name = prefix
            elif isinstance(ex, dict):
                prefix = _std_prefix(str(ex.get("prefix") or ""))
                board_name = str(ex.get("board_name") or "自定义").strip() or "自定义"
                name = str(ex.get("name") or prefix).strip() or prefix
            else:
                continue
            if not prefix or prefix in removed.get(rid, set()):
                continue
            key = (rid, prefix)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "prefix": prefix,
                    "region": rid,
                    "path": ["片区", "自定义", board_name or prefix],
                    "name": name,
                    "type_name": prefix,
                    "board_name": board_name,
                    "custom": True,
                }
            )

    # 刮削后写入的作者名等：覆盖导航/extra 的 board_name
    for entry in out:
        rid = str(entry.get("region") or "")
        prefix = _std_prefix(str(entry.get("prefix") or ""))
        cfg = ov.get(rid) if isinstance(ov.get(rid), dict) else None
        names = (cfg or {}).get("boardNames") if isinstance(cfg, dict) else None
        if not isinstance(names, dict) or not prefix:
            continue
        bn = str(names.get(prefix) or "").strip()
        if bn:
            entry["board_name"] = bn
    return out


def set_prefix_board_name(
    region_id: str,
    prefix: str,
    board_name: str,
) -> dict[str, Any] | None:
    """更新前缀展示名（FC2 作者）；写入 overrides.boardNames 并重写区目录。"""
    rid = resolve_fs_region(region_id)
    if not rid or rid not in REGION_META:
        return None
    p = _std_prefix(prefix)
    if not p:
        return None
    bn = str(board_name or "").strip()
    if rid == "fc2":
        bn = _fc2_catalog_board_name(bn)
    else:
        bn = bn or "自定义"
    data = load_prefix_overrides()
    regions = data.setdefault("regions", {})
    cfg = regions.setdefault(rid, {"extra": [], "removed": []})
    if not isinstance(cfg, dict):
        cfg = {"extra": [], "removed": []}
        regions[rid] = cfg
    names = cfg.setdefault("boardNames", {})
    if not isinstance(names, dict):
        names = {}
        cfg["boardNames"] = names
    names[p] = bn
    # 同步 extra 条目里的 board_name（若有）
    extras: list[Any] = list(cfg.get("extra") or [])
    new_extras: list[Any] = []
    for ex in extras:
        if isinstance(ex, dict) and _std_prefix(str(ex.get("prefix") or "")) == p:
            new_extras.append({**ex, "board_name": bn})
        else:
            new_extras.append(ex)
    cfg["extra"] = new_extras
    regions[rid] = cfg
    save_prefix_overrides(data)
    rewrite_region_catalogs()
    return read_region_index(rid)

def list_effective_prefixes() -> list[dict[str, Any]]:
    nav, _ = _walk_nav_prefixes()
    return apply_prefix_overrides(nav)


def rewrite_region_catalogs() -> dict[str, Any]:
    """按导航+人工覆盖重写七区细表。"""
    ensure_root()
    prefixes = list_effective_prefixes()
    return _write_region_catalogs(prefixes)


def add_region_prefix(
    region_id: str,
    prefix: str,
    *,
    board_name: str = "",
    name: str = "",
) -> dict[str, Any]:
    rid = resolve_fs_region(region_id)
    if not rid or rid not in REGION_META:
        raise ValueError("未知分区")
    p = _validate_prefix(prefix)
    bn = str(board_name or "").strip()
    if rid == "fc2":
        bn = _fc2_catalog_board_name(bn)
    else:
        bn = bn or "自定义"
    nm = str(name or "").strip() or p

    effective = {(e["region"], e["prefix"]) for e in list_effective_prefixes()}
    if (rid, p) in effective:
        raise ValueError(f"主番号 {p} 已存在")

    data = load_prefix_overrides()
    regions = data.setdefault("regions", {})
    cfg = regions.setdefault(rid, {"extra": [], "removed": []})
    if not isinstance(cfg, dict):
        cfg = {"extra": [], "removed": []}
        regions[rid] = cfg
    removed = [
        _std_prefix(x)
        for x in (cfg.get("removed") or [])
        if _std_prefix(str(x))
    ]
    cfg["removed"] = [x for x in removed if x != p]

    # 若本来就在导航里，只需从 removed 拿掉
    nav_set = {
        (e["region"], e["prefix"]) for e in _walk_nav_prefixes()[0]
    }
    if (rid, p) not in nav_set:
        extras: list[Any] = list(cfg.get("extra") or [])
        extras = [
            ex
            for ex in extras
            if _std_prefix(
                str(ex if isinstance(ex, str) else (ex or {}).get("prefix") or "")
            )
            != p
        ]
        extras.append({"prefix": p, "board_name": bn, "name": nm})
        cfg["extra"] = extras
    regions[rid] = cfg
    save_prefix_overrides(data)
    rewrite_region_catalogs()
    cat = read_region_index(rid)
    if not cat:
        raise RuntimeError("写入后读取分区失败")
    return cat


def remove_region_prefix(region_id: str, prefix: str) -> dict[str, Any]:
    rid = resolve_fs_region(region_id)
    if not rid or rid not in REGION_META:
        raise ValueError("未知分区")
    p = _validate_prefix(prefix)

    effective = {(e["region"], e["prefix"]) for e in list_effective_prefixes()}
    if (rid, p) not in effective:
        raise ValueError(f"主番号 {p} 不在本区")

    data = load_prefix_overrides()
    regions = data.setdefault("regions", {})
    cfg = regions.setdefault(rid, {"extra": [], "removed": []})
    if not isinstance(cfg, dict):
        cfg = {"extra": [], "removed": []}
        regions[rid] = cfg

    extras: list[Any] = list(cfg.get("extra") or [])
    new_extras = []
    was_extra = False
    for ex in extras:
        ep = _std_prefix(
            str(ex if isinstance(ex, str) else (ex or {}).get("prefix") or "")
        )
        if ep == p:
            was_extra = True
            continue
        new_extras.append(ex)
    cfg["extra"] = new_extras

    nav_set = {
        (e["region"], e["prefix"]) for e in _walk_nav_prefixes()[0]
    }
    if (rid, p) in nav_set and not was_extra:
        removed = [
            _std_prefix(x)
            for x in (cfg.get("removed") or [])
            if _std_prefix(str(x))
        ]
        if p not in removed:
            removed.append(p)
        cfg["removed"] = removed

    regions[rid] = cfg
    save_prefix_overrides(data)
    rewrite_region_catalogs()
    cat = read_region_index(rid)
    if not cat:
        raise RuntimeError("写入后读取分区失败")
    return cat


def reset_region_prefix_overrides(region_id: str) -> dict[str, Any]:
    rid = resolve_fs_region(region_id)
    if not rid or rid not in REGION_META:
        raise ValueError("未知分区")
    data = load_prefix_overrides()
    regions = data.setdefault("regions", {})
    regions.pop(rid, None)
    save_prefix_overrides(data)
    rewrite_region_catalogs()
    cat = read_region_index(rid)
    if not cat:
        raise RuntimeError("写入后读取分区失败")
    return cat


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def write_json(
    path: Path, data: dict[str, Any], *, compact: bool = False
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")


def read_manifest() -> dict[str, Any]:
    data = read_json(manifest_path())
    if data:
        return data
    return {
        "version": 1,
        "ready": False,
        "updatedAt": "",
        "prefixCount": 0,
        "coverCount": 0,
        "root": str(MAKER_FS_ROOT),
        "regions": [],
    }


def _read_cover_count_fast(path: Path) -> int:
    """只抽 coverCount，避免加载整份 covers。"""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return 0
    m = re.search(r'"coverCount"\s*:\s*(\d+)', text)
    if m:
        return int(m.group(1))
    # 旧文件无 coverCount 时数 covers 键（慢路径，尽量少走）
    m2 = re.search(r'"covers"\s*:\s*\{', text)
    if not m2:
        return 0
    # 粗算："PREFIX-N": 形态的键
    return len(re.findall(r'"[A-Z0-9][A-Z0-9_-]*-\d+"\s*:', text))


def prefix_code_count(prefix: str, fs_region: str | None = None) -> int:
    """已搜索确认的子条目数（如 SONE-001 → 1）。"""
    p = _std_prefix(prefix)
    rid = resolve_fs_region(fs_region)
    if rid:
        n = _read_cover_count_fast(prefix_index_path(p, rid))
        if n:
            return n
    return _read_cover_count_fast(ensure_root() / "p" / p / "index.json")


_nav_prefix_order_cache: dict[str, int] | None = None


def _nav_prefix_order() -> dict[str, int]:
    """导航热门序：prefix → 序号（含 overrides）。"""
    global _nav_prefix_order_cache
    if _nav_prefix_order_cache is not None:
        return _nav_prefix_order_cache
    try:
        nav_prefixes, _tree = _walk_nav_prefixes()
        entries = apply_prefix_overrides(nav_prefixes)
    except Exception:
        entries = []
    order: dict[str, int] = {}
    for i, e in enumerate(entries):
        p = _std_prefix(str(e.get("prefix") or ""))
        if p and p not in order:
            order[p] = i
    _nav_prefix_order_cache = order
    return order


def enrich_region_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """为区目录补齐每个前缀的 codeCount，并汇总厂牌/条目数。

    前缀按导航番号热门序排列（非库内资源条数）。
    """
    rid = str(catalog.get("id") or "")
    prefixes = catalog.get("prefixes") if isinstance(catalog.get("prefixes"), list) else []
    total = 0
    out_prefixes: list[dict[str, Any]] = []
    makers: set[str] = set()
    for it in prefixes:
        if not isinstance(it, dict):
            continue
        row = dict(it)
        pref = str(row.get("prefix") or "").strip()
        code_n = prefix_code_count(pref, rid)
        row["codeCount"] = code_n
        total += code_n
        try:
            from .search_av import prefix_format_meta

            meta = prefix_format_meta(pref)
            row["shape"] = meta.get("shape")
            row["codeFormat"] = meta.get("codeFormat")
            row["codeSample"] = meta.get("codeSample")
            row["pad"] = int(meta.get("pad") or 0)
            row["padLocked"] = bool(meta.get("padLocked"))
            row["padEditable"] = bool(meta.get("padEditable"))
            # 本地 index.pad 若已锁定/写出，与 ranges 对齐展示样例
            local = read_json(prefix_index_path(pref, rid or None))
            if isinstance(local, dict) and int(local.get("pad") or 0) > 0:
                local_pad = max(1, min(8, int(local.get("pad") or 3)))
                row["pad"] = local_pad
                if row.get("codeFormat") == "digit_pad" or meta.get("padEditable"):
                    row["codeSample"] = f"{_std_prefix(pref)}-{1:0{local_pad}d}"
        except Exception:
            row.setdefault("codeFormat", "digit_pad")
            row.setdefault("codeSample", f"{pref}-001")
            row.setdefault("pad", 3)
            row.setdefault("padEditable", True)
            row.setdefault("padLocked", False)
        maker = str(row.get("board_name") or row.get("name") or row.get("prefix") or "").strip()
        if maker:
            makers.add(maker)
        out_prefixes.append(row)
    nav_ord = _nav_prefix_order()
    out_prefixes.sort(
        key=lambda r: (
            nav_ord.get(_std_prefix(str(r.get("prefix") or "")), 10**9),
            str(r.get("prefix") or ""),
        )
    )
    catalog = {**catalog, "prefixes": out_prefixes}
    catalog["prefixCount"] = len(out_prefixes)
    catalog["makerCount"] = len(makers)
    catalog["codeCount"] = total
    return catalog


def read_regions_overview() -> dict[str, Any] | None:
    data = read_json(regions_overview_path())
    if not data:
        return None
    regions = data.get("regions") if isinstance(data.get("regions"), list) else []
    enriched: list[dict[str, Any]] = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("id") or "")
        cat = read_region_index(rid)
        code_n = int((cat or {}).get("codeCount") or 0) if cat else 0
        prefix_n = int((cat or {}).get("prefixCount") or r.get("prefixCount") or 0)
        maker_n = int((cat or {}).get("makerCount") or r.get("makerCount") or 0)
        enriched.append(
            {
                **r,
                "prefixCount": prefix_n,
                "makerCount": maker_n,
                "codeCount": code_n,
            }
        )
    # 七区固定顺序（日本有码→写真→无码→素人→FC2→国产→欧美）
    order = {rid: i for i, rid in enumerate(REGION_ORDER)}
    enriched.sort(
        key=lambda r: order.get(str(r.get("id") or ""), 99),
    )
    return {**data, "regions": enriched, "regionCount": len(enriched)}


def read_region_index(fs_region: str) -> dict[str, Any] | None:
    rid = resolve_fs_region(fs_region) or fs_region
    raw = read_json(region_index_path(rid))
    if not raw:
        return None
    return enrich_region_catalog(raw)


def read_tree() -> dict[str, Any] | None:
    return read_json(tree_path())


def _find_prefix_index(
    prefix: str, region: str | None = None
) -> tuple[dict[str, Any] | None, str]:
    """返回 (index, fs_region)。优先指定区，再扫七区，最后旧 p/ 布局。"""
    p = _std_prefix(prefix)
    rid = resolve_fs_region(region)
    if rid:
        idx = read_json(prefix_index_path(p, rid))
        if idx:
            return idx, rid
    for cand in REGION_ORDER:
        idx = read_json(prefix_index_path(p, cand))
        if idx:
            return idx, cand
    legacy = read_json(ensure_root() / "p" / p / "index.json")
    if legacy:
        return legacy, resolve_fs_region(str(legacy.get("region") or "")) or ""
    return None, ""


def read_prefix_index(prefix: str, region: str | None = None) -> dict[str, Any] | None:
    idx, _ = _find_prefix_index(prefix, region)
    return idx


def forum_seed_for_code_local(
    code: str,
    *,
    prefix: str | None = None,
    region: str | None = None,
) -> dict[str, Any] | None:
    """从 maker-fs 前缀索引读【影片名称】/女优；命中返回 dict，否则 None。"""
    key = _std_code_key(code)
    if not key:
        return None
    pfx = _std_prefix(prefix) if prefix else ""
    if not pfx:
        try:
            from .search_av import parse_maker_code

            parsed = parse_maker_code(key)
            if parsed and parsed.prefix:
                pfx = _std_prefix(parsed.prefix)
        except Exception:
            pfx = ""
    if not pfx:
        m = re.fullmatch(r"([A-Z0-9]+)[-.](\d+)", key)
        pfx = m.group(1) if m else ""
    if not pfx:
        return None
    idx, _ = _find_prefix_index(pfx, region)
    if not idx:
        return None
    covers = idx.get("covers") if isinstance(idx.get("covers"), dict) else {}
    hit = _lookup_cover(covers, code)
    if not isinstance(hit, dict):
        return None
    title = str(hit.get("forumTitle") or "").strip()
    actors = _normalize_forum_actors_field(hit.get("forumActors")) or []
    if not title and not actors:
        return None
    return {"title": title, "actors": actors, "postsScanned": 0, "source": "maker-fs"}


def build_status() -> dict[str, Any]:
    return {**_build_state, "manifest": read_manifest()}


def claim_build(*, region: str | None = None) -> bool:
    """后台任务入队前标记 running（不跨线程持锁），避免轮询读到旧 finished。"""
    with _meta_lock:
        if _build_state.get("running"):
            return False
        _reset_build_progress(region=region or "", message="queued", running=True)
        _build_state["startedAt"] = _now_iso()
        return True


def abort_claim(message: str = "failed") -> None:
    """后台 worker 启动失败或扫库前置失败时结束 running。"""
    with _meta_lock:
        if not (
            _build_state.get("running")
            or _build_state.get("message") in {"queued", "building"}
        ):
            return
        _build_state.update(
            {
                "running": False,
                "finishedAt": _now_iso(),
                "message": message,
                "updatedAt": _now_iso(),
            }
        )


def _region_from_path(path: list[str], hub_fid: str = "") -> str:
    hub = str(hub_fid or "")
    if hub.startswith("mk-censored"):
        return "japan_censored"
    if hub.startswith("mk-gravure"):
        return "japan_gravure"
    if hub.startswith("mk-uncensored"):
        return "japan_uncensored"
    if hub.startswith("mk-amateur"):
        return "japan_amateur"
    if hub.startswith("mk-fc2"):
        return "fc2"
    if hub.startswith("mk-china"):
        return "china"
    if hub.startswith("mk-western"):
        return "western"
    joined = "/".join(path)
    if "FC2" in joined and "日本" in joined:
        return "fc2"
    if "素人" in joined and "日本" in joined:
        return "japan_amateur"
    if "有码" in joined and "日本" in joined:
        return "japan_censored"
    if "无码" in joined and "日本" in joined:
        return "japan_uncensored"
    if "写真" in joined:
        return "japan_gravure"
    if "国产" in joined:
        return "china"
    if "欧美" in joined:
        return "western"
    if "日本" in joined:
        return "japan_censored"
    return ""


def _walk_nav_prefixes() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """从 boards.nav 片区收集 search_keyword 前缀。"""
    try:
        nav = json.loads(NAV_PATH.read_text(encoding="utf-8-sig"))
    except Exception as e:
        raise RuntimeError(f"读取 boards.nav.json 失败: {e}") from e

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def walk_parent(
        parent: dict[str, Any],
        path: list[str],
        hub_fid: str = "",
    ) -> dict[str, Any]:
        name = str(parent.get("name") or "").strip()
        here = path + ([name] if name else [])
        hub = str(parent.get("hub_fid") or hub_fid or "")
        node: dict[str, Any] = {
            "name": name,
            "hub_fid": hub,
            "children": [],
            "boards": [],
            "prefixes": [],
        }
        for ch in parent.get("children") or []:
            if not isinstance(ch, dict):
                continue
            kw = str(ch.get("search_keyword") or "").strip().upper()
            if not kw:
                continue
            prefix = _std_prefix(kw)
            region = _region_from_path(here, hub)
            if region not in REGION_META:
                continue
            entry = {
                "prefix": prefix,
                "region": region,
                "path": here
                + (
                    [str(ch.get("board_name") or "").strip()]
                    if ch.get("board_name")
                    else []
                ),
                "name": str(ch.get("name") or prefix),
                "type_name": str(ch.get("type_name") or prefix),
                "board_name": str(ch.get("board_name") or ""),
            }
            node["prefixes"].append(entry)
            key = (region, prefix)
            if key not in seen:
                seen.add(key)
                out.append(entry)
        for sub in parent.get("boards") or []:
            if isinstance(sub, dict):
                node["boards"].append(walk_parent(sub, here, hub))
        return node

    tree_roots: list[dict[str, Any]] = []
    for cat in nav if isinstance(nav, list) else []:
        if not isinstance(cat, dict):
            continue
        if str(cat.get("category") or "") != "片区":
            continue
        for b in cat.get("boards") or []:
            if isinstance(b, dict):
                tree_roots.append(walk_parent(b, ["片区"]))

    return out, {
        "version": 1,
        "category": "片区",
        "updatedAt": _now_iso(),
        "boards": tree_roots,
        "prefixCount": len(out),
    }


def covers_for_codes_local(
    prefix: str,
    codes: list[str],
    *,
    region: str | None = None,
) -> dict[str, Any] | None:
    """从本地 index 取封面；无 index 返回 None（调用方回退库）。"""
    idx, fs_region = _find_prefix_index(prefix, region)
    if not idx:
        return None
    cover_map = idx.get("covers") if isinstance(idx.get("covers"), dict) else {}
    items: list[dict[str, Any]] = []
    for code in codes:
        key = _std_code_key(code)
        hit = _lookup_cover(cover_map, code)
        if isinstance(hit, dict):
            file_rel = hit.get("file")
            local_url = None
            if file_rel and fs_region:
                local_url = (
                    f"/maker-fs/file/r/{fs_region}/p/"
                    f"{_std_prefix(prefix)}/{file_rel}"
                )
            elif file_rel:
                local_url = f"/maker-fs/file/p/{_std_prefix(prefix)}/{file_rel}"
            urls = [u for u in (hit.get("coverUrls") or []) if u]
            cover_url = local_url or hit.get("coverUrl") or (urls[0] if urls else None)
            if local_url:
                urls = [local_url, *[u for u in urls if u != local_url]]
            items.append(
                {
                    "code": code,
                    "coverUrl": cover_url,
                    "coverUrls": urls[:6],
                    "forumTitle": hit.get("forumTitle"),
                    "forumActors": _normalize_forum_actors_field(hit.get("forumActors")),
                }
            )
        else:
            items.append({"code": code, "coverUrl": None, "coverUrls": []})
    return {
        "prefix": _std_prefix(prefix),
        "items": items,
        "source": "maker-fs",
        "updatedAt": idx.get("updatedAt") or "",
        "region": fs_region or idx.get("region") or "",
    }


def list_prefix_codes(
    prefix: str,
    region: str | None = None,
    *,
    offset: int = 0,
    limit: int = 100,
    q: str | None = None,
) -> dict[str, Any] | None:
    """列出已确认子条目（封面索引中的番号）。

    展示键一律按 index.pad 规范成 PREFIX-zeroPad；-C 等尾缀不单独成条。
    from/to 优先采用 prefix-code-ranges 的稳健上限（可裁掉索引里的离群高号）。
    """
    from .search_av import code_sort_key
    from . import prefix_ranges

    idx, fs_region = _find_prefix_index(prefix, region)
    if not idx:
        return None
    pref = _std_prefix(prefix)
    pad = max(1, min(8, int(idx.get("pad") or 3)))
    from_n = max(1, int(idx.get("from") or 1))
    to_n = max(0, int(idx.get("to") or 0))
    # 实时区间更紧时（离群修正后）用 ranges，避免旧 index.to=750 继续放出 726
    try:
        rng = prefix_ranges.get_range(pref)
        if rng:
            rf = max(1, int(rng.get("from") or 1))
            rt = max(0, int(rng.get("to") or 0))
            if rt > 0 and (to_n <= 0 or rt < to_n):
                to_n = rt
            if rf > from_n:
                from_n = rf
            rp = int(rng.get("pad") or 0)
            if rp > 0:
                pad = max(1, min(8, rp))
    except Exception:
        pass
    cover_map_raw = idx.get("covers") if isinstance(idx.get("covers"), dict) else {}
    # 读时规范化：旧索引里的 IPZZ-599C / 短号 / 超区间号一并收敛
    cover_map = _rekey_covers_to_pad(
        cover_map_raw, prefix=pref, pad=pad, from_n=from_n, to_n=to_n
    )
    if set(cover_map_raw.keys()) != set(cover_map.keys()) or len(cover_map_raw) != len(
        cover_map
    ):
        # 懒写回：去掉不正规/超区间键，下次扫描前展示也干净
        try:
            idx["covers"] = cover_map
            idx["coverCount"] = len(cover_map)
            idx["from"] = from_n
            idx["to"] = to_n
            idx["pad"] = pad
            idx["updatedAt"] = _now_iso()
            path = prefix_index_path(pref, fs_region or None)
            write_json(path, idx, compact=True)
        except Exception:
            log.debug("lazy rekey covers %s failed", pref, exc_info=True)
    want_actors = indexes_forum_actors(fs_region)
    needle = str(q or "").strip().upper()
    items: list[dict[str, Any]] = []
    for code, hit in cover_map.items():
        key = str(code or "").strip().upper()
        if not key:
            continue
        cover_url = None
        forum_title = None
        forum_actors = None
        if isinstance(hit, dict):
            urls = [u for u in (hit.get("coverUrls") or []) if u]
            cover_url = hit.get("coverUrl") or (urls[0] if urls else None)
            forum_title = hit.get("forumTitle")
            if want_actors:
                forum_actors = _normalize_forum_actors_field(hit.get("forumActors"))
        if needle:
            blob = key
            if forum_title:
                blob = f"{blob} {forum_title}"
            if forum_actors:
                blob = f"{blob} {' '.join(forum_actors)}"
            # 搜索同时匹配磁盘上的原始女优名（映射前）
            if want_actors and isinstance(hit, dict):
                raw_acts = hit.get("forumActors")
                if isinstance(raw_acts, list) and raw_acts:
                    blob = f"{blob} {' '.join(str(a) for a in raw_acts if str(a).strip())}"
            if needle not in blob.upper():
                continue
        # 全员 coverUrl；有码/写真带女优；其余只带标题
        row: dict[str, Any] = {
            "code": key,
            "coverUrl": cover_url,
            "forumTitle": forum_title,
        }
        if want_actors:
            row["forumActors"] = forum_actors
        items.append(row)
    # 热门→冷门：番号数字大的（更新）在前
    items.sort(key=lambda it: code_sort_key(str(it["code"])), reverse=True)
    total = len(items)
    off = max(0, int(offset or 0))
    lim = max(1, min(500, int(limit or 100)))
    page = items[off : off + lim]
    return {
        "prefix": pref,
        "region": fs_region or idx.get("region") or "",
        "total": total,
        "offset": off,
        "limit": lim,
        "items": page,
        "pad": pad,
        "codeSample": f"{pref}-{1:0{pad}d}",
        "from": from_n,
        "to": to_n,
        "updatedAt": idx.get("updatedAt") or "",
        "source": "maker-fs",
        "q": needle or "",
    }


def sync_prefix_pad(prefix: str, pad: int) -> None:
    """把规范位数写回各区此前缀的 index.json，并按 pad 重键 covers。"""
    p = _std_prefix(prefix)
    width = max(1, min(8, int(pad or 3)))
    if not p:
        return
    for rid in REGION_ORDER:
        path = prefix_index_path(p, rid)
        idx = read_json(path)
        if not idx or not isinstance(idx, dict):
            continue
        old_pad = int(idx.get("pad") or 0)
        from_n = max(1, int(idx.get("from") or 1))
        to_n = max(0, int(idx.get("to") or 0))
        covers = idx.get("covers") if isinstance(idx.get("covers"), dict) else {}
        new_covers = _rekey_covers_to_pad(
            covers, prefix=p, pad=width, from_n=from_n, to_n=to_n
        )
        changed = old_pad != width or len(new_covers) != len(covers) or any(
            k not in new_covers for k in covers
        )
        # 键集合变化（如剥掉 -C）也要写回
        if not changed:
            changed = set(covers.keys()) != set(new_covers.keys())
        if not changed:
            continue
        idx["pad"] = width
        idx["covers"] = new_covers
        idx["coverCount"] = len(new_covers)
        idx["updatedAt"] = _now_iso()
        write_json(path, idx, compact=True)


def range_for_prefix_local(
    prefix: str, region: str | None = None
) -> dict[str, Any] | None:
    idx, fs_region = _find_prefix_index(prefix, region)
    if not idx:
        return None
    to = int(idx.get("to") or 0)
    if to <= 0:
        return None
    frm = max(1, int(idx.get("from") or 1))
    pad = max(1, min(8, int(idx.get("pad") or 3)))
    return {
        "prefix": _std_prefix(prefix),
        "from": frm,
        "to": to,
        "pad": pad,
        "total": max(0, to - frm + 1),
        "source": "maker-fs",
        "skip": False,
        "updatedAt": idx.get("updatedAt") or "",
        "region": fs_region or idx.get("region") or "",
    }


def _parse_iso_utc(raw: str) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _try_reuse_fresh_index(
    prefix: str,
    fs_region: str,
    *,
    skip_fresh_hours: float,
) -> dict[str, Any] | None:
    """未过期的本地索引直接复用，跳过扫库。"""
    if skip_fresh_hours <= 0:
        return None
    path = prefix_index_path(prefix, fs_region or None)
    idx = read_json(path)
    if not idx:
        # 兼容旧扁平布局
        idx = read_json(ensure_root() / "p" / prefix / "index.json")
    if not idx:
        return None
    covers = idx.get("covers") if isinstance(idx.get("covers"), dict) else {}
    count = int(idx.get("coverCount") or len(covers) or 0)
    if count <= 0:
        return None
    updated = _parse_iso_utc(str(idx.get("updatedAt") or ""))
    if not updated:
        return None
    age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600.0
    if age_h > skip_fresh_hours:
        return None
    idx = {**idx, "skipped": True, "coverCount": count}
    return idx


def _export_prefix_index(
    entry: dict[str, Any],
    *,
    max_covers: int = 5000,
    skip_fresh_hours: float = 0,
) -> dict[str, Any]:
    from . import prefix_ranges, prefix_service

    prefix = _std_prefix(str(entry.get("prefix") or ""))
    fs_region = resolve_fs_region(str(entry.get("region") or "")) or ""
    db_region = db_region_for(fs_region)
    path = list(entry.get("path") or [])

    reused = _try_reuse_fresh_index(
        prefix, fs_region, skip_fresh_hours=skip_fresh_hours
    )
    if reused:
        # 非有码/写真：清掉历史 forumActors，避免旧索引残留
        pad_reuse = max(1, min(8, int(reused.get("pad") or 3)))
        from_reuse = max(1, int(reused.get("from") or 1))
        to_reuse = max(0, int(reused.get("to") or 0))
        # 与实时 ranges / 稳健上限对齐，避免复用旧 to=750 把离群号写回
        try:
            rng_live = prefix_ranges.get_range(prefix) or {}
            rt = max(0, int(rng_live.get("to") or 0))
            rf = max(1, int(rng_live.get("from") or 1))
            rp = int(rng_live.get("pad") or 0)
            if rt > 0 and (to_reuse <= 0 or rt < to_reuse):
                to_reuse = rt
            if rf > from_reuse:
                from_reuse = rf
            if rp > 0:
                pad_reuse = max(1, min(8, rp))
        except Exception:
            pass
        covers0 = reused.get("covers") if isinstance(reused.get("covers"), dict) else {}
        # 索引内流水再跑一轮稳健上限（covers 已有离群时）
        try:
            nums = []
            for ck in covers0:
                m = re.fullmatch(rf"{re.escape(prefix)}-(\d+)$", str(ck).upper())
                if m:
                    nums.append(int(m.group(1)))
            if len(nums) >= 10:
                rob = prefix_ranges.robust_serial_max(nums)
                est = prefix_ranges.estimate_to(rob) if rob else 0
                if est > 0 and (to_reuse <= 0 or est < to_reuse):
                    to_reuse = est
        except Exception:
            pass
        covers_norm = _rekey_covers_to_pad(
            covers0,
            prefix=prefix,
            pad=pad_reuse,
            from_n=from_reuse,
            to_n=to_reuse,
        )
        dirty = False
        if (
            set(covers0.keys()) != set(covers_norm.keys())
            or len(covers0) != len(covers_norm)
            or int(reused.get("to") or 0) != to_reuse
            or int(reused.get("from") or 0) != from_reuse
            or int(reused.get("pad") or 0) != pad_reuse
        ):
            reused["covers"] = covers_norm
            reused["coverCount"] = len(covers_norm)
            reused["from"] = from_reuse
            reused["to"] = to_reuse
            reused["pad"] = pad_reuse
            dirty = True
        if not indexes_forum_actors(fs_region):
            covers = reused.get("covers")
            if isinstance(covers, dict):
                for hit in covers.values():
                    if isinstance(hit, dict) and "forumActors" in hit:
                        hit.pop("forumActors", None)
                        dirty = True
        if dirty:
            write_json(
                prefix_index_path(prefix, fs_region or None),
                reused,
                compact=True,
            )
        return reused

    rng = prefix_ranges.get_range(prefix) or {}
    from_n = max(1, int(rng.get("from") or 1))
    to_n = max(0, int(rng.get("to") or 0))
    pad = max(1, min(8, int(rng.get("pad") or 3)))

    covers: dict[str, Any] = {}
    matched_rows = 0
    t0 = time.perf_counter()
    try:
        indexed = prefix_service._load_cached(  # noqa: SLF001 — 构建任务复用缓存
            prefix,
            bust=skip_fresh_hours <= 0,
            region=db_region,
        )
        matched_rows = int(indexed.get("matchedRows") or 0)
        for it in indexed.get("items") or []:
            if len(covers) >= max_covers:
                break
            raw_code = str(it.get("code") or "")
            # 规范键：PREFIX-zeroPad(n, pad)；剥 -C；超 from..to 丢弃
            code = _index_code_key(
                raw_code,
                pad=pad,
                prefix=prefix,
                from_n=from_n,
                to_n=to_n,
            )
            if not code:
                continue
            urls = [u for u in (it.get("coverUrls") or []) if u][:6]
            cover_url = urls[0] if urls else it.get("coverUrl")
            # 全员写入封面字段（可空）；有码/写真写女优，其余写标题
            hit: dict[str, Any] = {
                "coverUrl": cover_url or None,
                "coverUrls": urls[:2],
                "file": None,
            }
            title = str(it.get("forumTitle") or "").strip()
            if title:
                # 旧缓存可能残留 `) (20230104)…`；写入前再洗一轮
                from .scrape_forum_title import clean_forum_zh_title

                title = clean_forum_zh_title(title, code) or title
            actors = it.get("forumActors")
            want_actors = indexes_forum_actors(fs_region)
            if want_actors:
                if isinstance(actors, list) and actors:
                    cleaned = _normalize_forum_actors_field(actors)
                    if cleaned:
                        hit["forumActors"] = cleaned
                # 影片标题仍保留供刮削种子；女优名不当标题
                if title:
                    from .forum_seed import (
                        _looks_like_bare_actor_title,
                        _title_is_actor_echo,
                    )
                    from .scrape_forum_title import is_indexable_forum_title

                    actor_list = hit.get("forumActors") or []
                    if _title_is_actor_echo(title, actor_list) or _looks_like_bare_actor_title(
                        title
                    ):
                        pass
                    elif is_indexable_forum_title(title, code, assume_not_fake=True):
                        hit["forumTitle"] = title
            else:
                if title:
                    from .scrape_forum_title import is_indexable_forum_title

                    if is_indexable_forum_title(title, code, assume_not_fake=True):
                        hit["forumTitle"] = title
            if code in covers and isinstance(covers[code], dict):
                covers[code] = _merge_cover_hit(covers[code], hit)
            else:
                covers[code] = hit
    except Exception as e:
        log.warning("maker-fs export covers %s failed: %s", prefix, e)

    wall_ms = (time.perf_counter() - t0) * 1000
    log.debug(
        "maker-fs export %s region=%s coverCount=%s matchedRows=%s wall_ms=%.0f",
        prefix,
        fs_region,
        len(covers),
        matched_rows,
        wall_ms,
    )

    if to_n <= 0 and covers:
        nums: list[int] = []
        for code in covers:
            m = re.fullmatch(rf"{re.escape(prefix)}-(\d+)", code)
            if m:
                nums.append(int(m.group(1)))
        if nums:
            to_n = max(nums)
            from_n = 1
            from .prefix_ranges import choose_pad

            pad = choose_pad(prefix, to_n)

    # digit_pad：用 covers 内流水再裁一轮离群，避免 MIMK-726 类写进索引
    if covers and to_n > 0:
        try:
            from .prefix_ranges import SKIP_PREFIXES, estimate_to, robust_serial_max
            from .search_av import prefix_format_meta

            meta = prefix_format_meta(prefix)
            fmt = str(meta.get("codeFormat") or "digit_pad")
            if (
                fmt in {"digit_pad", "fixed_std", ""}
                and prefix not in SKIP_PREFIXES
            ):
                nums2: list[int] = []
                for code in covers:
                    m = re.fullmatch(rf"{re.escape(prefix)}-(\d+)$", str(code).upper())
                    if m:
                        nums2.append(int(m.group(1)))
                if len(nums2) >= 10:
                    rob = robust_serial_max(nums2)
                    est = estimate_to(rob) if rob else 0
                    if est > 0 and est < to_n:
                        to_n = est
                        covers = _rekey_covers_to_pad(
                            covers,
                            prefix=prefix,
                            pad=pad,
                            from_n=from_n,
                            to_n=to_n,
                        )
        except Exception:
            log.debug("robust trim covers %s failed", prefix, exc_info=True)

    data = {
        "version": 1,
        "prefix": prefix,
        "region": fs_region,
        "dbRegion": db_region or "",
        "path": path,
        "from": from_n,
        "to": to_n,
        "pad": pad,
        "updatedAt": _now_iso(),
        "source": "db",
        "coverCount": len(covers),
        "covers": covers,
    }
    # 前缀索引体积大：紧凑 JSON 显著加快写盘
    write_json(prefix_index_path(prefix, fs_region or None), data, compact=True)
    return data


def _is_fc2_plate_maker_name(name: str) -> bool:
    """论坛板名/前缀壳，不是真实 FC2 作者名。"""
    s = re.sub(r"[\s·\-_/=]+", "", str(name or "").strip().lower())
    if not s:
        return True
    return s in {"fc2", "fc2ppv", "fc2ppvfc2"} or s.startswith("fc2fc2") or bool(
        re.fullmatch(r"fc2(ppv)?", s)
    )


def _fc2_catalog_board_name(raw: str) -> str:
    """FC2 个人产出：索引无作者时落「未分类」，刮削后再改作者名。"""
    bn = str(raw or "").strip()
    if bn and bn not in {"自定义", "未分组", "未知"} and not _is_fc2_plate_maker_name(
        bn
    ):
        return bn
    return "未分类"


def _write_region_catalogs(prefixes: list[dict[str, Any]]) -> dict[str, Any]:
    """写出七区 index.json + regions.json（番号细表）。"""
    by_region: dict[str, list[dict[str, Any]]] = {rid: [] for rid in REGION_ORDER}
    for entry in prefixes:
        rid = resolve_fs_region(str(entry.get("region") or ""))
        if not rid:
            continue
        board_name = str(entry.get("board_name") or "")
        if rid == "fc2":
            board_name = _fc2_catalog_board_name(board_name)
        by_region[rid].append(
            {
                "prefix": entry["prefix"],
                "name": entry.get("name") or entry["prefix"],
                "type_name": entry.get("type_name") or entry["prefix"],
                "board_name": board_name,
                "path": entry.get("path") or [],
                "custom": bool(entry.get("custom")),
            }
        )

    region_summaries: list[dict[str, Any]] = []
    for rid in REGION_ORDER:
        meta = REGION_META[rid]
        # 保持导航热门顺序（S1、MOODYZ…），勿按资源条数打乱
        items = by_region[rid]
        dedup: list[dict[str, Any]] = []
        seen_p: set[str] = set()
        for it in items:
            p = str(it["prefix"])
            if p in seen_p:
                continue
            seen_p.add(p)
            dedup.append(it)
        makers = {
            str(it.get("board_name") or it.get("name") or it["prefix"]).strip()
            or str(it["prefix"])
            for it in dedup
        }
        catalog = enrich_region_catalog(
            {
                "version": 1,
                "id": rid,
                "label": meta["label"],
                "dbRegion": meta["db_region"],
                "navPath": meta["navPath"],
                "updatedAt": _now_iso(),
                "prefixCount": len(dedup),
                "makerCount": len(makers),
                "codeCount": 0,
                "prefixes": dedup,
            }
        )
        # enrich 后重算厂牌数（custom 等）
        makers_after = {
            str(it.get("board_name") or it.get("name") or it["prefix"]).strip()
            or str(it["prefix"])
            for it in (catalog.get("prefixes") or [])
            if isinstance(it, dict)
        }
        catalog["makerCount"] = len(makers_after)
        write_json(region_index_path(rid), catalog)
        region_summaries.append(
            {
                "id": rid,
                "label": meta["label"],
                "dbRegion": meta["db_region"],
                "navPath": meta["navPath"],
                "prefixCount": int(catalog.get("prefixCount") or len(dedup)),
                "makerCount": int(catalog.get("makerCount") or len(makers_after)),
                "codeCount": int(catalog.get("codeCount") or 0),
                "dir": f"r/{rid}",
            }
        )

    overview = {
        "version": 1,
        "updatedAt": _now_iso(),
        "regionCount": len(region_summaries),
        "regions": region_summaries,
    }
    write_json(regions_overview_path(), overview)
    return overview


def build_maker_fs(
    *,
    limit_prefixes: int | None = None,
    max_covers_per_prefix: int = 5000,
    catalogs_only: bool = False,
    workers: int = DEFAULT_EXPORT_WORKERS,
    skip_fresh_hours: float = DEFAULT_SKIP_FRESH_HOURS,
    region: str | None = None,
    from_claim: bool = False,
) -> dict[str, Any]:
    """生成七区细表 +（可选）从库导出各前缀封面索引。

    - workers: 并行扫库线程数（默认 8，与连接池上限对齐）
    - skip_fresh_hours: 跳过 N 小时内已导出的前缀（0=强制全量）
    - region: 仅扫描指定分区（如 japan_censored）；空=全部
    - from_claim: 后台任务已 claim_build，跳过 running 互斥检查
    """
    region_id = resolve_fs_region(region) if region else None
    if region and not region_id:
        raise ValueError(f"未知分区: {region}")
    if not from_claim:
        with _meta_lock:
            if _build_state.get("running"):
                raise RuntimeError("构建任务正在进行中")
    if not _build_lock.acquire(blocking=False):
        if from_claim:
            abort_claim("构建任务正在进行中")
        raise RuntimeError("构建任务正在进行中")
    with _meta_lock:
        started = _build_state.get("startedAt") or _now_iso()
        _build_state.update(
            {
                "running": True,
                "startedAt": started,
                "finishedAt": "",
                "message": "building",
                "prefixes": 0,
                "prefixTotal": 0,
                "covers": 0,
                "skipped": 0,
                "workers": 0,
                "region": region_id or "",
                "currentPrefix": "",
                "updatedAt": _now_iso(),
                "regionProgress": {},
            }
        )
    try:
        ensure_root()
        nav_prefixes, tree = _walk_nav_prefixes()
        prefixes = apply_prefix_overrides(nav_prefixes)
        write_json(tree_path(), tree)
        overview = _write_region_catalogs(prefixes)

        if catalogs_only:
            manifest = {
                "version": 2,
                "ready": True,
                "updatedAt": _now_iso(),
                "prefixCount": len(prefixes),
                "coverCount": 0,
                "root": str(MAKER_FS_ROOT),
                "source": "nav",
                "scope": "region_catalogs",
                "regions": overview.get("regions") or [],
            }
            write_json(manifest_path(), manifest)
            _build_state.update(
                {
                    "running": False,
                    "finishedAt": _now_iso(),
                    "message": "ok",
                    "prefixes": len(prefixes),
                    "covers": 0,
                    "skipped": 0,
                }
            )
            return {
                "manifest": manifest,
                "treePrefixCount": tree.get("prefixCount"),
                "regions": overview,
            }

        # 扫库依赖资源库；不可用时以前会静默写 0 条目
        from .pg import ResourceDbUnavailable, get_pool

        try:
            with get_pool().connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
        except ResourceDbUnavailable as e:
            raise ValueError(
                f"{e}。NAS 容器内主机填 postgres、端口 5432，"
                "并加入 sehuatang-network；勿用 127.0.0.1"
            ) from e
        except Exception as e:
            raise ValueError(
                f"资源库连不上: {e}。请检查设置→资源库 DSN 与 Docker 网络"
            ) from e

        # 索引按「设置→论坛管理」地区标签过滤板块；未配置时全部视为 other → 条目恒为 0
        from .forum_region_tags import (
            forum_allow_specs_for_search,
            invalidate_forum_region_cache,
            known_forum_leaf_keys,
        )

        invalidate_forum_region_cache()
        if not known_forum_leaf_keys():
            raise ValueError(
                "论坛地区未配置：请到 设置→论坛管理，给色花堂板块标注"
                "「日本 / 国产 / 欧美 / 混合」后再扫描（未标注的板块不参与索引）"
            )
        check_regions = (
            [region_id]
            if region_id
            else list(REGION_ORDER)
        )
        missing_tags: list[str] = []
        for rid in check_regions:
            db_r = db_region_for(rid) or rid
            if not forum_allow_specs_for_search(db_r):
                lab = (REGION_META.get(rid) or {}).get("label") or rid
                missing_tags.append(str(lab))
        if missing_tags and region_id:
            raise ValueError(
                f"本区无可用论坛标签（{'、'.join(missing_tags)}）："
                "请在 设置→论坛管理 标注对应「日本/国产/欧美/混合」板块"
            )

        work = prefixes
        if region_id:
            work = [e for e in work if e.get("region") == region_id]
        if limit_prefixes is not None and limit_prefixes > 0:
            work = work[:limit_prefixes]

        worker_n = max(1, min(int(workers or 1), 8))
        _build_state["workers"] = worker_n
        total_covers = 0
        built = 0
        skipped = 0
        progress_lock = threading.Lock()

        # 分区进度：全量时七区各有 total；单区扫描只有该区
        region_totals: dict[str, int] = {rid: 0 for rid in REGION_ORDER}
        for entry in work:
            rid = resolve_fs_region(str(entry.get("region") or "")) or ""
            if rid in region_totals:
                region_totals[rid] += 1
            elif rid:
                region_totals[rid] = region_totals.get(rid, 0) + 1
        with _meta_lock:
            _build_state["prefixTotal"] = len(work)
            _build_state["regionProgress"] = {
                rid: _empty_region_progress(n)
                for rid, n in region_totals.items()
                if n > 0 or not region_id
            }
            # 全量：未出现在 work 的区也挂 0/0，便于 UI 对齐
            if not region_id:
                for rid in REGION_ORDER:
                    _build_state["regionProgress"].setdefault(
                        rid, _empty_region_progress(0)
                    )
            _build_state["updatedAt"] = _now_iso()

        def _touch_progress(
            *,
            rid: str,
            prefix: str,
            phase: str,
            cover_n: int = 0,
            was_skipped: bool = False,
        ) -> None:
            nonlocal total_covers, built, skipped
            now = _now_iso()
            with progress_lock:
                with _meta_lock:
                    rp_map = _build_state.setdefault("regionProgress", {})
                    rp = rp_map.get(rid)
                    if not isinstance(rp, dict):
                        rp = _empty_region_progress(0)
                        rp_map[rid] = rp
                    if phase == "start":
                        _build_state["currentPrefix"] = prefix
                        active = list(rp.get("active") or [])
                        if prefix not in active:
                            active.append(prefix)
                        rp["active"] = active
                        # 展示最早开工的前缀，避免并行时名称来回跳显得「倒退」
                        rp["currentPrefix"] = str(active[0]) if active else prefix
                    elif phase == "done":
                        built += 1
                        total_covers += cover_n
                        if was_skipped:
                            skipped += 1
                        # 单调递增，防止异常路径重复写坏 UI
                        rp["done"] = min(
                            int(rp.get("total") or 0) or 10**9,
                            int(rp.get("done") or 0) + 1,
                        )
                        rp["covers"] = int(rp.get("covers") or 0) + cover_n
                        active = [
                            p
                            for p in list(rp.get("active") or [])
                            if str(p) != prefix
                        ]
                        rp["active"] = active
                        rp["lastCompleted"] = prefix
                        rp["currentPrefix"] = (
                            str(active[0]) if active else prefix
                        )
                        if str(_build_state.get("currentPrefix") or "") == prefix:
                            _build_state["currentPrefix"] = rp["currentPrefix"]
                        _build_state["prefixes"] = built
                        _build_state["covers"] = total_covers
                        _build_state["skipped"] = skipped
                    rp["updatedAt"] = now
                    _build_state["updatedAt"] = now

        def _one(entry: dict[str, Any]) -> dict[str, Any]:
            rid = resolve_fs_region(str(entry.get("region") or "")) or ""
            prefix = _std_prefix(str(entry.get("prefix") or ""))
            _touch_progress(rid=rid, prefix=prefix, phase="start")
            try:
                idx = _export_prefix_index(
                    entry,
                    max_covers=max_covers_per_prefix,
                    skip_fresh_hours=skip_fresh_hours,
                )
                _touch_progress(
                    rid=rid,
                    prefix=prefix,
                    phase="done",
                    cover_n=int(idx.get("coverCount") or 0),
                    was_skipped=bool(idx.get("skipped")),
                )
                return idx
            except Exception:
                # 失败也推进进度，避免条卡住不动
                _touch_progress(rid=rid, prefix=prefix, phase="done")
                raise

        if worker_n == 1 or len(work) <= 1:
            for entry in work:
                try:
                    _one(entry)
                except Exception as e:
                    log.warning(
                        "maker-fs build prefix %s: %s",
                        entry.get("prefix"),
                        e,
                    )
        else:
            with ThreadPoolExecutor(max_workers=worker_n) as pool:
                futs = {pool.submit(_one, entry): entry for entry in work}
                for fut in as_completed(futs):
                    entry = futs[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        log.warning(
                            "maker-fs build prefix %s: %s",
                            entry.get("prefix"),
                            e,
                        )

        # 封面导出后再汇总各区已确认子条目数
        overview = _write_region_catalogs(prefixes)

        manifest = {
            "version": 2,
            "ready": True,
            "updatedAt": _now_iso(),
            "prefixCount": built,
            "coverCount": total_covers,
            "skippedCount": skipped,
            "workers": worker_n,
            "skipFreshHours": skip_fresh_hours,
            "region": region_id or "",
            "root": str(MAKER_FS_ROOT),
            "source": "db",
            "scope": (
                f"nav_covers_l1_{region_id}"
                if region_id
                else "nav_covers_l1_regions"
            ),
            "regions": overview.get("regions") or [],
        }
        write_json(manifest_path(), manifest)
        done_msg = "ok"
        if built > 0 and total_covers <= 0:
            done_msg = (
                "完成但条目为 0：资源库已通，请检查 设置→论坛管理 的地区标签"
                "是否覆盖资源所在板块（未标注=不索引）"
            )
        _build_state.update(
            {
                "running": False,
                "finishedAt": _now_iso(),
                "message": done_msg,
                "prefixes": built,
                "prefixTotal": len(work),
                "covers": total_covers,
                "skipped": skipped,
                "currentPrefix": "",
                "updatedAt": _now_iso(),
            }
        )
        return {
            "manifest": manifest,
            "treePrefixCount": tree.get("prefixCount"),
            "regions": overview,
        }
    except Exception as e:
        _build_state.update(
            {
                "running": False,
                "finishedAt": _now_iso(),
                "message": str(e),
            }
        )
        raise
    finally:
        _build_lock.release()
