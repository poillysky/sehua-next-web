"""片商刮削库收藏 — 服务端持久化（按登录账号 user_id，取代仅浏览器 localStorage）。

存储策略：对每个收藏条目快照一份完整 payload（对应前端 ScrapLibraryEmbedItem +
hub_region），跨设备列出/恢复时无需依赖刮削库向量仍在线，前端可直接渲染卡片。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .db import connect


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_item(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    item_id = str(row["item_id"] or "").strip()
    if not item_id:
        return None
    payload: dict[str, Any] = {}
    raw = row["payload_json"]
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:  # noqa: BLE001
            payload = {}
    payload["itemId"] = item_id
    payload["favoritedAt"] = _parse_ms(row["favorited_at"])
    region = str(row["hub_region"] or "").strip()
    if region:
        payload["hubRegion"] = region
    return payload


def _parse_ms(ts: str) -> int:
    """把 'YYYY-MM-DDTHH:MM:SSZ' 之类的服务端时间转成毫秒时间戳，便于前端排序展示。"""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:  # noqa: BLE001
        return 0


def list_favorites(user_id: int) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT item_id, hub_region, payload_json, favorited_at
            FROM scrap_favorites
            WHERE user_id = ?
            ORDER BY favorited_at DESC
            """,
            (user_id,),
        ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        it = _row_to_item(row)
        if it:
            items.append(it)
    return items


def is_favorite(user_id: int, item_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 AS ok FROM scrap_favorites WHERE user_id = ? AND item_id = ?",
            (user_id, item_id),
        ).fetchone()
    return bool(row)


def add_favorite(
    user_id: int,
    item_id: str,
    payload: dict[str, Any] | None,
    hub_region: str = "",
) -> bool:
    """返回 True=新增收藏；False=原本已是收藏（幂等）。"""
    item_id = str(item_id or "").strip()
    if not item_id:
        raise ValueError("缺少条目 ID")
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    now = _utc_now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO scrap_favorites (user_id, item_id, hub_region, payload_json, favorited_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (user_id, item_id) DO UPDATE SET
              hub_region = excluded.hub_region,
              payload_json = excluded.payload_json
            """,
            (user_id, item_id, str(hub_region or "").strip(), payload_json, now),
        )
        conn.commit()
    return True


def remove_favorite(user_id: int, item_id: str) -> bool:
    """返回 True=确实删除了；False=原本就不在收藏（幂等）。"""
    item_id = str(item_id or "").strip()
    if not item_id:
        return False
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM scrap_favorites WHERE user_id = ? AND item_id = ?",
            (user_id, item_id),
        )
        conn.commit()
    return (cur.rowcount or 0) > 0


def clear_favorites(user_id: int) -> int:
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM scrap_favorites WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()
    return cur.rowcount or 0
