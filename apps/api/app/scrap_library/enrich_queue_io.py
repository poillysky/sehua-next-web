# -*- coding: utf-8 -*-
"""Queue log I/O, pending iterators, and in-memory queue mutators for enrich."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

import app.scrap_library.embed as embed_svc
from app.core.db import get_meta_pool, media_dir
from app.scrap_library import enrich_log_sink
from app.scrap_library.enrich_runtime import (
    _QUEUE_SCAN_STATE,
    _enrich_job,
    _enrich_lock,
    _set_progress,
    notify_enrich_watchers,
)

import app.scrap_library.enrich as _enrich

log = logging.getLogger(__name__)


def _write_enrich_log_batch(rows: list[tuple[str, str]]) -> None:
    """**一次事务**写多行日志 + 每个 region 只裁剪一次。

    第九轮：原实现一行一次事务（552 ms/番号，13 行），实测同样 20 行
    504 ms（各自事务）→ 74 ms（一个事务 + 一次裁剪）。裁剪 SQL 语义与原来
    逐行版一致（保留该 region 最新 `_enrich._ENRICH_LOG_KEEP` 行）。
    """
    from app.core.db import connect, init_db

    init_db()
    with connect() as conn:
        for rid, line in rows:
            conn.execute(
                "INSERT INTO enrich_logs (region, line) VALUES (?, ?)",
                (rid, line[:2000]),
            )
        for rid in {r for r, _ in rows}:
            conn.execute(
                """
                DELETE FROM enrich_logs
                WHERE region = ?
                  AND id < COALESCE(
                    (
                      SELECT id FROM enrich_logs
                      WHERE region = ?
                      ORDER BY id DESC
                      LIMIT 1 OFFSET ?
                    ),
                    0
                  )
                """,
                (rid, rid, max(0, _enrich._ENRICH_LOG_KEEP - 1)),
            )
        conn.commit()


_enrich_log_sink = enrich_log_sink.LogBatcher(
    _write_enrich_log_batch, flush_sec=0.25, max_delay=3.0, min_rows=24, label="enrich_log"
)


_hist_log_cache: dict[tuple[str, int], tuple[float, list[str]]] = {}


def _push_log(msg: str, *, region: str | None = None) -> None:
    text = str(msg)
    rid = ""
    with _enrich._enrich_lock:
        # 停止后不再写日志，避免清完又被当前番号灌回
        if _enrich._enrich_job.get("halt") == "stop":
            return
        log_list = list(_enrich._enrich_job.get("log") or [])
        log_list.append(text)
        _enrich._enrich_job["log"] = log_list[-80:]
        raw = str(region or _enrich._enrich_job.get("currentRegion") or "").strip()
        rid = _enrich._canonical_enrich_log_region(raw) if raw else "_all"
        if rid and rid != "_all":
            region_logs = dict(_enrich._enrich_job.get("regionLogs") or {})
            bucket = list(region_logs.get(rid) or [])
            bucket.append(text)
            region_logs[rid] = bucket[-_enrich._ENRICH_LOG_MEMORY:]
            _enrich._enrich_job["regionLogs"] = region_logs
    _enrich._persist_enrich_log(rid or "_all", text)
    _enrich.notify_enrich_watchers()


def _queue_log_region(region: str | None = None) -> str:
    rid = _enrich._canonical_enrich_log_region(region or "")
    return "" if rid == "_all" else rid


_counts_cache: dict[str, tuple[float, dict[str, int]]] = {}


_COUNTS_CACHE_TTL_SEC = 1.2


_counts_ok_cache: dict[str, tuple[float, bool]] = {}


_scrape_counts_cache: dict[str, tuple[float, dict[str, int]]] = {}


_LOCAL_STATUS_TOTALS: dict[str, dict[str, int]] = {}


_LOCAL_STATUS_TOTALS_LOADED = False


_LOCAL_STATUS_TOTALS_LOCK = threading.Lock()


def _local_status_totals_path() -> Path:
    return _enrich.media_dir() / "scrap-library" / "_local_status_totals.json"


def _ensure_local_status_totals_loaded() -> None:
    """加载 tip 落盘。loaded 旗标以 `enrich` 门面为准（测试会改 E._LOCAL_STATUS_TOTALS_LOADED）。"""
    global _LOCAL_STATUS_TOTALS_LOADED
    if bool(getattr(_enrich, "_LOCAL_STATUS_TOTALS_LOADED", _LOCAL_STATUS_TOTALS_LOADED)):
        _LOCAL_STATUS_TOTALS_LOADED = True
        return
    with _LOCAL_STATUS_TOTALS_LOCK:
        if bool(getattr(_enrich, "_LOCAL_STATUS_TOTALS_LOADED", _LOCAL_STATUS_TOTALS_LOADED)):
            _LOCAL_STATUS_TOTALS_LOADED = True
            return
        _LOCAL_STATUS_TOTALS_LOADED = True
        _enrich._LOCAL_STATUS_TOTALS_LOADED = True
        path = _enrich._local_status_totals_path()
        if not path.is_file():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            regions = (raw or {}).get("regions") if isinstance(raw, dict) else None
            if not isinstance(regions, dict):
                return
            for rid, tip in regions.items():
                key = _queue_log_region(str(rid or ""))
                if not key or not isinstance(tip, dict):
                    continue
                _LOCAL_STATUS_TOTALS[key] = {
                    "done": max(0, int(tip.get("done") or 0)),
                    "soft": max(0, int(tip.get("soft") or 0)),
                    "fail": max(0, int(tip.get("fail") or 0)),
                    **(
                        {"total": max(0, int(tip.get("total") or 0))}
                        if int(tip.get("total") or 0) > 0
                        else {}
                    ),
                }
        except Exception as e:  # noqa: BLE001
            log.debug("load local status totals failed: %s", e)


def _lift_local_status_totals_from_counts(
    region: str, counts: dict[str, int] | None
) -> None:
    """刮削推进后把扫描角标抬到至少不低于库内真实值。"""
    rid = _queue_log_region(region)
    if not rid or not isinstance(counts, dict):
        return
    _ensure_local_status_totals_loaded()
    tip = _LOCAL_STATUS_TOTALS.get(rid)
    if not tip:
        return
    done = max(int(tip.get("done") or 0), int(counts.get("done") or 0))
    soft = int(counts.get("soft") if "soft" in counts else tip.get("soft") or 0)
    fail = int(counts.get("fail") if "fail" in counts else tip.get("fail") or 0)
    tot = int(tip.get("total") or 0)
    if (
        done == int(tip.get("done") or 0)
        and soft == int(tip.get("soft") or 0)
        and fail == int(tip.get("fail") or 0)
    ):
        return
    _enrich._set_local_status_totals(rid, done=done, soft=soft, fail=fail, total=tot or None)


def _hydrate_queue_item_from_library(
    *,
    code: str = "",
    region: str = "",
    item_id: str = "",
) -> dict[str, Any]:
    """从元库/NFO 回填成功条目详情（恢复空壳 done 时用）。

    无向量行时仍读本地 NFO（转移入库的番号常见）。
    """
    code_u = str(code or "").strip().upper()
    iid = str(item_id or "").strip()
    rid = _queue_log_region(region)
    out: dict[str, Any] = {}
    if not code_u and not iid:
        return out

    folder: Path | None = None
    d: dict[str, Any] = {}
    try:
        embed_svc.ensure_schema()
        pool = _enrich.get_meta_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            if iid:
                cur.execute(
                    f"""
                    SELECT item_id, region, prefix, code, title, rel_path,
                           poster_path, thumb_path, cover_url, source_text
                    FROM {embed_svc.TABLE}
                    WHERE item_id = %s
                    LIMIT 1
                    """,
                    (iid,),
                )
            else:
                cur.execute(
                    f"""
                    SELECT item_id, region, prefix, code, title, rel_path,
                           poster_path, thumb_path, cover_url, source_text
                    FROM {embed_svc.TABLE}
                    WHERE UPPER(code) = %s
                    ORDER BY CASE WHEN region = %s THEN 0 ELSE 1 END, updated_at DESC NULLS LAST
                    LIMIT 1
                    """,
                    (code_u, rid or ""),
                )
            row = cur.fetchone()
            if row:
                d = dict(row) if isinstance(row, dict) else {}
    except Exception as e:  # noqa: BLE001
        log.debug(
            "hydrate library lookup failed code=%s item=%s: %s",
            code_u,
            iid,
            e,
        )
        d = {}

    if d:
        out["itemId"] = str(d.get("item_id") or iid or "")
        out["code"] = str(d.get("code") or code_u).strip().upper() or code_u
        title = str(d.get("title") or "").strip()
        if title:
            out["detailTitle"] = title[:300]
        poster_ok = bool(
            str(d.get("poster_path") or "").strip()
            or str(d.get("thumb_path") or "").strip()
            or str(d.get("cover_url") or "").startswith(("http://", "https://"))
        )
        out["posterDownloaded"] = poster_ok
        out["vectorSynced"] = True
        code_u = out["code"] or code_u
        rel = str(d.get("rel_path") or "").replace("\\", "/").strip().strip("/")
        if rel:
            try:
                settings = embed_svc.get_settings()
                root = embed_svc.resolve_root(settings.get("root"))
                cand = (root / rel).resolve()
                try:
                    cand.relative_to(root.resolve())
                except ValueError:
                    cand = None  # type: ignore[assignment]
                if cand is not None and cand.is_dir():
                    folder = cand
            except Exception:  # noqa: BLE001
                folder = None

    if folder is None:
        folder = _enrich._resolve_enrich_folder(
            region=rid or region,
            code=code_u,
            item_id=iid,
        )

    if folder is not None:
        local_detail, fields, local_ok = _enrich._detail_from_local_folder(
            folder, code=code_u or folder.name
        )
        if local_detail.get("detailTitle"):
            out["detailTitle"] = local_detail["detailTitle"]
        if local_detail.get("code"):
            out["code"] = str(local_detail["code"]).strip().upper()
        if local_ok:
            out["posterDownloaded"] = True
        out["fields"] = fields
        if not out.get("itemId"):
            try:
                settings = embed_svc.get_settings()
                root = embed_svc.resolve_root(settings.get("root")).resolve()
                out["itemId"] = folder.relative_to(root).as_posix()
            except Exception:  # noqa: BLE001
                out["itemId"] = iid or code_u
        return out

    # 无本地目录：仅用向量行拼最小字段表
    if not d:
        return out
    detail: dict[str, Any] = {
        "code": out.get("code") or code_u,
        "title": str(out.get("detailTitle") or d.get("title") or "").strip(),
        "posterUrl": str(d.get("cover_url") or "").strip(),
    }
    src_text = str(d.get("source_text") or "")
    if src_text and not detail.get("actors"):
        def _pick(re_pat: str) -> str:
            m = re.search(re_pat, src_text, re.M)
            return (m.group(1) if m else "").strip()

        if not detail.get("title"):
            detail["title"] = _pick(r"^标题：(.+)$")
        actors_line = _pick(r"^女优：(.+)$")
        if actors_line:
            detail["actors"] = [
                a.strip() for a in re.split(r"[、,/|]", actors_line) if a.strip()
            ]
        detail["studio"] = detail.get("studio") or _pick(r"^片商：(.+)$")
        detail["overview"] = detail.get("overview") or _pick(r"^剧情：(.+)$")
    fields = _enrich._detail_field_rows(detail)
    if out.get("posterDownloaded"):
        for f in fields:
            if str(f.get("id") or "") == "poster":
                f["ok"] = True
                f["value"] = "已落盘"
    out["fields"] = fields
    out["source"] = ""
    return out


def _queue_log_insert_many(region: str, rows: list[dict[str, Any]]) -> list[int]:
    if not rows:
        return []
    rid = _queue_log_region(region)
    if not rid:
        return [0] * len(rows)
    ids: list[int] = []
    cols = (
        "(region, item_id, code, status, gaps_json, error, source, "
        "fetch_ms, detail_title, payload_json)"
    )
    one = "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    chunk_n = max(50, min(1000, int(_enrich._QUEUE_LOG_INSERT_CHUNK or 500)))
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            for start in range(0, len(rows), chunk_n):
                chunk = rows[start : start + chunk_n]
                sql = (
                    f"INSERT INTO enrich_queue_log {cols} VALUES "
                    + ", ".join([one] * len(chunk))
                    + " RETURNING id"
                )
                params: list[Any] = []
                for r in chunk:
                    params.extend(_enrich._queue_log_insert_params(rid, r))
                got = conn.execute(sql, params).fetchall()
                for g in got:
                    ids.append(int(g["id"] if isinstance(g, dict) else g[0]))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("insert enrich queue log failed region=%s: %s", rid, e)
        return [0] * len(rows)
    if len(ids) < len(rows):
        ids.extend([0] * (len(rows) - len(ids)))
    return ids[: len(rows)]


def _queue_log_update_row(row: dict[str, Any], *, region: str = "") -> int:
    lid = _enrich._queue_log_int_id(row)
    rid = _queue_log_region(region or str(row.get("region") or ""))
    code_u = str(row.get("code") or "").strip().upper()
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            target_id = lid if lid > 0 else 0
            if target_id <= 0 and rid and code_u:
                found = conn.execute(
                    """
                    SELECT id FROM enrich_queue_log
                    WHERE region=? AND code=?
                    ORDER BY
                      CASE status
                        WHEN 'running' THEN 0
                        WHEN 'pending' THEN 1
                        WHEN 'done' THEN 2
                        ELSE 3
                      END,
                      id DESC
                    LIMIT 1
                    """,
                    (rid, code_u),
                ).fetchone()
                if found:
                    target_id = int(
                        found["id"] if isinstance(found, dict) else found[0]
                    )
            payload_base = _enrich._queue_log_read_payload(conn, target_id)
            # 完成态优先保留/写入刮削结果，勿被 running 空包覆盖
            params = _enrich._queue_log_insert_params(
                rid, row, payload_base=payload_base
            )
            if target_id > 0:
                # 若库里已是 done 且带 fields，而本次只是 running/pending，勿降级清空
                st_new = str(row.get("status") or "").strip().lower()
                if st_new in {"pending", "running"} and payload_base.get("fields"):
                    existing = conn.execute(
                        "SELECT status FROM enrich_queue_log WHERE id=?",
                        (target_id,),
                    ).fetchone()
                    st_old = str(
                        (
                            existing.get("status")
                            if isinstance(existing, dict)
                            else (existing[0] if existing else "")
                        )
                        or ""
                    ).strip().lower()
                    if st_old == "done":
                        return target_id
                cur_upd = conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET item_id=?, code=?, status=?, gaps_json=?, error=?,
                        source=?, fetch_ms=?, detail_title=?, payload_json=?,
                        updated_at=NOW()
                    WHERE id=?
                    """,
                    (*params[1:], target_id),
                )
                if int(getattr(cur_upd, "rowcount", 0) or 0) <= 0:
                    # ⚠️ 目标行已不存在，两种成因都要处理：
                    #   1) 扫描删掉全部 local_scan 行后重写、裁剪窗口删旧 done
                    #      → 旧实现 UPDATE 打空 0 行后仍 `return target_id`，
                    #        日志打印 "persist ... status=done" 而列表里永远
                    #        查不到这个番号（假成功）；
                    #   2) 内存里的 logId 已过期（暂停恢复的 checkpoint、同番号
                    #      被重复入队后其 pending 行被 prune 删掉）→ 之前「打空就
                    #      INSERT」的兜底会把**一次刮削的多次落库**放大成多行
                    #      （实测同一番号 3 行、payload 完全相同、id 连续）。
                    # 所以先按 (region, code) 重查一次改 UPDATE；确实没有才 INSERT，
                    # 保证「一个番号在日志里最多一行」。
                    retry_id = 0
                    if rid and code_u:
                        found2 = conn.execute(
                            """
                            SELECT id FROM enrich_queue_log
                            WHERE region=? AND code=?
                            ORDER BY
                              CASE status
                                WHEN 'running' THEN 0
                                WHEN 'pending' THEN 1
                                WHEN 'done' THEN 2
                                ELSE 3
                              END,
                              id DESC
                            LIMIT 1
                            """,
                            (rid, code_u),
                        ).fetchone()
                        if found2:
                            retry_id = int(
                                found2["id"]
                                if isinstance(found2, dict)
                                else found2[0]
                            )
                    if retry_id > 0 and retry_id != target_id:
                        # 与上面同一条守卫：目标行已是 done 且带 fields 时，
                        # 不接受 pending/running 空包把它降级清空。
                        st_new2 = str(row.get("status") or "").strip().lower()
                        base2 = _enrich._queue_log_read_payload(conn, retry_id)
                        if st_new2 in {"pending", "running"} and base2.get("fields"):
                            ex2 = conn.execute(
                                "SELECT status FROM enrich_queue_log WHERE id=?",
                                (retry_id,),
                            ).fetchone()
                            st_old2 = str(
                                (
                                    ex2.get("status")
                                    if isinstance(ex2, dict)
                                    else (ex2[0] if ex2 else "")
                                )
                                or ""
                            ).strip().lower()
                            if st_old2 == "done":
                                return retry_id
                        params = _enrich._queue_log_insert_params(
                            rid,
                            row,
                            payload_base=base2,
                        )
                        cur_re = conn.execute(
                            """
                            UPDATE enrich_queue_log
                            SET item_id=?, code=?, status=?, gaps_json=?, error=?,
                                source=?, fetch_ms=?, detail_title=?, payload_json=?,
                                updated_at=NOW()
                            WHERE id=?
                            """,
                            (*params[1:], retry_id),
                        )
                        if int(getattr(cur_re, "rowcount", 0) or 0) > 0:
                            log.info(
                                "enrich queue log row id=%s missing; "
                                "rebound to id=%s code=%s region=%s",
                                target_id,
                                retry_id,
                                code_u,
                                rid,
                            )
                            conn.commit()
                            return retry_id
                    log.info(
                        "enrich queue log row id=%s missing (rowcount=0); "
                        "reinsert code=%s region=%s",
                        target_id,
                        code_u,
                        rid,
                    )
                    got_re = conn.execute(
                        """
                        INSERT INTO enrich_queue_log (
                          region, item_id, code, status, gaps_json, error, source,
                          fetch_ms, detail_title, payload_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        RETURNING id
                        """,
                        params,
                    ).fetchone()
                    conn.commit()
                    if not got_re:
                        return target_id
                    return int(
                        got_re["id"] if isinstance(got_re, dict) else got_re[0]
                    )
                conn.commit()
                return target_id
            got = conn.execute(
                """
                INSERT INTO enrich_queue_log (
                  region, item_id, code, status, gaps_json, error, source,
                  fetch_ms, detail_title, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                params,
            ).fetchone()
            conn.commit()
            if not got:
                return lid
            return int(got["id"] if isinstance(got, dict) else got[0])
    except Exception as e:  # noqa: BLE001
        log.warning("update enrich queue log failed id=%s: %s", lid, e)
        return lid


def iter_enrich_pending_items(
    *,
    region: str,
    limit: int = 0,
    skip_item_ids: set[str] | None = None,
    skip_codes: set[str] | None = None,
    local_maps: _enrich._LocalNfoMaps | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """未处理 = 向量库所有番号 − 本地成功 − 软成功 − 失败。

    含「向量已齐但本地已删」：二次入队后重刮并覆盖向量行。
    limit>0（扫描）：只取样例；角标用向量 total 扣本地已分类。
    limit<=0（开刮）：枚举可处理项。
    local_maps：可传入已扫结果，避免二次磁盘遍历。
    """
    from app.scrap_library import embed as embed_svc

    rid = _queue_log_region(region)
    lim = int(limit or 0)
    samples: list[dict[str, Any]] = []
    total = 0
    seen: set[str] = set()
    skip_iids = skip_item_ids or set()
    skip_cs = {str(c).strip().upper() for c in (skip_codes or set()) if str(c).strip()}
    maps = local_maps if isinstance(local_maps, _enrich._LocalNfoMaps) else _enrich._local_nfo_gap_maps(
        region=rid or region
    )
    local_classified = maps.skip_rels
    local_codes = maps.classified_codes

    # 角标：每次以向量库最新 COUNT 为准，再扣本地已分类
    vector_total = _enrich._fresh_vector_library_total(rid or region, force=True)
    classified_n = int(maps.done_n or 0) + int(maps.soft_n or 0) + int(maps.fail_n or 0)
    pending_total = max(0, vector_total - classified_n)

    def _emit(item: dict[str, Any]) -> None:
        nonlocal total
        iid = str(item.get("itemId") or "").strip()
        if not iid or iid in seen:
            return
        code_u = str(item.get("code") or "").strip().upper()
        if iid in skip_iids or (code_u and code_u in skip_cs):
            return
        seen.add(iid)
        total += 1
        if lim <= 0 or len(samples) < lim:
            samples.append(item)

    # 全库有番号行（空壳 + 已齐）；本地已分类排除 → 本地已删也会回未处理
    # 最新变更优先，与未处理列表 / 开刮取号一致
    try:
        rows = embed_svc.list_region_code_items(
            region=rid or region,
            limit=lim if lim > 0 else 0,
            order="updated",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("list_region_code_items failed region=%s: %s", rid, e)
        rows = []

    for r in rows or []:
        if not isinstance(r, dict):
            continue
        iid = str(r.get("itemId") or "").strip()
        rel = str(r.get("relPath") or r.get("rel_path") or iid).strip().replace(
            "\\", "/"
        )
        if not iid and not rel:
            continue
        code_u = str(r.get("code") or "").strip().upper()
        # 本地已成功/软成功/失败 → 不进未处理
        if (rel and rel in local_classified) or (iid and iid in local_classified):
            continue
        if code_u and code_u in local_codes:
            continue
        gaps = list(r.get("gaps") or [])
        if not gaps:
            gaps = list(_enrich._ENRICH_KINDS)
        _emit(
            {
                "itemId": iid or rel,
                "code": code_u,
                "gaps": gaps,
                "rel_path": rel or iid,
                "relPath": rel or iid,
                "region": rid or str(r.get("region") or region),
                "status": "pending",
                "shell": bool(r.get("shell")),
            }
        )

    if lim > 0:
        return samples, max(int(pending_total), len(samples))
    return samples, max(total, int(pending_total))


def iter_enrich_pending_batches(
    *,
    region: str,
    batch_size: int = 200,
    limit: int = 0,
    skip_item_ids: set[str] | None = None,
    skip_codes: set[str] | None = None,
    defer_skip_until: threading.Event | None = None,
) -> Any:
    """分批产出未处理：向量库全部番号 − 本地成功/软成功/失败。

    含「向量已齐、本地已删」回填。不把 12 万行一次载入内存。limit<=0 表示一直扫到库空。
    队列表已有 pending 先吐（不挡开刮）；骨架/向量切片可等 ``defer_skip_until``。
    """
    from app.scrap_library import embed as embed_svc

    rid = _queue_log_region(region)
    bs = max(50, min(1_000, int(batch_size or 200)))
    cap = int(limit or 0)
    skip_iids = skip_item_ids if skip_item_ids is not None else set()
    skip_cs = skip_codes if skip_codes is not None else set()
    # 延迟扫本地 NFO：否则开刮前全盘映射会卡数分钟，处理中一直 0。
    # 队列表已有 pending（失败/软成功重试）必须立刻入队，不受本地「已分类」过滤。
    local_maps: Any = None
    local_classified: set[str] = set()
    local_codes: set[str] = set()

    def _ensure_local_maps() -> None:
        nonlocal local_maps, local_classified, local_codes
        if local_maps is not None:
            return
        cache_key = rid or region
        cached = _enrich._local_nfo_maps_cache_get(cache_key)
        if cached is not None:
            skip_set, code_set, d_n, s_n, f_n = cached
            marker = _enrich._CachedLocalMapsMarker(skip_set, code_set, d_n, s_n, f_n)
            local_maps = marker
            local_classified = skip_set
            local_codes = code_set
            _push_log(
                f"本地 NFO 分类 · 命中缓存 {len(skip_set):,} 条（免扫盘）",
                region=cache_key,
            )
            return
        # ⚠️ 这里是「开刮后到出队首条」之间最耗时的一步：有码区要读 10.9 万
        # 个本地目录、实测 4 分钟。旧实现既不开进度上报、也不写任何日志，
        # 界面在这几分钟里恒显示「队列 0 · 处理中 0」，看起来就是「启动不了」。
        # 现在：① 先明确告知正在干什么、大概多久；② 打开 report_progress 让磁盘
        # 扫描进度能通过 queueScan 上报；③ 扫完打一条含耗时的就绪日志。
        _t_map = time.monotonic()
        _push_log(
            "本地 NFO 分类 · 开始扫描（首次约 2~5 分钟，期间不产生队列；"
            "可在总览看到磁盘扫描进度）",
            region=cache_key,
        )
        _enrich._set_progress(
            stage="disk",
            label="扫描本地 NFO 分类…（首次约 2~5 分钟）",
            done=0,
            total=0,
        )
        try:
            maps = _enrich._local_nfo_gap_maps(region=cache_key, report_progress=True)
        except TypeError:
            maps = _enrich._local_nfo_gap_maps(region=cache_key)
        local_maps = maps
        local_classified = maps.skip_rels
        local_codes = maps.classified_codes
        _enrich._local_nfo_maps_cache_put(cache_key, maps)
        _push_log(
            f"本地 NFO 分类 · 就绪 {len(local_classified):,} 条"
            f"（成功 {int(getattr(maps, 'done_n', 0) or 0):,} · "
            f"软成功 {int(getattr(maps, 'soft_n', 0) or 0):,} · "
            f"失败 {int(getattr(maps, 'fail_n', 0) or 0):,}）"
            f" · 用时 {time.monotonic() - _t_map:.1f}s",
            region=cache_key,
        )

    # 「封面已放弃」的番号不再自动入队（否则每轮重抓全部源，且永远清不掉）；
    # 只抑制**仅剩封面缺口**的行 —— 同时缺剧情/女优的仍要重试。
    cover_giveup = _enrich._cover_giveup_codes(rid or region)
    # 源故障补抓：能进队列表的抬到未处理队首（与列表同序）；
    # 本地已齐、不在 pending 里的仍要显式补出，否则永远没人回头修。
    src_retry = [
        h
        for h in _enrich._retry_hint_load(rid or region, _enrich._RETRY_KIND_SRC_DOWN)
        if not h.get("giveup") and str(h.get("code") or "").strip()
    ]
    src_retry_orphan: list[dict[str, Any]] = []
    if src_retry and (rid or region):
        try:
            from app.core.db import connect, init_db

            init_db()
            bumped = 0
            with connect() as conn:
                for h in src_retry:
                    code_u = str(h.get("code") or "").strip().upper()
                    if not code_u:
                        continue
                    cur = conn.execute(
                        """
                        UPDATE enrich_queue_log
                        SET updated_at=NOW()
                        WHERE region=? AND status='pending' AND UPPER(code)=?
                        """,
                        (rid or region, code_u),
                    )
                    n = int(getattr(cur, "rowcount", 0) or 0)
                    if n > 0:
                        bumped += n
                    else:
                        src_retry_orphan.append(h)
                conn.commit()
            if bumped:
                _push_log(
                    f"源故障补抓 · {bumped} 条已抬到未处理队首",
                    region=rid or region,
                )
        except Exception as e:  # noqa: BLE001
            log.debug("bump src_retry pending failed: %s", e)
            src_retry_orphan = list(src_retry)
    elif src_retry:
        src_retry_orphan = list(src_retry)
    seen: set[str] = set()
    emitted = 0

    def _want(
        iid: str, code_u: str, gaps: Any = None, *, honor_skip_done: bool = True
    ) -> bool:
        if not iid or iid in seen:
            return False
        if honor_skip_done and (
            iid in skip_iids or (code_u and code_u in skip_cs)
        ):
            return False
        if _enrich._should_skip_for_giveup(
            code_u=code_u, gaps=gaps, giveup_codes=cover_giveup
        ):
            return False
        return True

    # 0) 仅补「不在 pending 里」的源故障番号（本地已齐），仍放队首
    if src_retry_orphan:
        _push_log(
            f"源故障补抓 · {len(src_retry_orphan)} 个本地已齐番号优先重跑",
            region=rid or region,
        )
        head: list[dict[str, Any]] = []
        for h in src_retry_orphan:
            item_h = _enrich._src_retry_item(h, region=rid or region)
            if item_h is None:
                continue
            iid_h = str(item_h.get("itemId") or "")
            if iid_h in seen:
                continue
            seen.add(iid_h)
            head.append(item_h)
            emitted += 1
            if len(head) >= bs or (cap > 0 and emitted >= cap):
                yield head
                head = []
                if cap > 0 and emitted >= cap:
                    return
        if head:
            yield head

    def _pack(r: dict[str, Any], *, honor_local: bool = True) -> dict[str, Any] | None:
        iid = str(r.get("itemId") or "").strip()
        rel = str(r.get("relPath") or r.get("rel_path") or iid).strip().replace(
            "\\", "/"
        )
        if not iid and not rel:
            return None
        code_u = str(r.get("code") or "").strip().upper()
        # 本地成功/软成功/失败 → 不进未处理（队列表显式 pending 重试除外）
        if honor_local:
            if (rel and rel in local_classified) or (iid and iid in local_classified):
                return None
            if code_u and code_u in local_codes:
                return None
        iid2 = iid or rel
        gaps = list(r.get("gaps") or []) or list(_enrich._ENRICH_KINDS)
        # 队列表 pending（失败/软成功重试）禁止再被 skip_done 挡掉
        if not _want(
            iid2, code_u, gaps, honor_skip_done=honor_local
        ):
            return None
        seen.add(iid2)
        return {
            "itemId": iid2,
            "code": code_u,
            "gaps": gaps,
            "rel_path": rel or iid2,
            "relPath": rel or iid2,
            "region": rid or str(r.get("region") or region),
            "status": "pending",
            "shell": bool(r.get("shell")),
        }

    # 0b) 先吃队列表已有 pending（扫描/中断/失败·软成功重试），与列表同序
    #     ORDER BY updated_at DESC, id DESC。用 keyset 翻页，避免 OFFSET 在
    #     边刮边改 status 时跳号/乱序。
    #
    # 一表五态：扫描已写满 pending 后，开刮只改 status，禁止再扫盘/骨架
    # （否则「点刮削」又卡在「扫描本地 · 2万/12万」数分钟）。
    had_db_pending = False
    try:
        had_db_pending = (
            int((_enrich._queue_log_status_counts_db(rid or region) or {}).get("pending") or 0)
            > 0
        )
    except Exception:  # noqa: BLE001
        had_db_pending = False
    emitted_from_log = 0
    try:
        from app.core.db import connect, init_db

        init_db()
        cursor_updated: Any = None
        cursor_id: int | None = None
        with connect() as conn:
            while True:
                if _enrich._halt_kind():
                    return
                if cursor_id is None:
                    rows = conn.execute(
                        """
                        SELECT id, item_id, code, status, gaps_json, error, source,
                               fetch_ms, detail_title, payload_json, updated_at
                        FROM enrich_queue_log
                        WHERE region=? AND status='pending'
                        ORDER BY updated_at DESC NULLS LAST, id DESC
                        LIMIT ?
                        """,
                        (rid or region, bs),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT id, item_id, code, status, gaps_json, error, source,
                               fetch_ms, detail_title, payload_json, updated_at
                        FROM enrich_queue_log
                        WHERE region=? AND status='pending'
                          AND (
                            updated_at < ?
                            OR (updated_at = ? AND id < ?)
                          )
                        ORDER BY updated_at DESC NULLS LAST, id DESC
                        LIMIT ?
                        """,
                        (
                            rid or region,
                            cursor_updated,
                            cursor_updated,
                            cursor_id,
                            bs,
                        ),
                    ).fetchall()
                batch_rows = list(rows or [])
                if not batch_rows:
                    break
                log_batch: list[dict[str, Any]] = []
                last_raw = batch_rows[-1]
                if isinstance(last_raw, dict):
                    cursor_id = int(last_raw.get("id") or 0) or None
                    cursor_updated = last_raw.get("updated_at")
                else:
                    cursor_id = int(last_raw[0] or 0) or None
                    cursor_updated = last_raw[10] if len(last_raw) > 10 else None
                for r in batch_rows:
                    if isinstance(r, dict):
                        it = _enrich._queue_log_row_to_item(r)
                    else:
                        it = _enrich._queue_log_row_to_item(
                            {
                                "id": r[0],
                                "item_id": r[1],
                                "code": r[2],
                                "status": r[3],
                                "gaps_json": r[4],
                                "error": r[5],
                                "source": r[6],
                                "fetch_ms": r[7],
                                "detail_title": r[8],
                                "payload_json": r[9],
                            }
                        )
                    packed = _pack(
                        {
                            **it,
                            "itemId": it.get("itemId"),
                            "relPath": it.get("relPath") or it.get("rel_path"),
                            "rel_path": it.get("rel_path") or it.get("relPath"),
                        },
                        honor_local=False,
                    )
                    if not packed:
                        iid0 = str(it.get("itemId") or "").strip()
                        if iid0:
                            seen.add(iid0)
                        continue
                    if it.get("logId"):
                        packed["logId"] = it.get("logId")
                    log_batch.append(packed)
                    emitted += 1
                    emitted_from_log += 1
                    if cap > 0 and emitted >= cap:
                        break
                if log_batch:
                    yield log_batch
                if cap > 0 and emitted >= cap:
                    return
                if len(batch_rows) < bs:
                    break
    except Exception as e:  # noqa: BLE001
        log.warning("iter pending from queue_log failed: %s", e)

    if had_db_pending or emitted_from_log > 0:
        # 队列表已有未处理：开刮只消费 pending，不再扫本地 / 骨架 / 向量
        return

    # 骨架/向量切片需要 done-keys；开刮线程可能还在加载——最多等几秒，不永久堵死
    if defer_skip_until is not None and not defer_skip_until.is_set():
        defer_skip_until.wait(timeout=15.0)

    # 后续骨架/向量切片才需要本地已分类映射（仅队列表无 pending 时的兜底）
    _ensure_local_maps()

    # 本地已分类路径占位，避免队列表残留 pending 与骨架重复吐出
    for rel in local_classified:
        seen.add(rel)

    # 1) 骨架空壳分页：热门前缀（本地已有/近期成功）优先，其余空壳降权殿后
    hot_prefs = _enrich._hot_prefixes_for_region(rid or region, max_n=80)
    if hot_prefs:
        _push_log(
            f"队列切片 · 热门前缀 {len(hot_prefs)} · "
            f"{','.join(hot_prefs[:12])}{'…' if len(hot_prefs) > 12 else ''}",
            region=rid or region,
        )
    off = 0
    while True:
        if _enrich._halt_kind():
            return
        rows = embed_svc.list_skeleton_shell_items(
            rid or region,
            limit=bs,
            offset=off,
            prefer_prefixes=hot_prefs,
        )
        if not rows:
            break
        off += len(rows)
        batch: list[dict[str, Any]] = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            packed = _pack(r)
            if not packed:
                continue
            batch.append(packed)
            emitted += 1
            if cap > 0 and emitted >= cap:
                break
        if batch:
            yield batch
        if cap > 0 and emitted >= cap:
            return
        if len(rows) < bs:
            break

    # 2) 向量库全部有番号行（含已齐但本地已删）— 按更新时间倒序回填未处理
    off = 0
    while True:
        if _enrich._halt_kind():
            return
        try:
            extra = embed_svc.list_region_code_items(
                region=rid or region,
                limit=bs,
                offset=off,
                order="updated",
            )
        except Exception:  # noqa: BLE001
            extra = []
        if not extra:
            break
        off += len(extra)
        batch = []
        for r in extra or []:
            if not isinstance(r, dict):
                continue
            packed = _pack(r)
            if not packed:
                continue
            batch.append(packed)
            emitted += 1
            if cap > 0 and emitted >= cap:
                break
        if batch:
            yield batch
        if cap > 0 and emitted >= cap:
            return
        if len(extra) < bs:
            break


