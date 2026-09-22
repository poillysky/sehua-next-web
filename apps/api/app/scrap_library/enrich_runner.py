# -*- coding: utf-8 -*-
"""Batch enrich runner (extracted from enrich.py)."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any

import app.scrap_library.embed as embed_svc
import app.scrap_library.enrich as _enrich
from app.scrap_library import enrich_monitor as enrich_mon
from app.scrap_library.enrich_runtime import (
    _enrich_job,
    _enrich_lock,
    _enrich_percent,
    _enrich_retry_front,
    _persist_enrich_runtime,
    _set_progress,
    notify_enrich_watchers,
)

log = logging.getLogger(__name__)

def run_enrich(
    *,
    region: str = "japan_censored",
    kinds: list[str] | None = None,
    limit: int = 0,
    dry_run: bool = False,
    mode: str = "incremental",
    resume: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode_raw = str(mode or "incremental").strip().lower()
    overwrite = mode_raw in {
        "overwrite",
        "cover",
        "force",
        "replace",
    }
    # I49：弱项重刮 = 缺口队列 + 强制写回（薄标题/空剧情/坏封面等）
    refresh_weak = mode_raw in {"refresh_weak", "weak", "refresh"}
    force_write = overwrite or refresh_weak
    kind_list = [k for k in (kinds or list(_enrich._DEFAULT_ENRICH_KINDS)) if k in _enrich._ENRICH_KINDS]
    if not kind_list:
        kind_list = list(_enrich._DEFAULT_ENRICH_KINDS)
    # limit<=0：全量；预览默认抽样 30
    raw_lim = int(limit) if limit is not None else 0
    if dry_run and raw_lim <= 0:
        lim = 30
    elif raw_lim <= 0:
        lim = 0  # 全量
    else:
        lim = max(1, min(20_000, raw_lim))
    lim_label = "全部" if lim <= 0 else str(lim)
    import app.scrape.sources_settings as scrape_src

    groups = scrape_src.enrich_groups_for_region(region)
    sources = _enrich._detail_sources(region=region)
    import app.scrap_library.enrich_strategy as strat

    cfg = strat.get_strategy()
    include_flare = bool(cfg.get("includeFlare", True))
    if not include_flare:
        sources = [s for s in sources if str(s.get("access") or "") != "proxy_flare"]
    src_label = " → ".join(
        f"{s.get('id')}({s.get('baseUrl') or '-'})" for s in sources
    ) or "(无启用源)"
    if overwrite:
        mode_label = "覆盖"
        mode_norm = "overwrite"
    elif refresh_weak:
        mode_label = "弱项重刮"
        mode_norm = "refresh_weak"
    else:
        mode_label = "增量"
        mode_norm = "incremental"

    resume_cp = resume if isinstance(resume, dict) else None
    # 预览（dryRun）永不续跑：
    # ① 预览本身不写检查点（见下方 _enrich._save_checkpoint 门禁）；
    # ② 一旦续跑，检查点的 queueInLog 会走 _enrich._rebuild_checkpoint_queue_from_log
    #    重建**整个分区**的 pending 队列（有码区实测 2 万+条），且该分支不设
    #    fetch_lim → limit 被无视，预览退化成全分区刮削（实测 2 条样本 >5 分钟）。
    # ③ 续跑会 pop 掉那个检查点，反把真实暂停任务的续跑状态吃掉。
    if dry_run and resume_cp is not None:
        log.info("enrich dry-run ignores checkpoint region=%s", region)
        resume_cp = None
    ok_n = int((resume_cp or {}).get("ok") or 0) if resume_cp else 0
    fail_n = int((resume_cp or {}).get("failed") or 0) if resume_cp else 0
    prior_done = int((resume_cp or {}).get("done") or 0) if resume_cp else 0
    original_total = 0
    live_feed = False
    feed_done = threading.Event()
    feed_done.set()
    queue_cv: threading.Condition | None = None
    queue: list[Any] = []

    if resume_cp and (
        list(resume_cp.get("queue") or [])
        or bool(resume_cp.get("queueInLog"))
        or int(resume_cp.get("remainingCount") or 0) > 0
    ):
        queue = [
            dict(r) for r in list(resume_cp.get("queue") or []) if isinstance(r, dict)
        ]
        rem_declared = int(resume_cp.get("remainingCount") or len(queue))
        # 队列表仍有未处理时强制重建，避免抽样检查点「刮完就停」
        try:
            db_pending = int(_enrich._queue_log_status_counts(region, fresh=True).get("pending") or 0)
        except Exception:  # noqa: BLE001
            db_pending = 0
        if (
            bool(resume_cp.get("queueInLog"))
            or rem_declared > len(queue)
            or db_pending > len(queue)
        ):
            from_log = _enrich._rebuild_checkpoint_queue_from_log(region)
            if from_log:
                queue = from_log
                rem_declared = max(rem_declared, db_pending, len(queue))
        original_total = int(
            resume_cp.get("originalTotal")
            or (prior_done + max(len(queue), rem_declared, db_pending))
        )
        _enrich._push_log(
            f"继续 · {mode_label} · {region or '全部'} · "
            f"已完成 {prior_done}/{original_total} · 剩余 {len(queue)}",
            region=region,
        )
        _enrich._push_log(
            f"策略 · {cfg.get('mode')} · 过盾={'开' if include_flare else '关'} · "
            f"分组 · {'+'.join(groups) or '-'} · 数据源 · {src_label}",
            region=region,
        )
    else:
        resume_cp = None
        _enrich._push_log(
            f"{'预览' if dry_run else '补齐'} · {mode_label} · {region or '全部'} · "
            f"{'全量' if overwrite else 'kinds=' + ','.join(kind_list)} · limit={lim_label}",
            region=region,
        )
        _enrich._push_log(
            f"策略 · {cfg.get('mode')} · 过盾={'开' if include_flare else '关'} · "
            f"分组 · {'+'.join(groups) or '-'} · 数据源 · {src_label}",
            region=region,
        )
        _set_progress(
            stage="queue",
            percent=0,
            label="全量队列" if overwrite else ("弱项队列" if refresh_weak else "筛选缺口"),
            done=0,
            total=0,
            ok=0,
            failed=0,
        )

        queue = []
        fetch_lim = 0 if lim <= 0 else lim
        live_feed = False
        feed_done = threading.Event()
        feed_done.set()
        queue_cv: threading.Condition | None = None

        if overwrite:
            # 覆盖：本地分区全部 NFO（一次性入队）
            scan_label = "读全量队列…"
            _set_progress(stage="queue", label=scan_label, done=0, total=0)
            hb_stop = threading.Event()

            def _scan_heartbeat() -> None:
                t0 = time.perf_counter()
                while not hb_stop.wait(1.5):
                    sec = int(time.perf_counter() - t0)
                    _set_progress(
                        stage="queue",
                        label=f"{scan_label} {sec}s",
                        done=0,
                        total=0,
                    )

            hb_th = threading.Thread(
                target=_scan_heartbeat, name="enrich-queue-hb", daemon=True
            )
            hb_th.start()
            try:
                from app.scrap_library import embed as _emb

                _root = _emb.resolve_root(_emb.get_settings().get("root")).resolve()
                _dirs = _enrich._region_local_dirs(_root, region)
                _seen_o: set[str] = set()
                for _base in _dirs:
                    try:
                        _nfo_it = _base.rglob("*.nfo")
                    except Exception:  # noqa: BLE001
                        continue
                    for _nfo in _nfo_it:
                        _folder = _nfo.parent
                        try:
                            _rel = _folder.relative_to(_root).as_posix()
                        except ValueError:
                            continue
                        if _rel in _seen_o:
                            continue
                        _seen_o.add(_rel)
                        _code, _ = _enrich._local_folder_gaps(_folder)
                        queue.append(
                            {
                                "itemId": _rel,
                                "code": _code,
                                "gaps": list(_enrich._ENRICH_KINDS),
                                "rel_path": _rel,
                                "relPath": _rel,
                                "region": region,
                            }
                        )
                        if fetch_lim > 0 and len(queue) >= fetch_lim:
                            break
                    if fetch_lim > 0 and len(queue) >= fetch_lim:
                        break
                _enrich._push_log("队列来源 · 本地 NFO（覆盖）", region=region)
            finally:
                hb_stop.set()
                try:
                    hb_th.join(timeout=0.2)
                except Exception:  # noqa: BLE001
                    pass
            original_total = len(queue)
            prior_done = 0
            ok_n = 0
            fail_n = 0
            _enrich._push_log(f"队列 {len(queue)} 条", region=region)
        else:
            # 增量/弱项：边扫边刮——扫描线程分批入队，worker 立刻开刮。
            # ⚠️ 禁止在开刮前同步 demote / 全量 done-keys：会卡数分钟，
            # UI 显示 running 但「处理中=0」。队列表已有 pending 优先入队；
            # done-keys 在首批入队后再懒加载，只影响后续骨架/向量切片去重。
            skip_done_iids: set[str] = set()
            skip_done_codes: set[str] = set()
            skip_ready = threading.Event()

            def _load_skip_done() -> None:
                try:
                    iids, codes = _enrich._queue_log_done_keys(region)
                    skip_done_iids.clear()
                    skip_done_iids.update(iids)
                    skip_done_codes.clear()
                    skip_done_codes.update(
                        str(c).strip().upper()
                        for c in codes
                        if str(c).strip()
                    )
                except Exception as e:  # noqa: BLE001
                    log.warning("enrich load done keys failed: %s", e)
                finally:
                    skip_ready.set()

            threading.Thread(
                target=_load_skip_done,
                name=f"done-keys-{region}",
                daemon=True,
            ).start()
            try:
                if region not in _enrich._demoted_false_dones:
                    threading.Thread(
                        target=_enrich._queue_log_demote_false_dones_budgeted,
                        kwargs={"region": region, "time_budget_sec": 5.0},
                        name=f"demote-bg-{region}",
                        daemon=True,
                    ).start()
            except Exception as e:  # noqa: BLE001
                log.warning("enrich start demote schedule failed: %s", e)
            try:
                lib = _enrich._region_library_progress(region)
                est_total = max(int(lib.get("incomplete") or 0), 1)
            except Exception:  # noqa: BLE001
                est_total = 0
            original_total = est_total
            prior_done = 0
            ok_n = 0
            fail_n = 0
            queue = []
            live_feed = True
            feed_done = threading.Event()
            queue_cv = threading.Condition()
            _enrich._push_log(
                f"边扫边刮 · 预估未处理 {est_total} · 扫描与刮削并行",
                region=region,
            )
            _set_progress(
                stage="enrich",
                label="扫描入队中 · 刮削并行…",
                done=0,
                total=est_total,
                ok=0,
                failed=0,
            )

            def _feed_loop() -> None:
                fed = 0
                try:
                    # 首批只用队列表 pending（不依赖 done-keys）；之后等 skip 就绪再扫骨架
                    for batch in _enrich.iter_enrich_pending_batches(
                        region=region,
                        batch_size=200,
                        limit=fetch_lim if fetch_lim > 0 else 0,
                        skip_item_ids=skip_done_iids,
                        skip_codes=skip_done_codes,
                        defer_skip_until=skip_ready,
                    ):
                        if _enrich._halt_kind():
                            break
                        view_batch: list[dict[str, Any]] = []
                        for r in batch:
                            if not isinstance(r, dict):
                                continue
                            iid = str(r.get("itemId") or "").strip()
                            if not iid:
                                continue
                            item: dict[str, Any] = {
                                "itemId": iid,
                                "code": str(r.get("code") or "").strip().upper(),
                                "gaps": list(r.get("gaps") or []),
                                "status": "pending",
                                "region": str(r.get("region") or region),
                            }
                            rel = str(r.get("rel_path") or r.get("relPath") or "")
                            if rel:
                                item["rel_path"] = rel
                                item["relPath"] = rel
                            view_batch.append(item)
                        if not view_batch:
                            continue
                        view_batch = _enrich._ensure_queue_log_ids(
                            region, view_batch, persist=not dry_run
                        )
                        with queue_cv:
                            base_i = len(queue)
                            for j, vr in enumerate(view_batch):
                                row = dict(vr)
                                row["index"] = prior_done + base_i + j
                                if not str(row.get("region") or "").strip():
                                    row["region"] = region
                                queue.append(row)
                            fed = len(queue)
                            queue_cv.notify_all()
                        # 勿在 queue_cv 内嵌套 _enrich_lock（会死锁卡死清空/状态接口）
                        with _enrich_lock:
                            qv = list(_enrich_job.get("queue") or [])
                            qv.extend(view_batch)
                            # 裁展示队列时留下 status=running，避免进行中被首尾窗口挤掉
                            _enrich_job["queue"] = _enrich._cap_status_queue(qv)
                            qc = dict(_enrich_job.get("queueCounts") or {})
                            qc["pending"] = max(
                                int(qc.get("pending") or 0),
                                max(
                                    0,
                                    fed
                                    - int(qc.get("done") or 0)
                                    - int(qc.get("fail") or 0)
                                    - int(qc.get("running") or 0),
                                ),
                            )
                            _enrich_job["queueCounts"] = qc
                        _set_progress(
                            stage="enrich",
                            label=f"边扫边刮 · 已入队 {fed}"
                            + (f"/{est_total}" if est_total else ""),
                            done=0,
                            total=max(est_total, fed),
                        )
                        _enrich.notify_enrich_watchers()
                        if fetch_lim > 0 and fed >= fetch_lim:
                            break
                except Exception as e:  # noqa: BLE001
                    log.warning("enrich feed loop failed: %s", e)
                    _enrich._push_log(f"扫描入队异常 · {e}", region=region)
                finally:
                    feed_done.set()
                    with queue_cv:
                        queue_cv.notify_all()
                    _enrich._push_log(f"扫描入队结束 · 共 {len(queue)} 条", region=region)

            feed_th = threading.Thread(
                target=_feed_loop, name="enrich-feed", daemon=True
            )
            feed_th.start()
            with queue_cv:
                if not queue:
                    queue_cv.wait(timeout=2.0)
            if queue:
                _enrich._push_log(
                    f"刮削已启动 · 队列 {len(queue)}（只消费未处理队列表，不再扫盘）",
                    region=region,
                )
            else:
                _enrich._push_log(
                    "刮削已启动 · 等待未处理入队…",
                    region=region,
                )

    # 历史脏数据清理改后台：同步跑会挡 worker 占槽（处理中一直 0）
    if not dry_run:

        def _prune_bg() -> None:
            try:
                cleaned = _enrich._queue_log_prune_open_if_done(region)
                if cleaned:
                    _enrich._push_log(f"清理成功残留未处理 {cleaned}", region=region)
                cleaned_run = _enrich._queue_log_prune_pending_if_running(region)
                if cleaned_run:
                    _enrich._push_log(f"清理处理中残留未处理 {cleaned_run}", region=region)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(
            target=_prune_bg, name=f"prune-open-{region}", daemon=True
        ).start()

    if not live_feed:
        queue_view: list[dict[str, Any]] = []
        for i, r in enumerate(queue):
            if not isinstance(r, dict):
                continue
            item: dict[str, Any] = {
                "index": prior_done + i,
                "itemId": str(r.get("itemId") or ""),
                "code": str(r.get("code") or "").strip().upper(),
                "gaps": list(r.get("gaps") or []),
                "status": "pending",
                "region": str(r.get("region") or region or ""),
            }
            lid = _enrich._queue_log_int_id(r)
            if lid:
                item["logId"] = lid
            rel = str(r.get("rel_path") or r.get("relPath") or "")
            if rel:
                item["rel_path"] = rel
                item["relPath"] = rel
            queue_view.append(item)
            if not str(r.get("region") or "").strip():
                queue[i] = dict(r)
                queue[i]["region"] = region
        queue_view = _enrich._ensure_queue_log_ids(region, queue_view, persist=not dry_run)
        for i, vr in enumerate(queue_view):
            if i < len(queue) and isinstance(queue[i], dict):
                lid = _enrich._queue_log_int_id(vr)
                if lid:
                    queue[i] = dict(queue[i])
                    queue[i]["logId"] = lid
                if not str(queue[i].get("region") or "").strip():
                    queue[i]["region"] = region
        _enrich._set_queue(queue_view)
        original_total = int(prior_done or 0) + len(queue_view)
        _set_progress(
            stage="enrich",
            label=f"处理 {prior_done}/{original_total}"
            if prior_done
            else f"队列 {len(queue_view)}",
            ok=ok_n,
            failed=fail_n,
        )
    else:
        # feeder 已写 queue / UI；original_total 用库预估，后续随入队抬升
        original_total = max(int(original_total or 0), len(queue), 1)
        _set_progress(
            stage="enrich",
            label=f"边扫边刮 · 队列 {len(queue)}",
            ok=ok_n,
            failed=fail_n,
            total=original_total,
        )

    results: list[dict[str, Any]] = []
    cancelled = False
    paused = False
    halt_at = -1
    results_lock = threading.Lock()
    counters_lock = threading.Lock()
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    # 预览（dryRun）：只算不写。所有 enrich_queue_log 写入一律关掉，
    # 否则预览会把行标成 done/running，被剪枝吃掉真正的待处理行。
    persist_db = not bool(dry_run)

    def _finish_one(i: int, row: dict[str, Any], one: dict[str, Any] | None, exc: BaseException | None) -> None:
        nonlocal ok_n, fail_n
        # 暂停/停止：进行中已退回未处理；但仍把已算出的结果落库，避免刷新丢详情
        halted = _enrich._halt_kind() in {"pause", "stop"}
        code_u = str(row.get("code") or "").strip().upper()
        gaps = list(row.get("gaps") or [])
        abs_i = prior_done + i
        if exc is not None:
            if not halted:
                with counters_lock:
                    fail_n += 1
                    cur_ok, cur_fail = ok_n, fail_n
                with results_lock:
                    results.append({"code": row.get("code"), "ok": False, "error": str(exc)})
                    if len(results) > int(_enrich._RESULTS_MEM_CAP):
                        del results[: len(results) - int(_enrich._RESULTS_MEM_CAP)]
                _enrich._patch_queue_item(
                    i, match=row, persist=persist_db, status="fail", error=str(exc)[:120]
                )
                _enrich._set_current(
                    {
                        "code": code_u,
                        "itemId": str(row.get("itemId") or ""),
                        "gaps": gaps,
                        "status": "fail",
                        "index": abs_i,
                        "total": original_total,
                        "ok": False,
                        "error": str(exc),
                        "sourceTimings": [],
                        "fields": [],
                    }
                )
                _enrich._push_log(f"{row.get('code')}: {exc}", region=region)
                _set_progress(
                    stage="enrich",
                    label=f"处理 {prior_done + cur_ok + cur_fail}/{original_total}",
                    ok=cur_ok,
                    failed=cur_fail,
                )
            else:
                if persist_db:
                    _enrich._queue_log_update_row(
                        {
                            **dict(row),
                            "status": "fail",
                            "error": str(exc)[:120],
                            "code": code_u,
                        },
                        region=region,
                    )
            return

        assert one is not None
        # 落库前再验盘：标成功但无 NFO/合格海报 → 降为失败
        # 预览（dryRun）跳过：预览按定义不落盘，验盘必然失败，
        # 会把「将被补齐」的行全报成失败，误导判读。
        if one.get("ok") and persist_db:
            folder = _enrich._resolve_enrich_folder(
                region=region,
                code=code_u,
                item_id=str(row.get("itemId") or ""),
            )
            rel = str(row.get("rel_path") or row.get("relPath") or "").strip()
            if folder is None and rel:
                try:
                    settings = embed_svc.get_settings()
                    root = embed_svc.resolve_root(settings.get("root"))
                    cand = (root / rel.replace("\\", "/")).resolve()
                    cand.relative_to(root.resolve())
                    if cand.is_dir():
                        folder = cand
                except Exception:  # noqa: BLE001
                    folder = None
            if folder is None or not _enrich._local_success_disk_ok(folder):
                one["ok"] = False
                one["partialOk"] = False
                one["error"] = str(one.get("error") or "仍缺:封面 · 落盘校验失败")[
                    :120
                ]
                one["gapsAfter"] = list(one.get("gapsAfter") or ["no_local"])
                _enrich._push_log(
                    f"{code_u} · 成功回滚 · 落盘校验失败",
                    region=region,
                )
        # 有界重试记账（封面重试上限 / 源故障补抓）；预览不落库 → 必须跳过
        if persist_db and not bool(one.get("dryRun")):
            try:
                _enrich._note_retry_hints(region=region, code=code_u, row=row, one=one)
            except Exception as e:  # noqa: BLE001
                log.debug("retry hint note failed code=%s: %s", code_u, e)
        st = "done" if one.get("ok") else "fail"
        gaps_after = list(one.get("gapsAfter") or [])
        patch = {
            "status": st,
            "error": str(one.get("error") or "")[:120],
            "source": str(one.get("source") or ""),
            "fetchMs": one.get("fetchMs"),
            "coverMs": one.get("coverMs"),
            "actressMs": one.get("actressMs"),
            "vectorMs": one.get("vectorMs"),
            "totalMs": one.get("totalMs"),
            "detailTitle": str(one.get("detailTitle") or "")[:200],
            "actors": one.get("actors"),
            "nfoChanged": bool(one.get("nfoChanged")),
            "posterDownloaded": bool(one.get("posterDownloaded")),
            "vectorSynced": bool(one.get("vectorSynced")),
            "vectorSkipped": bool(one.get("vectorSkipped")),
            "vectorError": str(one.get("vectorError") or "")[:120],
            "sourceTimings": list(one.get("sourceTimings") or []),
            "fields": list(one.get("fields") or []),
            "wouldFill": one.get("wouldFill"),
            "partialOk": bool(one.get("partialOk")),
            "gapsAfter": gaps_after,
            # 必须始终回写 gaps：成功且 gapsAfter=[] 时要清空刮前的 no_local，
            # 否则内存队列/库 gaps_json 仍显示「缺封面」
            "gaps": gaps_after,
        }
        if not halted:
            _enrich._patch_queue_item(i, match=row, persist=persist_db, **patch)
        if persist_db:
            # 强制落库：用提交时 row 的 logId/番号（暂停时也写）
            persist = dict(row)
            persist.update(patch)
            persist["code"] = code_u or str(persist.get("code") or "")
            persist["itemId"] = str(
                persist.get("itemId") or row.get("itemId") or ""
            )
            try:
                new_lid = _enrich._queue_log_update_row(persist, region=region)
                if st == "done":
                    _iid2 = str(persist.get("itemId") or "")

                    def _prune_open_bg2() -> None:
                        try:
                            _enrich._queue_log_prune_open_if_done(
                                region, code=code_u, item_id=_iid2
                            )
                        except Exception:  # noqa: BLE001
                            pass

                    threading.Thread(
                        target=_prune_open_bg2,
                        name=f"prune-open2-{code_u or 'x'}",
                        daemon=True,
                    ).start()
                if (
                    new_lid
                    and not halted
                    and int(new_lid) != _enrich._queue_log_int_id(persist)
                ):
                    with _enrich_lock:
                        q = list(_enrich_job.get("queue") or [])
                        if 0 <= i < len(q):
                            q[i] = {**dict(q[i] or {}), "logId": int(new_lid)}
                            _enrich_job["queue"] = q
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "force persist enrich queue failed code=%s: %s", code_u, e
                )
        if halted:
            return
        _enrich._set_current(
            {
                "code": code_u,
                "itemId": str(row.get("itemId") or ""),
                "gaps": gaps,
                "status": st,
                "index": abs_i,
                "total": original_total,
                "ok": bool(one.get("ok")),
                "error": one.get("error"),
                "source": one.get("source"),
                "detailTitle": one.get("detailTitle"),
                "fetchMs": one.get("fetchMs"),
                "coverMs": one.get("coverMs"),
                "actressMs": one.get("actressMs"),
                "vectorMs": one.get("vectorMs"),
                "totalMs": one.get("totalMs"),
                "actors": one.get("actors"),
                "nfoChanged": one.get("nfoChanged"),
                "posterDownloaded": one.get("posterDownloaded"),
                "vectorSynced": bool(one.get("vectorSynced")),
                "vectorSkipped": bool(one.get("vectorSkipped")),
                "vectorError": one.get("vectorError"),
                "sourceTimings": list(one.get("sourceTimings") or []),
                "fields": list(one.get("fields") or []),
                "wouldFill": one.get("wouldFill"),
                "partialOk": bool(one.get("partialOk")),
                "gapsAfter": list(one.get("gapsAfter") or []),
            }
        )
        with results_lock:
            results.append(_enrich._slim_one_result_mem(one))
            if len(results) > int(_enrich._RESULTS_MEM_CAP):
                del results[: len(results) - int(_enrich._RESULTS_MEM_CAP)]
        if one.get("ok"):
            with counters_lock:
                ok_n += 1
                cur_ok, cur_fail = ok_n, fail_n
            if one.get("vectorSynced"):
                _enrich._push_log(f"{code_u} · 完成（刮削+向量）", region=region)
            elif one.get("vectorSkipped"):
                _enrich._push_log(f"{code_u} · 完成（仅本地）", region=region)
            if persist_db:
                _enrich._maybe_prune_done_logs(region)
        else:
            with counters_lock:
                fail_n += 1
                cur_ok, cur_fail = ok_n, fail_n
            _enrich._push_log(
                f"{one.get('code') or code_u}: {one.get('error') or 'fail'}",
                region=region,
            )
            if persist_db:
                _enrich._maybe_prune_done_logs(region)
        _set_progress(
            stage="enrich",
            label=f"处理 {prior_done + cur_ok + cur_fail}/{original_total}",
            ok=cur_ok,
            failed=cur_fail,
        )

    def _run_one(i: int, row: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any] | None, BaseException | None]:
        if _enrich._halt_kind():
            return i, row, None, None
        code_u = str(row.get("code") or "").strip().upper()
        item_id = str(row.get("itemId") or "")
        gaps = list(row.get("gaps") or [])
        abs_i = prior_done + i
        _enrich._patch_queue_item(i, match=row, persist=persist_db, status="running")
        if _enrich._halt_kind():
            return i, row, None, None
        try:
            enrich_mon.item_start(code=code_u, item_id=item_id, region=region)
            enrich_mon.set_phase(code=code_u, item_id=item_id, phase="fetch")
            _enrich.notify_enrich_watchers(force=True)
        except Exception:  # noqa: BLE001
            pass
        _enrich._set_current(
            {
                "code": code_u,
                "itemId": item_id,
                "gaps": gaps,
                "status": "running",
                "index": abs_i,
                "total": original_total,
            }
        )
        _set_progress(
            stage="enrich",
            label=f"处理 {code_u or abs_i + 1}",
            ok=ok_n,
            failed=fail_n,
        )
        try:
            one = _enrich.enrich_one_row(
                row,
                dry_run=dry_run,
                # 源故障补抓行：必须允许覆盖写回。`_enrich.merge_nfo_with_detail` 默认只补
                # 空字段，否则「降级取值」写进 NFO 的差字段永远不会被高优先源的
                # 好值替换 —— 那样补抓就白跑了。
                overwrite=force_write or bool(row.get("overwrite")),
                # 分区批量：只写 NFO/封面；元库/向量用「同步数据库」「数据库向量化」
                sync_vector=False,
            )
            try:
                enrich_mon.item_end(
                    code=code_u,
                    item_id=item_id,
                    ok=bool(one and one.get("ok")),
                    fetch_ms=int((one or {}).get("fetchMs") or 0) or None,
                    error=str((one or {}).get("error") or ""),
                )
                _enrich.notify_enrich_watchers(force=True)
            except Exception:  # noqa: BLE001
                pass
            return i, row, one, None
        except BaseException as e:  # noqa: BLE001
            try:
                enrich_mon.item_end(
                    code=code_u,
                    item_id=item_id,
                    ok=False,
                    error=str(e)[:120],
                )
                _enrich.notify_enrich_watchers(force=True)
            except Exception:  # noqa: BLE001
                pass
            return i, row, None, e

    def _abort_inflight_now() -> None:
        for fut in list(inflight.keys()):
            try:
                fut.cancel()
            except Exception:  # noqa: BLE001
                pass
        inflight.clear()

    def _remaining_for_pause() -> list[dict[str, Any]]:
        """未完成（含进行中）→ 检查点未处理队列。优先用 pause API 已写好的。"""
        with _enrich_lock:
            cps = dict(_enrich_job.get("checkpoints") or {})
            cp = cps.get(region) if isinstance(cps.get(region), dict) else None
            if cp and isinstance(cp.get("queue"), list) and cp.get("queue"):
                return [dict(r) for r in cp["queue"] if isinstance(r, dict)]
            view = [
                dict(r)
                for r in list(_enrich_job.get("queue") or [])
                if isinstance(r, dict)
            ]
        remaining_by_id: dict[str, dict[str, Any]] = {}
        for r in view:
            st = str(r.get("status") or "pending")
            if st in {"done", "fail"}:
                continue
            key = str(r.get("itemId") or r.get("code") or "").strip()
            if not key:
                continue
            remaining_by_id[key] = {
                "itemId": str(r.get("itemId") or ""),
                "code": str(r.get("code") or ""),
                "gaps": list(r.get("gaps") or []),
                "rel_path": str(r.get("rel_path") or r.get("relPath") or ""),
                "relPath": str(r.get("relPath") or r.get("rel_path") or ""),
                "region": region,
            }
            lid = _enrich._queue_log_int_id(r)
            if lid:
                remaining_by_id[key]["logId"] = lid
        for r in queue[next_i:]:
            if not isinstance(r, dict):
                continue
            key = str(r.get("itemId") or r.get("code") or "").strip()
            if key and key not in remaining_by_id:
                remaining_by_id[key] = dict(r)
        return list(remaining_by_id.values())

    workers = max(1, int(_enrich._ITEM_WORKERS_DEFAULT))
    try:
        import app.scrap_library.enrich_strategy as strat

        cfg_w = int(strat.get_strategy().get("itemWorkers") or _enrich._ITEM_WORKERS_DEFAULT)
        from app.core.container_budget import cap_parallel

        workers = cap_parallel(
            max(1, min(int(_enrich._ITEM_WORKERS_MAX), cfg_w)),
            tight=2,
            small=4,
            hard=int(_enrich._ITEM_WORKERS_MAX),
        )
    except Exception:  # noqa: BLE001
        from app.core.container_budget import cap_parallel as _cap_workers

        workers = _cap_workers(
            workers, tight=2, small=4, hard=int(_enrich._ITEM_WORKERS_MAX)
        )
    # 出站槽必须与「同时处理的番号数」同步（第十七轮 D5）。
    # 只在本处（任务启动前、无在飞请求）应用：把 page/api 全局槽从
    # 「手工凑的 24+12」换成按 itemWorkers 推导，扩容从此只需改策略一处。
    cfg_workers = int(workers)
    try:
        from app.core.outbound_scheduler import get_scheduler as _get_sched

        _get_sched().apply_item_workers(cfg_workers)
    except Exception as e:  # noqa: BLE001
        log.warning("apply outbound caps failed: %s", e)
    # 非边扫：初始 worker 数不超过当前队列；边扫时队列会涨
    if not live_feed:
        workers = max(1, min(workers, len(queue) or 1))
    try:
        import app.scrap_library.enrich_strategy as strat_to

        timeout_sec = int(
            strat_to.get_strategy().get("perSourceTimeoutSec") or 28
        )
    except Exception:  # noqa: BLE001
        timeout_sec = 28
    try:
        enrich_mon.reset_job(
            region=region,
            item_workers=workers,
            per_source_timeout_sec=timeout_sec,
        )
        _enrich.notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    _enrich._push_log(f"并发番号 · {workers} · 封面池 {_enrich._cover_job_workers_target()}", region=region)
    next_i = 0
    inflight: dict[Any, int] = {}
    # 「请求并发超出出站槽档位」只提示一次，避免每轮刷屏
    _outbound_cap_warned = False
    # 池按上限开；循环内按最新 itemWorkers 节流，改策略后下一轮投递即生效
    pool_cap = int(workers)
    from app.core.container_budget import memory_class as _mem_class

    if _mem_class() == "host":
        pool_cap = max(workers, int(_enrich._ITEM_WORKERS_MAX))
    pool = ThreadPoolExecutor(
        max_workers=pool_cap, thread_name_prefix="enrich-item"
    )
    try:
        while True:
            # 热读并发：保存策略后无需重启任务。
            # ⚠️ 但派发上限不得越过「已经按规模算好的出站槽」（`cfg_workers`）：
            # 飞行中换信号量不安全（已持旧对象的线程会 release 到孤儿上），
            # 所以抬 itemWorkers 需要重开任务；此处只做封顶，避免 2× 超订。
            try:
                import app.scrap_library.enrich_strategy as strat_live

                cfg_live = int(
                    strat_live.get_strategy().get("itemWorkers")
                    or _enrich._ITEM_WORKERS_DEFAULT
                )
                want_w = max(1, min(pool_cap, cfg_live))
                if want_w > cfg_workers:
                    if not _outbound_cap_warned:
                        _outbound_cap_warned = True
                        _enrich._push_log(
                            f"并发番号请求 {want_w} 超出出站槽档位 {cfg_workers} · "
                            f"已封顶（重开任务后生效）",
                            region=region,
                        )
                    want_w = cfg_workers
                if want_w != workers:
                    workers = want_w
                    _enrich._push_log(f"并发番号热更新 · {workers}", region=region)
            except Exception:  # noqa: BLE001
                pass
            with _enrich_lock:
                has_retry = bool(_enrich_retry_front)
            # 边扫边刮：扫描未结束时队列空也继续等
            feeding = bool(live_feed and not feed_done.is_set())
            if not (next_i < len(queue) or inflight or has_retry or feeding):
                break
            halt = _enrich._halt_kind()
            if halt:
                # 立刻停投递、取消未开始、丢弃在飞（不 _finish_one）
                halt_at = next_i
                _abort_inflight_now()
                if halt == "pause":
                    paused = True
                    remaining = _remaining_for_pause()
                    with counters_lock:
                        cur_ok, cur_fail = ok_n, fail_n
                    # 暂停时抬升 original_total，避免检查点比已入队小
                    ot = max(int(original_total or 0), prior_done + cur_ok + cur_fail + len(remaining))
                    # 预览不写检查点：否则会用「预览队列」覆盖真实暂停任务的续跑队列
                    if not dry_run:
                        _enrich._save_checkpoint(
                            region,
                            {
                                "region": region,
                                "mode": mode_norm,
                                "kinds": list(kind_list),
                                "dryRun": bool(dry_run),
                                "queue": remaining,
                                "ok": cur_ok,
                                "failed": cur_fail,
                                "done": prior_done + cur_ok + cur_fail,
                                "originalTotal": ot,
                            },
                        )
                    _enrich._push_log(
                        f"已暂停 · 进行中已退回未处理 · 剩余 {len(remaining)}",
                        region=region,
                    )
                else:
                    cancelled = True
                    _enrich._clear_checkpoint(region)
                    _enrich._clear_runtime_queue()
                    _enrich._queue_log_reopen_running(region=region)
                    log.info(
                        "enrich stopped region=%s done=%s/%s",
                        region,
                        prior_done + next_i,
                        original_total,
                    )
                break

            while len(inflight) < workers:
                if _enrich._halt_kind():
                    break
                # 失败重试优先：追加到队列尾投递（不挪动已在飞下标）
                row_retry: dict[str, Any] | None = None
                with _enrich_lock:
                    if _enrich_retry_front:
                        cand = _enrich_retry_front.pop(0)
                        if isinstance(cand, dict):
                            row_retry = dict(cand)
                if row_retry is not None:
                    key = str(
                        row_retry.get("itemId") or row_retry.get("code") or ""
                    ).strip()
                    dup = False
                    if key:
                        for r in queue[next_i:]:
                            if not isinstance(r, dict):
                                continue
                            if (
                                str(r.get("itemId") or r.get("code") or "").strip()
                                == key
                            ):
                                dup = True
                                break
                    if dup:
                        continue
                    idx = len(queue)
                    queue.append(row_retry)
                    view_row: dict[str, Any] = {
                        "index": prior_done + idx,
                        "itemId": str(row_retry.get("itemId") or ""),
                        "code": str(row_retry.get("code") or "").strip().upper(),
                        "gaps": list(row_retry.get("gaps") or []),
                        "status": "pending",
                        "region": region,
                    }
                    lid = _enrich._queue_log_int_id(row_retry)
                    if lid:
                        view_row["logId"] = lid
                    rel = str(
                        row_retry.get("rel_path") or row_retry.get("relPath") or ""
                    )
                    if rel:
                        view_row["rel_path"] = rel
                        view_row["relPath"] = rel
                    with _enrich_lock:
                        qv = list(_enrich_job.get("queue") or [])
                        qv.append(view_row)
                        _enrich_job["queue"] = qv
                    fut = pool.submit(_run_one, idx, row_retry)
                    inflight[fut] = idx
                    continue

                if next_i >= len(queue):
                    # 扫描还在：等下一批，不退出
                    if live_feed and not feed_done.is_set() and queue_cv is not None:
                        with queue_cv:
                            if next_i >= len(queue) and not feed_done.is_set():
                                queue_cv.wait(timeout=0.5)
                        break
                    break
                idx = next_i
                row = queue[idx]
                next_i += 1
                # 边扫时随入队抬升总量，进度条不倒退
                if live_feed:
                    original_total = max(int(original_total or 0), len(queue), next_i)
                fut = pool.submit(_run_one, idx, row)
                inflight[fut] = idx

            if not inflight:
                with _enrich_lock:
                    if _enrich_retry_front:
                        continue
                if live_feed and not feed_done.is_set():
                    if queue_cv is not None:
                        with queue_cv:
                            if next_i >= len(queue) and not feed_done.is_set():
                                queue_cv.wait(timeout=0.5)
                    continue
                break
            # 短超时轮询 halt，避免卡在 wait 里暂停不生效
            done_set, _ = wait(
                list(inflight.keys()),
                timeout=0.25,
                return_when=FIRST_COMPLETED,
            )
            if not done_set:
                continue
            for fut in done_set:
                inflight.pop(fut, None)
                try:
                    i, row, one, exc = fut.result()
                except BaseException:  # noqa: BLE001
                    continue
                if one is None and exc is None:
                    continue
                _finish_one(i, row, one, exc)
    finally:
        # 暂停/停止：不等在飞线程，避免开关卡住
        try:
            pool.shutdown(wait=not (paused or cancelled), cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=not (paused or cancelled))

    if not dry_run and not paused and not cancelled:
        # 内存队列跑完但队列表仍有 pending：不算真完成，留检查点可继续
        try:
            db_pending = int(_enrich._queue_log_status_counts(region, fresh=True).get("pending") or 0)
        except Exception:  # noqa: BLE001
            db_pending = 0
        if db_pending > 0:
            _enrich._save_checkpoint(
                region,
                {
                    "region": region,
                    "mode": mode_norm,
                    "kinds": list(kind_list),
                    "dryRun": bool(dry_run),
                    "queue": [],
                    "ok": ok_n,
                    "failed": fail_n,
                    "done": prior_done + ok_n + fail_n,
                    "originalTotal": max(
                        int(original_total or 0),
                        prior_done + ok_n + fail_n + db_pending,
                    ),
                    "remainingCount": db_pending,
                    "queueInLog": True,
                },
            )
            paused = True
            _enrich._push_log(
                f"本轮队列已空 · 库内仍有未处理 {db_pending} · 已暂停可继续",
                region=region,
            )
        else:
            _enrich._clear_checkpoint(region)

    summary = {
        "dryRun": dry_run,
        "mode": mode_norm,
        "region": region,
        "groups": list(groups),
        "kinds": kind_list,
        "queued": original_total,
        # 本区**实际处理条数**。多区调度要用它扣减跨区 limit 预算：
        # `queued` 在增量模式下是库内待处理预估（有码区十万级），
        # 拿它扣减会让首个分区一口吃光整个 limit，后续分区全被跳过。
        "processed": ok_n + fail_n,
        "ok": ok_n,
        "failed": fail_n,
        "cancelled": cancelled,
        "paused": paused,
        "remaining": (
            len(queue[halt_at:])
            if (paused or cancelled) and halt_at >= 0
            else (
                int(_enrich._queue_log_status_counts(region, fresh=True).get("pending") or 0)
                if paused
                else 0
            )
        ),
        "sources": [
            {
                "id": s.get("id"),
                "label": s.get("label"),
                "group": s.get("group"),
                "baseUrl": s.get("baseUrl"),
            }
            for s in sources
        ],
        "items": results[:80],
    }
    if paused:
        try:
            dbc = _enrich._queue_log_status_counts(region, fresh=True)
            fin = int(dbc.get("done") or 0) + int(dbc.get("fail") or 0)
            rem = int(dbc.get("pending") or 0)
            _set_progress(
                stage="done",
                label="已暂停" if halt_at < 0 else "已暂停",
                ok=int(dbc.get("done") or ok_n),
                failed=int(dbc.get("fail") or fail_n),
                done=fin,
                total=max(fin + rem, int(original_total or 0)),
            )
            with _enrich_lock:
                _enrich_job["queueCounts"] = {
                    "pending": rem,
                    "running": 0,
                    "done": int(dbc.get("done") or 0),
                    "fail": int(dbc.get("fail") or 0),
                }
        except Exception:  # noqa: BLE001
            _set_progress(
                stage="done",
                label="已暂停",
                ok=ok_n,
                failed=fail_n,
            )
        _enrich._push_log(f"已暂停 · 成功 {ok_n} · 失败 {fail_n}", region=region)
    elif cancelled:
        _set_progress(
            stage="cleared",
            percent=0,
            label="已停止",
            done=0,
            total=0,
            ok=0,
            failed=0,
        )
        # 日志已随队列清掉，不再写入
    else:
        try:
            dbc = _enrich._queue_log_status_counts(region, fresh=True)
            with _enrich_lock:
                _enrich_job["queueCounts"] = {
                    "pending": int(dbc.get("pending") or 0),
                    "running": 0,
                    "done": int(dbc.get("done") or 0),
                    "fail": int(dbc.get("fail") or 0),
                }
            _set_progress(
                stage="done",
                label="完成",
                ok=int(dbc.get("done") or ok_n),
                failed=int(dbc.get("fail") or fail_n),
                done=int(dbc.get("done") or 0) + int(dbc.get("fail") or 0),
                total=max(
                    int(original_total or 0),
                    int(dbc.get("done") or 0) + int(dbc.get("fail") or 0),
                ),
            )
        except Exception:  # noqa: BLE001
            _set_progress(
                stage="done",
                label="完成",
                ok=ok_n,
                failed=fail_n,
            )
        _enrich._push_log(f"完成 · 成功 {ok_n} · 失败 {fail_n}", region=region)
    return summary


