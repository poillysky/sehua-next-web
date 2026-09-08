"""Fast Postgres resource-data dump/restore → backups/*.zip (COPY binary, ZIP_STORED)."""

from __future__ import annotations

import json
import logging
import re
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql

from .db import ROOT

logger = logging.getLogger("app.pg_data_backup")

KIND_RESOURCE = "resource-db"
KIND_BITMAGNET = "bitmagnet-db"

# 上传备份 zip 的大小上限：防止超大文件写满磁盘（导入前即中断）
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

# 色花资源库：只导资源数据，不含 auth_* 等
RESOURCE_TABLES = (
    "ed2k_resources",
    "resource_sources",
    "sources",
    "tags",
    "resource_tags",
    "av_metadata",
    "av_scrape_queue",
    "sehua_resource_embed",
    "sehua_search_prefix_code_index",
    "import_jobs",
    "collector_settings",
    "schema_migrations",
)

# Bitmagnet：磁力索引与内容元数据（不含 queue_jobs / goose）
BITMAGNET_TABLES = (
    "torrent_files",
    "torrent_contents",
    "torrents",
    "torrents_torrent_sources",
    "content",
    "content_attributes",
    "content_collections_content",
    "content_collections",
    "torrent_sources",
    "metadata_sources",
    "torrent_tags",
    "bloom_filters",
    "key_values",
    "torrent_pieces",
    "torrent_hints",
    "bitmagnet_torrent_embed",
)

TABLES_BY_KIND: dict[str, tuple[str, ...]] = {
    KIND_RESOURCE: RESOURCE_TABLES,
    KIND_BITMAGNET: BITMAGNET_TABLES,
}

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,180}$")
_WORKERS = 3


def _wanted_tables(kind: str) -> tuple[str, ...]:
    tables = TABLES_BY_KIND.get(kind)
    if not tables:
        raise ValueError(f"未知备份类型：{kind}")
    return tables


def backups_root(kind: str) -> Path:
    d = ROOT / "backups" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quote_ident(name: str) -> sql.Composed:
    return sql.Identifier(name)


