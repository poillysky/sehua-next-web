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

from . import settings_store
from .ai_config import resolve_embed_config
from .ai_embed import encode_texts_sync
from .db import data_dir, media_dir, get_meta_pool, init_db, meta_dsn_label
from .scrap_library_nfo import (
    build_nfo_embed_text,
    content_sha,
    item_id_from_rel,
    parse_nfo,
)
from .ttl_cache import enforce_max, prune_by_age

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


def _quality_region_sql(region: str) -> tuple[str, list[Any]]:
    values = _region_match_values(region)
    if not values:
        return "", []
    return " AND region = ANY(%s)", [values]


def _row_gaps(row: dict[str, Any]) -> list[str]:
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
    """刮削库元数据缺口计数（按区）。"""
    ensure_schema()
    region_sql, params = _quality_region_sql(region)
    pool = get_meta_pool()
    counts: dict[str, int] = {k: 0 for k in QUALITY_KINDS}
    total = 0
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) AS n FROM {TABLE} WHERE true{region_sql}",
            params,
        )
        row = cur.fetchone() or {}
        total = int((row.get("n") if isinstance(row, dict) else row[0]) or 0)
        for kind, pred in _QUALITY_PRED.items():
            cur.execute(
                f"SELECT count(*) AS n FROM {TABLE} WHERE {pred}{region_sql}",
                params,
            )
            r = cur.fetchone() or {}
            counts[kind] = int((r.get("n") if isinstance(r, dict) else r[0]) or 0)
        # 任一缺口
        any_pred = " OR ".join(f"({_QUALITY_PRED[k]})" for k in QUALITY_KINDS)
        cur.execute(
            f"SELECT count(*) AS n FROM {TABLE} WHERE ({any_pred}){region_sql}",
            params,
        )
        r = cur.fetchone() or {}
        incomplete = int((r.get("n") if isinstance(r, dict) else r[0]) or 0)
    return {
        "region": str(region or "").strip() or None,
        "total": total,
        "incomplete": incomplete,
        "counts": counts,
    }


