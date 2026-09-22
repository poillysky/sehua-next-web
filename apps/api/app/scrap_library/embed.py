# -*- coding: utf-8 -*-
"""刮削库 NFO → 元库 (SNS_META_DSN / :5439) pgvector。"""
from __future__ import annotations
import json
import logging
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable
import app.core.settings_store as settings_store
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import data_dir, media_dir, get_meta_pool, init_db, meta_dsn_label
from app.scrap_library.nfo import (
    build_nfo_embed_text,
    content_sha,
    item_id_from_rel,
    normalize_source_text_for_diff,
    parse_nfo,
    polish_source_text_actresses,
    preserve_actress_line,
)
from app.core.ttl_cache import enforce_max, prune_by_age


log = logging.getLogger(__name__)


SETTINGS_KEY = "scrap_library.embed"


DEFAULT_REL_ROOT = "scrap-library"


TABLE = "scrap_library_embed"


_job_lock = threading.Lock()


_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}


_job_hydrated = False


_job_hydrate_lock = threading.Lock()


def _persist_embed_job(**extra: Any) -> None:
    try:
        from app.core import job_persist

        with _job_lock:
            payload = {
                "status": "running" if _job.get("running") else str(extra.get("status") or _job.get("phase") or "idle"),
                "phase": str(_job.get("phase") or ""),
                "progress": dict(_job.get("progress") or {}) or None,
                "log": list(_job.get("log") or [])[-40:],
                "result": _job.get("result"),
                "error": _job.get("error"),
                "running": bool(_job.get("running")),
            }
        for k, v in extra.items():
            if k == "status" and _job.get("running"):
                payload["status"] = "running"
            else:
                payload[k] = v
        if payload.get("running"):
            payload["status"] = "running"
        job_persist.save_job(job_persist.EMBED_JOB_KEY, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("persist embed job failed: %s", e)


def _hydrate_embed_job(*, force: bool = False) -> dict[str, Any]:
    """从 DB 恢复上次任务快照；若上次崩溃中 running→interrupted。"""
    global _job_hydrated
    with _job_hydrate_lock:
        if _job_hydrated and not force:
            return {}
        _job_hydrated = True
    try:
        from app.core import job_persist

        raw = job_persist.load_job(job_persist.EMBED_JOB_KEY)
        if not raw:
            return {}
        with _job_lock:
            if _job.get("running"):
                return raw
            if not _job.get("phase") and raw.get("phase"):
                _job["phase"] = str(raw.get("phase") or "")
            if not _job.get("progress") and raw.get("progress"):
                _job["progress"] = dict(raw.get("progress") or {})
            if not _job.get("log") and raw.get("log"):
                _job["log"] = list(raw.get("log") or [])[-40:]
            if _job.get("result") is None and raw.get("result") is not None:
                _job["result"] = raw.get("result")
            if not _job.get("error") and raw.get("error"):
                _job["error"] = raw.get("error")
            st = str(raw.get("status") or "")
            if st == "running":
                _job["phase"] = "interrupted"
                prog = dict(_job.get("progress") or {})
                prog["label"] = "进程中断 · 可继续"
                _job["progress"] = prog
                raw = dict(raw)
                raw["status"] = "interrupted"
                raw["running"] = False
                job_persist.save_job(job_persist.EMBED_JOB_KEY, raw)
        return raw
    except Exception as e:  # noqa: BLE001
        log.warning("hydrate embed job failed: %s", e)
        return {}


def get_job_status() -> dict[str, Any]:
    _hydrate_embed_job()
    with _job_lock:
        return {
            "running": bool(_job["running"]),
            "phase": _job.get("phase") or "",
            "progress": _job.get("progress"),
            "log": list(_job.get("log") or [])[-12:],
            "result": _job.get("result"),
            "error": _job.get("error"),
        }


def _push_log(msg: str) -> None:
    with _job_lock:
        log_list = list(_job.get("log") or [])
        log_list.append(str(msg))
        _job["log"] = log_list[-40:]


def _set_progress(**kwargs: Any) -> None:
    with _job_lock:
        cur = dict(_job.get("progress") or {})
        cur.update(kwargs)
        _job["progress"] = cur
        if kwargs.get("label"):
            _job["phase"] = str(kwargs["label"])


def get_settings() -> dict[str, Any]:
    raw = settings_store.get_setting(SETTINGS_KEY) or {}
    if not isinstance(raw, dict):
        raw = {}
    root = str(raw.get("root") or "").strip() or DEFAULT_REL_ROOT
    return {
        "root": root,
        "resolved": str(resolve_root(root)),
        "default_root": DEFAULT_REL_ROOT,
        "meta_db": meta_dsn_label(),
        "table": TABLE,
        "updated_at": raw.get("updated_at"),
    }


def put_settings(*, root: str) -> dict[str, Any]:
    text = str(root or "").strip() or DEFAULT_REL_ROOT
    # 禁止逃出 media/
    resolve_root(text)
    saved = settings_store.put_setting(SETTINGS_KEY, {"root": text})
    out = get_settings()
    out["updated_at"] = saved.get("updated_at")
    return out


_ROOT_CACHE: dict[str, Path] = {}


_ROOT_CACHE_MAX = 256


def resolve_root(raw: str | None = None) -> Path:
    """片库相对根 → 绝对路径。

    ⚠️ 纯函数（只依赖入参 + 模块常量 `DEFAULT_REL_ROOT` / `db.MEDIA_DIR`），
    因此按输入串记忆化。`enrich_one_row` / `_finish_one` / `_download_covers`
    **每个番号**都要调它一次以上，而 `(base / parts).resolve()` 会走文件系统
    （实测 ~0.1ms，叠加 `media_dir()` 后单次 0.45ms）。
    非法入参（相对路径含 `..`）在缓存之前就抛错，不会被记忆化成合法结果。
    """
    text = str(raw or "").strip() or DEFAULT_REL_ROOT
    hit = _ROOT_CACHE.get(text)
    if hit is not None:
        return hit
    p = Path(text)
    if p.is_absolute():
        out = p.resolve()
    else:
        parts = [x for x in p.parts if x not in ("", ".")]
        if any(x == ".." for x in parts):
            raise ValueError("相对路径不能包含 ..")
        base = media_dir()
        out = (base / Path(*parts)).resolve() if parts else base.resolve()
    if len(_ROOT_CACHE) >= _ROOT_CACHE_MAX:
        _ROOT_CACHE.clear()
    _ROOT_CACHE[text] = out
    return out


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


def assert_embed_ready() -> dict[str, Any]:
    """启动灌库前检查向量配置，避免扫完目录才因缺依赖失败。"""
    cfg = resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        raise RuntimeError("向量模型未启用，请先在 AI 设置中开启")
    provider = str(cfg.get("provider") or "local").lower()
    if provider == "local":
        try:
            from fastembed import TextEmbedding  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "未安装 fastembed。请执行: pip install -r apps/api/requirements-embed.txt"
            ) from e
    elif not str(cfg.get("apiKey") or "").strip():
        raise RuntimeError("OpenAI 兼容向量需配置 API Key")
    return cfg


def ensure_schema(*, recreate: bool = False) -> dict[str, Any]:
    init_db()
    cfg = resolve_embed_config(include_secret=True)
    dim = int(cfg.get("dim") or 1024)
    if dim < 64 or dim > 4096:
        raise ValueError(f"非法向量维度: {dim}")
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            if recreate:
                cur.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                  item_id       text PRIMARY KEY,
                  region        text NOT NULL DEFAULT '',
                  prefix        text NOT NULL DEFAULT '',
                  code          text NOT NULL DEFAULT '',
                  rel_path      text NOT NULL DEFAULT '',
                  title         text NOT NULL DEFAULT '',
                  poster_path   text NOT NULL DEFAULT '',
                  thumb_path    text NOT NULL DEFAULT '',
                  fanart_path   text NOT NULL DEFAULT '',
                  cover_url     text NOT NULL DEFAULT '',
                  model         text NOT NULL,
                  dim           smallint NOT NULL,
                  content_sha   text NOT NULL,
                  source_text   text NOT NULL,
                  embedding     vector({dim}) NOT NULL,
                  updated_at    timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            # 旧表补列
            for col, decl in (
                ("poster_path", "text NOT NULL DEFAULT ''"),
                ("thumb_path", "text NOT NULL DEFAULT ''"),
                ("fanart_path", "text NOT NULL DEFAULT ''"),
                ("cover_url", "text NOT NULL DEFAULT ''"),
            ):
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = %s AND column_name = %s
                    """,
                    (TABLE, col),
                )
                if cur.fetchone() is None:
                    cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN {col} {decl}")
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {TABLE}_sha
                  ON {TABLE} (content_sha)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {TABLE}_code
                  ON {TABLE} (code)
                """
            )
            # ⚠️ 未处理列表 / 开刮取号走 ORDER BY updated_at DESC NULLS LAST,
            # code ASC + region = ANY(...)。无此索引时是 22.6 万行全表排序，
            # 深 offset 直接爆掉（实测 offset=20000 → 33s）→ 未处理列表只能翻几页。
            # 索引列序必须与 ORDER BY 完全一致（含 NULLS LAST），否则用不上。
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {TABLE}_region_updated
                  ON {TABLE} (region, updated_at DESC NULLS LAST, code)
                """
            )
            # 维度不一致则重建（模型换维后）
            # pgvector：atttypmod 就是维数（不是 typmod-4）
            cur.execute(
                """
                SELECT a.atttypmod,
                       format_type(a.atttypid, a.atttypmod) AS ft
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = %s
                  AND a.attname = 'embedding'
                  AND NOT a.attisdropped
                """,
                (TABLE,),
            )
            row = cur.fetchone()
            if row and not recreate:
                typmod = row.get("atttypmod") if isinstance(row, dict) else row[0]
                ft = str(
                    (row.get("ft") if isinstance(row, dict) else None) or ""
                )
                existing_dim = 0
                try:
                    existing_dim = int(typmod)
                except (TypeError, ValueError):
                    existing_dim = 0
                if existing_dim <= 0 and "vector(" in ft:
                    try:
                        existing_dim = int(ft.split("vector(", 1)[1].split(")", 1)[0])
                    except (IndexError, ValueError):
                        existing_dim = dim
                if existing_dim > 0 and existing_dim != dim:
                    cur.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
                    cur.execute(
                        f"""
                        CREATE TABLE {TABLE} (
                          item_id       text PRIMARY KEY,
                          region        text NOT NULL DEFAULT '',
                          prefix        text NOT NULL DEFAULT '',
                          code          text NOT NULL DEFAULT '',
                          rel_path      text NOT NULL DEFAULT '',
                          title         text NOT NULL DEFAULT '',
                          poster_path   text NOT NULL DEFAULT '',
                          thumb_path    text NOT NULL DEFAULT '',
                          fanart_path   text NOT NULL DEFAULT '',
                          cover_url     text NOT NULL DEFAULT '',
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
                        f"CREATE INDEX IF NOT EXISTS {TABLE}_sha ON {TABLE} (content_sha)"
                    )
                    cur.execute(
                        f"CREATE INDEX IF NOT EXISTS {TABLE}_code ON {TABLE} (code)"
                    )
                    cur.execute(
                        f"""
                        CREATE INDEX IF NOT EXISTS {TABLE}_region_updated
                          ON {TABLE} (region, updated_at DESC NULLS LAST, code)
                        """
                    )
        conn.commit()
    try:
        from app.scrap_library.actress_store import ensure_actress_schema

        ensure_actress_schema()
    except Exception as e:  # noqa: BLE001
        log.warning("actress schema ensure failed: %s", e)
    return {"table": TABLE, "dim": dim, "meta_db": meta_dsn_label()}


