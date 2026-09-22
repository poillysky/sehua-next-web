# -*- coding: utf-8 -*-
"""enrich_cover —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from fastapi import HTTPException
import app.scrap_library.embed as embed_svc
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import get_meta_pool, media_dir
from app.scrap_library import enrich_log_sink
from app.scrap_library.nfo import (
    build_mdcx_nfo_root,
    fields_from_movie_root,
    format_nfo_xml,
    parse_nfo,
    write_nfo,
)
from app.scrap_library import enrich_monitor as enrich_mon

import app.scrap_library.enrich as _enrich
import app.scrap_library.enrich_detail as _enrich_detail
import app.scrap_library.enrich_merge as _enrich_merge
from app.scrap_library.enrich import (_COVER_FAIL_LABEL, _COVER_JOB_WORKERS_MAX, _COVER_JOB_WORKERS_MIN, _ITEM_WORKERS_DEFAULT, _ITEM_WORKERS_MAX, _cover_job_slot, _enrich_job, _enrich_lock, _get_cover_job_pool, _poster_ok_cache)


def _cover_fail_message(cover_fail: str) -> str:
    cf = str(cover_fail or "").strip()
    if not cf:
        return "封面空图或下载失败"
    return f"封面失败:{_COVER_FAIL_LABEL.get(cf, cf)}"


def _poster_rank(url: str) -> int:
    """封面 URL 质量：官网竖图 > aws；避免 DMM 横封挤掉 MGStage pf_e。"""
    u = str(url or "").strip().lower()
    if not u.startswith(("http://", "https://")):
        return 0
    if "javbus.com" in u or "seejav." in u:
        return 0
    # MGStage / Prestige 官网竖海报（MDCX: pf_e）；高于 DMM 横封 pl
    if "image.mgstage.com" in u or "mgstage.com" in u:
        if "pf_e_" in u or "/pf_" in u:
            return 12
        if "pb_e_" in u or "/pb_" in u:
            return 7  # 横封，可裁但次于 pf_e
        return 6
    # 对齐 MDCX：pics.dmm → awsimgsrc/pics_dig；但 aws 常 404，mono 才是实体封
    if "awsimgsrc.dmm." in u and "/pics_dig/" in u:
        if "ps.jpg" in u:
            return 9
        if "pl.jpg" in u:
            return 8
        return 7
    if "dmm.co.jp" in u:
        # mono 实体碟封：高于易 NOW PRINTING 的 digital、易 404 的 aws
        if "/mono/movie/" in u and "pl.jpg" in u:
            return 11
        if "/mono/movie/" in u and "ps.jpg" in u:
            return 6
        if "/pics_dig/" in u:
            return 8
        if "/digital/video/" in u and "pl.jpg" in u:
            return 3  # 常空白占位，靠后
        if "/digital/video/" in u and "ps.jpg" in u:
            return 2
        return 5
    if "jdbstatic.com/covers" in u:
        return 4
    if "airav.io" in u or "fourhoi.com" in u or "123av.me" in u:
        return 1
    if u.endswith("pl.jpg") or "_b.jpg" in u or "bigImage" in u:
        return 3
    if "/cover" in u:
        return 2
    if "/digital/video/" in u:
        return 1
    return 2


def _dmm_poster_fallbacks(url: str) -> list[str]:
    """DMM 封面候选：aws pics_dig + digital + mono（Prestige 等好图常在 mono）。"""
    u = str(url or "").strip()
    out: list[str] = []
    cids: list[str] = []

    m_dig = re.search(
        r"(?:pics\.dmm\.co\.jp|awsimgsrc\.dmm\.co\.jp/pics_dig)"
        r"/digital/video/([^/]+)/\1(p[sl])\.jpg",
        u,
        re.I,
    )
    if m_dig:
        cids.append(m_dig.group(1))

    m_mono = re.search(
        r"pics\.dmm\.co\.jp/mono/movie/adult/([^/]+)/\1(p[sl])\.jpg",
        u,
        re.I,
    )
    if m_mono:
        cids.append(m_mono.group(1))

    # digital cid → 常见 mono cid（436abf00278 → 118abf278）
    extra: list[str] = []
    for cid in list(cids):
        m = re.match(r"^(?:\d+)?([a-z]+)0*(\d+)$", cid.lower())
        if m:
            mono_cid = f"118{m.group(1)}{int(m.group(2))}"
            if mono_cid not in cids:
                extra.append(mono_cid)
    cids.extend(extra)

    seen: set[str] = set()
    for cid in cids:
        if not cid or cid in seen:
            continue
        seen.add(cid)
        cl = cid.lower()
        # digital 风格（abf00278）挂 mono 路径几乎都是空白占位；只给「短 cid」走 mono
        mono_ok = not re.search(r"[a-z]0{2,}\d", cl)
        if mono_ok:
            out.append(
                f"https://pics.dmm.co.jp/mono/movie/adult/{cid}/{cid}pl.jpg"
            )
            out.append(
                f"https://pics.dmm.co.jp/mono/movie/adult/{cid}/{cid}ps.jpg"
            )
        out.append(
            f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}ps.jpg"
        )
        out.append(
            f"https://awsimgsrc.dmm.co.jp/pics_dig/digital/video/{cid}/{cid}pl.jpg"
        )
        out.append(f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}pl.jpg")
        out.append(f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}ps.jpg")
    return out


def _rewrite_cover_host_mirrors(url: str) -> list[str]:
    """同源图床镜像改写（不发明新图，只换更稳的 host）。

    例：jav321 刮到的 prestige 图 → image.mgstage.com 同路径。
    """
    u = str(url or "").strip()
    if not u:
        return []
    out = [u]
    m = re.search(
        r"https?://(?:www\.)?jav321\.com/images/(prestige|nanox|doc)/"
        r"([a-z0-9]+)/(\d+)/(p[fb]_e_[^/?#]+\.jpg)",
        u,
        re.I,
    )
    if m:
        out.append(
            f"https://image.mgstage.com/images/{m.group(1).lower()}/"
            f"{m.group(2).lower()}/{m.group(3)}/{m.group(4)}"
        )
    return list(dict.fromkeys(out))


def _normalize_cover_entries(cover_url: Any) -> list[dict[str, str]]:
    """统一为 [{source, url}, ...]。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(url: str, source: str = "") -> None:
        u = str(url or "").strip()
        if not u.startswith(("http://", "https://")):
            return
        if u in seen:
            return
        seen.add(u)
        out.append({"source": str(source or "").strip(), "url": u})

    if isinstance(cover_url, dict):
        _add(str(cover_url.get("url") or ""), str(cover_url.get("source") or ""))
        return out
    if isinstance(cover_url, str):
        _add(cover_url)
        return out
    if not isinstance(cover_url, list):
        return out
    for item in cover_url:
        if isinstance(item, dict):
            _add(
                str(item.get("url") or ""),
                str(item.get("source") or item.get("sid") or ""),
            )
        else:
            _add(str(item or ""))
    return out


