# -*- coding: utf-8 -*-
"""embed_catalog —— 自 scrap_library/embed.py 拆出（机械搬移，行为不变）。"""

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
import app.core.settings_store as settings_store
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import data_dir, media_dir, get_meta_pool, init_db, meta_dsn_label
from app.scrap_library.nfo import (
    build_nfo_embed_text,
    content_sha,
    item_id_from_rel,
    normalize_source_text_for_diff,
    parse_nfo,
    polish_source_text_actresses,
    preserve_actress_line,
)
from app.core.ttl_cache import enforce_max, prune_by_age

import app.scrap_library.embed as _embed
import app.scrap_library.embed_poster as _embed_poster
from app.scrap_library.embed import (DEFAULT_REL_ROOT, _SHELL_GAPS, _embed_code_set, _skeleton_content_sha, _skeleton_source_text, _vec_literal, _zero_vec_literal, catalog_code_set, ensure_hnsw, log)
from app.scrap_library.embed_runtime import (_FACETS_CACHE, _ITEMS_HUB_CACHE, _RECOMMEND_CACHE, _persist_embed_job, _push_log, _set_progress)


ProgressCb = Callable[[dict[str, Any]], None]


SKELETON_SHA_PREFIX = "skeleton:v1"


def is_skeleton_sha(sha: str | None) -> bool:
    return str(sha or "").startswith(SKELETON_SHA_PREFIX)


def _canon_embed_code(code: str) -> str:
    """向量/目录比对用番号键：FC2-PPV-* 与 FC2-* 同一键。"""
    from app.core.region_meta import normalize_fc2_code

    cu = str(code or "").strip().upper().replace("_", "-")
    if not cu:
        return ""
    if "FC2" in cu:
        return normalize_fc2_code(cu)
    return cu


def _catalog_code_locations() -> dict[str, tuple[str, str]]:
    """番号 → (区中文名, 前缀)。同号多路径按 REGION_ORDER 先出现的为准。"""
    import app.prefix.catalog_store as store
    from app.core.region_meta import REGION_META, REGION_ORDER, std_prefix

    doc = store.load_catalog(force=True)
    out: dict[str, tuple[str, str]] = {}
    for rid in REGION_ORDER:
        reg = (doc.get("regions") or {}).get(rid) or {}
        label = str(reg.get("label") or REGION_META.get(rid, {}).get("label") or rid)
        for pref, ent in (reg.get("prefixes") or {}).items():
            p = std_prefix(str(pref or ""))
            if not p:
                continue
            for code in store.codes_of(ent):
                cu = _canon_embed_code(code)
                if cu and cu not in out:
                    out[cu] = (label, p)
    return out


def _catalog_prefix_labels() -> dict[str, str]:
    """前缀 → 唯一区中文名。跨区同名前缀（如 MKY）不自动搬磁盘。"""
    import app.prefix.catalog_store as store
    from app.core.region_meta import REGION_META, REGION_ORDER
    from collections import defaultdict

    doc = store.load_catalog(force=True)
    buckets: dict[str, set[str]] = defaultdict(set)
    for rid in REGION_ORDER:
        reg = (doc.get("regions") or {}).get(rid) or {}
        label = str(reg.get("label") or REGION_META.get(rid, {}).get("label") or rid)
        for pref in (reg.get("prefixes") or {}):
            p = str(pref or "").strip().upper()
            if p:
                buckets[p].add(label)
    return {p: next(iter(labels)) for p, labels in buckets.items() if len(labels) == 1}


