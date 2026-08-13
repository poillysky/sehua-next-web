"""综合区自定义文件夹 / 搜索标签（JSON 落盘，对齐 sehua-search）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .db import ROOT

ZoneItemKind = Literal["folder", "search"]

CONFIG_PATH = ROOT / "data" / "zone-folders.json"

EMPTY: dict[str, Any] = {
    "version": 1,
    "folders": [],
    "updatedAt": "",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_str(v: Any) -> str:
    return str(v or "").strip()


def _normalize_kind(raw: Any, search_keyword: str) -> ZoneItemKind:
    if raw in ("search", "folder"):
        return raw  # type: ignore[return-value]
    return "search" if search_keyword else "folder"


def _normalize_folder(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    id_ = _as_str(raw.get("id"))
    name = _as_str(raw.get("name"))
    if not id_ or not name:
        return None
    parent_raw = raw.get("parentId")
    parent_id = (
        None
        if parent_raw is None or parent_raw == ""
        else (_as_str(parent_raw) or None)
    )
    search_keyword = _as_str(raw.get("searchKeyword"))
    kind = _normalize_kind(raw.get("kind"), search_keyword)
    sort_order = raw.get("sortOrder")
    try:
        sort_n = int(sort_order)
    except (TypeError, ValueError):
        sort_n = 0
    return {
        "id": id_,
        "parentId": parent_id,
        "name": name,
        "kind": kind,
        "searchKeyword": search_keyword if kind == "search" else "",
        "sortOrder": sort_n,
        "createdAt": _as_str(raw.get("createdAt")) or _now_iso(),
        "updatedAt": _as_str(raw.get("updatedAt")) or _now_iso(),
    }


def _normalize_store(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {**EMPTY, "folders": []}
    folders: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw.get("folders") or []:
        f = _normalize_folder(item)
        if not f or f["id"] in seen:
            continue
        seen.add(f["id"])
        folders.append(f)
    return {
        "version": 1,
        "folders": folders,
        "updatedAt": _as_str(raw.get("updatedAt")),
    }


def is_search_item(item: dict[str, Any]) -> bool:
    return item.get("kind") == "search" or bool(
        _as_str(item.get("searchKeyword"))
    )


def find_folder(folders: list[dict[str, Any]], id_: str) -> dict[str, Any] | None:
    needle = _as_str(id_)
    if not needle:
        return None
    for f in folders:
        if f["id"] == needle:
            return f
    return None


def list_children(
    folders: list[dict[str, Any]], parent_id: str | None
) -> list[dict[str, Any]]:
    kids = [f for f in folders if f.get("parentId") == parent_id]
    kids.sort(key=lambda f: (f.get("sortOrder", 0), f.get("name", "")))
    return kids


def collect_descendant_ids(
    folders: list[dict[str, Any]], root_id: str
) -> set[str]:
    kids: dict[str | None, list[str]] = {}
    for f in folders:
        key = f.get("parentId")
        kids.setdefault(key, []).append(f["id"])
    out: set[str] = set()
    stack = [root_id]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(kids.get(cur) or [])
    return out


def read_zone_folders() -> dict[str, Any]:
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return _normalize_store(raw)
    except Exception:
        return {**EMPTY, "folders": []}


def write_zone_folders(store: dict[str, Any]) -> dict[str, Any]:
    next_store = {
        "version": 1,
        "folders": store.get("folders") or [],
        "updatedAt": _now_iso(),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(next_store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return next_store


def create_zone_folder(
    *,
    name: str,
    parent_id: str | None = None,
    kind: ZoneItemKind | None = None,
    search_keyword: str | None = None,
) -> dict[str, Any]:
    name = _as_str(name)
    if not name:
        raise ValueError("名称不能为空")
    if len(name) > 80:
        raise ValueError("名称过长")

    kw = _as_str(search_keyword)
    resolved: ZoneItemKind
    if kind in ("search", "folder"):
        resolved = kind
    else:
        resolved = "search" if kw else "folder"
    if resolved == "search" and not kw:
        raise ValueError("搜索文件夹需要填写关键词")

    store = read_zone_folders()
    pid = None if not parent_id else _as_str(parent_id)
    if pid:
        parent = find_folder(store["folders"], pid)
        if not parent:
            raise ValueError("上级目录不存在")
        if is_search_item(parent):
            raise ValueError("搜索项下不能再建子项")

    siblings = list_children(store["folders"], pid)
    ts = _now_iso()
    folder = {
        "id": uuid.uuid4().hex[:16],
        "parentId": pid,
        "name": name,
        "kind": resolved,
        "searchKeyword": kw if resolved == "search" else "",
        "sortOrder": (
            max((s.get("sortOrder", 0) for s in siblings), default=-1) + 1
        ),
        "createdAt": ts,
        "updatedAt": ts,
    }
    next_store = write_zone_folders(
        {**store, "folders": [*store["folders"], folder]}
    )
    return {"store": next_store, "folder": folder}


def delete_zone_folder(id_: str) -> dict[str, Any]:
    store = read_zone_folders()
    target = find_folder(store["folders"], id_)
    if not target:
        raise ValueError("目录不存在")
    drop = collect_descendant_ids(store["folders"], target["id"])
    return write_zone_folders(
        {
            **store,
            "folders": [f for f in store["folders"] if f["id"] not in drop],
        }
    )
