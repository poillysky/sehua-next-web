"""向量灌库服务公共引擎（bitmagnet / sehua_resource 两个库共用）。

原先 `bitmagnet_embed_svc` 与 `sehua_resource_embed_svc` 是两份 440 行、约 85%
逐字相同的复制品 —— 差异只有表名 / 主键列 / 待嵌入 SQL / DSN 来源 / 日志节奏
这类**声明性**参数。这里收敛成「声明式 spec + 唯一引擎」，两个 svc 模块只声明
自己的差异。

⚠️ 刻意保留的历史差异（不要顺手"统一"，会改变落库/日志表现）：
  · force 模式日志节奏：sehua 每批都打且带「跳过」；bitmagnet 每 10 批打一次
  · 非 force 循环日志节奏：sehua 每 5 轮且带本批条数；bitmagnet 每 10 轮
  · 非 force 循环的「全跳过即退出」守卫只有 sehua 有
  · `_write_chunk` 只有 bitmagnet 会跳过空主键
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import psycopg
from psycopg.rows import dict_row

from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.scrap_library.embed import assert_embed_ready

BATCH_DEFAULT = 16
FETCH_BATCH = 200


@dataclass(frozen=True)
class EmbedSpec:
    """一个向量库的声明式差异集合。"""

    table: str
    pk: str
    pk_ddl: str
    source_table: str
    payload_fn: Callable[[dict[str, Any]], dict[str, Any]]
    dsn_env: str
    dsn_setting_key: str
    dsn_required_message: str
    log_name: str
    error_log: str
    busy_message: str
    thread_name: str
    pending_sql: str
    force_select_sql: str
    skip_empty_pk: bool = False
    # force 模式日志：每 N 批打一次（1 = 每批）
    force_log_mod: int = 1
    force_log_with_skipped: bool = True
    # 非 force 循环日志：每 N 轮打一次
    loop_log_every: int = 5
    loop_log_with_batch: bool = True
    break_on_all_skipped: bool = False

    @property
    def insert_sql(self) -> str:
        return f"""
INSERT INTO {self.table}
  ({self.pk}, model, dim, content_sha, source_text, embedding, updated_at)
VALUES
  (%s, %s, %s, %s, %s, %s::vector, now())
ON CONFLICT ({self.pk}) DO UPDATE SET
  model = EXCLUDED.model,
  dim = EXCLUDED.dim,
  content_sha = EXCLUDED.content_sha,
  source_text = EXCLUDED.source_text,
  embedding = EXCLUDED.embedding,
  updated_at = now()
"""

    @property
    def hnsw_sql(self) -> str:
        return f"""
