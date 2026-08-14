"""从 maker-fs 索引物化到 scrape library 目录，并提供目录浏览。

结构与刮削命名一致：{category}/{studio}/{series_name}/{number}/
  meta.json   — 本地索引物化（本模块写入）
  scrape.json — 刮削结果（刮削模块写入，本模块不改）
  封面.url

同步：本地与索引路径完全对齐（补齐 + 删除多余）。
FC2 刮削搬家产生的作者目录写入白名单，同步时不删；
片商/定位读取时优先非「未分类」，同番号在未分类中则跳过。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import maker_fs, scrape_export, scrape_naming
from .db import ROOT
from .scrape_forum_title import is_likely_chinese
from .scrape_metadata_optimize import normalize_actor_names

log = logging.getLogger("nextweb.library")

COVER_URL_NAME = "封面.url"
INDEX_META_FILE = "meta.json"
SCRAPE_META_FILE = "scrape.json"
FC2_KEEP_FILE = ".fc2-keep.json"
# 本地小文件写入：并行度（IO 为主）
_DEFAULT_MAT_WORKERS = max(4, min(12, (os.cpu_count() or 4) * 2))
_PROGRESS_EVERY = 32
_fc2_keep_lock = threading.Lock()

_mat_lock = threading.Lock()
_meta_lock = threading.Lock()
_mat_state: dict[str, Any] = {
    "running": False,
    "startedAt": "",
    "finishedAt": "",
    "message": "",
    "region": "",
    "total": 0,
    "done": 0,
    "written": 0,
    "skipped": 0,
    "updated": 0,
    "removed": 0,
    "errors": 0,
    "currentCode": "",
    "workers": 0,
    "updatedAt": "",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def materialize_status() -> dict[str, Any]:
    with _meta_lock:
        return dict(_mat_state)


def _set_state(**kwargs: Any) -> None:
    with _meta_lock:
        _mat_state.update(kwargs)
        _mat_state["updatedAt"] = _now_iso()


def _library_root() -> Path:
    raw = scrape_export.scrape_settings()["libraryRoot"]
    lib = Path(str(raw))
    if not lib.is_absolute():
        lib = (ROOT / lib).resolve()
    else:
        lib = lib.resolve()
    return lib


def _internet_shortcut(url: str) -> str:
    u = str(url or "").strip()
    return f"[InternetShortcut]\nURL={u}\n"


def _norm_text_newlines(s: str) -> str:
    return str(s or "").replace("\r\n", "\n").replace("\r", "\n")


def _ensure_cover_url_file(url_path: Path, cover_url: str) -> bool:
    """仅在缺失或 URL 变化时写 封面.url。返回是否写盘。"""
    u = str(cover_url or "").strip()
    if not u:
        if url_path.is_file():
            try:
                url_path.unlink()
                return True
            except OSError:
                return False
        return False
    body = _internet_shortcut(u)
    if url_path.is_file():
        try:
            prev = _norm_text_newlines(url_path.read_text(encoding="utf-8"))
            if prev == _norm_text_newlines(body):
                return False
        except Exception:
            pass
    with url_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    return True


def _norm_str_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()]


def _canonicalize_seed_identity(
    *,
    code: str,
    prefix: Any,
    region: str,
) -> tuple[str, str]:
    """与索引一致：只做大小写/分隔符整理，不改 FC2 ↔ FC2-PPV 等形态。"""
    del region
    c = str(code or "").strip().upper().replace("_", "-")
    p = maker_fs._std_prefix(str(prefix or ""))  # noqa: SLF001
    if not c:
        return "", p
    # 缺前缀时按番号推断，不覆盖索引已给的前缀
    if not p:
        if re.search(r"FC2-?PPV", c, re.I):
            p = "FC2PPV"
        elif re.match(r"^FC2-\d", c, re.I):
            p = "FC2"
    return c, p


def _seed_richness(seed: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        1 if str(seed.get("coverUrl") or "").strip() else 0,
        len(_norm_str_list(seed.get("coverUrls"))),
        1 if str(seed.get("title") or "").strip() else 0,
        len(_norm_str_list(seed.get("actors"))),
    )


def _merge_seed_preserve(
    existing: dict[str, Any], seed: dict[str, Any]
) -> dict[str, Any]:
    """空字段不覆盖已有内容（同目录重复写入时勿用空壳冲掉封面/标题）。"""
    out = dict(seed)
    for k in ("title", "titleZh", "coverUrl", "poster"):
        if not str(out.get(k) or "").strip() and str(existing.get(k) or "").strip():
            out[k] = existing.get(k)
    if not _norm_str_list(out.get("coverUrls")) and _norm_str_list(
        existing.get("coverUrls")
    ):
        out["coverUrls"] = list(existing.get("coverUrls") or [])
    if not _norm_str_list(out.get("actors")) and _norm_str_list(existing.get("actors")):
        out["actors"] = list(existing.get("actors") or [])
    return out


def _seed_unchanged(existing: dict[str, Any], seed: dict[str, Any]) -> bool:
    """种子内容未变则不必重写 meta.json（忽略 seededAt/updatedAt）。"""
    for k in (
        "code",
        "prefix",
        "title",
        "titleZh",
        "coverUrl",
        "poster",
        "maker",
        "studio",
        "region",
        "regionLabel",
        "source",
    ):
        if str(existing.get(k) or "") != str(seed.get(k) or ""):
            return False
    if _norm_str_list(existing.get("actors")) != _norm_str_list(seed.get("actors")):
        return False
    if _norm_str_list(existing.get("coverUrls")) != _norm_str_list(seed.get("coverUrls")):
        return False
    return True


def _is_network_scraped(meta: dict[str, Any]) -> bool:
    """已有网络刮削痕迹则不可被索引种子覆盖。"""
    if meta.get("scrapedAt") or meta.get("scraped_at"):
        return True
    if meta.get("exportFields"):
        return True
    src = str(meta.get("source") or "").strip().lower()
    if src and src not in {"maker-fs", "index", "forum", "seed"}:
        return True
    fs = meta.get("fieldSources")
    if isinstance(fs, dict):
        for v in fs.values():
            s = str(v or "").strip().lower()
            if s and s not in {"forum", "maker-fs", "index", "seed"}:
                return True
    return False


def _normalize_fc2_maker(maker: str, region: str) -> str:
    rid = maker_fs.resolve_fs_region(region) or str(region or "").strip()
    bn = str(maker or "").strip()
    if rid != "fc2":
        return bn or "未分组"
    if bn and bn not in {"自定义", "未分组", "未知"}:
        # plate shell → 未分类
        s = "".join(ch for ch in bn.lower() if ch not in " ·-_/=")
        if s in {"fc2", "fc2ppv", "fc2ppvfc2"} or s.startswith("fc2fc2"):
            return "未分类"
        if s == "fc2" or s == "fc2ppv":
            return "未分类"
        return bn
    return "未分类"


def _write_entry(
    library: Path,
    naming: dict[str, Any],
    target: dict[str, Any],
    *,
    actor_map_enable: bool | None = None,
    actor_map_lang: str | None = None,
) -> str:
    """返回 written|updated|skipped|error。

    二次同步热路径：已存在且未变则只读 meta 比对，不 mkdir、不重写封面.url。
    """
    rid = str(target.get("region") or "")
    code, prefix = _canonicalize_seed_identity(
        code=str(target.get("code") or ""),
        prefix=target.get("prefix"),
        region=rid,
    )
    if not code:
        return "error"
    label = scrape_naming.KIND_LABELS.get(
        scrape_naming.resolve_kind(region=rid, code=code), ""
    ) or maker_fs.REGION_META.get(rid, {}).get("label") or rid
    maker = _normalize_fc2_maker(str(target.get("maker") or ""), rid)
    target = {**target, "maker": maker, "prefix": prefix, "code": code}

    raw_actors = target.get("forumActors")
    actors: list[str] = []
    if isinstance(raw_actors, list):
        actors = normalize_actor_names(
            [str(a) for a in raw_actors if str(a).strip()],
            lang=actor_map_lang,
            enable=actor_map_enable,
        )

    title = str(target.get("forumTitle") or "").strip()
    cover_url = str(target.get("coverUrl") or "").strip()
    cover_urls = [
        str(u).strip()
        for u in (target.get("coverUrls") or [])
        if str(u).strip()
    ]
    if cover_url and cover_url not in cover_urls:
        cover_urls = [cover_url, *cover_urls]

    meta_seed: dict[str, Any] = {
        "code": code,
        "prefix": prefix,
        "maker": maker,
        "studio": maker,
        "region": rid,
        "regionLabel": label,
        "title": title or None,
        # 日文正片题只放 title；titleZh 仅真正中文
        "titleZh": title if (title and is_likely_chinese(title)) else None,
        "actors": actors,
        "coverUrl": cover_url or None,
        "coverUrls": cover_urls[:6],
        "poster": cover_url or None,
        "source": "maker-fs",
        "seededAt": _now_iso(),
    }

    kind_id = scrape_naming.resolve_kind(region=rid, code=code)
    entry_dir = scrape_naming.resolve_entry_dir(
        library,
        naming,
        code=code,
        meta=meta_seed,
        target=target,
        category=label,
        kind=kind_id,
    )
    meta_path = entry_dir / INDEX_META_FILE
    scrape_path = entry_dir / SCRAPE_META_FILE
    url_path = entry_dir / COVER_URL_NAME

    if meta_path.is_file():
        try:
            existing = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}

        scraped = _is_network_scraped(existing)
        if scraped and not scrape_path.is_file():
            # 旧版把刮削写进 meta.json：迁到 scrape.json 后，索引文件改回种子
            entry_dir.mkdir(parents=True, exist_ok=True)
            try:
                scrape_path.write_text(
                    json.dumps(existing, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                log.warning(
                    "migrate scrape meta failed %s", entry_dir, exc_info=True
                )

        # 空壳索引不覆盖已有标题/封面（FC2 / FC2-PPV 同目录）
        meta_seed = _merge_seed_preserve(existing, meta_seed)
        prev_seeded = str(existing.get("seededAt") or "").strip()
        if prev_seeded:
            meta_seed["seededAt"] = prev_seeded

        if not scraped and _seed_unchanged(existing, meta_seed):
            cover = str(meta_seed.get("coverUrl") or "")
            if cover and not url_path.is_file():
                entry_dir.mkdir(parents=True, exist_ok=True)
                _ensure_cover_url_file(url_path, cover)
                return "updated"
            return "skipped"

        meta_seed["updatedAt"] = _now_iso()
        entry_dir.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(meta_seed, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        _ensure_cover_url_file(url_path, str(meta_seed.get("coverUrl") or ""))
        return "updated"

    # 新条目
    entry_dir.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        json.dumps(meta_seed, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    _ensure_cover_url_file(url_path, cover_url)
    return "written"


_CODE_DIR_RE = re.compile(
    r"^(?:FC2(?:-?PPV)?-?\d+|[A-Z0-9]{2,20}-\d{2,10}|[A-Z]{2,24}\.\d{4}(?:\.\d{2}){0,2})$",
    re.I,
)
_SKIP_TOP_NAMES = {".git", "__pycache__", "node_modules"}


def _norm_entry_code(raw: str) -> str:
    s = str(raw or "").strip().upper().replace("_", "-")
    if not s:
        return ""
    try:
        from .search_av import std_code_key

        return std_code_key(s, pad=3) or s
    except Exception:
        return s


def _read_entry_code(entry_dir: Path, *, prefer_name: bool = False) -> str:
    name = entry_dir.name.strip()
    if prefer_name and _CODE_DIR_RE.fullmatch(name):
        return _norm_entry_code(name)
    for fname in (INDEX_META_FILE, SCRAPE_META_FILE):
        p = entry_dir / fname
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            c = _norm_entry_code(str(data.get("code") or ""))
            if c:
                return c
    if _CODE_DIR_RE.fullmatch(name):
        return _norm_entry_code(name)
    return ""


def _is_entry_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    if _CODE_DIR_RE.fullmatch(path.name.strip()):
        return True
    if (path / INDEX_META_FILE).is_file() or (path / SCRAPE_META_FILE).is_file():
        return True
    return False


def _iter_library_entry_dirs(library: Path):
    """遍历片库番号目录（区域/厂牌[/前缀]/番号），不做全库 rglob。"""
    if not library.is_dir():
        return
    try:
        regions = [p for p in library.iterdir() if p.is_dir()]
    except OSError:
        return
    for region in regions:
        if region.name in _SKIP_TOP_NAMES or region.name.startswith("."):
            continue
        try:
            makers = [p for p in region.iterdir() if p.is_dir()]
        except OSError:
            continue
        for maker in makers:
            if maker.name.startswith("."):
                continue
            try:
                children = [p for p in maker.iterdir() if p.is_dir()]
            except OSError:
                continue
            for child in children:
                if _is_entry_dir(child):
                    yield child
                    continue
                try:
                    for code_dir in child.iterdir():
                        if code_dir.is_dir() and _is_entry_dir(code_dir):
                            yield code_dir
                except OSError:
                    pass


def _rel_posix(library: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(library.resolve()).as_posix()
    except Exception:
        return str(path).replace("\\", "/")


def load_fc2_keep(library: Path | None = None) -> set[str]:
    """FC2 刮削搬家后的作者目录白名单（相对 library 的 posix 路径）。"""
    lib = library or _library_root()
    path = lib / FC2_KEEP_FILE
    if not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if isinstance(raw, dict):
        items = raw.get("paths") or raw.get("keep") or []
    elif isinstance(raw, list):
        items = raw
    else:
        return set()
    out: set[str] = set()
    for x in items:
        s = str(x or "").strip().replace("\\", "/").strip("/")
        if s:
            out.add(s)
    return out


def add_fc2_keep_path(library: Path, rel_or_abs: str | Path) -> None:
    """把刮削产生的作者番号目录加入白名单（同步时不删）。"""
    lib = library.resolve()
    p = Path(rel_or_abs)
    if p.is_absolute():
        rel = _rel_posix(lib, p)
    else:
        rel = str(rel_or_abs).replace("\\", "/").strip().strip("/")
    if not rel or "未分类" in rel.split("/"):
        return
    with _fc2_keep_lock:
        keep = load_fc2_keep(lib)
        if rel in keep:
            return
        keep.add(rel)
        path = lib / FC2_KEEP_FILE
        try:
            path.write_text(
                json.dumps(
                    {"version": 1, "paths": sorted(keep)},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception:
            log.warning("write fc2 keep failed", exc_info=True)


def _path_key(path: Path | str) -> str:
    """稳定路径键：避免 Path.resolve() 对海量目录逐个 stat。"""
    return os.path.normcase(os.path.abspath(str(path)))


def is_fc2_keep_path(
    library: Path,
    entry: Path,
    *,
    keep: set[str] | None = None,
) -> bool:
    rel = _rel_posix(library, entry)
    if not rel:
        return False
    keep_set = keep if keep is not None else load_fc2_keep(library)
    if rel in keep_set:
        return True
    # 白名单命中任意前缀（作者夹整棵）
    for k in keep_set:
        if rel == k or rel.startswith(k.rstrip("/") + "/"):
            return True
    return False


def _expected_paths_and_codes(
    library: Path,
    naming: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    on_progress: Any | None = None,
) -> tuple[set[str], set[str]]:
    """返回 (expected_codes, expected_dir_keys)。含 FC2，一律按索引规范路径。"""
    codes: set[str] = set()
    expected_dirs: set[str] = set()
    total = len(targets)
    for i, t in enumerate(targets, 1):
        rid = str(t.get("region") or "")
        code, prefix = _canonicalize_seed_identity(
            code=str(t.get("code") or ""),
            prefix=t.get("prefix"),
            region=rid,
        )
        if not code:
            continue
        codes.add(code)
        kind_id = scrape_naming.resolve_kind(region=rid, code=code)
        label = scrape_naming.KIND_LABELS.get(kind_id, "") or maker_fs.REGION_META.get(
            rid, {}
        ).get("label") or rid
        maker = _normalize_fc2_maker(str(t.get("maker") or ""), rid)
        meta = {
            "code": code,
            "prefix": prefix,
            "maker": maker,
            "studio": maker,
            "region": rid,
        }
        try:
            d = scrape_naming.resolve_entry_dir(
                library,
                naming,
                code=code,
                meta=meta,
                target={**t, "maker": maker, "prefix": prefix, "code": code},
                category=str(label),
                kind=kind_id,
            )
            expected_dirs.add(_path_key(d))
        except Exception:
            pass
        if on_progress and (i == 1 or i % 2048 == 0 or i >= total):
            on_progress(i, total)
    return codes, expected_dirs


def _prune_empty_parents(path: Path, stop_at: Path) -> None:
    try:
        stop = stop_at.resolve()
    except Exception:
        return
    cur = path
    for _ in range(8):
        try:
            cur = cur.resolve()
        except Exception:
            return
        if cur == stop:
            return
        try:
            if stop not in cur.parents:
                return
        except Exception:
            return
        try:
            next(cur.iterdir())
            return
        except StopIteration:
            parent = cur.parent
            try:
                cur.rmdir()
            except OSError:
                return
            cur = parent
        except OSError:
            return


def prune_library_to_index(
    library: Path,
    naming: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    on_progress: Any | None = None,
) -> dict[str, int]:
    """与索引路径完全对齐；FC2 刮削白名单目录保留不删。"""

    def _build_prog(done: int, total: int) -> None:
        if on_progress:
            on_progress("build", done, total, 0, 0)

    codes, expected_dirs = _expected_paths_and_codes(
        library, naming, targets, on_progress=_build_prog
    )
    keep = load_fc2_keep(library)
    removed = 0
    kept = 0
    scanned = 0

    def _rm(entry: Path) -> None:
        nonlocal removed
        try:
            parent = entry.parent
            shutil.rmtree(entry)
            removed += 1
            _prune_empty_parents(parent, library)
        except OSError as e:
            log.warning("prune remove %s failed: %s", entry, e)

    for entry in _iter_library_entry_dirs(library):
        scanned += 1
        key = _path_key(entry)
        if key in expected_dirs:
            kept += 1
        else:
            code = _read_entry_code(entry, prefer_name=True)
            if not code:
                if on_progress and scanned % 512 == 0:
                    on_progress("scan", scanned, len(targets), kept, removed)
                continue
            # 索引仍有此番号，且目录在刮削白名单（作者夹）→ 保留
            if code in codes and is_fc2_keep_path(library, entry, keep=keep):
                kept += 1
            else:
                _rm(entry)
        if on_progress and (scanned == 1 or scanned % 512 == 0):
            on_progress("scan", scanned, len(targets), kept, removed)

    if on_progress:
        on_progress("scan", scanned, len(targets), kept, removed)
    return {"removed": removed, "kept": kept, "scanned": scanned}


def _collect_targets(region: str | None = None) -> list[dict[str, Any]]:
    """收集待物化目标。

    collect_targets 已按 区|前缀|番号 去重，且落盘与索引一一对应；
    rekey=False 跳过全库重算键，避免点击后干等十余秒才见进度。
    include_fill=True：digit_pad 前缀按 fillFrom..fillTo 建空洞目录
    （如 SONE-014 不在 covers 也会建空文件夹，与片商列表 999 一致）。
    """
    return scrape_export.collect_targets(
        region=region or None,
        rekey=False,
        include_fill=True,
    )


def _dedupe_targets_by_entry_path(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一落盘目录只保留信息最全的一条（保留供测试/特殊调用；热路径默认不用）。"""
    naming = scrape_naming.fixed_naming()
    library = _library_root()
    best: dict[str, tuple[tuple[int, int, int, int], dict[str, Any]]] = {}
    order: list[str] = []
    for t in targets:
        rid = str(t.get("region") or "")
        code, prefix = _canonicalize_seed_identity(
            code=str(t.get("code") or ""),
            prefix=t.get("prefix"),
            region=rid,
        )
        if not code:
            continue
        maker = _normalize_fc2_maker(str(t.get("maker") or ""), rid)
        label = scrape_naming.KIND_LABELS.get(
            scrape_naming.resolve_kind(region=rid, code=code), ""
        ) or maker_fs.REGION_META.get(rid, {}).get("label") or rid
        meta = {
            "code": code,
            "prefix": prefix,
            "maker": maker,
            "studio": maker,
            "region": rid,
            "title": t.get("forumTitle"),
            "coverUrl": t.get("coverUrl"),
            "actors": t.get("forumActors") if isinstance(t.get("forumActors"), list) else [],
        }
        try:
            d = scrape_naming.resolve_entry_dir(
                library,
                naming,
                code=code,
                meta=meta,
                target={**t, "maker": maker, "prefix": prefix, "code": code},
                category=str(label),
            )
            key = _path_key(d)
        except Exception:
            key = f"{rid}|{prefix}|{code}|{maker}"
        merged = {
            **t,
            "code": code,
            "prefix": prefix,
            "maker": maker,
        }
        score = _seed_richness(
            {
                "coverUrl": merged.get("coverUrl"),
                "coverUrls": merged.get("coverUrls") or [],
                "title": merged.get("forumTitle"),
                "actors": merged.get("forumActors") or [],
            }
        )
        prev = best.get(key)
        if prev is None:
            best[key] = (score, merged)
            order.append(key)
            continue
        prev_score, prev_t = prev
        if score > prev_score:
            keep = _merge_target_richer(prev_t, merged)
            best[key] = (
                _seed_richness(
                    {
                        "coverUrl": keep.get("coverUrl"),
                        "coverUrls": keep.get("coverUrls") or [],
                        "title": keep.get("forumTitle"),
                        "actors": keep.get("forumActors") or [],
                    }
                ),
                keep,
            )
        else:
            keep = _merge_target_richer(merged, prev_t)
            best[key] = (prev_score, keep)
    return [best[k][1] for k in order if k in best]


