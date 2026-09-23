# -*- coding: utf-8 -*-
"""Single-row enrich pipeline (extracted from enrich.py)."""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import app.scrap_library.embed as embed_svc
import app.scrap_library.enrich as _enrich
from app.scrap_library import enrich_monitor as enrich_mon
from app.scrap_library.enrich_runtime import (
    _enrich_job,
    _enrich_lock,
    _set_progress,
    notify_enrich_watchers,
)

log = logging.getLogger(__name__)

def enrich_one_row(
    row: dict[str, Any],
    *,
    dry_run: bool = False,
    wait_all: bool = False,
    overwrite: bool = False,
    prefetched_detail: dict[str, Any] | None = None,
    sync_vector: bool = True,
) -> dict[str, Any]:
    code = str(row.get("code") or "").strip().upper()
    rel = str(row.get("rel_path") or row.get("relPath") or "").strip().replace("\\", "/")
    gaps = list(row.get("gaps") or [])
    region = str(row.get("region") or "").strip()
    force = bool(overwrite)
    out: dict[str, Any] = {
        "code": code,
        "relPath": rel,
        "region": region,
        "gaps": gaps,
        "ok": False,
        "dryRun": dry_run,
        "overwrite": force,
        "syncVector": bool(sync_vector),
    }
    if not code or not rel:
        out["error"] = "missing code/relPath"
        return out

    t_all0 = time.perf_counter()

    def _stamp_total(result: dict[str, Any]) -> dict[str, Any]:
        result["totalMs"] = int(round((time.perf_counter() - t_all0) * 1000))
        return result

    def _done(result: dict[str, Any]) -> dict[str, Any]:
        _stamp_total(result)
        _enrich._persist_enrich_result_to_queue_log(
            result, row=row, region=region, dry_run=dry_run
        )
        return result

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    folder = (root / rel).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError:
        out["error"] = "bad path"
        return out

    # 无显式 region 时从路径首段推断（日本有码/...）
    if not region and rel:
        region = rel.split("/", 1)[0].strip()
        out["region"] = region

    # 队列 gaps 常是向量空壳（仅 no_local）；以本地 NFO 真实缺口为准，避免漏拉剧情。
    # 覆盖重刮也要读本地缺口：成功行 gaps_json 常为空，但仍缺女优/片商/剧情。
    if folder.is_dir() and _enrich._find_nfo(folder):
        try:
            _lc, local_gaps = _enrich._local_folder_gaps(folder)
            if _lc and not code:
                code = _lc
                out["code"] = code
            if local_gaps:
                gaps = list(dict.fromkeys([*local_gaps, *[g for g in gaps if g]]))
                out["gaps"] = gaps
                row = {**row, "gaps": gaps}
        except Exception:  # noqa: BLE001
            pass

    # E2E 等可传入已合并详情，跳过再拉源（仍写 NFO/封面/向量）
    try:
        enrich_mon.set_phase(code=code, item_id=str(row.get("itemId") or ""), phase="fetch")
        _enrich.notify_enrich_watchers()
    except Exception:  # noqa: BLE001
        pass
    if isinstance(prefetched_detail, dict) and prefetched_detail:
        detail = dict(prefetched_detail)
        out["prefetched"] = True
    else:
        # 运行中改策略：本条起热切数据源/超时（进行中的其它番号不打断）
        _enrich._note_strategy_hot_if_needed(region)
        # 增量：缺口齐了就早停；覆盖：拉满各源再合并写回（仍带本地缺口做源优先级）
        # wait_all=True（详情单刷）时强制自适应优先，不过盾池拖尾
        detail = _enrich._fetch_detail(
            code,
            region=region,
            wait_all=force,
            gaps=gaps if gaps else (None if force else gaps),
            # 增量：按需早停（近 MDCX 字段链）；覆盖/单刷再拉满
            adaptive_first=not force,
            # 分区批量只写本地：机翻短超时，避免 LLM 占满番号槽
            fast_zh=not sync_vector,
        )
    if not detail:
        out["error"] = "各数据源均未找到该番号"
        return out
    out["source"] = detail.get("source") or detail.get("provider")
    out["detailTitle"] = detail.get("title")
    out["sourceTimings"] = list(detail.get("sourceTimings") or [])
    out["fetchMs"] = detail.get("fetchMs")
    out["mergeMs"] = detail.get("mergeMs")
    # 源级诊断（区分「源挂了」「源没这条番号」「我们没轮到」）：
    # 交给 _finish_one 做有界重试记账（busy / cooldown 也进 degradedByDown → 同样要补抓）
    out["sourcesDown"] = list(detail.get("sourcesDown") or [])
    out["sourcesBusy"] = list(detail.get("sourcesBusy") or [])
    out["sourcesCooldown"] = list(detail.get("sourcesCooldown") or [])
    out["sourcesMiss"] = list(detail.get("sourcesMiss") or [])
    out["degradedByDown"] = list(detail.get("degradedByDown") or [])
    out["actors"] = len(detail.get("actors") or [])
    out["fields"] = _enrich._detail_field_rows(detail)

    if dry_run:
        out["ok"] = True
        out["wouldFill"] = {
            "title": bool(detail.get("title")),
            "studio": bool(detail.get("studio") or detail.get("maker")),
            "actors": len(detail.get("actors") or []),
            "tags": len(detail.get("tags") or []),
            "poster": bool(detail.get("posterUrl")),
            "overview": bool(detail.get("overview")),
        }
        return out

    nfo = _enrich._find_nfo(folder) or (folder / f"{folder.name}.nfo")
    force_fields: set[str] = set()
    if not force:
        try:
            from app.scrap_library.enrich_strategy import get_strategy

            force_fields = {
                str(x).strip().lower()
                for x in (get_strategy().get("forceFields") or [])
                if str(x).strip()
            }
        except Exception:  # noqa: BLE001
            force_fields = set()
    try:
        enrich_mon.set_phase(code=code, item_id=str(row.get("itemId") or ""), phase="write")
        _enrich.notify_enrich_watchers()
    except Exception:  # noqa: BLE001
        pass
    changed = _enrich.merge_nfo_with_detail(
        nfo, detail, overwrite=force, force_fields=force_fields
    )
    poster_url = str(detail.get("posterUrl") or "").strip()
    poster_file = folder / "poster.jpg"
    blank_local = poster_file.is_file() and embed_svc._is_blank_cover_file(
        poster_file
    )
    need_cover = force or ("poster" in force_fields) or (
        "no_local" in gaps
        or "no_media" in gaps
        or blank_local
        or not poster_file.is_file()
    )
    if need_cover:
        detailed = detail.get("posterCandidatesDetailed")
        cands: list[Any] = []
        if isinstance(detailed, list) and detailed:
            cands = list(detailed)
        else:
            if poster_url.startswith(("http://", "https://")):
                cands.append(
                    {
                        "source": str(
                            (detail.get("fieldSources") or {}).get("poster") or ""
                        ),
                        "url": poster_url,
                    }
                )
            for u in detail.get("posterCandidates") or []:
                s = str(u or "").strip()
                if s.startswith(("http://", "https://")):
                    cands.append({"source": "", "url": s})
        if cands:
            try:
                enrich_mon.set_phase(
                    code=code, item_id=str(row.get("itemId") or ""), phase="cover"
                )
                _enrich.notify_enrich_watchers()
            except Exception:  # noqa: BLE001
                pass
            t_cover0 = time.perf_counter()
            cover_res = _enrich._download_covers(
                folder,
                cands,
                region=region,
                overwrite=force or ("poster" in force_fields),
                code=code,
                item_id=str(row.get("itemId") or ""),
            )
            out["coverMs"] = int(round((time.perf_counter() - t_cover0) * 1000))
            got_p = str(cover_res.get("poster") or "").strip()
            tried = list(cover_res.get("tried") or [])
            out["coverTried"] = tried[:6]
            out["coverAttempts"] = list(cover_res.get("attempts") or [])[:8]
            out["coverMode"] = str(cover_res.get("mode") or "")
            out["coverSource"] = str(cover_res.get("coverSource") or "")
            fail_reason = str(cover_res.get("failReason") or "").strip()
            if got_p and not cover_res.get("keptOld"):
                changed = True
                out["posterDownloaded"] = True
                out["coverFail"] = ""
            elif got_p and cover_res.get("keptOld"):
                out["posterDownloaded"] = False
                out["coverFail"] = fail_reason or "kept_old"
                out["coverKeptOld"] = True
            else:
                out["posterDownloaded"] = False
                out["coverFail"] = fail_reason or "all_failed"
            _enrich._push_log(
                f"{code or folder.name} · 封面 "
                f"{out.get('coverMs')}ms"
                + (
                    f" · src={out.get('coverSource')}"
                    if out.get("coverSource")
                    else ""
                )
                + (
                    f" · fail={out.get('coverFail')}"
                    if out.get("coverFail")
                    else " · ok"
                ),
                region=region,
            )
        else:
            out["posterDownloaded"] = False
            out["coverTried"] = []
            out["coverAttempts"] = []
            out["coverFail"] = "no_candidates"
            out["coverMs"] = 0
    out["nfoChanged"] = changed

    local_cover_ok = _enrich._local_poster_ok(folder)
    cover_required = bool(
        need_cover
        or "no_local" in gaps
        or "no_media" in gaps
    )
    if cover_required and not local_cover_ok:
        _enrich._purge_blank_covers(folder)
        local_cover_ok = _enrich._local_poster_ok(folder)

    # 字段表：写回后按本地 NFO 刷新（早停未采剧情时不再误报缺剧情）
    fields = _enrich._fields_after_local_write(
        folder,
        detail,
        local_cover_ok=local_cover_ok,
        poster_url=poster_url,
    )
    out["fields"] = fields
    out["localCoverOk"] = local_cover_ok

    # 批量分区刮削：只写本地 NFO/封面，元库/向量交给「同步数据库」「数据库向量化」单独跑（提速）
    if not sync_vector:
        out["vectorSynced"] = False
        out["vectorSkipped"] = True
        if cover_required and not local_cover_ok:
            out["ok"] = False
            cover_fail = str(out.get("coverFail") or "").strip()
            out["error"] = _enrich._cover_fail_message(cover_fail)
            # 封面失败也要记缺口（原先这里直接 return，缺口字段缺失 →
            # 下游无法判断「是否只剩封面缺口」，重试上限就没法生效）
            out["gapsAfter"] = _enrich._safe_local_gaps(folder)
            _enrich._push_log(
                f"{code or folder.name} · cover_fail · {cover_fail or 'unknown'}",
                region=region,
            )
            return _done(out)
        # 回写缺口判定字段（不重嵌），避免再启动又进增量队列
        remain: list[str] = []
        try:
            patched = _enrich.patch_folder_meta_no_embed(folder)
            out["metaPatched"] = bool(patched.get("patched"))
        except Exception as e:  # noqa: BLE001
            out["metaPatched"] = False
            out["metaPatchError"] = str(e)[:160]
            _enrich._push_log(
                f"{code or folder.name} · 元数据回写失败 · {e}",
                region=region,
            )
        # 成功门槛以本地 NFO 为准（向量 _row_gaps 可能与磁盘不一致）
        try:
            _, remain = _enrich._local_folder_gaps(folder)
        except Exception:  # noqa: BLE001
            remain = []
        if remain:
            out["gapsAfter"] = remain
            _enrich._push_log(
                f"{code or folder.name} · 元数据已回写 · 仍缺 "
                f"{','.join(remain)}",
                region=region,
            )
        else:
            _enrich._push_log(
                f"{code or folder.name} · 元数据已回写 · 缺口已清",
                region=region,
            )

        out["fields"] = _enrich._fields_after_local_write(
            folder,
            detail,
            local_cover_ok=local_cover_ok,
            poster_url=poster_url,
        )
        _enrich._apply_local_gap_success(
            out,
            folder=folder,
            code=str(code or ""),
            region=region,
            remain=remain,
        )
        # 软成功且仍缺女优：轻量二次只补女优，补到则升级为完整成功
        if (
            out.get("ok")
            and out.get("partialOk")
            and "no_actress" in set(remain or [])
        ):
            got_actors = _enrich._soft_retry_fill_actors(
                code=str(code or ""),
                region=region,
                folder=folder,
                nfo=nfo,
                detail=detail,
            )
            if got_actors:
                try:
                    patched = _enrich.patch_folder_meta_no_embed(folder)
                    out["metaPatched"] = bool(patched.get("patched"))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    _, remain = _enrich._local_folder_gaps(folder)
                except Exception:  # noqa: BLE001
                    remain = [g for g in (remain or []) if g != "no_actress"]
                out["gapsAfter"] = list(remain or [])
                out["softActressRetry"] = True
                out["fields"] = _enrich._fields_after_local_write(
                    folder,
                    detail,
                    local_cover_ok=local_cover_ok,
                    poster_url=poster_url,
                )
                _enrich._apply_local_gap_success(
                    out,
                    folder=folder,
                    code=str(code or ""),
                    region=region,
                    remain=remain,
                )
        if out.get("ok") is False:
            return _done(out)

        out["ok"] = True
        if not out.get("partialOk"):
            _enrich._push_log(
                f"{code or folder.name} · 刮削写回完成 · 跳过向量（本地提速）",
                region=region,
            )
        else:
            _enrich._push_log(
                f"{code or folder.name} · 刮削写回完成（软成功）· 跳过向量",
                region=region,
            )
        return _done(out)

    # 刮削写回后立刻同步向量库（一步完成）；女优档案并行，省串行等待
    _set_progress(
        stage="enrich",
        label=f"向量 {code or folder.name}",
    )
    _enrich._push_log(f"{code or folder.name} · 刮削写回完成 · 同步向量…", region=region)

    actors_for_db = [
        str(a).strip()
        for a in (detail.get("actors") or [])
        if str(a or "").strip()
    ]
    alias_extra = [
        str(a).strip()
        for a in (detail.get("actorAliases") or [])
        if str(a or "").strip()
    ]

    def _run_vector() -> tuple[dict[str, Any] | None, BaseException | None, int]:
        t0 = time.perf_counter()
        try:
            rein = _enrich.reingest_folder(folder) or {
                "ok": False,
                "embedded": False,
                "error": "reingest_none",
            }
            return rein, None, int(round((time.perf_counter() - t0) * 1000))
        except BaseException as e:  # noqa: BLE001
            return None, e, int(round((time.perf_counter() - t0) * 1000))

    def _run_actress() -> tuple[dict[str, Any] | None, BaseException | None, int]:
        t0 = time.perf_counter()
        try:
            enrich_mon.set_phase(
                code=code, item_id=str(row.get("itemId") or ""), phase="actress"
            )
            _enrich.notify_enrich_watchers()
        except Exception:  # noqa: BLE001
            pass
        try:
            from app.scrap_library.actress_store import sync_actresses_to_vector_db
            from app.scrap_library.enrich_strategy import get_strategy

            st = get_strategy()
            mode = str(st.get("actressAvatarMode") or "incremental").lower()
            force_av = mode in {"overwrite", "cover", "force", "replace"}
            actress_db = sync_actresses_to_vector_db(
                actors_for_db,
                region=region,
                ensure_avatar=True,
                force_avatar=force_av,
                extra_aliases=alias_extra,
            )
            return actress_db, None, int(round((time.perf_counter() - t0) * 1000))
        except BaseException as e:  # noqa: BLE001
            return None, e, int(round((time.perf_counter() - t0) * 1000))

    do_actress = bool(actors_for_db) and not dry_run
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_v = pool.submit(_run_vector)
        fut_a = pool.submit(_run_actress) if do_actress else None
        rein, vec_exc, vector_ms = fut_v.result()
        actress_db = None
        act_exc: BaseException | None = None
        actress_ms = 0
        if fut_a is not None:
            actress_db, act_exc, actress_ms = fut_a.result()

    out["vectorMs"] = vector_ms
    if vec_exc is not None:
        out["ok"] = False
        out["vectorSynced"] = False
        out["error"] = f"向量同步失败:{vec_exc}"
        out["reingest"] = {"ok": False, "embedded": False, "error": str(vec_exc)}
        _enrich._push_log(f"{code or folder.name} · 向量同步失败 · {vec_exc}", region=region)
    else:
        assert rein is not None
        out["reingest"] = rein
        if cover_required and not local_cover_ok:
            out["ok"] = False
            out["vectorSynced"] = bool(rein.get("embedded"))
            cover_fail = str(out.get("coverFail") or "").strip()
            out["error"] = _enrich._cover_fail_message(cover_fail)
            # 同批量路径：封面失败也补上缺口记账（重试上限依赖它）
            out["gapsAfter"] = _enrich._safe_local_gaps(folder)
            _enrich._push_log(
                f"{code or folder.name} · cover_fail · {cover_fail or 'unknown'}",
                region=region,
            )
        elif rein.get("embedded"):
            out["ok"] = True
            out["vectorSynced"] = True
            _enrich._push_log(
                f"{code or folder.name} · 向量已同步 · {vector_ms}ms",
                region=region,
            )
        else:
            err = str(rein.get("error") or "vector_skip")
            out["vectorSynced"] = False
            out["vectorError"] = err
            if err == "embed_disabled":
                out["ok"] = True
                out["error"] = "刮削完成 · 向量未启用"
                _enrich._push_log(
                    f"{code or folder.name} · 向量跳过（嵌入未启用）",
                    region=region,
                )
            else:
                out["ok"] = False
                out["error"] = f"向量同步失败:{err}"
                _enrich._push_log(
                    f"{code or folder.name} · 向量同步失败 · {err}",
                    region=region,
                )

    if do_actress:
        out["actressMs"] = actress_ms
        if act_exc is not None:
            out["actressDb"] = {"ok": False, "error": str(act_exc)}
            _enrich._push_log(
                f"{code or folder.name} · 女优档案写入失败 · {act_exc}",
                region=region,
            )
        else:
            out["actressDb"] = actress_db
            if isinstance(actress_db, dict) and actress_db.get("ok"):
                n_ok = int(actress_db.get("n") or 0)
                av_n = sum(
                    1 for it in (actress_db.get("items") or []) if it.get("avatar_ok")
                )
                bio_n = sum(
                    1
                    for it in (actress_db.get("items") or [])
                    if it.get("birthday") or it.get("height") or it.get("cup")
                )
                _enrich._push_log(
                    f"{code or folder.name} · 女优本地化 "
                    f"{n_ok}人 · 资料{bio_n} · 头像{av_n}"
                    f" · {actress_ms}ms",
                    region=region,
                )
            else:
                issues = (
                    (actress_db.get("issues") or [])[:3]
                    if isinstance(actress_db, dict)
                    else []
                )
                _enrich._push_log(
                    f"{code or folder.name} · 女优档案部分失败 "
                    f"{issues} · {actress_ms}ms",
                    region=region,
                )

    if cover_required and not local_cover_ok:
        out["fields"] = _enrich._fields_after_local_write(
            folder,
            detail,
            local_cover_ok=local_cover_ok,
            poster_url=poster_url,
        )
        return _done(out)

    # 向量路径：无封面→失败；有封面无标题→软成功；其余缺失→成功
    try:
        _, remain = _enrich._local_folder_gaps(folder)
    except Exception:  # noqa: BLE001
        remain = []
    if remain:
        out["gapsAfter"] = remain
    out["fields"] = _enrich._fields_after_local_write(
        folder,
        detail,
        local_cover_ok=local_cover_ok,
        poster_url=poster_url,
    )
    _enrich._apply_local_gap_success(
        out,
        folder=folder,
        code=str(code or ""),
        region=region,
        remain=remain,
        only_if_ok=True,
    )
    if (
        out.get("ok")
        and out.get("partialOk")
        and "no_actress" in set(remain or [])
    ):
        got_actors = _enrich._soft_retry_fill_actors(
            code=str(code or ""),
            region=region,
            folder=folder,
            nfo=nfo,
            detail=detail,
        )
        if got_actors:
            try:
                _, remain = _enrich._local_folder_gaps(folder)
            except Exception:  # noqa: BLE001
                remain = [g for g in (remain or []) if g != "no_actress"]
            out["gapsAfter"] = list(remain or [])
            out["softActressRetry"] = True
            out["fields"] = _enrich._fields_after_local_write(
                folder,
                detail,
                local_cover_ok=local_cover_ok,
                poster_url=poster_url,
            )
            _enrich._apply_local_gap_success(
                out,
                folder=folder,
                code=str(code or ""),
                region=region,
                remain=remain,
                only_if_ok=True,
            )
    return _done(out)