def relocate_disk_prefix_dirs(*, on_progress: ProgressCb | None = None) -> dict[str, int]:
    """把刮削库磁盘上的前缀目录搬到目录所属分区，并改写向量行路径。

    item_id 等于相对路径，搬完必须一起改，否则封面和 NFO 对不上。
    """
    import shutil

    from app.core.db import media_dir

    def prog(label: str, **kw: Any) -> None:
        if on_progress:
            on_progress({"stage": "skeleton", "label": label, **kw})

    root = (media_dir() / DEFAULT_REL_ROOT).resolve()
    if not root.is_dir():
        return {"dirs": 0, "folders": 0, "rows": 0}

    labels = _catalog_prefix_labels()
    plans: list[tuple[Path, Path, str, str, str]] = []
    for region_dir in root.iterdir():
        if not region_dir.is_dir() or region_dir.name.startswith("_"):
            continue
        for pref_dir in region_dir.iterdir():
            if not pref_dir.is_dir():
                continue
            pref = pref_dir.name.strip().upper()
            want = labels.get(pref)
            if not want or want == region_dir.name:
                continue
            plans.append((pref_dir, root / want / pref, region_dir.name, want, pref))

    moved_dirs = moved_folders = updated_rows = 0
    pool = get_meta_pool()
    for src, dst, old_label, new_label, pref in plans:
        dst.parent.mkdir(parents=True, exist_ok=True)
        folder_n = 0
        if not dst.exists():
            src.rename(dst)
            folder_n = sum(1 for p in dst.iterdir() if p.is_dir())
        else:
            for child in list(src.iterdir()):
                target = dst / child.name
                if target.exists():
                    continue
                shutil.move(str(child), str(target))
                if child.is_dir() or target.is_dir():
                    folder_n += 1
            try:
                if not any(src.iterdir()):
                    src.rmdir()
            except OSError:
                pass
        old_seg = f"{old_label}/{pref}/"
        new_seg = f"{new_label}/{pref}/"
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {_embed.TABLE}
                   SET item_id = replace(item_id, %s, %s),
                       rel_path = replace(rel_path, %s, %s),
                       poster_path = replace(poster_path, %s, %s),
                       thumb_path = replace(thumb_path, %s, %s),
                       fanart_path = replace(fanart_path, %s, %s),
                       region = %s,
                       prefix = %s,
                       updated_at = now()
                 WHERE item_id LIKE %s
                    OR rel_path LIKE %s
                    OR poster_path LIKE %s
                """,
                (
                    old_seg,
                    new_seg,
                    old_seg,
                    new_seg,
                    old_seg,
                    new_seg,
                    old_seg,
                    new_seg,
                    old_seg,
                    new_seg,
                    new_label,
                    pref,
                    old_seg + "%",
                    "%" + old_seg + "%",
                    "%" + old_seg + "%",
                ),
            )
            updated_rows += int(cur.rowcount or 0)
            conn.commit()
        moved_dirs += 1
        moved_folders += folder_n
        prog(f"磁盘分区 · {pref} {old_label} → {new_label}")

    if moved_dirs:
        try:
            _FACETS_CACHE.clear()
            _ITEMS_HUB_CACHE.clear()
            _RECOMMEND_CACHE.clear()
        except Exception:  # noqa: BLE001
            pass
    return {"dirs": moved_dirs, "folders": moved_folders, "rows": updated_rows}


def _fc2_target_paths(
    *,
    item_id: str = "",
    code: str = "",
    rel_path: str = "",
) -> tuple[str, str, str] | None:
    """旧 FC2 路径/番号 → (new_code, new_item_id, new_rel)。非 FC2 或不需改写返回 None。"""
    from app.core.region_meta import normalize_fc2_code

    iid = str(item_id or "").strip().replace("\\", "/")
    code_u = str(code or "").strip().upper()
    rel = str(rel_path or iid).strip().replace("\\", "/")
    blob = f"{iid}|{code_u}|{rel}".upper()
    looks_fc2 = "FC2" in blob
    if not looks_fc2:
        return None
    # 旧写法：夹名 / 番号含 PPV，或扁平 FC2/{CODE}（缺中间前缀夹）
    parts = [p for p in iid.split("/") if p]
    legacy = bool(
        re.search(r"FC2-?PPV", blob)
        or (len(parts) == 2 and parts[0].upper() == "FC2" and parts[1].upper().startswith("FC2"))
        or (len(parts) >= 3 and parts[1].upper().replace("_", "-") in {"FC2-PPV", "FC2PPV"})
        or code_u.startswith("FC2-PPV")
        or re.fullmatch(r"FC2PPV\d+", re.sub(r"[\s\-]", "", code_u) or "")
    )
    if not legacy and len(parts) >= 3:
        # 已是 FC2/FC2/FC2-{num} 但 code 仍旧
        pref = parts[1].upper().replace("_", "-")
        code_part = parts[2].upper()
        if pref == "FC2" and code_part.startswith("FC2") and "PPV" not in code_part:
            canon = normalize_fc2_code(code_u or code_part)
            if canon and canon != code_u:
                return canon, f"FC2/FC2/{canon}", f"FC2/FC2/{canon}"
            return None
    if not legacy:
        return None
    seed = code_u
    if not seed or "FC2" not in seed:
        seed = parts[-1] if parts else ""
    canon = normalize_fc2_code(seed)
    if not canon or not canon.startswith("FC2-"):
        return None
    new_id = f"FC2/FC2/{canon}"
    if iid == new_id and code_u == canon and (not rel or rel == new_id):
        return None
    return canon, new_id, new_id


def _merge_fc2_disk_dirs(src: Path, dst: Path) -> bool:
    """把旧番号目录合并进新路径；有冲突时保留较大文件。返回是否搬走了内容。"""
    import shutil

    if not src.is_dir():
        return False
    dst.mkdir(parents=True, exist_ok=True)
    moved_any = False
    for child in list(src.iterdir()):
        target = dst / child.name
        if not target.exists():
            shutil.move(str(child), str(target))
            moved_any = True
            continue
        if child.is_file() and target.is_file():
            try:
                if child.stat().st_size > target.stat().st_size:
                    target.unlink(missing_ok=True)
                    shutil.move(str(child), str(target))
                    moved_any = True
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass
        elif child.is_dir():
            _merge_fc2_disk_dirs(child, target)
            try:
                if not any(child.iterdir()):
                    child.rmdir()
            except OSError:
                pass
    try:
        if src.is_dir() and not any(src.iterdir()):
            src.rmdir()
            moved_any = True
    except OSError:
        pass
    return moved_any


def migrate_fc2_legacy_paths(*, on_progress: ProgressCb | None = None) -> dict[str, int]:
    """全量归并旧 FC2-PPV / FC2PPV → ``FC2/FC2/FC2-{num}``（纯 SQL，秒级）。

    - 向量：先删与新路径冲突的旧行，再 replace 改写路径/番号/前缀
    - 队列：同步 item_id / code
    - 磁盘：仅当旧前缀夹仍存在时合并（通常盘上已是新路径）
    """
    from app.core.db import connect as connect_app

    def prog(label: str, **kw: Any) -> None:
        if on_progress:
            on_progress({"stage": "skeleton", "label": label, **kw})

    prog("FC2 旧路径归并…", percent=1)
    root = (media_dir() / _embed.DEFAULT_REL_ROOT).resolve()
    pool = get_meta_pool()
    dropped = updated = queue_n = disk_moved = 0

    with pool.connection() as conn, conn.cursor() as cur:
        try:
            cur.execute("SET LOCAL statement_timeout = 0")
        except Exception:  # noqa: BLE001
            pass

        # 1) 旧路径且新路径已存在 → 删旧（保留新）
        cur.execute(
            f"""
            DELETE FROM {_embed.TABLE} AS old
             WHERE (old.item_id LIKE 'FC2/FC2-PPV/%%'
                 OR old.item_id LIKE 'FC2/FC2PPV/%%')
               AND EXISTS (
                    SELECT 1 FROM {_embed.TABLE} AS neu
                     WHERE neu.item_id = (
                        'FC2/FC2/FC2-' || COALESCE(
                            NULLIF(substring(UPPER(old.code)
                                from 'FC2(?:-?PPV)?-?([0-9]+)'), ''),
                            NULLIF(substring(UPPER(old.item_id)
                                from 'FC2(?:-?PPV)?-?([0-9]+)'), '')
                        )
                     )
                       AND neu.item_id <> old.item_id
               )
            """
        )
        dropped += int(cur.rowcount or 0)
        prog(f"FC2 去重冲突 · {dropped:,}", percent=2)

        # 2) 剩余旧路径一次性改写（路径前缀 + 番号名）
        cur.execute(
            f"""
            UPDATE {_embed.TABLE}
               SET item_id = regexp_replace(
                        regexp_replace(item_id, 'FC2/(FC2-PPV|FC2PPV)/', 'FC2/FC2/', 'i'),
                        'FC2-PPV-', 'FC2-', 'i'
                    ),
                   rel_path = regexp_replace(
                        regexp_replace(
                            COALESCE(NULLIF(rel_path,''), item_id),
                            'FC2/(FC2-PPV|FC2PPV)/', 'FC2/FC2/', 'i'
                        ),
                        'FC2-PPV-', 'FC2-', 'i'
                    ),
                   poster_path = regexp_replace(
                        regexp_replace(COALESCE(poster_path,''),
                            'FC2/(FC2-PPV|FC2PPV)/', 'FC2/FC2/', 'i'),
                        'FC2-PPV-', 'FC2-', 'i'
                    ),
                   thumb_path = regexp_replace(
                        regexp_replace(COALESCE(thumb_path,''),
                            'FC2/(FC2-PPV|FC2PPV)/', 'FC2/FC2/', 'i'),
                        'FC2-PPV-', 'FC2-', 'i'
                    ),
                   fanart_path = regexp_replace(
                        regexp_replace(COALESCE(fanart_path,''),
                            'FC2/(FC2-PPV|FC2PPV)/', 'FC2/FC2/', 'i'),
                        'FC2-PPV-', 'FC2-', 'i'
                    ),
                   code = CASE
                        WHEN code ~* 'FC2' THEN
                            'FC2-' || COALESCE(
                                NULLIF(substring(UPPER(code) from 'FC2(?:-?PPV)?-?([0-9]+)'), ''),
                                substring(UPPER(code) from '([0-9]+)')
                            )
                        ELSE code
                   END,
                   prefix = 'FC2',
                   region = 'FC2',
                   updated_at = now()
             WHERE item_id LIKE 'FC2/FC2-PPV/%%'
                OR item_id LIKE 'FC2/FC2PPV/%%'
            """
        )
        updated += int(cur.rowcount or 0)
        prog(f"FC2 路径改写 · {updated:,}", percent=3)

        # 3) 路径已新但 code/prefix 仍旧
        cur.execute(
            f"""
            UPDATE {_embed.TABLE}
               SET code = 'FC2-' || COALESCE(
                        NULLIF(substring(UPPER(code) from 'FC2(?:-?PPV)?-?([0-9]+)'), ''),
                        NULLIF(substring(UPPER(item_id) from 'FC2-([0-9]+)'), ''),
                        ''
                    ),
                   prefix = 'FC2',
                   updated_at = now()
             WHERE item_id LIKE 'FC2/FC2/FC2-%%'
               AND (
                    code LIKE 'FC2-PPV-%%'
                    OR UPPER(TRIM(COALESCE(prefix,''))) IN ('FC2-PPV', 'FC2PPV')
               )
               AND COALESCE(
                    NULLIF(substring(UPPER(code) from 'FC2(?:-?PPV)?-?([0-9]+)'), ''),
                    NULLIF(substring(UPPER(item_id) from 'FC2-([0-9]+)'), ''),
                    ''
               ) <> ''
            """
        )
        updated += int(cur.rowcount or 0)
        conn.commit()

    # 4) 队列表（通常很少）
    try:
        with connect_app() as conn:
            cur = conn.execute(
                """
                UPDATE enrich_queue_log
                   SET item_id = regexp_replace(
                            regexp_replace(item_id, 'FC2/(FC2-PPV|FC2PPV)/', 'FC2/FC2/', 'i'),
                            'FC2-PPV-', 'FC2-', 'i'
                        ),
                       code = CASE
                            WHEN code ~* 'FC2' THEN
                                'FC2-' || COALESCE(
                                    NULLIF(substring(UPPER(code) from 'FC2(?:-?PPV)?-?([0-9]+)'), ''),
                                    substring(UPPER(code) from '([0-9]+)')
                                )
                            ELSE code
                       END,
                       updated_at = NOW()
                 WHERE region = 'fc2'
                   AND (
                        item_id LIKE '%%FC2-PPV%%'
                        OR item_id LIKE '%%FC2PPV%%'
                        OR code LIKE 'FC2-PPV%%'
                        OR code LIKE 'FC2PPV%%'
                   )
                """
            )
            queue_n = int(getattr(cur, "rowcount", 0) or 0)
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("migrate fc2 queue paths failed: %s", e)

    # 5) 磁盘：旧前缀夹若还在，整夹合并进 FC2/FC2
    for old_name in ("FC2-PPV", "FC2PPV"):
        src = root / "FC2" / old_name
        dst = root / "FC2" / "FC2"
        if src.is_dir():
            # 旧夹下番号目录名也可能是 FC2-PPV-xxx
            for child in list(src.iterdir()):
                if not child.is_dir():
                    continue
                from app.core.region_meta import normalize_fc2_code

                new_name = normalize_fc2_code(child.name)
                target = dst / new_name
                if _merge_fc2_disk_dirs(child, target):
                    disk_moved += 1
            try:
                if src.is_dir() and not any(src.iterdir()):
                    src.rmdir()
            except OSError:
                pass

    if updated or dropped or disk_moved:
        try:
            _FACETS_CACHE.clear()
            _ITEMS_HUB_CACHE.clear()
            _RECOMMEND_CACHE.clear()
        except Exception:  # noqa: BLE001
            pass

    prog(
        f"FC2 旧路径归并 · 改写 {updated:,} · 去重 {dropped:,} · 磁盘 {disk_moved:,} · 队列 {queue_n:,}",
        percent=3,
    )
    return {
        "updated": updated,
        "dropped": dropped,
        "disk_moved": disk_moved,
        "queue": queue_n,
    }


def realign_embed_locations(*, on_progress: ProgressCb | None = None) -> dict[str, int]:
    """把已有向量行的 region/prefix 对齐到当前目录，并把刮削库磁盘前缀目录搬过去。

    已刮削行保留正文。路径（item_id / rel_path）随磁盘目录一起改。
    """
    def prog(label: str, **kw: Any) -> None:
        if on_progress:
            on_progress({"stage": "skeleton", "label": label, **kw})

    # 先收口 FC2-PPV → FC2/FC2/FC2-*，再做分区对齐
    try:
        fc2_mig = migrate_fc2_legacy_paths(on_progress=on_progress)
    except Exception as e:  # noqa: BLE001
        log.warning("migrate_fc2_legacy_paths failed: %s", e)
        fc2_mig = {"updated": 0, "dropped": 0, "disk_moved": 0, "queue": 0}

    locations = _catalog_code_locations()
    prog("对齐已有番号的分区…", percent=3)
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT item_id, region, prefix, code, content_sha FROM {_embed.TABLE}"
        )
        raw_rows = cur.fetchall() or []

    by_code: dict[str, list[dict[str, str]]] = {}
    for row in raw_rows:
        if isinstance(row, dict):
            item = {
                "item_id": str(row.get("item_id") or "").strip(),
                "region": str(row.get("region") or "").strip(),
                "prefix": str(row.get("prefix") or "").strip().upper(),
                "code": str(row.get("code") or "").strip().upper(),
                "sha": str(row.get("content_sha") or ""),
            }
        else:
            item = {
                "item_id": str(row[0] or "").strip(),
                "region": str(row[1] or "").strip(),
                "prefix": str(row[2] or "").strip().upper(),
                "code": str(row[3] or "").strip().upper(),
                "sha": str(row[4] or ""),
            }
        if not item["item_id"] or not item["code"]:
            continue
        canon = _canon_embed_code(item["code"])
        if not canon:
            continue
        item["canon"] = canon
        by_code.setdefault(canon, []).append(item)

    updates: list[tuple[str, str, str, str]] = []  # region, prefix, code, item_id
    drop_ids: list[str] = []
    for canon, items in by_code.items():
        target = locations.get(canon)
        if not target:
            # 不在最新目录 → 交给 prune 删；这里不去碰
            continue
        label, pref = target
        scraped = [x for x in items if not is_skeleton_sha(x["sha"])]
        keeper = scraped[0] if scraped else items[0]
        for extra in items:
            if extra["item_id"] != keeper["item_id"]:
                drop_ids.append(extra["item_id"])
        need_code = keeper["code"] != canon
        need_loc = keeper["region"] != label or keeper["prefix"] != pref
        if need_code or need_loc:
            updates.append((label, pref, canon, keeper["item_id"]))

    moved = dropped = 0
    with pool.connection() as conn, conn.cursor() as cur:
        for i in range(0, len(updates), 800):
            chunk = updates[i : i + 800]
            cur.executemany(
                f"""
                UPDATE {_embed.TABLE}
                   SET region = %s, prefix = %s, code = %s, updated_at = now()
                 WHERE item_id = %s
                """,
                chunk,
            )
            moved += len(chunk)
        for i in range(0, len(drop_ids), 800):
            chunk = drop_ids[i : i + 800]
            cur.execute(
                f"DELETE FROM {_embed.TABLE} WHERE item_id = ANY(%s)",
                (chunk,),
            )
            dropped += int(cur.rowcount or 0)
        conn.commit()

    if moved or dropped:
        try:
            _FACETS_CACHE.clear()
            _ITEMS_HUB_CACHE.clear()
            _RECOMMEND_CACHE.clear()
        except Exception:  # noqa: BLE001
            pass
    disk = relocate_disk_prefix_dirs(on_progress=on_progress)
    prog(
        f"分区对齐 · 调整 {moved:,} · 去掉重复 {dropped:,} · 磁盘 {disk.get('dirs', 0)} 个前缀",
        percent=5,
        done=moved,
        total=moved,
    )
    return {
        "moved": moved,
        "dropped_dupes": dropped,
        "disk_dirs": int(disk.get("dirs") or 0),
        "disk_rows": int(disk.get("rows") or 0),
        "fc2_updated": int(fc2_mig.get("updated") or 0),
        "fc2_dropped": int(fc2_mig.get("dropped") or 0),
        "fc2_disk": int(fc2_mig.get("disk_moved") or 0),
        "fc2_queue": int(fc2_mig.get("queue") or 0),
    }


def upsert_catalog_skeletons(
    *,
    on_progress: ProgressCb | None = None,
    batch_size: int = 4000,
) -> dict[str, Any]:
    """按六区目录 1:1 同步番号骨架到向量库。

    - 目录无 / 向量有 → 删（含已刮削；prune_embed_not_in_catalog）
    - 目录有 / 向量无 → 插入仅骨架行（空壳态）
    - 两边都有（含已刮削）→ 对齐 region/prefix/code，不覆盖正文
    - 同番号多行（含 FC2↔FC2-PPV）保留已刮削，删多余
    - embedding 用零向量占位；语义检索排除骨架
    """
    import app.prefix.catalog_store as store
    from app.prefix.catalog_strm_sync import safe_name
    from app.core.region_meta import REGION_META, REGION_ORDER, std_prefix

    def prog(stage: str, **kw: Any) -> None:
        payload = {"stage": stage, **kw}
        if on_progress:
            on_progress(payload)

    t0 = time.monotonic()
    cfg = resolve_embed_config(include_secret=True)
    # 骨架空行不依赖在线 embedding；关着也要与目录 1:1
    schema = _embed.ensure_schema()
    dim = int(schema["dim"])
    model_name = str((cfg or {}).get("model") or "skeleton")
    zero_vec = _zero_vec_literal(dim)

    prog("skeleton", percent=2, label="按目录清理多余向量…")
    try:
        purged_codes = prune_embed_not_in_catalog()
    except Exception as e:  # noqa: BLE001
        prog("skeleton", percent=100, label=f"清多余向量失败 · {e}")
        return {
            "ok": False,
            "skipped": False,
            "error": f"prune: {e}",
            "inserted": 0,
            "skipped_existing": 0,
            "purged": 0,
            "purged_codes": 0,
            "total": 0,
        }

    try:
        relocated = realign_embed_locations(on_progress=on_progress)
    except Exception as e:  # noqa: BLE001
        prog("skeleton", percent=100, label=f"分区对齐失败 · {e}")
        return {
            "ok": False,
            "skipped": False,
            "error": f"realign: {e}",
            "inserted": 0,
            "skipped_existing": 0,
            "purged": 0,
            "purged_codes": purged_codes,
            "relocated": 0,
            "dropped_dupes": 0,
            "total": 0,
        }

    prog("skeleton", percent=6, label="加载六区目录…", done=0, total=None)
    doc = store.load_catalog(force=True)
    # 按番号去重：同 code 多路径只插一条（FC2 归一）
    jobs: list[tuple[str, str, str, str, str]] = []
    seen_job_codes: set[str] = set()
    dup_paths = 0
    for rid in REGION_ORDER:
        reg = doc["regions"].get(rid) or {}
        label = str(reg.get("label") or REGION_META.get(rid, {}).get("label") or rid)
        r_name = safe_name(label)
        for pref, ent in (reg.get("prefixes") or {}).items():
            p_key = std_prefix(str(pref))
            p_name = safe_name(p_key or str(pref))
            for code in store.codes_of(ent):
                code_u = _canon_embed_code(code)
                if not code_u:
                    continue
                if code_u in seen_job_codes:
                    dup_paths += 1
                    continue
                seen_job_codes.add(code_u)
                c_name = safe_name(code_u)
                rel = f"{r_name}/{p_name}/{c_name}"
                jobs.append((label, p_key or str(pref).strip().upper(), code_u, rel, item_id_from_rel(rel)))

    total = len(jobs)
    prog(
        "skeleton",
        percent=10,
        label=f"比对已有向量 · {total:,}",
        done=0,
        total=total,
    )

    pool = get_meta_pool()
    existing_ids: set[str] = set()
    existing_codes: set[str] = set()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT item_id, code FROM {_embed.TABLE}")
        for row in cur.fetchall() or []:
            if isinstance(row, dict):
                iid = str(row.get("item_id") or "").strip()
                code = str(row.get("code") or "").strip()
            else:
                iid = str(row[0] or "").strip()
                code = str(row[1] or "").strip()
            if iid:
                existing_ids.add(iid)
            canon = _canon_embed_code(code)
            if canon:
                existing_codes.add(canon)

    pending: list[tuple[str, str, str, str, str]] = []
    skipped_existing = 0
    for row in jobs:
        _label, _pref, code_u, _rel, iid = row
        if iid in existing_ids or code_u in existing_codes:
            skipped_existing += 1
            continue
        pending.append(row)
        existing_ids.add(iid)
        existing_codes.add(code_u)

    prog(
        "skeleton",
        percent=14,
        label=f"待写入骨架 {len(pending):,} · 已有保留 {skipped_existing:,}",
        done=0,
        total=len(pending),
    )

    insert_sql = f"""
        INSERT INTO {_embed.TABLE}
          (item_id, region, prefix, code, rel_path, title,
           poster_path, thumb_path, fanart_path, cover_url,
           model, dim, content_sha, source_text, embedding, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
        ON CONFLICT (item_id) DO NOTHING
    """
    inserted = 0
    bs = max(500, min(8000, int(batch_size or 4000)))
    try:
        if pending:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    for i in range(0, len(pending), bs):
                        chunk = pending[i : i + bs]
                        rows = []
                        for region, prefix, code_u, rel, iid in chunk:
                            src = _skeleton_source_text(code_u)
                            rows.append(
                                [
                                    iid,
                                    region,
                                    prefix,
                                    code_u,
                                    rel,
                                    "",
                                    "",
                                    "",
                                    "",
                                    "",
                                    model_name,
                                    dim,
                                    _skeleton_content_sha(
                                        code_u, model=model_name, dim=dim
                                    ),
                                    src,
                                    zero_vec,
                                ]
                            )
                        cur.executemany(insert_sql, rows)
                        conn.commit()
                        inserted += len(chunk)
                        pct = 14 + int(84 * inserted / max(1, len(pending)))
                        prog(
                            "skeleton",
                            percent=min(98, pct),
                            label=f"骨架写入 {inserted:,}/{len(pending):,}",
                            done=inserted,
                            total=len(pending),
                        )
    except Exception as e:  # noqa: BLE001
        prog(
            "skeleton",
            percent=100,
            label=f"骨架写入中断 · 已写 {inserted:,} · {e}",
            done=inserted,
            total=len(pending),
        )
        return {
            "ok": False,
            "skipped": False,
            "error": str(e),
            "inserted": inserted,
            "skipped_existing": skipped_existing,
            "purged": 0,
            "purged_codes": purged_codes,
            "total": total,
            "pending": len(pending),
            "dup_paths": dup_paths,
            "elapsed_sec": round(time.monotonic() - t0, 1),
            "dim": dim,
            "meta_db": meta_dsn_label(),
            "table": _embed.TABLE,
        }

    # 写完再清一次：防止对齐/写入窗口插入目录外残留
    try:
        purged_codes += prune_embed_not_in_catalog()
    except Exception:  # noqa: BLE001
        pass

    elapsed = round(time.monotonic() - t0, 1)
    prog(
        "skeleton",
        percent=100,
        label=(
            f"骨架同步完成 · 新写入 {inserted:,} · 目录内保留 {skipped_existing:,}"
            f" · 分区调整 {int(relocated.get('moved') or 0):,}"
            f" · 清目录外 {purged_codes:,} · {elapsed}s"
        ),
        done=inserted,
        total=len(pending),
    )
    return {
        "ok": True,
        "skipped": False,
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "purged": 0,
        "purged_codes": purged_codes,
        "relocated": int(relocated.get("moved") or 0),
        "dropped_dupes": int(relocated.get("dropped_dupes") or 0),
        "total": total,
        "pending": len(pending),
        "dup_paths": dup_paths,
        "elapsed_sec": elapsed,
        "dim": dim,
        "meta_db": meta_dsn_label(),
        "table": _embed.TABLE,
    }


def ensure_region_catalog_skeletons(
    region: str,
    *,
    on_progress: ProgressCb | None = None,
    batch_size: int = 4000,
) -> dict[str, Any]:
    """本区向量与目录骨架 1:1（双库扫描真相源）。

    - 目录有 / 向量无 → 插入空壳番号行
    - 向量有 / 目录无 → 删除（含已刮削）
    - 两边都有 → 保留（不覆盖正文）
    """
    import app.prefix.catalog_store as store
    from app.prefix.catalog_strm_sync import safe_name
    from app.core.region_meta import REGION_META, std_prefix

    def prog(stage: str, **kw: Any) -> None:
        if on_progress:
            on_progress({"stage": stage, **kw})

    rid_keys = _catalog_region_ids(region)
    if not rid_keys:
        return {
            "ok": False,
            "skipped": True,
            "reason": "bad_region",
            "inserted": 0,
            "deleted": 0,
            "total": 0,
        }

    t0 = time.monotonic()
    cfg = resolve_embed_config(include_secret=True)
    schema = _embed.ensure_schema()
    dim = int(schema["dim"])
    model_name = str((cfg or {}).get("model") or "skeleton")
    zero_vec = _zero_vec_literal(dim)

    prog("skeleton", percent=2, label=f"对齐目录骨架 · {rid_keys[0]}…")
    doc = store.load_catalog(force=True)
    jobs: list[tuple[str, str, str, str, str]] = []
    catalog_codes: set[str] = set()
    for rid in rid_keys:
        reg = (doc.get("regions") or {}).get(rid) or {}
        label = str(reg.get("label") or REGION_META.get(rid, {}).get("label") or rid)
        r_name = safe_name(label)
        for pref, ent in (reg.get("prefixes") or {}).items():
            p_key = std_prefix(str(pref))
            p_name = safe_name(p_key or str(pref))
            for code in store.codes_of(ent):
                code_u = _canon_embed_code(code)
                if not code_u or code_u in catalog_codes:
                    continue
                catalog_codes.add(code_u)
                c_name = safe_name(code_u)
                rel = f"{r_name}/{p_name}/{c_name}"
                jobs.append(
                    (
                        label,
                        p_key or str(pref).strip().upper(),
                        code_u,
                        rel,
                        item_id_from_rel(rel),
                    )
                )

    total = len(jobs)
    prog(
        "skeleton",
        percent=8,
        label=f"目录 {total:,} · 清理目录外向量…",
        done=0,
        total=total,
    )

    pool = get_meta_pool()
    region_sql, region_params = _quality_region_sql(rid_keys[0])
    deleted = 0
    existing_ids: set[str] = set()
    existing_codes: set[str] = set()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, code FROM {_embed.TABLE}
             WHERE coalesce(trim(code), '') <> ''
               {region_sql}
            """,
            region_params,
        )
        dead: list[str] = []
        for row in cur.fetchall() or []:
            if isinstance(row, dict):
                iid = str(row.get("item_id") or "").strip()
                code = str(row.get("code") or "").strip()
            else:
                iid = str(row[0] or "").strip()
                code = str(row[1] or "").strip()
            if not iid:
                continue
            canon = _canon_embed_code(code)
            if not canon or canon not in catalog_codes:
                dead.append(iid)
                continue
            existing_ids.add(iid)
            existing_codes.add(canon)
        for i in range(0, len(dead), 800):
            chunk = dead[i : i + 800]
            cur.execute(
                f"DELETE FROM {_embed.TABLE} WHERE item_id = ANY(%s)",
                (chunk,),
            )
            deleted += int(cur.rowcount or 0)
        conn.commit()

    prog(
        "skeleton",
        percent=14,
        label=f"已删目录外 {deleted:,} · 比对待建空壳…",
        done=0,
        total=total,
    )

    pending: list[tuple[str, str, str, str, str]] = []
    skipped = 0
    for row in jobs:
        _label, _pref, code_u, _rel, iid = row
        if iid in existing_ids or code_u in existing_codes:
            skipped += 1
            continue
        pending.append(row)
        existing_ids.add(iid)
        existing_codes.add(code_u)

    insert_sql = f"""
        INSERT INTO {_embed.TABLE}
          (item_id, region, prefix, code, rel_path, title,
           poster_path, thumb_path, fanart_path, cover_url,
           model, dim, content_sha, source_text, embedding, updated_at)
        VALUES
          (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
        ON CONFLICT (item_id) DO NOTHING
    """
    inserted = 0
    bs = max(500, min(8000, int(batch_size or 4000)))
    try:
        if pending:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    for i in range(0, len(pending), bs):
                        chunk = pending[i : i + bs]
                        rows = []
                        for region_label, prefix, code_u, rel, iid in chunk:
                            src = _skeleton_source_text(code_u)
                            rows.append(
                                [
                                    iid,
                                    region_label,
                                    prefix,
                                    code_u,
                                    rel,
                                    "",
                                    "",
                                    "",
                                    "",
                                    "",
                                    model_name,
                                    dim,
                                    _skeleton_content_sha(
                                        code_u, model=model_name, dim=dim
                                    ),
                                    src,
                                    zero_vec,
                                ]
                            )
                        cur.executemany(insert_sql, rows)
                        conn.commit()
                        inserted += len(chunk)
                        pct = 14 + int(84 * inserted / max(1, len(pending)))
                        prog(
                            "skeleton",
                            percent=min(98, pct),
                            label=f"空壳写入 {inserted:,}/{len(pending):,}",
                            done=inserted,
                            total=len(pending),
                        )
    except Exception as e:  # noqa: BLE001
        log.warning("sync region catalog skeletons failed region=%s: %s", rid_keys, e)
        return {
            "ok": False,
            "error": str(e),
            "inserted": inserted,
            "deleted": deleted,
            "skipped_existing": skipped,
            "total": total,
            "pending": len(pending),
            "elapsed_sec": round(time.monotonic() - t0, 1),
        }

    # 清本区相关缓存
    try:
        _FACETS_CACHE.clear()
        _ITEMS_HUB_CACHE.clear()
        _RECOMMEND_CACHE.clear()
    except Exception:  # noqa: BLE001
        pass

    elapsed = round(time.monotonic() - t0, 1)
    prog(
        "skeleton",
        percent=100,
        label=(
            f"骨架 1:1 · 删目录外 {deleted:,} · 新建空壳 {inserted:,}"
            f" · 保留 {skipped:,} · 目录 {total:,} · {elapsed}s"
        ),
        done=total,
        total=total,
    )
    return {
        "ok": True,
        "inserted": inserted,
        "deleted": deleted,
        "skipped_existing": skipped,
        "total": total,
        "pending": len(pending),
        "region": rid_keys[0],
        "elapsed_sec": elapsed,
        "dim": dim,
    }