def _merge_target_richer(base: dict[str, Any], rich: dict[str, Any]) -> dict[str, Any]:
    """rich 优先非空字段，保留 base 其它键。"""
    out = dict(base)
    out.update({k: v for k, v in rich.items() if v not in (None, "", [], {})})
    for k in ("coverUrl", "forumTitle"):
        if not str(out.get(k) or "").strip() and str(base.get(k) or "").strip():
            out[k] = base.get(k)
    if not _norm_str_list(out.get("coverUrls")) and _norm_str_list(base.get("coverUrls")):
        out["coverUrls"] = list(base.get("coverUrls") or [])
    if not (
        isinstance(out.get("forumActors"), list) and out.get("forumActors")
    ) and isinstance(base.get("forumActors"), list):
        out["forumActors"] = list(base.get("forumActors") or [])
    return out


def materialize_library(
    *,
    region: str | None = None,
    workers: int | None = None,
) -> dict[str, Any]:
    """同步执行物化；调用方负责后台线程。"""
    if not _mat_lock.acquire(blocking=False):
        raise RuntimeError("本地片库同步正在进行中")
    try:
        region_key = (region or "").strip() or ""
        # 立刻刷新状态，避免收集索引时 UI 长时间停在 queued / 0
        _set_state(
            running=True,
            finishedAt="",
            message="收集索引…",
            region=region_key,
            total=0,
            done=0,
            written=0,
            skipped=0,
            updated=0,
            removed=0,
            errors=0,
            currentCode="",
            workers=0,
        )
        targets = _collect_targets(region_key or None)
        if not targets:
            raise ValueError("没有可同步的番号，请先增量/全量扫库生成本地索引")

        library = _library_root()
        library.mkdir(parents=True, exist_ok=True)
        cfg = scrape_export.scrape_settings()
        naming = scrape_naming.fixed_naming()
        worker_n = max(1, min(16, int(workers or _DEFAULT_MAT_WORKERS)))

        # 整次同步只读一次映射配置，避免每条打 settings
        actor_map_enable = True
        actor_map_lang = "zh-CN"
        try:
            from .scrape_metadata_optimize import (
                mapping_language_from_settings,
                normalize_metadata_optimize,
            )

            actor_map_lang = mapping_language_from_settings()
            opt = normalize_metadata_optimize(
                (cfg.get("metadataOptimize") or cfg.get("metadata_optimize"))
            )
            actor_map_enable = bool(opt.get("enableActorMapping", True))
        except Exception:
            pass

        _set_state(
            running=True,
            finishedAt="",
            message="同步中",
            region=region_key,
            total=len(targets),
            done=0,
            written=0,
            skipped=0,
            updated=0,
            removed=0,
            errors=0,
            currentCode="",
            workers=worker_n,
        )

        written = skipped = updated = errors = 0
        done = 0
        counters_lock = threading.Lock()

        def _one(t: dict[str, Any]) -> tuple[str, str]:
            code = str(t.get("code") or "")
            try:
                return code, _write_entry(
                    library,
                    naming,
                    t,
                    actor_map_enable=actor_map_enable,
                    actor_map_lang=actor_map_lang,
                )
            except Exception as e:
                log.warning("materialize %s failed: %s", code, e)
                return code, "error"

        def _bump(code: str, result: str) -> None:
            nonlocal written, skipped, updated, errors, done
            with counters_lock:
                done += 1
                if result == "written":
                    written += 1
                elif result == "updated":
                    updated += 1
                elif result == "skipped":
                    skipped += 1
                else:
                    errors += 1
                # 降频刷进度，避免每条抢锁拖慢
                if done == 1 or done % _PROGRESS_EVERY == 0 or done >= len(targets):
                    _set_state(
                        done=done,
                        written=written,
                        skipped=skipped,
                        updated=updated,
                        errors=errors,
                        currentCode=code,
                        message=(
                            f"同步 {done}/{len(targets)}"
                            f" · 跳过 {skipped} · 更新 {updated} · 新写 {written}"
                        ),
                    )

        if worker_n <= 1:
            for t in targets:
                code, result = _one(t)
                _bump(code, result)
        else:
            # map 限流提交，避免一次建数万 Future
            with ThreadPoolExecutor(max_workers=worker_n) as pool:
                for code, result in pool.map(_one, targets, chunksize=16):
                    _bump(code, result)

        _set_state(
            message="清理多余目录…",
            currentCode="",
            done=len(targets),
            written=written,
            skipped=skipped,
            updated=updated,
            errors=errors,
        )
        removed = 0
        try:

            def _prune_prog(
                phase: str, a: int, b: int, kept_n: int, removed_n: int
            ) -> None:
                if phase == "build":
                    _set_state(
                        message=f"清理准备 {a}/{b}",
                        removed=removed_n,
                        currentCode="",
                    )
                else:
                    _set_state(
                        message=f"清理扫描 {a} · 保留 {kept_n} · 删除 {removed_n}",
                        removed=removed_n,
                        currentCode="",
                    )

            pruned = prune_library_to_index(
                library, naming, targets, on_progress=_prune_prog
            )
            removed = int(pruned.get("removed") or 0)
        except Exception as e:
            log.warning("prune library failed: %s", e)

        _set_state(
            running=False,
            finishedAt=_now_iso(),
            message="ok",
            done=len(targets),
            written=written,
            skipped=skipped,
            updated=updated,
            removed=removed,
            errors=errors,
            currentCode="",
        )
        try:
            _write_catalogs_from_targets(targets)
            # 同步刷新标签/系列分类索引（失败不影响物化成功）
            try:
                seen_rids = {
                    str(t.get("region") or "").strip()
                    for t in targets
                    if str(t.get("region") or "").strip()
                }
                for rid in seen_rids:
                    sync_region_facets(rid, force=False)
            except Exception:
                log.warning("facets rebuild after materialize failed", exc_info=True)
        except Exception as e:
            log.warning("catalog cache after materialize: %s", e)
        return materialize_status()
    except Exception as e:
        _set_state(
            running=False,
            finishedAt=_now_iso(),
            message=str(e) or "failed",
        )
        raise
    finally:
        _mat_lock.release()


