"""色花资源向量：建表 / 小批量灌数 / 试检索。

试点（默认最多 50 条，不会全库跑）:

  python -m app.sehua_embed_job ensure-schema --dsn "$DSN"
  python -m app.sehua_embed_job ingest --dsn "$DSN" --limit 50
  python -m app.sehua_embed_job search --dsn "$DSN" "人妻 寝取"
  python -m app.sehua_embed_job stats --dsn "$DSN"

全库必须显式 --all（本次不要用）。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from .ai_config import resolve_embed_config
from .ai_embed import encode_texts_sync
from .sehua_embed import row_embed_payload

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_SQL = ROOT / "config" / "sql" / "sehua_resource_embed.sql"
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
HNSW_SQL = """
CREATE INDEX IF NOT EXISTS sehua_resource_embed_hnsw
  ON sehua_resource_embed
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64)
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


def _statements_from_sql(path: Path) -> list[str]:
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("--"):
            continue
        lines.append(line)
    body = "\n".join(lines)
    return [s.strip() for s in body.split(";") if s.strip()]


def _configure_stdio() -> None:
    """Windows 控制台默认 GBK，标题里的符号会直接崩。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


def _resolve_dsn(cli_dsn: str | None) -> str:
    dsn = (cli_dsn or "").strip() or str(os.environ.get("SEHUA_RESOURCE_DSN") or "").strip()
    if dsn:
        return dsn
    from .db import init_db
    from . import settings_store

    init_db()
    raw = settings_store.get_setting(settings_store.RESOURCE_DB_KEY) or {}
    if bool(raw.get("enabled")) and str(raw.get("dsn") or "").strip():
        return str(raw["dsn"]).strip()
    raise SystemExit("缺少 DSN：传 --dsn 或设环境变量 SEHUA_RESOURCE_DSN")


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row)


def _vec_literal(vec: Iterable[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


def cmd_ensure_schema(conn: psycopg.Connection, *, recreate: bool = False) -> None:
    cfg = _embed_cfg()
    dim = int(cfg.get("dim") or 512)
    if dim < 64 or dim > 4096:
        raise SystemExit(f"非法维度: {dim}")
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        if recreate:
            cur.execute("DROP TABLE IF EXISTS sehua_resource_embed CASCADE")
            print(f"dropped sehua_resource_embed, recreating vector({dim})")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS sehua_resource_embed (
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
            """
            CREATE INDEX IF NOT EXISTS sehua_resource_embed_sha
              ON sehua_resource_embed (content_sha)
            """
        )
    conn.commit()
    print(f"schema ok: sehua_resource_embed vector({dim})")


def cmd_stats(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ext = cur.fetchone()
        cur.execute(
            """
            SELECT
              (SELECT count(*) FROM ed2k_resources) AS resources,
              (SELECT count(*) FROM sehua_resource_embed) AS embedded
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
        indexes = [r["indexname"] for r in cur.fetchall()]
    print(
        "vector_ext={ext} resources={res} embedded={emb} indexes={idx}".format(
            ext=(ext or {}).get("extversion") or "missing",
            res=row.get("resources"),
            emb=row.get("embedded"),
            idx=",".join(indexes) or "-",
        )
    )


def _embed_cfg() -> dict[str, Any]:
    from .db import init_db

    init_db()
    return resolve_embed_config(include_secret=True)


def _fetch_pending(
    conn: psycopg.Connection, *, limit: int, board_like: str
) -> list[dict[str, Any]]:
    like = (board_like or "").strip()
    any_board = not like
    pattern = like if like else "%"
    with conn.cursor() as cur:
        cur.execute(FETCH_SQL, [any_board, pattern, limit])
        return list(cur.fetchall())


def cmd_ingest(
    conn: psycopg.Connection,
    *,
    limit: int,
    all_rows: bool,
    batch_size: int,
    board_like: str,
) -> None:
    if all_rows:
        raise SystemExit("全库灌数已禁用：先把试点打通再开 --all")
    if limit <= 0 or limit > 500:
        raise SystemExit("试点 --limit 必须在 1–500；全库请等试点通过后再做")
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
        if any(len(v) != dim for v in vecs):
            raise SystemExit(f"向量维度不是 {dim}")
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


def cmd_create_index(conn: psycopg.Connection) -> None:
    print("creating HNSW (pilot 数据量很小，应该很快) …")
    with conn.cursor() as cur:
        cur.execute(HNSW_SQL)
    conn.commit()
    print("index ok: sehua_resource_embed_hnsw")


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
        src = str(row.get("source_text") or "").replace("\n", " | ")
        _safe_print(f"      {src[:180]}")


def cmd_preview(conn: psycopg.Connection, limit: int, board_like: str) -> None:
    rows = _fetch_pending(conn, limit=limit, board_like=board_like)
    print(f"preview {len(rows)} pending rows")
    for i, row in enumerate(rows, 1):
        p = row_embed_payload(row)
        text = p["source_text"].replace("\n", " | ")
        _safe_print(f"{i:2d}  {p['hash'][:12]}  {text[:200]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="色花资源向量试点")
    parser.add_argument("--dsn", default="", help="资源库 Postgres DSN")
    sub = parser.add_subparsers(dest="cmd", required=True)

    schema = sub.add_parser("ensure-schema", help="建扩展 + 表")
    schema.add_argument(
        "--recreate",
        action="store_true",
        help="删除旧表后按当前设置维度重建（会清掉已有向量）",
    )
    sub.add_parser("stats", help="条数 / 索引")
    preview = sub.add_parser("preview", help="只看拼出来的文本，不调模型")
    preview.add_argument("--limit", type=int, default=10)
    preview.add_argument("--board-like", default="", help="板块名 ILIKE，如 %%有码%%")

    ingest = sub.add_parser("ingest", help="小批量写入向量")
    ingest.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    ingest.add_argument("--batch-size", type=int, default=16)
    ingest.add_argument("--board-like", default="", help="板块名 ILIKE，如 %%有码%%")
    ingest.add_argument("--all", action="store_true", help="全库（试点阶段拒绝）")

    sub.add_parser("create-index", help="给当前表建 HNSW")
    search = sub.add_parser("search", help="自然语言试检索")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)

    _configure_stdio()
    args = parser.parse_args(argv)
    dsn = _resolve_dsn(args.dsn)
    with _connect(dsn) as conn:
        if args.cmd == "ensure-schema":
            cmd_ensure_schema(conn, recreate=bool(getattr(args, "recreate", False)))
        elif args.cmd == "stats":
            cmd_stats(conn)
        elif args.cmd == "preview":
            cmd_preview(conn, args.limit, str(args.board_like or ""))
        elif args.cmd == "ingest":
            cmd_ingest(
                conn,
                limit=int(args.limit),
                all_rows=bool(args.all),
                batch_size=max(1, int(args.batch_size)),
                board_like=str(args.board_like or ""),
            )
        elif args.cmd == "create-index":
            cmd_create_index(conn)
        elif args.cmd == "search":
            cmd_search(conn, args.query, int(args.limit))
        else:
            parser.error(args.cmd)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
