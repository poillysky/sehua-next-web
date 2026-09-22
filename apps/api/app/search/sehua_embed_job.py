"""色花资源向量：建表 / 灌数 / 试检索。

  python -m app.sehua_embed_job ensure-schema --dsn "$DSN"
  python -m app.sehua_embed_job ingest --dsn "$DSN" --limit 50
  python -m app.sehua_embed_job ingest --dsn "$DSN" --all
  python -m app.sehua_embed_job search --dsn "$DSN" "人妻 寝取"
  python -m app.sehua_embed_job stats --dsn "$DSN"
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.search.sehua_embed import row_embed_payload
import app.search.sehua_resource_embed_svc as svc
from app.core.cli_io import configure_stdio as _configure_stdio
from app.core.cli_io import safe_print as _safe_print

DEFAULT_LIMIT = 50
FETCH_SQL = """
SELECT r.hash, r.filename, rs.title, rs.description, rs.board_name
FROM ed2k_resources r
JOIN resource_sources rs ON rs.hash = r.hash
LEFT JOIN sehua_resource_embed e ON e.hash = r.hash
WHERE e.hash IS NULL
  AND (%s OR rs.board_name ILIKE %s)
ORDER BY r.created_at DESC NULLS LAST
LIMIT %s
"""
INSERT_SQL = """
INSERT INTO sehua_resource_embed
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
SEARCH_SQL = """
SELECT
  e.hash,
  rs.title,
  r.filename,
  rs.board_name,
  e.source_text,
  1 - (e.embedding <=> %s::vector) AS score
FROM sehua_resource_embed e
JOIN resource_sources rs ON rs.hash = e.hash
JOIN ed2k_resources r ON r.hash = e.hash
ORDER BY e.embedding <=> %s::vector
LIMIT %s
"""


def _resolve_dsn(cli_dsn: str | None) -> str:
    dsn = (cli_dsn or "").strip() or str(os.environ.get("SEHUA_RESOURCE_DSN") or "").strip()
    if dsn:
        return dsn
    from app.core.db import init_db
    import app.core.settings_store as settings_store

    init_db()
    raw = settings_store.get_setting(settings_store.RESOURCE_DB_KEY) or {}
    if bool(raw.get("enabled")) and str(raw.get("dsn") or "").strip():
        return str(raw["dsn"]).strip()
    raise SystemExit("缺少 DSN：传 --dsn 或设环境变量 SEHUA_RESOURCE_DSN")


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row)


