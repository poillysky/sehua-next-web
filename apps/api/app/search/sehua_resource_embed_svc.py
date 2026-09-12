"""色花资源库向量灌库服务（resource_db / sehua_resource_embed）。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.search.sehua_embed import row_embed_payload
from app.scrap_library.embed import assert_embed_ready

log = logging.getLogger("app.sehua_resource_embed")

TABLE = "sehua_resource_embed"
BATCH_DEFAULT = 16
FETCH_BATCH = 200

INSERT_SQL = f"""
INSERT INTO {TABLE}
  (hash, model, dim, content_sha, source_text, embedding, updated_at)
VALUES
  (%s, %s, %s, %s, %s, %s::vector, now())
ON CONFLICT (hash) DO UPDATE SET
  model = EXCLUDED.model,
  dim = EXCLUDED.dim,
  content_sha = EXCLUDED.content_sha,
  source_text = EXCLUDED.source_text,
  embedding = EXCLUDED.embedding,
  updated_at = now()
"""

HNSW_SQL = f"""
CREATE INDEX IF NOT EXISTS {TABLE}_hnsw
  ON {TABLE}
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64)
"""

_job_lock = threading.Lock()
_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
    "startedAt": None,
    "stop": False,
}


def get_job_status() -> dict[str, Any]:
    with _job_lock:
        return {
            "running": bool(_job["running"]),
            "phase": _job.get("phase") or "",
            "progress": _job.get("progress"),
            "log": list(_job.get("log") or [])[-12:],
            "result": _job.get("result"),
            "error": _job.get("error"),
            "startedAt": _job.get("startedAt"),
            "stop": bool(_job.get("stop")),
        }


def _should_stop() -> bool:
    with _job_lock:
        return bool(_job.get("stop"))


def request_stop() -> dict[str, Any]:
    with _job_lock:
        if not _job["running"]:
            return {"ok": False, "reason": "not_running"}
        _job["stop"] = True
        _job["phase"] = "pausing"
        log_list = list(_job.get("log") or [])
        log_list.append("正在暂停…")
        _job["log"] = log_list[-40:]
    return {"ok": True, "pausing": True}


def _push_log(msg: str) -> None:
    with _job_lock:
        log_list = list(_job.get("log") or [])
        log_list.append(msg)
        _job["log"] = log_list[-40:]


def _prog(**kwargs: Any) -> None:
    with _job_lock:
        cur = dict(_job.get("progress") or {})
        cur.update(kwargs)
        _job["progress"] = cur
        if "label" in kwargs:
            _job["phase"] = str(kwargs["label"])


def _vec_literal(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


def _resource_dsn() -> str:
    import os

    import app.core.settings_store as settings_store

    env = str(os.environ.get("SEHUA_RESOURCE_DSN") or "").strip()
    if env:
        return env
    raw = settings_store.get_setting(settings_store.RESOURCE_DB_KEY) or {}
    dsn = str(raw.get("dsn") or "").strip()
    if not bool(raw.get("enabled")) or not dsn:
        raise RuntimeError("请先启用并保存色花资源库连接")
    return dsn


def _connect() -> psycopg.Connection:
    return psycopg.connect(_resource_dsn(), row_factory=dict_row)


def ensure_schema(*, recreate: bool = False) -> dict[str, Any]:
    cfg = resolve_embed_config(include_secret=True)
    dim = int(cfg.get("dim") or 1024)
    if dim < 64 or dim > 4096:
        raise ValueError(f"非法向量维度: {dim}")
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            if recreate:
                cur.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                  hash          text PRIMARY KEY REFERENCES ed2k_resources(hash) ON DELETE CASCADE,
                  model         text NOT NULL,
                  dim           smallint NOT NULL,
                  content_sha   text NOT NULL,
                  source_text   text NOT NULL,
                  embedding     vector({dim}) NOT NULL,
                  updated_at    timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {TABLE}_sha
                  ON {TABLE} (content_sha)
                """
            )
        conn.commit()
    return {"table": TABLE, "dim": dim, "recreate": bool(recreate)}