CREATE INDEX IF NOT EXISTS {self.table}_hnsw
  ON {self.table}
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64)
"""

    @property
    def stats_counts_sql(self) -> str:
        return f"""
                SELECT
                  (SELECT count(*)::int FROM {self.source_table}) AS resources,
                  (SELECT count(*)::int FROM {self.table}) AS embedded
                """


def vec_literal(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


class EmbedIngestJob:
    """一个向量库的灌库任务：状态机 + schema + 写入 + 主循环。

    每个 svc 模块持有一个实例，模块级函数只是转发（保持原有模块级 API）。
    """

    def __init__(self, spec: EmbedSpec) -> None:
        self.spec = spec
        self.log = logging.getLogger(spec.log_name)
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "phase": "",
            "progress": None,
            "log": [],
            "result": None,
            "error": None,
            "startedAt": None,
            "stop": False,
        }

    # ---------------- 任务状态 ----------------

    def get_job_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": bool(self._state["running"]),
                "phase": self._state.get("phase") or "",
                "progress": self._state.get("progress"),
                "log": list(self._state.get("log") or [])[-12:],
                "result": self._state.get("result"),
                "error": self._state.get("error"),
                "startedAt": self._state.get("startedAt"),
                "stop": bool(self._state.get("stop")),
            }

    def _should_stop(self) -> bool:
        with self._lock:
            return bool(self._state.get("stop"))

    def request_stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._state["running"]:
                return {"ok": False, "reason": "not_running"}
            self._state["stop"] = True
            self._state["phase"] = "pausing"
            log_list = list(self._state.get("log") or [])
            log_list.append("正在暂停…")
            self._state["log"] = log_list[-40:]
        return {"ok": True, "pausing": True}

    def _push_log(self, msg: str) -> None:
        with self._lock:
            log_list = list(self._state.get("log") or [])
            log_list.append(msg)
            self._state["log"] = log_list[-40:]

    def _prog(self, **kwargs: Any) -> None:
        with self._lock:
            cur = dict(self._state.get("progress") or {})
            cur.update(kwargs)
            self._state["progress"] = cur
            if "label" in kwargs:
                self._state["phase"] = str(kwargs["label"])

    # ---------------- 连接 ----------------

    def dsn(self) -> str:
        import os

        import app.core.settings_store as settings_store

        env = str(os.environ.get(self.spec.dsn_env) or "").strip()
        if env:
            return env
        raw = settings_store.get_setting(self.spec.dsn_setting_key) or {}
        dsn = str(raw.get("dsn") or "").strip()
        if not bool(raw.get("enabled")) or not dsn:
            raise RuntimeError(self.spec.dsn_required_message)
        return dsn

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn(), row_factory=dict_row)

    # ---------------- schema / stats ----------------

    def ensure_schema(self, *, recreate: bool = False) -> dict[str, Any]:
        spec = self.spec
        cfg = resolve_embed_config(include_secret=True)
        dim = int(cfg.get("dim") or 1024)
        if dim < 64 or dim > 4096:
            raise ValueError(f"非法向量维度: {dim}")
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                if recreate:
                    cur.execute(f"DROP TABLE IF EXISTS {spec.table} CASCADE")
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {spec.table} (
                      {spec.pk_ddl},
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
                    CREATE INDEX IF NOT EXISTS {spec.table}_sha
                      ON {spec.table} (content_sha)
                    """
                )
            conn.commit()
        return {"table": spec.table, "dim": dim, "recreate": bool(recreate)}

    def stats(self) -> dict[str, Any]:
        spec = self.spec
        try:
            self.ensure_schema()
        except Exception as e:  # noqa: BLE001
            return {
                "ok": False,
                "error": str(e),
                "resources": 0,
                "embedded": 0,
                "indexes": [],
                "hasHnsw": False,
            }
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                ext = cur.fetchone()
                cur.execute(spec.stats_counts_sql)
                row = cur.fetchone() or {}
                cur.execute(
                    """
                    SELECT indexname FROM pg_indexes
                    WHERE tablename = %s
                    ORDER BY indexname
                    """,
                    [spec.table],
                )
                indexes = [str(r["indexname"]) for r in cur.fetchall()]
        resources = int(row.get("resources") or 0)
        embedded = int(row.get("embedded") or 0)
        cfg = resolve_embed_config(include_secret=False)
        return {
            "ok": True,
            "vectorExt": (ext or {}).get("extversion") or "",
            "resources": resources,
            "embedded": embedded,
            "pending": max(0, resources - embedded),
            "indexes": indexes,
            "hasHnsw": any("hnsw" in i for i in indexes),
            "model": str(cfg.get("model") or ""),
            "dim": int(cfg.get("dim") or 1024),
        }

    def create_hnsw_index(self) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(self.spec.hnsw_sql)
            conn.commit()
        return {"index": f"{self.spec.table}_hnsw", "ok": True}

    # ---------------- 写入 ----------------

    def _fetch_pending(
        self, conn: psycopg.Connection, *, limit: int
    ) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(self.spec.pending_sql, [limit])
            return list(cur.fetchall())

    def _write_chunk(
        self,
        conn: psycopg.Connection,
        rows: list[dict[str, Any]],
        *,
        model_name: str,
        dim: int,
        force: bool,
    ) -> tuple[int, int]:
        spec = self.spec
        payloads: list[dict[str, Any]] = []
        for r in rows:
            p = spec.payload_fn(r)
            if spec.skip_empty_pk and not p[spec.pk]:
                continue
            existing = str(r.get("existing_sha") or "")
            if not force and existing and existing == p["content_sha"]:
                continue
            payloads.append(p)
        if not payloads:
            return 0, len(rows)
        written = 0
        skipped = len(rows) - len(payloads)
        for i in range(0, len(payloads), BATCH_DEFAULT):
            chunk = payloads[i : i + BATCH_DEFAULT]
            vecs = encode_texts_sync([p["source_text"] for p in chunk], query=False)
            if len(vecs) != len(chunk):
                raise RuntimeError(f"向量条数不匹配: {len(vecs)} != {len(chunk)}")
            if any(len(v) != dim for v in vecs):
                raise RuntimeError(f"向量维度不是 {dim}")
            with conn.cursor() as cur:
                for p, vec in zip(chunk, vecs, strict=True):
                    cur.execute(
                        spec.insert_sql,
                        [
                            p[spec.pk],
                            model_name,
                            dim,
                            p["content_sha"],
                            p["source_text"],
                            vec_literal(vec),
                        ],
                    )
            conn.commit()
            written += len(chunk)
        return written, skipped

    # ---------------- 主流程 ----------------

    def ingest(self, *, force: bool = False, build_index: bool = True) -> dict[str, Any]:
        spec = self.spec
        cfg = assert_embed_ready()
        self.ensure_schema()
        model_name = str(cfg["model"])
        dim = int(cfg["dim"])
        self._push_log(f"模型 {model_name} dim={dim}")
        self._prog(stage="prepare", done=0, total=None, percent=0, label="准备")

        written = 0
        skipped = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*)::int AS n FROM {spec.source_table}")
                total = int((cur.fetchone() or {}).get("n") or 0)
                cur.execute(f"SELECT count(*)::int AS n FROM {spec.table}")
                embedded0 = int((cur.fetchone() or {}).get("n") or 0)
            self._prog(
                stage="embed",
                done=embedded0,
                total=total,
                percent=round(100.0 * embedded0 / max(total, 1), 2) if total else 0,
                label="写入向量",
            )

            if force:
                offset = 0
                while True:
                    if self._should_stop():
                        self._push_log("已暂停")
                        self._prog(
                            stage="paused",
                            done=offset,
                            total=total,
                            percent=min(
                                99.99, round(100.0 * offset / max(total, 1), 2)
                            ),
                            label="已暂停",
                        )
                        return {
                            "written": written,
                            "skipped": skipped,
                            "embedded": offset,
                            "resources": total,
                            "paused": True,
                            "index": "",
                        }
                    with conn.cursor() as cur:
                        cur.execute(spec.force_select_sql, [FETCH_BATCH, offset])
                        rows = list(cur.fetchall())
                    if not rows:
                        break
                    w, s = self._write_chunk(
                        conn, rows, model_name=model_name, dim=dim, force=True
                    )
                    written += w
                    skipped += s
                    offset += len(rows)
                    pct = min(99.99, round(100.0 * offset / max(total, 1), 2))
                    self._prog(
                        stage="embed",
                        done=offset,
                        total=total,
                        percent=pct,
                        label=f"写入 {written}",
                    )
                    if spec.force_log_mod <= 1 or offset % (
                        FETCH_BATCH * spec.force_log_mod
                    ) == 0:
                        if spec.force_log_with_skipped:
                            self._push_log(
                                f"进度 {offset}/{total} · 写入 {written} · 跳过 {skipped}"
                            )
                        else:
                            self._push_log(f"进度 {offset}/{total} · 写入 {written}")
            else:
                loops = 0
                while True:
                    if self._should_stop():
                        done_est = min(total, embedded0 + written)
                        pct = min(99.99, round(100.0 * done_est / max(total, 1), 2))
                        self._push_log("已暂停")
                        self._prog(
                            stage="paused",
                            done=done_est,
                            total=total,
                            percent=pct,
                            label="已暂停",
                        )
                        with conn.cursor() as cur:
                            cur.execute(f"SELECT count(*)::int AS n FROM {spec.table}")
                            embedded = int((cur.fetchone() or {}).get("n") or 0)
                        return {
                            "written": written,
                            "skipped": skipped,
                            "embedded": embedded,
                            "resources": total,
                            "paused": True,
                            "index": "",
                        }
                    rows = self._fetch_pending(conn, limit=FETCH_BATCH)
                    if not rows:
                        break
                    w, s = self._write_chunk(
                        conn, rows, model_name=model_name, dim=dim, force=False
                    )
                    written += w
                    skipped += s
                    loops += 1
                    done_est = min(total, embedded0 + written)
                    pct = min(99.99, round(100.0 * done_est / max(total, 1), 2))
                    self._prog(
                        stage="embed",
                        done=done_est,
                        total=total,
                        percent=pct,
                        label=f"写入 {written}",
                    )
                    if loops % spec.loop_log_every == 0:
                        if spec.loop_log_with_batch:
                            self._push_log(f"已写入 {written} · 本批 {len(rows)}")
                        else:
                            self._push_log(f"已写入 {written}")
                    if spec.break_on_all_skipped and w == 0 and s == len(rows):
                        # 全部因 sha 跳过但仍在 pending 查询里——不应发生
                        break

            if build_index and written > 0 and not self._should_stop():
                self._prog(
                    stage="index", done=total, total=total, percent=99.5, label="建 HNSW"
                )
                self._push_log("创建 HNSW 索引…")
                with conn.cursor() as cur:
                    cur.execute(spec.hnsw_sql)
                conn.commit()

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*)::int AS n FROM {spec.table}")
                embedded = int((cur.fetchone() or {}).get("n") or 0)

        result = {
            "written": written,
            "skipped": skipped,
            "embedded": embedded,
            "resources": total,
            "index": f"{spec.table}_hnsw" if build_index and written > 0 else "",
            "paused": False,
        }
        self._prog(stage="done", done=total, total=total, percent=100, label="完成")
        self._push_log(f"完成 · 写入 {written} · 嵌入总计 {embedded}/{total}")
        return result

    def start_ingest_job(self, *, force: bool = False) -> dict[str, Any]:
        spec = self.spec
        assert_embed_ready()
        with self._lock:
            if self._state["running"]:
                raise RuntimeError(spec.busy_message)
            self._state.update(
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
                result = self.ingest(force=force, build_index=True)
                with self._lock:
                    self._state["result"] = result
                    self._state["phase"] = "paused" if result.get("paused") else "done"
            except Exception as e:  # noqa: BLE001
                self.log.exception(spec.error_log)
                with self._lock:
                    self._state["error"] = str(e)
                    self._state["phase"] = "error"
                    log_list = list(self._state.get("log") or [])
                    log_list.append(f"失败: {e}")
                    self._state["log"] = log_list[-40:]
            finally:
                with self._lock:
                    self._state["running"] = False
                    self._state["stop"] = False

        threading.Thread(target=run, name=spec.thread_name, daemon=True).start()
        return {"started": True}
