# -*- coding: utf-8 -*-
"""七区目录 → 本地 STRM 树：区/前缀/番号/番号.strm（供刮削）。

路径策略（Docker 友好）：
- 相对路径：相对项目 data/，如 strm-library → data/strm-library
- 绝对路径：按运行环境解释（本机盘符，或容器内挂载点如 /media/strm）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from . import prefix_catalog_store as store
from . import settings_store
from .db import data_dir
from .region_meta import REGION_META, REGION_ORDER

STRM_SYNC_KEY = "prefix_catalog.strm_sync"
_WIN_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
DEFAULT_REL_ROOT = "strm-library"


def resolve_strm_root(raw: str | None) -> Path:
    """相对 → data/ 下；绝对 → 原样。"""
    text = str(raw or "").strip() or DEFAULT_REL_ROOT
    p = Path(text)
    if p.is_absolute():
        return p
    # 禁止跳出 data（..）
    parts = [x for x in p.parts if x not in ("", ".")]
    if any(x == ".." for x in parts):
        raise ValueError("相对路径不能包含 ..")
    return (data_dir() / Path(*parts)).resolve() if parts else data_dir().resolve()


def _rel_under_data(rel: str) -> Path:
    """把 data 相对路径解析为绝对路径，禁止逃逸。"""
    text = str(rel or "").strip().replace("\\", "/")
    parts = [x for x in Path(text).parts if x not in ("", ".", "/")]
    if any(x == ".." for x in parts):
        raise ValueError("非法路径")
    base = data_dir().resolve()
    target = (base / Path(*parts)).resolve() if parts else base
    try:
        target.relative_to(base)
    except ValueError as e:
        raise ValueError("只能选择 data/ 下的目录") from e
    return target


def browse_data_dirs(rel: str = "") -> dict[str, Any]:
    """列出 data/ 下某层子目录，供 UI 选择。"""
    cur = _rel_under_data(rel)
    if not cur.exists():
        cur.mkdir(parents=True, exist_ok=True)
    if not cur.is_dir():
        raise ValueError("不是目录")
    base = data_dir().resolve()
    rel_path = "" if cur == base else str(cur.relative_to(base)).replace("\\", "/")
    crumbs = []
    if rel_path:
        acc: list[str] = []
        for part in Path(rel_path).parts:
            acc.append(part)
            crumbs.append({"name": part, "path": "/".join(acc)})
    folders = []
    for child in sorted(cur.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        folders.append(
            {
                "name": child.name,
                "path": str(child.relative_to(base)).replace("\\", "/"),
            }
        )
    return {
        "base": "data",
        "path": rel_path,
        "resolved": str(cur),
        "crumbs": crumbs,
        "folders": folders,
    }


def mkdir_data_dir(*, parent: str = "", name: str) -> dict[str, Any]:
    name = safe_name(name)
    if not name or name in {".", ".."}:
        raise ValueError("文件夹名称无效")
    parent_abs = _rel_under_data(parent)
    target = parent_abs / name
    target.mkdir(parents=False, exist_ok=False)
    base = data_dir().resolve()
    rel = str(target.relative_to(base)).replace("\\", "/")
    return browse_data_dirs(str(Path(rel).parent).replace("\\", "/") if "/" in rel else "")


def get_strm_sync_settings() -> dict[str, Any]:
    raw = settings_store.get_setting(STRM_SYNC_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    root = str(raw.get("root") or "").strip() or DEFAULT_REL_ROOT
    try:
        resolved = str(resolve_strm_root(root))
    except ValueError:
        resolved = ""
    return {
        "root": root,
        "resolved": resolved,
        "default_root": DEFAULT_REL_ROOT,
        "structure": "region/prefix/code/code.strm",
        "hint": "在 data/ 下选择目录（Docker 随 data 卷）",
        "updated_at": raw.get("updated_at"),
    }


def put_strm_sync_settings(*, root: str) -> dict[str, Any]:
    root = str(root or "").strip() or DEFAULT_REL_ROOT
    resolved = resolve_strm_root(root)
    saved = settings_store.put_setting(STRM_SYNC_KEY, {"root": root})
    return {
        "root": root,
        "resolved": str(resolved),
        "default_root": DEFAULT_REL_ROOT,
        "structure": "region/prefix/code/code.strm",
        "hint": "在 data/ 下选择目录（Docker 随 data 卷）",
        "updated_at": saved.get("updated_at"),
    }


def safe_name(raw: str, *, fallback: str = "_") -> str:
    s = _WIN_BAD.sub("_", str(raw or "").strip())
    s = s.rstrip(" .")
    return s or fallback


def strm_body(code: str) -> str:
    """刮削主要靠文件名；内容放番号占位即可。"""
    return f"{code}\n"


def run_strm_sync(
    root: str | None = None,
    *,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cfg = get_strm_sync_settings()
    configured = str(root or cfg.get("root") or DEFAULT_REL_ROOT).strip()
    out_root = resolve_strm_root(configured)

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

    emit("加载目录…", stage="prepare", percent=1)
    doc = store.load_catalog(force=True)

    jobs: list[tuple[str, str, str]] = []  # region_label, prefix, code
    for rid in REGION_ORDER:
        reg = doc["regions"].get(rid) or {}
        label = str(reg.get("label") or REGION_META.get(rid, {}).get("label") or rid)
        for pref, ent in (reg.get("prefixes") or {}).items():
            for code in store.codes_of(ent):
                if code:
                    jobs.append((label, str(pref), str(code)))

    total = len(jobs)
    emit(
        f"输出 {out_root} · 待写入 {total:,}",
        stage="prepare",
        done=0,
        total=total,
        percent=2,
    )

    out_root.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    errors: list[str] = []
    by_region: dict[str, int] = {REGION_META[r]["label"]: 0 for r in REGION_ORDER}

    for i, (region_label, prefix, code) in enumerate(jobs, 1):
        rel_dir = (
            Path(safe_name(region_label))
            / safe_name(prefix)
            / safe_name(code)
        )
        target_dir = out_root / rel_dir
        target = target_dir / f"{safe_name(code)}.strm"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            body = strm_body(code)
            if target.is_file():
                old = target.read_text(encoding="utf-8", errors="ignore")
                if old == body:
                    skipped += 1
                else:
                    target.write_text(body, encoding="utf-8", newline="\n")
                    written += 1
            else:
                target.write_text(body, encoding="utf-8", newline="\n")
                written += 1
            by_region[region_label] = by_region.get(region_label, 0) + 1
        except OSError as e:
            if len(errors) < 30:
                errors.append(f"{rel_dir}: {e}")

        if i == total or i % 500 == 0:
            pct = 2 + 96 * (i / max(total, 1))
            emit(
                f"写入 {i:,}/{total:,}",
                stage="write",
                done=i,
                total=total,
                percent=pct,
            )

    result = {
        "root": configured,
        "resolved": str(out_root),
        "total": total,
        "written": written,
        "skipped": skipped,
        "errors": errors,
        "by_region": by_region,
    }
    emit(
        f"完成 · 写入 {written} · 跳过 {skipped} · 合计 {total}",
        stage="done",
        done=total,
        total=total,
        percent=100,
    )
    return result
