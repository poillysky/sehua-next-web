# -*- coding: utf-8 -*-
"""刮削库 NFO → 元库 (SNS_META_DSN / :5439) pgvector。"""

from __future__ import annotations

import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from . import settings_store
from .ai_config import resolve_embed_config
from .ai_embed import encode_texts_sync
from .db import media_dir, get_meta_pool, init_db, meta_dsn_label
from .scrap_library_nfo import (
    build_nfo_embed_text,
    content_sha,
    item_id_from_rel,
    parse_nfo,
)

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


def _image_looks_blank(path: Path) -> bool:
    """低色彩多样性 / 近灰白平铺 → 视为空封面。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            rgb = im.convert("RGB")
            small = rgb.resize((24, 24), Image.Resampling.BILINEAR)
            pixels = list(small.getdata())
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
    except Exception:
        return False
    return False


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


def _existing_shas(item_ids: list[str]) -> dict[str, str]:
    if not item_ids:
        return {}
    out: dict[str, str] = {}
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            # 分批，避免超大 IN
            for i in range(0, len(item_ids), 800):
                chunk = item_ids[i : i + 800]
                cur.execute(
                    f"SELECT item_id, content_sha FROM {TABLE} WHERE item_id = ANY(%s)",
                    (chunk,),
                )
                for row in cur.fetchall():
                    if isinstance(row, dict):
                        out[str(row["item_id"])] = str(row["content_sha"])
                    else:
                        out[str(row[0])] = str(row[1])
    return out


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
    total = len(items)
    _push_log(f"发现 {total} 条 NFO · 元库 {meta_dsn_label()}")
    if total == 0:
        warmup_thread.join(timeout=1)
        prog("done", percent=100, label="无 NFO", done=0, total=0)
        return {
            "written": 0,
            "skipped": 0,
            "total": 0,
            "root": str(abs_root),
            "meta_db": meta_dsn_label(),
            "dim": schema["dim"],
        }

    prog("diff", percent=22, label="比对已有向量…", done=0, total=total)
    existing = {} if force else _existing_shas([it["item_id"] for it in items])
    pending = [
        it
        for it in items
        if force or existing.get(it["item_id"]) != it["content_sha"]
    ]
    skipped_items = [
        it
        for it in items
        if not force and existing.get(it["item_id"]) == it["content_sha"]
    ]
    skipped = len(skipped_items)
    _push_log(f"待写入 {len(pending)} · 跳过未变 {skipped}")
    prog(
        "embed",
        percent=24,
        label=f"待写入 {len(pending)}",
        done=0,
        total=len(pending),
    )

    written = 0
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
        "total": total,
        "root": str(abs_root),
        "meta_db": meta_dsn_label(),
        "table": TABLE,
        "dim": schema["dim"],
        "index": f"{TABLE}_hnsw",
    }
    prog("done", percent=100, label="完成", done=written, total=len(pending))
    _push_log(
        f"完成 · 写入 {written} · 跳过 {skipped} · 合计 {total} · HNSW → {meta_dsn_label()}"
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
    out: dict[str, Any] = {
        "itemId": row.get("item_id"),
        "region": row.get("region") or "",
        "prefix": row.get("prefix") or "",
        "code": row.get("code") or "",
        "title": row.get("title") or "",
        "sourceText": row.get("source_text") or "",
        "posterPath": poster,
        "thumbPath": thumb,
        "fanartPath": fanart,
        "coverUrl": str(row.get("cover_url") or ""),
        "posterApi": local_file_api(poster) if poster else "",
        "thumbApi": local_file_api(thumb) if thumb else "",
        "fanartApi": local_file_api(fanart) if fanart else "",
    }
    if score is not None:
        out["score"] = float(score)
    return out


def _region_match_values(region: str | None) -> list[str]:
    """japan_censored / 日本有码 → 可匹配的 region 列取值。"""
    from .region_meta import REGION_META, resolve_fs_region

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
    from .region_meta import REGION_META, REGION_ORDER

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


def list_prefixes(*, region: str = "", studio: str = "") -> list[dict[str, Any]]:
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
        if studio_q in {"未标注厂牌", "未标注", "(unknown)"}:
            clauses.append(
                "(source_text !~ '片商：' OR NULLIF(substring(source_text from '片商：(.+?)(?:\\n|$)'), '') IS NULL)"
            )
        else:
            clauses.append("source_text ILIKE %s")
            params.append(f"%片商：%{studio_q}%")
    where = " AND ".join(clauses)
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT prefix, count(*)::int AS n,
                       array_agg(
                         COALESCE(
                           NULLIF(poster_path, ''),
                           NULLIF(thumb_path, '')
                         )
                         ORDER BY code ASC
                       ) FILTER (
                         WHERE coalesce(poster_path,'') <> ''
                            OR coalesce(thumb_path,'') <> ''
                       ) AS posters
                FROM {TABLE}
                WHERE {where}
                GROUP BY prefix
                ORDER BY prefix ASC
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
                if len(candidates) >= 32:
                    break
        paths = _pick_collage_posters(candidates, limit=4)
        primary = paths[0] if paths else ""
        out.append(
            {
                "prefix": str(row.get("prefix") or ""),
                "count": int(row.get("n") or 0),
                "posterPath": primary,
                "posterApi": local_file_api(primary) if primary else "",
                "posterApis": [local_file_api(p) for p in paths],
            }
        )
    return out


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
) -> dict[str, Any]:
    """分页浏览刮削库条目（海报墙）。"""
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
    match = _region_match_values(region)
    if match:
        clauses.append("region = ANY(%s)")
        params.append(match)
    if pref:
        clauses.append("upper(prefix) = %s")
        params.append(pref)
    if query:
        like = f"%{query}%"
        clauses.append("(code ILIKE %s OR title ILIKE %s OR prefix ILIKE %s)")
        params.extend([like, like, like])
    if genre_q:
        # source_text 行：类型：a b c
        clauses.append("source_text ILIKE %s")
        params.append(f"%类型：%{genre_q}%")
    if tag_q:
        # 标签行，或回退女优名
        clauses.append("(source_text ILIKE %s OR source_text ILIKE %s)")
        params.extend([f"%标签：%{tag_q}%", f"%女优：%{tag_q}%"])
    if studio_q:
        if studio_q in {"未标注厂牌", "未标注", "(unknown)"}:
            clauses.append(
                "(source_text !~ '片商：' OR NULLIF(substring(source_text from '片商：(.+?)(?:\\n|$)'), '') IS NULL)"
            )
        else:
            clauses.append("source_text ILIKE %s")
            params.append(f"%片商：%{studio_q}%")
    if actress_q:
        if actress_q in {"未标注女优", "未标注", "(unknown)"}:
            clauses.append(
                "(source_text !~ '女优：' OR NULLIF(substring(source_text from '女优：(.+?)(?:\\n|$)'), '') IS NULL)"
            )
        else:
            clauses.append("source_text ILIKE %s")
            params.append(f"%女优：%{actress_q}%")
    where = " AND ".join(clauses)

    if sort_key in {"recent", "updated", "new", "dateadded"}:
        order_sql = (
            f"updated_at {'ASC' if ascending else 'DESC'} NULLS LAST, code DESC"
        )
    elif sort_key in {"year", "premiere", "date"}:
        # 年份：2024
        order_sql = (
            f"(NULLIF(substring(source_text from '年份：([0-9]{{4}})'), ''))::int "
            f"{'ASC' if ascending else 'DESC'} NULLS LAST, code ASC"
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
                  item_id, region, prefix, code, title, source_text,
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


_FACET_LINE_RE = {
    "genre": re.compile(r"^类型：(.+)$", re.M),
    "tag": re.compile(r"^标签：(.+)$", re.M),
    "studio": re.compile(r"^片商：(.+)$", re.M),
    "actress": re.compile(r"^女优：(.+)$", re.M),
}
_CODEISH_RE = re.compile(r"^[A-Za-z]{1,12}-?\d{0,6}[A-Za-z]?$")


def _split_tokens(raw: str) -> list[str]:
    out: list[str] = []
    for token in re.split(r"[\s/|、，,]+", str(raw or "")):
        name = token.strip()
        if name:
            out.append(name)
    return out


def list_facets(
    *,
    region: str = "",
    kind: str = "genre",
    studio: str = "",
    prefix: str = "",
) -> list[dict[str, Any]]:
    """从 source_text 汇总流派 / 标签 / 片商。"""
    key = str(kind or "genre").strip().lower()
    if key in {"genres", "类型"}:
        key = "genre"
    elif key in {"tags", "标签"}:
        key = "tag"
    elif key in {"studios", "maker", "片商", "合集"}:
        key = "studio"
    elif key in {"actress", "actor", "女优"}:
        key = "actress"
    if key not in {"genre", "tag", "studio", "actress"}:
        raise ValueError("kind 仅支持 genre / tag / studio / actress")

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
        if studio_q in {"未标注厂牌", "未标注", "(unknown)"}:
            clauses.append(
                "(source_text !~ '片商：' OR NULLIF(substring(source_text from '片商：(.+?)(?:\\n|$)'), '') IS NULL)"
            )
        else:
            clauses.append("source_text ILIKE %s")
            params.append(f"%片商：%{studio_q}%")
    if pref:
        clauses.append("upper(prefix) = %s")
        params.append(pref)
    where = " AND ".join(clauses)

    pool = get_meta_pool()
    counts: dict[str, int] = {}
    posters: dict[str, list[str]] = {}
    unknown_studio = 0
    unknown_actress = 0
    unknown_studio_posters: list[str] = []
    unknown_actress_posters: list[str] = []
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT source_text, poster_path, thumb_path, prefix
                FROM {TABLE}
                WHERE {where}
                """,
                params,
            )
            for row in cur.fetchall():
                if not isinstance(row, dict):
                    continue
                text = str(row.get("source_text") or "")
                poster = str(row.get("poster_path") or "").strip() or str(
                    row.get("thumb_path") or ""
                ).strip()
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
                elif key == "studio":
                    m = _FACET_LINE_RE["studio"].search(text)
                    names = [m.group(1).strip()] if m and m.group(1).strip() else []
                    if not names:
                        unknown_studio += 1
                        if poster and poster not in unknown_studio_posters:
                            unknown_studio_posters.append(poster)
                elif key == "actress":
                    names = list(actresses)
                    if not names:
                        unknown_actress += 1
                        if poster and poster not in unknown_actress_posters:
                            unknown_actress_posters.append(poster)
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

    out: list[dict[str, Any]] = []
    out_kind = "tag" if key == "actress" else key
    for name, n in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        paths = _pick_collage_posters(posters.get(name) or [], limit=4)
        primary = paths[0] if paths else ""
        out.append(
            {
                "name": name,
                "count": n,
                "kind": out_kind,
                "posterPath": primary,
                "posterApi": local_file_api(primary) if primary else "",
                "posterApis": [local_file_api(p) for p in paths if p],
            }
        )
    if key == "studio" and unknown_studio > 0:
        paths = _pick_collage_posters(unknown_studio_posters, limit=4)
        primary = paths[0] if paths else ""
        out.append(
            {
                "name": "未标注厂牌",
                "count": unknown_studio,
                "kind": out_kind,
                "posterPath": primary,
                "posterApi": local_file_api(primary) if primary else "",
                "posterApis": [local_file_api(p) for p in paths if p],
            }
        )
    if key == "actress" and unknown_actress > 0:
        paths = _pick_collage_posters(unknown_actress_posters, limit=4)
        primary = paths[0] if paths else ""
        out.append(
            {
                "name": "未标注女优",
                "count": unknown_actress,
                "kind": out_kind,
                "posterPath": primary,
                "posterApi": local_file_api(primary) if primary else "",
                "posterApis": [local_file_api(p) for p in paths if p],
            }
        )
    return out


def list_recommend(*, region: str = "") -> dict[str, Any]:
    """Emby「推荐」：最新影片 + 流派 / 文件夹(厂牌)预览。"""
    latest = list_items(region=region, sort="recent", offset=0, limit=18)
    studios = list_facets(region=region, kind="studio")
    return {
        "latest": latest.get("items") or [],
        "genres": list_facets(region=region, kind="genre")[:12],
        "collections": studios[:12],
        # 文件夹入口改为厂牌，与库内「文件夹」钻取一致
        "folders": [
            {
                "prefix": s["name"],
                "count": s["count"],
                "posterPath": s.get("posterPath") or "",
                "posterApi": s.get("posterApi") or "",
                "posterApis": s.get("posterApis") or [],
            }
            for s in studios[:12]
        ],
        "total": int(latest.get("total") or 0),
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
    region_sql = ""
    params: list[Any] = [vec]
    if match:
        region_sql = "WHERE region = ANY(%s)"
        params.append(match)
    params.extend([vec, top_k])
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  item_id, region, prefix, code, title, source_text,
                  poster_path, thumb_path, fanart_path, cover_url,
                  1 - (embedding <=> %s::vector) AS score
                FROM {TABLE}
                {region_sql}
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
