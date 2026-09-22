"""详情页路径缓存（第十六轮：跳过重复刮的搜索请求）。

背景：iqqtv（uuid）/ airav_io（hid）的详情 URL 不含番号，只能「搜索 → 标题
匹配 → 详情」，每码多一次搜索往返。但详情路径对同一番号是**稳定的**
（iqqtv uuid 跨镜像域名通用，airav hid 实测两次一致）—— 重复刮/补抓时
完全可以直接走缓存路径，省掉最慢的那次搜索。

安全设计（对齐 site_mirror 的既有模式）：
- **单写者**：`data/meta/detail-paths.json` 只有本模块写；
- **原子写**：走 `app.core.atomic_io.atomic_write_text`，读者只见旧值或新值；
- **损坏抢救**：`raw_decode` 抢首段合法 JSON，坏文件改名 `.corrupt-<ts>` 留证不删；
- **缓存永远只是加速**：命中后仍会校验页面（page_mentions_code /
  airav_detail_code_ok），校验不过就回落搜索并覆盖缓存 —— 坏条目最多浪费
  1 个请求，不可能产生错绑。

写盘节流：remember 仅在「新增或变更」时落盘（与 site_mirror.remember 同策略），
批量重刮同一批番号时第 2 次起零写盘。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# 条目过期：详情路径长期稳定，取大值（30 天），过期自动回落搜索并刷新。
TTL_MS = 30 * 24 * 60 * 60 * 1000

_memory: dict[str, dict[str, Any]] = {}
_loaded = False
_lock = threading.Lock()


def _store_path() -> Path:
    from app.core.db import data_dir

    return data_dir() / "meta" / "detail-paths.json"


def _key(source: str, code: str) -> str:
    return f"{str(source or '').strip().lower()}:{str(code or '').strip().upper()}"


def _load_disk() -> None:
    global _loaded
    _loaded = True
    path = _store_path()
    if not path.is_file():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("detail-paths read: %s", e)
        return
    raw: Any = None
    try:
        raw = json.loads(text)
    except Exception as e:  # json.JSONDecodeError / UnicodeDecodeError
        # 抢救首段合法 JSON（同 site_mirror._salvage_json）
        stripped = str(text or "").lstrip("\ufeff \t\r\n")
        try:
            raw, _end = json.JSONDecoder().raw_decode(stripped)
        except Exception:
            raw = None
        log.warning("detail-paths damaged (%s) — 抢救=%s", e, raw is not None)
        if isinstance(raw, dict):
            try:
                path.replace(
                    path.with_name(f"{path.stem}.corrupt-{int(time.time())}.json")
                )
            except OSError:
                pass
    if not isinstance(raw, dict):
        return
    entries = raw.get("entries") if isinstance(raw.get("entries"), dict) else {}
    now = int(time.time() * 1000)
    for k, ent in entries.items():
        if not isinstance(ent, dict):
            continue
        p = str(ent.get("path") or "").strip()
        if not p or int(ent.get("expiresAt") or 0) <= now:
            continue
        prev = _memory.get(str(k))
        if prev and int(prev.get("expiresAt") or 0) >= int(ent.get("expiresAt") or 0):
            continue
        _memory[str(k)] = {"path": p, "expiresAt": int(ent.get("expiresAt") or 0)}


def _persist_locked() -> None:
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "entries": dict(_memory)}
        from app.core.atomic_io import atomic_write_text

        atomic_write_text(
            path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
    except OSError as e:
        log.warning("detail-paths write: %s", e)


def lookup(source: str, code: str) -> str | None:
    """取缓存的详情路径（相对路径，不含域名）；未命中/过期返回 None。"""
    k = _key(source, code)
    if not _loaded:
        with _lock:
            if not _loaded:
                _load_disk()
    with _lock:
        ent = _memory.get(k)
        if not ent:
            return None
        if int(ent.get("expiresAt") or 0) <= int(time.time() * 1000):
            return None
        return str(ent.get("path") or "") or None


def remember(source: str, code: str, path: str) -> None:
    """记住详情路径（相对路径）。新增/变更才落盘；失败只记日志不抛。"""
    p = str(path or "").strip()
    if not p:
        return
    k = _key(source, code)
    now = int(time.time() * 1000)
    ent = {"path": p, "expiresAt": now + TTL_MS}
    with _lock:
        if not _loaded:
            _load_disk()
        prev = _memory.get(k)
        if prev and prev.get("path") == p and int(prev.get("expiresAt") or 0) > now:
            return
        _memory[k] = ent
        _persist_locked()


def clear_for_tests() -> None:
    """仅测试用：清空内存并删除落盘文件。"""
    global _loaded
    with _lock:
        _memory.clear()
        _loaded = True
        try:
            _store_path().unlink(missing_ok=True)
        except OSError:
            pass