def purge_catalog_skeletons() -> int:
    """删除 content_sha 标记为 skeleton 的骨架行（手动/维护用）。"""
    _embed.ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {_embed.TABLE} WHERE content_sha LIKE %s",
            (f"{SKELETON_SHA_PREFIX}:%",),
        )
        n = int(cur.rowcount or 0)
        conn.commit()
    return n


def rebuild_catalog_skeletons(
    *,
    on_progress: ProgressCb | None = None,
    batch_size: int = 4000,
) -> dict[str, Any]:
    """双库扫描后：以最新目录为唯一真相源，向量库与目录 1:1。

    - 删光旧骨架壳
    - 目录外番号整行删除（**含已刮削**）
    - 目录有、向量无 → 插入骨架
    - 目录有且已刮削 → 保留正文，对齐 region/prefix/code（FC2 归一）
    """

    def prog(stage: str, **kw: Any) -> None:
        if on_progress:
            on_progress({"stage": stage, **kw})

    t0 = time.monotonic()
    # 骨架行不依赖在线 embedding；关着嵌入也要与目录 1:1
    _embed.ensure_schema()

    prog("skeleton", percent=1, label="按最新目录 1:1 对齐向量…")

    # 清分面缓存，避免旧骨架聚合
    try:
        _FACETS_CACHE.clear()
        _ITEMS_HUB_CACHE.clear()
        _RECOMMEND_CACHE.clear()
    except Exception:  # noqa: BLE001
        pass

    # upsert 内：prune 目录外（含已刮削）+ 补空壳；不再先删光全部骨架再重建
    sync = upsert_catalog_skeletons(on_progress=on_progress, batch_size=batch_size)
    out = {
        **sync,
        "mode": "rebuild",
        "purged_skeletons": 0,
        "elapsed_sec": round(time.monotonic() - t0, 1),
    }
    if sync.get("ok"):
        inserted = int(sync.get("inserted") or 0)
        purged_codes = int(sync.get("purged_codes") or 0)
        kept = int(sync.get("skipped_existing") or 0)
        total = int(sync.get("total") or 0)
        prog(
            "skeleton",
            percent=100,
            label=(
                f"骨架 1:1 完成 · 目录外 -{purged_codes:,}"
                f" · 新壳 +{inserted:,} · 目录内保留 {kept:,} · 目录 {total:,}"
            ),
            done=total,
            total=total,
        )
    return out


