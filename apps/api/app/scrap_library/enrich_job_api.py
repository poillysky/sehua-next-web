# -*- coding: utf-8 -*-
"""Job entrypoints: start_enrich_job / save_item_plot / enrich_one_by_item_id."""
from __future__ import annotations

import logging
import re
import threading
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import app.scrap_library.embed as embed_svc
import app.scrap_library.enrich as _enrich
from app.core.db import get_meta_pool
from app.scrap_library.enrich_runtime import (
    _checkpoint_summaries,
    _enrich_job,
    _enrich_lock,
    _enrich_retry_front,
    _hydrate_enrich_runtime,
    _persist_enrich_runtime,
    notify_enrich_watchers,
)
from app.scrap_library.nfo import (
    build_mdcx_nfo_root,
    fields_from_movie_root,
    write_nfo,
)

log = logging.getLogger(__name__)

def save_item_plot(*, item_id: str = "", plot: str = "") -> dict[str, Any]:
    """把中文剧情写入 NFO 并重嵌入落库（覆盖原 plot/outline）。"""
    iid = str(item_id or "").strip()
    plot_zh = str(plot or "").strip()
    # NFO/展示里常见的 HTML 换行转成纯文本
    plot_zh = re.sub(r"<br\s*/?>", "\n", plot_zh, flags=re.I)
    plot_zh = re.sub(r"&nbsp;", " ", plot_zh, flags=re.I)
    plot_zh = re.sub(r"\n{3,}", "\n\n", plot_zh).strip()
    if not iid:
        raise ValueError("itemId 必填")
    if len(plot_zh) < 2:
        raise ValueError("剧情太短")
    if len(plot_zh) > 4000:
        plot_zh = plot_zh[:4000]

    embed_svc.ensure_schema()
    pool = _enrich.get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, rel_path, code, region, source_text
            FROM {embed_svc.TABLE}
            WHERE item_id = %s
            LIMIT 1
            """,
            (iid,),
        )
        row = cur.fetchone()
    if not row:
        raise ValueError("条目不存在")
    d = dict(row) if isinstance(row, dict) else {}
    rel = str(d.get("rel_path") or "").replace("\\", "/").strip()
    if not rel:
        raise ValueError("缺少 rel_path")

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    folder = (root / rel).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError("bad path") from e
    if not folder.is_dir():
        raise ValueError("目录不存在")

    nfo = _enrich._find_nfo(folder) or (folder / f"{folder.name}.nfo")
    if nfo.is_file():
        try:
            raw = nfo.read_text(encoding="utf-8", errors="replace")
            root_el = ET.fromstring(raw)
        except Exception:
            root_el = ET.Element("movie")
    else:
        root_el = ET.Element("movie")
    if root_el.tag.lower() != "movie":
        movie = root_el.find("movie")
        root_el = movie if movie is not None else ET.Element("movie")

    # 原日文剧情备份到 originalplot（仅首次）；整文件按 MDCx 布局重排
    fields = _enrich.fields_from_movie_root(root_el, code_fallback=str(d.get("code") or ""))
    cur_plot = str(fields.get("plot") or "").strip()
    if cur_plot and cur_plot != plot_zh:
        if not str(fields.get("originalplot") or "").strip():
            fields["originalplot"] = cur_plot
    fields["plot"] = plot_zh
    fields["outline"] = plot_zh
    root_el = _enrich.build_mdcx_nfo_root(fields)
    _enrich.write_nfo(nfo, root_el)

    # 先把剧情写进 source_text，保证详情再打开就是中文；向量失败不挡落库
    prev_src = str(d.get("source_text") or "")
    plot_line = "剧情：" + re.sub(r"\s*\n\s*", " ", plot_zh).strip()
    if re.search(r"^剧情：", prev_src, flags=re.M):
        new_src = re.sub(
            r"^剧情：[\s\S]+?(?=\n[^\s][^：\n]*：|$)",
            plot_line,
            prev_src,
            count=1,
            flags=re.M,
        )
    else:
        new_src = (prev_src.rstrip() + "\n" + plot_line).strip()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE {embed_svc.TABLE}
            SET source_text = %s, updated_at = now()
            WHERE item_id = %s
            """,
            (new_src, iid),
        )
        conn.commit()

    rein: dict[str, Any] | None = None
    rein_err = ""
    try:
        rein = _enrich.reingest_folder(folder)
    except Exception as e:  # noqa: BLE001
        rein_err = str(e)
        log.warning("save_item_plot reingest failed item=%s: %s", iid, e)

    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT item_id, code, title, source_text, updated_at
            FROM {embed_svc.TABLE}
            WHERE item_id = %s
            LIMIT 1
            """,
            (iid,),
        )
        fresh = cur.fetchone()
    fd = dict(fresh) if isinstance(fresh, dict) else {}
    return {
        "ok": True,
        "itemId": iid,
        "code": str(fd.get("code") or d.get("code") or ""),
        "title": str(fd.get("title") or ""),
        "sourceText": str(fd.get("source_text") or new_src),
        "plot": plot_zh,
        "reingest": rein,
        "reingestError": rein_err or None,
    }


def enrich_one_by_item_id(
    *,
    item_id: str = "",
    dry_run: bool = False,
    overwrite: bool = True,
    sync_vector: bool = True,
) -> dict[str, Any]:
    """详情页单番号刷新：默认全量覆盖（重刮 → 覆盖 NFO → 重写向量）。

    sync_vector=False：只写本地 NFO/封面（与分区批量一致），不清空向量行。
    """
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("itemId 必填")
    force = bool(overwrite)
    do_vector = bool(sync_vector)

    with _enrich_lock:
        if _enrich_job["running"]:
            raise RuntimeError("元数据补全已在运行")
        if embed_svc.get_job_status().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        _enrich_job.update(
            {
                "running": True,
                "phase": "one",
                "progress": {
                    "stage": "enrich",
                    "done": 0,
                    "total": 1,
                    "percent": 5,
                    "label": "单条覆盖刷新" if force else "单条补全",
                },
                "log": [],
                "result": None,
                "error": None,
            }
        )

    try:
        embed_svc.ensure_schema()
        pool = _enrich.get_meta_pool()
        with pool.connection() as conn, conn.cursor() as cur:
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
            row = cur.fetchone()
        if not row:
            raise ValueError("条目不存在")
        d = dict(row) if isinstance(row, dict) else {}
        gaps = embed_svc._row_gaps(d)
        code = str(d.get("code") or "").strip().upper()
        mode_label = "覆盖重刮" if force else "增量补缺"
        _enrich._push_log(
            f"单条{mode_label} · {code or iid} · gaps={','.join(gaps) or 'none'}"
        )
        _enrich._set_progress(
            stage="enrich",
            percent=15,
            label=f"{mode_label} {code or iid}",
            done=0,
            total=1,
        )

        # 覆盖且要同步向量：先清空该条向量，再刮削写回
        # 仅本地刮削时保留向量行，交给「同步数据库」「数据库向量化」另跑
        if force and do_vector and not dry_run:
            with pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {embed_svc.TABLE} WHERE item_id = %s",
                    (iid,),
                )
                conn.commit()
            _enrich._push_log(f"{code or iid} · 已清空向量行，开始重刮")
            _enrich._set_progress(
                stage="enrich",
                percent=25,
                label=f"重刮 {code or iid}",
                done=0,
                total=1,
            )

        one = _enrich.enrich_one_row(
            {
                "itemId": str(d.get("item_id") or iid),
                "code": code,
                "rel_path": str(d.get("rel_path") or "").replace("\\", "/"),
                "relPath": str(d.get("rel_path") or "").replace("\\", "/"),
                "region": str(d.get("region") or ""),
                # 覆盖时不当缺口限制，拉满源再整表写回
                "gaps": [] if force else gaps,
            },
            dry_run=dry_run,
            wait_all=True,
            overwrite=force,
            sync_vector=do_vector,
        )

        # 覆盖失败且已删向量：尝试用旧 NFO 救回一条，避免详情变 404
        if force and do_vector and not dry_run and not one.get("ok"):
            rel = str(d.get("rel_path") or "").replace("\\", "/")
            settings = embed_svc.get_settings()
            root = embed_svc.resolve_root(settings.get("root"))
            folder = (root / rel).resolve() if rel else None
            if folder and folder.is_dir():
                try:
                    rein = _enrich.reingest_folder(folder)
                    _enrich._push_log(
                        f"{code or iid} · 覆盖失败，已尝试从 NFO 救回向量"
                        f" · {rein.get('error') or ('ok' if rein.get('ok') else 'fail')}"
                    )
                except Exception as e:  # noqa: BLE001
                    _enrich._push_log(f"{code or iid} · 向量救回失败 · {e}")

        item: dict[str, Any] | None = None
        if not dry_run:
            with pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT item_id, region, prefix, code, title, rel_path,
                           poster_path, thumb_path, fanart_path, cover_url,
                           source_text
                    FROM {embed_svc.TABLE}
                    WHERE item_id = %s
                    LIMIT 1
                    """,
                    (iid,),
                )
                fresh = cur.fetchone()
            if fresh:
                item = embed_svc._hit_from_row(
                    dict(fresh) if isinstance(fresh, dict) else {}
                )
        out = {
            "ok": bool(one.get("ok")),
            "dryRun": dry_run,
            "overwrite": force,
            "result": one,
            "item": item,
            "gaps": gaps,
        }
        with _enrich_lock:
            _enrich_job["result"] = _enrich._slim_result_for_status(out)
            _enrich_job["phase"] = "done" if one.get("ok") else "error"
            if not one.get("ok"):
                _enrich_job["error"] = str(one.get("error") or "fail")
        _enrich._set_progress(
            stage="done",
            percent=100,
            label="完成",
            done=1 if one.get("ok") else 0,
            total=1,
        )
        _enrich._push_log(
            f"单条{mode_label}结束 · {code or iid} · "
            f"{'ok' if one.get('ok') else one.get('error') or 'fail'}"
        )
        return out
    except Exception as e:
        with _enrich_lock:
            _enrich_job["error"] = str(e)
            _enrich_job["phase"] = "error"
        raise
    finally:
        with _enrich_lock:
            _enrich_job["running"] = False
        # 收尾把攒批的日志落库（异步缓冲，不 flush 会等下一次后台写或进程退出）
        _enrich.flush_enrich_logs()


