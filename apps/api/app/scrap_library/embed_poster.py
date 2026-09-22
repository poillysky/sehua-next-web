# -*- coding: utf-8 -*-
"""embed_poster —— 自 scrap_library/embed.py 拆出（机械搬移，行为不变）。"""

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
import app.scrap_library.embed_catalog as _embed_catalog
from app.scrap_library.embed import (_POSTER_DL_FAIL_CAP, _blank_cover_cache, _ensure_poster_dl_pool, _is_http_url, _media_rel, _poster_dl_fail_until, _poster_dl_inflight, _poster_dl_lock, canonical_fc2_scrap_rel, log)


def _blank_pixels(im) -> list:
    """把 PIL Image 缩成 24x24 像素列表（供空图判定复用）。"""
    from PIL import Image as _Image

    rgb = im.convert("RGB")
    small = rgb.resize((24, 24), _Image.Resampling.BILINEAR)
    return list(small.getdata())


def _blank_from_pixels(pixels: list) -> bool:
    """低色彩多样性 / 近灰白平铺 / 近黑近白低方差 → 视为空封面。"""
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
    # 近白 / 近黑 + 低方差（亮度门）
    mean_y = 0.299 * means[0] + 0.587 * means[1] + 0.114 * means[2]
    if mean_y > 245 and var < 500:
        return True
    if mean_y < 12 and var < 500:
        return True
    return False


def _image_looks_blank(path: Path) -> bool:
    """低色彩多样性 / 近灰白平铺 → 视为空封面（磁盘文件版）。"""
    try:
        from PIL import Image

        with Image.open(path) as im:
            pixels = _blank_pixels(im)
    except Exception:
        return False
    return _blank_from_pixels(pixels)


def _image_bytes_looks_blank(raw: bytes) -> bool:
    """空图判定（内存字节版）：免落盘探测，避免临时文件写删。"""
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(raw)) as im:
            pixels = _blank_pixels(im)
    except Exception:
        return False
    return _blank_from_pixels(pixels)


def _image_magic_ok(raw: bytes) -> bool:
    """字节是否带**图片容器头**（JPEG / PNG / GIF / WEBP / BMP / AVIF-ish）。

    ⚠️ 为什么单靠 `_is_blank_cover_file()` 不够：它对「PIL 打不开」一律
    `return False`（= 当作有效图，避免 PIL 缺编解码器时把所有封面误判成空白）。
    于是源站返回的 **HTML 错误页（>1024B）会被当成合格封面落成 poster.jpg**，
    而且 `>=80_000` 字节还会走体积豁免分支直接放行。
    真实缺陷现场：`_write_poster_jpg(HTML 2482B)` → 落盘成功。
    这里用**容器头**做廉价硬门禁（不解码、不依赖 PIL），挡掉非图片字节。
    """
    head = bytes(raw or b"")[:16]
    if len(head) < 12:
        return False
    if head.startswith(b"\xff\xd8\xff"):  # JPEG
        return True
    if head.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
        return True
    if head.startswith((b"GIF87a", b"GIF89a")):  # GIF
        return True
    if head.startswith(b"BM"):  # BMP
        return True
    if head[0:4] == b"RIFF" and head[8:12] == b"WEBP":  # WEBP
        return True
    if head[4:8] == b"ftyp" and head[8:12] in (b"avif", b"avis", b"mif1"):  # AVIF/HEIF
        return True
    return False


def _is_blank_cover_rel(rel: str) -> bool:
    r = str(rel or "").strip().replace("\\", "/")
    if not r:
        return True
    hit = _blank_cover_cache.get(r)
    if hit is not None:
        return hit
    try:
        path = _embed.resolve_local_file(r)
        blank = _embed._is_blank_cover_file(path)
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
    names = files if files is not None else _embed_catalog._folder_file_names(folder)
    real = names.get(clean.casefold())
    if not real:
        return ""
    return _media_rel(folder / real, media_root=media_root)


