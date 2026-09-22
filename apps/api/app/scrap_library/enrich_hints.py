# -*- coding: utf-8 -*-
"""Give-up / retry-hint helpers for enrich pipeline."""
from __future__ import annotations

import logging
import re
import time
from typing import Any

import app.scrap_library.enrich as _enrich

log = logging.getLogger(__name__)

def _give_up_kind(*, give_up: str, acquired: int, cancelled: bool) -> str:
    """被主动放弃的单源，最终归到哪一类（纯函数，第十一轮抽出以便单测锁语义）。

    ⚠️ `acquired == 0`（从没拿到过出站槽）**只有对走调度器的源**才等于「没轮到」。
    第八轮那类「直连 API 源」（r18dev / libredmm / dmm / jav321）以前完全不占槽，
    `acquired` 恒为 0 → 它们**真的慢/挂**（`give_up == "down"`）也会被这条兜底
    改写成 `busy` —— 与「假 down」方向相反的同型缺陷：源坏了不记健康度、不退避，
    坏源被一直重试。第十一轮把直连路径接进 `kind="api"` 通道后，这条兜底对所有源
    才成立；这里用单测把语义钉住。
    """
    if cancelled:
        return "cancelled"
    if give_up == "busy":
        return "busy"
    if not acquired:
        return "busy"
    return "down"


def _refine_kind_with_meter(kind: str, *, slot_timeout: int) -> str:
    """线程已返回时的分类修正：出站侧「排队预算耗尽」的痕迹优先于源侧消息（纯函数）。

    坑：`fetch_json` / `_post_graphql` 这类调用点普遍写着
    `try: ... except Exception: return None`，会把 `OutboundBusy` 吞成
    「未找到」→ 本来是 `busy`（该补抓）却记成 `miss`（明确不补抓）= **假 miss**，
    数据静默丢失。`SlotWaitMeter.slot_timeout` 记下了「这次请求压根没发出去」，
    所以只要它非 0，就不能采信 `miss` / `down`。

    保守方向说明：源若「第一次请求排到超时（被吞）+ 第二次成功但确实没这条番号」，
    会被改成 busy 而多补抓一次 —— 可以接受（宁可多重试一次，不可静默丢数据）。
    """
    if int(slot_timeout or 0) > 0 and kind in {"miss", "down"}:
        return "busy"
    return kind


def _retry_hint_note(
    *,
    region: str,
    code: str,
    kind: str,
    need: bool,
    cap: int,
    error: str = "",
    item_id: str = "",
    rel_path: str = "",
) -> tuple[int, bool]:
    """维护一条重试提示。need=True 累计一次失败；need=False 清零。

    返回 (累计次数, 是否已放弃)。**只在需要时写库**：need=False 且进程内已知
    没有该行时直接返回，避免给每条成功番号发 DELETE。
    """
    c = str(code or "").strip().upper()
    rid = _enrich._queue_log_region(region) or region
    if not c or not rid:
        return 0, False
    key = (rid, str(kind or ""))
    if not need:
        if c not in _enrich._retry_hint_known.get(key, set()):
            # 首次清零前预热一次 known（每个 (region,kind) 进程内只做一次库读）。
            # 不预热的话，「单号重刮」这类不走队列构建的路径会漏掉清零。
            if key not in _enrich._retry_hint_primed:
                _enrich._retry_hint_load(rid, kind)
            if c not in _enrich._retry_hint_known.get(key, set()):
                return 0, False
    try:
        from app.core.db import connect, init_db

        init_db()
        if not need:
            with connect() as conn:
                conn.execute(
                    "DELETE FROM enrich_retry_hint WHERE region=? AND code=? AND kind=?",
                    (rid, c, str(kind or "")),
                )
                conn.commit()
            _enrich._retry_hint_known.setdefault(key, set()).discard(c)
            _enrich._retry_hint_invalidate(rid, kind)
            return 0, False
        with connect() as conn:
            row = conn.execute(
                """
                SELECT attempts FROM enrich_retry_hint
                WHERE region=? AND code=? AND kind=?
                """,
                (rid, c, str(kind or "")),
            ).fetchone()
            cur_attempts = 0
            if row is not None:
                if isinstance(row, dict):
                    cur_attempts = int(row.get("attempts") or 0)
                else:
                    cur_attempts = int(row[0] or 0)
            n, giveup = _enrich._retry_next_state(cur_attempts, cap=cap)
            conn.execute(
                """
                INSERT INTO enrich_retry_hint
                  (region, code, kind, attempts, giveup, last_error, item_id, rel_path, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW())
                ON CONFLICT(region, code, kind) DO UPDATE SET
                  attempts = excluded.attempts,
                  giveup = excluded.giveup,
                  last_error = excluded.last_error,
                  item_id = CASE WHEN excluded.item_id <> '' THEN excluded.item_id
                                 ELSE enrich_retry_hint.item_id END,
                  rel_path = CASE WHEN excluded.rel_path <> '' THEN excluded.rel_path
                                  ELSE enrich_retry_hint.rel_path END,
                  updated_at = NOW()
                """,
                (
                    rid,
                    c,
                    str(kind or ""),
                    n,
                    bool(giveup),
                    str(error or "")[:160],
                    str(item_id or ""),
                    str(rel_path or ""),
                ),
            )
            conn.commit()
        _enrich._retry_hint_known.setdefault(key, set()).add(c)
        _enrich._retry_hint_invalidate(rid, kind)
        return n, giveup
    except Exception as e:  # noqa: BLE001
        log.debug("retry hint note failed code=%s kind=%s: %s", c, kind, e)
        return 0, False


_TRAD_HINT_RE = re.compile(r"[體後國興專質畫婦獨數碼溫亂戀顏觀恥縛緊嗎麼萬與幹]")


_TITLE_TAIL_NOISE = frozenset(
    {
        "完全版",
        "特别篇",
        "特別篇",
        "限定版",
        "配信版",
        "字幕版",
        "高清版",
        "中文字幕",
        "无码流出",
        "無碼流出",
        "独家配信",
        "独占配信",
        "文芸部",
        "游泳部",
        "水泳部",
        "网球部",
        "テニス部",
        "篮球部",
        "バスケ部",
        "部活",
    }
)




