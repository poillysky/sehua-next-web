"""批量重压已落盘 poster.jpg：只改体积，不改构图。"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("scrap_library.poster_recompress")

_lock = threading.Lock()
_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "startedAt": 0.0,
    "finishedAt": 0.0,
    "progress": {
        "done": 0,
        "total": 0,
        "ok": 0,
        "skip": 0,
        "fail": 0,
        "savedBytes": 0,
        "percent": 0,
    },
    "result": None,
    "error": "",
    "dryRun": False,
    "quality": "compact",
}


def get_status() -> dict[str, Any]:
    with _lock:
        return {
            "running": bool(_job["running"]),
            "phase": str(_job.get("phase") or ""),
            "startedAt": float(_job.get("startedAt") or 0),
            "finishedAt": float(_job.get("finishedAt") or 0),
            "progress": dict(_job.get("progress") or {}),
            "result": _job.get("result"),
            "error": str(_job.get("error") or ""),
            "dryRun": bool(_job.get("dryRun")),
            "quality": str(_job.get("quality") or "compact"),
        }


def _list_poster_rows(*, region: str = "", limit: int = 0) -> list[dict[str, Any]]:
    from app.core.db import get_meta_pool
    from app.scrap_library import embed as embed_svc

    embed_svc.ensure_schema()
    region_sql, params = embed_svc._quality_region_sql(region)  # noqa: SLF001
    pool = get_meta_pool()
    lim = max(0, int(limit or 0))
    sql_limit = "" if lim <= 0 else " LIMIT %s"
    sql_params: list[Any] = [*params]
    if lim > 0:
        sql_params.append(min(20_000, lim))
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, region, code, poster_path
            FROM {embed_svc.TABLE}
            WHERE coalesce(poster_path, '') <> ''{region_sql}
            ORDER BY updated_at DESC
            {sql_limit}
            """,
            sql_params,
        )
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for r in rows:
        d = r if isinstance(r, dict) else {}
        iid = str(d.get("item_id") or "").strip()
        rel = str(d.get("poster_path") or "").strip()
        if not iid or not rel:
            continue
        out.append(
            {
                "itemId": iid,
                "region": str(d.get("region") or ""),
                "code": str(d.get("code") or ""),
                "posterPath": rel,
            }
        )
    return out


def _recompress_one(
    rel: str,
    *,
    quality: str,
    dry_run: bool,
    min_save_ratio: float = 0.02,
) -> dict[str, Any]:
    from app.scrap_library.cover_scrape import process_cover_bytes
    from app.scrap_library.embed import resolve_local_file

    q = "compact"
    path = resolve_local_file(rel)
    before = path.stat().st_size
    if before < 1024:
        return {"ok": False, "skip": True, "reason": "too_small", "before": before}
    raw = path.read_bytes()
    # 不改构图：crop_mode=none
    out = process_cover_bytes(raw, crop_mode="none", quality=q, crop_ratio="full")
    after = len(out) if out else 0
    if after < 1024:
        return {"ok": False, "skip": True, "reason": "encode_fail", "before": before}
    saved = before - after
    # 体积几乎不降则跳过，避免无意义覆写
    if saved < max(512, int(before * min_save_ratio)):
        return {
            "ok": True,
            "skip": True,
            "reason": "no_gain",
            "before": before,
            "after": after,
            "saved": 0,
        }
    if dry_run:
        return {
            "ok": True,
            "skip": False,
            "dryRun": True,
            "before": before,
            "after": after,
            "saved": saved,
        }
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        tmp.write_bytes(out)
        tmp.replace(path)
    except OSError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return {"ok": False, "skip": False, "reason": str(e), "before": before}
    return {
        "ok": True,
        "skip": False,
        "before": before,
        "after": after,
        "saved": saved,
    }


def _run(
    *,
    region: str,
    quality: str,
    limit: int,
    dry_run: bool,
) -> None:
    q = "compact"
    try:
        rows = _list_poster_rows(region=region, limit=limit)
        total = len(rows)
        with _lock:
            _job["phase"] = "recompress"
            _job["progress"] = {
                "done": 0,
                "total": total,
                "ok": 0,
                "skip": 0,
                "fail": 0,
                "savedBytes": 0,
                "percent": 0,
            }
        ok = skip = fail = saved_bytes = 0
        for i, row in enumerate(rows):
            with _lock:
                if not _job["running"]:
                    break
            try:
                r = _recompress_one(
                    str(row["posterPath"]),
                    quality=q,
                    dry_run=dry_run,
                )
                if r.get("ok") and not r.get("skip"):
                    ok += 1
                    saved_bytes += int(r.get("saved") or 0)
                elif r.get("skip"):
                    skip += 1
                else:
                    fail += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.debug("recompress fail %s: %s", row.get("itemId"), e)
            done = i + 1
            with _lock:
                _job["progress"] = {
                    "done": done,
                    "total": total,
                    "ok": ok,
                    "skip": skip,
                    "fail": fail,
                    "savedBytes": saved_bytes,
                    "percent": int(done * 100 / total) if total else 100,
                }
        result = {
            "ok": True,
            "dryRun": dry_run,
            "quality": q,
            "total": total,
            "rewritten": ok,
            "skipped": skip,
            "failed": fail,
            "savedBytes": saved_bytes,
        }
        with _lock:
            _job["result"] = result
            _job["phase"] = "done"
            _job["error"] = ""
    except Exception as e:  # noqa: BLE001
        log.exception("poster recompress failed")
        with _lock:
            _job["error"] = str(e)
            _job["phase"] = "error"
            _job["result"] = {"ok": False, "error": str(e)}
    finally:
        with _lock:
            _job["running"] = False
            _job["finishedAt"] = time.time()


def start_job(
    *,
    region: str = "",
    quality: str = "",
    limit: int = 0,
    dry_run: bool = False,
) -> dict[str, Any]:
    import app.scrap_library.enrich_strategy as strat

    cfg = strat.get_strategy()
    cover = cfg.get("cover") if isinstance(cfg.get("cover"), dict) else {}
    q = "compact"

    with _lock:
        if _job["running"]:
            raise RuntimeError("海报重压已在运行")
        _job.update(
            {
                "running": True,
                "phase": "starting",
                "startedAt": time.time(),
                "finishedAt": 0.0,
                "progress": {
                    "done": 0,
                    "total": 0,
                    "ok": 0,
                    "skip": 0,
                    "fail": 0,
                    "savedBytes": 0,
                    "percent": 0,
                },
                "result": None,
                "error": "",
                "dryRun": bool(dry_run),
                "quality": q,
            }
        )

    threading.Thread(
        target=_run,
        kwargs={
            "region": str(region or "").strip(),
            "quality": q,
            "limit": int(limit or 0),
            "dry_run": bool(dry_run),
        },
        name="scrap-poster-recompress",
        daemon=True,
    ).start()
    return get_status()
