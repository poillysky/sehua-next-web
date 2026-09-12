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

ProgressCb = Callable[[dict[str, Any]], None]

_job_lock = threading.Lock()
_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
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


def resolve_root(raw: str | None = None) -> Path:
    text = str(raw or "").strip() or DEFAULT_REL_ROOT
    p = Path(text)
    if p.is_absolute():
        return p.resolve()
    parts = [x for x in p.parts if x not in ("", ".")]
    if any(x == ".." for x in parts):
        raise ValueError("相对路径不能包含 ..")
    base = media_dir()
    return (base / Path(*parts)).resolve() if parts else base.resolve()


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
        conn.commit()
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


SKELETON_SHA_PREFIX = "skeleton:v1"


def is_skeleton_sha(sha: str | None) -> bool:
    return str(sha or "").startswith(SKELETON_SHA_PREFIX)


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


def upsert_catalog_skeletons(
    *,
    on_progress: ProgressCb | None = None,
    batch_size: int = 4000,
) -> dict[str, Any]:
    """按七区目录 1:1 同步番号骨架到向量库。

    - 目录无 / 向量有 → 删（prune_embed_not_in_catalog）
    - 目录有 / 向量无 → 插入仅骨架行（空壳态）
    - 两边都有（含已刮削）→ 跳过，绝不覆盖清零
    - 同番号多区/多前缀只保留一条骨架（先出现的区优先）
    - embedding 用零向量占位；语义检索排除骨架
    """
    import app.prefix.catalog_store as store
    from app.prefix.catalog_strm_sync import safe_name
    from app.core.region_meta import REGION_META, REGION_ORDER

    def prog(stage: str, **kw: Any) -> None:
        payload = {"stage": stage, **kw}
        if on_progress:
            on_progress(payload)

    t0 = time.monotonic()
    cfg = resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        prog("skeleton", percent=100, label="嵌入未启用，跳过骨架同步")
        return {
            "ok": False,
            "skipped": True,
            "reason": "embed_disabled",
            "inserted": 0,
            "skipped_existing": 0,
            "purged": 0,
            "purged_codes": 0,
            "total": 0,
        }

    schema = ensure_schema()
    dim = int(schema["dim"])
    model_name = str(cfg["model"])
    zero_vec = _zero_vec_literal(dim)

    prog("skeleton", percent=2, label="按目录清理多余向量…")
    try:
        purged_codes = prune_embed_not_in_catalog()
    except Exception as e:  # noqa: BLE001
        prog("skeleton", percent=100, label=f"清多余向量失败 · {e}")
        return {
            "ok": False,
            "skipped": False,
            "error": f"prune: {e}",
            "inserted": 0,
            "skipped_existing": 0,
            "purged": 0,
            "purged_codes": 0,
            "total": 0,
        }

    prog("skeleton", percent=6, label="加载七区目录…", done=0, total=None)
    doc = store.load_catalog(force=True)
    # 按番号去重：同 code 多路径只插一条
    jobs: list[tuple[str, str, str, str, str]] = []
    seen_job_codes: set[str] = set()
    dup_paths = 0
    for rid in REGION_ORDER:
        reg = doc["regions"].get(rid) or {}
        label = str(reg.get("label") or REGION_META.get(rid, {}).get("label") or rid)
        r_name = safe_name(label)
        for pref, ent in (reg.get("prefixes") or {}).items():
            p_name = safe_name(str(pref))
            for code in store.codes_of(ent):
                c = str(code or "").strip()
                if not c:
                    continue
                code_u = c.upper()
                if code_u in seen_job_codes:
                    dup_paths += 1
                    continue
                seen_job_codes.add(code_u)
                c_name = safe_name(c)
                rel = f"{r_name}/{p_name}/{c_name}"
                jobs.append((label, str(pref), code_u, rel, item_id_from_rel(rel)))

    total = len(jobs)
    prog(
        "skeleton",
        percent=10,
        label=f"比对已有向量 · {total:,}",
        done=0,
        total=total,
    )

    pool = get_meta_pool()
    existing_ids: set[str] = set()
    existing_codes: set[str] = set()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT item_id, code FROM {TABLE}")
        for row in cur.fetchall() or []:
            if isinstance(row, dict):
                iid = str(row.get("item_id") or "").strip()
                code = str(row.get("code") or "").strip().upper()
            else:
                iid = str(row[0] or "").strip()
                code = str(row[1] or "").strip().upper()
            if iid:
                existing_ids.add(iid)
            if code:
                existing_codes.add(code)

    pending: list[tuple[str, str, str, str, str]] = []
    skipped_existing = 0
    for row in jobs:
        _label, _pref, code_u, _rel, iid = row
        if iid in existing_ids or code_u in existing_codes:
            skipped_existing += 1
            continue
        pending.append(row)
        existing_ids.add(iid)
        existing_codes.add(code_u)

    prog(
        "skeleton",
        percent=14,
        label=f"待写入骨架 {len(pending):,} · 跳过已有 {skipped_existing:,}",
        done=0,
        total=len(pending),
    )

    insert_sql = f"""
        INSERT INTO {TABLE}
          (item_id, region, prefix, code, rel_path, title,
           poster_path, thumb_path, fanart_path, cover_url,
           model, dim, content_sha, source_text, embedding, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
        ON CONFLICT (item_id) DO NOTHING
    """
    inserted = 0
    bs = max(500, min(8000, int(batch_size or 4000)))
    try:
        if pending:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    for i in range(0, len(pending), bs):
                        chunk = pending[i : i + bs]
                        rows = []
                        for region, prefix, code_u, rel, iid in chunk:
                            src = _skeleton_source_text(code_u)
                            rows.append(
                                [
                                    iid,
                                    region,
                                    prefix,
                                    code_u,
                                    rel,
                                    "",
                                    "",
                                    "",
                                    "",
                                    "",
                                    model_name,
                                    dim,
                                    _skeleton_content_sha(
                                        code_u, model=model_name, dim=dim
                                    ),
                                    src,
                                    zero_vec,
                                ]
                            )
                        cur.executemany(insert_sql, rows)
                        conn.commit()
                        inserted += len(chunk)
                        pct = 14 + int(84 * inserted / max(1, len(pending)))
                        prog(
                            "skeleton",
                            percent=min(98, pct),
                            label=f"骨架写入 {inserted:,}/{len(pending):,}",
                            done=inserted,
                            total=len(pending),
                        )
    except Exception as e:  # noqa: BLE001
        prog(
            "skeleton",
            percent=100,
            label=f"骨架写入中断 · 已写 {inserted:,} · {e}",
            done=inserted,
            total=len(pending),
        )
        return {
            "ok": False,
            "skipped": False,
            "error": str(e),
            "inserted": inserted,
            "skipped_existing": skipped_existing,
            "purged": 0,
            "purged_codes": purged_codes,
            "total": total,
            "pending": len(pending),
            "dup_paths": dup_paths,
            "elapsed_sec": round(time.monotonic() - t0, 1),
            "dim": dim,
            "meta_db": meta_dsn_label(),
            "table": TABLE,
        }

    elapsed = round(time.monotonic() - t0, 1)
    prog(
        "skeleton",
        percent=100,
        label=(
            f"骨架同步完成 · 新写入 {inserted:,} · 跳过 {skipped_existing:,}"
            f" · 清目录外 {purged_codes:,} · {elapsed}s"
        ),
        done=inserted,
        total=len(pending),
    )
    return {
        "ok": True,
        "skipped": False,
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "purged": 0,
        "purged_codes": purged_codes,
        "total": total,
        "pending": len(pending),
        "dup_paths": dup_paths,
        "elapsed_sec": elapsed,
        "dim": dim,
        "meta_db": meta_dsn_label(),
        "table": TABLE,
    }


def purge_catalog_skeletons() -> int:
    """删除 content_sha 标记为 skeleton 的骨架行（手动/维护用）。"""
    ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {TABLE} WHERE content_sha LIKE %s",
            (f"{SKELETON_SHA_PREFIX}:%",),
        )
        n = int(cur.rowcount or 0)
        conn.commit()
    return n


def reset_embed_to_catalog_skeletons(
    *,
    on_progress: ProgressCb | None = None,
    batch_size: int = 4000,
) -> dict[str, Any]:
    """清空向量库全部行，再按七区目录 1:1 重建仅番号骨架。

    用于「刮削前只留骨架、逐号重刮入库」测试/重建。
    不删本地 scrap-library 磁盘上的 NFO/封面；单号 overwrite 刮削时会覆盖写回。
    """
    def prog(stage: str, **kw: Any) -> None:
        if on_progress:
            on_progress({"stage": stage, **kw})

    ensure_schema()
    pool = get_meta_pool()
    prog("reset", percent=2, label="统计现有行…")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS c FROM {TABLE}")
        before = int(dict(cur.fetchone() or {}).get("c") or 0)
        cur.execute(
            f"SELECT count(*) AS c FROM {TABLE} WHERE content_sha LIKE %s",
            (f"{SKELETON_SHA_PREFIX}:%",),
        )
        before_skel = int(dict(cur.fetchone() or {}).get("c") or 0)

    prog("reset", percent=8, label=f"清空向量表 · {before:,} 行…")
    with pool.connection() as conn, conn.cursor() as cur:
        # TRUNCATE 快；无表则 DELETE
        try:
            cur.execute(f"TRUNCATE TABLE {TABLE}")
        except Exception:  # noqa: BLE001
            cur.execute(f"DELETE FROM {TABLE}")
        deleted = before
        conn.commit()

    # 清分面缓存，避免旧聚合
    try:
        _FACETS_CACHE.clear()
        _ITEMS_HUB_CACHE.clear()
        _RECOMMEND_CACHE.clear()
    except Exception:  # noqa: BLE001
        pass

    prog("reset", percent=20, label="按目录重建骨架…")
    sync = upsert_catalog_skeletons(on_progress=on_progress, batch_size=batch_size)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS c FROM {TABLE}")
        after = int(dict(cur.fetchone() or {}).get("c") or 0)
        cur.execute(
            f"SELECT count(*) AS c FROM {TABLE} WHERE content_sha LIKE %s",
            (f"{SKELETON_SHA_PREFIX}:%",),
        )
        after_skel = int(dict(cur.fetchone() or {}).get("c") or 0)

    prog(
        "reset",
        percent=100,
        label=f"完成 · 删 {deleted:,} · 骨架 {after_skel:,}",
        done=after_skel,
        total=after_skel,
    )
    return {
        "ok": bool(sync.get("ok", True)) and not sync.get("error"),
        "deleted": deleted,
        "before": before,
        "beforeSkeletons": before_skel,
        "after": after,
        "afterSkeletons": after_skel,
        "skeletonSync": sync,
    }


def catalog_code_set() -> set[str]:
    """七区目录全部番号（大写）。"""
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


def prune_embed_not_in_catalog() -> int:
    """删除向量库中番号不在七区目录里的行（多的删）。"""
    ensure_schema()
    codes = catalog_code_set()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        if not codes:
            # 目录空：只清带番号的行，避免误删异常空 code
            cur.execute(
                f"""
                DELETE FROM {TABLE}
                WHERE coalesce(trim(code), '') <> ''
                """
            )
        else:
            cur.execute(
                f"""
                DELETE FROM {TABLE}
                WHERE coalesce(trim(code), '') <> ''
                  AND upper(trim(code)) <> ALL(%s)
                """,
                (list(codes),),
            )
        n = int(cur.rowcount or 0)
        conn.commit()
    return n