def reset_embed_to_catalog_skeletons(
    *,
    on_progress: ProgressCb | None = None,
    batch_size: int = 4000,
) -> dict[str, Any]:
    """清空向量库全部行，再按六区目录 1:1 重建仅番号骨架。

    用于「刮削前只留骨架、逐号重刮入库」测试/重建。
    不删本地 scrap-library 磁盘上的 NFO/封面；单号 overwrite 刮削时会覆盖写回。
    """
    def prog(stage: str, **kw: Any) -> None:
        if on_progress:
            on_progress({"stage": stage, **kw})

    _embed.ensure_schema()
    pool = get_meta_pool()
    prog("reset", percent=2, label="统计现有行…")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS c FROM {_embed.TABLE}")
        before = int(dict(cur.fetchone() or {}).get("c") or 0)
        cur.execute(
            f"SELECT count(*) AS c FROM {_embed.TABLE} WHERE content_sha LIKE %s",
            (f"{SKELETON_SHA_PREFIX}:%",),
        )
        before_skel = int(dict(cur.fetchone() or {}).get("c") or 0)

    prog("reset", percent=8, label=f"清空向量表 · {before:,} 行…")
    with pool.connection() as conn, conn.cursor() as cur:
        # TRUNCATE 快；无表则 DELETE
        try:
            cur.execute(f"TRUNCATE TABLE {_embed.TABLE}")
        except Exception:  # noqa: BLE001
            cur.execute(f"DELETE FROM {_embed.TABLE}")
        deleted = before
        conn.commit()

    # 清分面缓存，避免旧聚合
    try:
        _FACETS_CACHE.clear()
        _ITEMS_HUB_CACHE.clear()
        _RECOMMEND_CACHE.clear()
    except Exception:  # noqa: BLE001
        pass

    prog("reset", percent=20, label="按目录重建骨架…")
    sync = upsert_catalog_skeletons(on_progress=on_progress, batch_size=batch_size)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) AS c FROM {_embed.TABLE}")
        after = int(dict(cur.fetchone() or {}).get("c") or 0)
        cur.execute(
            f"SELECT count(*) AS c FROM {_embed.TABLE} WHERE content_sha LIKE %s",
            (f"{SKELETON_SHA_PREFIX}:%",),
        )
        after_skel = int(dict(cur.fetchone() or {}).get("c") or 0)

    prog(
        "reset",
        percent=100,
        label=f"完成 · 删 {deleted:,} · 骨架 {after_skel:,}",
        done=after_skel,
        total=after_skel,
    )
    return {
        "ok": bool(sync.get("ok", True)) and not sync.get("error"),
        "deleted": deleted,
        "before": before,
        "beforeSkeletons": before_skel,
        "after": after,
        "afterSkeletons": after_skel,
        "skeletonSync": sync,
    }