def ensure_hnsw() -> None:
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {TABLE}_hnsw
                  ON {TABLE}
                  USING hnsw (embedding vector_cosine_ops)
                  WITH (m = 16, ef_construction = 64)
                """
            )
        conn.commit()


def _skeleton_source_text(code: str) -> str:
    c = str(code or "").strip().upper()
    return f"番号：{c}\n" if c else "番号：\n"


def _skeleton_content_sha(code: str, *, model: str, dim: int) -> str:
    """可识别的骨架 sha；正式 NFO 入库 sha 为 hex，不会撞车。"""
    base = content_sha(_skeleton_source_text(code), model=model, dim=dim)
    return f"{SKELETON_SHA_PREFIX}:{base}"


def _zero_vec_literal(dim: int) -> str:
    """紧凑零向量字面量（大批量骨架插入复用，避免反复拼 1024 浮点）。"""
    d = max(1, int(dim))
    return "[" + ",".join(["0"] * d) + "]"


def catalog_code_set() -> set[str]:
    """六区目录全部番号（大写）。"""
    import app.prefix.catalog_store as store

    doc = store.load_catalog(force=True)
    out: set[str] = set()
    for rid in doc.get("regions") or {}:
        reg = (doc["regions"] or {}).get(rid) or {}
        for _pref, ent in (reg.get("prefixes") or {}).items():
            for code in store.codes_of(ent):
                cu = str(code or "").strip().upper()
                if cu:
                    out.add(cu)
    return out


def _is_thin_nfo_item(it: dict[str, Any]) -> bool:
    """无实质元数据的空壳/薄 NFO：不同步进向量库。"""
    src = str(it.get("source_text") or "").strip()
    if not src:
        return True
    if is_skeleton_sha(str(it.get("content_sha") or "")):
        return True
    # 仅有「番号：XXX」一行
    if re.fullmatch(r"番号：[^\n]+", src, re.I):
        return True
    title = str(it.get("title") or "").strip()
    code = str(it.get("code") or "").strip().upper()
    # 无标题（或标题=番号）且无女优/剧情/片商/类型
    has_meta = bool(
        re.search(r"^(女优|剧情|片商|类型|标签|发行|原标题)：", src, re.M)
    )
    if not has_meta and (not title or title.upper() == code):
        return True
    return False


def stats() -> dict[str, Any]:
    ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) AS n FROM {TABLE}")
            row = cur.fetchone() or {}
            n = int((row.get("n") if isinstance(row, dict) else row[0]) or 0)
            cur.execute(
                """
                SELECT indexname FROM pg_indexes
                WHERE tablename = %s ORDER BY indexname
                """,
                (TABLE,),
            )
            indexes = [
                (r.get("indexname") if isinstance(r, dict) else r[0])
                for r in cur.fetchall()
            ]
    root = resolve_root(get_settings().get("root"))
    nfo_count = 0
    if root.is_dir():
        nfo_count = sum(1 for _ in root.rglob("*.nfo"))
    return {
        "meta_db": meta_dsn_label(),
        "table": TABLE,
        "embedded": n,
        "nfo_files": nfo_count,
        "root": str(root),
        "indexes": indexes,
    }


QUALITY_KINDS = (
    "no_local",
    "no_media",
    "no_actress",
    "no_studio",
    "no_plot",
    "thin_title",
)


_QUALITY_PRED: dict[str, str] = {
    "no_local": (
        "(coalesce(poster_path, '') = '' AND coalesce(thumb_path, '') = '')"
    ),
    "no_media": "(coalesce(cover_url, '') = '')",
    "no_actress": (
        "(coalesce(NULLIF(substring(source_text from '女优：(.+?)(?:\\n|$)'), ''), '') = '')"
    ),
    "no_studio": (
        "(coalesce(NULLIF(substring(source_text from '片商：(.+?)(?:\\n|$)'), ''), '') = '')"
    ),
    "no_plot": (
        "(coalesce(NULLIF(substring(source_text from '剧情：(.+?)(?:\\n|$)'), ''), '') = '')"
    ),
    "thin_title": (
        "(coalesce(trim(title), '') = '' OR length(trim(title)) < 4 "
        "OR upper(trim(title)) = upper(trim(coalesce(code, ''))))"
    ),
}


_SHELL_GAPS = list(QUALITY_KINDS)


def _embed_code_set(region: str = "") -> set[str]:
    """向量库已有番号（大写）。"""
    ensure_schema()
    region_sql, params = _quality_region_sql(region)
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT upper(trim(code)) AS c
            FROM {TABLE}
            WHERE coalesce(trim(code), '') <> ''{region_sql}
            """,
            params,
        )
        return {
            str(r.get("c") or "").strip().upper()
            for r in (cur.fetchall() or [])
            if isinstance(r, dict) and str(r.get("c") or "").strip()
        }


def _queue_item_from_row(
    d: dict[str, Any], *, shell: bool = False
) -> dict[str, Any]:
    gaps = list(_SHELL_GAPS) if shell else _row_gaps(d)
    return {
        "itemId": str(d.get("item_id") or ""),
        "region": str(d.get("region") or ""),
        "prefix": str(d.get("prefix") or ""),
        "code": str(d.get("code") or ""),
        "title": str(d.get("title") or ""),
        "relPath": str(d.get("rel_path") or "").replace("\\", "/"),
        "gaps": gaps,
        "shell": bool(shell),
    }


def list_skeleton_shell_items(
    region: str = "",
    *,
    limit: int = 0,
    offset: int = 0,
    prefer_prefixes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """向量库空壳（仅骨架）队列项。

    prefer_prefixes：本地已有/热门前缀优先（空壳降权，避免全库按番号字母从头刮）。
    """
    ensure_schema()
    off = max(0, int(offset or 0))
    lim = int(limit or 0)
    region_sql, params = _quality_region_sql(region)
    prefs = [
        str(p or "").strip().upper()
        for p in (prefer_prefixes or [])
        if str(p or "").strip()
    ]
    # 去重保序
    seen_p: set[str] = set()
    prefs_u: list[str] = []
    for p in prefs:
        if p in seen_p:
            continue
        seen_p.add(p)
        prefs_u.append(p)
    order_sql = "ORDER BY updated_at DESC NULLS LAST, code ASC"
    sql_params: list[Any] = [*params]
    if prefs_u:
        # 热门前缀靠前，同档内最新变更优先
        order_sql = (
            "ORDER BY CASE WHEN upper(prefix) = ANY(%s) THEN 0 ELSE 1 END, "
            "updated_at DESC NULLS LAST, code ASC"
        )
        sql_params.append(prefs_u)
    sql_limit = ""
    if lim > 0:
        sql_limit = " LIMIT %s OFFSET %s"
        sql_params.extend([lim, off])
    elif off:
        sql_limit = " OFFSET %s"
        sql_params.append(off)
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, region, prefix, code, title, rel_path,
                   poster_path, thumb_path, cover_url, source_text, content_sha
            FROM {TABLE}
            WHERE {_SKELETON_SQL}{region_sql}
            {order_sql}
            {sql_limit}
            """,
            sql_params,
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for raw in rows:
        d = dict(raw) if isinstance(raw, dict) else {}
        if d:
            out.append(_queue_item_from_row(d, shell=True))
    return out


def _row_gaps(row: dict[str, Any]) -> list[str]:
    if is_skeleton_sha(str(row.get("content_sha") or "")):
        return list(_SHELL_GAPS)
    gaps: list[str] = []
    poster = str(row.get("poster_path") or "").strip()
    thumb = str(row.get("thumb_path") or "").strip()
    cover = str(row.get("cover_url") or "").strip()
    title = str(row.get("title") or "").strip()
    code = str(row.get("code") or "").strip()
    src = str(row.get("source_text") or "")
    if not poster and not thumb:
        gaps.append("no_local")
    if not cover:
        gaps.append("no_media")
    if not re.search(r"^女优：.+$", src, re.M):
        gaps.append("no_actress")
    if not re.search(r"^片商：.+$", src, re.M):
        gaps.append("no_studio")
    if not re.search(r"^剧情：.+$", src, re.M):
        gaps.append("no_plot")
    if (not title) or len(title) < 4 or title.casefold() == code.casefold():
        gaps.append("thin_title")
    return gaps


def region_library_totals_fast(*, region: str = "") -> dict[str, int]:
    """角标用：仅向量库 COUNT(*)。

    不做分项 quality COUNT、也不扫未入库目录壳（后者在大库上可达数百毫秒）。
    准确「未处理」= tip.total（扫描写入）或本 COUNT − tip(done/soft/fail)。
    目录壳数量通常个位数，相对 10 万+ 可忽略；完整壳统计留给 quality 面板。
    """
    ensure_schema()
    region_sql, params = _quality_region_sql(region)
    pool = get_meta_pool()
    embed_total = 0
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) AS n FROM {TABLE} WHERE true{region_sql}",
            params,
        )
        row = cur.fetchone() or {}
        embed_total = int((row.get("n") if isinstance(row, dict) else row[0]) or 0)
    total = max(0, embed_total)
    return {
        "total": total,
        "embedTotal": total,
        "shells": 0,
    }


def quality_stats(*, region: str = "") -> dict[str, Any]:
    """刮削库元数据缺口计数（按区）。

    空壳 = 向量库仅骨架；缺口统计已含空壳，不再把「目录未入库」重复加到各分项。
    同步未跑完时，目录有但向量完全没有的一并计入 total/incomplete/shells。
    """
    ensure_schema()
    region_sql, params = _quality_region_sql(region)
    pool = get_meta_pool()
    counts: dict[str, int] = {k: 0 for k in QUALITY_KINDS}
    embed_total = 0
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) AS n FROM {TABLE} WHERE true{region_sql}",
            params,
        )
        row = cur.fetchone() or {}
        embed_total = int((row.get("n") if isinstance(row, dict) else row[0]) or 0)
        for kind, pred in _QUALITY_PRED.items():
            cur.execute(
                f"SELECT count(*) AS n FROM {TABLE} WHERE {pred}{region_sql}",
                params,
            )
            r = cur.fetchone() or {}
            counts[kind] = int((r.get("n") if isinstance(r, dict) else r[0]) or 0)
        any_pred = " OR ".join(f"({_QUALITY_PRED[k]})" for k in QUALITY_KINDS)
        cur.execute(
            f"SELECT count(*) AS n FROM {TABLE} WHERE ({any_pred}){region_sql}",
            params,
        )
        r = cur.fetchone() or {}
        embed_incomplete = int((r.get("n") if isinstance(r, dict) else r[0]) or 0)
    skeletons = count_skeleton_shells(region)
    missing = count_catalog_shells(region)
    return {
        "region": str(region or "").strip() or None,
        "total": embed_total + missing,
        "incomplete": embed_incomplete + missing,
        "embedTotal": embed_total,
        "shells": skeletons + missing,
        "counts": counts,
    }


def quality_items(
    *,
    region: str = "",
    kind: str = "no_local",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """待补全队列：先空壳（未入库兜底 + 仅骨架），再该 kind 缺口。

    limit<=0 表示不截断（全量）；否则上限 20000。
    """
    ensure_schema()
    kind_k = str(kind or "no_local").strip()
    if kind_k not in _QUALITY_PRED:
        raise ValueError(f"unknown kind: {kind_k}")
    raw_lim = int(limit) if limit is not None else 50
    off = max(0, int(offset or 0))
    unlimited = raw_lim <= 0
    lim = None if unlimited else max(1, min(20_000, raw_lim))
    need = None if unlimited else (off + int(lim))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    _take = _dedup_appender(out, seen)

    _take(
        list_catalog_shell_items(
            region, limit=0 if need is None else need, offset=0
        )
    )
    remain = None if need is None else max(0, need - len(out))
    if remain is None or remain > 0:
        _take(
            list_skeleton_shell_items(
                region, limit=0 if remain is None else remain, offset=0
            )
        )
    remain = None if need is None else max(0, need - len(out))
    if remain is None or remain > 0:
        region_sql, params = _quality_region_sql(region)
        pred = _QUALITY_PRED[kind_k]
        pool = get_meta_pool()
        fetch_n = remain if remain is not None else None
        sql_limit = "" if fetch_n is None else " LIMIT %s"
        sql_params: list[Any] = [*params]
        if fetch_n is not None:
            sql_params.append(fetch_n + len(seen))
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT item_id, region, prefix, code, title, rel_path,
                       poster_path, thumb_path, cover_url, source_text, content_sha
                FROM {TABLE}
                WHERE {pred}
                  AND NOT ({_SKELETON_SQL})
                  {region_sql}
                ORDER BY updated_at DESC NULLS LAST, code ASC
                {sql_limit}
                """,
                sql_params,
            )
            rows = cur.fetchall() or []
        for raw in rows:
            d = dict(raw) if isinstance(raw, dict) else {}
            if not d:
                continue
            _take([_queue_item_from_row(d, shell=False)])
            if need is not None and len(out) >= need:
                break

    if off:
        out = out[off:]
    if lim is not None:
        out = out[:lim]
    return out


