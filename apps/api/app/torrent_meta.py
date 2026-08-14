"""Fetch & parse .torrent metainfo by infohash (magnet without dn).

策略：
- 只对「磁力且无 dn/后缀」补全；ed2k / 已有扩展名不走这里
- 成功结果写入 SQLite（torrent_file_cache），重启后仍可直接用
- 外网失败只短时记 miss，不长期误判为「没有」
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

_HASH_RE = re.compile(r"^[a-fA-F0-9]{40}$")
_CACHE_TTL_OK_MEM = 24 * 3600
_CACHE_TTL_MISS_MEM = 120  # 网络失败短抑流，允许稍后重试
_CACHE_MAX = 1024
_FETCH_TIMEOUT = 8.0

# infohash lower -> {ts, files|None}
_cache: dict[str, tuple[float, list[dict[str, Any]] | None]] = {}
_cache_lock = threading.Lock()
_fetch_locks: dict[str, threading.Lock] = {}
_fetch_locks_guard = threading.Lock()
_table_ready = False
_table_lock = threading.Lock()

# 优先 itorrents（命中率高）；其它源作兜底
_TORRENT_URLS = (
    "https://itorrents.org/torrent/{H}.torrent",
    "https://torrage.info/download?h={h}",
)


def _bdecode(data: bytes, i: int = 0) -> tuple[Any, int]:
    if i >= len(data):
        raise ValueError("truncated bencode")
    c = data[i : i + 1]
    if c == b"i":
        j = data.index(b"e", i)
        return int(data[i + 1 : j]), j + 1
    if c == b"l":
        i += 1
        out: list[Any] = []
        while data[i : i + 1] != b"e":
            v, i = _bdecode(data, i)
            out.append(v)
        return out, i + 1
    if c == b"d":
        i += 1
        out_d: dict[bytes, Any] = {}
        while data[i : i + 1] != b"e":
            k, i = _bdecode(data, i)
            v, i = _bdecode(data, i)
            if not isinstance(k, bytes):
                raise ValueError("dict key not bytes")
            out_d[k] = v
        return out_d, i + 1
    if c.isdigit():
        colon = data.index(b":", i)
        n = int(data[i:colon])
        start = colon + 1
        end = start + n
        return data[start:end], end
    raise ValueError(f"bad bencode at {i}")


def _bencode(obj: Any) -> bytes:
    if isinstance(obj, int):
        return b"i" + str(obj).encode("ascii") + b"e"
    if isinstance(obj, bytes):
        return str(len(obj)).encode("ascii") + b":" + obj
    if isinstance(obj, str):
        raw = obj.encode("utf-8")
        return str(len(raw)).encode("ascii") + b":" + raw
    if isinstance(obj, list):
        return b"l" + b"".join(_bencode(x) for x in obj) + b"e"
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: kv[0])
        body = b""
        for k, v in items:
            key = k if isinstance(k, bytes) else str(k).encode("utf-8")
            body += _bencode(key) + _bencode(v)
        return b"d" + body + b"e"
    raise TypeError(type(obj))


def _dec_path(parts: list[Any]) -> str:
    out: list[str] = []
    for p in parts:
        if isinstance(p, bytes):
            out.append(p.decode("utf-8", "replace"))
        else:
            out.append(str(p))
    return "/".join(out)


def _ext_of(path: str) -> str:
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in base:
        return ""
    ext = base.rsplit(".", 1)[-1].strip().lower()
    if not ext or len(ext) > 8 or " " in ext or not ext.isalnum():
        return ""
    return ext


def parse_torrent_files(raw: bytes, *, expect_hash: str | None = None) -> list[dict[str, Any]]:
    root, _ = _bdecode(raw, 0)
    if not isinstance(root, dict):
        raise ValueError("torrent root not dict")
    info = root.get(b"info")
    if not isinstance(info, dict):
        raise ValueError("missing info")
    if expect_hash:
        digest = hashlib.sha1(_bencode(info)).hexdigest()
        if digest.lower() != expect_hash.lower():
            raise ValueError(f"infohash mismatch {digest} != {expect_hash}")

    name_b = info.get(b"name") or b""
    name = (
        name_b.decode("utf-8", "replace")
        if isinstance(name_b, bytes)
        else str(name_b)
    )
    files_out: list[dict[str, Any]] = []
    raw_files = info.get(b"files")
    if isinstance(raw_files, list) and raw_files:
        for i, f in enumerate(raw_files):
            if not isinstance(f, dict):
                continue
            length = int(f.get(b"length") or 0)
            path_parts = f.get(b"path") or []
            if not isinstance(path_parts, list):
                continue
            rel = _dec_path(path_parts)
            path = f"{name}/{rel}" if name and rel else (rel or name)
            files_out.append(
                {
                    "index": i + 1,
                    "path": path,
                    "size": length,
                    "extension": _ext_of(path),
                }
            )
    else:
        length = int(info.get(b"length") or 0)
        path = name or (expect_hash or "torrent")
        files_out.append(
            {
                "index": 1,
                "path": path,
                "size": length,
                "extension": _ext_of(path),
            }
        )
    return files_out


def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        try:
            from . import db

            with db.connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS torrent_file_cache (
                      info_hash TEXT PRIMARY KEY,
                      files_json TEXT NOT NULL,
                      updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                    """
                )
                conn.commit()
            _table_ready = True
        except Exception as e:
            log.debug("torrent_file_cache table skip: %s", e)