def _cover_job_workers_target() -> int:
    """封面 job 并发：跟随番号并发，至少 8、至多 16。

    番号 5 → 封面 10；番号 8 → 12；番号 16 → 16。
    避免「元数据工人全卡在封面排队」；也不盲目开太大打爆 CDN。
    """
    iw = int(_ITEM_WORKERS_DEFAULT)
    try:
        from app.scrap_library.enrich_strategy import get_strategy

        iw = max(
            1,
            min(
                int(_ITEM_WORKERS_MAX),
                int(get_strategy().get("itemWorkers") or _ITEM_WORKERS_DEFAULT),
            ),
        )
    except Exception:  # noqa: BLE001
        pass
    # 番号 5 → 封面 10；番号 8 → 16；再夹在 [MIN, MAX]
    want = max(iw * 2, iw + 4)
    raw = max(int(_COVER_JOB_WORKERS_MIN), min(int(_COVER_JOB_WORKERS_MAX), want))
    from app.core.container_budget import cap_parallel

    return cap_parallel(raw, tight=2, small=4, hard=int(_COVER_JOB_WORKERS_MAX))


def _download_covers(
    folder: Path,
    cover_url: str | list[Any],
    *,
    region: str = "",
    overwrite: bool = False,
    cover_cfg: dict | None = None,
    code: str = "",
    item_id: str = "",
) -> dict[str, Any]:
    """最终版封面下载：字段优先 → URL 升级 → 并发打分早停 → 分区裁切落盘。

    经独立 cover-job 池调度，与番号元数据 itemWorkers 解耦。
    """
    from app.scrap_library.cover_download import download_best_cover
    from app.scrap_library.cover_scrape import normalize_cover_settings
    from app.scrap_library.enrich_strategy import get_strategy

    # code / item_id 用于封面下载心跳（监控）
    code_u = str(code or "").strip().upper()
    item_id_s = str(item_id or "").strip()
    batch_mode = False
    with _enrich_lock:
        batch_mode = bool(_enrich_job.get("running"))

    cfg = normalize_cover_settings(
        cover_cfg
        if cover_cfg is not None
        else (get_strategy().get("cover") or {})
    )
    entries = _normalize_cover_entries(cover_url)
    field_priority = list(_enrich_merge._strategy_field_priority("poster", region=region) or [])
    region_sources = list(_enrich_merge._strategy_region_sources(region, code=code_u) or [])

    def _log(msg: str) -> None:
        _enrich._push_log(msg, region=region)

    def _beat() -> None:
        try:
            from app.scrap_library import enrich_monitor as enrich_mon

            enrich_mon.touch_beat(code=code_u, item_id=item_id_s, note="cover")
        except Exception:  # noqa: BLE001
            pass

    def _run() -> dict[str, Any]:
        return download_best_cover(
            folder,
            entries,
            region=region,
            overwrite=overwrite,
            batch_mode=batch_mode,
            field_priority=field_priority,
            region_sources=region_sources,
            cover_cfg=cfg,
            log_fn=_log,
            beat_fn=_beat,
        )

    # 批量：走封面专用池 + 动态闸门；单刷：直接跑，避免池排队拖尾
    if batch_mode:
        with _cover_job_slot():
            return _get_cover_job_pool().submit(_run).result()
    return _run()