def start_enrich_job(
    *,
    region: str = "",
    regions: list[str] | None = None,
    kinds: list[str] | None = None,
    limit: int = 0,
    dry_run: bool = False,
    mode: str = "incremental",
) -> dict[str, Any]:
    import app.scrap_library.enrich_strategy as strat
    from app.core.region_meta import REGION_META, REGION_ORDER

    _enrich._hydrate_enrich_runtime()

    requested = [str(r).strip() for r in (regions or []) if str(r).strip()]
    if not requested:
        one = str(region or "").strip()
        if one:
            requested = [one]
    enabled = set(strat.enabled_region_ids())
    if requested:
        # 显式指定分区：按请求跑（开关打开即开始，不二次过滤）
        want = set(requested)
        region_list = [r for r in strat.enrich_region_ids() if r in want]
        for r in requested:
            if r not in region_list:
                region_list.append(r)
    else:
        region_list = list(enabled)
    if not region_list:
        raise ValueError("未开启任何刮削分区")

    mode_raw = str(mode or "").strip().lower()
    if mode_raw in {"overwrite", "cover", "force", "replace"}:
        mode_norm = "overwrite"
    elif mode_raw in {"refresh_weak", "weak", "refresh"}:
        mode_norm = "refresh_weak"
    else:
        mode_norm = "incremental"

    with _enrich_lock:
        if _enrich_job["running"]:
            raise RuntimeError("刮削补齐已在运行")
        if embed_svc.get_job_status().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        global _enrich_retry_front
        _enrich_retry_front = []
        prev_logs = dict(_enrich_job.get("regionLogs") or {})
        resume_map: dict[str, dict[str, Any]] = {}
        cps = dict(_enrich_job.get("checkpoints") or {})
        for rid in region_list:
            raw = cps.get(rid)
            # 预览（dryRun）不续跑：预览是抽样，不是"继续上一次"。
            # 若让它续跑，检查点的 queueInLog 会让 _enrich.run_enrich 用
            # _enrich._rebuild_checkpoint_queue_from_log 重建整个分区的 pending（有码区 2 万+），
            # limit 被无视 → 预览退化成全分区刮削；还会 pop 掉真实暂停任务的检查点。
            if dry_run or not isinstance(raw, dict):
                continue
            remaining_q = [
                dict(r)
                for r in list(raw.get("queue") or [])
                if isinstance(r, dict)
            ]
            rem_declared = int(raw.get("remainingCount") or 0)
            try:
                db_pending = int(
                    _enrich._queue_log_status_counts(rid, fresh=True).get("pending") or 0
                )
            except Exception:  # noqa: BLE001
                db_pending = 0
            if (
                bool(raw.get("queueInLog"))
                or rem_declared > len(remaining_q)
                or db_pending > len(remaining_q)
            ):
                from_log = _enrich._rebuild_checkpoint_queue_from_log(rid)
                if from_log:
                    remaining_q = from_log
                    rem_declared = max(rem_declared, db_pending, len(remaining_q))
            if not remaining_q and db_pending <= 0:
                # 空检查点占位：丢掉，避免挡后续
                cps.pop(rid, None)
                continue
            if not remaining_q and db_pending > 0:
                remaining_q = []
                rem_declared = db_pending
                raw = dict(raw)
                raw["queueInLog"] = True
                raw["remainingCount"] = db_pending
            # 有剩余队列就续跑——不再因 mode/dryRun 不一致丢掉检查点
            # （否则会重扫缺口；本地已写过的会被跳过，表现为「再开队列空了」）
            cp_mode = str(raw.get("mode") or "incremental").strip().lower()
            if cp_mode not in {"incremental", "refresh_weak", "overwrite"}:
                cp_mode = mode_norm
            fixed = dict(raw)
            fixed["queue"] = remaining_q
            fixed["mode"] = cp_mode
            if bool(raw.get("dryRun")) != bool(dry_run):
                log.info(
                    "enrich resume ignore dryRun mismatch region=%s cp=%s req=%s",
                    rid,
                    bool(raw.get("dryRun")),
                    bool(dry_run),
                )
            if cp_mode != mode_norm:
                log.info(
                    "enrich resume keep checkpoint mode region=%s cp=%s req=%s",
                    rid,
                    cp_mode,
                    mode_norm,
                )
            resume_map[rid] = fixed
            cps.pop(rid, None)
        _enrich_job["checkpoints"] = cps
        # 立刻把续跑队列塞进 status，避免「再开瞬间 queue=[]」被当成清空
        seed_queue: list[dict[str, Any]] = []
        seed_prior = 0
        if resume_map:
            first_rid = next(
                (r for r in region_list if r in resume_map),
                next(iter(resume_map)),
            )
            first_cp = resume_map[first_rid]
            seed_prior = int(first_cp.get("done") or 0)
            for i, r in enumerate(list(first_cp.get("queue") or [])):
                if not isinstance(r, dict):
                    continue
                seed_queue.append(
                    {
                        "index": seed_prior + i,
                        "itemId": str(r.get("itemId") or ""),
                        "code": str(r.get("code") or "").strip().upper(),
                        "gaps": list(r.get("gaps") or []),
                        "status": "pending",
                        **(
                            {"logId": lid}
                            if (lid := _enrich._queue_log_int_id(r))
                            else {}
                        ),
                    }
                )
        region_logs: dict[str, list[str]] = {
            str(k): list(v or [])[-40:]
            for k, v in prev_logs.items()
            if str(k) not in region_list
        }
        for rid in region_list:
            if rid in resume_map:
                region_logs[rid] = list(prev_logs.get(rid) or [])[-40:]
            else:
                region_logs[rid] = []
        keep_log = bool(resume_map)
        # 开刮时内存 queueCounts 若清零，运行中 SSE 会把成功/软成功/失败角标刷成 0。
        badge_seed = _enrich._empty_queue_counts()
        badge_rid = next((r for r in region_list if r), "")
        if badge_rid:
            try:
                badge_seed = _enrich._apply_local_status_totals(
                    _enrich._queue_log_status_counts(badge_rid, fresh=True),
                    badge_rid,
                )
            except Exception as e:  # noqa: BLE001
                log.debug("enrich start badge seed failed region=%s: %s", badge_rid, e)
        _enrich_job.update(
            {
                "running": True,
                "phase": "starting",
                "progress": {
                    "stage": "prepare",
                    "done": seed_prior if seed_queue else 0,
                    "total": (seed_prior + len(seed_queue)) if seed_queue else 0,
                    "percent": 0,
                    "ok": 0,
                    "failed": 0,
                    "label": "继续" if keep_log else "starting",
                },
                "log": list(_enrich_job.get("log") or [])[-40:] if keep_log else [],
                "regionLogs": region_logs,
                "currentRegion": badge_rid,
                "cancel": False,
                "halt": None,
                "queue": seed_queue,
                "queueCounts": {
                    "pending": len(seed_queue),
                    "running": 0,
                    "done": int(badge_seed.get("done") or 0),
                    "soft": int(badge_seed.get("soft") or 0),
                    "fail": int(badge_seed.get("fail") or 0),
                },
                "current": None,
                "result": None,
                "error": None,
                "jobMode": mode_norm,
                "jobKinds": list(kinds or []),
                "jobDryRun": bool(dry_run),
            }
        )
    _enrich.notify_enrich_watchers(force=True)

    def run() -> None:
        try:
            parts: list[dict[str, Any]] = []
            ok_n = 0
            fail_n = 0
            queued_n = 0
            cancelled = False
            paused = False
            # 预览 limit 为跨区总预算；正式跑 limit=0 表示各区全量
            budget: int | None = int(limit) if int(limit or 0) > 0 else None
            for idx, rid in enumerate(region_list):
                halt = _enrich._halt_kind()
                if halt:
                    if halt == "pause":
                        paused = True
                        _enrich._push_log("已暂停，后续分区跳过")
                    else:
                        cancelled = True
                        _enrich._clear_checkpoint(rid)
                        _enrich._clear_runtime_queue()
                        _enrich._queue_log_reopen_running(region=rid)
                        log.info("enrich stopped, skip remaining regions")
                    break
                label = str((REGION_META.get(rid) or {}).get("label") or rid)
                _enrich._set_current_region(rid)
                cp = resume_map.get(rid)
                if cp:
                    _enrich._push_log(
                        f"分区 {idx + 1}/{len(region_list)} · {label} · 继续",
                        region=rid,
                    )
                else:
                    _enrich._push_log(
                        f"分区 {idx + 1}/{len(region_list)} · {label}",
                        region=rid,
                    )
                if budget is not None and budget <= 0 and not cp:
                    _enrich._push_log(f"跳过 {label}（预览额度已用完）", region=rid)
                    break
                use_lim = budget if budget is not None else int(limit or 0)
                # 续跑：队列来自检查点；mode/kinds 用本次请求（=最新策略），改策略后立刻生效
                use_mode = mode_norm
                use_kinds = list(kinds or [])
                one = _enrich.run_enrich(
                    region=rid,
                    kinds=use_kinds,
                    limit=use_lim,
                    dry_run=dry_run,
                    mode=use_mode,
                    resume=cp,
                )
                parts.append(one)
                if one.get("paused"):
                    paused = True
                if one.get("cancelled"):
                    cancelled = True
                ok_n += int(one.get("ok") or 0)
                fail_n += int(one.get("failed") or 0)
                q = int(one.get("queued") or 0)
                queued_n += q
                # 预算按实际处理条数扣减（见 _enrich._next_budget 注释）
                if not cp:
                    budget = _enrich._next_budget(budget, one)
                if paused or cancelled:
                    break
            _enrich._set_current_region("")
            result = {
                "dryRun": dry_run,
                "mode": mode_norm,
                "regions": list(region_list),
                "queued": queued_n,
                "ok": ok_n,
                "failed": fail_n,
                "cancelled": cancelled,
                "paused": paused,
                "parts": parts,
                "items": [
                    it
                    for p in parts
                    for it in (p.get("items") or [])
                ][:80],
            }
            with _enrich_lock:
                _enrich_job["result"] = _enrich._slim_result_for_status(result)
                if paused:
                    _enrich_job["phase"] = "paused"
                    _enrich_job["progress"] = {
                        **dict(_enrich_job.get("progress") or {}),
                        "stage": "done",
                        "label": "已暂停",
                    }
                    # 暂停保留 queue / current / checkpoints / logs
                elif cancelled:
                    _enrich_job["phase"] = "stopped"
                    _enrich_job["queue"] = []
                    _enrich_job["current"] = None
                    _enrich_job["progress"] = {
                        "stage": "cleared",
                        "percent": 0,
                        "done": 0,
                        "total": 0,
                        "label": "已停止 · 队列已清除 · 历史日志保留",
                    }
                else:
                    _enrich_job["phase"] = "done"
            if cancelled:
                for rid in region_list:
                    _enrich._queue_log_reopen_running(region=str(rid))
            _enrich._persist_enrich_runtime()
        except Exception as e:  # noqa: BLE001
            log.exception("scrap library enrich failed")
            with _enrich_lock:
                _enrich_job["error"] = str(e)
                _enrich_job["phase"] = "error"
                log_list = list(_enrich_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _enrich_job["log"] = log_list[-40:]
            _enrich._persist_enrich_runtime()
        finally:
            with _enrich_lock:
                _enrich_job["running"] = False
                _enrich_job["halt"] = None
                _enrich_job["cancel"] = False
            # 收尾/暂停/停止都要把攒批的日志落库（否则要等后台线程或进程退出）
            _enrich.flush_enrich_logs()
            try:
                enrich_mon.clear_job()
            except Exception:  # noqa: BLE001
                pass
            _enrich._persist_enrich_runtime()
            _enrich.notify_enrich_watchers(force=True)

    threading.Thread(target=run, name="scrap-library-enrich", daemon=True).start()
    return {"started": True, "resumed": bool(resume_map)}


