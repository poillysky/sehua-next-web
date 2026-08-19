"""从 maker-fs 索引物化到 library，并提供片商目录浏览。

library 根下三层：
  本地索引/  — 「同步本地片库」写入；每番号仅 {番号}.strm
  片商目录/  — mdc-ng 刮削落盘；片商页读此层
  封面库/    — 片商/前缀卡片用，每目录固定 1 张最新海报
    {区}/prefixes/{厂牌}/{前缀}/  — 前缀卡（新番号入盘则同步）
    {区}/makers/{厂牌}/           — 厂牌卡（最新前缀的最新番号）

路径模板与刮削命名一致：{category}/{studio}/{series_name}/{number}
  本地索引：…/{number}.strm（文件，非目录）
  片商目录：…/{number}/scrape.json …

同步：本地索引与 maker-fs 严格一致（全区同一逻辑，含 FC2）：
  仅保留索引内番号对应的 {番号}.strm，其余文件/目录/文件夹一律删除。
片商目录（刮削落盘）与本地索引分离；片商浏览仍可读片商目录。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import unicodedata
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import maker_fs, scrape_export, scrape_naming
from .db import ROOT
from .scrape_forum_title import is_likely_chinese
from .scrape_metadata_optimize import normalize_actor_names

log = logging.getLogger("nextweb.library")

LIBRARY_INDEX_DIR = "本地索引"
LIBRARY_MAKERS_DIR = "片商目录"
LIBRARY_COVERS_DIR = "封面库"
INDEX_STRM_EXT = ".strm"
COVER_URL_NAME = "封面.url"
INDEX_META_FILE = "meta.json"
SCRAPE_META_FILE = "scrape.json"
FC2_KEEP_FILE = ".fc2-keep.json"
_LIBRARY_RESERVED_TOP = frozenset(
    {LIBRARY_INDEX_DIR, LIBRARY_MAKERS_DIR, LIBRARY_COVERS_DIR}
)
_TILE_COVER_N = 1
_TILE_PACK_TTL_S = 24 * 3600
_TILE_PACK_EMPTY_TTL_S = 2 * 60
_TILE_PACK_SERIES_CAP = 4
_TILE_PACK_PROBE_CAP = 80
_TILE_PACK_VERSION = 2
_TILE_THUMB_MAX = 420
_pack_locks_guard = threading.Lock()
_pack_locks: dict[str, threading.Lock] = {}
_pack_mem_lock = threading.Lock()
_pack_mem: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_POSTER_NAMES = ("poster.jpg", "poster.jpeg", "poster.png", "poster.webp")
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


def library_base() -> Path:
    raw = scrape_export.scrape_settings()["libraryRoot"]
    lib = Path(str(raw))
    if not lib.is_absolute():
        lib = (ROOT / lib).resolve()
    else:
        lib = lib.resolve()
    return lib


def library_index_root() -> Path:
    root = library_base() / LIBRARY_INDEX_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def makers_library_root() -> Path:
    root = library_base() / LIBRARY_MAKERS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_library_media_path(rel: str) -> Path | None:
    """解析 library 内封面/海报相对路径（兼容 片商目录 前缀可有可无、library 独立挂载）。"""
    raw = str(rel or "").replace("\\", "/").strip().lstrip("/")
    if not raw or ".." in Path(raw).parts:
        return None
    base = library_base().resolve()
    makers = makers_library_root().resolve()
    variants = [raw]
    prefix = f"{LIBRARY_MAKERS_DIR}/"
    if raw.startswith(prefix):
        variants.append(raw[len(prefix) :])
    roots = [makers, base]
    seen: set[str] = set()
    for root in roots:
        for variant in variants:
            try:
                target = (root / variant).resolve()
            except OSError:
                continue
            key = str(target)
            if key in seen:
                continue
            seen.add(key)
            try:
                target.relative_to(base)
            except ValueError:
                continue
            if target.is_file():
                return target
    return None


def _merge_dir_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            if target.is_dir():
                _merge_dir_tree(item, target)
                try:
                    item.rmdir()
                except OSError:
                    pass
            else:
                shutil.move(str(item), str(target))
        else:
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
            shutil.move(str(item), str(target))


def migrate_library_layout() -> dict[str, Any]:
    """整理 library 布局：根下仅「本地索引 / 片商目录 / 封面库」，片商目录下保证七区一级目录。"""
    base = library_base()
    makers = makers_library_root()
    index = library_index_root()
    labels = [scrape_naming.KIND_LABELS[kid] for kid in scrape_naming.KIND_ORDER]
    label_set = set(labels)
    moved: list[str] = []
    merged: list[str] = []
    created: list[str] = []
    skipped: list[str] = []

    try:
        children = list(base.iterdir())
    except OSError:
        children = []

    for p in children:
        if not p.is_dir() or p.name.startswith("."):
            continue
        if p.name in _LIBRARY_RESERVED_TOP:
            continue
        # 仅迁移旧七区目录；其它顶层目录不动
        if p.name not in label_set:
            continue
        dst = makers / p.name
        try:
            if not dst.exists():
                shutil.move(str(p), str(dst))
                moved.append(p.name)
            else:
                _merge_dir_tree(p, dst)
                try:
                    p.rmdir()
                except OSError:
                    skipped.append(p.name)
                else:
                    merged.append(p.name)
        except OSError as e:
            log.warning("migrate library %s -> %s failed: %s", p, dst, e)
            skipped.append(p.name)

    for name in labels:
        dest = makers / name
        if dest.is_dir():
            continue
        try:
            dest.mkdir(parents=True, exist_ok=True)
            created.append(name)
        except OSError as e:
            log.warning("ensure maker region dir %s failed: %s", dest, e)
            skipped.append(name)

    return {
        "libraryRoot": str(base),
        "indexRoot": str(index),
        "makersRoot": str(makers),
        "moved": moved,
        "merged": merged,
        "created": created,
        "skipped": skipped,
        "regions": labels,
    }


def _library_root() -> Path:
    """兼容旧调用：library 根（data/library）。"""
    return library_base()


def _makers_root_for_browse() -> Path:
    """片商页只读「片商目录」，目录结构：分区/厂牌/前缀/番号。"""
    return makers_library_root()


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
    """片商目录浏览/FC2 未分类跳过（仅片商目录，不参与本地索引同步）。"""
    rid = maker_fs.resolve_fs_region(region) or str(region or "").strip()
    bn = str(maker or "").strip()
    if rid != "fc2":
        return bn or "未分组"
    if bn and bn not in {"自定义", "未分组", "未知"}:
        s = "".join(ch for ch in bn.lower() if ch not in " ·-_/=")
        if s in {"fc2", "fc2ppv", "fc2ppvfc2"} or s.startswith("fc2fc2"):
            return "未分类"
        if s == "fc2" or s == "fc2ppv":
            return "未分类"
        return bn
    return "未分类"


def _sync_maker(maker: str) -> str:
    """本地索引同步：全区统一，直接使用索引里的厂牌/作者名。"""
    bn = str(maker or "").strip()
    return bn or "未分组"


def _resolve_index_strm_path(
    library_index: Path,
    naming: dict[str, Any],
    *,
    code: str,
    meta: dict[str, Any],
    target: dict[str, Any],
    category: str,
    kind: str | None = None,
) -> Path:
    entry_dir = scrape_naming.resolve_entry_dir(
        library_index,
        naming,
        code=code,
        meta=meta,
        target=target,
        category=category,
        kind=kind,
    )
    return entry_dir.parent / f"{entry_dir.name}{INDEX_STRM_EXT}"


def _write_entry(
    library: Path,
    naming: dict[str, Any],
    target: dict[str, Any],
    *,
    actor_map_enable: bool | None = None,
    actor_map_lang: str | None = None,
) -> str:
    """本地索引：仅写入 {番号}.strm，不生成 meta.json / 封面.url。"""
    del actor_map_enable, actor_map_lang
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
    maker = _sync_maker(str(target.get("maker") or ""))
    target = {**target, "maker": maker, "prefix": prefix, "code": code}
    kind_id = scrape_naming.resolve_kind(region=rid, code=code)
    meta = {
        "code": code,
        "prefix": prefix,
        "maker": maker,
        "studio": maker,
        "region": rid,
    }
    try:
        strm_path = _resolve_index_strm_path(
            library,
            naming,
            code=code,
            meta=meta,
            target=target,
            category=str(label),
            kind=kind_id,
        )
        legacy_dir = scrape_naming.resolve_entry_dir(
            library,
            naming,
            code=code,
            meta=meta,
            target=target,
            category=str(label),
            kind=kind_id,
        )
    except Exception:
        return "error"

    body = f"{code}\n"
    strm_path.parent.mkdir(parents=True, exist_ok=True)
    if strm_path.is_file():
        try:
            prev = strm_path.read_text(encoding="utf-8")
            if _norm_text_newlines(prev).strip() == code:
                return "skipped"
        except Exception:
            pass
        strm_path.write_text(body, encoding="utf-8", newline="\n")
        wrote = "updated"
    else:
        strm_path.write_text(body, encoding="utf-8", newline="\n")
        wrote = "written"

    # 本地索引只允许 .strm；旧版番号目录一律删除
    if legacy_dir.is_dir():
        try:
            shutil.rmtree(legacy_dir)
        except OSError:
            pass
    return wrote


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
    lib = library or makers_library_root()
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
    """返回 (expected_codes, expected_strm_path_keys)。全区同一规则。"""
    codes: set[str] = set()
    expected_strm: set[str] = set()
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
        maker = _sync_maker(str(t.get("maker") or ""))
        meta = {
            "code": code,
            "prefix": prefix,
            "maker": maker,
            "studio": maker,
            "region": rid,
        }
        try:
            sp = _resolve_index_strm_path(
                library,
                naming,
                code=code,
                meta=meta,
                target={**t, "maker": maker, "prefix": prefix, "code": code},
                category=str(label),
                kind=kind_id,
            )
            expected_strm.add(_path_key(sp))
        except Exception:
            pass
        if on_progress and (i == 1 or i % 2048 == 0 or i >= total):
            on_progress(i, total)
    return codes, expected_strm


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
    region: str | None = None,
    on_progress: Any | None = None,
) -> dict[str, int]:
    """本地索引与 maker-fs 严格对齐：仅保留预期 .strm，其余文件/目录全部删除。"""

    def _build_prog(done: int, total: int) -> None:
        if on_progress:
            on_progress("build", done, total, 0, 0)

    _codes, expected_strm = _expected_paths_and_codes(
        library, naming, targets, on_progress=_build_prog
    )

    prune_root = library
    region_key = str(region or "").strip()
    if region_key:
        rid = maker_fs.resolve_fs_region(region_key) or region_key
        label = scrape_naming.KIND_LABELS.get(rid)
        if label:
            prune_root = library / label

    removed = 0
    kept = 0
    scanned = 0

    def _rm_file(p: Path) -> None:
        nonlocal removed
        try:
            parent = p.parent
            p.unlink(missing_ok=True)
            removed += 1
            _prune_empty_parents(parent, library)
        except OSError as e:
            log.warning("prune remove file %s failed: %s", p, e)

    def _rm_tree(p: Path) -> None:
        nonlocal removed
        try:
            parent = p.parent
            shutil.rmtree(p)
            removed += 1
            _prune_empty_parents(parent, library)
        except OSError as e:
            log.warning("prune remove tree %s failed: %s", p, e)

    if not prune_root.is_dir():
        return {"removed": 0, "kept": 0, "scanned": 0}

    try:
        all_paths = list(prune_root.rglob("*"))
    except OSError:
        all_paths = []

    for p in all_paths:
        if not p.is_file():
            continue
        scanned += 1
        key = _path_key(p)
        if key in expected_strm and p.suffix.lower() == INDEX_STRM_EXT:
            kept += 1
        else:
            _rm_file(p)
        if on_progress and scanned % 512 == 0:
            on_progress("scan", scanned, len(targets), kept, removed)

    try:
        all_dirs = sorted(
            [p for p in prune_root.rglob("*") if p.is_dir()],
            key=lambda x: len(x.parts),
            reverse=True,
        )
    except OSError:
        all_dirs = []

    for d in all_dirs:
        scanned += 1
        if _is_entry_dir(d):
            _rm_tree(d)
            continue
        try:
            next(d.iterdir())
        except StopIteration:
            try:
                d.rmdir()
                removed += 1
            except OSError:
                pass
        except OSError:
            pass

    if on_progress:
        on_progress("scan", scanned, len(targets), kept, removed)
    return {"removed": removed, "kept": kept, "scanned": scanned}


def _collect_targets(region: str | None = None) -> list[dict[str, Any]]:
    """收集待物化目标：仅 maker-fs 索引 covers 内真实条目，不含空洞补全。"""
    return scrape_export.collect_targets(
        region=region or None,
        rekey=False,
        include_fill=False,
    )


def _dedupe_targets_by_entry_path(targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一落盘目录只保留信息最全的一条（保留供测试/特殊调用；热路径默认不用）。"""
    naming = scrape_naming.fixed_naming()
    library = library_index_root()
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
        maker = _sync_maker(str(t.get("maker") or ""))
        label = scrape_naming.KIND_LABELS.get(
            scrape_naming.resolve_kind(region=rid, code=code), ""
        ) or maker_fs.REGION_META.get(rid, {}).get("label") or rid
        kind_id = scrape_naming.resolve_kind(region=rid, code=code)
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
            d = _resolve_index_strm_path(
                library,
                naming,
                code=code,
                meta=meta,
                target={**t, "maker": maker, "prefix": prefix, "code": code},
                category=str(label),
                kind=kind_id,
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
        migrate_library_layout()
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

        library = library_index_root()
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
                library,
                naming,
                targets,
                region=region_key or None,
                on_progress=_prune_prog,
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


def _xml_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return str(el.text or "").strip()


# mdc-ng 常把片商/系列/女优再写进 <genre>/<tag>，例如「发行: S1 NO.1 STYLE」
_TAG_META_KEYS = frozenset(
    x.casefold()
    for x in (
        "系列",
        "片商",
        "发行",
        "發行",
        "发行商",
        "發行商",
        "发行日期",
        "發行日期",
        "女优",
        "女優",
        "女优名",
        "女優名",
        "演员",
        "演員",
        "制作",
        "製作",
        "导演",
        "導演",
        "出品",
        "工作室",
        "厂商",
        "廠商",
        "studio",
        "maker",
        "publisher",
        "label",
        "series",
        "set",
        "actress",
        "actor",
        "director",
        "番号",
        "id",
        "num",
    )
)
_SERIES_META_KEYS = frozenset({"系列", "series", "set"})
_TAG_META_SPLIT_RE = re.compile(r"^(.{1,16}?)[:：]\s*(.+)$")
_HIRA_RE = re.compile(r"[\u3040-\u309f]")
_FACET_PUNCT_RE = re.compile(r"[・·‧･•∙⋅\s　…]+")


def _fold_facet_name(s: str) -> str:
    """比较用：统一中点/空白，避免系列名「·」和「・」对不上。"""
    t = unicodedata.normalize("NFKC", str(s or "").strip()).casefold()
    t = _FACET_PUNCT_RE.sub("", t)
    return t


def _split_tag_meta_field(raw: str) -> tuple[str, str] | None:
    """「系列: 新人NO.1 STYLE」→ ('系列', '新人NO.1 STYLE')；普通标签返回 None。"""
    s = str(raw or "").strip()
    if not s:
        return None
    m = _TAG_META_SPLIT_RE.match(s)
    if not m:
        return None
    key = m.group(1).strip().casefold()
    val = m.group(2).strip()
    if not val or key not in _TAG_META_KEYS:
        return None
    return key, val


def _sanitize_genre_tags(
    tags: list[str] | None,
    *,
    actors: list[str] | None = None,
    series: list[str] | None = None,
    studio: str = "",
    code: str = "",
    prefix: str = "",
) -> tuple[list[str], list[str]]:
    """去掉混进标签的系列、女优、片商、前缀。返回 (干净标签, 从「系列:」拆出的系列)。"""
    actor_cf = {_fold_facet_name(a) for a in (actors or []) if str(a).strip()}
    actor_cf.discard("")
    series_cf = {_fold_facet_name(s) for s in (series or []) if str(s).strip()}
    series_cf.discard("")
    studio_cf = _fold_facet_name(studio)
    code_u = str(code or "").strip().upper().replace("_", "-")
    prefix_cf = _fold_facet_name(prefix)
    if not prefix_cf and code_u:
        prefix_cf = _fold_facet_name(
            code_u.split("-", 1)[0] if "-" in code_u else code_u
        )

    extra_series: list[str] = []
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        t = str(raw or "").strip()
        if not t:
            continue
        split = _split_tag_meta_field(t)
        if split is not None:
            key, val = split
            if key in _SERIES_META_KEYS:
                extra_series.append(val)
            continue
        folded = _fold_facet_name(t)
        if not folded or folded in seen:
            continue
        if folded in actor_cf or folded in series_cf:
            continue
        if studio_cf and folded == studio_cf:
            continue
        if prefix_cf and folded == prefix_cf:
            continue
        if code_u and t.upper().replace("_", "-") == code_u:
            continue
        # 平假名长句基本是系列名被写进 genre，不是标签
        if len(folded) >= 10 and _HIRA_RE.search(t):
            extra_series.append(t)
            continue
        seen.add(folded)
        out.append(t)
    return out, extra_series


def _normalize_plot_text(raw: str) -> str:
    """mdc-ng 简介常含 <br>。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _find_nfo_file(entry_dir: Path) -> Path | None:
    direct = entry_dir / f"{entry_dir.name}.nfo"
    if direct.is_file():
        return direct
    try:
        for p in entry_dir.iterdir():
            if p.is_file() and p.suffix.lower() == ".nfo":
                return p
    except OSError:
        return None
    return None


def _read_nfo(entry_dir: Path) -> dict[str, Any]:
    """解析 mdc-ng / Kodi NFO。"""
    path = _find_nfo_file(entry_dir)
    if path is None:
        return {}
    try:
        text = path.read_bytes().decode("utf-8-sig")
        root = ET.fromstring(text)
    except Exception:
        return {}
    actors: list[str] = []
    for node in root.findall("actor"):
        name = _xml_text(node.find("name"))
        if name:
            actors.append(name)
    raw_genres = [_xml_text(g) for g in root.findall("genre") if _xml_text(g)]
    raw_tags = [_xml_text(t) for t in root.findall("tag") if _xml_text(t)]
    merged: list[str] = []
    seen_g: set[str] = set()
    for t in raw_genres + raw_tags:
        cf = t.casefold()
        if cf in seen_g:
            continue
        seen_g.add(cf)
        merged.append(t)
    studio = (
        _xml_text(root.find("studio"))
        or _xml_text(root.find("maker"))
        or _xml_text(root.find("publisher"))
        or _xml_text(root.find("label"))
    )
    title = _xml_text(root.find("title"))
    original = _xml_text(root.find("originaltitle"))
    series = _xml_text(root.find("set/name")) or _xml_text(root.find("set"))
    plot = _normalize_plot_text(
        _xml_text(root.find("plot"))
        or _xml_text(root.find("outline"))
        or _xml_text(root.find("originalplot"))
    )
    code = _xml_text(root.find("num")) or entry_dir.name
    genres, extra_series = _sanitize_genre_tags(
        merged,
        actors=actors,
        series=[series] if series else [],
        studio=studio,
        code=code,
    )
    if extra_series and not series:
        series = extra_series[0]
    return {
        "code": code,
        "title": title,
        "originalTitle": original,
        "studio": studio,
        "actors": actors,
        "genres": genres,
        "series": series,
        "plot": plot,
        "cover": _xml_text(root.find("cover")),
    }


def _is_code_entry_dir(path: Path) -> bool:
    """番号目录：含 poster / nfo / strm（mdc-ng 落盘）。"""
    if not path.is_dir() or path.name.startswith("."):
        return False
    try:
        with os.scandir(path) as it:
            for e in it:
                if not e.is_file(follow_symlinks=False):
                    continue
                name = e.name.lower()
                if name in _POSTER_NAMES or name.startswith("poster."):
                    return True
                if name.endswith(".nfo") or name.endswith(".strm"):
                    return True
                if name in {"thumb.jpg", "fanart.jpg"}:
                    return True
    except OSError:
        return False
    return False


def _list_code_entry_dirs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    out: list[str] = []
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False) and _is_code_entry_dir(
                        Path(e.path)
                    ):
                        out.append(e.name)
                except OSError:
                    continue
        out.sort(key=str.lower)
    except OSError:
        return []
    return out


def _studio_from_prefix_folder(prefix_dir: Path) -> str:
    for name in _list_code_entry_dirs(prefix_dir)[:8]:
        studio = str(_read_nfo(prefix_dir / name).get("studio") or "").strip()
        if studio:
            return studio
    return prefix_dir.name


def _resolve_prefix_dir(
    region_root: Path,
    studio: str,
    prefix: str,
) -> Path | None:
    """兼容 分区/厂牌/前缀/番号 与 mdc-ng 分区/前缀/番号。"""
    st = str(studio or "").strip()
    pref = str(prefix or "").strip()
    cands: list[Path] = []
    if st and pref:
        cands.append(region_root / st / pref)
    if pref:
        cands.append(region_root / pref)
    if st:
        cands.append(region_root / st)
    seen: set[str] = set()
    for cand in cands:
        key = str(cand)
        if key in seen:
            continue
        seen.add(key)
        if cand.is_dir() and _list_code_entry_dirs(cand):
            return cand
    return None


_CATALOG_NAME = ".catalog.json"


def _region_catalog_path(label: str) -> Path:
    return _makers_root_for_browse() / label / _CATALOG_NAME


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


_CATALOG_SEARCH_VERSION = 3
_MAX_PREFIX_ACTORS = 80
_MAX_PREFIX_TAGS = 80
_MAX_PREFIX_SERIES = 80


def _uniq_cap(items: list[str] | set[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        s = str(raw or "").strip()
        if not s:
            continue
        key = _fold_facet_name(s) or s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _entry_search_bits(entry_dir: Path) -> tuple[list[str], list[str], list[str]]:
    """从 nfo / scrape.json / meta.json 抽女优、标签、系列。"""
    nfo = _read_nfo(entry_dir)
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

    def _series(src: dict[str, Any]) -> list[str]:
        s = str(src.get("series") or src.get("set") or "").strip()
        return [s] if s else []

    actors = _actors(nfo) or _actors(scrape) or _actors(index)
    tags = _tags(nfo) or _tags(scrape) or _tags(index)
    series = _series(nfo) or _series(scrape) or _series(index)
    studio = (
        str(nfo.get("studio") or "").strip()
        or str(scrape.get("studio") or scrape.get("maker") or "").strip()
        or str(index.get("studio") or "").strip()
    )
    code = str(nfo.get("code") or scrape.get("code") or entry_dir.name).strip()
    tags, extra_s = _sanitize_genre_tags(
        tags,
        actors=actors,
        series=series,
        studio=studio,
        code=code,
    )
    series = _uniq_cap([*series, *extra_s], _MAX_PREFIX_SERIES)
    return actors, tags, series


def _prefix_search_from_disk(
    root: Path,
    maker: str,
    prefix: str,
) -> tuple[list[str], list[str], list[str]]:
    path = _resolve_prefix_dir(root, maker, prefix)
    if path is None:
        return [], [], []
    actors: list[str] = []
    tags: list[str] = []
    series: list[str] = []
    seen_a: set[str] = set()
    seen_t: set[str] = set()
    seen_s: set[str] = set()
    for name in _list_code_entry_dirs(path):
        a_list, t_list, s_list = _entry_search_bits(path / name)
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
        for s in s_list:
            k = s.casefold()
            if k in seen_s:
                continue
            seen_s.add(k)
            series.append(s)
        if (
            len(actors) >= _MAX_PREFIX_ACTORS
            and len(tags) >= _MAX_PREFIX_TAGS
            and len(series) >= _MAX_PREFIX_SERIES
        ):
            break
    return (
        actors[:_MAX_PREFIX_ACTORS],
        tags[:_MAX_PREFIX_TAGS],
        series[:_MAX_PREFIX_SERIES],
    )


def _attach_prefix_search_fields(
    prefixes: list[dict[str, Any]],
    *,
    actors_map: dict[tuple[str, str], list[str]] | None = None,
    tags_map: dict[tuple[str, str], list[str]] | None = None,
    series_map: dict[tuple[str, str], list[str]] | None = None,
    library_root: Path | None = None,
    region_label: str | None = None,
) -> list[dict[str, Any]]:
    """给前缀挂 actors / tags / series，供片商本页筛选与索引。"""
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
        series = list((series_map or {}).get(key) or p.get("series") or [])
        if (not actors or not tags or not series) and root and pref:
            disk_a, disk_t, disk_s = _prefix_search_from_disk(root, maker, pref)
            if not actors:
                actors = disk_a
            if not tags:
                tags = disk_t
            if not series:
                series = disk_s
        tags, extra_s = _sanitize_genre_tags(
            tags,
            actors=actors,
            series=series,
            studio=maker,
            prefix=pref,
        )
        series = _uniq_cap([*series, *extra_s], _MAX_PREFIX_SERIES)
        p["actors"] = _uniq_cap(actors, _MAX_PREFIX_ACTORS)
        p["tags"] = _uniq_cap(tags, _MAX_PREFIX_TAGS)
        p["series"] = series
        if (
            not str(p.get("posterLocal") or "").strip()
            and not str(p.get("coverUrl") or "").strip()
            and root
            and pref
        ):
            path = _resolve_prefix_dir(root, maker, pref)
            if path is not None:
                p.update(_prefix_cover_from_disk(path))
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
        with _catalog_mem_lock:
            _catalog_mem.pop(rid, None)
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


_catalog_mem: dict[str, tuple[int, dict[str, Any]]] = {}
_catalog_mem_lock = threading.Lock()


def read_region_catalog_cache(region_id: str) -> dict[str, Any] | None:
    """读分区 .catalog.json；有效则免扫盘（片商各级页首屏）。"""
    rid = maker_fs.resolve_fs_region(region_id) or str(region_id or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    label = scrape_naming.KIND_LABELS[rid]
    path = _region_catalog_path(label)
    if not path.is_file():
        return None
    try:
        mtime_ns = int(path.stat().st_mtime_ns)
    except OSError:
        return None
    with _catalog_mem_lock:
        hit = _catalog_mem.get(rid)
        if hit and hit[0] == mtime_ns:
            return dict(hit[1])
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if int(data.get("version") or 0) < _CATALOG_SEARCH_VERSION:
        return None
    if not _catalog_has_search_fields(data):
        return None
    with _catalog_mem_lock:
        _catalog_mem[rid] = (mtime_ns, data)
    return data


def _region_summary_from_catalog(
    kid: str,
    label: str,
    cached: dict[str, Any],
) -> dict[str, Any]:
    meta = maker_fs.REGION_META.get(kid) or {}
    return {
        "id": kid,
        "label": label,
        "dbRegion": cached.get("dbRegion") or meta.get("db_region") or kid,
        "navPath": cached.get("navPath") or meta.get("navPath") or label,
        "prefixCount": int(cached.get("prefixCount") or 0),
        "makerCount": int(cached.get("makerCount") or 0),
        "codeCount": int(cached.get("codeCount") or 0),
    }


def _write_catalogs_from_targets(targets: list[dict[str, Any]]) -> None:
    """按物化目标聚合各区 prefix 计数并落盘。"""
    buckets: dict[str, dict[tuple[str, str], int]] = {}
    actors_bags: dict[str, dict[tuple[str, str], list[str]]] = {}
    tags_bags: dict[str, dict[tuple[str, str], list[str]]] = {}
    series_bags: dict[str, dict[tuple[str, str], list[str]]] = {}
    lib = _makers_root_for_browse()
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
                _, tags, series = _entry_search_bits(entry)
                if tags:
                    tags_bags.setdefault(rid, {}).setdefault(key, []).extend(tags)
                if series:
                    series_bags.setdefault(rid, {}).setdefault(key, []).extend(series)
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
            series_map={
                k: _uniq_cap(v, _MAX_PREFIX_SERIES)
                for k, v in (series_bags.get(rid) or {}).items()
            },
            library_root=lib,
            region_label=label,
        )
        write_region_catalog_cache(rid, prefixes)


def _scan_region_prefixes(root: Path, label: str) -> list[dict[str, Any]]:
    """扫描片商目录：分区/前缀/番号 或 分区/厂牌/前缀/番号。"""
    prefixes: list[dict[str, Any]] = []
    if not root.is_dir():
        return prefixes
    for l2 in _safe_list_dirs(root):
        p2 = root / l2
        codes2 = _list_code_entry_dirs(p2)
        if codes2:
            studio = _studio_from_prefix_folder(p2)
            prefixes.append(
                {
                    "prefix": l2,
                    "name": f"{studio} · {l2}",
                    "board_name": studio,
                    "codeCount": len(codes2),
                    "path": [label, l2],
                    **_prefix_cover_from_disk(p2, codes2),
                }
            )
            continue
        for l3 in _safe_list_dirs(p2):
            p3 = p2 / l3
            codes3 = _list_code_entry_dirs(p3)
            if not codes3:
                continue
            prefixes.append(
                {
                    "prefix": l3,
                    "name": f"{l2} · {l3}",
                    "board_name": l2,
                    "codeCount": len(codes3),
                    "path": [label, l2, l3],
                    **_prefix_cover_from_disk(p3, codes3),
                }
            )
    return prefixes


def browse_regions() -> dict[str, Any]:
    try:
        migrate_library_layout()
    except Exception:
        log.debug("browse migrate_library_layout failed", exc_info=True)
    lib = _makers_root_for_browse()
    regions: list[dict[str, Any]] = []
    for kid in scrape_naming.KIND_ORDER:
        label = scrape_naming.KIND_LABELS[kid]
        cached = read_region_catalog_cache(kid)
        if cached:
            regions.append(_region_summary_from_catalog(kid, label, cached))
            continue
        root = lib / label
        scanned = _scan_region_prefixes(root, label) if root.is_dir() else []
        maker_count = len({str(p.get("board_name") or "") for p in scanned})
        prefix_count = len(scanned)
        code_count = sum(int(p.get("codeCount") or 0) for p in scanned)
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
        "libraryRoot": str(library_base()),
        "indexRoot": str(library_index_root()),
        "makersRoot": str(makers_library_root()),
        "regionCount": len(regions),
        "regions": regions,
        "updatedAt": _now_iso(),
    }


def refresh_region_catalog(region_id: str) -> dict[str, Any] | None:
    """强制重扫片商目录并写 catalog（含 tags / series）。"""
    rid = maker_fs.resolve_fs_region(region_id) or str(region_id or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    label = scrape_naming.KIND_LABELS[rid]
    lib = _makers_root_for_browse()
    root = lib / label
    prefixes = _scan_region_prefixes(root, label) if root.is_dir() else []
    prefixes = _attach_prefix_search_fields(
        prefixes,
        library_root=lib,
        region_label=label,
    )
    with _catalog_mem_lock:
        _catalog_mem.pop(rid, None)
    return write_region_catalog_cache(rid, prefixes)


def browse_region(region_id: str) -> dict[str, Any] | None:
    rid = maker_fs.resolve_fs_region(region_id) or str(region_id or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    cached = read_region_catalog_cache(rid)
    if cached:
        return cached
    return refresh_region_catalog(rid)


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


def _poster_name_in_entry(entry_dir: Path, code_name: str) -> str | None:
    for cand in (*_POSTER_NAMES, f"{code_name}-poster.jpg"):
        try:
            if (entry_dir / cand).is_file():
                return cand
        except OSError:
            continue
    return None


def covers_library_root() -> Path:
    root = library_base() / LIBRARY_COVERS_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _pack_lock_for(key: str) -> threading.Lock:
    with _pack_locks_guard:
        lock = _pack_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _pack_locks[key] = lock
        return lock


def _safe_pack_seg(raw: str) -> str:
    t = re.sub(r'[<>:"/\\|?*]', "_", str(raw or "").strip())
    t = t.strip(" .")
    return t[:80] or "_"


def _tile_pack_dir(region_id: str, studio: str, prefix: str) -> Path:
    rid = _safe_pack_seg(region_id)
    st = _safe_pack_seg(studio)
    pref = _safe_pack_seg(prefix) if prefix else ""
    root = covers_library_root() / rid
    if pref:
        return root / "prefixes" / st / pref
    return root / "makers" / st


def _list_child_dir_names(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    names: list[str] = []
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        names.append(e.name)
                except OSError:
                    continue
    except OSError:
        return []
    return names


def _child_dirs_newest_first(root: Path) -> list[Path]:
    rows: list[tuple[int, str, Path]] = []
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    mtime = int(e.stat(follow_symlinks=False).st_mtime_ns)
                except OSError:
                    continue
                rows.append((mtime, e.name, Path(e.path)))
    except OSError:
        return []
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    return [p for _m, _n, p in rows]


def _collect_latest_posters(code_parent: Path, need: int) -> list[tuple[Path, str]]:
    """只扫一层子目录名，按番号从新到旧取 need 张 poster，不递归全盘。"""
    if need <= 0 or not code_parent.is_dir():
        return []
    names = _list_child_dir_names(code_parent)
    names.sort(key=_dir_name_sort_key)
    found: list[tuple[Path, str]] = []
    probes = 0
    for name in names:
        if len(found) >= need:
            break
        probes += 1
        if probes > _TILE_PACK_PROBE_CAP:
            break
        poster = _poster_name_in_entry(code_parent / name, name)
        if not poster:
            continue
        found.append((code_parent / name / poster, name))
    return found


def _looks_like_code_parent(root: Path) -> bool:
    try:
        with os.scandir(root) as it:
            n = 0
            for e in it:
                if e.name.startswith(".") or not e.is_dir(follow_symlinks=False):
                    continue
                if _poster_name_in_entry(Path(e.path), e.name):
                    return True
                n += 1
                if n >= 8:
                    break
    except OSError:
        return False
    return False


def _resolve_prefix_folder(
    region_root: Path,
    studio: str,
    prefix: str,
) -> Path | None:
    st = str(studio or "").strip()
    pref = str(prefix or "").strip()
    if not pref:
        return None
    if st:
        cand = region_root / st / pref
        if cand.is_dir():
            return cand
    cand = region_root / pref
    if cand.is_dir():
        return cand
    return None


def _folder_mtime(path: Path | None) -> float:
    if path is None:
        return 0.0
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def _parse_prefix_list(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = str(raw or "").replace(";", ",").split(",")
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        s = str(p or "").strip().upper().replace("_", "-")
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out[:40]


def _write_pack_thumb(src: Path, dst_webp: Path) -> bool:
    """封面库只存小图 webp，列表加载比原版 DMM 大海报快得多。"""
    try:
        from PIL import Image

        dst_webp.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((_TILE_THUMB_MAX, _TILE_THUMB_MAX), Image.Resampling.LANCZOS)
            im.save(dst_webp, format="WEBP", quality=72, method=3)
        return dst_webp.is_file()
    except Exception:
        return False


def _link_or_copy_poster(src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            dst.unlink()
        except OSError:
            return False
    try:
        os.link(src, dst)
        return True
    except OSError:
        pass
    try:
        shutil.copy2(src, dst)
        return True
    except OSError:
        return False


def _pack_items_from_dir(pack_dir: Path) -> list[dict[str, Any]]:
    """只返回封面库里的本地文件，不用索引外链。"""
    meta = _read_json_dict(pack_dir / "pack.json")
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    codes = meta.get("codes") if isinstance(meta.get("codes"), list) else []
    if not files:
        return []
    try:
        base = library_base().resolve()
        pack_rel = pack_dir.resolve().relative_to(base).as_posix()
    except Exception:
        return []
    items: list[dict[str, Any]] = []
    for i, name in enumerate(files):
        fn = str(name or "").strip()
        if not fn or "/" in fn or "\\" in fn:
            continue
        path = pack_dir / fn
        if not path.is_file():
            continue
        rev = ""
        try:
            st = path.stat()
            rev = f"{int(st.st_mtime_ns)}-{int(st.st_size)}"
        except OSError:
            continue
        code = ""
        if i < len(codes):
            code = str(codes[i] or "").strip()
        items.append(
            {
                "coverCode": code or None,
                "posterLocal": f"{pack_rel}/{fn}",
                "posterRev": rev,
            }
        )
    return items


def _pack_items_cached(pack_dir: Path) -> list[dict[str, Any]]:
    try:
        mtime = (pack_dir / "pack.json").stat().st_mtime
    except OSError:
        return []
    key = str(pack_dir)
    with _pack_mem_lock:
        hit = _pack_mem.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
    items = _pack_items_from_dir(pack_dir)
    with _pack_mem_lock:
        _pack_mem[key] = (mtime, items)
        if len(_pack_mem) > 400:
            extra = list(_pack_mem.keys())[:80]
            for k in extra:
                _pack_mem.pop(k, None)
    return items


def _pack_mtime(pack_dir: Path) -> float:
    try:
        return float((pack_dir / "pack.json").stat().st_mtime)
    except OSError:
        return 0.0


def _pack_is_fresh(pack_dir: Path) -> bool:
    meta = _read_json_dict(pack_dir / "pack.json")
    if not meta:
        return False
    if meta.get("urls"):
        return False
    if int(meta.get("version") or 0) < _TILE_PACK_VERSION:
        return False
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    try:
        updated = str(meta.get("updatedAt") or "")
        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return False
    if not files:
        return age <= _TILE_PACK_EMPTY_TTL_S
    if age > _TILE_PACK_TTL_S:
        return False
    for name in files:
        fn = str(name or "").strip()
        if not fn or not (pack_dir / fn).is_file():
            return False
    return True


def _pack_files_ok(pack_dir: Path) -> tuple[dict[str, Any], list[str]] | None:
    meta = _read_json_dict(pack_dir / "pack.json")
    if not meta or meta.get("urls"):
        return None
    if int(meta.get("version") or 0) < _TILE_PACK_VERSION:
        return None
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    names: list[str] = []
    for name in files:
        fn = str(name or "").strip()
        if not fn or not (pack_dir / fn).is_file():
            return None
        names.append(fn)
    return meta, names


def _prefix_pack_is_current(pack_dir: Path, folder: Path | None) -> bool:
    """前缀目录 mtime 未新于封面包 → 不必重建。"""
    got = _pack_files_ok(pack_dir)
    if not got:
        return False
    _meta, files = got
    if folder is None or not folder.is_dir():
        return not files and _pack_is_fresh(pack_dir)
    if not files:
        return _pack_is_fresh(pack_dir) and _folder_mtime(folder) <= _pack_mtime(pack_dir)
    return _folder_mtime(folder) <= _pack_mtime(pack_dir)


def _rebuild_tile_pack(
    pack_dir: Path,
    sources: list[tuple[Path, str]],
    extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    pack_dir.mkdir(parents=True, exist_ok=True)
    for old in pack_dir.iterdir():
        if old.name.startswith(".") or old.name == "pack.json":
            continue
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass
    files: list[str] = []
    codes: list[str] = []
    for src, code in sources[:_TILE_COVER_N]:
        name = f"{len(files):02d}.webp"
        dest = pack_dir / name
        placed = False
        if src.suffix.lower() == ".webp":
            placed = _link_or_copy_poster(src, dest)
        if not placed:
            placed = _write_pack_thumb(src, dest)
        if not placed:
            fallback = pack_dir / f"{len(files):02d}{src.suffix.lower() or '.jpg'}"
            if not _link_or_copy_poster(src, fallback):
                continue
            name = fallback.name
        files.append(name)
        codes.append(str(code or "").strip().upper())
    payload: dict[str, Any] = {
        "version": _TILE_PACK_VERSION,
        "updatedAt": _now_iso(),
        "files": files,
        "codes": codes,
    }
    if extra:
        payload.update(extra)
    try:
        (pack_dir / "pack.json").write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    with _pack_mem_lock:
        _pack_mem.pop(str(pack_dir), None)
    return _pack_items_from_dir(pack_dir)


def ensure_tile_cover_pack(
    region_id: str,
    studio: str,
    prefix: str = "",
) -> list[dict[str, Any]]:
    """前缀封面库固定 1 张最新番号；目录有新番号才重建。"""
    rid = str(region_id or "").strip()
    st = str(studio or "").strip()
    pref = str(prefix or "").strip()
    if not rid or not pref:
        return []
    if not st:
        st = pref
    pack_dir = _tile_pack_dir(rid, st, pref)
    key = str(pack_dir)
    with _pack_lock_for(key):
        label = scrape_naming.KIND_LABELS.get(rid) or ""
        region_root = _makers_root_for_browse() / label
        folder = _resolve_prefix_folder(region_root, st, pref)
        if _prefix_pack_is_current(pack_dir, folder):
            return _pack_items_cached(pack_dir)
        sources = _collect_latest_posters(folder, 1) if folder else []
        return _rebuild_tile_pack(pack_dir, sources)


def _prefix_pack_sources(pack_dir: Path, limit: int) -> list[tuple[Path, str]]:
    """从前缀封面包抽出本地文件，供厂牌包硬链，不再二次压缩。"""
    if limit <= 0:
        return []
    meta = _read_json_dict(pack_dir / "pack.json")
    files = meta.get("files") if isinstance(meta.get("files"), list) else []
    codes = meta.get("codes") if isinstance(meta.get("codes"), list) else []
    out: list[tuple[Path, str]] = []
    for i, name in enumerate(files):
        if len(out) >= limit:
            break
        fn = str(name or "").strip()
        if not fn or "/" in fn or "\\" in fn:
            continue
        path = pack_dir / fn
        if not path.is_file():
            continue
        code = str(codes[i] or "").strip() if i < len(codes) else ""
        out.append((path, code))
    return out


def _norm_prefix_keys(prefixes: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for p in prefixes:
        s = str(p or "").strip().upper().replace("_", "-")
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _pick_latest_prefix_folder(
    region_root: Path,
    studio: str,
    prefixes: list[str],
) -> tuple[str, Path] | None:
    """目录 mtime 最新的前缀 = 最近入盘的前缀。"""
    best_m = -1.0
    best: tuple[str, Path] | None = None
    for pref in prefixes:
        folder = _resolve_prefix_folder(region_root, studio, pref)
        if folder is None:
            continue
        mt = _folder_mtime(folder)
        if best is None or mt > best_m:
            best_m = mt
            best = (pref, folder)
    return best


def ensure_maker_cover_pack(
    region_id: str,
    studio: str,
    prefixes: list[str],
) -> list[dict[str, Any]]:
    """厂牌封面库固定 1 张：最新前缀的最新番号，硬链已有 webp。"""
    rid = str(region_id or "").strip()
    st = str(studio or "").strip()
    prefs = _norm_prefix_keys(prefixes)
    if not rid or not st or not prefs:
        return []
    pack_dir = _tile_pack_dir(rid, st, "")
    key = str(pack_dir)
    with _pack_lock_for(key):
        label = scrape_naming.KIND_LABELS.get(rid) or ""
        region_root = _makers_root_for_browse() / label
        picked = _pick_latest_prefix_folder(region_root, st, prefs)
        got = _pack_files_ok(pack_dir)
        if got:
            _meta, files = got
            if picked:
                _pref, folder = picked
                if files and _folder_mtime(folder) <= _pack_mtime(pack_dir):
                    return _pack_items_cached(pack_dir)
            elif not files and _pack_is_fresh(pack_dir):
                return _pack_items_cached(pack_dir)
        extra: dict[str, Any] = {"kind": "maker", "prefixes": prefs, "sourcePrefix": ""}
        if not picked:
            return _rebuild_tile_pack(pack_dir, [], extra=extra)
        pref, folder = picked
        ensure_tile_cover_pack(rid, st, pref)
        sources = _prefix_pack_sources(_tile_pack_dir(rid, st, pref), 1)
        if not sources:
            sources = _collect_latest_posters(folder, 1)
        extra["sourcePrefix"] = pref
        extra["sourceCode"] = sources[0][1] if sources else ""
        return _rebuild_tile_pack(pack_dir, sources, extra=extra)


def browse_tile_covers(
    *,
    region: str,
    studio: str,
    prefix: str = "",
    prefixes: str | list[str] | None = None,
) -> dict[str, Any]:
    """前缀卡读 prefixes/ 最新 1 张；厂牌卡读 makers/ 最新前缀最新番号。"""
    rid = maker_fs.resolve_fs_region(region) or str(region or "").strip()
    st = str(studio or "").strip()
    pref = str(prefix or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return {"items": [], "region": rid, "studio": st, "prefix": pref}
    if pref:
        items = ensure_tile_cover_pack(rid, st or pref, pref)
    else:
        plist = _parse_prefix_list(prefixes)
        items = ensure_maker_cover_pack(rid, st, plist) if st and plist else []
    return {
        "items": items,
        "region": rid,
        "studio": st,
        "prefix": pref,
    }


def browse_tile_covers_batch(
    *,
    region: str,
    queries: list[Any],
) -> dict[str, Any]:
    """一次返回整页格子封面，避免每张卡单独打接口。"""
    qlist = [q for q in (queries or []) if isinstance(q, dict)][:80]
    packs: list[list[dict[str, Any]]] = [[] for _ in qlist]

    def one(i: int, q: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
        data = browse_tile_covers(
            region=region,
            studio=str(q.get("studio") or ""),
            prefix=str(q.get("prefix") or ""),
            prefixes=q.get("prefixes") or "",
        )
        return i, list(data.get("items") or [])

    if not qlist:
        return {"packs": []}
    workers = min(4, len(qlist))
    if workers <= 1:
        for i, q in enumerate(qlist):
            _i, items = one(i, q)
            packs[i] = items
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(one, i, q) for i, q in enumerate(qlist)]
            for fut in as_completed(futs):
                i, items = fut.result()
                packs[i] = items
    return {"packs": packs}


def _prefix_cover_from_disk(
    prefix_dir: Path,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """取前缀下最新/最大番号的本地海报，供厂牌/前缀卡片。"""
    if not prefix_dir.is_dir():
        return {}
    try:
        lib = _makers_root_for_browse().resolve()
    except OSError:
        return {}
    ordered = sorted(names or _list_code_entry_dirs(prefix_dir), key=_dir_name_sort_key)
    pending_url: dict[str, Any] = {}
    for name in ordered[:32]:
        entry = prefix_dir / name
        poster_name = _poster_name_in_entry(entry, name)
        cover_url = _parse_cover_url_file(entry / COVER_URL_NAME)
        if not poster_name:
            if cover_url and not pending_url:
                pending_url = {
                    "coverCode": str(name).strip().upper(),
                    "coverUrl": cover_url,
                    "coverUrls": [cover_url],
                }
            continue
        poster_path = entry / poster_name
        try:
            rel = entry.resolve().relative_to(lib).as_posix()
            poster_local = f"{rel}/{poster_name}"
        except Exception:
            continue
        poster_rev = ""
        try:
            st = poster_path.stat()
            poster_rev = f"{int(st.st_mtime_ns)}-{int(st.st_size)}"
        except OSError:
            poster_rev = ""
        out: dict[str, Any] = {
            "coverCode": str(name).strip().upper(),
            "posterLocal": poster_local,
            "posterRev": poster_rev or None,
        }
        if cover_url:
            out["coverUrl"] = cover_url
            out["coverUrls"] = [cover_url]
        return out
    return pending_url


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
    """片库条目摘要：nfo + poster 优先（mdc-ng），其次 scrape.json / meta.json。"""
    scrape_path = entry_dir / SCRAPE_META_FILE
    meta_path = entry_dir / INDEX_META_FILE
    url_path = entry_dir / COVER_URL_NAME
    shortcut = _parse_cover_url_file(url_path)
    nfo = _read_nfo(entry_dir)

    index_data = _read_json_dict(meta_path)
    scrape_data = _read_json_dict(scrape_path)
    if not scrape_data and index_data and _meta_looks_scraped(index_data):
        scrape_data = index_data
        index_data = {}

    has_poster = any((entry_dir / cand).is_file() for cand in _POSTER_NAMES)
    if (
        not nfo
        and not scrape_data
        and not index_data
        and not shortcut
        and not has_poster
        and not _find_nfo_file(entry_dir)
    ):
        return None

    def _pick_str(*vals: Any) -> str | None:
        for v in vals:
            s = str(v or "").strip()
            if s:
                return s
        return None

    def _pick_actors(*srcs: dict[str, Any]) -> list[str] | None:
        for src in srcs:
            raw = src.get("actors") if isinstance(src.get("actors"), list) else None
            if not raw:
                raw = src.get("actress") if isinstance(src.get("actress"), list) else None
            cleaned = [str(a).strip() for a in (raw or []) if str(a).strip()]
            if cleaned:
                return cleaned
        return None

    def _pick_tags(*srcs: dict[str, Any]) -> list[str] | None:
        for src in srcs:
            raw = src.get("genres") if isinstance(src.get("genres"), list) else None
            if not raw:
                raw = src.get("tags") if isinstance(src.get("tags"), list) else None
            cleaned = [str(t).strip() for t in (raw or []) if str(t).strip()]
            if cleaned:
                return cleaned
        return None

    code = _pick_str(
        nfo.get("code"),
        scrape_data.get("code"),
        index_data.get("code"),
        entry_dir.name,
    )
    code = str(code or entry_dir.name).strip().upper()

    title = _pick_str(
        nfo.get("title"),
        scrape_data.get("titleZh"),
        scrape_data.get("title"),
        index_data.get("titleZh"),
        index_data.get("title"),
    )
    original_title = _pick_str(
        nfo.get("originalTitle"),
        scrape_data.get("originalTitle"),
        index_data.get("originalTitle"),
    )
    actors = _pick_actors(nfo, scrape_data, index_data)
    tags = _pick_tags(nfo, scrape_data, index_data) or []
    series = _pick_str(
        nfo.get("series"),
        scrape_data.get("series"),
        index_data.get("series"),
        scrape_data.get("set"),
    )
    studio = _pick_str(
        nfo.get("studio"),
        scrape_data.get("studio"),
        index_data.get("studio"),
        scrape_data.get("maker"),
    )
    tags, extra_s = _sanitize_genre_tags(
        tags,
        actors=actors or [],
        series=[series] if series else [],
        studio=studio or "",
        code=code,
    )
    if extra_s and not series:
        series = extra_s[0]
    plot = _normalize_plot_text(
        _pick_str(
            nfo.get("plot"),
            scrape_data.get("plot"),
            scrape_data.get("outline"),
            index_data.get("plot"),
            index_data.get("outline"),
            scrape_data.get("originalplot"),
            scrape_data.get("originalPlot"),
            index_data.get("originalplot"),
            index_data.get("originalPlot"),
        )
        or ""
    )

    cover = _pick_str(
        nfo.get("cover"),
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
            lib = _makers_root_for_browse().resolve()
            rel = entry_dir.resolve().relative_to(lib).as_posix()
            poster_local = f"{rel}/{poster_name}"
        except Exception:
            poster_local = ""
        try:
            st = poster_path.stat()
            poster_rev = f"{int(st.st_mtime_ns)}-{int(st.st_size)}"
        except OSError:
            poster_rev = ""

    scraped = bool(_find_nfo_file(entry_dir)) or bool(scrape_path.is_file()) or bool(scrape_data)

    return {
        "code": code,
        "coverUrl": cover,
        "coverUrls": urls[:8],
        "forumTitle": title,
        "originalTitle": original_title,
        "forumActors": actors,
        "genres": tags,
        "series": series,
        "studio": studio,
        "plot": plot,
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
    """列出前缀下番号子目录（分区/厂牌/前缀/番号），不按空壳过滤。"""
    key = str(root.resolve())
    try:
        st = root.stat()
        sig = float(st.st_mtime)
        nlink = int(getattr(st, "st_nlink", 0) or 0)
    except OSError:
        return _list_code_entry_dirs(root)
    with _browse_names_lock:
        hit = _browse_names_cache.get(key)
        if hit and hit[0] == sig and hit[1] == nlink:
            return list(hit[2])
    names = _list_code_entry_dirs(root)
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
    region_root = _makers_root_for_browse() / label
    root = _resolve_prefix_dir(region_root, st, pref)
    if root is None:
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
    names = _list_prefix_entry_names(root)

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
            items = list(raw_items)
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
                f"{' '.join(summary.get('genres') or [])} "
                f"{summary.get('series') or ''}"
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
        items.append(by_name.get(n) or _empty_code_summary(n))

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
    return _makers_root_for_browse() / label / _FACETS_NAME


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
    actors = scrape.get("actors") if isinstance(scrape.get("actors"), list) else None
    if not actors:
        actors = scrape.get("actress") if isinstance(scrape.get("actress"), list) else None
    studio = str(scrape.get("studio") or scrape.get("maker") or "").strip()
    code = str(scrape.get("code") or entry_dir.name).strip()
    tags, extra_s = _sanitize_genre_tags(
        tags,
        actors=[str(a).strip() for a in (actors or []) if str(a).strip()],
        series=[series] if series else [],
        studio=studio,
        code=code,
    )
    if extra_s and not series:
        series = extra_s[0]
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
        raw_tags = [str(t).strip() for t in (ent.get("tags") or []) if str(t).strip()]
        series = str(ent.get("series") or "").strip()
        tags, extra_s = _sanitize_genre_tags(
            raw_tags,
            series=[series] if series else [],
            studio=studio,
            code=code,
            prefix=pref,
        )
        for t in tags:
            _facet_bucket_add(tag_bag, t, ref)
        if extra_s and not series:
            series = extra_s[0]
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
    root = _makers_root_for_browse() / label
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
            lib = _makers_root_for_browse().resolve()
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


def _aggregate_catalog_facets(
    prefixes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从片商目录 catalog 聚合标签 / 系列。"""
    tag_bag: dict[str, int] = {}
    series_bag: dict[str, int] = {}
    series_fold: dict[str, str] = {}
    for raw in prefixes or []:
        if not isinstance(raw, dict):
            continue
        n = max(1, int(raw.get("codeCount") or 0))
        actors = [str(a).strip() for a in (raw.get("actors") or []) if str(a).strip()]
        studio = str(raw.get("board_name") or "").strip()
        pref = str(raw.get("prefix") or "").strip()
        series_list = [str(s).strip() for s in (raw.get("series") or []) if str(s).strip()]
        tags, extra_s = _sanitize_genre_tags(
            [str(t) for t in (raw.get("tags") or [])],
            actors=actors,
            series=series_list,
            studio=studio,
            prefix=pref,
        )
        for t in tags:
            name = str(t or "").strip()
            if name:
                tag_bag[name] = tag_bag.get(name, 0) + n
        for s in [*series_list, *extra_s]:
            name = str(s or "").strip()
            if not name:
                continue
            folded = _fold_facet_name(name)
            if not folded:
                continue
            display = series_fold.setdefault(folded, name)
            series_bag[display] = series_bag.get(display, 0) + n

    def _rows(bag: dict[str, int]) -> list[dict[str, Any]]:
        return sorted(
            [{"name": k, "count": v} for k, v in bag.items() if v > 0],
            key=lambda x: (-int(x["count"]), str(x["name"])),
        )[:_MAX_FACET_ITEMS]

    return _rows(tag_bag), _rows(series_bag)


def _catalog_prefix_refs_for_facet(
    prefixes: list[dict[str, Any]],
    kind: str,
    value: str,
) -> list[tuple[str, str]]:
    """catalog 中含该标签/系列的前缀列表。"""
    want_cf = _fold_facet_name(value)
    if not want_cf:
        return []
    key = "series" if kind == "series" else "tags"
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in prefixes or []:
        if not isinstance(raw, dict):
            continue
        items = raw.get(key) or []
        if not any(_fold_facet_name(str(x or "")) == want_cf for x in items):
            continue
        studio = str(raw.get("board_name") or "").strip()
        pref = str(raw.get("prefix") or "").strip()
        if not studio or not pref:
            continue
        sig = f"{studio}|{pref}"
        if sig in seen:
            continue
        seen.add(sig)
        out.append((studio, pref))
    return out


def _browse_catalog_facet_codes(
    *,
    rid: str,
    kind: str,
    value: str,
    offset: int,
    limit: int,
) -> dict[str, Any] | None:
    cat = browse_region(rid)
    if not cat:
        return None
    refs = _catalog_prefix_refs_for_facet(cat.get("prefixes") or [], kind, value)
    want = str(value or "").strip()
    if not want:
        return {
            "region": rid,
            "kind": kind,
            "value": want,
            "total": 0,
            "offset": 0,
            "limit": limit,
            "items": [],
            "source": "catalog",
        }

    all_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for studio, pref in refs[:64]:
        chunk = browse_codes(
            region=rid,
            studio=studio,
            prefix=pref,
            q=want,
            offset=0,
            limit=500,
        )
        if not chunk:
            continue
        for it in chunk.get("items") or []:
            if not isinstance(it, dict):
                continue
            code = str(it.get("code") or "").strip().upper()
            if not code:
                continue
            dedupe = f"{studio}|{pref}|{code}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            row = {**it, "studio": studio, "prefix": pref}
            if _summary_is_listable(row):
                all_items.append(row)

    all_items.sort(key=_code_sort_key)
    off = max(0, int(offset or 0))
    lim = max(1, min(500, int(limit or 100)))
    page = all_items[off : off + lim]
    return {
        "region": rid,
        "kind": kind,
        "value": want,
        "total": len(all_items),
        "offset": off,
        "limit": lim,
        "items": page,
        "updatedAt": _now_iso(),
        "source": "catalog",
    }


def browse_region_facets(
    region_id: str,
    *,
    rebuild: bool = False,
    sync: bool = False,
) -> dict[str, Any] | None:
    """读分区标签 / 系列索引（来自片商目录 catalog）。"""
    rid = maker_fs.resolve_fs_region(region_id) or str(region_id or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    label = scrape_naming.KIND_LABELS[rid]
    facet_payload: dict[str, Any] | None = None
    if rebuild:
        facet_payload = build_region_facets(rid)
    elif sync:
        facet_payload = sync_region_facets(rid, force=False)

    stale = False
    if sync or rebuild:
        cat = refresh_region_catalog(rid)
    else:
        cat = browse_region(rid)
        if cat and not _catalog_has_search_fields(cat):
            stale = True
            cat = refresh_region_catalog(rid)
    if not cat:
        return None
    prefixes = cat.get("prefixes") or []
    tags, series = _aggregate_catalog_facets(prefixes)
    return {
        "id": rid,
        "label": label,
        "updatedAt": cat.get("updatedAt"),
        "scanned": len(prefixes),
        "reused": int((facet_payload or {}).get("reused") or 0),
        "updated": int((facet_payload or {}).get("updated") or 0),
        "removed": int((facet_payload or {}).get("removed") or 0),
        "tags": tags,
        "series": series,
        "source": "catalog",
        "stale": stale,
        "empty": not (tags or series),
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
    """按标签 / 系列取番号列表（catalog 索引 + 片商目录检索）。"""
    rid = maker_fs.resolve_fs_region(region) or str(region or "").strip()
    if rid not in scrape_naming.KIND_LABELS:
        return None
    k = str(kind or "").strip().lower()
    if k in {"tag", "tags", "genre", "genres", "标签"}:
        kind_out = "tag"
    elif k in {"series", "series_name", "系列"}:
        kind_out = "series"
    else:
        return None

    return _browse_catalog_facet_codes(
        rid=rid,
        kind=kind_out,
        value=value,
        offset=offset,
        limit=limit,
    )