def fail_materialize(message: str = "failed") -> None:
    _set_state(running=False, finishedAt=_now_iso(), message=message or "failed")


def _parse_state_time(raw: str) -> datetime | None:
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


def claim_materialize(*, region: str | None = None, force: bool = False) -> bool:
    """申请开始物化。

    真在跑（持有工作锁）→ 拒绝（force 也不能打断）。
    running 标志僵死（工作锁空闲且超时）或 force+锁空闲 → 回收后领取。
    """
    lock_busy = not _mat_lock.acquire(blocking=False)
    if not lock_busy:
        _mat_lock.release()

    with _meta_lock:
        running = bool(_mat_state.get("running"))

        # 工作锁占用 = 真在跑，不可抢
        if lock_busy:
            return False

        if running and not force:
            msg = str(_mat_state.get("message") or "")
            ts = _parse_state_time(
                str(_mat_state.get("updatedAt") or _mat_state.get("startedAt") or "")
            )
            age = (
                (datetime.now(timezone.utc) - ts).total_seconds()
                if ts
                else 10**9
            )
            # 收集阶段宽限 90s（线程已领取但尚未开写）
            if msg in {"queued", "收集索引…"} and age < 90:
                return False
            # 其它状态锁却空闲：超过 2 分钟视为僵死
            if msg not in {"queued", "收集索引…"} and age < 120:
                return False

        _mat_state.update(
            {
                "running": True,
                "startedAt": _now_iso(),
                "finishedAt": "",
                "message": "收集索引…",
                "region": (region or "").strip(),
                "total": 0,
                "done": 0,
                "written": 0,
                "skipped": 0,
                "updated": 0,
                "removed": 0,
                "errors": 0,
                "currentCode": "",
                "workers": 0,
                "updatedAt": _now_iso(),
            }
        )
        return True


