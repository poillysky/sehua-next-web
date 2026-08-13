from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .db import connect

RESOURCE_DB_KEY = "resource_db"
SCRAPE_KEY = "scrape"
P115_KEY = "p115"
TMDB_KEY = "tmdb"
FORUM_SEHUATANG_KEY = "forum.sehuatang"


def get_setting(key: str) -> Any | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row["value_json"])


def put_setting(key: str, value: Any) -> dict[str, Any]:
    payload = json.dumps(value, ensure_ascii=False)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value_json = excluded.value_json,
              updated_at = excluded.updated_at
            """,
            (key, payload, now),
        )
        conn.commit()
    return {"key": key, "value": value, "updated_at": now}