def _purge_extra_cover_files(folder: Path) -> None:
    """番号目录只留 poster.jpg，删掉 thumb/fanart 等多余封面。"""
    for name in ("thumb.jpg", "fanart.jpg", "landscape.jpg", "cover.jpg"):
        path = folder / name
        try:
            if path.is_file():
                rel = embed_svc._media_rel(path)  # noqa: SLF001
                path.unlink(missing_ok=True)
                if rel:
                    embed_svc._blank_cover_cache.pop(rel, None)  # noqa: SLF001
        except OSError:
            pass


def _local_poster_ok(folder: Path) -> bool:
    """海报真实存在、非空白、尺寸过线（防假成功）。"""
    poster_file = folder / "poster.jpg"
    try:
        st = poster_file.stat()
    except OSError:
        return False
    if not _stat_is_file(st):
        return False
    ck = (
        str(poster_file),
        int(getattr(st, "st_mtime_ns", 0) or 0),
        int(getattr(st, "st_size", 0) or 0),
    )
    hit = _poster_ok_cache.get(ck)
    if hit is not None:
        return bool(hit)
    ok = _local_poster_ok_uncached(poster_file, int(getattr(st, "st_size", 0) or 0))
    if len(_poster_ok_cache) > 20_000:
        _poster_ok_cache.clear()
    _poster_ok_cache[ck] = bool(ok)
    return bool(ok)