def _trim_poster_dl_fails() -> None:
    """超上限时丢掉最早过期的一半（纯冷却表，丢失只会让某条早点重试）。"""
    if len(_poster_dl_fail_until) < _POSTER_DL_FAIL_CAP:
        return
    doomed = sorted(_poster_dl_fail_until, key=_poster_dl_fail_until.get)[
        : len(_poster_dl_fail_until) // 2
    ]
    for k in doomed:
        _poster_dl_fail_until.pop(k, None)


def _write_poster_jpg(folder: Path, data: bytes) -> Path | None:
    """写入番号目录 poster.jpg；成功返回路径。"""
    try:
        # 先挡非图片字节：HTML / JSON 错误页必须在这里被拒，不能落成 poster.jpg
        # （`_is_blank_cover_file` 对「PIL 打不开」返回 False，单靠它会放行）。
        if not _image_magic_ok(data):
            log.debug("scrap poster reject: not an image container")
            return None
        if not folder.is_dir():
            folder.mkdir(parents=True, exist_ok=True)
        dest = folder / "poster.jpg"
        tmp = folder / "poster.jpg.part"
        tmp.write_bytes(data)
        # 拒绝空图占位
        if _embed._is_blank_cover_file(tmp):
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
    crop_mode: str | None = None,
) -> str:
    """本地缺/空 poster 时，把远程 cover 落到 folder/poster.jpg，返回 media 相对路径。

    横图会按分区走 smart 裁出主人物竖幅（与 enrich 一致），避免整盒横封直接落盘。
    """
    if not _is_http_url(cover_url):
        return ""
    if not folder.is_dir():
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ""
    existing = folder / "poster.jpg"
    if existing.is_file() and not _embed._is_blank_cover_file(existing):
        return _media_rel(existing, media_root=media_root)

    try:
        got = _embed._fetch_cover_bytes(cover_url)
    except TimeoutError:
        return ""
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

    try:
        from app.scrap_library.cover_scrape import (
            cover_crop_for_region,
            process_cover_bytes,
        )

        mode = str(crop_mode or "").strip().lower()
        if mode not in ("right", "face", "none"):
            # 从目录名推断分区（…/日本有码/厂牌/番号）
            mode = "right"
            try:
                from app.core.region_meta import REGION_META

                parts = {str(p) for p in folder.parts}
                for rid, meta in REGION_META.items():
                    label = str(meta.get("label") or "")
                    if label and label in parts:
                        mode = cover_crop_for_region(rid)
                        break
            except Exception:  # noqa: BLE001
                mode = "right"
        data = process_cover_bytes(
            data, crop_mode=mode, quality="compact", crop_ratio="full"
        )
    except Exception:  # noqa: BLE001
        pass

    dest = _write_poster_jpg(folder, data)
    if not dest:
        return ""
    # 番号目录只留一张封面
    for name in ("thumb.jpg", "fanart.jpg", "landscape.jpg", "cover.jpg"):
        extra = folder / name
        try:
            if extra.is_file():
                rel_extra = _media_rel(extra, media_root=media_root)
                extra.unlink(missing_ok=True)
                if rel_extra:
                    _blank_cover_cache.pop(rel_extra, None)
        except OSError:
            pass
    return _media_rel(dest, media_root=media_root)


def _update_item_poster_path(item_id: str, poster_path: str) -> None:
    if not item_id or not poster_path:
        return
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {_embed.TABLE}
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
    _embed.ensure_schema()
    iid = str(item_id or "").strip()
    rel = str(rel_path or "").strip().replace("\\", "/")
    url = str(cover_url or "").strip()
    if iid and (not rel or not url):
        pool = get_meta_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT item_id, rel_path, poster_path, cover_url
                FROM {_embed.TABLE}
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
                "posterApi": _embed.local_file_api(existing),
            }

    if not rel or not _is_http_url(url):
        return {"ok": False, "reason": "no_cover"}

    # 禁止再往扁平 FC2/{CODE} 落盘；顺带把库里的旧 rel 纠正到三层
    canon = canonical_fc2_scrap_rel(rel)
    if canon and canon != rel.replace("\\", "/").strip("/"):
        rel = canon
        if iid:
            try:
                pool = get_meta_pool()
                with pool.connection() as conn, conn.cursor() as cur:
                    cur.execute(
                        f"""
                        UPDATE {_embed.TABLE}
                        SET rel_path = %s, updated_at = now()
                        WHERE item_id = %s
                          AND (rel_path IS DISTINCT FROM %s)
                        """,
                        (rel, iid, rel),
                    )
                    conn.commit()
            except Exception:  # noqa: BLE001
                pass

    root = _embed.resolve_root(_embed.get_settings().get("root"))
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
        "posterApi": _embed.local_file_api(poster),
    }


