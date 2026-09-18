# -*- coding: utf-8 -*-
"""一步迁移：刮削库扁平 FC2/{CODE} → FC2/FC2|FC2PPV/{CODE}。

用法：
  python -m scripts.migrate_fc2_split_prefixes --dry-run
  python -m scripts.migrate_fc2_split_prefixes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.scrap_library.embed import get_settings, resolve_root  # noqa: E402
from scripts.sync_fc2_lib_to_scrap import split_flat_into_prefix_dirs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="拆分 FC2 扁平目录为 FC2 / FC2PPV 前缀夹")
    ap.add_argument("--dest-root", default="", help="刮削库根，默认 settings")
    ap.add_argument("--region-label", default="FC2")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if str(args.dest_root or "").strip():
        dest_root = Path(args.dest_root).expanduser().resolve()
    else:
        dest_root = resolve_root(get_settings().get("root")).resolve()
    region = str(args.region_label or "FC2").strip() or "FC2"
    dest = dest_root / region
    print(f"dest={dest} dry_run={bool(args.dry_run)}")
    if not dest.is_dir():
        print("region dir missing")
        return 2
    stats = split_flat_into_prefix_dirs(dest, dry_run=bool(args.dry_run))
    print(
        f"moved={stats['moved']:,} skipped={stats['skipped']:,} "
        f"conflicts={stats['conflicts']:,}"
    )
    # 摘要
    for pref in ("FC2", "FC2PPV"):
        p = dest / pref
        n = 0
        if p.is_dir():
            n = sum(1 for c in p.iterdir() if c.is_dir() and not c.name.startswith("_"))
        print(f"  {pref}/ → {n:,} codes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
