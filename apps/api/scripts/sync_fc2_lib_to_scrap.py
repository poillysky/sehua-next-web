# -*- coding: utf-8 -*-
"""把外部 FC2 库同步到刮削库（去掉制作商层，按番号一层显示）。

源（常见 MDCx：制作商/番号）：
  E:/Project/FC2/{maker}/{FC2-xxxxx}/{FC2-xxxxx}.nfo + poster.jpg

目标（本项目 scrap-library，扁平）：
  media/scrap-library/FC2/{FC2-xxxxx}/{FC2-xxxxx}.nfo
  media/scrap-library/FC2/{FC2-xxxxx}/poster.jpg

扫描器对 FC2 识别为两层 region/code（prefix 记为 FC2）。

默认只补缺失，不覆盖已有非空文件；不复制 strm/视频。
同一番号多制作商时优先保留有 NFO+封面的目录。

用法：
  python -m scripts.sync_fc2_lib_to_scrap --dry-run
  python -m scripts.sync_fc2_lib_to_scrap
  python -m scripts.sync_fc2_lib_to_scrap --flatten-only
  python -m scripts.sync_fc2_lib_to_scrap --overwrite --limit 100
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_API_ROOT = Path(__file__).resolve().parents[1]
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.scrap_library.embed import get_settings, resolve_root  # noqa: E402

_POSTER_CANDIDATES = (
    "poster.jpg",
    "poster.jpeg",
    "poster.png",
    "poster.webp",
    "thumb.jpg",
    "thumb.jpeg",
    "fanart.jpg",
    "cover.jpg",
)


@dataclass
class SyncStats:
    seen: int = 0
    copied_nfo: int = 0
    copied_poster: int = 0
    skipped: int = 0
    missing_src: int = 0
    errors: int = 0
    samples: list[str] = field(default_factory=list)


def _is_nonempty(path: Path, *, min_bytes: int = 32) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= min_bytes
    except OSError:
        return False


def _pick_src_nfo(code_dir: Path, code: str) -> Path | None:
    preferred = [
        code_dir / f"{code}.nfo",
        code_dir / f"{code.upper()}.nfo",
        code_dir / "movie.nfo",
    ]
    for p in preferred:
        if _is_nonempty(p, min_bytes=16):
            return p
    for p in sorted(code_dir.glob("*.nfo")):
        if _is_nonempty(p, min_bytes=16):
            return p
    return None


def _pick_src_poster(code_dir: Path) -> Path | None:
    for name in _POSTER_CANDIDATES:
        p = code_dir / name
        if _is_nonempty(p, min_bytes=256):
            return p
    return None


def _dir_score(code_dir: Path, code: str) -> tuple[int, int, int]:
    """有 NFO / 有封面 / 文件总大小 —— 用于同一番号多目录择优。"""
    nfo = 1 if _pick_src_nfo(code_dir, code) else 0
    poster = 1 if _pick_src_poster(code_dir) else 0
    size = 0
    try:
        for f in code_dir.iterdir():
            if f.is_file():
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return (nfo, poster, size)


def _ensure_num_in_nfo(raw: bytes, code: str) -> bytes:
    code_u = str(code or "").strip().upper()
    if not code_u or not raw:
        return raw
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return raw
    if root.tag.lower() != "movie":
        return raw
    num_el = root.find("num")
    cur = "".join(num_el.itertext()).strip().upper() if num_el is not None else ""
    if cur == code_u:
        return raw
    if num_el is None:
        num_el = ET.Element("num")
        root.insert(0, num_el)
    num_el.clear()
    num_el.text = code_u
    try:
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    except Exception:  # noqa: BLE001
        return raw


def _copy_file(src: Path, dest: Path, *, dry_run: bool) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return True
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        shutil.copy2(src, tmp)
        tmp.replace(dest)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _write_bytes(dest: Path, data: bytes, *, dry_run: bool) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        return True
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        tmp.write_bytes(data)
        tmp.replace(dest)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def sync_one(
    *,
    src_code_dir: Path,
    dest_code_dir: Path,
    code: str,
    overwrite: bool,
    dry_run: bool,
) -> dict[str, Any]:
    out = {
        "code": code,
        "nfo": False,
        "poster": False,
        "skip": False,
        "missing": False,
        "error": "",
    }
    src_nfo = _pick_src_nfo(src_code_dir, code)
    src_poster = _pick_src_poster(src_code_dir)
    if not src_nfo and not src_poster:
        out["missing"] = True
        return out

    dest_nfo = dest_code_dir / f"{code}.nfo"
    dest_poster = dest_code_dir / "poster.jpg"

    need_nfo = bool(src_nfo) and (overwrite or not _is_nonempty(dest_nfo, min_bytes=16))
    need_poster = bool(src_poster) and (
        overwrite or not _is_nonempty(dest_poster, min_bytes=256)
    )
    if not need_nfo and not need_poster:
        out["skip"] = True
        return out

    try:
        if need_nfo and src_nfo is not None:
            raw = src_nfo.read_bytes()
            raw = _ensure_num_in_nfo(raw, code)
            _write_bytes(dest_nfo, raw, dry_run=dry_run)
            out["nfo"] = True
        if need_poster and src_poster is not None:
            _copy_file(src_poster, dest_poster, dry_run=dry_run)
            out["poster"] = True
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    return out


def _normalize_code(name: str) -> str:
    s = str(name or "").strip().upper().replace("_", "-")
    if s.startswith("FC2PPV-"):
        s = "FC2-PPV-" + s[7:]
    elif s.startswith("FC2-PPV"):
        pass
    elif s.startswith("FC2PPV"):
        rest = s[6:].lstrip("-")
        s = f"FC2-PPV-{rest}" if rest else s
    return s


def _is_fc2_code_dir(name: str) -> bool:
    u = str(name or "").strip().upper()
    return u.startswith("FC2") and any(ch.isdigit() for ch in u)


def iter_code_dirs(src_root: Path):
    """扁平化：忽略制作商层，按番号去重择优。"""
    best: dict[str, Path] = {}
    for maker in src_root.iterdir():
        if not maker.is_dir() or maker.name.startswith("."):
            continue
        try:
            children = list(maker.iterdir())
        except OSError:
            continue
        for code_dir in children:
            if not code_dir.is_dir() or code_dir.name.startswith("."):
                continue
            if not _is_fc2_code_dir(code_dir.name):
                continue
            code = _normalize_code(code_dir.name)
            if not code:
                continue
            prev = best.get(code)
            if prev is None or _dir_score(code_dir, code) > _dir_score(prev, code):
                best[code] = code_dir
    for code in sorted(best.keys()):
        yield code, best[code]


def flatten_legacy_prefix_layer(dest_region: Path, *, dry_run: bool) -> int:
    """把旧布局 FC2/FC2/{CODE} 上移为 FC2/{CODE}。"""
    nested = dest_region / "FC2"
    if not nested.is_dir():
        return 0
    try:
        kids = [p for p in nested.iterdir() if p.is_dir()]
    except OSError:
        return 0
    if not kids:
        return 0
    code_like = sum(1 for p in kids if _is_fc2_code_dir(p.name))
    if code_like < max(1, len(kids) // 2):
        return 0
    moved = 0
    for src in kids:
        dest = dest_region / src.name
        if dest.exists():
            if not dry_run:
                for f in src.iterdir():
                    if not f.is_file():
                        continue
                    t = dest / f.name
                    if not t.exists():
                        try:
                            shutil.move(str(f), str(t))
                        except OSError:
                            pass
                shutil.rmtree(src, ignore_errors=True)
            moved += 1
            continue
        if dry_run:
            moved += 1
            continue
        try:
            src.rename(dest)
            moved += 1
        except OSError:
            try:
                shutil.move(str(src), str(dest))
                moved += 1
            except OSError:
                pass
    if not dry_run:
        try:
            if nested.is_dir() and not any(nested.iterdir()):
                nested.rmdir()
        except OSError:
            pass
    return moved


def main() -> int:
    ap = argparse.ArgumentParser(description="同步外部 FC2 NFO/封面到刮削库（无制作商层）")
    ap.add_argument("--src", default=r"E:\Project\FC2", help="外部库根（maker/CODE）")
    ap.add_argument("--dest-root", default="", help="刮削库根，默认 settings scrap-library")
    ap.add_argument("--region-label", default="FC2", help="目标分区目录名")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已有 NFO/封面")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写盘")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 个番号（0=全部）")
    ap.add_argument("--workers", type=int, default=8, help="并行复制线程")
    ap.add_argument(
        "--flatten-only",
        action="store_true",
        help="只把旧 FC2/FC2/{CODE} 上移为 FC2/{CODE}",
    )
    args = ap.parse_args()

    src_root = Path(args.src).expanduser().resolve()
    if not args.flatten_only and not src_root.is_dir():
        print(f"源目录不存在: {src_root}")
        return 2

    if str(args.dest_root or "").strip():
        dest_root = Path(args.dest_root).expanduser().resolve()
    else:
        dest_root = resolve_root(get_settings().get("root")).resolve()
    region = str(args.region_label or "FC2").strip() or "FC2"
    dest_region = dest_root / region

    print(f"src      = {src_root}")
    print(f"dest     = {dest_region}")
    print(f"layout   = {region}/{{CODE}}  (flat, no maker/prefix)")
    print(f"overwrite= {bool(args.overwrite)} dry_run={bool(args.dry_run)}")

    moved = flatten_legacy_prefix_layer(dest_region, dry_run=bool(args.dry_run))
    print(f"flatten  = {moved:,} (FC2/FC2/CODE → FC2/CODE)")
    if args.flatten_only:
        return 0

    print(f"workers  = {max(1, int(args.workers or 8))}")

    jobs: list[tuple[str, Path, Path]] = []
    lim = max(0, int(args.limit or 0))
    for code, code_dir in iter_code_dirs(src_root):
        dest = dest_region / code
        jobs.append((code, code_dir, dest))
        if lim and len(jobs) >= lim:
            break

    print(f"queued   = {len(jobs):,}")
    if not jobs:
        return 0

    stats = SyncStats()
    t0 = time.perf_counter()
    workers = max(1, min(32, int(args.workers or 8)))

    def _run(job: tuple[str, Path, Path]) -> dict[str, Any]:
        code, src_dir, dest_dir = job
        one = sync_one(
            src_code_dir=src_dir,
            dest_code_dir=dest_dir,
            code=code,
            overwrite=bool(args.overwrite),
            dry_run=bool(args.dry_run),
        )
        one["rel"] = f"{region}/{code}"
        return one

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(_run, j) for j in jobs]
        for fut in as_completed(futs):
            done += 1
            try:
                one = fut.result()
            except Exception as e:  # noqa: BLE001
                stats.errors += 1
                if len(stats.samples) < 8:
                    stats.samples.append(f"ERR {e}")
                continue
            stats.seen += 1
            if one.get("error"):
                stats.errors += 1
                if len(stats.samples) < 8:
                    stats.samples.append(f"{one.get('rel')}: {one.get('error')}")
            elif one.get("missing"):
                stats.missing_src += 1
            elif one.get("skip"):
                stats.skipped += 1
            else:
                if one.get("nfo"):
                    stats.copied_nfo += 1
                if one.get("poster"):
                    stats.copied_poster += 1
                if len(stats.samples) < 8 and (one.get("nfo") or one.get("poster")):
                    bits = []
                    if one.get("nfo"):
                        bits.append("nfo")
                    if one.get("poster"):
                        bits.append("poster")
                    stats.samples.append(f"{one.get('rel')} +{'+'.join(bits)}")
            if done % 1000 == 0 or done == len(jobs):
                elapsed = max(0.001, time.perf_counter() - t0)
                rate = done / elapsed
                print(
                    f"… {done:,}/{len(jobs):,} "
                    f"nfo+{stats.copied_nfo:,} poster+{stats.copied_poster:,} "
                    f"skip={stats.skipped:,} miss={stats.missing_src:,} "
                    f"err={stats.errors:,} {rate:.0f}/s",
                    flush=True,
                )

    elapsed = time.perf_counter() - t0
    print("---")
    print(
        f"done seen={stats.seen:,} nfo={stats.copied_nfo:,} "
        f"poster={stats.copied_poster:,} skip={stats.skipped:,} "
        f"missing={stats.missing_src:,} errors={stats.errors:,} "
        f"elapsed={elapsed:.1f}s"
    )
    for s in stats.samples:
        print(f"  · {s}")
    return 0 if stats.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