def ensure_local_poster_by_cover(*, cover_url: str) -> dict[str, Any]:
    """按 cover 外链定位条目并落到本地 poster.jpg。"""
    url = str(cover_url or "").strip()
    if not _is_http_url(url):
        return {"ok": False, "reason": "no_cover"}
    _embed.ensure_schema()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        # 优先缺本地海报的条目
        cur.execute(
            f"""
            SELECT item_id
            FROM {_embed.TABLE}
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
    assert _embed._poster_dl_q is not None
    while True:
        item_id, rel_path, cover_url = _embed._poster_dl_q.get()
        try:
            ensure_local_poster(
                item_id=item_id, rel_path=rel_path, cover_url=cover_url
            )
        except Exception as e:  # noqa: BLE001
            log.debug("poster dl worker: %s", e)
            _trim_poster_dl_fails()
            _poster_dl_fail_until[item_id] = time.time() + 600
        finally:
            with _poster_dl_lock:
                _poster_dl_inflight.discard(item_id)
            _embed._poster_dl_q.task_done()


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
        if until:
            # 冷却已过期：顺手清掉，避免这张表只增不减
            _poster_dl_fail_until.pop(iid, None)
        if iid in _poster_dl_inflight:
            return False
        _poster_dl_inflight.add(iid)
    _ensure_poster_dl_pool()
    assert _embed._poster_dl_q is not None
    _embed._poster_dl_q.put((iid, rel, url))
    return True


def _sample_prefix_disk_posters(
    region: str, prefix: str, *, limit: int = 8
) -> list[str]:
    """前缀夹下取样本地海报路径（相对 media 根），供厂牌墙封面。"""
    pref = str(prefix or "").strip()
    if not pref or limit <= 0:
        return []
    try:
        root = _embed.resolve_root(_embed.get_settings().get("root")).resolve()
    except Exception:  # noqa: BLE001
        return []
    media_root = media_dir().resolve()
    try:
        scrap_rel = root.relative_to(media_root).as_posix()
    except ValueError:
        scrap_rel = ""

    from app.core.region_meta import fc2_fs_prefix

    rid = str(region or "").strip()
    bases: list[Path] = []
    for name in _embed._region_match_values(rid) or [rid]:
        region_dir = root / str(name)
        if not region_dir.is_dir():
            continue
        if rid == "fc2" or str(name).upper() == "FC2":
            bases.append(region_dir / fc2_fs_prefix(pref))
            # 兼容旧夹名
            if fc2_fs_prefix(pref) == "FC2-PPV":
                bases.append(region_dir / "FC2PPV")
        else:
            bases.append(region_dir / pref)

    out: list[str] = []
    seen: set[str] = set()
    for base in bases:
        if not base.is_dir():
            continue
        try:
            kids = list(base.iterdir())
        except Exception:  # noqa: BLE001
            continue
        for folder in kids:
            if not folder.is_dir():
                continue
            poster = folder / "poster.jpg"
            if not poster.is_file():
                # 偶发其它后缀
                hit = next(
                    (
                        p
                        for p in folder.iterdir()
                        if p.is_file()
                        and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                        and "poster" in p.stem.lower()
                    ),
                    None,
                )
                if hit is None:
                    continue
                poster = hit
            try:
                rel = poster.resolve().relative_to(media_root).as_posix()
            except ValueError:
                if scrap_rel:
                    try:
                        rel = (
                            f"{scrap_rel}/"
                            f"{poster.resolve().relative_to(root).as_posix()}"
                        )
                    except ValueError:
                        continue
                else:
                    continue
            if rel in seen:
                continue
            seen.add(rel)
            out.append(rel)
            if len(out) >= limit:
                return out
    return out
