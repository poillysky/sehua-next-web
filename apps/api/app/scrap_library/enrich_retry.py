# -*- coding: utf-8 -*-
"""enrich_retry —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

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
import app.scrap_library.enrich_cover as _enrich_cover
import app.scrap_library.enrich_detail as _enrich_detail
import app.scrap_library.enrich_merge as _enrich_merge
import app.scrap_library.enrich_queue as _enrich_queue
import app.scrap_library.enrich_scan as _enrich_scan
from app.scrap_library.enrich import (_COVER_ONLY_GAPS, _ENRICH_KINDS, _GAP_FAIL_LABEL, _SOFT_GAP_LABELS, _SOFT_SUCCESS_GAPS, _SUCCESS_BLOCK_GAPS, _demoted_false_dones, _promoted_actress_soft, _retry_hint_cache, _retry_hint_known, _retry_hint_primed, _soft_correction_last, log)
from app.scrap_library.enrich_runtime import (_enrich_job, _enrich_lock)


_SOFT_OK_PREFIX = "软成功"


_SOFT_OK_PREFIXES = ("软成功", "次成功")


_SOFT_PROMOTE_RULE_VER = 8


_SOFT_CORRECTION_MIN_INTERVAL_SEC = 6.0


def _gap_labels(gaps: list[str]) -> list[str]:
    return [_enrich._GAP_FAIL_LABEL.get(g, g) for g in gaps]


def _strip_soft_ok_prefix(err: str) -> str:
    s = str(err or "").strip()
    for pref in _SOFT_OK_PREFIXES:
        if s.startswith(pref):
            rest = s[len(pref) :].strip()
            if rest.startswith("·"):
                rest = rest[1:].strip()
            return rest
    return s


def _is_soft_ok_error(err: str) -> bool:
    s = str(err or "").strip()
    return any(s.startswith(p) for p in _SOFT_OK_PREFIXES)


def _format_soft_ok_error(labels: list[str]) -> str:
    labs = [str(x).strip() for x in (labels or []) if str(x).strip()]
    if labs:
        return f"{_SOFT_OK_PREFIX} · 仍缺:{' · '.join(labs)}"
    return _SOFT_OK_PREFIX


def _soft_done_sql_pred(*, error_col: str = "error") -> str:
    """SQL：done 行是否软成功（当前规则：有封面但无标题）。

    兼容旧「次成功」前缀；须含「仍缺:标题」（不含仅「中文标题」）。
    psycopg 要求字面量 ``%`` 写成 ``%%``。
    """
    return (
        f"("
        f"({error_col} LIKE '软成功%%' OR {error_col} LIKE '次成功%%')"
        f" AND {error_col} LIKE '%%仍缺:标题%%'"
        f" AND {error_col} NOT LIKE '%%仍缺:中文标题%%'"
        f")"
    )


def _is_soft_remain_error(err: str) -> bool:
    """error 是否仅为软缺口「仍缺:…」（可带软成功/次成功前缀；不含封面/标题）。"""
    s = _strip_soft_ok_prefix(err)
    if not s.startswith("仍缺:"):
        return False
    rest = s[len("仍缺:") :].strip()
    parts = [p.strip() for p in re.split(r"[·,，]", rest) if p.strip()]
    return bool(parts) and all(p in _enrich._SOFT_GAP_LABELS for p in parts)


def _soft_gaps_from_remain_error(err: str) -> list[str]:
    """从仍缺文案反推 soft gap ids。"""
    s = _strip_soft_ok_prefix(err)
    if not s.startswith("仍缺:"):
        return []
    rest = s[len("仍缺:") :].strip()
    parts = [p.strip() for p in re.split(r"[·,，]", rest) if p.strip()]
    rev = {v: k for k, v in _enrich._GAP_FAIL_LABEL.items()}
    out: list[str] = []
    for p in parts:
        gid = rev.get(p)
        if gid and gid in _enrich._SOFT_SUCCESS_GAPS and gid not in out:
            out.append(gid)
    return out


_RETRY_KIND_COVER = "cover"


_RETRY_KIND_SRC_DOWN = "src_down"


_COVER_RETRY_MAX = 3


_SRC_DOWN_RETRY_MAX = 2


_RETRY_HINT_CACHE_TTL = 20.0


def _retry_next_state(attempts: int, *, cap: int) -> tuple[int, bool]:
    """纯函数：累计一次失败后的 (新次数, 是否已放弃)。便于单测锁语义。"""
    n = max(0, int(attempts or 0)) + 1
    return n, n >= int(cap)


def _is_cover_only_gaps(gaps: Any) -> bool:
    """剩余缺口是否「只有封面」（no_local=无合格海报 / no_media=无 cover_url）。"""
    g = {str(x).strip() for x in (gaps or []) if str(x).strip()}
    return bool(g) and g <= _enrich._COVER_ONLY_GAPS


_SRC_GIVEUP_POLL_SEC = 0.25


_SOURCE_COOLDOWN_STREAK = 3


_SOURCE_COOLDOWN_SEC = 50.0


_MISS_HINTS = (
    "未找到",
    "搜索无结果",
    "无结果",
    "不存在",
    "没有该",
    "格式无效",
    "not found",
    "no such",
    "404",
    "410",
)


class _CancelPair:
    """两个取消令牌的并集：任一置位即视为取消。

    用途：池级令牌（早停/暂停，回收整池在飞源）+ **本源专属令牌**
    （单源放弃时立刻把这一条从等槽队列里摘出来，不影响同池其它源）。
    `outbound_scheduler` 只调 `is_set()`，故这里只需实现这一个方法。
    """

    __slots__ = ("_evs",)

    def __init__(self, *evs: Any) -> None:
        self._evs = tuple(e for e in evs if e is not None)

    def is_set(self) -> bool:
        for ev in self._evs:
            try:
                if ev.is_set():
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False


def _src_retry_item(hint: dict[str, Any], *, region: str) -> dict[str, Any] | None:
    """把一条源故障提示转成队列项。

    这些番号的本地 NFO 是**齐的**，既不在 `local_incomplete` 里、也不是空壳骨架，
    所以必须显式补出来 —— 否则「降级取值」永远没人回头修。
    """
    code_h = str(hint.get("code") or "").strip().upper()
    iid = str(hint.get("itemId") or hint.get("relPath") or "").strip()
    rel = str(hint.get("relPath") or hint.get("itemId") or "").strip()
    if not iid or not code_h:
        return None
    return {
        "itemId": iid,
        "code": code_h,
        "gaps": list(_enrich._ENRICH_KINDS),
        "rel_path": rel or iid,
        "relPath": rel or iid,
        "region": region,
        "status": "pending",
        "retryKind": _RETRY_KIND_SRC_DOWN,
        # 允许覆盖写回：否则之前被低优先源写死的字段不会被修好
        "overwrite": True,
    }


def _retry_hint_load(region: str, kind: str) -> list[dict[str, Any]]:
    """读某分区某类重试提示（TTL 缓存）。顺带把已知番号灌进 `_enrich._retry_hint_known`。

    缓存必须由这里灌 `known` —— 否则进程重启后「成功清零」会因 known 为空而跳过 DELETE，
    提示行会永远留在库里、每轮被重新入队。
    """
    rid = _enrich._queue_log_region(region) or region
    key = (rid, str(kind or ""))
    now = time.time()
    hit = _enrich._retry_hint_cache.get(key)
    if hit and now - hit[0] < _RETRY_HINT_CACHE_TTL:
        _enrich._retry_hint_primed.add(key)
        return hit[1]
    rows: list[dict[str, Any]] = []
    known: set[str] = set()
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            cur = conn.execute(
                """
                SELECT code, attempts, giveup, item_id, rel_path, last_error
                FROM enrich_retry_hint
                WHERE region=? AND kind=?
                ORDER BY attempts DESC, code ASC
                """,
                (rid, str(kind or "")),
            )
            for r in cur.fetchall() or []:
                d = dict(r) if isinstance(r, dict) else {}
                if not d:
                    continue
                c = str(d.get("code") or "").strip().upper()
                if c:
                    known.add(c)
                rows.append(
                    {
                        "code": c,
                        "attempts": int(d.get("attempts") or 0),
                        "giveup": bool(d.get("giveup")),
                        "itemId": str(d.get("item_id") or ""),
                        "relPath": str(d.get("rel_path") or ""),
                        "lastError": str(d.get("last_error") or ""),
                    }
                )
    except Exception as e:  # noqa: BLE001
        log.debug("retry hint load failed region=%s kind=%s: %s", rid, kind, e)
    _enrich._retry_hint_cache[key] = (now, rows)
    _enrich._retry_hint_known.setdefault(key, set()).update(known)
    _enrich._retry_hint_primed.add(key)
    return rows


def _retry_hint_invalidate(region: str, kind: str) -> None:
    rid = _enrich._queue_log_region(region) or region
    _enrich._retry_hint_cache.pop((rid, str(kind or "")), None)


def _retry_hint_clear_region(region: str, kind: str | None = None) -> int:
    """清掉某分区（或某类）重试提示 —— 覆盖模式重扫时调用，让用户能强制再来一轮。"""
    rid = _enrich._queue_log_region(region) or region
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if kind:
                cur = conn.execute(
                    "DELETE FROM enrich_retry_hint WHERE region=? AND kind=?",
                    (rid, str(kind or "")),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM enrich_retry_hint WHERE region=?", (rid,)
                )
            n = int(getattr(cur, "rowcount", 0) or 0)
            conn.commit()
        for k in {_RETRY_KIND_COVER, _RETRY_KIND_SRC_DOWN} if not kind else {kind}:
            _enrich._retry_hint_cache.pop((rid, str(k or "")), None)
            _enrich._retry_hint_known.pop((rid, str(k or "")), None)
            _enrich._retry_hint_primed.discard((rid, str(k or "")))
        return n
    except Exception as e:  # noqa: BLE001
        log.debug("retry hint clear failed region=%s: %s", rid, e)
        return 0


def _retry_hint_clear_codes(
    region: str, codes: list[str] | set[str], *, kind: str | None = None
) -> int:
    """清掉指定番号的重试放弃标记，让「失败重试」能真正再刮。"""
    rid = _enrich._queue_log_region(region) or region
    code_list = sorted(
        {
            str(c or "").strip().upper()
            for c in (codes or [])
            if str(c or "").strip()
        }
    )
    if not rid or not code_list:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        dropped = 0
        with connect() as conn:
            for i in range(0, len(code_list), 400):
                chunk = code_list[i : i + 400]
                ph = ",".join(["?"] * len(chunk))
                if kind:
                    cur = conn.execute(
                        f"""
                        DELETE FROM enrich_retry_hint
                        WHERE region=? AND kind=? AND code IN ({ph})
                        """,
                        (rid, str(kind or ""), *chunk),
                    )
                else:
                    cur = conn.execute(
                        f"""
                        DELETE FROM enrich_retry_hint
                        WHERE region=? AND code IN ({ph})
                        """,
                        (rid, *chunk),
                    )
                dropped += int(getattr(cur, "rowcount", 0) or 0)
            conn.commit()
        for k in {_RETRY_KIND_COVER, _RETRY_KIND_SRC_DOWN} if not kind else {kind}:
            _enrich._retry_hint_cache.pop((rid, str(k or "")), None)
            known = _enrich._retry_hint_known.get((rid, str(k or "")))
            if isinstance(known, set):
                known.difference_update(code_list)
        return dropped
    except Exception as e:  # noqa: BLE001
        log.debug("retry hint clear codes failed region=%s: %s", rid, e)
        return 0


def _cover_giveup_codes(region: str) -> set[str]:
    """已放弃封面重试的番号（增量队列用它做排除；只抑制「仅剩封面缺口」的行）。"""
    return {
        str(h.get("code") or "").strip().upper()
        for h in _retry_hint_load(region, _RETRY_KIND_COVER)
        if h.get("giveup") and str(h.get("code") or "").strip()
    }


def _should_skip_for_giveup(
    *, code_u: str, gaps: Any, giveup_codes: set[str]
) -> bool:
    """纯函数：该行是否应因「封面已放弃」被增量队列排除。

    只在剩余缺口**仅有封面**时跳过 —— 同时缺剧情/女优的番号仍要重试，
    否则等于把一份半成品永久钉死。
    """
    c = str(code_u or "").strip().upper()
    if not c or c not in giveup_codes:
        return False
    return _is_cover_only_gaps(gaps)


def _note_retry_hints(
    *,
    region: str,
    code: str,
    row: dict[str, Any],
    one: dict[str, Any],
) -> None:
    """单条结果落库前的**有界重试记账**（封面 / 源故障降级）。

    - 只有「仅剩封面缺口」才累计封面重试（否则会连带把元数据一起放弃）；
    - 只有「高优先源不可用导致降级取值」才累计源故障重试；
    - 条件不再满足就清零，避免提示行长期滞留、每轮被重新入队。
    """
    code_u = str(code or "").strip().upper()
    if not code_u:
        return
    rel = str(row.get("rel_path") or row.get("relPath") or "").strip()
    iid = str(row.get("itemId") or row.get("item_id") or "").strip()

    # ① 封面
    cover_fail = str(one.get("coverFail") or "").strip()
    if cover_fail and not bool(one.get("localCoverOk")):
        if _is_cover_only_gaps(one.get("gapsAfter")):
            n, giveup = _enrich._retry_hint_note(
                region=region,
                code=code_u,
                kind=_RETRY_KIND_COVER,
                need=True,
                cap=_COVER_RETRY_MAX,
                error=cover_fail,
                item_id=iid,
                rel_path=rel,
            )
            if giveup and n == _COVER_RETRY_MAX:
                _enrich._push_log(
                    f"{code_u} · 封面连续失败 {n} 次 · 已停止自动重试"
                    "（可用覆盖模式重扫或单号重刮解除）",
                    region=region,
                )
        else:
            _enrich._retry_hint_note(
                region=region,
                code=code_u,
                kind=_RETRY_KIND_COVER,
                need=False,
                cap=_COVER_RETRY_MAX,
            )
    else:
        _enrich._retry_hint_note(
            region=region,
            code=code_u,
            kind=_RETRY_KIND_COVER,
            need=False,
            cap=_COVER_RETRY_MAX,
        )

    # ② 源故障降级（高优先源不可用 → 本轮取了更低优先源的值）
    down = [
        str(x).strip() for x in (one.get("degradedByDown") or []) if str(x).strip()
    ]
    if down and bool(one.get("ok")):
        n, giveup = _enrich._retry_hint_note(
            region=region,
            code=code_u,
            kind=_RETRY_KIND_SRC_DOWN,
            need=True,
            cap=_SRC_DOWN_RETRY_MAX,
            error=",".join(down),
            item_id=iid,
            rel_path=rel,
        )
        if giveup and n == _SRC_DOWN_RETRY_MAX:
            _enrich._push_log(
                f"{code_u} · 高优先源连续 {n} 轮不可用 · 已停止自动补抓"
                "（源恢复后可用覆盖模式重扫）",
                region=region,
            )
    else:
        _enrich._retry_hint_note(
            region=region,
            code=code_u,
            kind=_RETRY_KIND_SRC_DOWN,
            need=False,
            cap=_SRC_DOWN_RETRY_MAX,
        )


def _apply_local_gap_success(
    out: dict[str, Any],
    *,
    folder: Path,
    code: str,
    region: str,
    remain: list[str] | None = None,
    only_if_ok: bool = False,
) -> None:
    """本地 NFO 缺口收口：无封面→失败；有封面无标题→软成功；其余缺失→成功。"""
    # 无目录 / 无封面绝不能算成功（防并发串写把别人的结果盖到空壳番号）
    if not folder.is_dir() or not _enrich_cover._local_poster_ok(folder):
        if only_if_ok and not out.get("ok"):
            return
        out["ok"] = False
        out["partialOk"] = False
        out["localCoverOk"] = False
        if not folder.is_dir():
            out["gapsAfter"] = [
                "no_local",
                "no_media",
                "no_actress",
                "no_studio",
                "no_plot",
                "thin_title",
            ]
            out["error"] = "仍缺:封面 · 无本地目录"
        else:
            out["gapsAfter"] = ["no_local"]
            out["error"] = "仍缺:封面"
        _enrich._push_log(
            f"{code or folder.name} · 未算成功 · {out['error']}",
            region=region,
        )
        return
    # 有封面但无 NFO → 无标题 → 软成功
    if not _enrich_detail._find_nfo(folder):
        if only_if_ok and not out.get("ok"):
            return
        out["ok"] = True
        out["partialOk"] = True
        out["localCoverOk"] = True
        out["gapsAfter"] = ["thin_title"]
        out["error"] = _format_soft_ok_error(["标题"])
        _enrich._push_log(
            f"{code or folder.name} · {out['error']} · 无 NFO",
            region=region,
        )
        return
    if remain is None:
        try:
            _, remain = _enrich_scan._local_folder_gaps(folder)
        except Exception:  # noqa: BLE001
            remain = []
    remain = list(remain or [])
    block = [g for g in remain if g in _enrich._SUCCESS_BLOCK_GAPS]
    soft = [g for g in remain if g in _enrich._SOFT_SUCCESS_GAPS]
    if block:
        if only_if_ok and not out.get("ok"):
            return
        labels = _gap_labels(block)
        out["ok"] = False
        out["partialOk"] = False
        out["gapsAfter"] = remain
        out["error"] = f"仍缺:{' · '.join(labels)}"
        _enrich._push_log(
            f"{code or folder.name} · 未算成功 · {out['error']}",
            region=region,
        )
        return
    if soft:
        if only_if_ok and not out.get("ok"):
            return
        labels = _gap_labels(soft)
        out["ok"] = True
        out["partialOk"] = True
        out["gapsAfter"] = soft
        out["error"] = _format_soft_ok_error(labels)
        _enrich._push_log(
            f"{code or folder.name} · {out['error']}",
            region=region,
        )
        return
    # 硬缺口已清：必须显式 ok=True（调用方初始 ok=False，否则会被当成失败提前 return）
    # 缺剧情/女优/片商等不算软成功 → 完整成功
    if only_if_ok and not out.get("ok"):
        return
    out["ok"] = True
    out["partialOk"] = False
    out["error"] = ""
    out["gapsAfter"] = []
    out["localCoverOk"] = True


def _ensure_actress_soft_promoted(region: str, *, force: bool = False) -> int:
    """纠偏队列表：假成功回滚；软缺口失败升软成功；同步内存队列。

    按分区限频（首次 / 规则版本变更必须跑：DB 侧 demote/promote）。
    """
    rid = _enrich._queue_log_region(region)
    if not rid:
        return 0
    now = time.monotonic()
    first = (
        rid not in _enrich._demoted_false_dones
        or _enrich._promoted_actress_soft.get(rid) != _SOFT_PROMOTE_RULE_VER
    )
    if not force and not first:
        last = float(_enrich._soft_correction_last.get(rid) or 0.0)
        if (now - last) < _SOFT_CORRECTION_MIN_INTERVAL_SEC:
            return 0
    _enrich._soft_correction_last[rid] = now
    demoted = 0
    if rid not in _enrich._demoted_false_dones:
        demoted = _enrich_queue._queue_log_demote_false_dones(rid)
        _enrich._demoted_false_dones.add(rid)
    n = 0
    if _enrich._promoted_actress_soft.get(rid) != _SOFT_PROMOTE_RULE_VER:
        n = _enrich_queue._queue_log_promote_actress_soft_fails(rid)
        n += _enrich_queue._queue_log_normalize_soft_to_full_success(rid)
        _enrich._promoted_actress_soft[rid] = _SOFT_PROMOTE_RULE_VER
    # 内存队列同步：假成功→pending；软缺口 fail→软成功（须本地封面）
    mem_n = 0
    with _enrich._enrich_lock:
        q = list(_enrich._enrich_job.get("queue") or [])
        if q:
            new_q: list[Any] = []
            pending_delta = 0
            done_delta = 0
            soft_delta = 0
            fail_delta = 0
            for r in q:
                if not isinstance(r, dict):
                    new_q.append(r)
                    continue
                st = str(r.get("status") or "").strip().lower()
                err = str(r.get("error") or "")
                code_u = str(r.get("code") or "").strip().upper()
                iid = str(r.get("itemId") or "").strip()
                field_code = ""
                fields = r.get("fields")
                if isinstance(fields, list):
                    for f in fields:
                        if isinstance(f, dict) and str(f.get("id") or "") == "code":
                            field_code = str(f.get("value") or "").strip().upper()
                            break
                folder = None
                if st == "done" or (st == "fail" and _is_soft_remain_error(err)):
                    folder = _enrich_detail._resolve_enrich_folder(
                        region=rid, code=code_u, item_id=iid
                    )
                if st == "done" and (
                    (field_code and code_u and field_code != code_u)
                    or folder is None
                    or not _enrich_cover._local_poster_ok(folder)
                ):
                    nr = dict(r)
                    was_soft = bool(r.get("partialOk")) or _is_soft_ok_error(err)
                    nr["status"] = "pending"
                    nr["partialOk"] = False
                    nr["error"] = (
                        f"串号回滚:{field_code}"
                        if field_code and code_u and field_code != code_u
                        else "仍缺:封面 · 无本地目录"
                    )
                    new_q.append(nr)
                    mem_n += 1
                    if was_soft:
                        soft_delta -= 1
                    else:
                        done_delta -= 1
                    pending_delta += 1
                    continue
                if st == "fail" and (
                    _is_soft_remain_error(err)
                    or (
                        isinstance(r.get("gaps") or r.get("gapsAfter"), list)
                        and not any(
                            g in _enrich._SUCCESS_BLOCK_GAPS
                            for g in (r.get("gapsAfter") or r.get("gaps") or [])
                        )
                    )
                ):
                    if folder is not None and _enrich_cover._local_poster_ok(folder):
                        try:
                            _, disk_gaps = _enrich_scan._local_folder_gaps(folder)
                        except Exception:  # noqa: BLE001
                            disk_gaps = []
                        if not any(g in _enrich._SUCCESS_BLOCK_GAPS for g in disk_gaps):
                            soft_only = [
                                g
                                for g in disk_gaps
                                if g in _enrich._SOFT_SUCCESS_GAPS
                            ]
                            nr = dict(r)
                            nr["status"] = "done"
                            if soft_only:
                                nr["partialOk"] = True
                                nr["gapsAfter"] = soft_only
                                nr["error"] = _format_soft_ok_error(
                                    _gap_labels(soft_only)
                                )
                                soft_delta += 1
                            else:
                                nr["partialOk"] = False
                                nr["gapsAfter"] = []
                                nr["error"] = ""
                                done_delta += 1
                            new_q.append(nr)
                            mem_n += 1
                            fail_delta -= 1
                            continue
                if (
                    st == "done"
                    and folder is not None
                    and _enrich_cover._local_poster_ok(folder)
                ):
                    try:
                        _, disk_gaps = _enrich_scan._local_folder_gaps(folder)
                    except Exception:  # noqa: BLE001
                        disk_gaps = []
                    if not any(g in _enrich._SUCCESS_BLOCK_GAPS for g in disk_gaps):
                        soft_only = [
                            g for g in disk_gaps if g in _enrich._SOFT_SUCCESS_GAPS
                        ]
                        was_soft = bool(r.get("partialOk")) or _is_soft_ok_error(
                            err
                        )
                        if soft_only and (
                            not was_soft
                            or list(r.get("gapsAfter") or []) != soft_only
                        ):
                            nr = dict(r)
                            nr["partialOk"] = True
                            nr["gapsAfter"] = soft_only
                            nr["error"] = _format_soft_ok_error(
                                _gap_labels(soft_only)
                            )
                            new_q.append(nr)
                            mem_n += 1
                            if not was_soft:
                                done_delta -= 1
                                soft_delta += 1
                            continue
                        if was_soft and not soft_only:
                            nr = dict(r)
                            nr["partialOk"] = False
                            nr["gapsAfter"] = []
                            nr["error"] = ""
                            new_q.append(nr)
                            mem_n += 1
                            soft_delta -= 1
                            done_delta += 1
                            continue
                new_q.append(r)
            if mem_n:
                _enrich._enrich_job["queue"] = new_q
                counts = dict(_enrich._enrich_job.get("queueCounts") or {})
                if counts:
                    counts["pending"] = max(
                        0, int(counts.get("pending") or 0) + pending_delta
                    )
                    counts["fail"] = max(
                        0, int(counts.get("fail") or 0) + fail_delta
                    )
                    counts["done"] = max(
                        0, int(counts.get("done") or 0) + done_delta
                    )
                    counts["soft"] = max(
                        0, int(counts.get("soft") or 0) + soft_delta
                    )
                    _enrich._enrich_job["queueCounts"] = counts
                    prog = dict(_enrich._enrich_job.get("progress") or {})
                    prog["ok"] = int(counts.get("done") or 0) + int(
                        counts.get("soft") or 0
                    )
                    prog["failed"] = int(counts.get("fail") or 0)
                    _enrich._enrich_job["progress"] = prog
    if demoted:
        log.info(
            "demoted false enrich dones region=%s n=%s", rid, demoted
        )
    return demoted + n + mem_n


def _is_cancelled() -> bool:
    """兼容旧名：收到 pause/stop 都视为应中断循环。"""
    return _enrich_merge._halt_kind() is not None