def _vec_literal(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


def _embed_cfg() -> dict[str, Any]:
    from app.core.db import init_db

    init_db()
    return resolve_embed_config(include_secret=True)


def cmd_ensure_schema(*, recreate: bool = False) -> None:
    info = svc.ensure_schema(recreate=recreate)
    print(f"schema ok: {info}")


def cmd_stats() -> None:
    st = svc.stats()
    print(
        "vector_ext={ext} resources={res} embedded={emb} pending={pen} indexes={idx}".format(
            ext=st.get("vectorExt") or "missing",
            res=st.get("resources"),
            emb=st.get("embedded"),
            pen=st.get("pending"),
            idx=",".join(st.get("indexes") or []) or "-",
        )
    )


def _fetch_pending(
    conn: psycopg.Connection, *, limit: int, board_like: str
) -> list[dict[str, Any]]:
    like = (board_like or "").strip()
    any_board = not like
    pattern = like if like else "%"
    with conn.cursor() as cur:
        cur.execute(FETCH_SQL, [any_board, pattern, limit])
        return list(cur.fetchall())


def cmd_ingest_limited(
    conn: psycopg.Connection,
    *,
    limit: int,
    batch_size: int,
    board_like: str,
) -> None:
    if limit <= 0:
        raise SystemExit("--limit 须 > 0；全库请用 --all")
    rows = _fetch_pending(conn, limit=limit, board_like=board_like)
    if not rows:
        print("ingest skip: 没有待嵌入行（或已全部有向量）")
        return
    print(f"ingest fetch {len(rows)} rows")
    cfg = _embed_cfg()
    model_name = str(cfg["model"])
    dim = int(cfg["dim"])
    print(f"embed model {model_name} ({cfg['provider']}) dim={dim}")
    payloads = [row_embed_payload(r) for r in rows]
    written = 0
    for i in range(0, len(payloads), batch_size):
        chunk = payloads[i : i + batch_size]
        vecs = encode_texts_sync([p["source_text"] for p in chunk], query=False)
        if len(vecs) != len(chunk):
            raise SystemExit(f"向量条数不匹配: {len(vecs)} != {len(chunk)}")
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
        sample = chunk[0]["source_text"].replace("\n", " | ")
        _safe_print(f"  wrote {written}/{len(payloads)}  e.g. {sample[:160]}")
    print(f"ingest done: {written}")


def cmd_ingest_all(*, force: bool) -> None:
    print("full ingest via service…")
    result = svc.ingest(force=force, build_index=True)
    print(f"ingest done: {result}")


def cmd_create_index() -> None:
    info = svc.create_hnsw_index()
    print(f"index ok: {info}")


def cmd_search(conn: psycopg.Connection, query: str, limit: int) -> None:
    q = str(query or "").strip()
    if not q:
        raise SystemExit("查询为空")
    vec = _vec_literal(encode_texts_sync([q], query=True)[0])
    with conn.cursor() as cur:
        cur.execute(SEARCH_SQL, [vec, vec, limit])
        rows = list(cur.fetchall())
    if not rows:
        print("search: 表是空的，先 ingest")
        return
    _safe_print(f"search q={query!r} hits={len(rows)}")
    for i, row in enumerate(rows, 1):
        title = str(row.get("title") or "")[:80]
        board = str(row.get("board_name") or "")
        score = float(row.get("score") or 0)
        _safe_print(f"{i:2d}  {score:.4f}  [{board}] {title}")


def cmd_preview(conn: psycopg.Connection, limit: int, board_like: str) -> None:
    rows = _fetch_pending(conn, limit=limit, board_like=board_like)
    print(f"preview {len(rows)} pending rows")
    for i, row in enumerate(rows, 1):
        p = row_embed_payload(row)
        text = p["source_text"].replace("\n", " | ")
        _safe_print(f"{i:2d}  {p['hash'][:12]}  {text[:200]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="色花资源向量灌库")
    parser.add_argument("--dsn", default="", help="资源库 Postgres DSN")
    sub = parser.add_subparsers(dest="cmd", required=True)

    schema = sub.add_parser("ensure-schema", help="建扩展 + 表")
    schema.add_argument("--recreate", action="store_true")
    sub.add_parser("stats", help="条数 / 索引")
    preview = sub.add_parser("preview", help="只看拼出来的文本")
    preview.add_argument("--limit", type=int, default=10)
    preview.add_argument("--board-like", default="")

    ingest = sub.add_parser("ingest", help="写入向量")
    ingest.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ingest.add_argument("--batch-size", type=int, default=16)
    ingest.add_argument("--board-like", default="")
    ingest.add_argument("--all", action="store_true", help="全库增量（缺向量的行）")
    ingest.add_argument("--force", action="store_true", help="与 --all 联用：强制重写")

    sub.add_parser("create-index", help="建 HNSW")
    search = sub.add_parser("search", help="自然语言试检索")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)

    _configure_stdio()
    args = parser.parse_args(argv)
    dsn = _resolve_dsn(args.dsn)
    os.environ["SEHUA_RESOURCE_DSN"] = dsn

    if args.cmd == "ensure-schema":
        cmd_ensure_schema(recreate=bool(getattr(args, "recreate", False)))
        return
    if args.cmd == "stats":
        cmd_stats()
        return
    if args.cmd == "create-index":
        cmd_create_index()
        return
    if args.cmd == "ingest" and bool(args.all):
        cmd_ingest_all(force=bool(args.force))
        return

    with _connect(dsn) as conn:
        if args.cmd == "preview":
            cmd_preview(conn, args.limit, str(args.board_like or ""))
        elif args.cmd == "ingest":
            svc.ensure_schema()
            cmd_ingest_limited(
                conn,
                limit=int(args.limit),
                batch_size=max(1, int(args.batch_size)),
                board_like=str(args.board_like or ""),
            )
        elif args.cmd == "search":
            cmd_search(conn, args.query, int(args.limit))
        else:
            parser.error(args.cmd)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