def stats() -> dict[str, Any]:
    try:
        ensure_schema()
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": str(e),
            "resources": 0,
            "embedded": 0,
            "indexes": [],
            "hasHnsw": False,
        }
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            ext = cur.fetchone()
            cur.execute(
                """
                SELECT
                  (SELECT count(*)::int FROM ed2k_resources) AS resources,
                  (SELECT count(*)::int FROM sehua_resource_embed) AS embedded
                """
            )
            row = cur.fetchone() or {}
            cur.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename = 'sehua_resource_embed'
                ORDER BY indexname
                """
            )
            indexes = [str(r["indexname"]) for r in cur.fetchall()]
    resources = int(row.get("resources") or 0)
    embedded = int(row.get("embedded") or 0)
    return {
        "ok": True,
        "vectorExt": (ext or {}).get("extversion") or "",
        "resources": resources,
        "embedded": embedded,
        "pending": max(0, resources - embedded),
        "indexes": indexes,
        "hasHnsw": any("hnsw" in i for i in indexes),
        "model": str(resolve_embed_config(include_secret=False).get("model") or ""),
        "dim": int(resolve_embed_config(include_secret=False).get("dim") or 1024),
    }


def create_hnsw_index() -> dict[str, Any]:
    ensure_schema()
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(HNSW_SQL)
        conn.commit()
    return {"index": f"{TABLE}_hnsw", "ok": True}


def _fetch_pending(
    conn: psycopg.Connection, *, limit: int
) -> list[dict[str, Any]]:
    sql = """
    SELECT r.hash, r.filename, rs.title, rs.description, rs.board_name,
           e.content_sha AS existing_sha
    FROM ed2k_resources r
    JOIN resource_sources rs ON rs.hash = r.hash
    LEFT JOIN sehua_resource_embed e ON e.hash = r.hash
    WHERE e.hash IS NULL
    ORDER BY r.created_at DESC NULLS LAST
    LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, [limit])
        return list(cur.fetchall())


def _write_chunk(
    conn: psycopg.Connection,
    rows: list[dict[str, Any]],
    *,
    model_name: str,
    dim: int,
    force: bool,
) -> tuple[int, int]:
    payloads: list[dict[str, Any]] = []
    for r in rows:
        p = row_embed_payload(r)
        existing = str(r.get("existing_sha") or "")
        if not force and existing and existing == p["content_sha"]:
            continue
        payloads.append(p)
    if not payloads:
        return 0, len(rows)
    written = 0
    skipped = len(rows) - len(payloads)
    batch = BATCH_DEFAULT
    for i in range(0, len(payloads), batch):
        chunk = payloads[i : i + batch]
        vecs = encode_texts_sync([p["source_text"] for p in chunk], query=False)
        if len(vecs) != len(chunk):
            raise RuntimeError(f"向量条数不匹配: {len(vecs)} != {len(chunk)}")
        if any(len(v) != dim for v in vecs):
            raise RuntimeError(f"向量维度不是 {dim}")
        with conn.cursor() as cur:
            for p, vec in zip(chunk, vecs, strict=True):
                cur.execute(
                    INSERT_SQL,
                    [
                        p["hash"],
                        model_name,
                        dim,
                        p["content_sha"],
                        p["source_text"],
                        _vec_literal(vec),
                    ],
                )
        conn.commit()
        written += len(chunk)
    return written, skipped