def prune_embed_not_in_catalog() -> int:
    """删除向量库中番号不在最新六区目录里的行（含已刮削）。

    FC2-PPV-* 与 FC2-* 按同一番号比对；目录外一律删，保证与双库扫描结果 1:1。
    """
    _embed.ensure_schema()
    codes = catalog_code_set()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        if not codes:
            cur.execute(
                f"""
                DELETE FROM {_embed.TABLE}
                WHERE coalesce(trim(code), '') <> ''
                """
            )
            n = int(cur.rowcount or 0)
            conn.commit()
            return n

        cur.execute(f"SELECT item_id, code FROM {_embed.TABLE}")
        rows = cur.fetchall() or []
        dead: list[str] = []
        for row in rows:
            if isinstance(row, dict):
                iid = str(row.get("item_id") or "").strip()
                code = str(row.get("code") or "").strip()
            else:
                iid = str(row[0] or "").strip()
                code = str(row[1] or "").strip()
            if not iid:
                continue
            canon = _canon_embed_code(code)
            if not canon or canon not in codes:
                dead.append(iid)

        n = 0
        for i in range(0, len(dead), 800):
            chunk = dead[i : i + 800]
            cur.execute(
                f"DELETE FROM {_embed.TABLE} WHERE item_id = ANY(%s)",
                (chunk,),
            )
            n += int(cur.rowcount or 0)
        conn.commit()
    return n