def prune_embed_missing_from_disk(root: Path) -> int:
    """删除刮削库磁盘上已无 NFO 目录的向量行；目录空壳（skeleton）保留。"""
    ensure_schema()
    root_resolved = Path(root).resolve()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT item_id, rel_path, content_sha FROM {TABLE}")
        rows = cur.fetchall() or []
    dead: list[str] = []
    for r in rows:
        if isinstance(r, dict):
            iid = str(r.get("item_id") or "").strip()
            rel = str(r.get("rel_path") or "").replace("\\", "/").strip().strip("/")
            sha = str(r.get("content_sha") or "")
        else:
            iid = str(r[0] or "").strip()
            rel = str(r[1] or "").replace("\\", "/").strip().strip("/")
            sha = str(r[2] or "") if len(r) > 2 else ""
        if not iid:
            continue
        # 空壳无本地 NFO 是常态，留给刮削补齐
        if is_skeleton_sha(sha):
            continue
        folder = root_resolved / rel if rel else root_resolved
        try:
            if folder.is_dir() and any(folder.glob("*.nfo")):
                continue
        except OSError:
            pass
        dead.append(iid)
    if not dead:
        return 0
    n = 0
    with pool.connection() as conn, conn.cursor() as cur:
        for i in range(0, len(dead), 800):
            chunk = dead[i : i + 800]
            cur.execute(
                f"DELETE FROM {TABLE} WHERE item_id = ANY(%s)",
                (chunk,),
            )
            n += int(cur.rowcount or 0)
        conn.commit()
    return n


def prune_embed_missing_from_disk_ids(alive_ids: set[str]) -> int:
    """按存活 item_id 集合删除（兼容旧调用）。"""
    return prune_embed_orphans_by_ids(alive_ids)


def prune_embed_orphans_by_ids(alive_ids: set[str]) -> int:
    """删除不在 alive_ids 中的向量行。"""
    ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        if not alive_ids:
            cur.execute(f"DELETE FROM {TABLE}")
            n = int(cur.rowcount or 0)
        else:
            cur.execute(f"SELECT item_id FROM {TABLE}")
            rows = cur.fetchall() or []
            existing = {
                str((r.get("item_id") if isinstance(r, dict) else r[0]) or "")
                for r in rows
            }
            dead = [iid for iid in existing if iid and iid not in alive_ids]
            n = 0
            for i in range(0, len(dead), 800):
                chunk = dead[i : i + 800]
                cur.execute(
                    f"DELETE FROM {TABLE} WHERE item_id = ANY(%s)",
                    (chunk,),
                )
                n += int(cur.rowcount or 0)
        conn.commit()
    return n


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

# 空壳 = 向量库仅番号骨架（content_sha 带 skeleton 前缀），待刮削补齐
# %% → 字面 %（psycopg 与其它 %s 同句时不可写裸 %）
_SHELL_GAPS = list(QUALITY_KINDS)
_SKELETON_SQL = f"content_sha LIKE '{SKELETON_SHA_PREFIX}:%%'"
_NOT_SKELETON_SQL = f"content_sha NOT LIKE '{SKELETON_SHA_PREFIX}:%%'"


def _quality_region_sql(region: str) -> tuple[str, list[Any]]:
    values = _region_match_values(region)
    if not values:
        return "", []
    return " AND region = ANY(%s)", [values]


def _catalog_region_ids(region: str) -> list[str]:
    """quality/enrich 用的目录区 id 列表；空 = 七区全开。"""
    from app.core.region_meta import REGION_META, REGION_ORDER, resolve_fs_region

    raw = str(region or "").strip()
    if not raw:
        return list(REGION_ORDER)
    key = resolve_fs_region(raw) or (raw if raw in REGION_META else "")
    if key and key in REGION_META:
        return [key]
    for rid, meta in REGION_META.items():
        if raw == rid or raw == str(meta.get("label") or ""):
            return [rid]
    return []


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


def _shell_rel_path(region_label: str, prefix: str, code: str) -> str:
    from app.prefix.catalog_strm_sync import safe_name

    return (
        f"{safe_name(region_label)}/"
        f"{safe_name(prefix)}/"
        f"{safe_name(code)}"
    )


def iter_catalog_shell_items(region: str = "") -> Any:
    """目录有、向量库完全没有的番号（骨架同步未跑完时的兜底）。"""
    import app.prefix.catalog_store as store
    from app.core.region_meta import REGION_META

    existing = _embed_code_set(region)
    try:
        doc = store.load_catalog(force=False)
    except Exception:  # noqa: BLE001
        return
    regions = (doc or {}).get("regions") or {}
    for rid in _catalog_region_ids(region):
        reg = regions.get(rid) or {}
        label = str(
            reg.get("label") or REGION_META.get(rid, {}).get("label") or rid
        ).strip()
        for pref, ent in (reg.get("prefixes") or {}).items():
            pref_s = str(pref or "").strip()
            try:
                codes = store.codes_of(ent)
            except Exception:  # noqa: BLE001
                continue
            for code in codes:
                cu = str(code or "").strip().upper()
                if not cu or cu in existing:
                    continue
                p = pref_s or (cu.split("-", 1)[0] if "-" in cu else cu)
                rel = _shell_rel_path(label, p, cu)
                yield {
                    "itemId": rel,
                    "region": label,
                    "prefix": p,
                    "code": cu,
                    "title": cu,
                    "relPath": rel,
                    "gaps": list(_SHELL_GAPS),
                    "shell": True,
                }


def count_catalog_shells(region: str = "") -> int:
    return sum(1 for _ in iter_catalog_shell_items(region))


def list_catalog_shell_items(
    region: str = "",
    *,
    limit: int = 0,
    offset: int = 0,
) -> list[dict[str, Any]]:
    off = max(0, int(offset or 0))
    lim = int(limit or 0)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(iter_catalog_shell_items(region)):
        if i < off:
            continue
        out.append(row)
        if lim > 0 and len(out) >= lim:
            break
    return out


def count_skeleton_shells(region: str = "") -> int:
    """向量库仅骨架（空壳）条数。"""
    ensure_schema()
    region_sql, params = _quality_region_sql(region)
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*) AS n FROM {TABLE}
            WHERE {_SKELETON_SQL}{region_sql}
            """,
            params,
        )
        row = cur.fetchone() or {}
        return int((row.get("n") if isinstance(row, dict) else row[0]) or 0)


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
) -> list[dict[str, Any]]:
    """向量库空壳（仅骨架）队列项。"""
    ensure_schema()
    off = max(0, int(offset or 0))
    lim = int(limit or 0)
    region_sql, params = _quality_region_sql(region)
    sql_params: list[Any] = [*params]
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
            ORDER BY code ASC
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

    def _take(rows: list[dict[str, Any]]) -> None:
        for r in rows:
            iid = str(r.get("itemId") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            out.append(r)

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

    def _take(rows: list[dict[str, Any]]) -> None:
        for r in rows:
            iid = str(r.get("itemId") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            out.append(r)

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

    def _take(rows: list[dict[str, Any]]) -> None:
        for r in rows:
            iid = str(r.get("itemId") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            out.append(r)

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


def _media_rel(path: Path, *, media_root: Path | None = None) -> str:
    """绝对路径 → 相对 media/；失败则空。"""
    try:
        base = media_root if media_root is not None else media_dir().resolve()
        return path.resolve().relative_to(base).as_posix()
    except Exception:
        return ""


def _folder_file_names(folder: Path) -> dict[str, str]:
    """目录内文件：lower(name) → 实际文件名（一次 scandir）。"""
    out: dict[str, str] = {}
    try:
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        out[entry.name.casefold()] = entry.name
                except OSError:
                    continue
    except OSError:
        return {}
    return out


def _blank_pixels(im) -> list:
    """把 PIL Image 缩成 24x24 像素列表（供空图判定复用）。"""
    from PIL import Image as _Image

    rgb = im.convert("RGB")
    small = rgb.resize((24, 24), _Image.Resampling.BILINEAR)
    return list(small.getdata())


def _blank_from_pixels(pixels: list) -> bool:
    """低色彩多样性 / 近灰白平铺 → 视为空封面。"""
    if not pixels:
        return True
    uniq = len({(p[0] >> 3, p[1] >> 3, p[2] >> 3) for p in pixels})
    if uniq <= 18:
        return True
    n = len(pixels)
    means = [sum(p[i] for p in pixels) / n for i in range(3)]
    var = sum((p[i] - means[i]) ** 2 for p in pixels for i in range(3)) / (n * 3)
    if var < 220:
        return True
    # 灰白占位（NOW PRINTING 一类）
    if min(means) > 175 and var < 900 and uniq <= 40:
        return True
    return False


def _image_looks_blank(path: Path) -> bool:
    """低色彩多样性 / 近灰白平铺 → 视为空封面（磁盘文件版）。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            pixels = _blank_pixels(im)
    except Exception:
        return False
    return _blank_from_pixels(pixels)


def _image_bytes_looks_blank(raw: bytes) -> bool:
    """空图判定（内存字节版）：免落盘探测，避免临时文件写删。"""
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            pixels = _blank_pixels(im)
    except Exception:
        return False
    return _blank_from_pixels(pixels)


def _is_blank_cover_file(path: Path) -> bool:
    """本地封面文件是否为源站空图占位。"""
    try:
        size = path.stat().st_size
    except OSError:
        return True
    if size < 12_000:
        return True
    if size >= 80_000:
        return False
    return _image_looks_blank(path)


def _is_blank_cover_bytes(raw: bytes) -> bool:
    """内存版空图判定：阈值与 `_is_blank_cover_file` 完全一致。"""
    size = len(raw or b"")
    if size < 12_000:
        return True
    if size >= 80_000:
        return False
    return _image_bytes_looks_blank(raw)


# 拼贴选图缓存（rel → blank?）
_blank_cover_cache: dict[str, bool] = {}


def _is_blank_cover_rel(rel: str) -> bool:
    r = str(rel or "").strip().replace("\\", "/")
    if not r:
        return True
    hit = _blank_cover_cache.get(r)
    if hit is not None:
        return hit
    try:
        path = resolve_local_file(r)
        blank = _is_blank_cover_file(path)
    except Exception:
        blank = True
    if len(_blank_cover_cache) > 10_000:
        _blank_cover_cache.clear()
    _blank_cover_cache[r] = blank
    return blank


def _pick_collage_posters(
    candidates: list[str] | tuple[str, ...] | None,
    *,
    limit: int = 4,
    scan_limit: int = 24,
) -> list[str]:
    """从候选封面中挑真实海报，跳过空图 / 缺文件。"""
    out: list[str] = []
    seen: set[str] = set()
    scanned = 0
    for raw in candidates or []:
        s = str(raw or "").strip().replace("\\", "/")
        if not s or s in seen:
            continue
        seen.add(s)
        scanned += 1
        if _is_blank_cover_rel(s):
            if scanned >= scan_limit:
                break
            continue
        out.append(s)
        if len(out) >= limit or scanned >= scan_limit:
            break
    return out


