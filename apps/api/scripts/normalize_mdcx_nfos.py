# -*- coding: utf-8 -*-
"""把转入的 MDCx 风格 NFO 改写成程序标准格式（内容不删减）。

用法（在 apps/api 下）:
  python scripts/normalize_mdcx_nfos.py --region 日本有码 --dry-run
  python scripts/normalize_mdcx_nfos.py --region 日本有码
  python scripts/normalize_mdcx_nfos.py --path "E:/Project/sehua-next-web/media/scrap-library/日本有码/YSN"
  python scripts/normalize_mdcx_nfos.py --file ".../YSN-611.nfo" --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description="Normalize MDCx NFOs to program format")
    ap.add_argument("--region", default="", help="分区名，如 日本有码 / FC2")
    ap.add_argument("--path", default="", help="直接指定目录")
    ap.add_argument("--file", default="", help="单个 nfo 文件")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="已有 actor 也重排")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from app.scrap_library import embed as embed_svc
    from app.scrap_library.nfo import normalize_nfo_file, normalize_nfo_tree

    if args.file:
        r = normalize_nfo_file(
            Path(args.file), force=bool(args.force), dry_run=bool(args.dry_run)
        )
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("ok") else 1

    if args.path:
        base = Path(args.path)
    elif args.region:
        settings = embed_svc.get_settings()
        root = embed_svc.resolve_root(settings.get("root")).resolve()
        base = root / str(args.region).strip()
    else:
        print("需要 --region / --path / --file", file=sys.stderr)
        return 2

    if not base.is_dir():
        print(f"目录不存在: {base}", file=sys.stderr)
        return 2

    out = normalize_nfo_tree(
        base,
        force=bool(args.force),
        dry_run=bool(args.dry_run),
        limit=int(args.limit or 0),
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