def quality_items(
    *,
    region: str = "",
    kind: str = "no_local",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """待补全队列：code / itemId / relPath / gaps。

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
    region_sql, params = _quality_region_sql(region)
    pred = _QUALITY_PRED[kind_k]
    pool = get_meta_pool()
    sql_limit = "" if unlimited else " LIMIT %s"
    sql_params: list[Any] = [*params]
    if not unlimited:
        sql_params.append(lim)
    sql_params.append(off)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, region, prefix, code, title, rel_path,
                   poster_path, thumb_path, cover_url, source_text
            FROM {TABLE}
            WHERE {pred}{region_sql}
            ORDER BY updated_at DESC NULLS LAST, code ASC
            {sql_limit} OFFSET %s
            """,
            sql_params,
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for raw in rows:
        d = dict(raw) if isinstance(raw, dict) else {}
        if not d and raw is not None:
            # tuple fallback unlikely with dict cursor
            continue
        gaps = _row_gaps(d)
        out.append(
            {
                "itemId": str(d.get("item_id") or ""),
                "region": str(d.get("region") or ""),
                "prefix": str(d.get("prefix") or ""),
                "code": str(d.get("code") or ""),
                "title": str(d.get("title") or ""),
                "relPath": str(d.get("rel_path") or "").replace("\\", "/"),
                "gaps": gaps,
            }
        )
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
        from .cover_focus_routes import _fetch_bytes

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
    # 本地无有效海报时，把 NFO cover 外链落到 poster.jpg
    if not poster_path and _is_http_url(cover_url):
        poster_path = download_remote_poster(
            folder, cover_url, media_root=media_root
        )
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
        for part in re.split(r"[\s、,/|]+", m.group(1).strip()):
            name = part.strip()
            if name and name not in actresses:
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
    from .prefix_maker_names import resolve_maker_intro_for_prefix, resolve_maker_names

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
    from .prefix_maker_names import resolve_maker_intro_for_studio

    raw = str(studio_name or "").strip()
    if not raw or raw in {"未标注厂牌", "未标注", "(unknown)"}:
        return ""
    return resolve_maker_intro_for_studio(raw)


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
        _append_studio_clause(clauses, params, studio_q, region=region)
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
        from .prefix_maker_names import prefix_line_rank

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
    from .studio_display_names import resolve_studio_display

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
    from .studio_display_names import resolve_studio_canon_key, studio_norm_key

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
    from .studio_display_names import (
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
    from .studio_display_names import resolve_studio_for_prefix

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
    from .studio_display_names import resolve_studio_for_prefix

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


_FACETS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_FACETS_CACHE_TTL_S = 600.0
_FACETS_CACHE_MAX = 48

# 磁盘快照：厂牌/标签/女优等全库聚合很慢，落盘后重启仍可秒开
_FACETS_SNAP_DIR = "scrap_facets_snap"
# v2：studio 分面改用 prefix_catalog 分区映射
_FACETS_SNAP_VERSION = 2
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
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
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
    """各 kind 快照是否存在与更新时间（供 UI 提示）。"""
    kinds: dict[str, Any] = {}
    for kind in _FACETS_SNAP_KINDS:
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
) -> dict[str, Any]:
    """重建当前区厂牌/标签/女优磁盘快照（阻塞至完成）。"""
    if kinds:
        want = [_normalize_facet_kind(k) for k in kinds]
    else:
        # 片商页实际用到的三类；tag 保留兼容
        want = ["genre", "actress", "studio"]
    # 去重且保序
    seen: set[str] = set()
    ordered: list[str] = []
    for k in want:
        if k in seen:
            continue
        seen.add(k)
        ordered.append(k)

    built: dict[str, int] = {}
    with _facets_snap_lock:
        for key in ordered:
            rows = _build_facets_all(
                region=region, kind=key, studio="", prefix=""
            )
            _save_facets_snapshot(region, key, rows)
            built[key] = len(rows)
        _purge_facets_memory_cache(region=region)
        now = time.monotonic()
        for key in ordered:
            hit_rows = _load_facets_snapshot(region, key) or []
            _FACETS_CACHE[f"v8|{region}|{key}||"] = (now, list(hit_rows))
        enforce_max(_FACETS_CACHE, _FACETS_CACHE_MAX)
    return {
        "region": str(region or ""),
        "kinds": built,
        "updatedAt": time.time(),
    }


def list_facets(
    *,
    region: str = "",
    kind: str = "genre",
    studio: str = "",
    prefix: str = "",
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

    sorted_rows = _sort_facets(rows, sort=sort, order=order)
    total = len(sorted_rows)
    off = max(0, int(offset or 0))
    if limit is None:
        page = sorted_rows[off:]
    else:
        lim = max(1, min(100, int(limit)))
        page = sorted_rows[off : off + lim]
    return {"facets": page, "total": total}


def list_recommend(*, region: str = "") -> dict[str, Any]:
    """Emby「推荐」：七区各自一条「最新影片」横向货架。

    region 参数保留兼容；推荐页始终返回全部有内容的区。
    """
    from .region_meta import REGION_META, REGION_ORDER

    shelves: list[dict[str, Any]] = []
    total_all = 0
    for rid in REGION_ORDER:
        page = list_items(region=rid, sort="recent", offset=0, limit=12)
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
    # 兼容旧字段：取当前/第一区
    focus = str(region or "").strip()
    focus_shelf = next((s for s in shelves if s["region"] == focus), None)
    if focus_shelf is None and shelves:
        focus_shelf = shelves[0]
    latest = list((focus_shelf or {}).get("latest") or [])
    return {
        "shelves": shelves,
        "latest": latest,
        "genres": [],
        "collections": [],
        "folders": [],
        "total": total_all,
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
                  item_id, region, prefix, code, title, source_text, rel_path,
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