def _disk_get(h: str) -> list[dict[str, Any]] | None:
    _ensure_table()
    try:
        from . import db

        with db.connect() as conn:
            row = conn.execute(
                "SELECT files_json FROM torrent_file_cache WHERE info_hash = ?",
                (h,),
            ).fetchone()
        if not row:
            return None
        data = json.loads(row["files_json"] or "[]")
        if not isinstance(data, list):
            return None
        out: list[dict[str, Any]] = []
        for i, f in enumerate(data):
            if not isinstance(f, dict):
                continue
            path = str(f.get("path") or "").strip()
            if not path:
                continue
            out.append(
                {
                    "index": int(f.get("index") or i + 1),
                    "path": path,
                    "size": int(f.get("size") or 0),
                    "extension": str(f.get("extension") or "").lower().lstrip("."),
                }
            )
        return out
    except Exception as e:
        log.debug("torrent disk get fail %s: %s", h[:8], e)
        return None


def _disk_put(h: str, files: list[dict[str, Any]]) -> None:
    if not files:
        return
    _ensure_table()
    try:
        from . import db

        payload = json.dumps(files, ensure_ascii=False, separators=(",", ":"))
        with db.connect() as conn:
            conn.execute(
                """
                INSERT INTO torrent_file_cache (info_hash, files_json, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(info_hash) DO UPDATE SET
                  files_json = excluded.files_json,
                  updated_at = excluded.updated_at
                """,
                (h, payload),
            )
            conn.commit()
    except Exception as e:
        log.debug("torrent disk put fail %s: %s", h[:8], e)


def _mem_get(h: str) -> tuple[bool, list[dict[str, Any]] | None]:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(h)
        if not hit:
            return False, None
        ts, files = hit
        ttl = _CACHE_TTL_OK_MEM if files is not None else _CACHE_TTL_MISS_MEM
        if now - ts > ttl:
            _cache.pop(h, None)
            return False, None
        return True, files


def _mem_put(h: str, files: list[dict[str, Any]] | None) -> None:
    with _cache_lock:
        # 禁止失败覆盖已成功结果（并行预取竞态）
        prev = _cache.get(h)
        if files is None and prev and prev[1] is not None:
            return
        if len(_cache) >= _CACHE_MAX:
            items = sorted(_cache.items(), key=lambda kv: kv[1][0])
            for k, _ in items[: max(1, _CACHE_MAX // 4)]:
                _cache.pop(k, None)
        _cache[h] = (time.time(), files)


def _fetch_lock_for(h: str) -> threading.Lock:
    with _fetch_locks_guard:
        lock = _fetch_locks.get(h)
        if lock is None:
            lock = threading.Lock()
            _fetch_locks[h] = lock
        return lock


def _download_torrent(h: str) -> bytes | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; NextWeb/1.0; +local)",
        "Accept": "application/x-bittorrent,*/*",
    }
    with httpx.Client(
        timeout=_FETCH_TIMEOUT, follow_redirects=True, headers=headers
    ) as client:
        for tmpl in _TORRENT_URLS:
            url = tmpl.format(H=h.upper(), h=h.lower())
            try:
                r = client.get(url)
                if r.status_code != 200:
                    continue
                data = r.content or b""
                if len(data) < 16 or data[:1] not in (b"d",):
                    continue
                return data
            except Exception as e:
                log.debug("torrent fetch fail %s %s: %s", h[:8], url, e)
    return None


def files_from_infohash(info_hash: str) -> list[dict[str, Any]]:
    """
    Resolve file list for a magnet that only has btih.
    命中顺序：内存 → SQLite → 外网 .torrent 缓存。
    """
    h = (info_hash or "").strip().lower()
    if not _HASH_RE.match(h):
        return []

    ok, cached = _mem_get(h)
    if ok:
        return list(cached or [])

    disk = _disk_get(h)
    if disk is not None:
        _mem_put(h, disk)
        return list(disk)

    lock = _fetch_lock_for(h)
    with lock:
        # 双检：并行时可能已被其它线程写好
        ok, cached = _mem_get(h)
        if ok:
            return list(cached or [])
        disk = _disk_get(h)
        if disk is not None:
            _mem_put(h, disk)
            return list(disk)

        raw = _download_torrent(h)
        if not raw:
            # 仅短时 miss，不落盘、不长期误判
            _mem_put(h, None)
            return []
        try:
            files = parse_torrent_files(raw, expect_hash=h)
        except Exception as e:
            log.debug("torrent parse fail %s: %s", h[:8], e)
            _mem_put(h, None)
            return []
        _disk_put(h, files)
        _mem_put(h, files)
        return list(files)


def prefetch_infohashes(info_hashes: list[str], *, workers: int = 4) -> None:
    """Warm cache for a search page (parallel). 已落盘的跳过。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    uniq: list[str] = []
    seen: set[str] = set()
    for raw in info_hashes:
        h = (raw or "").strip().lower()
        if not _HASH_RE.match(h) or h in seen:
            continue
        seen.add(h)
        ok, _ = _mem_get(h)
        if ok:
            continue
        disk = _disk_get(h)
        if disk is not None:
            _mem_put(h, disk)
            continue
        uniq.append(h)
    if not uniq:
        return
    n = min(max(1, workers), len(uniq))
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = [pool.submit(files_from_infohash, h) for h in uniq]
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception:
                pass