def abort_claim(message: str = "failed") -> None:
    with _meta_lock:
        if _mat_state.get("message") in {"queued", "收集索引…"}:
            _mat_state.update(
                {
                    "running": False,
                    "finishedAt": _now_iso(),
                    "message": message,
                }
            )


def run_materialize_background(*, region: str | None = None) -> None:
    try:
        # claim 已设 running；materialize_library 内再拿锁
        # 释放 claim 的「假 running」：直接跑，绕过 claim 锁冲突
        # 简化：background 不经 claim 双重锁——路由里用线程直接调 materialize_library
        materialize_library(region=region)
    except Exception as e:
        log.exception("library materialize failed: %s", e)
        _set_state(running=False, finishedAt=_now_iso(), message=str(e))


# ---------- browse ----------


def _safe_list_dirs(path: Path) -> list[str]:
    """列出子目录名（排序）；适合厂牌/前缀等少量层级。"""
    if not path.is_dir():
        return []
    out: list[str] = []
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        out.append(e.name)
                except OSError:
                    continue
        out.sort(key=str.lower)
    except OSError:
        return []
    return out


def _count_dirs_fast(path: Path) -> int:
    """仅计数子目录，不排序、不建列表（番号层可能上万）。"""
    if not path.is_dir():
        return 0
    n = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        n += 1
                except OSError:
                    continue
    except OSError:
        return 0
    return n


_CATALOG_NAME = ".catalog.json"


def _region_catalog_path(label: str) -> Path:
    return _library_root() / label / _CATALOG_NAME