def _pick_local_image(
    folder: Path,
    name: str,
    *,
    files: dict[str, str] | None = None,
    media_root: Path | None = None,
) -> str:
    """NFO 里的文件名或 http → 本地 media 相对路径。"""
    raw = str(name or "").strip()
    if not raw or raw.startswith(("http://", "https://")):
        return ""
    clean = raw.replace("\\", "/").lstrip("/")
    if ".." in clean.split("/"):
        return ""
    # 仅支持同目录文件名（刮削库惯例）；带子路径时仍做一次校验
    if "/" in clean:
        p = (folder / clean).resolve()
        try:
            p.relative_to(folder.resolve())
        except ValueError:
            return ""
        if not p.is_file():
            return ""
        return _media_rel(p, media_root=media_root)
    names = files if files is not None else _folder_file_names(folder)
    real = names.get(clean.casefold())
    if not real:
        return ""
    return _media_rel(folder / real, media_root=media_root)


def _scan_workers() -> int:
    cpus = os.cpu_count() or 4
    return max(8, min(32, cpus * 2))


_POSTER_DL_WORKERS = 3
_poster_dl_q: queue.Queue[tuple[str, str, str]] | None = None
_poster_dl_lock = threading.Lock()
_poster_dl_inflight: set[str] = set()
_poster_dl_fail_until: dict[str, float] = {}


def _is_http_url(url: str) -> bool:
    u = str(url or "").strip().lower()
    return u.startswith("http://") or u.startswith("https://")


def _fetch_cover_bytes(url: str) -> tuple[bytes, str] | None:
    """复用封面代理拉图；失败返回 None（不抛到列表路径）。"""
    try:
        from app.scrap_library.cover_focus_routes import _fetch_bytes

        data, ctype = _fetch_bytes(url)
        if not data or len(data) < 1024:
            return None
        return data, ctype or "image/jpeg"
    except Exception as e:  # noqa: BLE001
        log.debug("scrap poster download fetch failed: %s", e)
        return None


def _write_poster_jpg(folder: Path, data: bytes) -> Path | None:
    """写入番号目录 poster.jpg；成功返回路径。"""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / "poster.jpg"
        tmp = folder / "poster.jpg.part"
        tmp.write_bytes(data)
        # 拒绝空图占位
        if _is_blank_cover_file(tmp):
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        tmp.replace(dest)
        rel = _media_rel(dest)
        if rel:
            _blank_cover_cache.pop(rel, None)
            _blank_cover_cache[rel] = False
        return dest
    except Exception as e:  # noqa: BLE001
        log.debug("scrap poster write failed: %s", e)
        try:
            (folder / "poster.jpg.part").unlink(missing_ok=True)
        except OSError:
            pass
        return None


def download_remote_poster(
    folder: Path,
    cover_url: str,
    *,
    media_root: Path | None = None,
) -> str:
    """本地缺/空 poster 时，把远程 cover 落到 folder/poster.jpg，返回 media 相对路径。"""
    if not _is_http_url(cover_url):
        return ""
    if not folder.is_dir():
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""
    existing = folder / "poster.jpg"
    if existing.is_file() and not _is_blank_cover_file(existing):
        return _media_rel(existing, media_root=media_root)

    got = _fetch_cover_bytes(cover_url)
    if not got:
        return ""
    data, ctype = got
    # 非 JPEG 也落成 poster.jpg（列表/NFO 惯例）；必要时转码
    if "png" in (ctype or "").lower() or "webp" in (ctype or "").lower():
        try:
            import io

            from PIL import Image

            im = Image.open(io.BytesIO(data))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            elif im.mode == "L":
                im = im.convert("RGB")
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=90, optimize=True)
            data = buf.getvalue()
        except Exception:
            pass
    dest = _write_poster_jpg(folder, data)
    if not dest:
        return ""
    # 番号目录只留一张封面
    for name in ("thumb.jpg", "fanart.jpg", "landscape.jpg", "cover.jpg"):
        extra = folder / name
        try:
            if extra.is_file():
                rel_extra = _media_rel(extra, media_root=media_root)
                extra.unlink(missing_ok=True)
                if rel_extra:
                    _blank_cover_cache.pop(rel_extra, None)
        except OSError:
            pass
    return _media_rel(dest, media_root=media_root)


def _update_item_poster_path(item_id: str, poster_path: str) -> None:
    if not item_id or not poster_path:
        return
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {TABLE}
            SET poster_path = %s, updated_at = now()
            WHERE item_id = %s
            """,
            (poster_path, item_id),
        )
        conn.commit()


def ensure_local_poster(
    *,
    item_id: str = "",
    rel_path: str = "",
    cover_url: str = "",
) -> dict[str, Any]:
    """同步兜底：缺本地海报则下载远程 cover → poster.jpg，并回写库。"""
    ensure_schema()
    iid = str(item_id or "").strip()
    rel = str(rel_path or "").strip().replace("\\", "/")
    url = str(cover_url or "").strip()
    if iid and (not rel or not url):
        pool = get_meta_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT item_id, rel_path, poster_path, cover_url
                FROM {TABLE}
                WHERE item_id = %s
                LIMIT 1
                """,
                (iid,),
            )
            row = cur.fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        d = dict(row) if isinstance(row, dict) else {}
        rel = str(d.get("rel_path") or rel).replace("\\", "/")
        url = str(d.get("cover_url") or url).strip()
        existing = str(d.get("poster_path") or "").strip()
        if existing and not _is_blank_cover_rel(existing):
            return {
                "ok": True,
                "skipped": True,
                "posterPath": existing,
                "posterApi": local_file_api(existing),
            }

    if not rel or not _is_http_url(url):
        return {"ok": False, "reason": "no_cover"}

    root = resolve_root(get_settings().get("root"))
    folder = (root / rel).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError:
        return {"ok": False, "reason": "bad_path"}

    poster = download_remote_poster(folder, url)
    if not poster:
        return {"ok": False, "reason": "download_failed"}
    if iid:
        _update_item_poster_path(iid, poster)
    return {
        "ok": True,
        "posterPath": poster,
        "posterApi": local_file_api(poster),
    }


def ensure_local_poster_by_cover(*, cover_url: str) -> dict[str, Any]:
    """按 cover 外链定位条目并落到本地 poster.jpg。"""
    url = str(cover_url or "").strip()
    if not _is_http_url(url):
        return {"ok": False, "reason": "no_cover"}
    ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        # 优先缺本地海报的条目
        cur.execute(
            f"""
            SELECT item_id
            FROM {TABLE}
            WHERE cover_url = %s
            ORDER BY
              CASE WHEN coalesce(poster_path, '') = '' THEN 0 ELSE 1 END,
              updated_at DESC NULLS LAST
            LIMIT 1
            """,
            (url,),
        )
        row = cur.fetchone()
    if not row:
        return {"ok": False, "reason": "not_found"}
    iid = str((row.get("item_id") if isinstance(row, dict) else row[0]) or "")
    if not iid:
        return {"ok": False, "reason": "not_found"}
    return ensure_local_poster(item_id=iid, cover_url=url)


def _poster_dl_worker_loop() -> None:
    assert _poster_dl_q is not None
    while True:
        item_id, rel_path, cover_url = _poster_dl_q.get()
        try:
            ensure_local_poster(
                item_id=item_id, rel_path=rel_path, cover_url=cover_url
            )
        except Exception as e:  # noqa: BLE001
            log.debug("poster dl worker: %s", e)
            _poster_dl_fail_until[item_id] = time.time() + 600
        finally:
            with _poster_dl_lock:
                _poster_dl_inflight.discard(item_id)
            _poster_dl_q.task_done()


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


def schedule_ensure_local_poster(
    *,
    item_id: str,
    rel_path: str,
    cover_url: str,
) -> bool:
    """列表/详情看到缺本地时后台补图；同 item 去重，失败冷却 10 分钟。"""
    iid = str(item_id or "").strip()
    rel = str(rel_path or "").strip()
    url = str(cover_url or "").strip()
    if not iid or not rel or not _is_http_url(url):
        return False
    now = time.time()
    with _poster_dl_lock:
        until = float(_poster_dl_fail_until.get(iid) or 0)
        if until > now:
            return False
        if iid in _poster_dl_inflight:
            return False
        _poster_dl_inflight.add(iid)
    _ensure_poster_dl_pool()
    assert _poster_dl_q is not None
    _poster_dl_q.put((iid, rel, url))
    return True


def _scan_one_nfo(
    nfo: Path,
    *,
    root: Path,
    model: str,
    dim: int,
    media_root: Path,
    scrap_rel: str,
) -> dict[str, Any] | None:
    try:
        folder = nfo.parent
        rel = folder.relative_to(root).as_posix()
    except ValueError:
        return None
    parts = [p for p in rel.split("/") if p]
    region = parts[0] if len(parts) >= 1 else ""
    prefix = parts[1] if len(parts) >= 2 else ""
    code = parts[2] if len(parts) >= 3 else nfo.stem
    meta = parse_nfo(nfo)
    if not meta:
        return None

    # 仅内存清洗进向量；NFO 是存档，禁止写回
    try:
        from app.scrap_library.enrich import _clean_actors

        raw_actors = list(meta.get("actors") or [])
        cleaned = _clean_actors(raw_actors)
        studio = str(meta.get("studio") or "").strip()
        publisher = str(meta.get("publisher") or "").strip()
        skip = {studio.casefold(), publisher.casefold()} - {""}
        cleaned = [a for a in cleaned if a.casefold() not in skip]
        if cleaned != raw_actors:
            meta["actors"] = cleaned
    except Exception:  # noqa: BLE001
        pass

    files = _folder_file_names(folder)

    def pick(*candidates: str) -> str:
        for raw in candidates:
            text = str(raw or "").strip()
            if not text or text.startswith(("http://", "https://")):
                continue
            clean = text.replace("\\", "/").lstrip("/")
            if ".." in clean.split("/") or "/" in clean:
                got = _pick_local_image(
                    folder, text, files=files, media_root=media_root
                )
                if got and not _is_blank_cover_rel(got):
                    return got
                continue
            real = files.get(clean.casefold())
            if not real:
                continue
            abs_file = folder / real
            if _is_blank_cover_file(abs_file):
                continue
            if scrap_rel:
                base = f"{scrap_rel}/{rel}" if rel else scrap_rel
                return f"{base}/{real}"
            got = _pick_local_image(
                folder, real, files=files, media_root=media_root
            )
            if got and not _is_blank_cover_rel(got):
                return got
        return ""

    poster_path = pick(str(meta.get("poster") or ""), "poster.jpg")
    thumb_path = pick(str(meta.get("thumb") or ""), "thumb.jpg")
    fanart_path = pick(str(meta.get("fanart") or ""), "fanart.jpg")
    cover_url = str(meta.get("cover_url") or "").strip()
    # 不外链拉图：仅索引本地 poster/thumb；缺图留给 cover_url 展示或其它补齐路径
    source_text = build_nfo_embed_text(meta, region=region, prefix=prefix)
    return {
        "item_id": item_id_from_rel(rel),
        "region": region,
        "prefix": prefix,
        "code": str(meta.get("num") or code),
        "rel_path": rel,
        "title": str(meta.get("title") or ""),
        "poster_path": poster_path,
        "thumb_path": thumb_path,
        "fanart_path": fanart_path,
        "cover_url": cover_url,
        "source_text": source_text,
        "content_sha": content_sha(source_text, model=model, dim=dim),
        "model": model,
        "dim": dim,
    }