def prune_embed_missing_from_disk(root: Path) -> int:
    """删除刮削库磁盘上已无 NFO 目录的向量行；目录空壳（skeleton）保留。"""
    _embed.ensure_schema()
    root_resolved = Path(root).resolve()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT item_id, rel_path, content_sha FROM {_embed.TABLE}")
        rows = cur.fetchall() or []
    dead: list[str] = []
    for r in rows:
        if isinstance(r, dict):
            iid = str(r.get("item_id") or "").strip()
            rel = str(r.get("rel_path") or "").replace("\\", "/").strip().strip("/")
            sha = str(r.get("content_sha") or "")
        else:
            iid = str(r[0] or "").strip()
            rel = str(r[1] or "").replace("\\", "/").strip().strip("/")
            sha = str(r[2] or "") if len(r) > 2 else ""
        if not iid:
            continue
        # 空壳无本地 NFO 是常态，留给刮削补齐
        if is_skeleton_sha(sha):
            continue
        folder = root_resolved / rel if rel else root_resolved
        try:
            if folder.is_dir() and any(folder.glob("*.nfo")):
                continue
        except OSError:
            pass
        dead.append(iid)
    if not dead:
        return 0
    n = 0
    with pool.connection() as conn, conn.cursor() as cur:
        for i in range(0, len(dead), 800):
            chunk = dead[i : i + 800]
            cur.execute(
                f"DELETE FROM {_embed.TABLE} WHERE item_id = ANY(%s)",
                (chunk,),
            )
            n += int(cur.rowcount or 0)
        conn.commit()
    return n


def prune_embed_missing_from_disk_ids(alive_ids: set[str]) -> int:
    """按存活 item_id 集合删除（兼容旧调用）。"""
    return prune_embed_orphans_by_ids(alive_ids)


def prune_embed_orphans_by_ids(alive_ids: set[str]) -> int:
    """删除不在 alive_ids 中的向量行。"""
    _embed.ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        if not alive_ids:
            cur.execute(f"DELETE FROM {_embed.TABLE}")
            n = int(cur.rowcount or 0)
        else:
            cur.execute(f"SELECT item_id FROM {_embed.TABLE}")
            rows = cur.fetchall() or []
            existing = {
                str((r.get("item_id") if isinstance(r, dict) else r[0]) or "")
                for r in rows
            }
            dead = [iid for iid in existing if iid and iid not in alive_ids]
            n = 0
            for i in range(0, len(dead), 800):
                chunk = dead[i : i + 800]
                cur.execute(
                    f"DELETE FROM {_embed.TABLE} WHERE item_id = ANY(%s)",
                    (chunk,),
                )
                n += int(cur.rowcount or 0)
        conn.commit()
    return n


_SKELETON_SQL = f"content_sha LIKE '{SKELETON_SHA_PREFIX}:%%'"


_NOT_SKELETON_SQL = f"content_sha NOT LIKE '{SKELETON_SHA_PREFIX}:%%'"


def _quality_region_sql(region: str) -> tuple[str, list[Any]]:
    values = _embed._region_match_values(region)
    if not values:
        return "", []
    return " AND region = ANY(%s)", [values]


def _catalog_region_ids(region: str) -> list[str]:
    """quality/enrich 用的目录区 id 列表；空 = 六区全开。"""
    from app.core.region_meta import REGION_META, REGION_ORDER, resolve_fs_region

    raw = str(region or "").strip()
    if not raw:
        return list(REGION_ORDER)
    key = resolve_fs_region(raw) or (raw if raw in REGION_META else "")
    if key and key in REGION_META:
        return [key]
    for rid, meta in REGION_META.items():
        if raw == rid or raw == str(meta.get("label") or ""):
            return [rid]
    return []


def _shell_rel_path(region_label: str, prefix: str, code: str) -> str:
    from app.prefix.catalog_strm_sync import safe_name

    label = str(region_label or "").strip()
    code_u = str(code or "").strip()
    pref = str(prefix or "").strip()
    # 六区统一：区/前缀/番号；FC2 磁盘夹一律 FC2/FC2/FC2-*
    if label.casefold() in {"fc2", "fc2ppv"} or label.upper() == "FC2":
        from app.core.region_meta import fc2_fs_prefix, normalize_fc2_code

        code_u = normalize_fc2_code(code_u)
        pref = fc2_fs_prefix(pref, code=code_u)
    elif not pref:
        pref = str(prefix or "").strip()
    return (
        f"{safe_name(label)}/"
        f"{safe_name(pref)}/"
        f"{safe_name(code_u)}"
    )


def iter_catalog_shell_items(region: str = "") -> Any:
    """目录有、向量库完全没有的番号（骨架同步未跑完时的兜底）。"""
    import app.prefix.catalog_store as store
    from app.core.region_meta import REGION_META

    existing = _embed_code_set(region)
    try:
        doc = store.load_catalog(force=False)
    except Exception:  # noqa: BLE001
        return
    regions = (doc or {}).get("regions") or {}
    for rid in _catalog_region_ids(region):
        reg = regions.get(rid) or {}
        label = str(
            reg.get("label") or REGION_META.get(rid, {}).get("label") or rid
        ).strip()
        for pref, ent in (reg.get("prefixes") or {}).items():
            pref_s = str(pref or "").strip()
            try:
                codes = store.codes_of(ent)
            except Exception:  # noqa: BLE001
                continue
            for code in codes:
                cu = str(code or "").strip().upper()
                if not cu or cu in existing:
                    continue
                p = pref_s or (cu.split("-", 1)[0] if "-" in cu else cu)
                rel = _shell_rel_path(label, p, cu)
                yield {
                    "itemId": rel,
                    "region": label,
                    "prefix": p,
                    "code": cu,
                    "title": cu,
                    "relPath": rel,
                    "gaps": list(_SHELL_GAPS),
                    "shell": True,
                }