def _sort_prefixes_nav(prefixes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """与 maker-fs 区目录一致：按导航番号热门序，而非字母序。"""
    try:
        nav_ord = maker_fs._nav_prefix_order()  # noqa: SLF001
        std = maker_fs._std_prefix  # noqa: SLF001
    except Exception:
        return list(prefixes)
    return sorted(
        prefixes,
        key=lambda r: (
            nav_ord.get(std(str(r.get("prefix") or "")), 10**9),
            str(r.get("prefix") or ""),
        ),
    )


_CATALOG_SEARCH_VERSION = 2
_MAX_PREFIX_ACTORS = 80
_MAX_PREFIX_TAGS = 80


def _uniq_cap(items: list[str] | set[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        s = str(raw or "").strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _entry_search_bits(entry_dir: Path) -> tuple[list[str], list[str]]:
    """从 meta.json / scrape.json 抽女优与刮削标签（刮削优先）。"""
    scrape = _read_json_dict(entry_dir / SCRAPE_META_FILE)
    index = _read_json_dict(entry_dir / INDEX_META_FILE)
    if not scrape and index and _meta_looks_scraped(index):
        scrape = index
        index = {}

    def _actors(src: dict[str, Any]) -> list[str]:
        raw = src.get("actors") if isinstance(src.get("actors"), list) else None
        if not raw:
            raw = src.get("actress") if isinstance(src.get("actress"), list) else None
        return [str(a).strip() for a in (raw or []) if str(a).strip()]

    def _tags(src: dict[str, Any]) -> list[str]:
        raw = src.get("genres") if isinstance(src.get("genres"), list) else None
        if not raw:
            raw = src.get("tags") if isinstance(src.get("tags"), list) else None
        return [str(t).strip() for t in (raw or []) if str(t).strip()]

    actors = _actors(scrape) or _actors(index)
    tags = _tags(scrape) or _tags(index)
    return actors, tags


def _prefix_search_from_disk(
    root: Path,
    maker: str,
    prefix: str,
) -> tuple[list[str], list[str]]:
    path = root / maker / prefix
    if not path.is_dir():
        return [], []
    actors: list[str] = []
    tags: list[str] = []
    seen_a: set[str] = set()
    seen_t: set[str] = set()
    for name in _safe_list_dirs(path):
        a_list, t_list = _entry_search_bits(path / name)
        for a in a_list:
            k = a.casefold()
            if k in seen_a:
                continue
            seen_a.add(k)
            actors.append(a)
        for t in t_list:
            k = t.casefold()
            if k in seen_t:
                continue
            seen_t.add(k)
            tags.append(t)
        if len(actors) >= _MAX_PREFIX_ACTORS and len(tags) >= _MAX_PREFIX_TAGS:
            break
    return actors[:_MAX_PREFIX_ACTORS], tags[:_MAX_PREFIX_TAGS]


def _attach_prefix_search_fields(
    prefixes: list[dict[str, Any]],
    *,
    actors_map: dict[tuple[str, str], list[str]] | None = None,
    tags_map: dict[tuple[str, str], list[str]] | None = None,
    library_root: Path | None = None,
    region_label: str | None = None,
) -> list[dict[str, Any]]:
    """给前缀挂 actors / tags，供片商本页筛选女优与刮削标签。"""
    out: list[dict[str, Any]] = []
    root = None
    if library_root is not None and region_label:
        cand = library_root / region_label
        if cand.is_dir():
            root = cand
    for raw in prefixes:
        p = dict(raw)
        maker = str(p.get("board_name") or "").strip() or "未分组"
        pref = str(p.get("prefix") or "").strip()
        key = (maker, pref)
        actors = list((actors_map or {}).get(key) or [])
        tags = list((tags_map or {}).get(key) or [])
        if (not actors or not tags) and root and pref:
            disk_a, disk_t = _prefix_search_from_disk(root, maker, pref)
            if not actors:
                actors = disk_a
            if not tags:
                tags = disk_t
        p["actors"] = _uniq_cap(actors, _MAX_PREFIX_ACTORS)
        p["tags"] = _uniq_cap(tags, _MAX_PREFIX_TAGS)
        out.append(p)
    return out


def _catalog_has_search_fields(payload: dict[str, Any]) -> bool:
    if int(payload.get("version") or 0) < _CATALOG_SEARCH_VERSION:
        return False
    prefs = payload.get("prefixes")
    if not isinstance(prefs, list) or not prefs:
        return True
    for p in prefs[:24]:
        if not isinstance(p, dict):
            continue
        if isinstance(p.get("actors"), list) or isinstance(p.get("tags"), list):
            return True
    return False


def _build_catalog_payload(
    rid: str,
    prefixes: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = _sort_prefixes_nav(prefixes)
    makers = {str(p.get("board_name") or "").strip() for p in ordered}
    meta = maker_fs.REGION_META.get(rid) or {}
    label = scrape_naming.KIND_LABELS.get(rid) or meta.get("label") or rid
    return {
        "version": _CATALOG_SEARCH_VERSION,
        "id": rid,
        "label": label,
        "dbRegion": meta.get("db_region") or rid,
        "navPath": meta.get("navPath") or label,
        "updatedAt": _now_iso(),
        "prefixCount": len(ordered),
        "makerCount": len(makers),
        "codeCount": sum(int(p.get("codeCount") or 0) for p in ordered),
        "prefixes": ordered,
        "source": "library",
    }


def write_region_catalog_cache(
    rid: str,
    prefixes: list[dict[str, Any]],
) -> dict[str, Any]:
    """物化后写分区目录缓存，片商打开免扫盘；内容未变则不写盘。"""
    payload = _build_catalog_payload(rid, prefixes)
    label = str(payload.get("label") or "")
    if not label:
        return payload
    path = _region_catalog_path(label)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                old = None
            if isinstance(old, dict) and _catalog_payload_same(old, payload):
                return old
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("write catalog cache %s: %s", rid, e)
    return payload


def _catalog_payload_same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """忽略 updatedAt，比较目录缓存实质内容。"""
    for k in (
        "version",
        "id",
        "label",
        "dbRegion",
        "navPath",
        "prefixCount",
        "makerCount",
        "codeCount",
        "prefixes",
        "source",
    ):
        if a.get(k) != b.get(k):
            return False
    return True


def _write_catalogs_from_targets(targets: list[dict[str, Any]]) -> None:
    """按物化目标聚合各区 prefix 计数并落盘。"""
    buckets: dict[str, dict[tuple[str, str], int]] = {}
    actors_bags: dict[str, dict[tuple[str, str], list[str]]] = {}
    tags_bags: dict[str, dict[tuple[str, str], list[str]]] = {}
    lib = _library_root()
    naming = scrape_naming.fixed_naming()
    for t in targets:
        rid = str(t.get("region") or "").strip()
        if not rid:
            continue
        maker = str(t.get("maker") or "未分组").strip() or "未分组"
        pref = str(t.get("prefix") or "").strip().upper()
        if not pref:
            continue
        bag = buckets.setdefault(rid, {})
        key = (maker, pref)
        bag[key] = bag.get(key, 0) + 1

        a_bag = actors_bags.setdefault(rid, {}).setdefault(key, [])
        raw_actors = t.get("forumActors")
        if isinstance(raw_actors, list):
            for a in raw_actors:
                s = str(a or "").strip()
                if s:
                    a_bag.append(s)

        # 刮削标签：读已落盘 scrape.json（若有）
        try:
            code = str(t.get("code") or "").strip().upper()
            if code:
                kind_id = scrape_naming.resolve_kind(region=rid, code=code)
                label = scrape_naming.KIND_LABELS.get(kind_id, "") or maker_fs.REGION_META.get(
                    rid, {}
                ).get("label") or rid
                entry = scrape_naming.resolve_entry_dir(
                    lib,
                    naming,
                    code=code,
                    meta={"region": rid, "maker": maker, "studio": maker},
                    target={**t, "maker": maker},
                    category=label,
                    kind=kind_id,
                )
                _, tags = _entry_search_bits(entry)
                if tags:
                    tags_bags.setdefault(rid, {}).setdefault(key, []).extend(tags)
        except Exception:
            pass

    for rid, bag in buckets.items():
        label = scrape_naming.KIND_LABELS.get(rid) or rid
        prefixes = [
            {
                "prefix": pref,
                "name": f"{maker} · {pref}",
                "board_name": maker,
                "codeCount": n,
                "path": [label, maker, pref],
            }
            for (maker, pref), n in bag.items()
        ]
        prefixes = _attach_prefix_search_fields(
            prefixes,
            actors_map={
                k: _uniq_cap(v, _MAX_PREFIX_ACTORS)
                for k, v in (actors_bags.get(rid) or {}).items()
            },
            tags_map={
                k: _uniq_cap(v, _MAX_PREFIX_TAGS)
                for k, v in (tags_bags.get(rid) or {}).items()
            },
            library_root=lib,
            region_label=label,
        )
        write_region_catalog_cache(rid, prefixes)


def _scan_region_prefixes(root: Path, label: str) -> list[dict[str, Any]]:
    prefixes: list[dict[str, Any]] = []
    for studio in _safe_list_dirs(root):
        for pref in _safe_list_dirs(root / studio):
            prefixes.append(
                {
                    "prefix": pref,
                    "name": f"{studio} · {pref}",
                    "board_name": studio,
                    "codeCount": _count_dirs_fast(root / studio / pref),
                    "path": [label, studio, pref],
                }
            )
    return prefixes


def browse_regions() -> dict[str, Any]:
    lib = _library_root()
    regions: list[dict[str, Any]] = []
    for kid in scrape_naming.KIND_ORDER:
        label = scrape_naming.KIND_LABELS[kid]
        root = lib / label
        cache_path = root / _CATALOG_NAME
        if cache_path.is_file():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached.get("id"):
                    regions.append(
                        {
                            "id": kid,
                            "label": label,
                            "dbRegion": cached.get("dbRegion") or kid,
                            "navPath": cached.get("navPath") or label,
                            "prefixCount": int(cached.get("prefixCount") or 0),
                            "makerCount": int(cached.get("makerCount") or 0),
                            "codeCount": int(cached.get("codeCount") or 0),
                        }
                    )
                    continue
            except Exception:
                pass
        studios = _safe_list_dirs(root) if root.is_dir() else []
        maker_count = len(studios)
        prefix_count = 0
        code_count = 0
        for st in studios:
            prefs = _safe_list_dirs(root / st)
            prefix_count += len(prefs)
            for pf in prefs:
                code_count += _count_dirs_fast(root / st / pf)
        meta = maker_fs.REGION_META.get(kid) or {}
        regions.append(
            {
                "id": kid,
                "label": label,
                "dbRegion": meta.get("db_region") or kid,
                "navPath": meta.get("navPath") or label,
                "prefixCount": prefix_count,
                "makerCount": maker_count,
                "codeCount": code_count,
            }
        )
    ready = any((r["codeCount"] or 0) > 0 or (r["prefixCount"] or 0) > 0 for r in regions)
    return {
        "version": 1,
        "ready": ready,
        "libraryRoot": str(lib),
        "regionCount": len(regions),
        "regions": regions,
        "updatedAt": _now_iso(),
    }


def browse_region(region_id: str) -> dict[str, Any] | None:
    rid = maker_fs.resolve_fs_region(region_id) or str(region_id or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    label = scrape_naming.KIND_LABELS[rid]
    lib = _library_root()
    root = lib / label
    cache_path = root / _CATALOG_NAME
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and isinstance(cached.get("prefixes"), list):
                if _catalog_has_search_fields(cached):
                    return cached
                # 旧缓存无女优/标签：补齐后写回，供片商本页筛选
                enriched = _attach_prefix_search_fields(
                    [p for p in cached["prefixes"] if isinstance(p, dict)],
                    library_root=lib,
                    region_label=label,
                )
                return write_region_catalog_cache(rid, enriched)
        except Exception:
            pass
    prefixes = _scan_region_prefixes(root, label) if root.is_dir() else []
    prefixes = _attach_prefix_search_fields(
        prefixes,
        library_root=lib,
        region_label=label,
    )
    return write_region_catalog_cache(rid, prefixes)


def _parse_cover_url_file(path: Path) -> str:
    """读目录内索引本地化的 封面.url（InternetShortcut）。"""
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("URL="):
            return s[4:].strip()
    # 纯 URL 一行
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("http://") or s.startswith("https://"):
            return s
    return ""


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _meta_looks_scraped(meta: dict[str, Any]) -> bool:
    return _is_network_scraped(meta)


def _read_meta_summary(entry_dir: Path) -> dict[str, Any] | None:
    """片库条目摘要：有刮削数据优先用刮削，没有再用索引物化。

    - scrape.json 存在 → 刮削为主
    - 旧版刮削写在 meta.json → 仍当刮削读
    - 否则用索引 meta.json / 封面.url
    字段级：标题/女优/封面刮削有值用刮削，缺了回退索引（不合并写盘）。
    """
    scrape_path = entry_dir / SCRAPE_META_FILE
    meta_path = entry_dir / INDEX_META_FILE
    url_path = entry_dir / COVER_URL_NAME
    shortcut = _parse_cover_url_file(url_path)

    index_data = _read_json_dict(meta_path)
    scrape_data = _read_json_dict(scrape_path)
    if not scrape_data and index_data and _meta_looks_scraped(index_data):
        # 旧目录：刮削还在 meta.json，索引种子尚未拆分
        scrape_data = index_data
        index_data = {}

    if (
        not scrape_data
        and not index_data
        and not shortcut
        and not any(
            (entry_dir / cand).is_file()
            for cand in ("poster.jpg", "poster.jpeg", "poster.png", "poster.webp")
        )
    ):
        return None

    def _pick_str(*vals: Any) -> str | None:
        for v in vals:
            s = str(v or "").strip()
            if s:
                return s
        return None

    def _pick_actors(primary: dict[str, Any], fallback: dict[str, Any]) -> list[str] | None:
        for src in (primary, fallback):
            raw = src.get("actors") if isinstance(src.get("actors"), list) else None
            if not raw:
                raw = src.get("actress") if isinstance(src.get("actress"), list) else None
            cleaned = [str(a).strip() for a in (raw or []) if str(a).strip()]
            if cleaned:
                return cleaned
        return None

    def _pick_tags(primary: dict[str, Any], fallback: dict[str, Any]) -> list[str] | None:
        for src in (primary, fallback):
            raw = src.get("genres") if isinstance(src.get("genres"), list) else None
            if not raw:
                raw = src.get("tags") if isinstance(src.get("tags"), list) else None
            cleaned = [str(t).strip() for t in (raw or []) if str(t).strip()]
            if cleaned:
                return cleaned
        return None

    code = _pick_str(
        scrape_data.get("code"),
        index_data.get("code"),
        entry_dir.name,
    )
    code = str(code or entry_dir.name).strip().upper()

    title = _pick_str(
        scrape_data.get("titleZh"),
        scrape_data.get("title"),
        index_data.get("titleZh"),
        index_data.get("title"),
    )
    actors = _pick_actors(scrape_data, index_data)
    tags = _pick_tags(scrape_data, index_data)

    cover = _pick_str(
        scrape_data.get("coverUrl"),
        scrape_data.get("poster"),
        index_data.get("coverUrl"),
        index_data.get("poster"),
        shortcut,
    )
    urls: list[str] = []
    for src in (scrape_data, index_data):
        for u in src.get("coverUrls") or []:
            s = str(u or "").strip()
            if s and s not in urls:
                urls.append(s)
    if cover and cover not in urls:
        urls = [cover, *urls]
    if shortcut and shortcut not in urls:
        urls.append(shortcut)

    poster_name = None
    for cand in (
        "poster.jpg",
        "poster.jpeg",
        "poster.png",
        "poster.webp",
        f"{code}-poster.jpg",
    ):
        if (entry_dir / cand).is_file():
            poster_name = cand
            break
    poster_local = ""
    poster_rev = ""
    if poster_name:
        poster_path = entry_dir / poster_name
        try:
            lib = _library_root().resolve()
            rel = entry_dir.resolve().relative_to(lib).as_posix()
            poster_local = f"{rel}/{poster_name}"
        except Exception:
            poster_local = ""
        try:
            st = poster_path.stat()
            poster_rev = f"{int(st.st_mtime_ns)}-{int(st.st_size)}"
        except OSError:
            poster_rev = ""

    scraped = bool(scrape_path.is_file()) or bool(scrape_data)

    return {
        "code": code,
        "coverUrl": cover,
        "coverUrls": urls[:8],
        "forumTitle": title,
        "forumActors": actors,
        "genres": tags,
        "posterFile": poster_name,
        "posterLocal": poster_local or None,
        "posterRev": poster_rev or None,
        "directory": entry_dir.name,
        "scraped": scraped,
    }


def _fc2_codes_outside_uncategorized(fc2_root: Path, prefix: str) -> set[str]:
    """FC2 区下、非「未分类」厂牌中已存在的番号（同前缀）。"""
    out: set[str] = set()
    pref = str(prefix or "").strip()
    if not fc2_root.is_dir() or not pref:
        return out
    try:
        makers = [p for p in fc2_root.iterdir() if p.is_dir()]
    except OSError:
        return out
    for maker in makers:
        if maker.name == "未分类" or maker.name.startswith("."):
            continue
        code_root = maker / pref
        if not code_root.is_dir():
            # 也可能 maker/code 两层
            try:
                for child in maker.iterdir():
                    if not child.is_dir():
                        continue
                    if child.name.upper() == pref.upper():
                        code_root = child
                        break
                else:
                    continue
            except OSError:
                continue
        try:
            for name in _safe_list_dirs(code_root):
                c = _norm_entry_code(name)
                if c:
                    out.add(c)
        except Exception:
            pass
    return out


def _code_sort_key(it: dict[str, Any]) -> tuple:
    c = str(it.get("code") or "")
    m = re.search(r"(\d+)(?:\D*)$", c)
    n = int(m.group(1)) if m else 0
    return (-n, c)


def _dir_name_sort_key(name: str) -> tuple:
    c = _norm_entry_code(name) or str(name).strip().upper()
    m = re.search(r"(\d+)(?:\D*)$", c)
    n = int(m.group(1)) if m else 0
    return (-n, c)


def _empty_code_summary(name: str) -> dict[str, Any]:
    return {
        "code": str(name).strip().upper(),
        "coverUrl": None,
        "coverUrls": [],
        "forumTitle": None,
        "forumActors": None,
        "genres": None,
        "posterLocal": None,
        "posterRev": None,
        "scraped": False,
    }


def _summary_for_entry(entry_dir: Path, name: str) -> dict[str, Any]:
    summary = _read_meta_summary(entry_dir)
    if not summary:
        return _empty_code_summary(name)
    return summary


def _entry_looks_listable(entry_dir: Path) -> bool:
    """有封面文件 / 封面.url / 元数据里的封面或标题女优 → 可展示；否则空壳跳过。"""
    code = entry_dir.name
    for cand in (
        "poster.jpg",
        "poster.jpeg",
        "poster.png",
        "poster.webp",
        f"{code}-poster.jpg",
        COVER_URL_NAME,
    ):
        try:
            if (entry_dir / cand).is_file():
                return True
        except OSError:
            pass
    for fname in (SCRAPE_META_FILE, INDEX_META_FILE):
        data = _read_json_dict(entry_dir / fname)
        if not data:
            continue
        if str(data.get("coverUrl") or data.get("poster") or "").strip():
            return True
        urls = data.get("coverUrls")
        if isinstance(urls, list) and any(str(u or "").strip() for u in urls):
            return True
        if str(data.get("titleZh") or data.get("title") or "").strip():
            return True
        actors = data.get("actors") or data.get("actress") or []
        if isinstance(actors, list) and any(str(a or "").strip() for a in actors):
            return True
    return False


def _summary_is_listable(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    if str(summary.get("posterLocal") or "").strip():
        return True
    if str(summary.get("coverUrl") or "").strip():
        return True
    urls = summary.get("coverUrls")
    if isinstance(urls, list) and any(str(u or "").strip() for u in urls):
        return True
    if str(summary.get("forumTitle") or "").strip():
        return True
    actors = summary.get("forumActors")
    if isinstance(actors, list) and any(str(a or "").strip() for a in actors):
        return True
    return False


# 前缀可展示目录名短缓存（已剔除空壳）
_browse_names_cache: dict[str, tuple[float, int, list[str]]] = {}
_browse_names_lock = threading.Lock()


def _list_prefix_entry_names(root: Path) -> list[str]:
    """列出前缀下可展示的子目录（跳过无封面/无标题的空壳）。"""
    key = str(root.resolve())
    try:
        st = root.stat()
        sig = float(st.st_mtime)
        nlink = int(getattr(st, "st_nlink", 0) or 0)
    except OSError:
        raw = _safe_list_dirs(root)
        return [n for n in raw if _entry_looks_listable(root / n)]
    with _browse_names_lock:
        hit = _browse_names_cache.get(key)
        if hit and hit[0] == sig and hit[1] == nlink:
            return list(hit[2])
    raw = _safe_list_dirs(root)
    if raw:
        with ThreadPoolExecutor(max_workers=min(8, len(raw))) as pool:
            flags = list(pool.map(lambda n: (n, _entry_looks_listable(root / n)), raw))
        names = [n for n, ok in flags if ok]
    else:
        names = []
    with _browse_names_lock:
        _browse_names_cache[key] = (sig, nlink, list(names))
        if len(_browse_names_cache) > 64:
            for k in list(_browse_names_cache.keys())[:16]:
                _browse_names_cache.pop(k, None)
    return names


def browse_codes(
    *,
    region: str,
    studio: str,
    prefix: str,
    offset: int = 0,
    limit: int = 100,
    q: str | None = None,
) -> dict[str, Any] | None:
    rid = maker_fs.resolve_fs_region(region) or str(region or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    label = scrape_naming.KIND_LABELS[rid]
    st = str(studio or "").strip()
    pref = str(prefix or "").strip()
    if not st or not pref:
        return None
    root = _library_root() / label / st / pref
    if not root.is_dir():
        return {
            "prefix": pref,
            "region": rid,
            "studio": st,
            "total": 0,
            "offset": 0,
            "limit": limit,
            "items": [],
            "source": "library",
        }
    needle = str(q or "").strip().upper()
    # 未分类：同番号若已有作者目录则跳过（片商优先读非未分类）
    skip_codes: set[str] = set()
    if rid == "fc2" and st == "未分类":
        skip_codes = _fc2_codes_outside_uncategorized(root.parent.parent, pref)

    names = _list_prefix_entry_names(root)
    if skip_codes:
        names = [
            n
            for n in names
            if (_norm_entry_code(n) or n.strip().upper()) not in skip_codes
        ]

    off = max(0, int(offset or 0))
    lim = max(1, min(500, int(limit or 100)))

    if not needle:
        # 快路径：只按目录名排序分页，再读当前页摘要（勿对整前缀扫 meta/scrape）
        names_sorted = sorted(names, key=_dir_name_sort_key)
        total = len(names_sorted)
        page_names = names_sorted[off : off + lim]
        items: list[dict[str, Any]] = []
        if page_names:
            with ThreadPoolExecutor(max_workers=min(8, len(page_names))) as pool:
                raw_items = list(
                    pool.map(
                        lambda n: _summary_for_entry(root / n, n),
                        page_names,
                    )
                )
            items = [s for s in raw_items if _summary_is_listable(s)]
        return {
            "prefix": pref,
            "region": rid,
            "studio": st,
            "total": total,
            "offset": off,
            "limit": lim,
            "items": items,
            "updatedAt": _now_iso(),
            "source": "library",
        }

    # 有搜索词：番号名先过滤；未命中的再读摘要做标题/女优匹配
    matched_names: list[str] = []
    maybe_title: list[str] = []
    for name in names:
        code_u = _norm_entry_code(name) or name.strip().upper()
        if needle in code_u:
            matched_names.append(name)
        else:
            maybe_title.append(name)

    extra: list[tuple[str, dict[str, Any]]] = []
    if maybe_title:
        # 限制额外扫描量，避免搜索拖死大前缀
        scan = maybe_title[:2000]

        def _match_one(n: str) -> tuple[str, dict[str, Any]] | None:
            summary = _summary_for_entry(root / n, n)
            if not _summary_is_listable(summary):
                return None
            blob = (
                f"{summary.get('code')} {summary.get('forumTitle') or ''} "
                f"{' '.join(summary.get('forumActors') or [])} "
                f"{' '.join(summary.get('genres') or [])}"
            )
            if needle in blob.upper():
                return (n, summary)
            return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            for hit in pool.map(_match_one, scan):
                if hit:
                    extra.append(hit)

    # 去重保序后按番号排序分页
    seen: set[str] = set()
    ordered_names: list[str] = []
    for n in [*matched_names, *[n for n, _ in extra]]:
        if n in seen:
            continue
        seen.add(n)
        ordered_names.append(n)
    ordered_names.sort(key=_dir_name_sort_key)
    total = len(ordered_names)
    page_names = ordered_names[off : off + lim]
    by_name = {n: s for n, s in extra}
    items = []
    need_read = [n for n in page_names if n not in by_name]
    if need_read:
        with ThreadPoolExecutor(max_workers=min(8, len(need_read))) as pool:
            for n, s in zip(
                need_read,
                pool.map(lambda x: _summary_for_entry(root / x, x), need_read),
            ):
                by_name[n] = s
    for n in page_names:
        s = by_name.get(n) or _empty_code_summary(n)
        if _summary_is_listable(s):
            items.append(s)

    return {
        "prefix": pref,
        "region": rid,
        "studio": st,
        "total": total,
        "offset": off,
        "limit": lim,
        "items": items,
        "updatedAt": _now_iso(),
        "source": "library",
    }


# —— 分区标签 / 系列分类落库（仅 scrape.json；增量复用）——
_FACETS_NAME = ".facets.json"
# v3：entries 按 scrape 签名增量落库；未变复用，变化只改对应番号
_FACETS_VERSION = 3
_MAX_FACET_ITEMS = 800
_MAX_CODES_PER_FACET = 600
_facets_locks_guard = threading.Lock()
_facets_locks: dict[str, threading.Lock] = {}


def _region_facets_path(label: str) -> Path:
    return _library_root() / label / _FACETS_NAME


def _facets_lock_for(rid: str) -> threading.Lock:
    with _facets_locks_guard:
        lock = _facets_locks.get(rid)
        if lock is None:
            lock = threading.Lock()
            _facets_locks[rid] = lock
        return lock


def _label_to_region_id(label: str) -> str | None:
    want = str(label or "").strip()
    if not want:
        return None
    for rid, lab in scrape_naming.KIND_LABELS.items():
        if lab == want:
            return rid
    return None


def _scrape_file_sig(scrape_path: Path) -> str:
    try:
        st = scrape_path.stat()
        return f"{int(st.st_mtime_ns)}:{int(st.st_size)}"
    except OSError:
        return ""


def _facet_entry_key(studio: str, prefix: str, code: str) -> str:
    return f"{studio}|{prefix}|{str(code or '').strip().upper()}"


def _entry_facet_bits(entry_dir: Path) -> tuple[list[str], str] | None:
    """只读落盘刮削 scrape.json：标签 + 系列。无刮削则跳过。"""
    scrape_path = entry_dir / SCRAPE_META_FILE
    if not scrape_path.is_file():
        return None
    scrape = _read_json_dict(scrape_path)
    if not scrape:
        return None

    raw = scrape.get("genres") if isinstance(scrape.get("genres"), list) else None
    if not raw:
        raw = scrape.get("tags") if isinstance(scrape.get("tags"), list) else None
    tags = [str(t).strip() for t in (raw or []) if str(t).strip()]
    series = str(scrape.get("series") or "").strip()
    if not tags and not series:
        return None
    return tags, series


def _facet_bucket_add(
    bag: dict[str, dict[str, Any]],
    name: str,
    ref: dict[str, str],
) -> None:
    key = str(name or "").strip()
    if not key:
        return
    slot = bag.get(key)
    if slot is None:
        slot = {"name": key, "count": 0, "refs": [], "_seen": set()}
        bag[key] = slot
    slot["count"] = int(slot["count"] or 0) + 1
    code = str(ref.get("code") or "").strip().upper()
    if not code:
        return
    seen: set[str] = slot["_seen"]
    if code in seen or len(slot["refs"]) >= _MAX_CODES_PER_FACET:
        return
    seen.add(code)
    slot["refs"].append(ref)


def _finalize_facet_bag(
    bag: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    rows = sorted(
        (
            {"name": str(v["name"]), "count": int(v["count"] or 0)}
            for v in bag.values()
            if int(v.get("count") or 0) > 0
        ),
        key=lambda x: (-int(x["count"]), str(x["name"])),
    )[:_MAX_FACET_ITEMS]
    index: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        name = str(row["name"])
        refs = list((bag.get(name) or {}).get("refs") or [])
        refs.sort(key=lambda r: _code_sort_key({"code": r.get("code")}))
        index[name] = refs
    return rows, index


def _aggregates_from_facet_entries(
    entries: dict[str, dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, str]]],
    list[dict[str, Any]],
    dict[str, list[dict[str, str]]],
]:
    tag_bag: dict[str, dict[str, Any]] = {}
    series_bag: dict[str, dict[str, Any]] = {}
    for ent in entries.values():
        if not isinstance(ent, dict):
            continue
        studio = str(ent.get("studio") or "").strip()
        pref = str(ent.get("prefix") or "").strip()
        code = str(ent.get("code") or "").strip().upper()
        if not studio or not pref or not code:
            continue
        ref = {"studio": studio, "prefix": pref, "code": code}
        for t in ent.get("tags") or []:
            _facet_bucket_add(tag_bag, str(t), ref)
        series = str(ent.get("series") or "").strip()
        if series:
            _facet_bucket_add(series_bag, series, ref)
    tags, tag_index = _finalize_facet_bag(tag_bag)
    series, series_index = _finalize_facet_bag(series_bag)
    return tags, tag_index, series, series_index


def _write_facets_payload(label: str, payload: dict[str, Any]) -> None:
    path = _region_facets_path(label)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # entries 内 _seen 不应落盘
        path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("write facets %s: %s", label, e)


def _load_facets_payload(label: str) -> dict[str, Any] | None:
    path = _region_facets_path(label)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception:
        return None


def _iter_scrape_entries(root: Path) -> list[tuple[str, str, str, Path, str]]:
    """列出 (studio, prefix, code, scrape_path, sig)。"""
    out: list[tuple[str, str, str, Path, str]] = []
    if not root.is_dir():
        return out
    for studio in _safe_list_dirs(root):
        if studio.startswith("."):
            continue
        for pref in _safe_list_dirs(root / studio):
            if pref.startswith("."):
                continue
            for name in _safe_list_dirs(root / studio / pref):
                scrape_path = root / studio / pref / name / SCRAPE_META_FILE
                if not scrape_path.is_file():
                    continue
                code = str(name or "").strip().upper()
                if not code:
                    continue
                sig = _scrape_file_sig(scrape_path)
                if not sig:
                    continue
                out.append((studio, pref, code, scrape_path, sig))
    return out


def _make_facet_entry(
    *,
    studio: str,
    prefix: str,
    code: str,
    sig: str,
    tags: list[str],
    series: str,
) -> dict[str, Any]:
    return {
        "sig": sig,
        "studio": studio,
        "prefix": prefix,
        "code": code,
        "tags": list(tags or []),
        "series": str(series or "").strip(),
    }


def sync_region_facets(
    region_id: str,
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    """增量同步标签/系列落库。

    - scrape.json 签名未变 → 复用 entries
    - 新增/变更 → 只读该番号 scrape.json
    - 删除刮削 → 从 entries 移除
    """
    rid = maker_fs.resolve_fs_region(region_id) or str(region_id or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    label = scrape_naming.KIND_LABELS[rid]
    root = _library_root() / label
    lock = _facets_lock_for(rid)
    with lock:
        prev = None if force else _load_facets_payload(label)
        entries: dict[str, dict[str, Any]] = {}
        if (
            isinstance(prev, dict)
            and int(prev.get("version") or 0) >= _FACETS_VERSION
            and isinstance(prev.get("entries"), dict)
        ):
            for k, v in prev["entries"].items():
                if isinstance(v, dict) and str(v.get("sig") or ""):
                    entries[str(k)] = dict(v)

        discovered = _iter_scrape_entries(root)
        live_keys: set[str] = set()
        changed: list[tuple[str, str, str, Path, str]] = []
        reused = 0
        for studio, pref, code, scrape_path, sig in discovered:
            key = _facet_entry_key(studio, pref, code)
            live_keys.add(key)
            old = entries.get(key)
            if (
                not force
                and isinstance(old, dict)
                and str(old.get("sig") or "") == sig
            ):
                reused += 1
                continue
            changed.append((studio, pref, code, scrape_path, sig))

        removed = 0
        for key in list(entries.keys()):
            if key not in live_keys:
                entries.pop(key, None)
                removed += 1

        updated = 0
        if changed:
            workers = max(4, min(16, (os.cpu_count() or 4) * 2))

            def _read_one(
                job: tuple[str, str, str, Path, str],
            ) -> tuple[str, dict[str, Any] | None]:
                studio, pref, code, scrape_path, sig = job
                key = _facet_entry_key(studio, pref, code)
                bits = _entry_facet_bits(scrape_path.parent)
                if not bits:
                    return key, None
                tags, series = bits
                return key, _make_facet_entry(
                    studio=studio,
                    prefix=pref,
                    code=code,
                    sig=sig,
                    tags=tags,
                    series=series,
                )

            with ThreadPoolExecutor(max_workers=workers) as pool:
                for key, ent in pool.map(_read_one, changed, chunksize=32):
                    if ent is None:
                        if key in entries:
                            entries.pop(key, None)
                            updated += 1
                        continue
                    entries[key] = ent
                    updated += 1

        tags, tag_index, series, series_index = _aggregates_from_facet_entries(entries)
        payload = {
            "version": _FACETS_VERSION,
            "id": rid,
            "label": label,
            "updatedAt": _now_iso(),
            "scanned": len(entries),
            "reused": reused,
            "updated": updated,
            "removed": removed,
            "entries": entries,
            "tags": tags,
            "series": series,
            "tagIndex": tag_index,
            "seriesIndex": series_index,
            "source": "scrape",
        }
        _write_facets_payload(label, payload)
        return payload


def build_region_facets(region_id: str) -> dict[str, Any] | None:
    """全量重建（force）。"""
    return sync_region_facets(region_id, force=True)


def upsert_region_facet_entry(
    entry_dir: Path | str,
    *,
    region: str | None = None,
    studio: str | None = None,
    prefix: str | None = None,
    code: str | None = None,
) -> bool:
    """刮削写入 scrape.json 后增量更新单条分类落库。"""
    path = Path(entry_dir)
    scrape_path = path / SCRAPE_META_FILE
    rid = maker_fs.resolve_fs_region(region) if region else None
    st = str(studio or "").strip()
    pref = str(prefix or "").strip()
    c = str(code or path.name or "").strip().upper()

    if not rid or not st or not pref:
        try:
            lib = _library_root().resolve()
            rel = path.resolve().relative_to(lib)
            parts = rel.parts
            if len(parts) >= 4:
                label0, st2, pref2, code2 = parts[0], parts[1], parts[2], parts[3]
                rid = rid or _label_to_region_id(str(label0))
                st = st or str(st2)
                pref = pref or str(pref2)
                c = c or str(code2).strip().upper()
        except Exception:
            pass
    if not rid or rid not in scrape_naming.KIND_LABELS or not st or not pref or not c:
        return False

    label = scrape_naming.KIND_LABELS[rid]
    # 无 v3 entries 底库时先增量扫一遍（不持单条锁，避免死锁）
    prev0 = _load_facets_payload(label)
    if (
        not isinstance(prev0, dict)
        or int(prev0.get("version") or 0) < _FACETS_VERSION
        or not isinstance(prev0.get("entries"), dict)
    ):
        sync_region_facets(rid, force=False)

    lock = _facets_lock_for(rid)
    with lock:
        prev = _load_facets_payload(label) or {
            "version": _FACETS_VERSION,
            "id": rid,
            "label": label,
            "entries": {},
        }
        entries = (
            dict(prev.get("entries") or {})
            if isinstance(prev.get("entries"), dict)
            else {}
        )
        key = _facet_entry_key(st, pref, c)

        if not scrape_path.is_file():
            if key not in entries:
                return False
            entries.pop(key, None)
        else:
            sig = _scrape_file_sig(scrape_path)
            old = entries.get(key)
            if isinstance(old, dict) and str(old.get("sig") or "") == sig:
                return True
            bits = _entry_facet_bits(path)
            if not bits:
                entries.pop(key, None)
            else:
                tags, series = bits
                entries[key] = _make_facet_entry(
                    studio=st,
                    prefix=pref,
                    code=c,
                    sig=sig,
                    tags=tags,
                    series=series,
                )

        tags, tag_index, series, series_index = _aggregates_from_facet_entries(entries)
        payload = {
            "version": _FACETS_VERSION,
            "id": rid,
            "label": label,
            "updatedAt": _now_iso(),
            "scanned": len(entries),
            "entries": entries,
            "tags": tags,
            "series": series,
            "tagIndex": tag_index,
            "seriesIndex": series_index,
            "source": "scrape",
        }
        _write_facets_payload(label, payload)
        return True


def browse_region_facets(
    region_id: str,
    *,
    rebuild: bool = False,
    sync: bool = False,
) -> dict[str, Any] | None:
    """读标签/系列落库。

    默认只读 .facets.json（快）；sync/rebuild 时才扫盘更新。
    """
    rid = maker_fs.resolve_fs_region(region_id) or str(region_id or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    label = scrape_naming.KIND_LABELS[rid]

    built: dict[str, Any] | None = None
    if rebuild or sync:
        built = sync_region_facets(rid, force=rebuild)
    else:
        raw = _load_facets_payload(label)
        if (
            isinstance(raw, dict)
            and int(raw.get("version") or 0) >= _FACETS_VERSION
            and isinstance(raw.get("tags"), list)
            and isinstance(raw.get("series"), list)
        ):
            built = raw

    if not built:
        return {
            "id": rid,
            "label": label,
            "updatedAt": None,
            "scanned": 0,
            "reused": 0,
            "updated": 0,
            "tags": [],
            "series": [],
            "source": "scrape",
            "stale": True,
            "empty": True,
        }

    return {
        "id": rid,
        "label": label,
        "updatedAt": built.get("updatedAt"),
        "scanned": int(built.get("scanned") or 0),
        "reused": int(built.get("reused") or 0),
        "updated": int(built.get("updated") or 0),
        "tags": built.get("tags") or [],
        "series": built.get("series") or [],
        "source": "scrape",
        "stale": False,
        "empty": not (built.get("tags") or built.get("series")),
    }


def _load_region_facet_index(rid: str) -> dict[str, Any] | None:
    """点进标签/系列时只用已落库索引，不自动扫盘。"""
    label = scrape_naming.KIND_LABELS.get(rid) or ""
    if not label:
        return None
    raw = _load_facets_payload(label)
    if (
        isinstance(raw, dict)
        and int(raw.get("version") or 0) >= _FACETS_VERSION
    ):
        return raw
    return None


def browse_facet_codes(
    *,
    region: str,
    kind: str,
    value: str,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any] | None:
    """按标签 / 系列取番号列表（含封面摘要）。"""
    rid = maker_fs.resolve_fs_region(region) or str(region or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    label = scrape_naming.KIND_LABELS[rid]
    k = str(kind or "").strip().lower()
    if k in {"tag", "tags", "genre", "genres"}:
        index_key = "tagIndex"
        kind_out = "tag"
    elif k in {"series", "series_name"}:
        index_key = "seriesIndex"
        kind_out = "series"
    else:
        return None
    want = str(value or "").strip()
    if not want:
        return {
            "region": rid,
            "kind": kind_out,
            "value": want,
            "total": 0,
            "offset": 0,
            "limit": limit,
            "items": [],
            "source": "library",
        }

    payload = _load_region_facet_index(rid) or {}
    index = payload.get(index_key) if isinstance(payload.get(index_key), dict) else {}
    refs = list(index.get(want) or [])
    if not refs:
        # 大小写不敏感兜底
        want_cf = want.casefold()
        for name, rows in index.items():
            if str(name).casefold() == want_cf:
                refs = list(rows or [])
                want = str(name)
                break

    total = len(refs)
    # 若索引截断，尽量用 facets 列表里的 count
    facet_rows = payload.get("tags" if kind_out == "tag" else "series") or []
    for row in facet_rows:
        if isinstance(row, dict) and str(row.get("name") or "") == want:
            total = max(total, int(row.get("count") or total))
            break

    off = max(0, int(offset or 0))
    lim = max(1, min(500, int(limit or 100)))
    page_refs = refs[off : off + lim]
    root = _library_root() / label
    items: list[dict[str, Any]] = []
    for ref in page_refs:
        studio = str(ref.get("studio") or "").strip()
        pref = str(ref.get("prefix") or "").strip()
        code = str(ref.get("code") or "").strip().upper()
        if not studio or not pref or not code:
            continue
        summary = _read_meta_summary(root / studio / pref / code)
        if not summary:
            summary = {
                "code": code,
                "coverUrl": None,
                "coverUrls": [],
                "forumTitle": None,
                "forumActors": None,
                "genres": None,
                "posterLocal": None,
                "scraped": False,
            }
        summary = {
            **summary,
            "studio": studio,
            "prefix": pref,
        }
        if _summary_is_listable(summary):
            items.append(summary)

    return {
        "region": rid,
        "kind": kind_out,
        "value": want,
        "total": total,
        "offset": off,
        "limit": lim,
        "items": items,
        "updatedAt": _now_iso(),
        "source": "library",
    }