def _list_existing_tables(conn: psycopg.Connection, wanted: tuple[str, ...]) -> list[str]:
    rows = conn.execute(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = ANY(%s)
        ORDER BY c.relname
        """,
        (list(wanted),),
    ).fetchall()
    found = {str(r[0]) for r in rows}
    # 稳定顺序：按 wanted 定义顺序（大表靠前，利于并行）
    return [t for t in wanted if t in found]


def _dump_one_table(dsn: str, table: str, dest: Path) -> dict[str, Any]:
    t0 = time.perf_counter()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(dsn, connect_timeout=15) as conn:
        conn.execute("SET statement_timeout = 0")
        with conn.cursor() as cur:
            with open(dest, "wb", buffering=8 * 1024 * 1024) as f:
                with cur.copy(
                    sql.SQL("COPY {} TO STDOUT WITH (FORMAT binary)").format(_quote_ident(table))
                ) as copy:
                    while True:
                        chunk = copy.read()
                        if not chunk:
                            break
                        f.write(chunk)
    size = dest.stat().st_size if dest.is_file() else 0
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "name": table,
        "rows": -1,
        "bytes": size,
        "elapsedMs": elapsed_ms,
    }


def _zip_add_file(zf: zipfile.ZipFile, arcname: str, path: Path) -> None:
    # ZIP_STORED：不压缩，大表导出显著更快
    zf.write(path, arcname=arcname, compress_type=zipfile.ZIP_STORED)


def canonical_zip_name(kind: str) -> str:
    return f"{kind}.zip"


def _cleanup_other_zips(kind: str, keep: Path) -> None:
    """只保留当前这一份，删掉同目录其它 zip，避免多份占盘。"""
    root = backups_root(kind)
    keep_res = keep.resolve()
    for p in root.glob("*.zip"):
        try:
            if p.resolve() == keep_res:
                continue
            p.unlink()
        except OSError:
            pass


def export_resource_zip(dsn: str, *, kind: str = KIND_RESOURCE) -> dict[str, Any]:
    """Export resource tables to backups/<kind>/<kind>.zip（覆盖旧文件）。"""
    dsn = (dsn or "").strip()
    if not dsn:
        raise ValueError("DSN 未配置")

    root = backups_root(kind)
    stamp = _now_stamp()
    work = root / f".tmp_{stamp}"
    if work.exists():
        _rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    zip_name = canonical_zip_name(kind)
    zip_path = root / zip_name
    partial = root / f".{kind}_{stamp}.partial.zip"

    t0 = time.perf_counter()
    try:
        with psycopg.connect(dsn, connect_timeout=15) as conn:
            dbname = conn.execute("SELECT current_database()").fetchone()[0]
            tables = _list_existing_tables(conn, _wanted_tables(kind))
            if not tables:
                raise ValueError("未找到可导出的资源表")

        data_dir = work / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        table_meta: list[dict[str, Any]] = []

        # 大表并行 COPY
        with ThreadPoolExecutor(max_workers=min(_WORKERS, len(tables))) as pool:
            futs = {
                pool.submit(_dump_one_table, dsn, t, data_dir / f"{t}.bin"): t for t in tables
            }
            for fut in as_completed(futs):
                table_meta.append(fut.result())

        table_meta.sort(key=lambda m: tables.index(m["name"]) if m["name"] in tables else 999)

        # 序列：仅保留「被导出表列拥有」的
        sequences: list[dict[str, Any]] = []
        with psycopg.connect(dsn, connect_timeout=15) as conn:
            seq_rows = conn.execute(
                """
                SELECT DISTINCT s.relname
                FROM pg_class t
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_depend d ON d.refobjid = t.oid AND d.deptype = 'a'
                JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
                WHERE n.nspname = 'public'
                  AND t.relkind = 'r'
                  AND t.relname = ANY(%s)
                ORDER BY 1
                """,
                (tables,),
            ).fetchall()
            for (seq_name,) in seq_rows:
                name = str(seq_name)
                last = conn.execute(
                    sql.SQL("SELECT last_value, is_called FROM {}").format(sql.Identifier(name))
                ).fetchone()
                sequences.append(
                    {
                        "name": name,
                        "lastValue": int(last[0]),
                        "isCalled": bool(last[1]),
                    }
                )

        manifest = {
            "kind": kind,
            "version": 1,
            "format": "copy-binary-zip-v1",
            "createdAt": _iso_now(),
            "database": str(dbname),
            "tables": table_meta,
            "sequences": sequences,
        }
        (work / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if partial.exists():
            partial.unlink()
        with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            zf.write(work / "manifest.json", arcname="manifest.json")
            for m in table_meta:
                _zip_add_file(zf, f"data/{m['name']}.bin", data_dir / f"{m['name']}.bin")
            if sequences:
                seq_path = work / "sequences.json"
                seq_path.write_text(
                    json.dumps(sequences, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                zf.write(seq_path, arcname="sequences.json")

        # 覆盖固定文件名，并清掉其它历史 zip
        if zip_path.exists():
            zip_path.unlink()
        partial.replace(zip_path)
        _cleanup_other_zips(kind, zip_path)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        size = zip_path.stat().st_size
        logger.info(
            "resource backup done kind=%s file=%s bytes=%s ms=%s tables=%s",
            kind,
            zip_path.name,
            size,
            elapsed_ms,
            len(table_meta),
        )
        return {
            "filename": zip_path.name,
            "relPath": f"backups/{kind}/{zip_path.name}",
            "bytes": size,
            "elapsedMs": elapsed_ms,
            "tables": table_meta,
            "createdAt": manifest["createdAt"],
        }
    except Exception:
        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass
        raise
    finally:
        _rmtree(work)


def list_backups(kind: str = KIND_RESOURCE) -> list[dict[str, Any]]:
    root = backups_root(kind)
    items: list[dict[str, Any]] = []
    for p in sorted(root.glob("*.zip"), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.name.startswith("."):
            continue
        st = p.stat()
        items.append(
            {
                "filename": p.name,
                "relPath": f"backups/{kind}/{p.name}",
                "bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
    return items


def _safe_backup_path(kind: str, filename: str) -> Path:
    name = (filename or "").strip()
    if not _SAFE_NAME_RE.match(name) or not name.endswith(".zip"):
        raise ValueError("无效的备份文件名")
    path = (backups_root(kind) / name).resolve()
    root = backups_root(kind).resolve()
    if path.parent != root or not path.is_file():
        raise ValueError("备份文件不存在")
    return path


def _peek_manifest_kind(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError as e:
            raise ValueError("备份缺少 manifest.json") from e
        if str(manifest.get("format") or "") != "copy-binary-zip-v1":
            raise ValueError("不支持的备份格式")
        return str(manifest.get("kind") or "")


def save_uploaded_zip(kind: str, *, source, original_name: str = "") -> dict[str, Any]:
    """Save uploaded zip as backups/<kind>/<kind>.zip（覆盖旧文件）。"""
    _ = original_name
    root = backups_root(kind)
    dest = root / canonical_zip_name(kind)
    tmp = root / f".upload_{_now_stamp()}.partial"
    try:
        written = 0
        with open(tmp, "wb", buffering=8 * 1024 * 1024) as out:
            while True:
                chunk = source.read(8 * 1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > _MAX_UPLOAD_BYTES:
                    raise ValueError(
                        f"上传文件超过上限 {_MAX_UPLOAD_BYTES // (1024 * 1024)}MB，已中断"
                    )
                out.write(chunk)
        if tmp.stat().st_size < 64:
            raise ValueError("上传文件过小，不是有效备份")
        peeked = _peek_manifest_kind(tmp)
        if peeked != kind:
            raise ValueError(
                f"备份类型不匹配：文件是 {peeked or '未知'}，当前是 {kind}"
            )
        if dest.exists():
            dest.unlink()
        tmp.replace(dest)
        _cleanup_other_zips(kind, dest)
        return {
            "filename": dest.name,
            "relPath": f"backups/{kind}/{dest.name}",
            "bytes": dest.stat().st_size,
        }
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def import_resource_zip(dsn: str, filename: str, *, kind: str = KIND_RESOURCE) -> dict[str, Any]:
    """Replace resource tables from a zip under backups/<kind>/."""
    dsn = (dsn or "").strip()
    if not dsn:
        raise ValueError("DSN 未配置")
    zip_path = _safe_backup_path(kind, filename)
    t0 = time.perf_counter()

    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError as e:
            raise ValueError("备份缺少 manifest.json") from e
        if str(manifest.get("kind") or "") != kind:
            raise ValueError("备份类型不匹配")
        if str(manifest.get("format") or "") != "copy-binary-zip-v1":
            raise ValueError("不支持的备份格式")
        tables = [str(t.get("name") or "") for t in (manifest.get("tables") or []) if t.get("name")]
        if not tables:
            raise ValueError("备份没有表")
        # 表名白名单校验：防止恶意 name 携带路径穿越到备份根目录之外
        bad = [n for n in tables if not re.fullmatch(r"[A-Za-z0-9_]{1,120}", n)]
        if bad:
            raise ValueError(f"备份含非法表名: {bad[:3]}")

        # 抽出到临时目录再 COPY（大文件流式进 psycopg 更稳）
        work = backups_root(kind) / f".restore_{_now_stamp()}"
        try:
            work.mkdir(parents=True, exist_ok=True)
            data_dir = work / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            for name in tables:
                arc = f"data/{name}.bin"
                if arc not in zf.namelist():
                    raise ValueError(f"备份缺少 {arc}")
                target = data_dir / f"{name}.bin"
                with zf.open(arc) as src, open(target, "wb", buffering=8 * 1024 * 1024) as dst:
                    while True:
                        chunk = src.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)

            sequences: list[dict[str, Any]] = []
            if "sequences.json" in zf.namelist():
                sequences = json.loads(zf.read("sequences.json").decode("utf-8"))

            restored: list[dict[str, Any]] = []
            with psycopg.connect(dsn, connect_timeout=15) as conn:
                conn.execute("SET statement_timeout = 0")
                conn.execute("SET session_replication_role = replica")
                # 只清空将恢复的表
                existing = _list_existing_tables(conn, tuple(tables))
                missing = [t for t in tables if t not in existing]
                if missing:
                    raise ValueError(f"目标库缺少表：{', '.join(missing)}")

                with conn.transaction():
                    if existing:
                        conn.execute(
                            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                                sql.SQL(", ").join(sql.Identifier(t) for t in existing)
                            )
                        )
                    for name in tables:
                        path = data_dir / f"{name}.bin"
                        with conn.cursor() as cur:
                            with open(path, "rb", buffering=8 * 1024 * 1024) as f:
                                with cur.copy(
                                    sql.SQL("COPY {} FROM STDIN WITH (FORMAT binary)").format(
                                        sql.Identifier(name)
                                    )
                                ) as copy:
                                    while True:
                                        chunk = f.read(8 * 1024 * 1024)
                                        if not chunk:
                                            break
                                        copy.write(chunk)
                        cnt = conn.execute(
                            sql.SQL("SELECT count(*)::bigint FROM {}").format(sql.Identifier(name))
                        ).fetchone()[0]
                        restored.append({"name": name, "rows": int(cnt)})

                    for seq in sequences:
                        sname = str(seq.get("name") or "")
                        if not sname:
                            continue
                        exists = conn.execute(
                            """
                            SELECT 1 FROM pg_class c
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE n.nspname = 'public' AND c.relkind = 'S' AND c.relname = %s
                            """,
                            (sname,),
                        ).fetchone()
                        if not exists:
                            continue
                        last = int(seq.get("lastValue") or 1)
                        is_called = bool(seq.get("isCalled", True))
                        conn.execute(
                            "SELECT setval(%s::regclass, %s, %s)",
                            (sname, last, is_called),
                        )
                conn.execute("SET session_replication_role = DEFAULT")

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            return {
                "filename": zip_path.name,
                "elapsedMs": elapsed_ms,
                "tables": restored,
            }
        finally:
            _rmtree(work)


def _rmtree(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        try:
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        except OSError:
            pass
    try:
        path.rmdir()
    except OSError:
        pass
