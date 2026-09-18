# -*- coding: utf-8 -*-
"""按目录骨架把 FC2/{CODE} 二次归位到 FC2/FC2 与 FC2/FC2PPV。

本地常见写法是 FC2-{id}，骨架 FC2PPV 为 FC2-PPV-{id}；按数字 id 对齐 catalog。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.core.region_meta import fc2_fs_prefix, normalize_fc2_code  # noqa: E402
from app.prefix import catalog_store as store  # noqa: E402
from app.scrap_library.embed import get_settings, resolve_root  # noqa: E402

_NUM_RE = re.compile(r"(\d+)\s*$")


def _id_key(code: str) -> str:
    """FC2-123 / FC2-PPV-0123 → 规范化数字 id（去前导零）。"""
    s = normalize_fc2_code(code)
    m = _NUM_RE.search(s)
    if not m:
        return ""
    return m.group(1).lstrip("0") or "0"


def _catalog_id_sets() -> tuple[set[str], set[str], dict[str, str], dict[str, str]]:
    doc = store.load_catalog(force=True)
    prefs = (doc.get("regions") or {}).get("fc2", {}).get("prefixes") or {}
    fc2_ids: set[str] = set()
    ppv_ids: set[str] = set()
    fc2_canon: dict[str, str] = {}
    ppv_canon: dict[str, str] = {}
    for code in store.codes_of(prefs.get("FC2") or {}):
        k = _id_key(code)
        if k:
            fc2_ids.add(k)
            fc2_canon[k] = normalize_fc2_code(code)
    for code in store.codes_of(prefs.get("FC2PPV") or {}):
        k = _id_key(code)
        if k:
            ppv_ids.add(k)
            ppv_canon[k] = normalize_fc2_code(code)
    return fc2_ids, ppv_ids, fc2_canon, ppv_canon


def _move(src: Path, dest: Path, *, dry_run: bool) -> str:
    if dest.resolve() == src.resolve():
        return "skip"
    if dest.exists():
        return "conflict"
    if dry_run:
        return "moved"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.rename(dest)
        return "moved"
    except OSError:
        try:
            shutil.move(str(src), str(dest))
            return "moved"
        except OSError:
            return "conflict"


def migrate(dest_region: Path, *, dry_run: bool) -> dict[str, int]:
    fc2_ids, ppv_ids, fc2_canon, ppv_canon = _catalog_id_sets()
    stats = {
        "to_fc2": 0,
        "to_ppv": 0,
        "unknown": 0,
        "conflict": 0,
        "skip": 0,
        "both": 0,
    }
    # 收集待处理：扁平残留 + 已在 FC2/ 下的番号夹
    candidates: list[Path] = []
    for child in dest_region.iterdir():
        if not child.is_dir() or child.name.startswith("_"):
            continue
        name_u = child.name.strip().upper().replace("_", "-")
        # 前缀夹（FC2 / FC2-PPV / 旧名 FC2PPV）
        if name_u in {"FC2", "FC2PPV", "FC2-PPV"}:
            for code_dir in child.iterdir():
                if (
                    code_dir.is_dir()
                    and not code_dir.name.startswith("_")
                    and any(ch.isdigit() for ch in code_dir.name)
                    and code_dir.name.upper().startswith("FC2")
                ):
                    candidates.append(code_dir)
            continue
        if any(ch.isdigit() for ch in child.name) and child.name.upper().startswith(
            "FC2"
        ):
            candidates.append(child)

    for src in candidates:
        code_now = normalize_fc2_code(src.name)
        kid = _id_key(code_now)
        in_fc2 = kid in fc2_ids
        in_ppv = kid in ppv_ids
        if in_fc2 and in_ppv:
            # 骨架两边都有：优先 PPV（体量大的那侧）
            target_pref = "FC2-PPV"
            target_code = ppv_canon.get(kid) or f"FC2-PPV-{kid}"
            stats["both"] += 1
        elif in_ppv:
            target_pref = "FC2-PPV"
            target_code = ppv_canon.get(kid) or f"FC2-PPV-{kid}"
        elif in_fc2:
            target_pref = "FC2"
            target_code = fc2_canon.get(kid) or (
                code_now if code_now.startswith("FC2-") and "PPV" not in code_now else f"FC2-{kid}"
            )
        else:
            # 不在骨架：默认留在 FC2/，番号保持 FC2-XXX
            target_pref = "FC2"
            if "PPV" in code_now:
                # 本地已是 PPV 写法但不在骨架 → 仍进 FC2-PPV
                target_pref = "FC2-PPV"
                target_code = code_now if code_now.startswith("FC2-PPV") else f"FC2-PPV-{kid}"
            else:
                target_code = code_now if code_now.startswith("FC2-") else f"FC2-{kid}"
            stats["unknown"] += 1

        # 保证番号形态与文件夹一致
        if target_pref == "FC2-PPV" and not target_code.startswith("FC2-PPV"):
            target_code = f"FC2-PPV-{kid}"
        if target_pref == "FC2" and target_code.startswith("FC2-PPV"):
            target_code = f"FC2-{kid}"

        dest = dest_region / target_pref / target_code
        same_pref = src.parent.name.upper().replace("_", "-") in {
            target_pref,
            "FC2PPV" if target_pref == "FC2-PPV" else "FC2",
        }
        if same_pref and src.name == target_code:
            stats["skip"] += 1
            continue
        result = _move(src, dest, dry_run=dry_run)
        if result == "moved":
            if target_pref == "FC2-PPV":
                stats["to_ppv"] += 1
            else:
                stats["to_fc2"] += 1
        elif result == "conflict":
            stats["conflict"] += 1
        else:
            stats["skip"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest-root", default="")
    ap.add_argument("--region-label", default="FC2")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if str(args.dest_root or "").strip():
        root = Path(args.dest_root).expanduser().resolve()
    else:
        root = resolve_root(get_settings().get("root")).resolve()
    dest = root / (str(args.region_label or "FC2").strip() or "FC2")
    print(f"dest={dest} dry_run={bool(args.dry_run)}")
    stats = migrate(dest, dry_run=bool(args.dry_run))
    print(stats)
    for pref in ("FC2", "FC2-PPV", "FC2PPV"):
        p = dest / pref
        n = (
            sum(1 for c in p.iterdir() if c.is_dir() and not c.name.startswith("_"))
            if p.is_dir()
            else 0
        )
        print(f"  {pref}/ → {n:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