def _scan_items(
    root: Path,
    *,
    on_progress: ProgressCb | None = None,
) -> list[dict[str, Any]]:
    if not root.is_dir():
        raise FileNotFoundError(f"刮削库不存在: {root}")

    cfg = resolve_embed_config()
    model = str(cfg["model"])
    dim = int(cfg["dim"])
    media_root = media_dir().resolve()
    root_resolved = root.resolve()
    try:
        scrap_rel = root_resolved.relative_to(media_root).as_posix()
    except ValueError:
        scrap_rel = ""

    def tick(**kw: Any) -> None:
        if on_progress:
            on_progress(kw)

    # 1) 先快速枚举路径（可显示发现数量），再并行解析
    nfo_paths: list[Path] = []
    for i, nfo in enumerate(root_resolved.rglob("*.nfo"), 1):
        nfo_paths.append(nfo)
        if i == 1 or i % 200 == 0:
            tick(
                stage="scan",
                percent=min(7, 2 + i // 800),
                label=f"发现 {i} 个 NFO…",
                done=i,
                total=None,
            )

    total_files = len(nfo_paths)
    tick(
        stage="scan",
        percent=8,
        label=f"解析 {total_files} 个 NFO…",
        done=0,
        total=total_files,
    )
    if total_files == 0:
        return []

    items: list[dict[str, Any]] = []
    workers = _scan_workers()
    done = 0
    # 分块提交，避免一次性创建数十万 Future
    chunk_size = 1500
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, total_files, chunk_size):
            batch = nfo_paths[start : start + chunk_size]
            futures = [
                pool.submit(
                    _scan_one_nfo,
                    nfo,
                    root=root_resolved,
                    model=model,
                    dim=dim,
                    media_root=media_root,
                    scrap_rel=scrap_rel,
                )
                for nfo in batch
            ]
            for fut in as_completed(futures):
                try:
                    item = fut.result()
                except Exception as e:  # noqa: BLE001
                    log.warning("scan nfo failed: %s", e)
                    item = None
                if item:
                    items.append(item)
                done += 1
                if done == 1 or done % 100 == 0 or done == total_files:
                    pct = 8 + int(12 * done / max(1, total_files))
                    tick(
                        stage="scan",
                        percent=min(20, pct),
                        label=f"解析 {done}/{total_files}",
                        done=done,
                        total=total_files,
                    )
    return items


def _existing_embed_rows(
    item_ids: list[str],
) -> dict[str, dict[str, str]]:
    """item_id → {sha, source_text}"""
    if not item_ids:
        return {}
    out: dict[str, dict[str, str]] = {}
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(item_ids), 800):
                chunk = item_ids[i : i + 800]
                cur.execute(
                    f"""
                    SELECT item_id, content_sha, source_text
                    FROM {TABLE}
                    WHERE item_id = ANY(%s)
                    """,
                    (chunk,),
                )
                for row in cur.fetchall():
                    if not isinstance(row, dict):
                        continue
                    iid = str(row.get("item_id") or "")
                    if not iid:
                        continue
                    out[iid] = {
                        "sha": str(row.get("content_sha") or ""),
                        "source_text": str(row.get("source_text") or ""),
                    }
    return out


def _existing_shas(item_ids: list[str]) -> dict[str, str]:
    return {
        iid: meta["sha"]
        for iid, meta in _existing_embed_rows(item_ids).items()
    }