def _stat_is_file(st: Any) -> bool:
    import stat as _stat

    return bool(_stat.S_ISREG(int(getattr(st, "st_mode", 0) or 0)))


def _local_poster_ok_uncached(poster_file: Path, size: int) -> bool:
    if int(size or 0) < 1024:
        return False
    try:
        if embed_svc._is_blank_cover_file(poster_file):
            return False
    except Exception:  # noqa: BLE001
        return False
    try:
        from PIL import Image

        with Image.open(poster_file) as im:
            w, h = int(im.size[0] or 0), int(im.size[1] or 0)
        # 与 cover_download.meets_processed_min_size 对齐：有有效像素即合格
        from app.scrap_library.cover_download import meets_processed_min_size

        if not meets_processed_min_size(w, h):
            return False
    except Exception:  # noqa: BLE001
        return False
    return True


def _local_success_disk_ok(folder: Path) -> bool:
    """成功落库前强校验：目录 + NFO + 合格 poster.jpg。"""
    if not folder.is_dir():
        return False
    if not _enrich_detail._find_nfo(folder):
        return False
    return _local_poster_ok(folder)


_LOCAL_COVER_FILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("poster", ("poster.jpg", "poster.jpeg", "poster.png", "poster.webp")),
    ("thumb", ("thumb.jpg", "thumb.jpeg", "thumb.png", "thumb.webp")),
    ("fanart", ("fanart.jpg", "fanart.jpeg", "fanart.png", "fanart.webp")),
)


def list_local_covers(
    *,
    region: str = "",
    code: str = "",
    item_id: str = "",
) -> dict[str, Any]:
    """检查用：只返回番号目录里已落盘的本地图。"""
    folder = _enrich_detail._resolve_enrich_folder(region=region, code=code, item_id=item_id)
    empty = {
        "ok": False,
        "folder": "",
        "posterApi": "",
        "thumbApi": "",
        "fanartApi": "",
        "files": [],
    }
    if folder is None:
        return empty
    try:
        media_root = media_dir().resolve()
        folder_rel = folder.relative_to(media_root).as_posix()
    except ValueError:
        folder_rel = folder.name
    files: list[dict[str, Any]] = []
    apis: dict[str, str] = {}
    for kind, names in _LOCAL_COVER_FILES:
        for name in names:
            path = folder / name
            if not path.is_file():
                continue
            try:
                if embed_svc._is_blank_cover_file(path):  # noqa: SLF001
                    continue
            except Exception:  # noqa: BLE001
                pass
            try:
                rel = embed_svc._media_rel(path)  # noqa: SLF001
            except Exception:  # noqa: BLE001
                rel = f"{folder_rel}/{name}".replace("\\", "/")
            api = embed_svc.local_file_api(rel)
            if not api:
                continue
            mtime = 0
            try:
                mtime = int(path.stat().st_mtime)
            except OSError:
                pass
            files.append(
                {
                    "kind": kind,
                    "name": name,
                    "posterApi": api,
                    "mtime": mtime,
                }
            )
            if kind not in apis:
                apis[kind] = api
            break
    return {
        "ok": bool(files),
        "folder": folder_rel,
        "posterApi": apis.get("poster") or "",
        "thumbApi": apis.get("thumb") or "",
        "fanartApi": apis.get("fanart") or "",
        "files": files,
    }


def _purge_blank_covers(folder: Path) -> None:
    """删掉源站 NOW PRINTING 一类空图，避免库里挂着无效 poster。"""
    for name in ("poster.jpg", "thumb.jpg", "fanart.jpg"):
        path = folder / name
        try:
            if path.is_file() and embed_svc._is_blank_cover_file(path):
                rel = embed_svc._media_rel(path)  # noqa: SLF001
                path.unlink(missing_ok=True)
                if rel:
                    embed_svc._blank_cover_cache.pop(rel, None)  # noqa: SLF001
        except OSError:
            pass