def quality_incomplete_items(
    *,
    region: str = "",
    limit: int = 0,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """增量刮削队列：先空壳，再其它缺数据番号。"""
    ensure_schema()
    raw_lim = int(limit) if limit is not None else 0
    off = max(0, int(offset or 0))
    unlimited = raw_lim <= 0
    lim = None if unlimited else max(1, min(20_000, raw_lim))
    need = None if unlimited else (off + int(lim))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    _take = _dedup_appender(out, seen)

    _take(
        list_catalog_shell_items(
            region, limit=0 if need is None else need, offset=0
        )
    )
    remain = None if need is None else max(0, need - len(out))
    if remain is None or remain > 0:
        _take(
            list_skeleton_shell_items(
                region, limit=0 if remain is None else remain, offset=0
            )
        )
    remain = None if need is None else max(0, need - len(out))
    if remain is None or remain > 0:
        region_sql, params = _quality_region_sql(region)
        any_pred = " OR ".join(f"({_QUALITY_PRED[k]})" for k in QUALITY_KINDS)
        pool = get_meta_pool()
        fetch_n = remain if remain is not None else None
        sql_limit = "" if fetch_n is None else " LIMIT %s"
        sql_params: list[Any] = [*params]
        if fetch_n is not None:
            sql_params.append(fetch_n + len(seen))
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT item_id, region, prefix, code, title, rel_path,
                       poster_path, thumb_path, cover_url, source_text, content_sha
                FROM {TABLE}
                WHERE ({any_pred})
                  AND NOT ({_SKELETON_SQL})
                  {region_sql}
                ORDER BY updated_at DESC NULLS LAST, code ASC
                {sql_limit}
                """,
                sql_params,
            )
            rows = cur.fetchall() or []
        for raw in rows:
            d = dict(raw) if isinstance(raw, dict) else {}
            if not d:
                continue
            _take([_queue_item_from_row(d, shell=False)])
            if need is not None and len(out) >= need:
                break

    if off:
        out = out[off:]
    if lim is not None:
        out = out[:lim]
    return out


def enrich_all_items(
    *,
    region: str = "",
    limit: int = 0,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """覆盖模式队列：先空壳，再区域内其余番号。"""
    ensure_schema()
    raw_lim = int(limit) if limit is not None else 0
    off = max(0, int(offset or 0))
    unlimited = raw_lim <= 0
    lim = None if unlimited else max(1, min(20_000, raw_lim))
    need = None if unlimited else (off + int(lim))

    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    _take = _dedup_appender(out, seen)

    _take(
        list_catalog_shell_items(
            region, limit=0 if need is None else need, offset=0
        )
    )
    remain = None if need is None else max(0, need - len(out))
    if remain is None or remain > 0:
        _take(
            list_skeleton_shell_items(
                region, limit=0 if remain is None else remain, offset=0
            )
        )
    remain = None if need is None else max(0, need - len(out))
    if remain is None or remain > 0:
        region_sql, params = _quality_region_sql(region)
        pool = get_meta_pool()
        fetch_n = remain if remain is not None else None
        sql_limit = "" if fetch_n is None else " LIMIT %s"
        sql_params: list[Any] = [*params]
        if fetch_n is not None:
            sql_params.append(fetch_n + len(seen))
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT item_id, region, prefix, code, title, rel_path,
                       poster_path, thumb_path, cover_url, source_text, content_sha
                FROM {TABLE}
                WHERE coalesce(trim(code), '') <> ''
                  AND NOT ({_SKELETON_SQL})
                  {region_sql}
                ORDER BY code ASC
                {sql_limit}
                """,
                sql_params,
            )
            rows = cur.fetchall() or []
        for raw in rows:
            d = dict(raw) if isinstance(raw, dict) else {}
            if not d:
                continue
            _take([_queue_item_from_row(d, shell=False)])
            if need is not None and len(out) >= need:
                break

    if off:
        out = out[off:]
    if lim is not None:
        out = out[:lim]
    return out