def ingest(
    *,
    root: str | None = None,
    batch_size: int = 32,
    force: bool = False,
    limit: int | None = None,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """扫描 scrap-library，把 NFO 元数据写入元库向量表。"""
    init_db()
    schema = ensure_schema()
    cfg_root = root if root is not None else get_settings().get("root")
    abs_root = resolve_root(str(cfg_root or DEFAULT_REL_ROOT))

    def prog(stage: str, **kw: Any) -> None:
        payload = {"stage": stage, **kw}
        _set_progress(**payload)
        if on_progress:
            on_progress(payload)

    # 扫描与模型预热并行：避免「扫完才开始加载模型」的长时间假死
    warmup_err: list[BaseException] = []

    def _warmup_model() -> None:
        try:
            encode_texts_sync(["."], query=False)
            _push_log("向量模型已预热")
        except BaseException as e:  # noqa: BLE001
            warmup_err.append(e)

    warmup_thread = threading.Thread(
        target=_warmup_model, name="scrap-embed-warmup", daemon=True
    )
    warmup_thread.start()

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
    if polished_actress:
        _push_log(f"自动优化女优名 {polished_actress:,}")
    if preserved_actress:
        _push_log(f"保留库内女优后再优化 {preserved_actress:,}（NFO 无 actor）")
    _push_log(
        f"待写入 {len(pending)} · 跳过未变 {len(skipped_items)}"
        f" · 清洗等价仅改文本 {len(text_only_items)}"
    )
    prog(
        "embed",
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
    if pending:
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
            pct = 26 + int(66 * written / max(1, len(pending)))
            prog(
                "embed",
                percent=min(92, pct),
                label=f"写入 {written}/{len(pending)}",
                done=written,
                total=len(pending),
            )
            if written == len(chunk) or written % max(bs * 4, 1) == 0:
                _push_log(f"写入 {written}/{len(pending)}")
    else:
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
        ensure_hnsw()
        _push_log("HNSW 向量索引就绪")
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
    }
    prog("done", percent=100, label="完成", done=written, total=len(pending))
    _push_log(
        f"完成 · 写入 {written} · 跳过 {skipped}"
        f"（含文本对齐 {len(text_only_items)}）· 删多余 {purged_disk}"
        f" · 合计 {total} · HNSW → {meta_dsn_label()}"
    )
    return result


def start_ingest_job(*, root: str = "", force: bool = False) -> dict[str, Any]:
    assert_embed_ready()
    with _job_lock:
        if _job["running"]:
            raise RuntimeError("刮削库向量灌库已在运行")
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
            }
        )

    def run() -> None:
        try:
            if root.strip():
                put_settings(root=root.strip())
            result = ingest(force=force)
            with _job_lock:
                _job["result"] = result
                _job["phase"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("scrap library embed failed")
            with _job_lock:
                _job["error"] = str(e)
                _job["phase"] = "error"
                log_list = list(_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _job["log"] = log_list[-40:]
        finally:
            with _job_lock:
                _job["running"] = False

    threading.Thread(target=run, name="scrap-library-embed", daemon=True).start()
    return {"started": True}


def _hit_from_row(row: dict[str, Any], *, score: float | None = None) -> dict[str, Any]:
    poster = str(row.get("poster_path") or "")
    thumb = str(row.get("thumb_path") or "")
    fanart = str(row.get("fanart_path") or "")
    cover = str(row.get("cover_url") or "")
    item_id = str(row.get("item_id") or "")
    rel_path = str(row.get("rel_path") or "")
    source_text = str(row.get("source_text") or "")
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

def _list_card_meta(source_text: str) -> dict[str, Any]:
    """条目附加字段（年份等）；列表卡不再展示剧情短摘。"""
    src = str(source_text or "")
    year = ""
    m = _LIST_YEAR_RE.search(src)
    if m:
        year = re.sub(r"\D", "", m.group(1))[:4]

    actresses: list[str] = []
    m = _LIST_ACTRESS_RE.search(src)
    if m:
        from app.scrap_library.enrich import _clean_actors
        from app.scrape.metadata_optimize import polish_actress_names

        cleaned = _clean_actors(re.split(r"[\s、,/|]+", m.group(1).strip()))
        for name in polish_actress_names(cleaned):
            if name not in actresses:
                actresses.append(name)
            if len(actresses) >= 3:
                break

    return {
        "year": year,
        "actresses": actresses,
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


def _region_match_values(region: str | None) -> list[str]:
    """japan_censored / 日本有码 → 可匹配的 region 列取值。"""
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
    return [v for v in values if v]


def list_regions() -> list[dict[str, Any]]:
    """向量库中实际存在的分区及条数。"""
    from app.core.region_meta import REGION_META, REGION_ORDER

    ensure_schema()
    pool = get_meta_pool()
    counts: dict[str, int] = {}
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT region, count(*)::int AS n
                FROM {TABLE}
                GROUP BY region
                """
            )
            for row in cur.fetchall():
                if not isinstance(row, dict):
                    continue
                counts[str(row.get("region") or "")] = int(row.get("n") or 0)

    # 按七区顺序输出；库内孤儿区追加在后
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rid in REGION_ORDER:
        label = str(REGION_META[rid].get("label") or rid)
        n = int(counts.get(label) or 0) + int(counts.get(rid) or 0)
        out.append({"id": rid, "label": label, "count": n})
        seen.add(label)
        seen.add(rid)
    for name, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        if not name or name in seen:
            continue
        out.append({"id": name, "label": name, "count": int(n)})
    return out


def list_prefixes(
    *, region: str = "", studio: str = "", q: str = "", limit: int | None = None
) -> list[dict[str, Any]]:
    ensure_schema()
    pool = get_meta_pool()
    clauses: list[str] = ["coalesce(prefix,'') <> ''"]
    params: list[Any] = []
    match = _region_match_values(region)
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    studio_q = str(studio or "").strip()
    if studio_q:
        _append_studio_clause(clauses, params, studio_q, region=region)
    query = str(q or "").strip()
    if query:
        like = f"%{query}%"
        clauses.append("prefix ILIKE %s")
        params.append(like)
    where = " AND ".join(clauses)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT prefix, count(*)::int AS n,
                       max(code) AS latest_code,
                       max(
                         NULLIF(
                           substring(source_text from '年份：([0-9]{{4}})'),
                           ''
                         )
                       ) AS latest_year,
                       max(updated_at) AS latest_at,
                       array_agg(
                         COALESCE(
                           NULLIF(thumb_path, ''),
                           NULLIF(poster_path, ''),
                           NULLIF(cover_url, '')
                         )
                         ORDER BY
                           NULLIF(
                             substring(source_text from '年份：([0-9]{{4}})'),
                             ''
                           ) DESC NULLS LAST,
                           code DESC
                       ) FILTER (
                         WHERE coalesce(poster_path,'') <> ''
                            OR coalesce(thumb_path,'') <> ''
                            OR coalesce(cover_url,'') <> ''
                       ) AS posters
                FROM {TABLE}
                WHERE {where}
                GROUP BY prefix
                ORDER BY
                  max(
                    NULLIF(
                      substring(source_text from '年份：([0-9]{{4}})'),
                      ''
                    )
                  ) DESC NULLS LAST,
                  max(updated_at) DESC NULLS LAST,
                  prefix ASC
                """,
                params,
            )
            rows = list(cur.fetchall())
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("posters") or []
        candidates: list[str] = []
        if isinstance(raw, (list, tuple)):
            for p in raw:
                s = str(p or "").strip()
                if s and s not in candidates:
                    candidates.append(s)
                if len(candidates) >= 8:
                    break
        # 列表页单封面：优先本地，否则外链 coverUrl
        poster_api, _, cover_url = _facet_media_refs(candidates[:4])
        primary = ""
        for c in candidates:
            if c and not str(c).startswith(("http://", "https://")):
                primary = str(c)
                break
        year_raw = row.get("latest_year")
        try:
            latest_year = int(year_raw) if year_raw not in (None, "") else 0
        except (TypeError, ValueError):
            latest_year = 0
        latest_at = row.get("latest_at")
        latest_at_s = ""
        if latest_at is not None:
            try:
                latest_at_s = latest_at.isoformat()  # datetime
            except AttributeError:
                latest_at_s = str(latest_at)
        pref = str(row.get("prefix") or "")
        blurb = _prefix_blurb(pref)
        from app.prefix.maker_names import prefix_line_rank
        from app.scrap_library.studio_display_names import resolve_studio_for_prefix

        studio_name = resolve_studio_for_prefix(pref, region=region) or ""
        out.append(
            {
                "prefix": pref,
                "count": int(row.get("n") or 0),
                "latestCode": str(row.get("latest_code") or "").strip().upper(),
                "latestYear": latest_year,
                "latestAt": latest_at_s,
                "lineRank": prefix_line_rank(pref, blurb),
                "posterPath": primary,
                "posterApi": poster_api,
                "posterApis": [],
                "coverUrl": cover_url,
                "blurb": blurb,
                "studio": studio_name,
            }
        )

    def _at_ts(raw: Any) -> float:
        s = str(raw or "").strip()
        if not s:
            return 0.0
        try:
            from datetime import datetime

            return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except Exception:  # noqa: BLE001
            return 0.0

    # 主力线优先，同档再按发行年 / 入库时间新→旧
    out.sort(
        key=lambda r: (
            int(r.get("lineRank") or 99),
            -int(r.get("latestYear") or 0),
            -_at_ts(r.get("latestAt")),
            str(r.get("prefix") or ""),
        )
    )
    if limit is not None:
        lim = max(1, min(100, int(limit)))
        out = out[:lim]
    return out


def _list_items_uncached(
    *,
    region: str = "",
    prefix: str = "",
    q: str = "",
    genre: str = "",
    tag: str = "",
    studio: str = "",
    actress: str = "",
    sort: str = "code",
    order: str = "asc",
    offset: int = 0,
    limit: int = 36,
    exclude_skeleton: bool = False,
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
    sort_key = str(sort or "code").strip().lower()
    ascending = str(order or "asc").strip().lower() not in {
        "desc",
        "descending",
        "down",
    }

    clauses: list[str] = ["TRUE"]
    params: list[Any] = []
    if exclude_skeleton:
        clauses.append(_NOT_SKELETON_SQL)
    match = _region_match_values(region)
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    if pref:
        clauses.append("upper(prefix) = %s")
        params.append(pref)
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
    sort: str = "code",
    order: str = "asc",
    offset: int = 0,
    limit: int = 36,
    exclude_skeleton: bool = False,
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
        )
    )
    cache_key = ""
    if hub_level:
        cache_key = (
            f"v1|{region}|{sort}|{order}|{int(offset or 0)}|{int(limit or 36)}"
            f"|sk={1 if exclude_skeleton else 0}"
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
        sort=sort,
        order=order,
        offset=offset,
        limit=limit,
        exclude_skeleton=exclude_skeleton,
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

# 片商 / 女优行精确抽取（勿用 ILIKE '%片商：%名%'：会跨行误匹配）
_STUDIO_LINE_SQL = "NULLIF(substring(source_text from '片商：(.+?)(?:\\n|$)'), '')"
_ACTRESS_LINE_SQL = "NULLIF(substring(source_text from '女优：(.+?)(?:\\n|$)'), '')"
# PG POSIX 空白类；勿用 E'[\\s...]'（E 串里 \\s 会变成字母 s，空格切不开）
_TOKEN_SPLIT_SQL = "[[:space:]/|、，,]+"
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


def _build_studio_facets_by_prefix(*, region: str = "") -> list[dict[str, Any]]:
    """厂牌货架：按库内 prefix 汇总，再用标准「前缀→厂牌」表归位（不读 NFO 片商）。"""
    from app.scrap_library.studio_display_names import resolve_studio_for_prefix

    ensure_schema()
    match = _region_match_values(region)
    clauses = ["coalesce(prefix, '') <> ''"]
    params: list[Any] = []
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    where = " AND ".join(clauses)
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT upper(prefix) AS pref, count(*)::int AS n,
                       array_agg(
                         COALESCE(
                           NULLIF(thumb_path, ''),
                           NULLIF(poster_path, ''),
                           NULLIF(cover_url, '')
                         )
                         ORDER BY code ASC
                       ) FILTER (
                         WHERE coalesce(poster_path, '') <> ''
                            OR coalesce(thumb_path, '') <> ''
                            OR coalesce(cover_url, '') <> ''
                       ) AS posters
                FROM {TABLE}
                WHERE {where}
                GROUP BY upper(prefix)
                """,
                params,
            )
            rows = list(cur.fetchall())

    buckets: dict[str, dict[str, Any]] = {}
    unknown_n = 0
    unknown_paths: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pref = str(row.get("pref") or "").strip().upper()
        n = int(row.get("n") or 0)
        if not pref or n <= 0:
            continue
        paths: list[str] = []
        for p in row.get("posters") or []:
            s = str(p or "").strip()
            if s and s not in paths:
                paths.append(s)
            if len(paths) >= 8:
                break
        studio = resolve_studio_for_prefix(pref, region=region)
        if not studio:
            unknown_n += n
            unknown_paths.extend(paths)
            continue
        key = _studio_match_key(studio) or studio.casefold()
        cur = buckets.get(key)
        if not cur:
            buckets[key] = _facet_row(
                name=studio,
                count=n,
                kind="studio",
                poster_paths=paths,
                validate_covers=False,
            )
        else:
            cur["count"] = int(cur.get("count") or 0) + n
            _absorb_facet_media(cur, paths)

    out = list(buckets.values())
    if unknown_n > 0:
        out.append(
            _facet_row(
                name="未标注厂牌",
                count=unknown_n,
                kind="studio",
                poster_paths=unknown_paths,
                validate_covers=False,
            )
        )
    return out


def _merge_studio_facets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并厂牌别名，展示名走映射表。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        raw_name = str(row.get("name") or "").strip()
        if raw_name in {"未标注厂牌", "未标注", "(unknown)"}:
            key = f"__unknown__:{raw_name}"
        else:
            key = _studio_match_key(raw_name) or f"__raw__:{raw_name.casefold()}"
        groups.setdefault(key, []).append(row)

    out: list[dict[str, Any]] = []
    for items in groups.values():
        items_sorted = sorted(
            items,
            key=lambda r: (
                -int(r.get("count") or 0),
                0 if " " in str(r.get("name") or "") else 1,
                -len(str(r.get("name") or "")),
            ),
        )
        primary = dict(items_sorted[0])
        total = sum(int(i.get("count") or 0) for i in items_sorted)
        display = _studio_display_name(str(primary.get("name") or ""))
        # 合并封面候选：优先主条目，再补其它
        poster_api = str(primary.get("posterApi") or "")
        cover_url = str(primary.get("coverUrl") or "")
        poster_apis = list(primary.get("posterApis") or [])
        for extra in items_sorted[1:]:
            if not poster_api and extra.get("posterApi"):
                poster_api = str(extra.get("posterApi") or "")
            if not cover_url and extra.get("coverUrl"):
                cover_url = str(extra.get("coverUrl") or "")
            for p in extra.get("posterApis") or []:
                s = str(p or "")
                if s and s not in poster_apis:
                    poster_apis.append(s)
                if len(poster_apis) >= 4:
                    break
        primary.update(
            {
                "name": display or str(primary.get("name") or ""),
                "count": total,
                "posterApi": poster_api,
                "posterApis": poster_apis[:4],
                "coverUrl": cover_url,
                "blurb": _studio_blurb(display or str(primary.get("name") or "")),
            }
        )
        out.append(primary)
    return out


def _null_studio_prefix_buckets(region: str) -> list[dict[str, Any]]:
    """无片商条目按前缀汇总（用于归位到厂牌）。"""
    ensure_schema()
    match = _region_match_values(region)
    clauses = [f"({_STUDIO_LINE_SQL} IS NULL)", "coalesce(prefix,'') <> ''"]
    params: list[Any] = []
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    where = " AND ".join(clauses)
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT prefix, count(*)::int AS n,
                       array_agg(
                         COALESCE(
                           NULLIF(thumb_path, ''),
                           NULLIF(poster_path, ''),
                           NULLIF(cover_url, '')
                         )
                         ORDER BY code ASC
                       ) FILTER (
                         WHERE coalesce(poster_path,'') <> ''
                            OR coalesce(thumb_path,'') <> ''
                            OR coalesce(cover_url,'') <> ''
                       ) AS posters
                FROM {TABLE}
                WHERE {where}
                GROUP BY prefix
                """,
                params,
            )
            rows = list(cur.fetchall())
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        paths: list[str] = []
        for p in row.get("posters") or []:
            s = str(p or "").strip()
            if s and s not in paths:
                paths.append(s)
            if len(paths) >= 8:
                break
        out.append(
            {
                "prefix": str(row.get("prefix") or "").strip().upper(),
                "count": int(row.get("n") or 0),
                "paths": paths,
            }
        )
    return out


def _absorb_facet_media(dst: dict[str, Any], paths: list[str]) -> None:
    api, apis, cover = _facet_media_refs(paths)
    if api and not dst.get("posterApi"):
        dst["posterApi"] = api
    if cover and not dst.get("coverUrl"):
        dst["coverUrl"] = cover
    existing = list(dst.get("posterApis") or [])
    for a in apis:
        if a and a not in existing:
            existing.append(a)
        if len(existing) >= 4:
            break
    dst["posterApis"] = existing[:4]
    if api and not dst.get("posterPath"):
        # 仅作占位；真实路径由 list 侧再解析
        dst["posterPath"] = str(dst.get("posterPath") or "")


def _reattribute_unlabeled_studios(
    rows: list[dict[str, Any]], *, region: str
) -> list[dict[str, Any]]:
    """把缺片商但前缀可识别的条目归入对应厂牌 facet。"""
    from app.scrap_library.studio_display_names import resolve_studio_for_prefix

    buckets = _null_studio_prefix_buckets(region)
    if not buckets:
        return rows

    by_canon: dict[str, dict[str, Any]] = {}
    unknown: dict[str, Any] | None = None
    for row in rows:
        name = str(row.get("name") or "").strip()
        if name in {"未标注厂牌", "未标注", "(unknown)"}:
            unknown = dict(row)
            continue
        key = _studio_match_key(name) or name.casefold()
        existing = by_canon.get(key)
        if not existing:
            by_canon[key] = dict(row)
            continue
        existing["count"] = int(existing.get("count") or 0) + int(
            row.get("count") or 0
        )
        _absorb_facet_media(
            existing,
            [
                str(row.get("posterPath") or ""),
                str(row.get("coverUrl") or ""),
                *list(row.get("posterApis") or []),
            ],
        )

    leftover = 0
    leftover_paths: list[str] = []
    for b in buckets:
        pref = str(b.get("prefix") or "")
        n = int(b.get("count") or 0)
        paths = list(b.get("paths") or [])
        if n <= 0:
            continue
        studio_disp = resolve_studio_for_prefix(pref, region=region)
        if not studio_disp:
            leftover += n
            leftover_paths.extend(paths)
            continue
        key = _studio_match_key(studio_disp) or studio_disp.casefold()
        target = by_canon.get(key)
        if not target:
            by_canon[key] = _facet_row(
                name=studio_disp,
                count=n,
                kind="studio",
                poster_paths=paths,
                validate_covers=False,
            )
        else:
            target["count"] = int(target.get("count") or 0) + n
            _absorb_facet_media(target, paths)

    out = list(by_canon.values())
    if leftover > 0:
        if unknown:
            unknown["count"] = leftover
            _absorb_facet_media(unknown, leftover_paths)
            out.append(unknown)
        else:
            out.append(
                _facet_row(
                    name="未标注厂牌",
                    count=leftover,
                    kind="studio",
                    poster_paths=leftover_paths,
                    validate_covers=False,
                )
            )
    return out


def _append_actress_clause(
    clauses: list[str], params: list[Any], actress: str
) -> None:
    actress_q = str(actress or "").strip()
    if not actress_q:
        return
    if actress_q in {"未标注女优", "未标注", "(unknown)"}:
        clauses.append(f"({_ACTRESS_LINE_SQL} IS NULL)")
        return
    # 女优行可多名：整行分词后精确命中
    clauses.append(
        f"""EXISTS (
          SELECT 1
          FROM unnest(
            regexp_split_to_array(trim({_ACTRESS_LINE_SQL}), '{_TOKEN_SPLIT_SQL}')
          ) AS tok
          WHERE trim(tok) = %s
        )"""
    )
    params.append(actress_q)


def _split_tokens(raw: str) -> list[str]:
    out: list[str] = []
    for token in re.split(r"[\s/|、，,]+", str(raw or "")):
        name = token.strip()
        if name:
            out.append(name)
    return out


def _split_actress_tokens(raw: str) -> list[str]:
    from app.scrap_library.enrich import _clean_actors

    return _clean_actors(_split_tokens(raw))


_FACETS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_FACETS_CACHE_TTL_S = 600.0
_FACETS_CACHE_MAX = 48

# 磁盘快照：厂牌/标签/女优等全库聚合很慢，落盘后重启仍可秒开
_FACETS_SNAP_DIR = "scrap_facets_snap"
# v3：女优分面过滤类型标签噪声
_FACETS_SNAP_VERSION = 3
_FACETS_SNAP_KINDS = ("genre", "actress", "studio", "tag")
_facets_snap_lock = threading.Lock()


def _normalize_facet_kind(kind: str) -> str:
    key = str(kind or "genre").strip().lower()
    if key in {"genres", "类型"}:
        return "genre"
    if key in {"tags", "标签"}:
        return "tag"
    if key in {"studios", "maker", "片商", "合集"}:
        return "studio"
    if key in {"actress", "actor", "女优"}:
        return "actress"
    if key not in {"genre", "tag", "studio", "actress"}:
        raise ValueError("kind 仅支持 genre / tag / studio / actress")
    return key


def _facet_media_refs(paths: list[str]) -> tuple[str, list[str], str]:
    """本地路径 → posterApi；coverUrl 仅供前端触发落盘，不直接展示。"""
    apis: list[str] = []
    cover = ""
    for raw in paths:
        s = str(raw or "").strip()
        if not s:
            continue
        if s.startswith(("http://", "https://")):
            if not cover:
                cover = s
            continue
        api = local_file_api(s.replace("\\", "/").lstrip("/"))
        if api and api not in apis:
            apis.append(api)
    return (apis[0] if apis else ""), apis[:4], cover


def _facet_row(
    *,
    name: str,
    count: int,
    kind: str,
    poster_paths: list[str],
    validate_covers: bool = False,
) -> dict[str, Any]:
    if validate_covers:
        paths = _pick_collage_posters(poster_paths, limit=4)
    else:
        locals_: list[str] = []
        covers_: list[str] = []
        seen: set[str] = set()
        for raw in poster_paths or []:
            s = str(raw or "").strip()
            if not s or s in seen:
                continue
            seen.add(s)
            if s.startswith(("http://", "https://")):
                if len(covers_) < 4:
                    covers_.append(s)
            elif len(locals_) < 4:
                locals_.append(s)
        paths = locals_ + covers_
    poster_api, poster_apis, cover_url = _facet_media_refs(paths)
    primary = next(
        (p for p in paths if not p.startswith(("http://", "https://"))),
        "",
    )
    return {
        "name": name,
        "count": count,
        "kind": kind,
        "posterPath": primary,
        "posterApi": poster_api,
        "posterApis": poster_apis,
        "coverUrl": cover_url,
    }


def _build_facets_sql_line_tokens(
    *,
    region: str,
    line_label: str,
    unknown_name: str,
    out_kind: str,
    studio: str = "",
    prefix: str = "",
    split_tokens: bool = True,
) -> list[dict[str, Any]]:
    """用 Postgres 抽取「女优：/片商：」行并汇总（比 Python 扫表快一个数量级）。"""
    ensure_schema()
    match = _region_match_values(region)
    clauses = ["TRUE"]
    params: list[Any] = []
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    studio_q = str(studio or "").strip()
    pref = str(prefix or "").strip().upper()
    if studio_q:
        _append_studio_clause(clauses, params, studio_q, region=region)
    if pref:
        clauses.append("upper(prefix) = %s")
        params.append(pref)
    where = " AND ".join(clauses)
    # 与 _split_tokens / list_items 一致
    split_re = _TOKEN_SPLIT_SQL
    label_re = f"{re.escape(line_label)}：(.+?)(?:\\n|$)"

    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            if split_tokens:
                cur.execute(
                    f"""
                    WITH base AS (
                      SELECT
                        ctid,
                        NULLIF(
                          substring(source_text from %s),
                          ''
                        ) AS line,
                        COALESCE(
                          NULLIF(thumb_path, ''),
                          NULLIF(poster_path, '')
                        ) AS local_poster,
                        NULLIF(cover_url, '') AS cover
                      FROM {TABLE}
                      WHERE {where}
                    ),
                    tokens AS (
                      SELECT DISTINCT ON (b.ctid, trim(tok))
                        trim(tok) AS name,
                        b.local_poster,
                        b.cover
                      FROM base b
                      CROSS JOIN LATERAL unnest(
                        regexp_split_to_array(b.line, %s)
                      ) AS tok
                      WHERE b.line IS NOT NULL AND trim(tok) <> ''
                    )
                    SELECT
                      name,
                      count(*)::int AS cnt,
                      (array_agg(local_poster) FILTER (
                        WHERE local_poster IS NOT NULL AND local_poster <> ''
                      ))[1:16] AS posters,
                      (array_agg(cover) FILTER (
                        WHERE cover IS NOT NULL AND cover <> ''
                      ))[1:8] AS covers
                    FROM tokens
                    GROUP BY name
                    """,
                    [label_re, *params, split_re],
                )
            else:
                cur.execute(
                    f"""
                    SELECT
                      trim(line) AS name,
                      count(*)::int AS cnt,
                      (array_agg(local_poster) FILTER (
                        WHERE local_poster IS NOT NULL AND local_poster <> ''
                      ))[1:16] AS posters,
                      (array_agg(cover) FILTER (
                        WHERE cover IS NOT NULL AND cover <> ''
                      ))[1:8] AS covers
                    FROM (
                      SELECT
                        NULLIF(
                          substring(source_text from %s),
                          ''
                        ) AS line,
                        COALESCE(
                          NULLIF(thumb_path, ''),
                          NULLIF(poster_path, '')
                        ) AS local_poster,
                        NULLIF(cover_url, '') AS cover
                      FROM {TABLE}
                      WHERE {where}
                    ) base
                    WHERE line IS NOT NULL AND trim(line) <> ''
                    GROUP BY trim(line)
                    """,
                    [label_re, *params],
                )
            rows = list(cur.fetchall())
            cur.execute(
                f"""
                SELECT count(*)::int AS n,
                       (array_agg(local_poster) FILTER (
                         WHERE local_poster IS NOT NULL AND local_poster <> ''
                       ))[1:16] AS posters,
                       (array_agg(cover) FILTER (
                         WHERE cover IS NOT NULL AND cover <> ''
                       ))[1:8] AS covers
                FROM (
                  SELECT
                    COALESCE(
                      NULLIF(thumb_path, ''),
                      NULLIF(poster_path, '')
                    ) AS local_poster,
                    NULLIF(cover_url, '') AS cover
                  FROM {TABLE}
                  WHERE {where}
                    AND (
                      source_text !~ %s
                      OR NULLIF(
                        substring(source_text from %s),
                        ''
                      ) IS NULL
                    )
                ) missing
                """,
                [*params, re.escape(line_label) + "：", label_re],
            )
            unknown = cur.fetchone() or {}

    def _merge_paths(row: dict[str, Any]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for key in ("posters", "covers"):
            for p in row.get(key) or []:
                s = str(p or "").strip()
                if not s or s in seen:
                    continue
                seen.add(s)
                out.append(s)
        return out

    out: list[dict[str, Any]] = []
    clean_actress = line_label in {"女优", "女優"}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if clean_actress:
            from app.scrap_library.enrich import _clean_actors

            kept = _clean_actors([name])
            if not kept:
                continue
            name = kept[0]
        out.append(
            _facet_row(
                name=name,
                count=int(row.get("cnt") or 0),
                kind=out_kind,
                poster_paths=_merge_paths(row),
                validate_covers=False,
            )
        )
    unknown_n = int(unknown.get("n") or 0) if isinstance(unknown, dict) else 0
    if unknown_n > 0:
        out.append(
            _facet_row(
                name=unknown_name,
                count=unknown_n,
                kind=out_kind,
                poster_paths=_merge_paths(
                    unknown if isinstance(unknown, dict) else {}
                ),
                validate_covers=False,
            )
        )
    return out


def _build_facets_all(
    *,
    region: str = "",
    kind: str = "genre",
    studio: str = "",
    prefix: str = "",
) -> list[dict[str, Any]]:
    """从 source_text 汇总流派 / 标签 / 片商（全量，未排序切片）。"""
    key = _normalize_facet_kind(kind)
    if key == "actress":
        return _build_facets_sql_line_tokens(
            region=region,
            line_label="女优",
            unknown_name="未标注女优",
            out_kind="tag",
            studio=studio,
            prefix=prefix,
            split_tokens=True,
        )
    if key == "studio":
        # 标准前缀→厂牌表；不依赖 NFO「片商：」
        return _build_studio_facets_by_prefix(region=region)

    ensure_schema()
    match = _region_match_values(region)
    clauses = ["TRUE"]
    params: list[Any] = []
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    studio_q = str(studio or "").strip()
    pref = str(prefix or "").strip().upper()
    if studio_q:
        _append_studio_clause(clauses, params, studio_q, region=region)
    if pref:
        clauses.append("upper(prefix) = %s")
        params.append(pref)
    where = " AND ".join(clauses)

    pool = get_meta_pool()
    counts: dict[str, int] = {}
    posters: dict[str, list[str]] = {}
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT source_text, poster_path, thumb_path, cover_url, prefix
                FROM {TABLE}
                WHERE {where}
                """,
                params,
            )
            for row in cur.fetchall():
                if not isinstance(row, dict):
                    continue
                text = str(row.get("source_text") or "")
                poster = (
                    str(row.get("thumb_path") or "").strip()
                    or str(row.get("poster_path") or "").strip()
                    or str(row.get("cover_url") or "").strip()
                )
                prefix_val = str(row.get("prefix") or "").strip().upper()
                actress_m = _FACET_LINE_RE["actress"].search(text)
                actresses = set(
                    _split_tokens(actress_m.group(1)) if actress_m else []
                )
                # 标签：无独立字段时回退女优，便于 Emby 式浏览
                if key == "tag":
                    m_tag = _FACET_LINE_RE["tag"].search(text)
                    names = (
                        _split_tokens(m_tag.group(1))
                        if m_tag
                        else list(actresses)
                    )
                else:
                    m = _FACET_LINE_RE["genre"].search(text)
                    names = []
                    if m:
                        genre_raw = m.group(1)
                        genre_raw = re.split(
                            r"\s*(?:片商|发行|系列)\s*[:：]",
                            genre_raw,
                            maxsplit=1,
                        )[0]
                        for token in _split_tokens(genre_raw):
                            if token in actresses:
                                continue
                            if prefix_val and token.upper() == prefix_val:
                                continue
                            if _CODEISH_RE.match(token):
                                continue
                            if token.upper() in {"NO.1", "STYLE", "4K", "8K", "VR"}:
                                continue
                            if len(token) > 24:
                                continue
                            names.append(token)

                for name in names:
                    if not name:
                        continue
                    counts[name] = counts.get(name, 0) + 1
                    if poster:
                        bucket = posters.setdefault(name, [])
                        if poster not in bucket and len(bucket) < 24:
                            bucket.append(poster)

    out_kind = key
    return [
        _facet_row(
            name=name,
            count=n,
            kind=out_kind,
            poster_paths=posters.get(name) or [],
            validate_covers=False,
        )
        for name, n in counts.items()
    ]


def _sort_facets(
    rows: list[dict[str, Any]],
    *,
    sort: str = "count",
    order: str = "desc",
) -> list[dict[str, Any]]:
    sort_key = str(sort or "count").strip().lower()
    ascending = str(order or "desc").strip().lower() not in {
        "desc",
        "descending",
        "down",
    }

    def name_of(row: dict[str, Any]) -> str:
        return str(row.get("name") or "")

    if sort_key == "name":
        return sorted(rows, key=name_of, reverse=not ascending)

    def count_name(row: dict[str, Any]) -> tuple[int, str]:
        c = int(row.get("count") or 0)
        return (c if ascending else -c, name_of(row))

    return sorted(rows, key=count_name)


def _facets_snap_region_key(region: str) -> str:
    raw = str(region or "").strip() or "_all"
    return re.sub(r"[^\w.\-]+", "_", raw)[:96] or "_all"


def _facets_snap_path(region: str, kind: str) -> Path:
    d = data_dir() / _FACETS_SNAP_DIR / _facets_snap_region_key(region)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{kind}.json"


def _load_facets_snapshot(region: str, kind: str) -> list[dict[str, Any]] | None:
    path = _facets_snap_path(region, kind)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("facets snapshot read failed %s: %s", path, e)
        return None
    if int(data.get("v") or 0) != _FACETS_SNAP_VERSION:
        return None
    rows = data.get("rows")
    if not isinstance(rows, list):
        return None
    return [r for r in rows if isinstance(r, dict)]


def _save_facets_snapshot(
    region: str, kind: str, rows: list[dict[str, Any]]
) -> Path:
    path = _facets_snap_path(region, kind)
    tmp = path.with_suffix(".tmp")
    payload = {
        "v": _FACETS_SNAP_VERSION,
        "region": str(region or ""),
        "kind": kind,
        "updatedAt": time.time(),
        "count": len(rows),
        "rows": rows,
    }
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)
    return path


def _purge_facets_memory_cache(*, region: str = "", kind: str = "") -> None:
    kind_q = str(kind or "").strip()
    region_s = str(region or "")
    dead: list[str] = []
    for k in _FACETS_CACHE:
        # key: v8|{region}|{kind}|{studio}|{pref}
        parts = k.split("|")
        if len(parts) < 3:
            continue
        if parts[1] != region_s:
            continue
        if kind_q and parts[2] != kind_q:
            continue
        dead.append(k)
    for k in dead:
        _FACETS_CACHE.pop(k, None)


def facets_snapshot_meta(*, region: str = "") -> dict[str, Any]:
    """单区或全部区的快照元信息。"""
    from app.core.region_meta import REGION_ORDER

    rid = str(region or "").strip()
    if rid:
        return _facets_snapshot_meta_one(rid)
    regions: dict[str, Any] = {}
    for r in REGION_ORDER:
        regions[r] = _facets_snapshot_meta_one(r)
    rec_path = _recommend_snap_path()
    recommend: dict[str, Any] = {"exists": False}
    if rec_path.is_file():
        try:
            raw = json.loads(rec_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                recommend = {
                    "exists": True,
                    "shelves": len(raw.get("shelves") or []),
                    "total": int(raw.get("total") or 0),
                    "updatedAt": float(raw.get("updatedAt") or 0),
                }
            else:
                recommend = {"exists": True, "shelves": 0, "total": 0, "updatedAt": 0}
        except Exception:  # noqa: BLE001
            recommend = {"exists": True, "shelves": 0, "total": 0, "updatedAt": 0}
    return {"regions": regions, "recommend": recommend}


def _facets_snapshot_meta_one(region: str) -> dict[str, Any]:
    kinds: dict[str, Any] = {}
    for kind in ("genre", "actress", "studio", "tag"):
        path = _facets_snap_path(region, kind)
        if not path.is_file():
            kinds[kind] = {"exists": False}
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            kinds[kind] = {
                "exists": True,
                "count": int(data.get("count") or 0),
                "updatedAt": float(data.get("updatedAt") or 0),
            }
        except Exception:  # noqa: BLE001
            kinds[kind] = {"exists": True, "count": 0, "updatedAt": 0}
    return {"region": str(region or ""), "kinds": kinds}


def refresh_facets_snapshot(
    *,
    region: str = "",
    kinds: list[str] | None = None,
    all_regions: bool = False,
) -> dict[str, Any]:
    """重建分面磁盘快照。

    默认策略：
    - 种类：studio / genre / actress（片商页三个分面）
    - 范围：all_regions 或 region 为空 → 七区全量；否则仅指定区
    - 附带：推荐货架快照 + 影片一级首页（发行日期）内存预热
    全量约数秒，可同步完成。
    """
    from app.core.region_meta import REGION_ORDER

    if kinds:
        want = [_normalize_facet_kind(k) for k in kinds]
    else:
        want = ["studio", "genre", "actress"]
    seen: set[str] = set()
    ordered: list[str] = []
    for k in want:
        if k in seen:
            continue
        seen.add(k)
        ordered.append(k)

    rid = str(region or "").strip()
    if all_regions or not rid:
        regions = list(REGION_ORDER)
    else:
        regions = [rid]

    by_region: dict[str, dict[str, int]] = {}
    with _facets_snap_lock:
        for reg in regions:
            built: dict[str, int] = {}
            for key in ordered:
                rows = _build_facets_all(
                    region=reg, kind=key, studio="", prefix=""
                )
                _save_facets_snapshot(reg, key, rows)
                built[key] = len(rows)
            _purge_facets_memory_cache(region=reg)
            now = time.monotonic()
            for key in ordered:
                hit_rows = _load_facets_snapshot(reg, key) or []
                _FACETS_CACHE[f"v8|{reg}|{key}||"] = (now, list(hit_rows))
            enforce_max(_FACETS_CACHE, _FACETS_CACHE_MAX)
            by_region[reg] = built

    recommend: dict[str, Any] = {}
    try:
        rec = refresh_recommend_snapshot()
        recommend = {
            "shelves": int(rec.get("shelves") or 0),
            "total": int(rec.get("total") or 0),
        }
    except Exception as e:  # noqa: BLE001
        log.warning("recommend snapshot refresh failed: %s", e)

    warmed = 0
    try:
        _ITEMS_HUB_CACHE.clear()
        for reg in regions:
            list_items(
                region=reg,
                sort="year",
                order="desc",
                offset=0,
                limit=45,
            )
            warmed += 1
    except Exception as e:  # noqa: BLE001
        log.warning("movies hub warm failed: %s", e)

    flat: dict[str, int] = {}
    if len(regions) == 1:
        flat = dict(by_region.get(regions[0]) or {})
    else:
        for built in by_region.values():
            for k, n in built.items():
                flat[k] = int(flat.get(k) or 0) + int(n)
    if recommend:
        flat["recommend"] = int(recommend.get("shelves") or 0)
    if warmed:
        flat["moviesWarm"] = warmed

    return {
        "region": "" if len(regions) > 1 else regions[0],
        "regions": list(regions),
        "byRegion": by_region,
        "kinds": flat,
        "recommend": recommend,
        "updatedAt": time.time(),
    }


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
    cache_key = f"v8|{region}|{key}|{studio_q}|{pref}"
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


def list_recommend(*, region: str = "") -> dict[str, Any]:
    """Emby「推荐」：七区各自一条「最近刮削入库」横向货架。

    region 参数保留兼容；推荐页始终返回全部有内容的区。
    按向量库 updated_at 新→旧（enrich/写回会刷新该字段），排除仅番号骨架。
    结果走内存 + 磁盘快照，打开推荐页秒开。
    """
    now = time.monotonic()
    prune_by_age(_RECOMMEND_CACHE, _RECOMMEND_CACHE_TTL_S, now=now)
    hit = _RECOMMEND_CACHE.get("all")
    if hit and now - hit[0] < _RECOMMEND_CACHE_TTL_S:
        data = dict(hit[1])
    else:
        data = _load_recommend_snapshot()
        if data is None:
            data = _build_recommend()
            try:
                _save_recommend_snapshot(data)
            except Exception as e:  # noqa: BLE001
                log.warning("recommend snapshot write failed: %s", e)
        _RECOMMEND_CACHE["all"] = (now, dict(data))
        enforce_max(_RECOMMEND_CACHE, 4)

    # 兼容旧字段：取当前/第一区
    shelves = list(data.get("shelves") or [])
    focus = str(region or "").strip()
    focus_shelf = next((s for s in shelves if s.get("region") == focus), None)
    if focus_shelf is None and shelves:
        focus_shelf = shelves[0]
    latest = list((focus_shelf or {}).get("latest") or [])
    return {
        "shelves": shelves,
        "latest": latest,
        "genres": [],
        "collections": [],
        "folders": [],
        "total": int(data.get("total") or 0),
    }


_RECOMMEND_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_RECOMMEND_CACHE_TTL_S = 180.0
_RECOMMEND_SNAP_VERSION = 1


def _recommend_snap_path() -> Path:
    d = data_dir() / _FACETS_SNAP_DIR / "_recommend"
    d.mkdir(parents=True, exist_ok=True)
    return d / "shelves.json"


def _load_recommend_snapshot() -> dict[str, Any] | None:
    path = _recommend_snap_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("recommend snapshot read failed: %s", e)
        return None
    if not isinstance(raw, dict):
        return None
    if int(raw.get("v") or 0) != _RECOMMEND_SNAP_VERSION:
        return None
    shelves = raw.get("shelves")
    if not isinstance(shelves, list):
        return None
    return {
        "shelves": shelves,
        "total": int(raw.get("total") or 0),
    }


def _save_recommend_snapshot(data: dict[str, Any]) -> None:
    path = _recommend_snap_path()
    payload = {
        "v": _RECOMMEND_SNAP_VERSION,
        "updatedAt": time.time(),
        "total": int(data.get("total") or 0),
        "shelves": list(data.get("shelves") or []),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(path)


def _build_recommend() -> dict[str, Any]:
    from app.core.region_meta import REGION_META, REGION_ORDER

    shelves: list[dict[str, Any]] = []
    total_all = 0
    for rid in REGION_ORDER:
        page = list_items(
            region=rid,
            sort="recent",
            order="desc",
            offset=0,
            limit=12,
            exclude_skeleton=True,
        )
        items = page.get("items") or []
        if not items:
            continue
        n = int(page.get("total") or 0)
        total_all += n
        label = str((REGION_META.get(rid) or {}).get("label") or rid)
        shelves.append(
            {
                "region": rid,
                "label": label,
                "latest": items,
                "total": n,
            }
        )
    return {"shelves": shelves, "total": total_all}


def refresh_recommend_snapshot() -> dict[str, Any]:
    """重建推荐货架磁盘快照。"""
    data = _build_recommend()
    _save_recommend_snapshot(data)
    _RECOMMEND_CACHE.clear()
    _RECOMMEND_CACHE["all"] = (time.monotonic(), dict(data))
    return {
        "shelves": len(data.get("shelves") or []),
        "total": int(data.get("total") or 0),
        "updatedAt": time.time(),
    }


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
    where_parts = [_NOT_SKELETON_SQL]
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


def get_actress_optimize_status() -> dict[str, Any]:
    with _ACTRESS_OPT_LOCK:
        return {
            "running": bool(_actress_opt_job["running"]),
            "phase": _actress_opt_job.get("phase") or "",
            "progress": _actress_opt_job.get("progress"),
            "log": list(_actress_opt_job.get("log") or [])[-40:],
            "result": _actress_opt_job.get("result"),
            "error": _actress_opt_job.get("error"),
        }


def _actress_opt_log(msg: str) -> None:
    with _ACTRESS_OPT_LOCK:
        log_list = list(_actress_opt_job.get("log") or [])
        log_list.append(str(msg))
        _actress_opt_job["log"] = log_list[-40:]


def _actress_opt_progress(**kw: Any) -> None:
    with _ACTRESS_OPT_LOCK:
        cur = dict(_actress_opt_job.get("progress") or {})
        cur.update(kw)
        _actress_opt_job["progress"] = cur
        if kw.get("label"):
            _actress_opt_job["phase"] = str(kw["label"])


def optimize_actress_metadata(
    *,
    reembed: bool = True,
    limit: int | None = None,
    batch_size: int = 32,
    read_nfo_directors: bool = False,
) -> dict[str, Any]:
    """批量优化向量库女优行：映射中文标准名 + 排除导演/男优（不改 NFO）。"""
    from app.ai.embed import encode_texts_sync
    from app.scrap_library.nfo import content_sha, parse_nfo
    from app.scrape.metadata_optimize import (
        actor_maps_loaded,
        polish_actress_names,
    )

    ensure_schema()
    maps_info = actor_maps_loaded()
    _actress_opt_log(
        f"映射表 {maps_info.get('lang')} · {maps_info.get('count') or 0} 条"
    )
    root = resolve_root(get_settings().get("root"))
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, code, rel_path, source_text, model, dim, title
            FROM {TABLE}
            WHERE source_text LIKE %s
            ORDER BY code
            """,
            ("%女优：%",),
        )
        rows = [dict(r) for r in cur.fetchall()]
    if limit is not None and int(limit) > 0:
        rows = rows[: int(limit)]
    total = len(rows)
    _actress_opt_log(f"待检查 {total:,} 条含女优行")
    _actress_opt_progress(
        stage="scan", percent=2, label=f"检查 {total}", done=0, total=total
    )

    actress_re = re.compile(r"^(女优：)(.+)$", re.M)
    pending: list[dict[str, Any]] = []
    unchanged = 0
    for i, row in enumerate(rows, 1):
        src = str(row.get("source_text") or "")
        m = actress_re.search(src)
        if not m:
            unchanged += 1
            continue
        raw_parts = [
            p for p in re.split(r"[\s、,/|]+", m.group(2).strip()) if p.strip()
        ]
        directors: list[str] = []
        # 批量任务默认不扫 NFO（极慢）；男优/导演以映射表 drop 为主。
        # 单条/小批量可传 read_nfo_directors=True。
        if read_nfo_directors:
            rel = str(row.get("rel_path") or "").replace("\\", "/").strip("/")
            if rel:
                folder = root / rel
                nfo = None
                if folder.is_dir():
                    for cand in (
                        folder / f"{folder.name}.nfo",
                        folder / f"{row.get('code')}.nfo",
                        *sorted(folder.glob("*.nfo")),
                    ):
                        if cand.is_file():
                            nfo = cand
                            break
                if nfo:
                    try:
                        meta = parse_nfo(nfo)
                        d = str(meta.get("director") or "").strip()
                        if d:
                            directors.append(d)
                    except Exception:  # noqa: BLE001
                        pass
        try:
            from app.scrap_library.enrich import _clean_actors

            cleaned = _clean_actors(raw_parts)
        except Exception:  # noqa: BLE001
            cleaned = raw_parts
        polished = polish_actress_names(cleaned, exclude=directors)
        old_line = m.group(0)
        if polished:
            new_line = f"女优：{' '.join(polished[:12])}"
        else:
            new_line = ""
        if new_line == old_line:
            unchanged += 1
            continue
        if new_line:
            new_src = src[: m.start()] + new_line + src[m.end() :]
        else:
            before = src[: m.start()].rstrip("\n")
            after = src[m.end() :].lstrip("\n")
            new_src = f"{before}\n{after}" if before and after else (before or after)
        new_src = re.sub(r"\n{2,}", "\n", new_src).strip()
        model = str(row.get("model") or "")
        dim = int(row.get("dim") or 0) or int(resolve_embed_config()["dim"])
        if not model:
            model = str(resolve_embed_config()["model"])
        pending.append(
            {
                "item_id": row["item_id"],
                "code": row.get("code"),
                "source_text": new_src,
                "content_sha": content_sha(new_src, model=model, dim=dim),
                "model": model,
                "dim": dim,
                "old": m.group(2).strip()[:80],
                "new": " ".join(polished[:8]) if polished else "(removed)",
            }
        )
        if i == 1 or i % 2000 == 0 or i == total:
            _actress_opt_progress(
                stage="diff",
                percent=2 + int(40 * i / max(1, total)),
                label=f"比对 {i}/{total}",
                done=i,
                total=total,
            )

    _actress_opt_log(
        f"需更新 {len(pending):,} · 未变 {unchanged:,}"
    )
    if pending[:5]:
        for s in pending[:5]:
            _actress_opt_log(f"例 {s.get('code')} · {s['old']} → {s['new']}")

    written = 0
    if not pending:
        _actress_opt_progress(
            stage="done", percent=100, label="无需更新", done=0, total=total
        )
        return {
            "ok": True,
            "total": total,
            "unchanged": unchanged,
            "updated": 0,
            "reembedded": 0,
            "maps": maps_info,
        }

    cfg = resolve_embed_config()
    if not cfg.get("enabled"):
        reembed = False
        _actress_opt_log("嵌入未启用 · 仅更新文本")

    bs = max(8, min(64, int(batch_size or 32)))
    reembedded = 0
    with pool.connection() as conn, conn.cursor() as cur:
        for i in range(0, len(pending), bs):
            chunk = pending[i : i + bs]
            if reembed:
                texts = [p["source_text"] for p in chunk]
                vecs = encode_texts_sync(texts, query=False)
                if not vecs or len(vecs) != len(chunk):
                    raise RuntimeError("向量编码失败")
                for p, vec in zip(chunk, vecs):
                    if len(vec) != int(p["dim"]):
                        raise RuntimeError("向量维度不匹配")
                    cur.execute(
                        f"""
                        UPDATE {TABLE}
                        SET source_text = %s,
                            content_sha = %s,
                            embedding = %s::vector,
                            updated_at = now()
                        WHERE item_id = %s
                        """,
                        (
                            p["source_text"],
                            p["content_sha"],
                            _vec_literal(vec),
                            p["item_id"],
                        ),
                    )
                    reembedded += 1
                    written += 1
            else:
                for p in chunk:
                    cur.execute(
                        f"""
                        UPDATE {TABLE}
                        SET source_text = %s,
                            content_sha = %s,
                            updated_at = now()
                        WHERE item_id = %s
                        """,
                        (p["source_text"], p["content_sha"], p["item_id"]),
                    )
                    written += 1
            conn.commit()
            done = min(len(pending), i + len(chunk))
            _actress_opt_progress(
                stage="embed" if reembed else "patch",
                percent=45 + int(50 * done / max(1, len(pending))),
                label=f"写入 {done}/{len(pending)}",
                done=done,
                total=len(pending),
            )
            if done == len(chunk) or done % (bs * 4) == 0:
                _actress_opt_log(f"写入 {done}/{len(pending)}")

    try:
        _FACETS_CACHE.clear()
    except Exception:  # noqa: BLE001
        pass
    _actress_opt_progress(
        stage="done",
        percent=100,
        label="完成",
        done=written,
        total=len(pending),
    )
    _actress_opt_log(
        f"完成 · 更新 {written:,} · 重嵌 {reembedded:,} · 未变 {unchanged:,}"
    )
    return {
        "ok": True,
        "total": total,
        "unchanged": unchanged,
        "updated": written,
        "reembedded": reembedded,
        "maps": maps_info,
    }


def start_actress_optimize_job(
    *, reembed: bool = True, limit: int | None = None
) -> dict[str, Any]:
    with _ACTRESS_OPT_LOCK:
        if _actress_opt_job["running"]:
            raise RuntimeError("女优元数据优化已在运行")
        if get_job_status().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        _actress_opt_job.update(
            {
                "running": True,
                "phase": "starting",
                "progress": {
                    "stage": "prepare",
                    "percent": 0,
                    "label": "starting",
                    "done": 0,
                    "total": None,
                },
                "log": [],
                "result": None,
                "error": None,
            }
        )

    def run() -> None:
        try:
            result = optimize_actress_metadata(reembed=reembed, limit=limit)
            with _ACTRESS_OPT_LOCK:
                _actress_opt_job["result"] = result
                _actress_opt_job["phase"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("actress optimize failed")
            with _ACTRESS_OPT_LOCK:
                _actress_opt_job["error"] = str(e)
                _actress_opt_job["phase"] = "error"
                log_list = list(_actress_opt_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _actress_opt_job["log"] = log_list[-40:]
        finally:
            with _ACTRESS_OPT_LOCK:
                _actress_opt_job["running"] = False

    threading.Thread(
        target=run, name="scrap-actress-optimize", daemon=True
    ).start()
    return {"started": True}


def local_file_api(rel: str) -> str:
    """前端可直接请求的本地封面接口路径。"""
    from urllib.parse import quote

    r = str(rel or "").replace("\\", "/").lstrip("/")
    if not r:
        return ""
    return f"/scrap-library/file?path={quote(r, safe='')}"


def resolve_local_file(rel: str) -> Path:
    """把 media 相对路径解析为绝对文件；禁止逃逸。"""
    text = str(rel or "").strip().replace("\\", "/")
    parts = [x for x in Path(text).parts if x not in ("", ".", "/")]
    if not parts or any(x == ".." for x in parts):
        raise ValueError("非法路径")
    abs_path = (media_dir() / Path(*parts)).resolve()
    try:
        abs_path.relative_to(media_dir().resolve())
    except ValueError as e:
        raise ValueError("路径越界") from e
    if not abs_path.is_file():
        raise FileNotFoundError(f"文件不存在: {text}")
    return abs_path