def count_catalog_shells(region: str = "") -> int:
    return sum(1 for _ in iter_catalog_shell_items(region))


def list_catalog_shell_items(
    region: str = "",
    *,
    limit: int = 0,
    offset: int = 0,
) -> list[dict[str, Any]]:
    off = max(0, int(offset or 0))
    lim = int(limit or 0)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(iter_catalog_shell_items(region)):
        if i < off:
            continue
        out.append(row)
        if lim > 0 and len(out) >= lim:
            break
    return out


def count_skeleton_shells(region: str = "") -> int:
    """向量库仅骨架（空壳）条数。"""
    _embed.ensure_schema()
    region_sql, params = _quality_region_sql(region)
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*) AS n FROM {_embed.TABLE}
            WHERE {_SKELETON_SQL}{region_sql}
            """,
            params,
        )
        row = cur.fetchone() or {}
        return int((row.get("n") if isinstance(row, dict) else row[0]) or 0)


def _dedup_appender(out: list[dict[str, Any]], seen: set[str]):
    """返回「按 `itemId` 去重后追加到 `out`」的写入闭包。

    `quality_items` / `quality_incomplete_items` / `enrich_all_items` 的拼装逻辑
    完全一致，只有 `out` / `seen` 是各自的局部状态 —— 故共用这一个工厂
    （原为三份逐字相同的嵌套 `_take`）。
    """

    def append(rows: list[dict[str, Any]]) -> None:
        for r in rows:
            iid = str(r.get("itemId") or "")
            if not iid or iid in seen:
                continue
            seen.add(iid)
            out.append(r)

    return append


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


def _scan_workers() -> int:
    from app.core.container_budget import io_threads, memory_class

    if memory_class() == "host":
        cpus = os.cpu_count() or 4
        return max(8, min(32, cpus * 2))
    return io_threads(floor=2, host_max=4)


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
    # 标准：region/prefix/code；兼容旧扁平 FC2/{CODE}
    if len(parts) == 2 and str(parts[0] or "").casefold() in {"fc2", "fc2ppv"}:
        from app.core.region_meta import fc2_prefix_from_code, normalize_fc2_code

        region = parts[0]
        code = normalize_fc2_code(parts[1])
        prefix = fc2_prefix_from_code(code)
    else:
        region = parts[0] if len(parts) >= 1 else ""
        prefix = parts[1] if len(parts) >= 2 else ""
        code = parts[2] if len(parts) >= 3 else nfo.stem
        # FC2 区若误把前缀层当番号，按番号纠正
        if (
            str(region or "").casefold() in {"fc2", "fc2ppv"}
            and prefix
            and str(prefix).upper().replace("-", "").startswith("FC2")
            and any(ch.isdigit() for ch in prefix)
            and (not code or code == nfo.stem)
        ):
            from app.core.region_meta import fc2_prefix_from_code, normalize_fc2_code

            code = normalize_fc2_code(prefix)
            prefix = fc2_prefix_from_code(code)
        elif str(region or "").casefold() in {"fc2", "fc2ppv"}:
            from app.core.region_meta import fc2_prefix_from_code, normalize_fc2_code

            code = normalize_fc2_code(code)
            prefix = _canonical_folder_prefix(prefix) or fc2_prefix_from_code(code)
    meta = parse_nfo(nfo)
    if not meta:
        return None

    # actors 按 NFO 原文进向量；不再 junk 清洗 / 撞片商剔除

    files = _folder_file_names(folder)

    def pick(*candidates: str) -> str:
        for raw in candidates:
            text = str(raw or "").strip()
            if not text or text.startswith(("http://", "https://")):
                continue
            clean = text.replace("\\", "/").lstrip("/")
            if ".." in clean.split("/") or "/" in clean:
                got = _embed_poster._pick_local_image(
                    folder, text, files=files, media_root=media_root
                )
                if got and not _embed_poster._is_blank_cover_rel(got):
                    return got
                continue
            real = files.get(clean.casefold())
            if not real:
                continue
            abs_file = folder / real
            if _embed._is_blank_cover_file(abs_file):
                continue
            if scrap_rel:
                base = f"{scrap_rel}/{rel}" if rel else scrap_rel
                return f"{base}/{real}"
            got = _embed_poster._pick_local_image(
                folder, real, files=files, media_root=media_root
            )
            if got and not _embed_poster._is_blank_cover_rel(got):
                return got
        return ""

    poster_path = pick(str(meta.get("poster") or ""), "poster.jpg")
    thumb_path = pick(str(meta.get("thumb") or ""), "thumb.jpg")
    fanart_path = pick(str(meta.get("fanart") or ""), "fanart.jpg")
    cover_url = str(meta.get("cover_url") or "").strip()
    # 不外链拉图：仅索引本地 poster/thumb；缺图留给 cover_url 展示或其它补齐路径
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


def _existing_embed_rows(
    item_ids: list[str],
) -> dict[str, dict[str, str]]:
    """item_id → {sha, source_text}"""
    if not item_ids:
        return {}
    out: dict[str, dict[str, str]] = {}
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            for i in range(0, len(item_ids), 800):
                chunk = item_ids[i : i + 800]
                cur.execute(
                    f"""
                    SELECT item_id, content_sha, source_text
                    FROM {_embed.TABLE}
                    WHERE item_id = ANY(%s)
                    """,
                    (chunk,),
                )
                for row in cur.fetchall():
                    if not isinstance(row, dict):
                        continue
                    iid = str(row.get("item_id") or "")
                    if not iid:
                        continue
                    out[iid] = {
                        "sha": str(row.get("content_sha") or ""),
                        "source_text": str(row.get("source_text") or ""),
                    }
    return out


def _existing_shas(item_ids: list[str]) -> dict[str, str]:
    return {
        iid: meta["sha"]
        for iid, meta in _existing_embed_rows(item_ids).items()
    }


def _meta_iter_batches(
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    *,
    batch_size: int = 200,
    cursor_name: str = "meta_scan",
):
    """元库服务端游标分批吐行。设置里的全表任务不要 fetchall。"""
    size = max(50, int(batch_size or 200))
    pool = get_meta_pool()
    with pool.connection() as conn:
        with conn.cursor(name=cursor_name) as cur:
            cur.itersize = size
            cur.execute(sql, params or [])
            while True:
                rows = cur.fetchmany(size)
                if not rows:
                    break
                yield rows


def vectorize_db_embeddings(
    *,
    batch_size: int = 32,
    force: bool = False,
    limit: int | None = None,
    on_progress: ProgressCb | None = None,
    resume_done_ids: set[str] | None = None,
) -> dict[str, Any]:
    """对元库已有行做向量编码（不扫磁盘 NFO）。

    增量：仅非骨架且 embedding 为零向量的行。
    全量：非骨架行全部重嵌。
    """
    init_db()
    schema = _embed.ensure_schema()
    _embed.assert_embed_ready()
    done_ids = set(resume_done_ids or ())
    dim = int(schema["dim"])
    zero_lit = _zero_vec_literal(dim)
    cfg_root = str(_embed.get_settings().get("root") or DEFAULT_REL_ROOT)

    def prog(stage: str, **kw: Any) -> None:
        payload = {"stage": stage, **kw}
        _set_progress(**payload)
        if on_progress:
            on_progress(payload)
        if stage in {"diff", "embed", "done"}:
            _persist_embed_job(
                status="running" if stage != "done" else "done",
                params={
                    "force": bool(force),
                    "root": cfg_root,
                    "mode": "embed",
                },
                doneIds=sorted(done_ids)[-8000:],
            )

    prog("diff", percent=8, label="筛选待向量化…", done=0, total=None)
    pool = get_meta_pool()
    where_sql = _NOT_SKELETON_SQL
    count_params: list[Any] = []
    if not force:
        where_sql += " AND embedding = %s::vector"
        count_params.append(zero_lit)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*)::int AS n FROM {_embed.TABLE} WHERE {where_sql}",
            count_params,
        )
        counted = cur.fetchone() or {}
        total_all = int(
            (counted.get("n") if isinstance(counted, dict) else counted[0]) or 0
        )
    cap = int(limit) if limit is not None and int(limit) > 0 else 0
    scan_total = min(total_all, cap) if cap else total_all
    _push_log(
        f"待扫描 {scan_total:,}"
        + (" · 全量重嵌" if force else " · 仅零向量")
    )
    if scan_total == 0:
        prog("done", percent=100, label="无需向量化", done=0, total=0)
        return {
            "written": 0,
            "skipped": 0,
            "deleted": 0,
            "total": 0,
            "root": cfg_root,
            "meta_db": meta_dsn_label(),
            "table": _embed.TABLE,
            "dim": dim,
            "mode": "embed",
        }

    prog("embed", percent=12, label=f"编码 0/{scan_total}", done=0, total=scan_total)
    _push_log("向量模型预热…")
    encode_texts_sync(["."], query=False)
    _push_log("向量模型已预热")

    cfg = resolve_embed_config(include_secret=True)
    model_name = str(cfg["model"])
    emb_dim = int(cfg["dim"])
    bs = max(1, min(64, int(batch_size)))
    written = 0
    skipped_done = 0
    scanned = 0
    update_sql = f"""
        UPDATE {_embed.TABLE} SET
          model = %s,
          dim = %s,
          embedding = %s::vector,
          updated_at = now()
        WHERE item_id = %s
    """

    def _encode_chunk(chunk: list[dict[str, Any]]) -> None:
        nonlocal written
        if not chunk:
            return
        texts = [str(r.get("source_text") or "") for r in chunk]
        vecs = encode_texts_sync(texts, query=False)
        if len(vecs) != len(chunk):
            raise RuntimeError(f"向量条数不匹配: {len(vecs)} != {len(chunk)}")
        if any(len(v) != emb_dim for v in vecs):
            raise RuntimeError(f"向量维度不是 {emb_dim}")
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    update_sql,
                    [
                        (
                            model_name,
                            emb_dim,
                            _vec_literal(vec),
                            str(r.get("item_id") or ""),
                        )
                        for r, vec in zip(chunk, vecs, strict=True)
                    ],
                )
            conn.commit()
        written += len(chunk)
        for r in chunk:
            iid = str(r.get("item_id") or "")
            if iid:
                done_ids.add(iid)
        pct = 12 + int(80 * scanned / max(1, scan_total))
        prog(
            "embed",
            percent=min(94, pct),
            label=f"编码 {written}/{scan_total}",
            done=written,
            total=scan_total,
        )
        _persist_embed_job(
            status="running",
            params={"force": bool(force), "root": cfg_root, "mode": "embed"},
            doneIds=sorted(done_ids)[-8000:],
        )

    select_sql = f"""
        SELECT item_id, source_text, dim
        FROM {_embed.TABLE}
        WHERE {where_sql}
        ORDER BY item_id
    """
    buf: list[dict[str, Any]] = []
    for raw_batch in _meta_iter_batches(
        select_sql,
        count_params,
        batch_size=200,
        cursor_name="scrap_embed_vec",
    ):
        for raw in raw_batch:
            if cap and scanned >= cap:
                break
            scanned += 1
            if isinstance(raw, dict):
                row = raw
            else:
                row = {
                    "item_id": raw[0],
                    "source_text": raw[1],
                    "dim": raw[2],
                }
            iid = str(row.get("item_id") or "")
            if iid and iid in done_ids:
                skipped_done += 1
                continue
            buf.append(row)
            if len(buf) >= bs:
                _encode_chunk(buf)
                buf = []
                if written == bs or written % max(bs * 4, 1) == 0:
                    _push_log(f"编码 {written}/{scan_total}")
        if cap and scanned >= cap:
            break
    if buf:
        _encode_chunk(buf)
        _push_log(f"编码 {written}/{scan_total}")
    if skipped_done:
        _push_log(f"续跑跳过已编码 {skipped_done:,}")
    total = scan_total

    try:
        ensure_hnsw()
        _push_log("HNSW 向量索引就绪")
    except Exception as e:  # noqa: BLE001
        _push_log(f"HNSW 跳过: {e}")

    result = {
        "written": written,
        "skipped": 0,
        "deleted": 0,
        "total": total,
        "root": cfg_root,
        "meta_db": meta_dsn_label(),
        "table": _embed.TABLE,
        "dim": emb_dim,
        "mode": "embed",
    }
    prog("done", percent=100, label="完成", done=written, total=total)
    _push_log(f"向量化完成 · 写入 {written:,} / {total:,}")
    return result


def _folder_prefix_aliases(prefix: str) -> list[str]:
    """前缀查询别名。FC2 / 旧 FC2PPV 一律归并。"""
    p = str(prefix or "").strip().upper()
    if not p:
        return []
    return [_canonical_folder_prefix(p)]


def _canonical_folder_prefix(prefix: str) -> str:
    """磁盘/查询前缀 → catalog 键（FC2-PPV / FC2PPV → FC2）。"""
    p = str(prefix or "").strip().upper()
    compact = re.sub(r"[-_\s]", "", p)
    if compact.startswith("FC2PPV") or p in {"FC2-PPV", "FC2_PPV"} or compact == "FC2":
        return "FC2"
    return p


def _fc2_rel_path_aliases(parts: list[str]) -> list[list[str]]:
    """FC2 扁平/旧夹名 → 现行 ``FC2/FC2/FC2-{num}`` 及读兼容候选。"""
    if len(parts) < 3:
        return []
    try:
        i = next(idx for idx, p in enumerate(parts) if str(p).upper() == "FC2")
    except StopIteration:
        return []
    if i + 1 >= len(parts):
        return []
    from app.core.region_meta import normalize_fc2_code

    out: list[list[str]] = []
    nxt = str(parts[i + 1] or "")
    nxt_u = nxt.upper().replace("_", "-")
    head = parts[: i + 1]

    def _push(pref: str, code: str, rest: list[str]) -> None:
        out.append([*head, pref, code, *rest])

    # 三层：前缀夹 + 番号 → 优先现行，再试旧夹/旧番号名
    if nxt_u in {"FC2", "FC2-PPV", "FC2PPV"} and i + 2 < len(parts):
        raw_code = str(parts[i + 2] or "")
        code = normalize_fc2_code(raw_code)
        rest = list(parts[i + 3 :])
        _push("FC2", code, rest)
        if raw_code.upper() != code:
            _push("FC2", raw_code, rest)
        _push("FC2-PPV", code, rest)
        _push("FC2-PPV", raw_code, rest)
        _push("FC2PPV", raw_code, rest)
        return out
    # 扁平 FC2/{CODE}/… → FC2/FC2/{FC2-num}/…
    if nxt_u.startswith("FC2"):
        code = normalize_fc2_code(nxt)
        rest = list(parts[i + 2 :])
        _push("FC2", code, rest)
        _push("FC2-PPV", code, rest)
        if nxt.upper() != code:
            _push("FC2", nxt, rest)
            _push("FC2-PPV", nxt, rest)
    return out


def resolve_existing_media_rel(rel: str) -> str:
    """返回实际存在的 media 相对路径；FC2 迁移后旧路径自动改写。"""
    text = str(rel or "").strip().replace("\\", "/").lstrip("/")
    if not text:
        return ""
    parts = [x for x in Path(text).parts if x not in ("", ".", "/")]
    if not parts or any(x == ".." for x in parts):
        return ""
    root = media_dir().resolve()
    candidates = [parts, *_fc2_rel_path_aliases(parts)]
    seen: set[str] = set()
    for cand in candidates:
        key = "/".join(cand)
        if key in seen:
            continue
        seen.add(key)
        abs_path = (root / Path(*cand)).resolve()
        try:
            abs_path.relative_to(root)
        except ValueError:
            continue
        if abs_path.is_file():
            return key
    return ""