def list_region_code_items(
    *,
    region: str = "",
    limit: int = 0,
    offset: int = 0,
    order: str = "code",
) -> list[dict[str, Any]]:
    """分区全部有番号行（含已齐元数据）。

    order:
      - ``code``（默认）：code ASC，兼容旧回填/扫描
      - ``updated``：updated_at DESC，未处理列表「最新入队在上」
    """
    ensure_schema()
    raw_lim = int(limit) if limit is not None else 0
    off = max(0, int(offset or 0))
    unlimited = raw_lim <= 0
    lim = None if unlimited else max(1, min(20_000, raw_lim))
    region_sql, params = _quality_region_sql(region)
    sql_params: list[Any] = [*params]
    sql_limit = ""
    if not unlimited:
        sql_limit = " LIMIT %s OFFSET %s"
        sql_params.extend([int(lim), off])
    elif off > 0:
        # 无上限但带 offset：用大 LIMIT + OFFSET
        sql_limit = " LIMIT %s OFFSET %s"
        sql_params.extend([2_000_000, off])
    order_u = str(order or "code").strip().lower()
    if order_u in {"updated", "updated_at", "mtime", "recent"}:
        order_sql = "updated_at DESC NULLS LAST, code ASC"
    else:
        order_sql = "code ASC"
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, region, prefix, code, title, rel_path,
                   poster_path, thumb_path, cover_url, source_text, content_sha
            FROM {TABLE}
            WHERE coalesce(trim(code), '') <> ''
              {region_sql}
            ORDER BY {order_sql}
            {sql_limit}
            """,
            sql_params,
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for raw in rows:
        d = dict(raw) if isinstance(raw, dict) else {}
        if not d:
            continue
        shell = bool(
            str(d.get("content_sha") or "").startswith(f"{SKELETON_SHA_PREFIX}:")
        )
        out.append(_queue_item_from_row(d, shell=shell))
    return out


def _media_rel(path: Path, *, media_root: Path | None = None) -> str:
    """绝对路径 → 相对 media/；失败则空。"""
    try:
        base = media_root if media_root is not None else media_dir().resolve()
        return path.resolve().relative_to(base).as_posix()
    except Exception:
        return ""


def _is_blank_cover_file(path: Path) -> bool:
    """本地封面是否源站假图/占位/坏文件（NOW PRINTING、HTML 错误页等）。

    真小图（矮 ps 常 &lt;12KB）必须保留；只靠像素多样性/灰白平铺判定。
    **非图片容器**（无 JPEG/PNG/GIF/WEBP/BMP/AVIF 头）一律按坏封面处理 ——
    否则 HTML 错误页会被当成有效封面长期挂在库里，既不会被重下也不会被修。
    """
    try:
        size = path.stat().st_size
        if size < 400:
            return True
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return True
    if not _image_magic_ok(head):
        return True
    if size >= 80_000:
        return False
    return _image_looks_blank(path)


def _is_blank_cover_bytes(raw: bytes) -> bool:
    """内存版假图判定：阈值与 `_is_blank_cover_file` 一致（不按体积误杀小图）。"""
    size = len(raw or b"")
    if size < 400:
        return True
    if not _image_magic_ok(raw):
        return True
    if size >= 80_000:
        return False
    return _image_bytes_looks_blank(raw)


_blank_cover_cache: dict[str, bool] = {}


_POSTER_DL_WORKERS = 3


_poster_dl_q: queue.Queue[tuple[str, str, str]] | None = None


_poster_dl_lock = threading.Lock()


_poster_dl_inflight: set[str] = set()


_poster_dl_fail_until: dict[str, float] = {}


_POSTER_DL_FAIL_CAP = 4096


def _is_http_url(url: str) -> bool:
    u = str(url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _fetch_cover_bytes(
    url: str, *, slot_timeout: float | None = None
) -> tuple[bytes, str] | None:
    """刮削落盘用拉图；走 enrich 专用闸门，不与列表封面代理抢槽。

    slot_timeout：抢槽秒数。槽超时抛 TimeoutError（上层可记 slot_blocked）；
    其它错误返回 None。
    """
    from app.scrap_library.cover_focus_routes import _fetch_bytes_for_enrich

    to = 8.0 if slot_timeout is None else float(slot_timeout)
    try:
        data, ctype = _fetch_bytes_for_enrich(url, timeout=to)
    except TimeoutError:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("scrap poster download fetch failed: %s", e)
        return None
    if not data or len(data) < 1024:
        return None
    return data, ctype or "image/jpeg"


def canonical_fc2_scrap_rel(rel: str) -> str:
    """扁平 FC2/{CODE}、旧夹 FC2PPV → 现行 FC2/FC2|FC2-PPV/{CODE}。

    非 FC2 路径原样返回。写入封面/NFO 前必须走这里，避免根目录再冒出扁平残留。
    """
    text = str(rel or "").strip().replace("\\", "/").strip("/")
    if not text:
        return ""
    parts = [p for p in text.split("/") if p and p not in (".",)]
    if not parts or any(p == ".." for p in parts):
        return text
    region = str(parts[0] or "")
    if region.casefold() not in {"fc2", "fc2ppv"} and region.upper() != "FC2":
        return text
    from app.core.region_meta import fc2_fs_prefix, normalize_fc2_code

    if len(parts) == 1:
        return text
    nxt = str(parts[1] or "")
    nxt_u = nxt.upper().replace("_", "-")
    # 旧前缀夹名
    if nxt_u in {"FC2PPV", "FC2_PPV"}:
        parts[1] = "FC2-PPV"
        if len(parts) >= 3:
            parts[2] = normalize_fc2_code(parts[2])
        return "/".join(parts)
    # 已是现行三层
    if nxt_u in {"FC2", "FC2-PPV"}:
        if len(parts) >= 3:
            parts[2] = normalize_fc2_code(parts[2])
            # 前缀夹与番号不一致时按番号纠正
            parts[1] = fc2_fs_prefix(code=parts[2])
        return "/".join(parts)
    # 扁平 FC2/{CODE}/…
    if nxt_u.startswith("FC2"):
        code = normalize_fc2_code(nxt)
        pref = fc2_fs_prefix(code=code)
        rest = parts[2:]
        return "/".join([parts[0], pref, code, *rest])
    return text


def _ensure_poster_dl_pool() -> None:
    global _poster_dl_q
    with _poster_dl_lock:
        if _poster_dl_q is not None:
            return
        _poster_dl_q = queue.Queue()
        for i in range(_POSTER_DL_WORKERS):
            threading.Thread(
                target=_poster_dl_worker_loop,
                name=f"scrap-poster-dl-{i}",
                daemon=True,
            ).start()


def _normalize_ingest_mode(mode: str | None) -> str:
    m = str(mode or "full").strip().lower()
    return m if m in {"full", "meta", "embed"} else "full"


def ingest(
    *,
    root: str | None = None,
    batch_size: int = 32,
    force: bool = False,
    limit: int | None = None,
    mode: str = "full",
    on_progress: ProgressCb | None = None,
    resume_done_ids: set[str] | None = None,
) -> dict[str, Any]:
    """扫描 scrap-library，把 NFO 元数据写入元库向量表。

    mode:
      - full: 元数据 + 向量编码（默认，兼容旧行为）
      - meta: 仅同步元数据（新/变更行写零向量，待向量化）
      - embed: 仅对元库待嵌行编码（见 vectorize_db_embeddings）

    resume_done_ids: 断点续跑时已写入的 item_id，跳过不再编码。
    """
    ingest_mode = _normalize_ingest_mode(mode)
    if ingest_mode == "embed":
        return vectorize_db_embeddings(
            batch_size=batch_size,
            force=force,
            limit=limit,
            on_progress=on_progress,
            resume_done_ids=resume_done_ids,
        )

    init_db()
    schema = ensure_schema()
    cfg_root = root if root is not None else get_settings().get("root")
    abs_root = resolve_root(str(cfg_root or DEFAULT_REL_ROOT))
    done_ids = set(resume_done_ids or ())
    meta_only = ingest_mode == "meta"

    def prog(stage: str, **kw: Any) -> None:
        payload = {"stage": stage, **kw}
        _set_progress(**payload)
        if on_progress:
            on_progress(payload)
        # 扫描阶段也落盘，便于 UI 重启后看到进度
        if stage in {"scan", "diff", "embed", "covers", "done"}:
            _persist_embed_job(
                status="running" if stage != "done" else "done",
                params={
                    "force": bool(force),
                    "root": str(cfg_root or ""),
                    "mode": ingest_mode,
                },
                doneIds=sorted(done_ids)[-8000:],
            )

    # 扫描与模型预热并行：避免「扫完才开始加载模型」的长时间假死
    # meta 模式不编码，跳过预热
    warmup_err: list[BaseException] = []
    warmup_thread: threading.Thread | None = None

    def _warmup_model() -> None:
        try:
            encode_texts_sync(["."], query=False)
            _push_log("向量模型已预热")
        except BaseException as e:  # noqa: BLE001
            warmup_err.append(e)

    if not meta_only:
        warmup_thread = threading.Thread(
            target=_warmup_model, name="scrap-embed-warmup", daemon=True
        )
        warmup_thread.start()
    else:
        _push_log("同步数据库 · 仅写元数据（不编码向量）")
    prog("scan", percent=2, label="扫描 NFO…", done=0, total=None)
    _push_log(f"扫描 {abs_root}")

    def _scan_prog(payload: dict[str, Any]) -> None:
        stage = str(payload.get("stage") or "scan")
        prog(stage, **{k: v for k, v in payload.items() if k != "stage"})

    items = _scan_items(abs_root, on_progress=_scan_prog)
    if limit is not None and int(limit) > 0:
        items = items[: int(limit)]
    # 跳过薄 NFO / 空壳式条目（真数据会覆盖同 item_id 的空壳行）
    before = len(items)
    items = [it for it in items if not _is_thin_nfo_item(it)]
    skipped_thin = before - len(items)
    if skipped_thin:
        _push_log(f"跳过空壳/薄 NFO {skipped_thin:,}")
    # 全量同步时：磁盘没有的非空壳向量行删掉（多的删）
    purged_disk = 0
    if limit is None or int(limit or 0) <= 0:
        prog("prune", percent=20, label="清理磁盘已删条目…", done=0, total=None)
        purged_disk = prune_embed_missing_from_disk(abs_root)
        if purged_disk:
            _push_log(f"已删多余向量 {purged_disk:,}（磁盘无 NFO）")
    total = len(items)
    _push_log(f"发现 {total} 条有效 NFO · 元库 {meta_dsn_label()}")
    if total == 0:
        if warmup_thread is not None:
            warmup_thread.join(timeout=1)
        prog("done", percent=100, label="无 NFO", done=0, total=0)
        return {
            "written": 0,
            "skipped": 0,
            "deleted": purged_disk,
            "total": 0,
            "root": str(abs_root),
            "meta_db": meta_dsn_label(),
            "dim": schema["dim"],
            "mode": ingest_mode,
        }

    prog("diff", percent=22, label="比对已有向量…", done=0, total=total)
    existing = (
        {}
        if force
        else _existing_embed_rows([it["item_id"] for it in items])
    )
    embed_cfg = resolve_embed_config()
    embed_model = str(embed_cfg["model"])
    embed_dim = int(embed_cfg["dim"])
    pending: list[dict[str, Any]] = []
    skipped_items: list[dict[str, Any]] = []
    text_only_items: list[dict[str, Any]] = []
    preserved_actress = 0
    polished_actress = 0
    for it in items:
        # 同步时自动优化女优名（映射中文 + 排除导演/男优）
        raw_src = str(it.get("source_text") or "")
        auto_src = polish_source_text_actresses(raw_src)
        if auto_src != raw_src:
            it["source_text"] = auto_src
            it["content_sha"] = content_sha(
                auto_src, model=embed_model, dim=embed_dim
            )
            polished_actress += 1
        if force:
            pending.append(it)
            continue
        prev = existing.get(it["item_id"])
        if not prev:
            pending.append(it)
            continue
        old_sha = prev.get("sha") or ""
        old_src = prev.get("source_text") or ""
        new_src = str(it.get("source_text") or "")
        # NFO 缺 actor 时保留库内女优，再走一遍优化
        merged = preserve_actress_line(old_src, new_src)
        merged = polish_source_text_actresses(merged)
        if merged != new_src:
            new_src = merged
            it["source_text"] = merged
            it["content_sha"] = content_sha(
                merged, model=embed_model, dim=embed_dim
            )
            preserved_actress += 1
        new_sha = str(it.get("content_sha") or "")
        if old_sha == new_sha:
            skipped_items.append(it)
            continue
        # 文本相同但 sha 变了（模型/维度）→ 仍需重嵌
        if old_src == new_src:
            pending.append(it)
            continue
        # 按清洗规则归一化后一致：视为「正常/已符合」，跳过重嵌
        if normalize_source_text_for_diff(old_src) == normalize_source_text_for_diff(
            new_src
        ):
            text_only_items.append(it)
            continue
        pending.append(it)

    skipped = len(skipped_items) + len(text_only_items)
    # 断点续跑：跳过本轮已写入的 item
    if done_ids:
        before_pending = len(pending)
        pending = [
            it
            for it in pending
            if str(it.get("item_id") or "") not in done_ids
        ]
        resumed_skip = before_pending - len(pending)
        if resumed_skip:
            _push_log(f"续跑跳过已写入 {resumed_skip:,}")
            skipped += resumed_skip
    if polished_actress:
        _push_log(f"自动优化女优名 {polished_actress:,}")
    if preserved_actress:
        _push_log(f"保留库内女优后再优化 {preserved_actress:,}（NFO 无 actor）")
    _push_log(
        f"待写入 {len(pending)} · 跳过未变 {len(skipped_items)}"
        f" · 清洗等价仅改文本 {len(text_only_items)}"
        + (" · 仅元数据" if meta_only else "")
    )
    prog(
        "embed" if not meta_only else "diff",
        percent=24,
        label=f"待写入 {len(pending)}",
        done=0,
        total=len(pending),
    )

    written = 0
    text_patched = 0
    pool = get_meta_pool()
    insert_sql = f"""
        INSERT INTO {TABLE}
          (item_id, region, prefix, code, rel_path, title,
           poster_path, thumb_path, fanart_path, cover_url,
           model, dim, content_sha, source_text, embedding, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
        ON CONFLICT (item_id) DO UPDATE SET
          region = EXCLUDED.region,
          prefix = EXCLUDED.prefix,
          code = EXCLUDED.code,
          rel_path = EXCLUDED.rel_path,
          title = EXCLUDED.title,
          poster_path = EXCLUDED.poster_path,
          thumb_path = EXCLUDED.thumb_path,
          fanart_path = EXCLUDED.fanart_path,
          cover_url = EXCLUDED.cover_url,
          model = EXCLUDED.model,
          dim = EXCLUDED.dim,
          content_sha = EXCLUDED.content_sha,
          source_text = EXCLUDED.source_text,
          embedding = EXCLUDED.embedding,
          updated_at = now()
    """
    text_sql = f"""
        UPDATE {TABLE} SET
          region = %s,
          prefix = %s,
          code = %s,
          rel_path = %s,
          title = %s,
          poster_path = %s,
          thumb_path = %s,
          fanart_path = %s,
          cover_url = %s,
          content_sha = %s,
          source_text = %s,
          updated_at = now()
        WHERE item_id = %s
    """
    cover_sql = f"""
        UPDATE {TABLE} SET
          region = %s,
          prefix = %s,
          code = %s,
          rel_path = %s,
          title = %s,
          poster_path = %s,
          thumb_path = %s,
          fanart_path = %s,
          cover_url = %s,
          updated_at = now()
        WHERE item_id = %s
    """
    if text_only_items:
        prog(
            "diff",
            percent=25,
            label=f"文本对齐 {len(text_only_items)}",
            done=0,
            total=len(text_only_items),
        )
        with pool.connection() as conn:
            with conn.cursor() as cur:
                rows = [
                    [
                        p["region"],
                        p["prefix"],
                        p["code"],
                        p["rel_path"],
                        p["title"],
                        p["poster_path"],
                        p["thumb_path"],
                        p["fanart_path"],
                        p["cover_url"],
                        p["content_sha"],
                        p["source_text"],
                        p["item_id"],
                    ]
                    for p in text_only_items
                ]
                for i in range(0, len(rows), 500):
                    cur.executemany(text_sql, rows[i : i + 500])
                    text_patched = min(len(rows), i + 500)
                    prog(
                        "diff",
                        percent=25,
                        label=f"文本对齐 {text_patched}/{len(rows)}",
                        done=text_patched,
                        total=len(rows),
                    )
            conn.commit()
        _push_log(f"清洗等价 · 仅更新文本 {len(text_only_items)}（未重嵌）")
    if pending and meta_only:
        # 仅同步元数据：新/变更行写零向量，留给「数据库向量化」
        dim = int(schema["dim"])
        zero_lit = _zero_vec_literal(dim)
        embed_cfg = resolve_embed_config()
        model_name = str(embed_cfg["model"])
        prog(
            "diff",
            percent=30,
            label=f"写元数据 {len(pending)}",
            done=0,
            total=len(pending),
        )
        _push_log(f"写元数据 {len(pending):,}（零向量占位）")
        bs_meta = max(1, min(500, int(batch_size) * 8))
        for i in range(0, len(pending), bs_meta):
            chunk = pending[i : i + bs_meta]
            rows = [
                [
                    p["item_id"],
                    p["region"],
                    p["prefix"],
                    p["code"],
                    p["rel_path"],
                    p["title"],
                    p["poster_path"],
                    p["thumb_path"],
                    p["fanart_path"],
                    p["cover_url"],
                    model_name,
                    dim,
                    p["content_sha"],
                    p["source_text"],
                    zero_lit,
                ]
                for p in chunk
            ]
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.executemany(insert_sql, rows)
                conn.commit()
            written += len(chunk)
            for p in chunk:
                iid = str(p.get("item_id") or "")
                if iid:
                    done_ids.add(iid)
            pct = 30 + int(55 * written / max(1, len(pending)))
            prog(
                "diff",
                percent=min(88, pct),
                label=f"写元数据 {written}/{len(pending)}",
                done=written,
                total=len(pending),
            )
            _persist_embed_job(
                status="running",
                params={
                    "force": bool(force),
                    "root": str(cfg_root or ""),
                    "mode": ingest_mode,
                },
                doneIds=sorted(done_ids)[-8000:],
            )
            if written == len(chunk) or written % max(bs_meta * 2, 1) == 0:
                _push_log(f"写元数据 {written}/{len(pending)}")
    elif pending:
        if warmup_thread is not None:
            warmup_thread.join()
        if warmup_err:
            raise RuntimeError(f"向量模型预热失败: {warmup_err[0]}") from warmup_err[0]
        cfg = resolve_embed_config(include_secret=True)
        model_name = str(cfg["model"])
        dim = int(cfg["dim"])
        bs = max(1, min(64, int(batch_size)))
        prog(
            "embed",
            percent=26,
            label=f"编码写入 {len(pending)}",
            done=0,
            total=len(pending),
        )
        _push_log(f"编码写入 {len(pending)} · batch={bs}")
        for i in range(0, len(pending), bs):
            chunk = pending[i : i + bs]
            vecs = encode_texts_sync([p["source_text"] for p in chunk], query=False)
            if len(vecs) != len(chunk):
                raise RuntimeError(f"向量条数不匹配: {len(vecs)} != {len(chunk)}")
            if any(len(v) != dim for v in vecs):
                raise RuntimeError(f"向量维度不是 {dim}")
            rows = [
                [
                    p["item_id"],
                    p["region"],
                    p["prefix"],
                    p["code"],
                    p["rel_path"],
                    p["title"],
                    p["poster_path"],
                    p["thumb_path"],
                    p["fanart_path"],
                    p["cover_url"],
                    model_name,
                    dim,
                    p["content_sha"],
                    p["source_text"],
                    _vec_literal(vec),
                ]
                for p, vec in zip(chunk, vecs, strict=True)
            ]
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.executemany(insert_sql, rows)
                conn.commit()
            written += len(chunk)
            for p in chunk:
                iid = str(p.get("item_id") or "")
                if iid:
                    done_ids.add(iid)
            pct = 26 + int(66 * written / max(1, len(pending)))
            prog(
                "embed",
                percent=min(92, pct),
                label=f"写入 {written}/{len(pending)}",
                done=written,
                total=len(pending),
            )
            _persist_embed_job(
                status="running",
                params={
                    "force": bool(force),
                    "root": str(cfg_root or ""),
                    "mode": ingest_mode,
                },
                doneIds=sorted(done_ids)[-8000:],
            )
            if written == len(chunk) or written % max(bs * 4, 1) == 0:
                _push_log(f"写入 {written}/{len(pending)}")
    else:
        if warmup_thread is not None:
            warmup_thread.join(timeout=0.2)

    # 文本未变也刷新封面路径，方便后续直接调用
    if skipped_items:
        prog("covers", percent=94, label="更新封面路径…", done=written, total=len(pending))
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cover_rows = [
                    [
                        p["region"],
                        p["prefix"],
                        p["code"],
                        p["rel_path"],
                        p["title"],
                        p["poster_path"],
                        p["thumb_path"],
                        p["fanart_path"],
                        p["cover_url"],
                        p["item_id"],
                    ]
                    for p in skipped_items
                ]
                # 分批 executemany，避免超大事务
                for i in range(0, len(cover_rows), 500):
                    cur.executemany(cover_sql, cover_rows[i : i + 500])
            conn.commit()
        _push_log(f"封面路径已刷新 {len(skipped_items)}")

    try:
        if not meta_only:
            ensure_hnsw()
            _push_log("HNSW 向量索引就绪")
        else:
            _push_log("跳过 HNSW（仅元数据同步）")
    except Exception as e:  # noqa: BLE001
        _push_log(f"HNSW 跳过: {e}")

    result = {
        "written": written,
        "skipped": skipped,
        "textPatched": text_patched,
        "deleted": purged_disk,
        "total": total,
        "root": str(abs_root),
        "meta_db": meta_dsn_label(),
        "table": TABLE,
        "dim": schema["dim"],
        "index": f"{TABLE}_hnsw",
        "mode": ingest_mode,
    }
    prog("done", percent=100, label="完成", done=written, total=len(pending))
    _push_log(
        (
            f"完成 · 写元数据 {written} · 跳过 {skipped}"
            if meta_only
            else f"完成 · 写入 {written} · 跳过 {skipped}"
        )
        + f"（含文本对齐 {len(text_only_items)}）· 删多余 {purged_disk}"
        + f" · 合计 {total} · → {meta_dsn_label()}"
    )
    return result


def start_ingest_job(
    *, root: str = "", force: bool = False, mode: str = "full"
) -> dict[str, Any]:
    ingest_mode = _normalize_ingest_mode(mode)
    if ingest_mode != "meta":
        assert_embed_ready()
    else:
        ensure_schema()
    prev = _hydrate_embed_job()
    resume_done: set[str] = set()
    resumed = False
    prev_params = prev.get("params") if isinstance(prev.get("params"), dict) else {}
    prev_status = str(prev.get("status") or "")
    want_root = str(root or "").strip() or str(
        (get_settings().get("root") or "")
    )
    same_params = (
        bool(prev_params.get("force")) == bool(force)
        and str(prev_params.get("root") or "").strip() in {"", want_root}
        and _normalize_ingest_mode(str(prev_params.get("mode") or "full"))
        == ingest_mode
    )
    if (
        prev_status in {"interrupted", "running", "paused"}
        and same_params
        and isinstance(prev.get("doneIds"), list)
    ):
        resume_done = {str(x) for x in prev["doneIds"] if str(x).strip()}
        resumed = bool(resume_done)

    mode_label = {
        "meta": "同步数据库",
        "embed": "向量化",
        "full": "同步向量",
    }.get(ingest_mode, "同步向量")

    with _job_lock:
        if _job["running"]:
            raise RuntimeError("刮削库向量灌库已在运行")
        _job.update(
            {
                "running": True,
                "phase": "继续" if resumed else "starting",
                "progress": {
                    "stage": "prepare",
                    "done": len(resume_done) if resumed else 0,
                    "total": None,
                    "percent": 0,
                    "label": "继续" if resumed else "starting",
                },
                "log": list(_job.get("log") or [])[-20:] if resumed else [],
                "result": None,
                "error": None,
            }
        )
    _persist_embed_job(
        status="running",
        params={
            "force": bool(force),
            "root": want_root,
            "mode": ingest_mode,
        },
        doneIds=sorted(resume_done)[-8000:],
    )

    def run() -> None:
        try:
            if root.strip():
                put_settings(root=root.strip())
            if resumed:
                _push_log(f"续跑 · 已跳过 {len(resume_done):,} 条")
            else:
                _push_log(
                    f"开始{mode_label}" + (" · 全量" if force else " · 增量")
                )
            result = ingest(
                force=force,
                mode=ingest_mode,
                resume_done_ids=resume_done or None,
            )
            with _job_lock:
                _job["result"] = result
                _job["phase"] = "done"
            _persist_embed_job(
                status="done",
                params={
                    "force": bool(force),
                    "root": want_root,
                    "mode": ingest_mode,
                },
                doneIds=[],
            )
        except Exception as e:  # noqa: BLE001
            log.exception("scrap library embed failed")
            with _job_lock:
                _job["error"] = str(e)
                _job["phase"] = "error"
                log_list = list(_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _job["log"] = log_list[-40:]
            _persist_embed_job(
                status="error",
                params={
                    "force": bool(force),
                    "root": want_root,
                    "mode": ingest_mode,
                },
                doneIds=sorted(resume_done)[-8000:],
            )
        finally:
            with _job_lock:
                _job["running"] = False
            _persist_embed_job()

    threading.Thread(target=run, name="scrap-library-embed", daemon=True).start()
    return {"started": True, "mode": ingest_mode, "resumed": resumed}


def _hit_from_row(row: dict[str, Any], *, score: float | None = None) -> dict[str, Any]:
    poster = str(row.get("poster_path") or "")
    thumb = str(row.get("thumb_path") or "")
    fanart = str(row.get("fanart_path") or "")
    cover = str(row.get("cover_url") or "")
    item_id = str(row.get("item_id") or "")
    rel_path = str(row.get("rel_path") or "").replace("\\", "/").strip("/")
    source_text = str(row.get("source_text") or "")
    # FC2 迁目录后库内路径常滞后：改写到现行文件
    poster = resolve_existing_media_rel(poster) or poster
    thumb = resolve_existing_media_rel(thumb) or thumb
    fanart = resolve_existing_media_rel(fanart) or fanart
    if not poster and rel_path:
        poster = resolve_existing_media_rel(
            f"scrap-library/{rel_path}/poster.jpg"
        )
    # 浏览时发现缺本地：后台把远程 cover 落到番号目录（不挡列表）
    if cover and not poster:
        schedule_ensure_local_poster(
            item_id=item_id, rel_path=rel_path, cover_url=cover
        )
    blurb_meta = _list_card_meta(source_text)
    out: dict[str, Any] = {
        "itemId": item_id or row.get("item_id"),
        "region": row.get("region") or "",
        "prefix": row.get("prefix") or "",
        "code": row.get("code") or "",
        "title": row.get("title") or "",
        "sourceText": source_text,
        "relPath": rel_path,
        "posterPath": poster,
        "thumbPath": thumb,
        "fanartPath": fanart,
        "coverUrl": cover,
        "posterApi": local_file_api(poster) if poster else "",
        "thumbApi": local_file_api(thumb) if thumb else "",
        "fanartApi": local_file_api(fanart) if fanart else "",
        **blurb_meta,
    }
    if score is not None:
        out["score"] = float(score)
    return out


_LIST_YEAR_RE = re.compile(r"^年份：(.+)$", re.M)


_LIST_ACTRESS_RE = re.compile(r"^女优：(.+)$", re.M)


_LIST_BADGE_RE = re.compile(r"^角标：(.+)$", re.M)


_LIST_DEF_RE = re.compile(r"^清晰度：(.+)$", re.M)


_LIST_MOSAIC_RE = re.compile(r"^马赛克：(.+)$", re.M)


def _list_card_meta(source_text: str) -> dict[str, Any]:
    """条目附加字段（年份/角标等）；列表卡不再展示剧情短摘。"""
    src = str(source_text or "")
    year = ""
    m = _LIST_YEAR_RE.search(src)
    if m:
        year = re.sub(r"\D", "", m.group(1))[:4]

    actresses: list[str] = []
    m = _LIST_ACTRESS_RE.search(src)
    if m:
        for name in re.split(r"[\s、,/|]+", m.group(1).strip()):
            name = name.strip()
            if not name or name in actresses:
                continue
            actresses.append(name)
            if len(actresses) >= 3:
                break

    badges: list[str] = []
    m = _LIST_BADGE_RE.search(src)
    if m:
        for tok in re.split(r"[\s,，、/|]+", m.group(1).strip()):
            t = tok.strip()
            if t and t not in badges:
                badges.append(t)
            if len(badges) >= 6:
                break
    definition = ""
    m = _LIST_DEF_RE.search(src)
    if m:
        definition = m.group(1).strip()
    mosaic = ""
    m = _LIST_MOSAIC_RE.search(src)
    if m:
        mosaic = m.group(1).strip()
    cnsub = bool(re.search(r"^字幕：中字\s*$", src, re.M)) or any(
        "中字" in b or "字幕" in b or b.lower() == "cnsub" for b in badges
    )

    return {
        "year": year,
        "actresses": actresses,
        "badges": badges,
        "cnsub": cnsub,
        "definition": definition,
        "mosaic": mosaic,
    }


def _blurb_bits(*parts: str, exclude: str = "") -> str:
    ex = str(exclude or "").strip().casefold()
    out: list[str] = []
    for raw in parts:
        s = str(raw or "").strip()
        if not s:
            continue
        # 仅跳过与标题完全相同的片段，避免把「SOD Create」因含 SOD 滤掉
        if ex and s.casefold() == ex:
            continue
        if s not in out:
            out.append(s)
        if len(out) >= 2:
            break
    return " · ".join(out)


def _prefix_blurb(prefix: str) -> str:
    """前缀卡简介：优先 MAKER_INTRO，否则回退厂牌名。"""
    from app.prefix.maker_names import resolve_maker_intro_for_prefix, resolve_maker_names

    pref = str(prefix or "").strip().upper()
    if not pref:
        return ""
    intro = resolve_maker_intro_for_prefix(pref)
    if intro:
        return intro
    names = resolve_maker_names(pref)
    label = str(names.get("maker") or "").strip()
    if label and label.casefold() != pref.casefold():
        return label
    return _blurb_bits(
        str(names.get("maker_zh") or ""),
        str(names.get("maker_ja") or ""),
        str(names.get("maker_en") or ""),
        exclude=pref,
    )


def _studio_blurb(studio_name: str) -> str:
    """厂牌卡简介：优先 MAKER_INTRO 中文介绍。"""
    from app.prefix.maker_names import resolve_maker_intro_for_studio

    raw = str(studio_name or "").strip()
    if not raw or raw in {"未标注厂牌", "未标注", "(unknown)"}:
        return ""
    return resolve_maker_intro_for_studio(raw)


_FC2_FOLDER_PREFIXES = ("FC2", "FC2PPV")  # 文档/兼容保留


def _append_prefix_clause(
    clauses: list[str], params: list[Any], prefix: str
) -> None:
    prefs = _folder_prefix_aliases(prefix)
    if not prefs:
        return
    if len(prefs) == 1:
        clauses.append("upper(prefix) = %s")
        params.append(prefs[0])
        return
    clauses.append("upper(prefix) = ANY(%s)")
    params.append(prefs)


def _region_match_values(region: str | None) -> list[str]:
    """japan_censored / 日本有码 → 可匹配的 region 列取值。

    含旧写真区遗留：japan_gravure / 日本写真 / 写真。
    """
    from app.core.region_meta import REGION_META, resolve_fs_region

    raw = str(region or "").strip()
    if not raw:
        return []
    values = {raw}
    key = resolve_fs_region(raw) or (raw if raw in REGION_META else "")
    if key and key in REGION_META:
        values.add(key)
        values.add(str(REGION_META[key].get("label") or ""))
    for rid, meta in REGION_META.items():
        label = str(meta.get("label") or "")
        if raw == label or raw == rid:
            values.add(rid)
            values.add(label)
    # 写真已并入有码：查有码时一并命中旧区磁盘/库行
    if key == "japan_censored" or raw in {
        "japan_censored",
        "日本有码",
        "有码",
        "japan_gravure",
        "日本写真",
        "写真",
    }:
        values.update({"japan_gravure", "日本写真", "写真"})
    return [v for v in values if v]


def _list_items_uncached(
    *,
    region: str = "",
    prefix: str = "",
    q: str = "",
    genre: str = "",
    tag: str = "",
    studio: str = "",
    actress: str = "",
    signal: str = "",
    sort: str = "code",
    order: str = "asc",
    offset: int = 0,
    limit: int = 36,
    exclude_skeleton: bool = False,
    display_only: bool = False,
) -> dict[str, Any]:
    """分页浏览刮削库条目（海报墙）— 无缓存实现。"""
    ensure_schema()
    off = max(0, int(offset or 0))
    lim = max(1, min(100, int(limit or 36)))
    pref = str(prefix or "").strip().upper()
    query = str(q or "").strip()
    genre_q = str(genre or "").strip()
    tag_q = str(tag or "").strip()
    studio_q = str(studio or "").strip()
    actress_q = str(actress or "").strip()
    signal_q = str(signal or "").strip().lower()
    sort_key = str(sort or "code").strip().lower()
    ascending = str(order or "asc").strip().lower() not in {
        "desc",
        "descending",
        "down",
    }

    clauses: list[str] = ["TRUE"]
    params: list[Any] = []
    if display_only:
        # 有本地海报即可（含磁盘已落图、向量仍标 skeleton 的 FC2-PPV 等）
        clauses.append("coalesce(poster_path, '') <> ''")
    elif exclude_skeleton:
        clauses.append(_NOT_SKELETON_SQL)
    match = _region_match_values(region)
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    if pref:
        _append_prefix_clause(clauses, params, pref)
    if query:
        like = f"%{query}%"
        clauses.append(
            """(
              code ILIKE %s
              OR title ILIKE %s
              OR prefix ILIKE %s
              OR NULLIF(substring(source_text from '片商：(.+?)(?:\\n|$)'), '') ILIKE %s
            )"""
        )
        params.extend([like, like, like, like])
    if genre_q:
        # source_text 行：类型：a b c
        clauses.append("source_text ILIKE %s")
        params.append(f"%类型：%{genre_q}%")
    if tag_q:
        # 兼容旧入口：把「未标注女优」等落到女优缺省条件
        if tag_q in {"未标注女优", "未标注", "(unknown)"}:
            _append_actress_clause(clauses, params, tag_q)
        else:
            # 真·标签行，或回退女优名（精确分词，避免 ILIKE 误伤）
            clauses.append(
                f"""(
                  EXISTS (
                    SELECT 1
                    FROM unnest(
                      regexp_split_to_array(
                        trim(NULLIF(substring(source_text from '标签：(.+?)(?:\\n|$)'), '')),
                        '{_TOKEN_SPLIT_SQL}'
                      )
                    ) AS tok
                    WHERE trim(tok) = %s
                  )
                  OR EXISTS (
                    SELECT 1
                    FROM unnest(
                      regexp_split_to_array(trim({_ACTRESS_LINE_SQL}), '{_TOKEN_SPLIT_SQL}')
                    ) AS tok
                    WHERE trim(tok) = %s
                  )
                )"""
            )
            params.extend([tag_q, tag_q])
    if studio_q:
        _append_studio_clause(clauses, params, studio_q, region=region)
    if actress_q:
        _append_actress_clause(clauses, params, actress_q)
    if signal_q in {"cnsub", "中字", "字幕"}:
        clauses.append(
            "(source_text ILIKE %s OR source_text ILIKE %s OR source_text ILIKE %s)"
        )
        params.extend(["%字幕：中字%", "%角标：%中字%", "%角标：%字幕%"])
    elif signal_q in {"hd", "4k", "uhd"}:
        clauses.append(
            "(source_text ILIKE %s OR source_text ILIKE %s OR source_text ILIKE %s)"
        )
        params.extend(["%清晰度：%", "%角标：%4K%", "%角标：%HD%"])
    elif signal_q in {"uncensored", "无码"}:
        clauses.append(
            "(source_text ILIKE %s OR source_text ILIKE %s OR source_text ILIKE %s)"
        )
        params.extend(["%马赛克：无码%", "%角标：%无码%", "%角标：%uncensored%"])
    elif signal_q in {"leak", "流出"}:
        clauses.append("(source_text ILIKE %s OR source_text ILIKE %s)")
        params.extend(["%角标：%流出%", "%角标：%leak%"])
    elif signal_q in {"crack", "破解"}:
        clauses.append("(source_text ILIKE %s OR source_text ILIKE %s)")
        params.extend(["%角标：%破解%", "%角标：%crack%"])
    where = " AND ".join(clauses)

    if sort_key in {"recent", "updated", "new", "dateadded"}:
        order_sql = (
            f"updated_at {'ASC' if ascending else 'DESC'} NULLS LAST, code DESC"
        )
    elif sort_key in {"year", "premiere", "date"}:
        # 年份：2024；同年份按番号新→旧
        order_sql = (
            f"(NULLIF(substring(source_text from '年份：([0-9]{{4}})'), ''))::int "
            f"{'ASC' if ascending else 'DESC'} NULLS LAST, "
            f"code {'ASC' if ascending else 'DESC'}"
        )
    elif sort_key in {"name", "title"}:
        order_sql = (
            f"title {'ASC' if ascending else 'DESC'} NULLS LAST, code ASC"
        )
    elif sort_key in {"studio", "maker", "片商"}:
        order_sql = (
            f"NULLIF(substring(source_text from '片商：(.+?)(?:\\n|$)'), '') "
            f"{'ASC' if ascending else 'DESC'} NULLS LAST, code ASC"
        )
    elif sort_key in {"prefix", "前缀"}:
        order_sql = (
            f"prefix {'ASC' if ascending else 'DESC'} NULLS LAST, "
            f"code {'ASC' if ascending else 'DESC'}"
        )
    elif sort_key in {"actress", "actor", "女优"}:
        # 取女优行首个名字（空格分隔）
        order_sql = (
            f"NULLIF(split_part(substring(source_text from '女优：(.+?)(?:\\n|$)'), ' ', 1), '') "
            f"{'ASC' if ascending else 'DESC'} NULLS LAST, code ASC"
        )
    elif sort_key in {"random", "rand", "shuffle"}:
        order_sql = "random()"
    else:
        # 番号 / 默认
        order_sql = (
            f"prefix {'ASC' if ascending else 'DESC'}, "
            f"code {'ASC' if ascending else 'DESC'}, item_id ASC"
        )

    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*)::int AS n FROM {TABLE} WHERE {where}", params)
            total_row = cur.fetchone()
            total = int(
                (total_row.get("n") if isinstance(total_row, dict) else total_row[0])
                or 0
            )
            cur.execute(
                f"""
                SELECT
                  item_id, region, prefix, code, title, source_text, rel_path,
                  poster_path, thumb_path, fanart_path, cover_url
                FROM {TABLE}
                WHERE {where}
                ORDER BY {order_sql}
                OFFSET %s LIMIT %s
                """,
                [*params, off, lim],
            )
            rows = list(cur.fetchall())

    items = [
        _hit_from_row(row)
        for row in rows
        if isinstance(row, dict)
    ]
    return {
        "total": total,
        "offset": off,
        "limit": lim,
        "items": items,
    }


_ITEMS_HUB_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


_ITEMS_HUB_CACHE_TTL_S = 90.0


_ITEMS_HUB_CACHE_MAX = 64


def list_items(
    *,
    region: str = "",
    prefix: str = "",
    q: str = "",
    genre: str = "",
    tag: str = "",
    studio: str = "",
    actress: str = "",
    signal: str = "",
    sort: str = "code",
    order: str = "asc",
    offset: int = 0,
    limit: int = 36,
    exclude_skeleton: bool = False,
    display_only: bool = False,
) -> dict[str, Any]:
    """分页浏览刮削库条目（海报墙）。

    无过滤条件的一级影片墙走短 TTL 内存缓存，切换页/重进更快。
    """
    hub_level = not any(
        (
            str(prefix or "").strip(),
            str(q or "").strip(),
            str(genre or "").strip(),
            str(tag or "").strip(),
            str(studio or "").strip(),
            str(actress or "").strip(),
            str(signal or "").strip(),
        )
    )
    cache_key = ""
    if hub_level:
        cache_key = (
            f"v2|{region}|{sort}|{order}|{int(offset or 0)}|{int(limit or 36)}"
            f"|sk={1 if exclude_skeleton else 0}|d={1 if display_only else 0}"
        )
        now = time.monotonic()
        prune_by_age(_ITEMS_HUB_CACHE, _ITEMS_HUB_CACHE_TTL_S, now=now)
        hit = _ITEMS_HUB_CACHE.get(cache_key)
        if hit and now - hit[0] < _ITEMS_HUB_CACHE_TTL_S:
            return dict(hit[1])

    data = _list_items_uncached(
        region=region,
        prefix=prefix,
        q=q,
        genre=genre,
        tag=tag,
        studio=studio,
        actress=actress,
        signal=signal,
        sort=sort,
        order=order,
        offset=offset,
        limit=limit,
        exclude_skeleton=exclude_skeleton,
        display_only=display_only,
    )
    if hub_level and cache_key:
        _ITEMS_HUB_CACHE[cache_key] = (time.monotonic(), dict(data))
        enforce_max(_ITEMS_HUB_CACHE, _ITEMS_HUB_CACHE_MAX)
    return data


_FACET_LINE_RE = {
    "genre": re.compile(r"^类型：(.+)$", re.M),
    "tag": re.compile(r"^标签：(.+)$", re.M),
    "studio": re.compile(r"^片商：(.+)$", re.M),
    "actress": re.compile(r"^女优：(.+)$", re.M),
}


_CODEISH_RE = re.compile(r"^[A-Za-z]{1,12}-?\d{0,6}[A-Za-z]?$")


_STUDIO_ANNOT_RE = re.compile(
    r"[（(\[<＜【].*?[）)\]>＞】]|［.*?］"
)


def _studio_display_name(name: str) -> str:
    """展示用：优先映射表短名，否则 NFKC + 去注音。"""
    from app.scrap_library.studio_display_names import resolve_studio_display

    mapped = resolve_studio_display(name)
    if mapped:
        return mapped
    import unicodedata

    s = unicodedata.normalize("NFKC", str(name or "")).strip()
    s = _STUDIO_ANNOT_RE.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(".")
    return s or str(name or "").strip()


def _studio_match_key(name: str) -> str:
    """合并别名键：映射表收拢 + First Star / FirstStar 等标点归一。"""
    from app.scrap_library.studio_display_names import resolve_studio_canon_key, studio_norm_key

    canon = resolve_studio_canon_key(name)
    if canon:
        return canon
    return studio_norm_key(name)


def _studio_norm_sql(expr: str) -> str:
    """SQL 侧与 studio_norm_key 对齐的规范化表达式。"""
    # 去掉常见括号注音 + 空白/标点（PostgreSQL lower ≈ ASCII；日文原样保留）
    return (
        "regexp_replace("
        "regexp_replace("
        f"lower(trim(coalesce({expr}, ''))),"
        r" '[（(\\[＜<【［][^）)\\]>＞】］]*[）)\\]>＞】］]', '', 'g'"
        "),"
        r" '[\s\-_.·・/／\\]+', '', 'g'"
        ")"
    )


def _append_studio_clause(
    clauses: list[str],
    params: list[Any],
    studio: str,
    *,
    region: str = "",
) -> None:
    """厂牌筛选：优先按「前缀→厂牌」标准表（catalog 分区优先），不依赖 NFO 片商字段。"""
    from app.scrap_library.studio_display_names import (
        all_mapped_prefixes,
        prefixes_for_studio_query,
        studio_filter_norm_keys,
    )

    studio_q = str(studio or "").strip()
    if not studio_q:
        return
    if studio_q in {"未标注厂牌", "未标注", "(unknown)"}:
        mapped = all_mapped_prefixes(region)
        if mapped:
            clauses.append(
                "(coalesce(prefix, '') = '' OR upper(prefix) <> ALL(%s))"
            )
            params.append(mapped)
        else:
            clauses.append("coalesce(prefix, '') = ''")
        return

    prefs = prefixes_for_studio_query(studio_q, region=region)
    if prefs:
        clauses.append("upper(coalesce(prefix, '')) = ANY(%s)")
        params.append(prefs)
        return

    # 映射表无此前缀集合时，回退 NFO 片商（罕见）
    keys = studio_filter_norm_keys(studio_q)
    if not keys:
        clauses.append(f"trim({_STUDIO_LINE_SQL}) = %s")
        params.append(studio_q)
        return
    if len(keys) == 1:
        clauses.append(f"{_studio_norm_sql(_STUDIO_LINE_SQL)} = %s")
        params.append(keys[0])
        return
    clauses.append(f"{_studio_norm_sql(_STUDIO_LINE_SQL)} = ANY(%s)")
    params.append(keys)


def _split_tokens(raw: str) -> list[str]:
    out: list[str] = []
    for token in re.split(r"[\s/|、，,]+", str(raw or "")):
        name = token.strip()
        if name:
            out.append(name)
    return out


_FACETS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


_FACETS_SNAP_DIR = ("cache", "facets")


_FACETS_SNAP_VERSION = 4


_FACETS_SNAP_KINDS = ("genre", "actress", "studio", "tag")


_facets_snap_lock = threading.Lock()


def list_facets(
    *,
    region: str = "",
    kind: str = "genre",
    studio: str = "",
    prefix: str = "",
    q: str = "",
    sort: str = "count",
    order: str = "desc",
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    """从 source_text 汇总流派 / 标签 / 片商；支持排序与分页。

    无 studio/prefix 过滤时优先读磁盘快照；冷 miss 会现场聚合并写回快照。
    """
    key = _normalize_facet_kind(kind)
    studio_q = str(studio or "").strip()
    pref = str(prefix or "").strip().upper()
    query = str(q or "").strip()
    cache_key = f"v10|{region}|{key}|{studio_q}|{pref}"
    hub_level = not studio_q and not pref

    now = time.monotonic()
    prune_by_age(_FACETS_CACHE, _FACETS_CACHE_TTL_S, now=now)
    hit = _FACETS_CACHE.get(cache_key)
    if hit and now - hit[0] < _FACETS_CACHE_TTL_S:
        rows = list(hit[1])
    else:
        rows = None
        if hub_level:
            rows = _load_facets_snapshot(region, key)
        if rows is None:
            rows = _build_facets_all(
                region=region, kind=key, studio=studio_q, prefix=pref
            )
            if hub_level:
                try:
                    _save_facets_snapshot(region, key, rows)
                except Exception as e:  # noqa: BLE001
                    log.warning("facets snapshot write failed: %s", e)
        _FACETS_CACHE[cache_key] = (now, list(rows))
        enforce_max(_FACETS_CACHE, _FACETS_CACHE_MAX)

    if key == "studio":
        # 已按前缀标准表建好，再合并别名展示
        rows = _merge_studio_facets(rows)

    if query:
        ql = query.casefold()
        rows = [
            r
            for r in rows
            if ql in str((r or {}).get("name") or "").casefold()
            or ql in str((r or {}).get("blurb") or "").casefold()
        ]

    if key == "actress":
        try:
            from app.scrap_library.actress_bio import fold_key
            from app.scrap_library.actress_store import actress_ages_for_names

            ages = actress_ages_for_names(
                [str((r or {}).get("name") or "") for r in rows]
            )
            for r in rows:
                fk = fold_key(str((r or {}).get("name") or ""))
                age = ages.get(fk)
                if age is not None:
                    r["age"] = age
                else:
                    r.pop("age", None)
        except Exception as e:  # noqa: BLE001
            log.debug("apply actress ages skipped: %s", e)

    sorted_rows = _sort_facets(rows, sort=sort, order=order)
    if key == "actress":
        try:
            from app.scrap_library.actress_avatar import apply_actress_avatars

            sorted_rows = apply_actress_avatars(sorted_rows)
        except Exception as e:  # noqa: BLE001
            log.debug("apply actress avatars skipped: %s", e)
    total = len(sorted_rows)
    off = max(0, int(offset or 0))
    if limit is None:
        page = sorted_rows[off:]
    else:
        lim = max(1, min(100, int(limit)))
        page = sorted_rows[off : off + lim]
    return {"facets": page, "total": total}


_RECOMMEND_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


_RECOMMEND_SNAP_VERSION = 2


def _recommend_snap_path() -> Path:
    d = data_dir().joinpath(*_FACETS_SNAP_DIR) / "_recommend"
    d.mkdir(parents=True, exist_ok=True)
    return d / "shelves.json"


def search(query: str, *, limit: int = 8, region: str = "") -> list[dict[str, Any]]:
    q = str(query or "").strip()
    if not q:
        return []
    ensure_schema()
    cfg = resolve_embed_config()
    top_k = max(1, min(50, int(limit or cfg.get("topK") or 8)))
    vec = _vec_literal(encode_texts_sync([q], query=True)[0])
    pool = get_meta_pool()
    match = _region_match_values(region)
    # 空壳零向量不参与语义检索
    where_parts = [_DISPLAY_READY_SQL]
    params: list[Any] = [vec]
    if match:
        where_parts.append("region = ANY(%s)")
        params.append(match)
    where_sql = "WHERE " + " AND ".join(where_parts)
    params.extend([vec, top_k])
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  item_id, region, prefix, code, title, source_text, rel_path,
                  poster_path, thumb_path, fanart_path, cover_url,
                  1 - (embedding <=> %s::vector) AS score
                FROM {TABLE}
                {where_sql}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                params,
            )
            rows = list(cur.fetchall())
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(_hit_from_row(row, score=float(row.get("score") or 0)))
    return out


_ACTRESS_OPT_LOCK = threading.Lock()


_actress_opt_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}


_actress_opt_hydrated = False


_actress_opt_hydrate_lock = threading.Lock()


def _hydrate_actress_opt_job(*, force: bool = False) -> dict[str, Any]:
    global _actress_opt_hydrated
    with _actress_opt_hydrate_lock:
        if _actress_opt_hydrated and not force:
            return {}
        _actress_opt_hydrated = True
    try:
        from app.core import job_persist

        raw = job_persist.load_job(job_persist.ACTRESS_OPTIMIZE_JOB_KEY)
        if not raw:
            return {}
        with _ACTRESS_OPT_LOCK:
            if _actress_opt_job.get("running"):
                return raw
            if not _actress_opt_job.get("phase") and raw.get("phase"):
                _actress_opt_job["phase"] = str(raw.get("phase") or "")
            if not _actress_opt_job.get("progress") and raw.get("progress"):
                _actress_opt_job["progress"] = dict(raw.get("progress") or {})
            if not _actress_opt_job.get("log") and raw.get("log"):
                _actress_opt_job["log"] = list(raw.get("log") or [])[-40:]
            if (
                _actress_opt_job.get("result") is None
                and raw.get("result") is not None
            ):
                _actress_opt_job["result"] = raw.get("result")
            if not _actress_opt_job.get("error") and raw.get("error"):
                _actress_opt_job["error"] = raw.get("error")
            if str(raw.get("status") or "") == "running":
                _actress_opt_job["phase"] = "interrupted"
                prog = dict(_actress_opt_job.get("progress") or {})
                prog["label"] = "进程中断 · 可继续"
                _actress_opt_job["progress"] = prog
                raw = dict(raw)
                raw["status"] = "interrupted"
                raw["running"] = False
                job_persist.save_job(job_persist.ACTRESS_OPTIMIZE_JOB_KEY, raw)
        return raw
    except Exception as e:  # noqa: BLE001
        log.warning("hydrate actress optimize job failed: %s", e)
        return {}


def local_file_api(rel: str) -> str:
    """前端可直接请求的本地封面接口路径。"""
    from urllib.parse import quote

    r = str(rel or "").replace("\\", "/").lstrip("/")
    if not r:
        return ""
    return f"/scrap-library/file?path={quote(r, safe='')}"


def resolve_local_file(rel: str) -> Path:
    """把 media 相对路径解析为绝对文件；禁止逃逸。

    兼容 FC2 目录迁移：扁平 FC2/{CODE}、旧夹名 FC2PPV → 现行 FC2/FC2|FC2-PPV。
    """
    text = str(rel or "").strip().replace("\\", "/").lstrip("/")
    parts = [x for x in Path(text).parts if x not in ("", ".", "/")]
    if not parts or any(x == ".." for x in parts):
        raise ValueError("非法路径")
    root = media_dir().resolve()
    candidates = [parts, *_fc2_rel_path_aliases(parts)]
    seen: set[str] = set()
    last_miss = text
    for cand in candidates:
        key = "/".join(cand)
        if key in seen:
            continue
        seen.add(key)
        abs_path = (root / Path(*cand)).resolve()
        try:
            abs_path.relative_to(root)
        except ValueError as e:
            raise ValueError("路径越界") from e
        if abs_path.is_file():
            return abs_path
        last_miss = key
    raise FileNotFoundError(f"文件不存在: {last_miss}")


# ==========================================================================
# 以下名字已搬到兄弟模块；此处再导出，保证 `embed.NAME` 调用/打补丁零改动。
# 注意：必须放在文件末尾 —— 兄弟模块会回引本模块的名字，
#       等本模块顶层全部定义完再导入，才能避免循环导入。
# ==========================================================================
from app.scrap_library.embed_actress_opt import (  # noqa: E402
    _append_actress_clause, _split_actress_tokens, _persist_actress_opt_job, get_actress_optimize_status, _actress_opt_log, _actress_opt_progress,
    optimize_actress_metadata, start_actress_optimize_job,
)
from app.scrap_library.embed_catalog import (  # noqa: E402
    ProgressCb, SKELETON_SHA_PREFIX, is_skeleton_sha, _catalog_code_locations, _catalog_prefix_labels, relocate_disk_prefix_dirs,
    realign_embed_locations, upsert_catalog_skeletons, purge_catalog_skeletons, rebuild_catalog_skeletons, reset_embed_to_catalog_skeletons, prune_embed_not_in_catalog,
    prune_embed_missing_from_disk, prune_embed_missing_from_disk_ids, prune_embed_orphans_by_ids, _SKELETON_SQL, _NOT_SKELETON_SQL, _quality_region_sql,
    _catalog_region_ids, _shell_rel_path, iter_catalog_shell_items, count_catalog_shells, list_catalog_shell_items, count_skeleton_shells,
    _dedup_appender, _folder_file_names, _scan_workers, _scan_one_nfo, _scan_items, _existing_embed_rows,
    _existing_shas, _meta_iter_batches, vectorize_db_embeddings, _folder_prefix_aliases, _canonical_folder_prefix, _fc2_rel_path_aliases,
    resolve_existing_media_rel,
)
from app.scrap_library.embed_facets import (  # noqa: E402
    _DISPLAY_READY_SQL, list_regions, list_prefixes, _STUDIO_LINE_SQL, _ACTRESS_LINE_SQL, _TOKEN_SPLIT_SQL,
    _build_studio_facets_by_prefix, _merge_studio_facets, _null_studio_prefix_buckets, _absorb_facet_media, _reattribute_unlabeled_studios, _FACETS_CACHE_TTL_S,
    _FACETS_CACHE_MAX, _normalize_facet_kind, _facet_media_refs, _facet_row, _build_facets_sql_line_tokens, _build_facets_all,
    _sort_facets, _facets_snap_region_key, _facets_snap_path, _load_facets_snapshot, _save_facets_snapshot, _purge_facets_memory_cache,
    facets_snapshot_meta, _facets_snapshot_meta_one, refresh_facets_snapshot,
)
from app.scrap_library.embed_poster import (  # noqa: E402
    _blank_pixels, _blank_from_pixels, _image_looks_blank, _image_bytes_looks_blank, _image_magic_ok, _is_blank_cover_rel,
    _pick_collage_posters, _pick_local_image, _trim_poster_dl_fails, _write_poster_jpg, download_remote_poster, _update_item_poster_path,
    ensure_local_poster, ensure_local_poster_by_cover, _poster_dl_worker_loop, schedule_ensure_local_poster, _sample_prefix_disk_posters,
)
from app.scrap_library.embed_recommend import (  # noqa: E402
    list_recommend, _RECOMMEND_CACHE_TTL_S, _load_recommend_snapshot, _save_recommend_snapshot, _build_recommend, refresh_recommend_snapshot,
)