def ingest(*, force: bool = False, build_index: bool = True) -> dict[str, Any]:
    cfg = assert_embed_ready()
    ensure_schema()
    model_name = str(cfg["model"])
    dim = int(cfg["dim"])
    _push_log(f"模型 {model_name} dim={dim}")
    _prog(stage="prepare", done=0, total=None, percent=0, label="准备")

    written = 0
    skipped = 0
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*)::int AS n FROM ed2k_resources")
            total = int((cur.fetchone() or {}).get("n") or 0)
            cur.execute(f"SELECT count(*)::int AS n FROM {TABLE}")
            embedded0 = int((cur.fetchone() or {}).get("n") or 0)
        _prog(
            stage="embed",
            done=embedded0,
            total=total,
            percent=round(100.0 * embedded0 / max(total, 1), 2) if total else 0,
            label="写入向量",
        )

        if force:
            offset = 0
            while True:
                if _should_stop():
                    _push_log("已暂停")
                    _prog(stage="paused", done=offset, total=total, percent=min(99.99, round(100.0 * offset / max(total, 1), 2)), label="已暂停")
                    return {
                        "written": written,
                        "skipped": skipped,
                        "embedded": offset,
                        "resources": total,
                        "paused": True,
                        "index": "",
                    }
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT r.hash, r.filename, rs.title, rs.description, rs.board_name,
                               e.content_sha AS existing_sha
                        FROM ed2k_resources r
                        JOIN resource_sources rs ON rs.hash = r.hash
                        LEFT JOIN sehua_resource_embed e ON e.hash = r.hash
                        ORDER BY r.hash
                        LIMIT %s OFFSET %s
                        """,
                        [FETCH_BATCH, offset],
                    )
                    rows = list(cur.fetchall())
                if not rows:
                    break
                w, s = _write_chunk(
                    conn, rows, model_name=model_name, dim=dim, force=True
                )
                written += w
                skipped += s
                offset += len(rows)
                pct = min(99.99, round(100.0 * offset / max(total, 1), 2))
                _prog(
                    stage="embed",
                    done=offset,
                    total=total,
                    percent=pct,
                    label=f"写入 {written}",
                )
                _push_log(f"进度 {offset}/{total} · 写入 {written} · 跳过 {skipped}")
        else:
            loops = 0
            while True:
                if _should_stop():
                    done_est = min(total, embedded0 + written)
                    pct = min(99.99, round(100.0 * done_est / max(total, 1), 2))
                    _push_log("已暂停")
                    _prog(stage="paused", done=done_est, total=total, percent=pct, label="已暂停")
                    with conn.cursor() as cur:
                        cur.execute(f"SELECT count(*)::int AS n FROM {TABLE}")
                        embedded = int((cur.fetchone() or {}).get("n") or 0)
                    return {
                        "written": written,
                        "skipped": skipped,
                        "embedded": embedded,
                        "resources": total,
                        "paused": True,
                        "index": "",
                    }
                rows = _fetch_pending(conn, limit=FETCH_BATCH)
                if not rows:
                    break
                w, s = _write_chunk(
                    conn, rows, model_name=model_name, dim=dim, force=False
                )
                written += w
                skipped += s
                loops += 1
                done_est = min(total, embedded0 + written)
                pct = min(99.99, round(100.0 * done_est / max(total, 1), 2))
                _prog(
                    stage="embed",
                    done=done_est,
                    total=total,
                    percent=pct,
                    label=f"写入 {written}",
                )
                if loops % 5 == 0:
                    _push_log(f"已写入 {written} · 本批 {len(rows)}")
                if w == 0 and s == len(rows):
                    # 全部因 sha 跳过但仍在 pending 查询里——不应发生
                    break

        if build_index and written > 0 and not _should_stop():
            _prog(stage="index", done=total, total=total, percent=99.5, label="建 HNSW")
            _push_log("创建 HNSW 索引…")
            with conn.cursor() as cur:
                cur.execute(HNSW_SQL)
            conn.commit()

    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*)::int AS n FROM {TABLE}")
            embedded = int((cur.fetchone() or {}).get("n") or 0)

    result = {
        "written": written,
        "skipped": skipped,
        "embedded": embedded,
        "resources": total,
        "index": f"{TABLE}_hnsw" if build_index and written > 0 else "",
        "paused": False,
    }
    _prog(stage="done", done=total, total=total, percent=100, label="完成")
    _push_log(f"完成 · 写入 {written} · 嵌入总计 {embedded}/{total}")
    return result


def start_ingest_job(*, force: bool = False) -> dict[str, Any]:
    assert_embed_ready()
    with _job_lock:
        if _job["running"]:
            raise RuntimeError("色花资源向量灌库已在运行")
        _job.update(
            {
                "running": True,
                "phase": "starting",
                "progress": {
                    "stage": "prepare",
                    "done": 0,
                    "total": None,
                    "percent": 0,
                    "label": "starting",
                },
                "log": [],
                "result": None,
                "error": None,
                "startedAt": int(time.time() * 1000),
                "stop": False,
            }
        )

    def run() -> None:
        try:
            result = ingest(force=force, build_index=True)
            with _job_lock:
                _job["result"] = result
                if result.get("paused"):
                    _job["phase"] = "paused"
                else:
                    _job["phase"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("sehua resource embed failed")
            with _job_lock:
                _job["error"] = str(e)
                _job["phase"] = "error"
                log_list = list(_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _job["log"] = log_list[-40:]
        finally:
            with _job_lock:
                _job["running"] = False
                _job["stop"] = False

    threading.Thread(target=run, name="sehua-resource-embed", daemon=True).start()
    return {"started": True}
