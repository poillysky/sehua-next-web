# -*- coding: utf-8 -*-
"""CLI：刮削库 NFO → 元库 (:5439) 向量。

  python -m app.scrap_library_embed_job ensure-schema
  python -m app.scrap_library_embed_job stats
  python -m app.scrap_library_embed_job preview --limit 5
  python -m app.scrap_library_embed_job ingest
  python -m app.scrap_library_embed_job search "美脚 派遣"
"""

from __future__ import annotations

import argparse
import sys

import app.scrap_library.embed as svc
from app.core.cli_io import configure_stdio as _configure_stdio
from app.core.cli_io import safe_print as _safe_print


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="刮削库向量灌入元库 (SNS_META_DSN)")
    parser.add_argument(
        "--root",
        default="",
        help="相对 media/ 或绝对路径，默认 scrap-library",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    schema = sub.add_parser("ensure-schema", help="在元库建 pgvector 表")
    schema.add_argument("--recreate", action="store_true")

    sub.add_parser("stats", help="条数 / 索引")

    preview = sub.add_parser("preview", help="只看拼出来的文本")
    preview.add_argument("--limit", type=int, default=5)

    ingest = sub.add_parser("ingest", help="扫描 NFO 写入元库向量")
    ingest.add_argument("--batch-size", type=int, default=16)
    ingest.add_argument("--limit", type=int, default=0, help="仅处理前 N 条（0=全部）")
    ingest.add_argument("--force", action="store_true", help="忽略 content_sha 强制重写")

    search = sub.add_parser("search", help="自然语言试检索")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=8)

    _configure_stdio()
    args = parser.parse_args(argv)

    if args.root:
        svc.put_settings(root=args.root)

    if args.cmd == "ensure-schema":
        info = svc.ensure_schema(recreate=bool(args.recreate))
        _safe_print(f"schema ok: {info}")
    elif args.cmd == "stats":
        st = svc.stats()
        _safe_print(
            "meta={meta} root={root} nfo={nfo} embedded={emb} indexes={idx}".format(
                meta=st.get("meta_db"),
                root=st.get("root"),
                nfo=st.get("nfo_files"),
                emb=st.get("embedded"),
                idx=",".join(st.get("indexes") or []) or "-",
            )
        )
    elif args.cmd == "preview":
        root = svc.resolve_root(svc.get_settings().get("root"))
        items = svc._scan_items(root)[: max(1, int(args.limit))]
        _safe_print(f"preview {len(items)} @ {root}")
        for i, it in enumerate(items, 1):
            text = it["source_text"].replace("\n", " | ")
            _safe_print(f"{i:2d}  {it['item_id']}  {text[:220]}")
    elif args.cmd == "ingest":
        lim = int(args.limit or 0)
        result = svc.ingest(
            batch_size=max(1, int(args.batch_size)),
            force=bool(args.force),
            limit=lim if lim > 0 else None,
        )
        _safe_print(
            "ingest done written={w} skipped={s} total={t} → {meta}".format(
                w=result.get("written"),
                s=result.get("skipped"),
                t=result.get("total"),
                meta=result.get("meta_db"),
            )
        )
    elif args.cmd == "search":
        hits = svc.search(args.query, limit=int(args.limit))
        if not hits:
            _safe_print("search: 无结果（先 ingest）")
            return
        _safe_print(f"search q={args.query!r} hits={len(hits)}")
        for i, h in enumerate(hits, 1):
            _safe_print(
                f"{i:2d}  {float(h['score']):.4f}  [{h.get('region')}] {h.get('code')} {h.get('title')}"
            )
    else:
        parser.error(args.cmd)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