def load_queue_log(
    *,
    region: str = "",
    status: str = "",
    limit: int = 200,
    offset: int = 0,
    code: str = "",
) -> dict[str, Any]:
    rid = _queue_log_region(region)
    st = str(status or "").strip().lower()
    if st not in _enrich._QUEUE_LOG_FILTER_STATUSES:
        st = ""
    # 番号搜索：强制跨状态（无视调用方传入的 status / 当前 tab）
    if str(code or "").strip():
        st = ""
    lim = max(1, min(int(limit or 200), 500))
    off = max(0, int(offset or 0))
    code_q = (
        str(code or "")
        .strip()
        .upper()
        .replace(" ", "")
        .replace("　", "")
    )
    counts = _enrich._empty_queue_counts()
    items: list[dict[str, Any]] = []
    total = 0
    if not rid:
        return {
            "region": rid or None,
            "counts": counts,
            "items": items,
            "total": 0,
            "limit": lim,
            "offset": off,
        }
    # 纠偏只在「扫描 / 开刮」入口同步跑；列表读路径绝不触发（后台 demote
    # 也会占满磁盘/连接池，把设置页其它接口拖死）。

    # 读路径不做 prune；pending 以队列表为准。

    def _rows_to_items(rows_l: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in rows_l:
            if isinstance(r, dict):
                out.append(_enrich._queue_log_row_to_item(r))
            else:
                out.append(
                    _enrich._queue_log_row_to_item(
                        {
                            "id": r[0],
                            "item_id": r[1],
                            "code": r[2],
                            "status": r[3],
                            "gaps_json": r[4],
                            "error": r[5],
                            "source": r[6],
                            "fetch_ms": r[7],
                            "detail_title": r[8],
                            "payload_json": r[9],
                        }
                    )
                )
        return out

    try:
        from app.core.db import connect, init_db

        init_db()
        soft_pred = _enrich._soft_done_sql_pred(error_col="error")
        with connect() as conn:
            # 读路径不做全表 prune/回填（切 tab 会卡死）；脏行靠写路径清理
            for row in conn.execute(
                f"""
                SELECT
                  CASE
                    WHEN status='done' AND {soft_pred} THEN 'soft'
                    ELSE status
                  END AS bucket,
                  COUNT(*) AS n
                FROM enrich_queue_log
                WHERE region=?
                GROUP BY 1
                """,
                (rid,),
            ).fetchall():
                key = str(
                    (row.get("bucket") if isinstance(row, dict) else row[0]) or ""
                ).strip().lower()
                n = int(
                    (row.get("n") if isinstance(row, dict) else row[1]) or 0
                )
                if key in counts:
                    counts[key] = n

            # 列表翻页用库内行数；角标可被本地全量 overlay 盖掉
            db_counts = dict(counts)
            counts = _enrich._apply_local_status_totals(counts, rid)

            cols = """
                    SELECT id, item_id, code, status, gaps_json, error, source,
                           fetch_ms, detail_title, payload_json
                    FROM enrich_queue_log
            """
            if code_q:
                # 番号查询：精确优先，再前缀；跨全部状态（无视 tab）
                fetched = conn.execute(
                    cols
                    + """
                    WHERE region=? AND code=?
                    ORDER BY
                      CASE status
                        WHEN 'running' THEN 0
                        WHEN 'fail' THEN 1
                        WHEN 'done' THEN 2
                        ELSE 3
                      END,
                      updated_at DESC NULLS LAST,
                      id DESC
                    LIMIT ?
                    """,
                    (rid, code_q, lim),
                ).fetchall()
                rows_l = list(fetched or [])
                if not rows_l and len(code_q) >= 2:
                    fetched = conn.execute(
                        cols
                        + """
                        WHERE region=? AND code LIKE ?
                        ORDER BY
                          CASE WHEN code=? THEN 0 ELSE 1 END,
                          CASE status
                            WHEN 'running' THEN 0
                            WHEN 'fail' THEN 1
                            WHEN 'done' THEN 2
                            ELSE 3
                          END,
                          updated_at DESC NULLS LAST,
                          id DESC
                        LIMIT ?
                        """,
                        (rid, f"{code_q}%", code_q, lim),
                    ).fetchall()
                    rows_l = list(fetched or [])
                items = _rows_to_items(rows_l)
                if not items:
                    # 库内无命中时：扫描内存 / 磁盘 / 向量兜底（跨状态）
                    items = _enrich._lookup_code_outside_queue_log(
                        region=rid, code_q=code_q, limit=lim
                    )
                elif bool(_enrich._QUEUE_SCAN_STATE.get("active")):
                    # 扫描中样例可能尚未入库：只并内存命中
                    extra = _enrich._lookup_code_from_scan_samples(
                        region=rid, code_q=code_q, limit=lim
                    )
                    if extra:
                        seen = {
                            str(it.get("itemId") or it.get("code") or "").strip()
                            for it in items
                        }
                        for it in extra:
                            key = str(
                                it.get("itemId") or it.get("code") or ""
                            ).strip()
                            if key and key not in seen:
                                items.append(it)
                                seen.add(key)
                            if len(items) >= lim:
                                break
                total = len(items)
                for i, it in enumerate(items):
                    items[i] = _enrich._backfill_queue_item_detail(it, region=rid)
            elif st:
                # 成功/软成功/失败：按最近更新时间（刚刮完的在最上）
                # 未处理：虚拟翻页（向量 − 已分类），total 用估算全量
                if st == "pending":
                    total = int(db_counts.get("pending") or 0)
                    counts["pending"] = total
                    items = _enrich._pending_page_from_vector(
                        rid, offset=off, limit=lim
                    )
                else:
                    if st in {"done", "soft", "fail"}:
                        order = "updated_at DESC NULLS LAST, id DESC"
                    else:
                        order = "id ASC"
                    total = int(db_counts.get(st) or 0)
                    if st == "soft":
                        where_extra = f"AND status='done' AND {soft_pred}"
                        params: tuple[Any, ...] = (rid, lim, off)
                    elif st == "done":
                        where_extra = f"AND status='done' AND NOT {soft_pred}"
                        params = (rid, lim, off)
                    else:
                        where_extra = "AND status=?"
                        params = (rid, st, lim, off)
                    fetched = conn.execute(
                        cols
                        + f"""
                        WHERE region=? {where_extra}
                        ORDER BY {order}
                        LIMIT ? OFFSET ?
                        """,
                        params,
                    ).fetchall()
                    items = _rows_to_items(list(fetched or []))
                    # 扫描轻量写入无 fields：列表仍可翻页，点开/本页按需从 NFO 补全
                    for i, it in enumerate(items):
                        fields = it.get("fields") if isinstance(it, dict) else None
                        if not (isinstance(fields, list) and fields):
                            items[i] = _enrich._backfill_queue_item_detail(it, region=rid)
            else:
                total = sum(int(db_counts.get(k) or 0) for k in db_counts)
    except Exception as e:  # noqa: BLE001
        log.warning("load enrich queue log failed region=%s: %s", rid, e)
    counts = _enrich._apply_local_status_totals(counts, rid)
    counts = _enrich._clamp_pending_badge(counts, rid)
    if st == "pending" and int(counts.get("pending") or 0) > 0:
        total = int(counts.get("pending") or total)
    return {
        "region": rid,
        "counts": counts,
        "items": items,
        "code": code_q or None,
        "total": int(total),
        "limit": lim,
        "offset": off,
    }


_QUEUE_SAMPLE_LIMIT = 48


_queue_sample_cache: tuple[Any, int, int, list[dict[str, Any]]] | None = None


_STATUS_QUEUE_HEAVY_KEYS = frozenset(
    {
        "sourceTimings",
        "fields",
        "wouldFill",
        "actors",
    }
)


def _sample_queue_for_status(
    raw_queue: list[Any], *, limit: int = _QUEUE_SAMPLE_LIMIT
) -> list[dict[str, Any]]:
    """状态帧的队列抽样（热路径：SSE 每 0.25s 重建一帧）。

    ⚠️ 队列可达 2 万+ 行。**不要**试图用"头尾窗口扫描"来省：
    真实分布是「done 堆头部、pending 往后」（顺序处理），头窗口里根本没有
    pending、尾窗口里根本没有 done，窗口必然扫不齐 → 退化成扫两遍，反而更慢
    （实测 4.6ms vs 3.1ms，方向错了）。这里改为按**队列身份**缓存：
    同一队列对象（未被改动）二次渲染直接复用，改动才重算。
    """
    global _queue_sample_cache

    try:
        n_all = len(raw_queue)
    except TypeError:
        return []
    if n_all <= 0:
        return []
    if n_all <= limit:
        return [r for r in raw_queue if isinstance(r, dict)]

    hit = _queue_sample_cache
    if (
        hit is not None
        and hit[0] is raw_queue
        and hit[1] == n_all
        and hit[2] == limit
    ):
        return hit[3]
    out = _enrich._sample_queue_uncached(raw_queue, limit=limit)
    _queue_sample_cache = (raw_queue, n_all, limit, out)
    return out


def _set_current_region(region_id: str = "") -> None:
    with _enrich._enrich_lock:
        _enrich._enrich_job["currentRegion"] = str(region_id or "").strip()


def _set_queue(rows: list[dict[str, Any]]) -> None:
    """写入完整处理队列；状态接口只抽样回传。"""
    with _enrich._enrich_lock:
        cleaned = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        _enrich._enrich_job["queue"] = cleaned
        _enrich._enrich_job["queueCounts"] = _enrich._queue_counts_of(cleaned)
    _enrich.notify_enrich_watchers(force=True)


def _patch_queue_item(
    index: int,
    *,
    match: dict[str, Any] | None = None,
    persist: bool = True,
    **fields: Any,
) -> None:
    """改内存队列行（UI 立即生效）；persist=False 只改内存不落库。

    persist=False 专供**预览（dryRun）**：预览行标 done 若落进
    enrich_queue_log，会被 `_enrich._queue_log_prune_open_if_done` 当成「同番号已有成功」
    从而删掉真正的 pending 行 —— 待刮条目就此消失（假成功）。
    """
    updated: dict[str, Any] | None = None
    region = ""
    resolved_i = -1
    st_in = str(fields.get("status") or "").strip().lower()
    with _enrich._enrich_lock:
        halt = _enrich._enrich_job.get("halt")
        # 暂停后：成功仍可落库；失败/进行中一律丢弃（由 pause 退回 pending）
        # 停止后：仅丢弃非终态回写
        if halt == "pause":
            if st_in == "fail":
                fields = {**fields, "status": "pending", "error": ""}
                st_in = "pending"
            elif st_in and st_in not in {"done", "pending"}:
                return
        elif halt == "stop" and st_in not in {"done", "fail"}:
            return
        queue = list(_enrich._enrich_job.get("queue") or [])
        resolved_i = _enrich._queue_row_match_index(queue, index=index, match=match)
        if resolved_i < 0:
            # 边扫展示队列只留约 120 行，进行中的番号常被裁掉。
            # 不补回 running，状态帧就没有占槽行，页面一直「等待番号占槽」。
            if isinstance(match, dict) and st_in == "running":
                base = dict(match)
                base.update(fields)
                base["status"] = "running"
                code_u = str(base.get("code") or "").strip().upper()
                iid = str(base.get("itemId") or base.get("item_id") or "").strip()
                kept: list[dict[str, Any]] = []
                for r in queue:
                    if not isinstance(r, dict):
                        continue
                    rc = str(r.get("code") or "").strip().upper()
                    ri = str(r.get("itemId") or r.get("item_id") or "").strip()
                    if code_u and rc == code_u:
                        continue
                    if iid and ri == iid:
                        continue
                    kept.append(r)
                kept.insert(0, base)
                _enrich._enrich_job["queue"] = _enrich._cap_status_queue(kept)
                counts = dict(_enrich._enrich_job.get("queueCounts") or {})
                n_run = sum(
                    1
                    for r in _enrich._enrich_job["queue"]
                    if isinstance(r, dict) and str(r.get("status") or "") == "running"
                )
                counts["running"] = max(int(counts.get("running") or 0), n_run)
                for k in ("pending", "running", "done", "fail", "soft"):
                    counts[k] = int(counts.get(k) or 0)
                _enrich._enrich_job["queueCounts"] = counts
                updated = base
                region = str(
                    base.get("region") or _enrich._enrich_job.get("currentRegion") or ""
                )
            # 截断后内存里可能已没有该行：仍用 match 身份落库，避免丢终态
            elif isinstance(match, dict) and st_in in {"done", "fail", "pending"}:
                base = dict(match)
                base.update(fields)
                updated = base
                region = str(
                    base.get("region") or _enrich._enrich_job.get("currentRegion") or ""
                )
                # 展示队列只有 ~120 行；丢行后若不改角标，成功数/部/分会假死在早期值
                counts = dict(_enrich._enrich_job.get("queueCounts") or {})
                old_st = str(match.get("status") or "").strip().lower()
                if old_st not in {"pending", "running", "done", "fail"}:
                    old_st = "running" if st_in in {"done", "fail"} else "pending"
                if old_st != st_in:
                    counts[old_st] = max(0, int(counts.get(old_st) or 0) - 1)
                    counts[st_in] = int(counts.get(st_in) or 0) + 1
                for k in ("pending", "running", "done", "fail", "soft"):
                    counts[k] = int(counts.get(k) or 0)
                _enrich._enrich_job["queueCounts"] = counts
                base_prog = dict(_enrich._enrich_job.get("progress") or {})
                _enrich._enrich_job["progress"] = _enrich._progress_from_queue_counts(
                    counts, base=base_prog
                )
                if old_st != st_in and st_in in {"done", "fail"}:
                    _lift_local_status_totals_from_counts(
                        region,
                        {
                            "done": int(counts.get("done") or 0),
                            "soft": int(counts.get("soft") or 0),
                            "fail": int(counts.get("fail") or 0),
                        },
                    )
            else:
                return
        else:
            row = dict(queue[resolved_i] or {})
            old_st = str(row.get("status") or "pending").strip().lower()
            if old_st not in {"pending", "running", "done", "fail"}:
                old_st = "pending"
            # 暂停后内存队列已把 running→pending：禁止再写回 running
            if halt == "pause" and st_in == "running":
                return
            if halt == "pause" and old_st == "pending" and st_in == "fail":
                return
            row.update(fields)
            new_st = str(row.get("status") or "pending").strip().lower()
            if new_st not in {"pending", "running", "done", "fail"}:
                new_st = "pending"
            queue[resolved_i] = row
            _enrich._enrich_job["queue"] = queue
            counts = dict(_enrich._enrich_job.get("queueCounts") or {}) or _enrich._queue_counts_of(queue)
            if old_st != new_st:
                counts[old_st] = max(0, int(counts.get(old_st) or 0) - 1)
                counts[new_st] = int(counts.get(new_st) or 0) + 1
            for k in ("pending", "running", "done", "fail"):
                counts[k] = int(counts.get(k) or 0)
            # 暂停态不允许残留 running 角标
            if halt == "pause" and int(counts.get("running") or 0) > 0:
                counts["pending"] = int(counts.get("pending") or 0) + int(
                    counts.get("running") or 0
                )
                counts["running"] = 0
            _enrich._enrich_job["queueCounts"] = counts
            # 同步进度，避免轮询间隙 percent 乱跳
            base = dict(_enrich._enrich_job.get("progress") or {})
            _enrich._enrich_job["progress"] = _enrich._progress_from_queue_counts(counts, base=base)
            updated = dict(row)
            region = str(
                row.get("region") or _enrich._enrich_job.get("currentRegion") or ""
            )
            if old_st != new_st and new_st in {"done", "fail"}:
                _lift_local_status_totals_from_counts(
                    region,
                    {
                        "done": int(counts.get("done") or 0),
                        "soft": int(counts.get("soft") or 0),
                        "fail": int(counts.get("fail") or 0),
                    },
                )
    if updated is not None:
        # 预览不落库，但内存态照改 —— UI 仍要看到「本行将被补齐」
        if persist:
            lid = _queue_log_update_row(updated, region=region)
            # ⚠️ 不只是「本来没有 lid」时要回写：内存 lid 已过期（行被 prune /
            # 扫描重写删掉）时，落库会改到别的行或新建行，内存必须跟着换，
            # 否则同一次刮削的后续落库继续用旧 lid → 日志里同一个番号出现多行。
            if lid and resolved_i >= 0 and int(lid) != _enrich._queue_log_int_id(updated):
                with _enrich._enrich_lock:
                    queue = list(_enrich._enrich_job.get("queue") or [])
                    if 0 <= resolved_i < len(queue):
                        row = dict(queue[resolved_i] or {})
                        row["logId"] = lid
                        queue[resolved_i] = row
                        _enrich._enrich_job["queue"] = queue
                        updated = dict(row)
            if str(updated.get("status") or "").strip().lower() == "running":
                keep = int(lid or _enrich._queue_log_int_id(updated) or 0)
                _enrich._queue_log_prune_pending_if_running(
                    region,
                    code=str(updated.get("code") or ""),
                    item_id=str(updated.get("itemId") or ""),
                    keep_id=keep,
                )
        _enrich.notify_enrich_watchers()


def _set_current(payload: dict[str, Any] | None) -> None:
    with _enrich._enrich_lock:
        _enrich._enrich_job["current"] = payload
    _enrich.notify_enrich_watchers()

