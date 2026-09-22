# -*- coding: utf-8 -*-
"""刮削库元数据补全：按配置片商源拉详情 → 写回 NFO/封面 → 重嵌入。"""
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


log = logging.getLogger(__name__)


_ENRICH_KINDS = (
    "no_local",
    "no_media",
    "no_actress",
    "no_studio",
    "no_plot",
    "thin_title",
)


_DEFAULT_ENRICH_KINDS = tuple(_ENRICH_KINDS)


_ITEM_WORKERS_DEFAULT = 6


_ITEM_WORKERS_MAX = 16


_COVER_JOB_WORKERS_MIN = 8


_COVER_JOB_WORKERS_MAX = 16


_COVER_JOB_WORKERS = _COVER_JOB_WORKERS_MAX  # ThreadPool 硬上限


_SOURCE_WORKERS_MAX = 64


_RESULTS_MEM_CAP = 80


_SCAN_QUEUE_SOURCES = frozenset({"local_scan", "scan"})


_cover_job_pool: Any = None


_cover_job_pool_lock = threading.Lock()


_cover_gate_lock = threading.Condition(_cover_job_pool_lock)


_cover_gate_inflight = 0


_cover_gate_target = _COVER_JOB_WORKERS_MIN


_finish_prune_counter = 0


_finish_prune_lock = threading.Lock()


_JUNK_TITLE_MARKERS = (
    "会员登入",
    "會員登入",
    "会员登录",
    "請先登入",
    "请先登录",
    "login",
    "sign in",
    "just a moment",
    "attention required",
    "access denied",
    "403 forbidden",
    "404",
    "cloudflare",
)


_JUNK_ACTORS = frozenset(
    {
        "女优",
        "女優",
        "演员",
        "演員",
        "actor",
        "actress",
        "未知",
        "暫無",
        "暂无",
        "有碼",
        "有码",
        "無碼",
        "无码",
        "注册一个新帐户",
        "忘記密碼?",
        "忘记密码?",
        "登入你的帐户",
        "登入你的帳戶",
        "显示更多",
        "顯示更多",
        "查看更多",
        "更多",
        "n/a",
        "na",
        "null",
        "none",
        "なし",
        "不明",
        "未标注",
        "未標注",
    }
)


_JUNK_ACTOR_TAGS = frozenset(
    {
        "巨乳",
        "美乳",
        "淫乱",
        "淫亂",
        "角色扮演",
        "原创",
        "原創",
        "高清",
        "高畫質",
        "高画质",
        "独家",
        "獨家",
        "中出",
        "中出し",
        "痴女",
        "漫改",
        "剧情",
        "劇情",
        "苗条",
        "苗條",
        "美少女",
        "单体作品",
        "單體作品",
        "出道",
        "出道作品",
        "AV出道",
        "デビュー",
        "デビュー作",
        "デビュー作品",
        "新人",
        "收藏",
        "字幕",
        "翻译",
        "翻譯",
        "绝顶高潮",
        "絕頂高潮",
        "moody's",
        "moodyz",
        "ムディーズ",
        "极限高潮",
        "極限高潮",
        "其他恋物癖",
        "其他戀物癖",
        "羞耻",
        "羞恥",
        "羞辱",
        "打手枪",
        "打手槍",
        "强制口交",
        "強制口交",
        "打屁股",
        "玩具",
        "多p",
        "3p",
        "4p",
        "合集",
        "vr",
        "4k",
        "hd",
        "uhd",
        "fc2",
        "sod",
        "m女",
        "素人",
        "人妻",
        "熟女",
        "制服",
        "口交",
        "颜射",
        "顏射",
        "内射",
        "潮吹",
        "露出",
        "偷拍",
        "调教",
        "調教",
        "丝袜",
        "絲襪",
        "黑丝",
        "黑絲",
        "足交",
        "出轨",
        "出軌",
        "出轨/ntr",
        "出軌/ntr",
        "ntr",
        "寝取",
        "寝取り",
        "寝取られ",
        "不倫",
        "不伦",
        "绿帽",
        "綠帽",
        "滥交",
        "濫交",
        "肛交",
        "群交",
        "无套",
        "無套",
        "有码",
        "有碼",
        "无码",
        "無碼",
        "中文",
        "中文字幕",
        "日本",
        "国产",
        "國產",
        "免费",
        "免費",
        "在线",
        "在線",
        # 标题尾误抽：企划词 / 姿势 / 片商工序
        "同人撮影",
        "同人摄影",
        "騎乗",
        "骑乘",
        "騎乗位",
        "骑乘位",
        "部活",
        "悶え",
        "扭动之夜",
        "儿媳的扭动之夜",
        "嫁の悶え",
        "妻・母・嫁",
        # 题材/亲属关系词（airav 标签，易被升格成女优）
        "乱伦",
        "亂倫",
        "近亲",
        "近親",
        "继母",
        "繼母",
        "义母",
        "義母",
        "岳母",
        "丈母娘",
        "高中生",
        "女学生",
        "女學生",
        "连裤袜",
        "連褲襪",
        "眼镜娘",
        "眼鏡娘",
        "黑丝",
        "黑絲",
        "丝袜",
        "絲襪",
        # 常见题材词（曾被误写入 <actor>）
        "业余",
        "業餘",
        "素人",
        "乳交",
        "乱交",
        "亂交",
        "亲吻",
        "親吻",
        "接吻",
        "无毛",
        "無毛",
        "自慰",
        "姐姐",
        "企划",
        "企劃",
        "白人",
        "深喉",
        "母乳",
        "舞蹈",
        "水手服",
        "体操服",
        "體操服",
        "萝莉",
        "蘿莉",
        "娇小",
        "嬌小",
        "小柄",
        "迷你裙",
        "辣妹",
        "吞精",
        "破解",
        "无码破解",
        "無碼破解",
        "职业装",
        "職業裝",
        "恋物癖",
        "戀物癖",
        "其他癖好",
        "多人数",
        "多人數",
        "丰满",
        "豐滿",
        "纪录片",
        "紀錄片",
        "猎艳",
        "獵艷",
        "猎豔",
        "温泉",
        "溫泉",
        "搭讪",
        "搭訕",
        "车震",
        "車震",
        "美尻",
        "饮尿",
        "飲尿",
        "女同",
        "主观视角",
        "主觀視角",
        "各种职业",
        "各種職業",
        "立即插入",
        "风俗",
        "風俗",
        "西洋片",
        "我流",
        "捆绑",
        "捆綁",
        "武术格斗",
        "武術格鬥",
        "巨根",
        "运动",
        "運動",
        "精选合集",
        "精選合集",
        "傲娇",
        "傲嬌",
        "过激系",
        "過激系",
        "女大学生",
        "女大學生",
        "4小时",
        "4小時",
        "JK制服",
        "睡虐魔",
        "强奸",
        "強姦",
        "勉强",
        "勉強",
        "淫乱真实",
        "淫亂真實",
        "カノジョ",
        "手交",
        "受孕",
        "秘书",
        "秘書",
        "白天出轨",
        "白天出軌",
        "汤烟频道",
        "湯煙頻道",
        "岁美容师",
        "歲美容師",
        "人间観察ドキュメント",
        "人間観察ドキュメント",
    }
)


_JUNK_ACTOR_SUBSTR = (
    "登入",
    "登录",
    "密码",
    "密碼",
    "注册",
    "註冊",
    "排行",
    "login",
    "password",
    "sign in",
    "forgot",
    "显示更多",
    "顯示更多",
    "查看更多",
    "撮影",
    "摄影",
    "扭动",
    "悶え",
    "dmm独家",
    "dmm獨家",
    "fanza独占",
    "fanza獨占",
    "独家配信",
    "独占配信",
    "數位馬賽克",
    "数位马赛克",
    "数字马赛克",
    "數字馬賽克",
)


_ACT_TAG_FRAG_RE = re.compile(
    r"(舐め|フェラ|性交|挿入|插入|騎乗|骑乘|オナニー|オナホ|中出し|アナル|貫通|贯通|"
    r"ハメ|プレイ|マッサージ|カメラ|視点|视角|視角|二穴|連発|连发|依存|"
    r"无套|無套|后背位|後背位|顔騎|颜面|オリジナル|半外半中|ダブル|"
    r"ご奉仕|個撮|卖挂|賣掛|ATM|贯通|ホス|ホスト|性感内衣|吸うやつ|"
    r"主观视角|主觀視角|女大学生|女大學生|かわいい|"
    r"デカ尻|巨尻|美尻|イチャイチャ|いちゃいちゃ|ちっぱい|微乳|貧乳|贫乳|"
    r"毛あり|毛無し|毛なし|垂れ乳|颜出し|顔出し|ロングヘア|"
    r"雪白肌肤|雪白肌膚|肉オナホ|马乗り|馬乗り|イラマ|ちんこ|ビンタ|"
    r"日本人|年轻少妇|年輕少婦)"
)


def _is_plausible_actress_name(name: str) -> bool:
    """女优栏正向形态：宁可空着，也不收体型/玩法标签。"""
    t = str(name or "").strip()
    if not t or len(t) < 2 or len(t) > 40:
        return False
    if _looks_like_act_tag_token(t):
        return False
    if _looks_like_actor_sentence_frag(t):
        return False
    # 姓 + 假名读
    if re.fullmatch(r"[一-龥々〆ヵヶ]{1,4}[ぁ-んァ-ンー･・]{1,10}", t):
        return True
    # 姓 名（官网空格分隔：横畠 杏菜 / 中村 あゆみ）
    if re.fullmatch(
        r"[一-龥々〆ヵヶ]{1,4}[\s　]+[一-龥々ぁ-んァ-ンー･・]{1,10}",
        t,
    ):
        return True
    # 纯汉字人名（题材 junk / act_tag 已滤）
    # 2～6 字：覆盖「宮田加奈子」「小向美奈子」等 5 字姓名（旧上限 4 会误杀）
    if re.fullmatch(r"[一-龥々]{2,6}", t):
        if t.endswith(("娘", "母", "妻", "父", "妇", "婦", "女", "男", "生")):
            return False
        return True
    # 西洋名 / 中间点名
    if re.search(r"[A-Za-z]", t) or "・" in t or "·" in t:
        return True
    # 纯假名短艺名（ことね）；叠词与体型词已在 act_tag 拦
    if re.fullmatch(r"[ぁ-んァ-ンー]{2,8}", t):
        # 描述性接头：デカ/超/巨 + 体词
        if re.match(r"^(デカ|超|巨|美|微|貧|贫)", t) and len(t) >= 3:
            return False
        return True
    # 汉字 + 假名其它短混合
    if (
        re.search(r"[一-龥]", t)
        and re.search(r"[ぁ-んァ-ン]", t)
        and len(t) <= 16
    ):
        return True
    return False


def _clean_actors(names: list[str] | None) -> list[str]:
    from app.scrape.metadata_optimize import _clean_actor_raw

    out: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        name = _clean_actor_raw(str(raw or ""))
        if not name or len(name) > 40:
            continue
        key = name.casefold()
        if key in _JUNK_ACTORS or key in _JUNK_ACTOR_TAGS or key in seen:
            continue
        if name in _JUNK_TITLE_MARKERS:
            continue
        if _looks_like_act_tag_token(name):
            continue
        if _is_platform_exclusivity_label(name):
            continue
        if any(s in name.casefold() for s in _JUNK_ACTOR_SUBSTR):
            continue
        # 片商/企划名误入女优栏（勿误伤西洋名中的「・」）
        if any(s in name for s in ("プロジェクト", "アネックス", "スタジオ")):
            continue
        if "project" in key or (key.startswith("studio") and len(name) >= 6):
            continue
        # 类型复合词：出轨/NTR、痴女/OL 等
        if "/" in name or "|" in name or "／" in name:
            continue
        # 纯英文缩写题材（NTR、SM、BDAM）
        if re.fullmatch(r"[A-Za-z]{2,8}", name):
            continue
        if _looks_like_actor_sentence_frag(name):
            continue
        # 带数字的前缀/番号（SOD123 / MIMK-286）；纯字母艺名如 Rio 保留
        if re.fullmatch(r"[A-Z]{2,10}-?\d{2,}[A-Z0-9]*", name, re.I):
            continue
        # 纯数字 / URL / HTML
        if re.fullmatch(r"\d+", name) or re.search(r"https?://|<|>", name, re.I):
            continue
        # 正名单：不像人名的（デカ尻/イチャイチャ）直接丢
        if not _is_plausible_actress_name(name):
            continue
        seen.add(key)
        out.append(name)
    return out


_JUNK_TAGS = frozenset(
    {
        "中文",
        "vr",
        "有码",
        "有碼",
        "无码",
        "無碼",
        "会员",
        "登入",
        "登录",
        "首页",
        "home",
        "jav",
        "av",
    }
)


_enrich_lock = threading.RLock()


_strategy_epoch = 0


_strategy_epoch_mu = threading.Lock()


_enrich_retry_front: list[dict[str, Any]] = []


_enrich_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "regionLogs": {},
    "currentRegion": "",
    "cancel": False,  # 兼容旧字段：True 表示收到 halt
    "halt": None,  # None | "pause" | "stop"
    "queue": [],
    "current": None,
    "result": None,
    "error": None,
    # region_id -> 暂停检查点（剩余队列，再开即继续）
    "checkpoints": {},
    # 当前轮次元数据（暂停立刻写检查点时用）
    "jobMode": "incremental",
    "jobKinds": [],
    "jobDryRun": False,
}


_enrich_watchers_lock = threading.Lock()


_enrich_watchers: list[threading.Event] = []


_enrich_notify_last = 0.0


_ENRICH_NOTIFY_MIN_GAP = 0.7


_ENRICH_NOTIFY_FORCE_MIN_GAP = 0.35


def subscribe_enrich_updates() -> threading.Event:
    ev = threading.Event()
    with _enrich_watchers_lock:
        _enrich_watchers.append(ev)
    ev.set()  # 立刻推一帧快照
    return ev


def unsubscribe_enrich_updates(ev: threading.Event) -> None:
    with _enrich_watchers_lock:
        try:
            _enrich_watchers.remove(ev)
        except ValueError:
            pass


def notify_enrich_watchers(*, force: bool = False) -> None:
    """唤醒 SSE 订阅端。force=阶段切换；普通进度有最小间隔合并。"""
    global _enrich_notify_last
    now = time.monotonic()
    gap = _ENRICH_NOTIFY_FORCE_MIN_GAP if force else _ENRICH_NOTIFY_MIN_GAP
    if (now - _enrich_notify_last) < gap:
        return
    _enrich_notify_last = now
    with _enrich_watchers_lock:
        watchers = list(_enrich_watchers)
    for ev in watchers:
        ev.set()


def _checkpoint_summaries() -> dict[str, Any]:
    raw = dict(_enrich_job.get("checkpoints") or {})
    out: dict[str, Any] = {}
    for rid, cp in raw.items():
        key = str(rid or "").strip()
        if not key or not isinstance(cp, dict):
            continue
        remaining = cp.get("queue") or []
        sample_n = len(remaining) if isinstance(remaining, list) else 0
        rem_n = max(int(cp.get("remainingCount") or 0), sample_n)
        done = int(cp.get("done") or 0)
        total = int(cp.get("originalTotal") or (done + rem_n))
        out[key] = {
            "region": key,
            "mode": str(cp.get("mode") or "incremental"),
            "dryRun": bool(cp.get("dryRun")),
            "done": done,
            "remaining": rem_n,
            "total": total,
            "ok": int(cp.get("ok") or 0),
            "failed": int(cp.get("failed") or 0),
        }
    return out


def _write_enrich_log_batch(rows: list[tuple[str, str]]) -> None:
    """**一次事务**写多行日志 + 每个 region 只裁剪一次。

    第九轮：原实现一行一次事务（552 ms/番号，13 行），实测同样 20 行
    504 ms（各自事务）→ 74 ms（一个事务 + 一次裁剪）。裁剪 SQL 语义与原来
    逐行版一致（保留该 region 最新 `_ENRICH_LOG_KEEP` 行）。
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
                (rid, rid, max(0, _ENRICH_LOG_KEEP - 1)),
            )
        conn.commit()


_enrich_log_sink = enrich_log_sink.LogBatcher(
    _write_enrich_log_batch, flush_sec=0.25, max_delay=3.0, min_rows=24, label="enrich_log"
)


_hist_log_cache: dict[tuple[str, int], tuple[float, list[str]]] = {}


def _push_log(msg: str, *, region: str | None = None) -> None:
    text = str(msg)
    rid = ""
    with _enrich_lock:
        # 停止后不再写日志，避免清完又被当前番号灌回
        if _enrich_job.get("halt") == "stop":
            return
        log_list = list(_enrich_job.get("log") or [])
        log_list.append(text)
        _enrich_job["log"] = log_list[-80:]
        raw = str(region or _enrich_job.get("currentRegion") or "").strip()
        rid = _canonical_enrich_log_region(raw) if raw else "_all"
        if rid and rid != "_all":
            region_logs = dict(_enrich_job.get("regionLogs") or {})
            bucket = list(region_logs.get(rid) or [])
            bucket.append(text)
            region_logs[rid] = bucket[-_ENRICH_LOG_MEMORY:]
            _enrich_job["regionLogs"] = region_logs
    _persist_enrich_log(rid or "_all", text)
    notify_enrich_watchers()


def _queue_log_region(region: str | None = None) -> str:
    rid = _canonical_enrich_log_region(region or "")
    return "" if rid == "_all" else rid


_counts_cache: dict[str, tuple[float, dict[str, int]]] = {}


_COUNTS_CACHE_TTL_SEC = 1.2


_counts_ok_cache: dict[str, tuple[float, bool]] = {}


_scrape_counts_cache: dict[str, tuple[float, dict[str, int]]] = {}


_LOCAL_STATUS_TOTALS: dict[str, dict[str, int]] = {}


_LOCAL_STATUS_TOTALS_LOADED = False


_LOCAL_STATUS_TOTALS_LOCK = threading.Lock()


def _local_status_totals_path() -> Path:
    return media_dir() / "scrap-library" / "_local_status_totals.json"


def _ensure_local_status_totals_loaded() -> None:
    global _LOCAL_STATUS_TOTALS_LOADED
    if _LOCAL_STATUS_TOTALS_LOADED:
        return
    with _LOCAL_STATUS_TOTALS_LOCK:
        if _LOCAL_STATUS_TOTALS_LOADED:
            return
        _LOCAL_STATUS_TOTALS_LOADED = True
        path = _local_status_totals_path()
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
    _set_local_status_totals(rid, done=done, soft=soft, fail=fail, total=tot or None)


_QUEUE_SCAN_LOCK = threading.Lock()


_QUEUE_SCAN_STATE: dict[str, Any] = {
    "active": False,
    "region": "",
    "stage": "",
    "label": "",
    "scanned": 0,
    "total": 0,
    "done": 0,
    "soft": 0,
    "fail": 0,
    "pending": 0,
    "samplesDone": [],
    "samplesSoft": [],
    "samplesFail": [],
    "updatedAt": 0.0,
}


_queue_scan_notify_last = 0.0


def _set_queue_scan_progress(
    *,
    region: str = "",
    stage: str = "",
    label: str = "",
    scanned: int | None = None,
    total: int | None = None,
    done: int | None = None,
    soft: int | None = None,
    fail: int | None = None,
    pending: int | None = None,
    active: bool = True,
    notify: bool = True,
) -> None:
    """更新清空·扫描进度；notify 时唤醒 SSE（节流）。"""
    global _queue_scan_notify_last
    rid = _queue_log_region(region) if str(region or "").strip() else ""
    with _QUEUE_SCAN_LOCK:
        if not active:
            _QUEUE_SCAN_STATE.update(
                {
                    "active": False,
                    "region": "",
                    "stage": "",
                    "label": "",
                    "scanned": 0,
                    "total": 0,
                    "done": 0,
                    "soft": 0,
                    "fail": 0,
                    "pending": 0,
                    "samplesDone": [],
                    "samplesSoft": [],
                    "samplesFail": [],
                    "updatedAt": time.monotonic(),
                }
            )
        else:
            if rid:
                _QUEUE_SCAN_STATE["region"] = rid
            if stage:
                _QUEUE_SCAN_STATE["stage"] = str(stage)
            if label:
                _QUEUE_SCAN_STATE["label"] = str(label)
            if scanned is not None:
                _QUEUE_SCAN_STATE["scanned"] = max(0, int(scanned))
            if total is not None:
                _QUEUE_SCAN_STATE["total"] = max(0, int(total))
            if done is not None:
                _QUEUE_SCAN_STATE["done"] = max(0, int(done))
            if soft is not None:
                _QUEUE_SCAN_STATE["soft"] = max(0, int(soft))
            if fail is not None:
                _QUEUE_SCAN_STATE["fail"] = max(0, int(fail))
            if pending is not None:
                _QUEUE_SCAN_STATE["pending"] = max(0, int(pending))
            _QUEUE_SCAN_STATE["active"] = True
            _QUEUE_SCAN_STATE["updatedAt"] = time.monotonic()
    if not notify:
        return
    now = time.monotonic()
    # 阶段切换强制推；计数进度按间隔合并，避免 10 万盘扫打爆 SSE
    force = bool(stage) and scanned is None
    gap = 0.12 if force else _QUEUE_SCAN_NOTIFY_GAP
    if (now - _queue_scan_notify_last) < gap and not force:
        return
    _queue_scan_notify_last = now
    try:
        notify_enrich_watchers(force=force)
    except Exception:  # noqa: BLE001
        pass


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
        pool = get_meta_pool()
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
        folder = _resolve_enrich_folder(
            region=rid or region,
            code=code_u,
            item_id=iid,
        )

    if folder is not None:
        local_detail, fields, local_ok = _detail_from_local_folder(
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
    fields = _detail_field_rows(detail)
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
    chunk_n = max(50, min(1000, int(_QUEUE_LOG_INSERT_CHUNK or 500)))
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
                    params.extend(_queue_log_insert_params(rid, r))
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
    lid = _queue_log_int_id(row)
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
            payload_base = _queue_log_read_payload(conn, target_id)
            # 完成态优先保留/写入刮削结果，勿被 running 空包覆盖
            params = _queue_log_insert_params(
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
                        base2 = _queue_log_read_payload(conn, retry_id)
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
                        params = _queue_log_insert_params(
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


_stale_running_last: dict[str, float] = {}


_STALE_RUNNING_MIN_INTERVAL_SEC = 3.0


def retry_enrich_fails(*, region: str = "") -> dict[str, Any]:
    """失败批量重试：转入未处理，并尽量插到当前任务最前优先跑。"""
    global _enrich_retry_front
    rid = _queue_log_region(region)
    if not rid:
        return {"ok": False, "reopened": 0, "error": "region required"}
    rows = _queue_log_reopen_fails(rid)
    n = len(rows)
    if n <= 0:
        # 仍可能因 overlay 显示有失败：以库内真实值为准同步角标
        raw = _queue_log_status_counts_db(rid)
        tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
        if tip:
            _set_local_status_totals(
                rid,
                done=int(raw.get("done") or tip.get("done") or 0),
                soft=int(raw.get("soft") or tip.get("soft") or 0),
                fail=int(raw.get("fail") or 0),
            )
        _counts_cache.pop(rid, None)
        counts = _queue_log_status_counts(rid, fresh=True)
        counts["fail"] = int(raw.get("fail") or 0)
        # pending 以队列表为准，不用向量估算覆盖
        return {
            "ok": True,
            "reopened": 0,
            "region": rid,
            "counts": counts,
            "injected": False,
        }

    # 解除封面/源放弃，否则重开后仍会被跳过
    try:
        codes = [
            str(r.get("code") or "").strip().upper()
            for r in rows
            if str(r.get("code") or "").strip()
        ]
        _retry_hint_clear_codes(rid, codes)
    except Exception:  # noqa: BLE001
        pass

    injected = False
    with _enrich_lock:
        cur_reg = _queue_log_region(str(_enrich_job.get("currentRegion") or ""))
        running = bool(_enrich_job.get("running"))
        # 检查点：插到剩余队列头，失败计数下调
        cps = dict(_enrich_job.get("checkpoints") or {})
        cp = cps.get(rid) if isinstance(cps.get(rid), dict) else None
        if isinstance(cp, dict):
            old_q = [dict(r) for r in list(cp.get("queue") or []) if isinstance(r, dict)]
            # 去重：已在剩余队列的不重复插
            seen_keys = {
                str(r.get("itemId") or r.get("code") or "").strip()
                for r in old_q
            }
            head = [
                r
                for r in rows
                if str(r.get("itemId") or r.get("code") or "").strip() not in seen_keys
            ]
            cp = dict(cp)
            cp["queue"] = head + old_q
            cp["remainingCount"] = max(
                int(cp.get("remainingCount") or 0) + len(head),
                len(cp["queue"]),
            )
            cp["failed"] = max(0, int(cp.get("failed") or 0) - n)
            cps[rid] = cp
            _enrich_job["checkpoints"] = cps
        if running and cur_reg == rid:
            # 插到投递前端；同键去重
            existing = {
                str(r.get("itemId") or r.get("code") or "").strip()
                for r in _enrich_retry_front
                if isinstance(r, dict)
            }
            add = [
                dict(r)
                for r in rows
                if str(r.get("itemId") or r.get("code") or "").strip() not in existing
            ]
            _enrich_retry_front = add + list(_enrich_retry_front)
            injected = True
            # 本轮进度失败数下调（避免角标虚高）
            prog = _enrich_job.get("progress")
            if isinstance(prog, dict):
                prog = dict(prog)
                prog["failed"] = max(0, int(prog.get("failed") or 0) - n)
                _enrich_job["progress"] = prog
        # 运行中 SSE 只读内存 queueCounts。失败数写成重开后的真实剩余，不能只减一截旧角标。
        if cur_reg == rid or not cur_reg:
            qc_mem = dict(_enrich_job.get("queueCounts") or {})
            if qc_mem:
                qc_mem["pending"] = int(qc_mem.get("pending") or 0) + n
                _enrich_job["queueCounts"] = qc_mem

    try:
        _persist_enrich_runtime()
    except Exception:  # noqa: BLE001
        pass

    # 角标：失败 overlay 必须跟库内走，否则会一直钉在扫描时的全量失败数
    raw = _queue_log_status_counts_db(rid)
    tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
    fail_left = int(raw.get("fail") or 0)
    _set_local_status_totals(
        rid,
        done=int(raw.get("done") or (tip or {}).get("done") or 0),
        soft=int(raw.get("soft") or (tip or {}).get("soft") or 0),
        fail=fail_left,
    )
    with _enrich_lock:
        qc_mem = dict(_enrich_job.get("queueCounts") or {})
        if qc_mem:
            qc_mem["fail"] = fail_left
            _enrich_job["queueCounts"] = qc_mem
    _counts_cache.pop(rid, None)

    _push_log(f"失败重试 · {n} 条 → 未处理优先", region=rid)
    try:
        notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    counts = _queue_log_status_counts(rid, fresh=True)
    counts["fail"] = fail_left
    return {
        "ok": True,
        "reopened": n,
        "region": rid,
        "counts": counts,
        "injected": injected,
        "running": bool(_enrich_job.get("running")),
    }


def retry_enrich_softs(*, region: str = "") -> dict[str, Any]:
    """软成功批量重试：转入未处理，并尽量插到当前任务最前优先跑。"""
    global _enrich_retry_front
    rid = _queue_log_region(region)
    if not rid:
        return {"ok": False, "reopened": 0, "error": "region required"}
    rows = _queue_log_reopen_softs(rid)
    n = len(rows)
    if n <= 0:
        raw = _queue_log_status_counts_db(rid)
        tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
        if tip:
            _set_local_status_totals(
                rid,
                done=int(raw.get("done") or tip.get("done") or 0),
                soft=int(raw.get("soft") or 0),
                fail=int(raw.get("fail") or tip.get("fail") or 0),
            )
        _counts_cache.pop(rid, None)
        counts = _queue_log_status_counts(rid, fresh=True)
        return {
            "ok": True,
            "reopened": 0,
            "region": rid,
            "counts": counts,
            "injected": False,
        }

    try:
        codes = [
            str(r.get("code") or "").strip().upper()
            for r in rows
            if str(r.get("code") or "").strip()
        ]
        _retry_hint_clear_codes(rid, codes)
    except Exception:  # noqa: BLE001
        pass

    injected = False
    with _enrich_lock:
        cur_reg = _queue_log_region(str(_enrich_job.get("currentRegion") or ""))
        running = bool(_enrich_job.get("running"))
        cps = dict(_enrich_job.get("checkpoints") or {})
        cp = cps.get(rid) if isinstance(cps.get(rid), dict) else None
        if isinstance(cp, dict):
            old_q = [dict(r) for r in list(cp.get("queue") or []) if isinstance(r, dict)]
            seen_keys = {
                str(r.get("itemId") or r.get("code") or "").strip()
                for r in old_q
            }
            head = [
                r
                for r in rows
                if str(r.get("itemId") or r.get("code") or "").strip() not in seen_keys
            ]
            cp = dict(cp)
            cp["queue"] = head + old_q
            cp["remainingCount"] = max(
                int(cp.get("remainingCount") or 0) + len(head),
                len(cp["queue"]),
            )
            # 软成功原先计入 ok
            cp["ok"] = max(0, int(cp.get("ok") or 0) - n)
            cps[rid] = cp
            _enrich_job["checkpoints"] = cps
        if running and cur_reg == rid:
            existing = {
                str(r.get("itemId") or r.get("code") or "").strip()
                for r in _enrich_retry_front
                if isinstance(r, dict)
            }
            add = [
                dict(r)
                for r in rows
                if str(r.get("itemId") or r.get("code") or "").strip() not in existing
            ]
            _enrich_retry_front = add + list(_enrich_retry_front)
            injected = True
            prog = _enrich_job.get("progress")
            if isinstance(prog, dict):
                prog = dict(prog)
                prog["ok"] = max(0, int(prog.get("ok") or 0) - n)
                _enrich_job["progress"] = prog
        if cur_reg == rid or not cur_reg:
            qc_mem = dict(_enrich_job.get("queueCounts") or {})
            if qc_mem:
                qc_mem["pending"] = int(qc_mem.get("pending") or 0) + n
                _enrich_job["queueCounts"] = qc_mem

    try:
        _persist_enrich_runtime()
    except Exception:  # noqa: BLE001
        pass

    raw = _queue_log_status_counts_db(rid)
    tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
    soft_left = int(raw.get("soft") or 0)
    _set_local_status_totals(
        rid,
        done=int(raw.get("done") or (tip or {}).get("done") or 0),
        soft=soft_left,
        fail=int(raw.get("fail") or (tip or {}).get("fail") or 0),
    )
    with _enrich_lock:
        qc_mem = dict(_enrich_job.get("queueCounts") or {})
        if qc_mem:
            qc_mem["soft"] = soft_left
            _enrich_job["queueCounts"] = qc_mem
    _counts_cache.pop(rid, None)

    _push_log(f"软成功重试 · {n} 条 → 未处理优先", region=rid)
    try:
        notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    counts = _queue_log_status_counts(rid, fresh=True)
    counts["soft"] = soft_left
    counts["done"] = int(raw.get("done") or counts.get("done") or 0)
    return {
        "ok": True,
        "reopened": n,
        "region": rid,
        "counts": counts,
        "injected": injected,
        "running": bool(_enrich_job.get("running")),
    }


def _maybe_prune_done_logs(region: str) -> None:
    """完成若干条后异步裁剪 done，避免拖慢主路径。"""
    global _finish_prune_counter
    with _finish_prune_lock:
        _finish_prune_counter += 1
        n = int(_finish_prune_counter)
    if n % int(_QUEUE_LOG_PRUNE_EVERY) != 0:
        return
    rid = str(region or "").strip()
    if not rid:
        return

    def _run() -> None:
        try:
            dropped = _queue_log_prune_done_keep(rid)
            if dropped:
                _push_log(f"队列表裁剪 done · -{dropped}", region=rid)
        except Exception:  # noqa: BLE001
            pass

    threading.Thread(target=_run, name="enrich-prune-done", daemon=True).start()


_incomplete_cache: dict[str, tuple[float, int, int]] = {}


_INCOMPLETE_CACHE_TTL_SEC = 45.0


def _fresh_vector_library_total(region: str, *, force: bool = False) -> int:
    """向量库该区番号总数（轻量 COUNT）。

    tip.total 会在双库扫描/骨架重建后落后；扫描与未处理角标必须以库为准。
    默认走短缓存，扫描传 force=True 强制刷新。
    """
    rid = _queue_log_region(region)
    if not rid:
        return 0
    now = time.time()
    if not force:
        hit = _incomplete_cache.get(rid)
        if hit and now - float(hit[0]) < _INCOMPLETE_CACHE_TTL_SEC:
            cached = int(hit[1] or 0)
            if cached > 0:
                return cached
    live = 0
    try:
        from app.scrap_library.embed import region_library_totals_fast

        live = int(region_library_totals_fast(region=rid).get("total") or 0)
    except Exception:  # noqa: BLE001
        live = 0
    if live > 0:
        prev_inc = 0
        hit = _incomplete_cache.get(rid)
        if hit:
            prev_inc = int(hit[2] or 0)
        _incomplete_cache[rid] = (now, live, prev_inc)
        # 同步 tip.total，避免后续路径继续用旧目录量级
        _ensure_local_status_totals_loaded()
        tip = _LOCAL_STATUS_TOTALS.get(rid) or {}
        if int(tip.get("total") or 0) != live:
            _set_local_status_totals(
                rid,
                done=int(tip.get("done") or 0),
                soft=int(tip.get("soft") or 0),
                fail=int(tip.get("fail") or 0),
                total=live,
            )
    return max(0, live)


_classified_skip_cache: dict[str, tuple[float, set[str], set[str]]] = {}


_CLASSIFIED_SKIP_TTL_SEC = 120.0


_pending_backfill_done: set[str] = set()


_local_nfo_maps_cache: dict[str, tuple[float, set[str], set[str], int, int, int]] = {}


_LOCAL_NFO_MAPS_TTL_SEC = 900.0


_LOCAL_NFO_MAPS_CACHE_MAX = 2


def _invalidate_classified_skip_cache(region: str = "") -> None:
    rid = _queue_log_region(region) if str(region or "").strip() else ""
    if rid:
        _classified_skip_cache.pop(rid, None)
    else:
        _classified_skip_cache.clear()


_DONE_LOG_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9\-_]{1,24})\s*·\s*完成"
)


_folder_gaps_cache: dict[str, tuple[tuple[Any, ...], tuple[str, list[str]]]] = {}


_FOLDER_GAPS_CACHE_CAP = 160_000


_folder_gaps_cache_lock = threading.Lock()


def iter_enrich_pending_items(
    *,
    region: str,
    limit: int = 0,
    skip_item_ids: set[str] | None = None,
    skip_codes: set[str] | None = None,
    local_maps: _LocalNfoMaps | None = None,
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
    maps = local_maps if isinstance(local_maps, _LocalNfoMaps) else _local_nfo_gap_maps(
        region=rid or region
    )
    local_classified = maps.skip_rels
    local_codes = maps.classified_codes

    # 角标：每次以向量库最新 COUNT 为准，再扣本地已分类
    vector_total = _fresh_vector_library_total(rid or region, force=True)
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
            gaps = list(_ENRICH_KINDS)
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
        cached = _local_nfo_maps_cache_get(cache_key)
        if cached is not None:
            skip_set, code_set, d_n, s_n, f_n = cached
            marker = _CachedLocalMapsMarker(skip_set, code_set, d_n, s_n, f_n)
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
        _set_progress(
            stage="disk",
            label="扫描本地 NFO 分类…（首次约 2~5 分钟）",
            done=0,
            total=0,
        )
        try:
            maps = _local_nfo_gap_maps(region=cache_key, report_progress=True)
        except TypeError:
            maps = _local_nfo_gap_maps(region=cache_key)
        local_maps = maps
        local_classified = maps.skip_rels
        local_codes = maps.classified_codes
        _local_nfo_maps_cache_put(cache_key, maps)
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
    cover_giveup = _cover_giveup_codes(rid or region)
    # 源故障补抓：能进队列表的抬到未处理队首（与列表同序）；
    # 本地已齐、不在 pending 里的仍要显式补出，否则永远没人回头修。
    src_retry = [
        h
        for h in _retry_hint_load(rid or region, _RETRY_KIND_SRC_DOWN)
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
        if _should_skip_for_giveup(
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
            item_h = _src_retry_item(h, region=rid or region)
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
        gaps = list(r.get("gaps") or []) or list(_ENRICH_KINDS)
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
            int((_queue_log_status_counts_db(rid or region) or {}).get("pending") or 0)
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
                if _halt_kind():
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
                        it = _queue_log_row_to_item(r)
                    else:
                        it = _queue_log_row_to_item(
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
    hot_prefs = _hot_prefixes_for_region(rid or region, max_n=80)
    if hot_prefs:
        _push_log(
            f"队列切片 · 热门前缀 {len(hot_prefs)} · "
            f"{','.join(hot_prefs[:12])}{'…' if len(hot_prefs) > 12 else ''}",
            region=rid or region,
        )
    off = 0
    while True:
        if _halt_kind():
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
        if _halt_kind():
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
    if st not in _QUEUE_LOG_FILTER_STATUSES:
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
    counts = _empty_queue_counts()
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
                out.append(_queue_log_row_to_item(r))
            else:
                out.append(
                    _queue_log_row_to_item(
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
        soft_pred = _soft_done_sql_pred(error_col="error")
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
            counts = _apply_local_status_totals(counts, rid)

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
                    items = _lookup_code_outside_queue_log(
                        region=rid, code_q=code_q, limit=lim
                    )
                elif bool(_QUEUE_SCAN_STATE.get("active")):
                    # 扫描中样例可能尚未入库：只并内存命中
                    extra = _lookup_code_from_scan_samples(
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
                    items[i] = _backfill_queue_item_detail(it, region=rid)
            elif st:
                # 成功/软成功/失败：按最近更新时间（刚刮完的在最上）
                # 未处理：虚拟翻页（向量 − 已分类），total 用估算全量
                if st == "pending":
                    total = int(db_counts.get("pending") or 0)
                    counts["pending"] = total
                    items = _pending_page_from_vector(
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
                            items[i] = _backfill_queue_item_detail(it, region=rid)
            else:
                total = sum(int(db_counts.get(k) or 0) for k in db_counts)
    except Exception as e:  # noqa: BLE001
        log.warning("load enrich queue log failed region=%s: %s", rid, e)
    counts = _apply_local_status_totals(counts, rid)
    counts = _clamp_pending_badge(counts, rid)
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
    out = _sample_queue_uncached(raw_queue, limit=limit)
    _queue_sample_cache = (raw_queue, n_all, limit, out)
    return out


_incomplete_cache: dict[str, tuple[float, int, int]] = {}


_INCOMPLETE_CACHE_TTL_SEC = 45.0


_lib_progress_counts_cache: dict[str, tuple[float, dict[str, int]]] = {}


_LIB_PROGRESS_COUNTS_TTL_SEC = 3.0


def _set_current_region(region_id: str = "") -> None:
    with _enrich_lock:
        _enrich_job["currentRegion"] = str(region_id or "").strip()


def _set_queue(rows: list[dict[str, Any]]) -> None:
    """写入完整处理队列；状态接口只抽样回传。"""
    with _enrich_lock:
        cleaned = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        _enrich_job["queue"] = cleaned
        _enrich_job["queueCounts"] = _queue_counts_of(cleaned)
    notify_enrich_watchers(force=True)


def _patch_queue_item(
    index: int,
    *,
    match: dict[str, Any] | None = None,
    persist: bool = True,
    **fields: Any,
) -> None:
    """改内存队列行（UI 立即生效）；persist=False 只改内存不落库。

    persist=False 专供**预览（dryRun）**：预览行标 done 若落进
    enrich_queue_log，会被 `_queue_log_prune_open_if_done` 当成「同番号已有成功」
    从而删掉真正的 pending 行 —— 待刮条目就此消失（假成功）。
    """
    updated: dict[str, Any] | None = None
    region = ""
    resolved_i = -1
    st_in = str(fields.get("status") or "").strip().lower()
    with _enrich_lock:
        halt = _enrich_job.get("halt")
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
        queue = list(_enrich_job.get("queue") or [])
        resolved_i = _queue_row_match_index(queue, index=index, match=match)
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
                _enrich_job["queue"] = _cap_status_queue(kept)
                counts = dict(_enrich_job.get("queueCounts") or {})
                n_run = sum(
                    1
                    for r in _enrich_job["queue"]
                    if isinstance(r, dict) and str(r.get("status") or "") == "running"
                )
                counts["running"] = max(int(counts.get("running") or 0), n_run)
                for k in ("pending", "running", "done", "fail", "soft"):
                    counts[k] = int(counts.get(k) or 0)
                _enrich_job["queueCounts"] = counts
                updated = base
                region = str(
                    base.get("region") or _enrich_job.get("currentRegion") or ""
                )
            # 截断后内存里可能已没有该行：仍用 match 身份落库，避免丢终态
            elif isinstance(match, dict) and st_in in {"done", "fail", "pending"}:
                base = dict(match)
                base.update(fields)
                updated = base
                region = str(
                    base.get("region") or _enrich_job.get("currentRegion") or ""
                )
                # 展示队列只有 ~120 行；丢行后若不改角标，成功数/部/分会假死在早期值
                counts = dict(_enrich_job.get("queueCounts") or {})
                old_st = str(match.get("status") or "").strip().lower()
                if old_st not in {"pending", "running", "done", "fail"}:
                    old_st = "running" if st_in in {"done", "fail"} else "pending"
                if old_st != st_in:
                    counts[old_st] = max(0, int(counts.get(old_st) or 0) - 1)
                    counts[st_in] = int(counts.get(st_in) or 0) + 1
                for k in ("pending", "running", "done", "fail", "soft"):
                    counts[k] = int(counts.get(k) or 0)
                _enrich_job["queueCounts"] = counts
                base_prog = dict(_enrich_job.get("progress") or {})
                _enrich_job["progress"] = _progress_from_queue_counts(
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
            _enrich_job["queue"] = queue
            counts = dict(_enrich_job.get("queueCounts") or {}) or _queue_counts_of(queue)
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
            _enrich_job["queueCounts"] = counts
            # 同步进度，避免轮询间隙 percent 乱跳
            base = dict(_enrich_job.get("progress") or {})
            _enrich_job["progress"] = _progress_from_queue_counts(counts, base=base)
            updated = dict(row)
            region = str(
                row.get("region") or _enrich_job.get("currentRegion") or ""
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
            if lid and resolved_i >= 0 and int(lid) != _queue_log_int_id(updated):
                with _enrich_lock:
                    queue = list(_enrich_job.get("queue") or [])
                    if 0 <= resolved_i < len(queue):
                        row = dict(queue[resolved_i] or {})
                        row["logId"] = lid
                        queue[resolved_i] = row
                        _enrich_job["queue"] = queue
                        updated = dict(row)
            if str(updated.get("status") or "").strip().lower() == "running":
                keep = int(lid or _queue_log_int_id(updated) or 0)
                _queue_log_prune_pending_if_running(
                    region,
                    code=str(updated.get("code") or ""),
                    item_id=str(updated.get("itemId") or ""),
                    keep_id=keep,
                )
        notify_enrich_watchers()


def _set_current(payload: dict[str, Any] | None) -> None:
    with _enrich_lock:
        _enrich_job["current"] = payload
    notify_enrich_watchers()


_GAP_FAIL_LABEL = {
    "no_local": "封面",
    "no_media": "外链",
    "no_actress": "女优",
    "no_studio": "片商",
    "no_plot": "剧情",
    "thin_title": "标题",
    "no_zh_title": "中文标题",
}


_COVER_FAIL_LABEL = {
    "slot_blocked": "封面队列繁忙",
    "timeout": "封面超时",
    "download": "封面下载失败",
    "host_blocked": "图床暂时不可用",
    "blank": "封面空图",
    "too_small": "封面尺寸过小",
    "write_fail": "封面写入失败",
    "all_failed": "封面全部候选失败",
    "no_candidates": "无封面候选",
    "kept_old": "保留旧封面",
}


_SUCCESS_BLOCK_GAPS = frozenset({"no_local", "thin_title"})


_SOFT_SUCCESS_GAPS = frozenset({"no_actress", "no_studio"})


_SOFT_GAP_LABELS = frozenset(
    {_GAP_FAIL_LABEL[g] for g in _SOFT_SUCCESS_GAPS if g in _GAP_FAIL_LABEL}
)


_promoted_actress_soft: dict[str, int] = {}


_demoted_false_dones: set[str] = set()


_soft_correction_last: dict[str, float] = {}


_COVER_ONLY_GAPS = frozenset({"no_local", "no_media"})


_retry_hint_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}


_retry_hint_known: dict[tuple[str, str], set[str]] = {}


_retry_hint_primed: set[tuple[str, str]] = set()


_SOURCE_DOWN_STREAK: dict[str, int] = {}


_SOURCE_COOLDOWN_UNTIL: dict[str, float] = {}


_SOURCE_COOLDOWN_LOCK = threading.Lock()


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
    rid = _queue_log_region(region) or region
    if not c or not rid:
        return 0, False
    key = (rid, str(kind or ""))
    if not need:
        if c not in _retry_hint_known.get(key, set()):
            # 首次清零前预热一次 known（每个 (region,kind) 进程内只做一次库读）。
            # 不预热的话，「单号重刮」这类不走队列构建的路径会漏掉清零。
            if key not in _retry_hint_primed:
                _retry_hint_load(rid, kind)
            if c not in _retry_hint_known.get(key, set()):
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
            _retry_hint_known.setdefault(key, set()).discard(c)
            _retry_hint_invalidate(rid, kind)
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
            n, giveup = _retry_next_state(cur_attempts, cap=cap)
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
        _retry_hint_known.setdefault(key, set()).add(c)
        _retry_hint_invalidate(rid, kind)
        return n, giveup
    except Exception as e:  # noqa: BLE001
        log.debug("retry hint note failed code=%s kind=%s: %s", c, kind, e)
        return 0, False


def _fill_mode_to_job_mode(fill_mode: str) -> str:
    raw = str(fill_mode or "incremental").strip().lower()
    if raw in {"overwrite", "cover", "force", "replace", "full"}:
        return "overwrite"
    if raw in {"refresh_weak", "weak", "refresh"}:
        return "refresh_weak"
    return "incremental"


def bump_strategy_epoch() -> int:
    global _strategy_epoch
    with _strategy_epoch_mu:
        _strategy_epoch += 1
        return int(_strategy_epoch)


def _persist_enrich_runtime() -> None:
    """把检查点 + 任务快照写入 app_settings（跨重启）。"""
    try:
        from app.core import job_persist

        with _enrich_lock:
            cps_raw = dict(_enrich_job.get("checkpoints") or {})
            cps_out: dict[str, Any] = {}
            for rid, cp in cps_raw.items():
                if not isinstance(cp, dict):
                    continue
                row = _checkpoint_for_persist(
                    {
                        **cp,
                        "region": str(cp.get("region") or rid),
                    }
                )
                cps_out[str(rid)] = row
            snapshot = {
                "phase": str(_enrich_job.get("phase") or ""),
                "progress": dict(_enrich_job.get("progress") or {}) or None,
                "jobMode": str(_enrich_job.get("jobMode") or "incremental"),
                "jobKinds": list(_enrich_job.get("jobKinds") or []),
                "jobDryRun": bool(_enrich_job.get("jobDryRun")),
                "currentRegion": str(_enrich_job.get("currentRegion") or ""),
                "result": _slim_result_for_status(_enrich_job.get("result")),
                "error": _enrich_job.get("error"),
                "running": bool(_enrich_job.get("running")),
                "halt": _enrich_job.get("halt"),
            }
            # 运行中落盘标 interrupted，便于重启后识别可续
            status = "idle"
            if snapshot["running"]:
                status = "running"
            elif cps_out or str(snapshot["phase"]) == "paused":
                status = "paused"
            elif str(snapshot["phase"]) in {"stopped", "cleared"}:
                status = "stopped"
            elif str(snapshot["phase"]) == "done":
                status = "done"
            elif str(snapshot["phase"]) == "error":
                status = "error"
            payload = {
                "status": status,
                "checkpoints": cps_out,
                "snapshot": snapshot,
            }
        job_persist.save_job(job_persist.ENRICH_RUNTIME_KEY, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("persist enrich runtime failed: %s", e)


_enrich_hydrated = False


_enrich_hydrate_lock = threading.Lock()


def _hydrate_enrich_runtime(*, force: bool = False) -> None:
    """进程启动后首次从 DB 恢复检查点/快照。"""
    global _enrich_hydrated
    with _enrich_hydrate_lock:
        if _enrich_hydrated and not force:
            return
        _enrich_hydrated = True
    try:
        from app.core import job_persist

        raw = job_persist.load_job(job_persist.ENRICH_RUNTIME_KEY)
        if not raw:
            return
        cps_in = raw.get("checkpoints") if isinstance(raw.get("checkpoints"), dict) else {}
        snap = raw.get("snapshot") if isinstance(raw.get("snapshot"), dict) else {}
        rebuilt: dict[str, Any] = {}
        need_rewrite = False
        for rid, cp in cps_in.items():
            if not isinstance(cp, dict):
                continue
            key = str(rid or "").strip()
            if not key:
                continue
            queue = [dict(r) for r in list(cp.get("queue") or []) if isinstance(r, dict)]
            rem_n = int(cp.get("remainingCount") or 0) or len(queue)
            # 旧版把整队塞进 settings：内存/落盘都截断，续跑走 enrich_queue_log
            if len(queue) > _CHECKPOINT_PERSIST_QUEUE_MAX:
                need_rewrite = True
                rem_n = max(rem_n, len(queue))
                queue = queue[:_CHECKPOINT_PERSIST_QUEUE_MAX]
            # 无抽样且声明有剩余时，不要在 hydrate 拉全表（会卡死启动）
            rebuilt[key] = {
                "region": str(cp.get("region") or key),
                "mode": str(cp.get("mode") or "incremental"),
                "kinds": list(cp.get("kinds") or []),
                "dryRun": bool(cp.get("dryRun")),
                "ok": int(cp.get("ok") or 0),
                "failed": int(cp.get("failed") or 0),
                "done": int(cp.get("done") or 0),
                "originalTotal": int(cp.get("originalTotal") or 0),
                "queue": queue,
                "remainingCount": rem_n,
                "queueInLog": bool(cp.get("queueInLog")) or rem_n > len(queue),
            }
        with _enrich_lock:
            if _enrich_job.get("running"):
                return
            if rebuilt:
                _enrich_job["checkpoints"] = rebuilt
            # 仅在空闲时回填展示用快照
            if snap and not _enrich_job.get("running"):
                if snap.get("phase") and not _enrich_job.get("phase"):
                    _enrich_job["phase"] = str(snap.get("phase") or "")
                if snap.get("progress") and not _enrich_job.get("progress"):
                    _enrich_job["progress"] = dict(snap.get("progress") or {})
                if snap.get("jobMode"):
                    _enrich_job["jobMode"] = str(snap.get("jobMode") or "incremental")
                if snap.get("jobKinds") is not None:
                    _enrich_job["jobKinds"] = list(snap.get("jobKinds") or [])
                if "jobDryRun" in snap:
                    _enrich_job["jobDryRun"] = bool(snap.get("jobDryRun"))
                if snap.get("result") is not None and _enrich_job.get("result") is None:
                    _enrich_job["result"] = _slim_result_for_status(snap.get("result"))
                if snap.get("error") and not _enrich_job.get("error"):
                    _enrich_job["error"] = snap.get("error")
                # 进程已死：running 不能为 True
                _enrich_job["running"] = False
                _enrich_job["halt"] = None
                _enrich_job["cancel"] = False
                # 上次崩溃时若 status=running，标为 paused 便于续跑
                st = str(raw.get("status") or "")
                if st == "running" and rebuilt:
                    _enrich_job["phase"] = "paused"
                    prog = dict(_enrich_job.get("progress") or {})
                    prog["label"] = "进程中断 · 可继续"
                    prog["stage"] = "done"
                    _enrich_job["progress"] = prog
                    # 把 running 行退回 pending
                    for rid in rebuilt:
                        _queue_log_reopen_running(region=rid)
                    # 落盘改为 paused
                elif st == "running" and not rebuilt:
                    # 无检查点：用队列表 pending 重建，避免再开当成「新任务」只刮一小截就假完成
                    recover_rid = _queue_log_region(
                        str(snap.get("currentRegion") or "")
                    )
                    if not recover_rid:
                        for rid0 in list(
                            (snap.get("result") or {}).get("regions") or []
                        ) if isinstance(snap.get("result"), dict) else []:
                            recover_rid = _queue_log_region(str(rid0 or ""))
                            if recover_rid:
                                break
                    if recover_rid:
                        try:
                            _queue_log_reopen_running(region=recover_rid)
                        except Exception:  # noqa: BLE001
                            pass
                        dbc = _queue_log_status_counts(recover_rid, fresh=True)
                        rem_n = int(dbc.get("pending") or 0)
                        if rem_n > 0:
                            rebuilt_one = {
                                "region": recover_rid,
                                "mode": str(
                                    snap.get("jobMode") or "incremental"
                                ),
                                "kinds": list(snap.get("jobKinds") or []),
                                "dryRun": bool(snap.get("jobDryRun")),
                                "ok": int(dbc.get("done") or 0),
                                "failed": int(dbc.get("fail") or 0),
                                "done": int(dbc.get("done") or 0)
                                + int(dbc.get("fail") or 0),
                                "originalTotal": max(
                                    rem_n
                                    + int(dbc.get("done") or 0)
                                    + int(dbc.get("fail") or 0),
                                    rem_n,
                                ),
                                "queue": [],
                                "remainingCount": rem_n,
                                "queueInLog": True,
                            }
                            _enrich_job["checkpoints"] = {
                                recover_rid: rebuilt_one
                            }
                            rebuilt = {recover_rid: rebuilt_one}
                            _enrich_job["phase"] = "paused"
                            prog = dict(_enrich_job.get("progress") or {})
                            prog["label"] = "进程中断 · 可继续"
                            prog["stage"] = "done"
                            _enrich_job["progress"] = prog
                        else:
                            _enrich_job["phase"] = str(
                                snap.get("phase") or "interrupted"
                            )
                    else:
                        _enrich_job["phase"] = str(
                            snap.get("phase") or "interrupted"
                        )
        if need_rewrite or (
            isinstance(raw, dict) and str(raw.get("status") or "") == "running"
        ):
            # 立刻把巨型检查点压成抽样，避免下次启动再读 27MB
            try:
                _persist_enrich_runtime()
            except Exception:  # noqa: BLE001
                pass
        if str(raw.get("status") or "") == "running":
            try:
                from app.core import job_persist as jp

                patched = dict(raw)
                patched["status"] = "paused" if rebuilt else "interrupted"
                if patched.get("snapshot") and isinstance(patched["snapshot"], dict):
                    patched["snapshot"] = dict(patched["snapshot"])
                    patched["snapshot"]["running"] = False
                    if rebuilt:
                        patched["snapshot"]["phase"] = "paused"
                jp.save_job(jp.ENRICH_RUNTIME_KEY, patched)
            except Exception:  # noqa: BLE001
                pass
    except Exception as e:  # noqa: BLE001
        log.warning("hydrate enrich runtime failed: %s", e)


def request_enrich_pause() -> dict[str, Any]:
    """暂停：立刻停投递；进行中/未处理一并退回 pending 检查点，再开续跑。

    不在这里等在飞线程结束——工作线程见 halt=pause 后立即收尾（shutdown wait=False）。
    """
    with _enrich_lock:
        if not _enrich_job.get("running"):
            # 已停时若仅有检查点，视为已暂停
            if _enrich_job.get("checkpoints"):
                return {"ok": True, "paused": True, "running": False}
            return {"ok": True, "paused": False, "running": False}
        _enrich_job["halt"] = "pause"
        _enrich_job["cancel"] = True
        region = str(_enrich_job.get("currentRegion") or "").strip()
        view = [
            dict(r)
            for r in list(_enrich_job.get("queue") or [])
            if isinstance(r, dict)
        ]
        remaining: list[dict[str, Any]] = []
        new_view: list[dict[str, Any]] = []
        ok_n = 0
        fail_n = 0
        for r in view:
            st = str(r.get("status") or "pending")
            if st == "done":
                ok_n += 1
                new_view.append(r)
                continue
            if st == "fail":
                fail_n += 1
                new_view.append(r)
                continue
            # pending / running / 其它 → 未处理
            row = dict(r)
            row["status"] = "pending"
            row.pop("error", None)
            new_view.append(row)
            rem: dict[str, Any] = {
                "itemId": str(r.get("itemId") or ""),
                "code": str(r.get("code") or ""),
                "gaps": list(r.get("gaps") or []),
                "rel_path": str(
                    r.get("rel_path") or r.get("relPath") or ""
                ),
                "relPath": str(
                    r.get("relPath") or r.get("rel_path") or ""
                ),
                "region": region,
            }
            lid = _queue_log_int_id(r)
            if lid:
                rem["logId"] = lid
            remaining.append(rem)
        pause_log_ids = [
            _queue_log_int_id(r)
            for r in remaining
            if _queue_log_int_id(r) > 0
        ]
        done_n = ok_n + fail_n
        total = len(view) if view else done_n + len(remaining)
        try:
            db_pending = int(_queue_log_status_counts(region, fresh=True).get("pending") or 0)
        except Exception:  # noqa: BLE001
            db_pending = 0
        rem_n = max(len(remaining), db_pending)
        _enrich_job["queue"] = new_view
        _enrich_job["queueCounts"] = _queue_counts_of(new_view)
        _enrich_job["queueCounts"]["pending"] = rem_n
        _enrich_job["queueCounts"]["running"] = 0
        ok_n = int(_enrich_job["queueCounts"].get("done") or 0) + int(
            _enrich_job["queueCounts"].get("soft") or 0
        )
        fail_n = int(_enrich_job["queueCounts"].get("fail") or 0)
        _enrich_job["current"] = None
        _enrich_job["phase"] = "paused"
        _enrich_job["progress"] = {
            "stage": "done",
            "label": "已暂停",
            "done": done_n,
            "total": max(total, done_n + rem_n),
            "ok": ok_n,
            "failed": fail_n,
            "percent": _enrich_percent(done_n, max(total, done_n + rem_n))
            if (done_n + rem_n)
            else 0,
        }
        if region:
            cps = dict(_enrich_job.get("checkpoints") or {})
            prev = cps.get(region) if isinstance(cps.get(region), dict) else {}
            cps[region] = {
                "region": region,
                "mode": str(
                    prev.get("mode")
                    or _enrich_job.get("jobMode")
                    or "incremental"
                ),
                "kinds": list(
                    prev.get("kinds") or _enrich_job.get("jobKinds") or []
                ),
                "dryRun": bool(
                    prev.get("dryRun")
                    if "dryRun" in prev
                    else _enrich_job.get("jobDryRun")
                ),
                "queue": remaining,
                "ok": ok_n,
                "failed": fail_n,
                "done": done_n,
                "originalTotal": int(prev.get("originalTotal") or max(total, done_n + rem_n)),
                "remainingCount": rem_n,
                "queueInLog": rem_n > len(remaining),
            }
            _enrich_job["checkpoints"] = cps
        # UI / 清空立刻视为已停；worker 见 halt 后自行收尾，勿继续占 busy
        _enrich_job["running"] = False
    if pause_log_ids:
        _queue_log_mark_pending(pause_log_ids)
    # 整区强制 running→pending，避免库残留把「处理中」角标顶回来
    if region:
        _queue_log_reopen_running(region=region)
    else:
        _queue_log_reopen_running()
    _persist_enrich_runtime()
    _push_log(
        f"已暂停 · 进行中已退回未处理 · 剩余 {len(remaining)}",
        region=region or "",
    )
    notify_enrich_watchers(force=True)
    return {"ok": True, "paused": True, "running": False}


def request_enrich_stop(*, region: str = "") -> dict[str, Any]:
    """停止：清除运行队列与检查点；历史日志/队列记录保留（仅「清空日志」可删）。"""
    rid = str(region or "").strip()
    with _enrich_lock:
        running = bool(_enrich_job.get("running"))
        if running:
            _enrich_job["halt"] = "stop"
            _enrich_job["cancel"] = True
            _enrich_job["phase"] = "stopping"
            cur = dict(_enrich_job.get("progress") or {})
            cur["label"] = "正在停止…"
            _enrich_job["progress"] = cur
        else:
            if rid:
                cps = dict(_enrich_job.get("checkpoints") or {})
                cps.pop(rid, None)
                _enrich_job["checkpoints"] = cps
            else:
                _enrich_job["checkpoints"] = {}
            _enrich_job["queue"] = []
            _enrich_job["current"] = None
            cur = dict(_enrich_job.get("progress") or {})
            cur["label"] = "已停止 · 队列已清除 · 历史日志保留"
            cur["stage"] = "cleared"
            cur["done"] = 0
            cur["total"] = 0
            cur["percent"] = 0
            _enrich_job["progress"] = cur
            _enrich_job["phase"] = "stopped"
            _enrich_job["result"] = None
    # 队列日志表不在 stop 时清除；仅「清空日志」可删
    if rid:
        _queue_log_reopen_running(region=rid)
    else:
        _queue_log_reopen_running()
    _persist_enrich_runtime()
    if not running:
        try:
            enrich_mon.clear_job()
        except Exception:  # noqa: BLE001
            pass
    log.info(
        "enrich stop%s running=%s",
        f" region={rid}" if rid else "",
        running,
    )
    notify_enrich_watchers(force=True)
    return {"ok": True, "stopped": True, "cleared": True, "running": running}


def _clear_runtime_queue(*, wipe_checkpoint_region: str = "") -> None:
    """停止后清掉运行时队列/当前项（暂停绝不能调用）。"""
    with _enrich_lock:
        _enrich_job["queue"] = []
        _enrich_job["queueCounts"] = {
            "pending": 0,
            "running": 0,
            "done": 0,
            "fail": 0,
        }
        _enrich_job["current"] = None
        if wipe_checkpoint_region:
            cps = dict(_enrich_job.get("checkpoints") or {})
            cps.pop(str(wipe_checkpoint_region).strip(), None)
            _enrich_job["checkpoints"] = cps
    if wipe_checkpoint_region:
        _persist_enrich_runtime()


def request_enrich_cancel() -> dict[str, Any]:
    """取消：当前语义等同暂停（保留 checkpoint，下次可续跑）。

    与 stop 区分：stop 清队列/进度；cancel/pause 只发停跑信号。
    """
    return request_enrich_pause()


def _set_progress(**kwargs: Any) -> None:
    with _enrich_lock:
        cur = dict(_enrich_job.get("progress") or {})
        cur.update(kwargs)
        counts = _enrich_job.get("queueCounts")
        # 本轮队列非空时：percent/done/total 必须跟文案同一套计数，
        # 禁止 worker 用 prior_done/original_total 把条拉到 33%/假 100%。
        if isinstance(counts, dict):
            qtot = sum(
                int(counts.get(k) or 0)
                for k in ("pending", "running", "done", "fail")
            )
            if qtot > 0:
                keep_label = cur.get("label")
                keep_stage = cur.get("stage")
                cur = _progress_from_queue_counts(counts, base=cur)
                if "label" in kwargs:
                    cur["label"] = kwargs["label"]
                elif keep_label is not None:
                    cur["label"] = keep_label
                if keep_stage is not None:
                    cur["stage"] = keep_stage
        _enrich_job["progress"] = cur
        if kwargs.get("label"):
            _enrich_job["phase"] = str(kwargs["label"])
    notify_enrich_watchers()


def _enrich_percent(done: int, total: int) -> int:
    """按已完成条数映射 0–100；不再人为从 10% 起跳。"""
    t = int(total or 0)
    if t <= 0:
        return 0
    d = max(0, min(int(done or 0), t))
    if d >= t:
        return 100
    return max(0, min(99, int(round(100.0 * d / t))))


def _next_budget(budget: int | None, part: dict[str, Any]) -> int | None:
    """多区调度：跨区 limit 预算扣减。

    必须按**实际处理条数**（`processed`）扣，不能按 `queued`：增量模式下
    `queued` 取库内待处理预估（有码区十万级），拿它扣减会让首个分区一口吃光
    整个 limit，后续分区全被「预览额度已用完」跳过。
    某区实际无待处理（processed=0）时预算原样顺延给下一区。
    """
    if budget is None:
        return None
    return max(0, budget - int(part.get("processed") or 0))


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


def _apply_mdcx_maps(
    detail: dict[str, Any] | None,
    *,
    code: str = "",
) -> dict[str, Any] | None:
    """对齐 MDCX scraper 映射段（字段合并之后、封面之前）：

    1. translate_title_outline · c_number 色花堂标题（开关开且命中 → 覆盖）
    2. translate_actor · 演员映射表
    3. translate_info · 标签映射表
    4. （本仓库）简介连续换行精简
    """
    if not detail:
        return detail
    code_u = str(code or detail.get("code") or "").strip()
    try:
        from app.scrap_library.enrich_strategy import local_map_bool, local_map_mode

        title_mode = local_map_mode("title")
        title_on = title_mode != "off"
        actors_on = local_map_mode("actors") != "off"
        tags_on = local_map_mode("tags") != "off"
        compact_nl = local_map_bool("compactOutlineNewlines")
    except Exception:  # noqa: BLE001
        title_mode = "prefer"
        title_on = actors_on = tags_on = compact_nl = True

    fs = (
        dict(detail["fieldSources"])
        if isinstance(detail.get("fieldSources"), dict)
        else {}
    )
    applied: list[str] = []

    # 1) 演员映射（MDCX translate_actor → map_actor_names）
    if actors_on:
        try:
            from app.scrape.metadata_optimize import polish_actress_names

            acts = [str(a).strip() for a in (detail.get("actors") or []) if str(a).strip()]
            if acts:
                polished = polish_actress_names(acts, enable_mapping=True)
                if polished:
                    detail["actors"] = _unique_identity_names(polished)[:12]
                    applied.append("actors")
            # 名单仍空：番号→女优表兜底（本仓库扩展）
            if not detail.get("actors") and code_u:
                from app.core.maps_paths import lookup_code_actors

                local_a = polish_actress_names(
                    list(lookup_code_actors(code_u) or []),
                    enable_mapping=True,
                )
                local_a = _clean_actors(local_a)
                if local_a:
                    detail["actors"] = _unique_identity_names(local_a)[:12]
                    fs["actors"] = "local_code_actors"
                    applied.append("actors_code")
        except Exception:  # noqa: BLE001
            pass

    # 2) 标签映射（MDCX translate_info）
    if tags_on:
        try:
            from app.scrape.metadata_optimize import code_prefix, polish_tag_names

            tags = [str(t).strip() for t in (detail.get("tags") or []) if str(t).strip()]
            if tags:
                detail["tags"] = polish_tag_names(
                    tags,
                    exclude=list(detail.get("actors") or []),
                    prefix=code_prefix(code_u),
                    enable_mapping=True,
                )
                applied.append("tags")
        except Exception:  # noqa: BLE001
            pass

    # 3) 简介换行精简（本仓库扩展）
    if compact_nl and detail.get("overview"):
        try:
            from app.scrape.metadata_optimize import compact_outline

            detail["overview"] = compact_outline(str(detail["overview"]))
            applied.append("outline_nl")
        except Exception:  # noqa: BLE001
            pass

    # 4) 剧情里的女优异写对齐（标题在映射优选后再对齐，见下）
    try:
        acts = list(detail.get("actors") or [])
        if acts and detail.get("overview"):
            detail["overview"] = _align_llm_text_actors(
                str(detail["overview"]), acts
            )
    except Exception:  # noqa: BLE001
        pass

    # 5) 色花堂中文标题：源站先定稿，再与映射比分优选（非强制、非纯兜底）
    if title_on and code_u:
        try:
            from app.core.maps_paths import lookup_code_title

            mapped = str(lookup_code_title(code_u) or "").strip()
            if mapped:
                cur = str(detail.get("title") or "").strip()
                use_map = False
                if title_mode == "force":
                    use_map = True
                elif title_mode == "fallback":
                    use_map = (not cur) or _title_is_thin(cur, code_u)
                else:
                    # prefer（默认）：哪个分高用哪个；平手留源站
                    # 演员映射已在上方跑完，用定稿女优压「标题尾错名」
                    use_map = _title_should_prefer_map(
                        cur,
                        mapped,
                        code=code_u,
                        allowed_actors=list(detail.get("actors") or []),
                    )
                if use_map:
                    if (
                        cur
                        and _has_kana(cur)
                        and not str(detail.get("titleJa") or "").strip()
                    ):
                        detail["titleJa"] = cur
                    detail["title"] = _strip_trailing_alt_code(
                        _normalize_merged_title(mapped), code_u
                    )
                    fs["title"] = "mdcx_c_number"
                    detail["titleMapApplied"] = True
                    if title_mode == "force":
                        detail["titleMapForced"] = True
                    applied.append("title")
        except Exception:  # noqa: BLE001
            pass

    # 6) 标题尾女优异写 → 定稿名（新有菜→桥本有菜），与女优栏一致
    try:
        acts = list(detail.get("actors") or [])
        if acts and detail.get("title"):
            aligned = _align_llm_text_actors(str(detail["title"]), acts)
            if aligned != str(detail.get("title") or ""):
                detail["title"] = aligned
                applied.append("title_actor")
    except Exception:  # noqa: BLE001
        pass

    if applied:
        detail["mapsApplied"] = applied
    detail["fieldSources"] = {k: v for k, v in fs.items() if v}
    return detail


_TRAILING_ALT_CODE_RE = re.compile(
    r"(?:[\s　]+)([A-Za-z]{2,6}[-−–]?\d{2,5}[A-Za-z]?)\s*$"
)


def _polish_studio_name(name: str) -> str:
    """片商展示名：别名/假名 → makers.json（优先中文，其次英文品牌）。"""
    raw = str(name or "").strip()
    if not raw:
        return ""
    try:
        from app.scrap_library.studio_display_names import resolve_studio_display

        mapped = str(resolve_studio_display(raw) or "").strip()
        return mapped or raw
    except Exception:  # noqa: BLE001
        return raw


def _maybe_llm_fill_zh(
    detail: dict[str, Any] | None,
    *,
    prefer_llm: bool = True,
    timeout_sec: float = 90.0,
) -> dict[str, Any] | None:
    """机翻过烂或仅有日文时：大模型（失败再机翻级联）生成中文标题/剧情。"""
    if not detail:
        return detail
    try:
        from app.scrap_library.enrich_strategy import get_strategy

        strat = get_strategy()
    except Exception:  # noqa: BLE001
        strat = {}
    if not bool(strat.get("llmTranslateOnJunk", True)):
        return detail

    try:
        from app.translate.routes import translate_to_zh_sync
    except Exception as e:  # noqa: BLE001
        log.debug("llm fill import failed: %s", e)
        return detail

    fs = detail.get("fieldSources") if isinstance(detail.get("fieldSources"), dict) else {}
    fs = dict(fs)
    filled: list[str] = []
    t_lim = max(8.0, min(90.0, float(timeout_sec or 90.0)))

    title = str(detail.get("title") or "").strip()
    # 已采信映射标题时不再烧 LLM；优选模式下未采信则仍可译源站日文再比
    skip_title_llm = bool(
        detail.get("titleMapForced") or detail.get("titleMapApplied")
    )
    if (
        title
        and _text_needs_zh_llm(title, kind="title")
        and not skip_title_llm
    ):
        # 只译已校验日文：优先 titleJa；若定稿标题本身是日文也可
        src = str(detail.get("titleJa") or "").strip()
        if not src and _has_kana(title):
            src = title
        if src and _has_kana(src):
            try:
                got = translate_to_zh_sync(
                    src,
                    kind="title",
                    prefer_llm=prefer_llm,
                    timeout_sec=t_lim,
                )
                zh = _normalize_merged_title(str(got.get("text") or ""))
                eng = str(got.get("engine") or "llm")
                if _zh_fill_acceptable(zh, kind="title"):
                    detail["title"] = _strip_trailing_alt_code(
                        _align_llm_text_actors(
                            zh, list(detail.get("actors") or [])
                        ),
                        str(detail.get("code") or ""),
                    )
                    fs["title"] = f"llm:{eng}" if eng != "none" else fs.get("title") or "llm"
                    filled.append(f"title/{eng}")
            except Exception as e:  # noqa: BLE001
                log.info("enrich llm title fill skip: %s", e)

    overview = str(detail.get("overview") or "").strip()
    if overview and _text_needs_zh_llm(overview):
        src = str(detail.get("overviewJa") or "").strip()
        if not src and _has_kana(overview):
            src = overview
        if src and _has_kana(src) and len(src) >= 20:
            try:
                got = translate_to_zh_sync(
                    src,
                    kind="plot",
                    prefer_llm=prefer_llm,
                    timeout_sec=t_lim,
                )
                zh = _normalize_merged_overview(str(got.get("text") or ""))
                eng = str(got.get("engine") or "llm")
                if _zh_fill_acceptable(zh, kind="plot"):
                    detail["overview"] = _align_llm_text_actors(
                        zh, list(detail.get("actors") or [])
                    )
                    try:
                        from app.scrap_library.enrich_strategy import local_map_bool
                        from app.scrape.metadata_optimize import compact_outline

                        if local_map_bool("compactOutlineNewlines"):
                            detail["overview"] = compact_outline(
                                str(detail["overview"])
                            )
                    except Exception:  # noqa: BLE001
                        pass
                    fs["overview"] = f"llm:{eng}" if eng != "none" else fs.get("overview") or "llm"
                    filled.append(f"overview/{eng}")
            except Exception as e:  # noqa: BLE001
                log.info("enrich llm overview fill skip: %s", e)

    if filled:
        detail["fieldSources"] = {k: v for k, v in fs.items() if v}
        detail["llmTranslated"] = filled
        log.info("enrich llm fill %s → %s", detail.get("code") or "", ",".join(filled))
    return detail


_CN_TEXT_SOURCE_IDS = frozenset(
    {
        "airav",
        "airav_io",
        "iqqtv",
        "javday",
        "miss_av",
        "sevenmmtv",
        "avsex",
        "lulubar",
    }
)


def _cn_text_ids_in_batch(batch: list[dict[str, Any]]) -> set[str]:
    import app.scrape.source_catalog as catalog

    out: set[str] = set()
    for src in batch:
        sid = catalog.canonicalize_id(str(src.get("id") or ""))
        if sid in _CN_TEXT_SOURCE_IDS:
            out.add(sid)
    return out


_GAP_FIELD_PRIORITY_KEYS: dict[str, tuple[str, ...]] = {
    "thin_title": ("title",),
    # 缺中文标题与「标题太薄」是同一诉求（都要 title 字段）→ 同样提权 title 源。
    # 不加这条时，只缺 `no_zh_title` 的号不会优先发车中文源，只能靠默认顺序兜底
    # （第二十一轮对齐；与 `_may_early_stop` 的 need_zh 集合同源）
    "no_zh_title": ("title",),
    "no_plot": ("overview",),
    "no_actress": ("actors",),
    "no_studio": ("studio", "maker"),
    "no_local": ("poster",),
    "no_media": ("poster",),
}


_META_FILL_SOURCE_IDS = frozenset(
    {
        "dmm",
        "mgstage",
        "r18dev",
        "jav321",
        "libredmm",
        "avbase",
        "avwikidb",
        "prestige",
    }
)


_META_WAIT_BUDGET_SEC = 1.2


_CN_WAIT_BUDGET_SEC = 2.8


def _title_is_thin(title: str, code: str) -> bool:
    t = str(title or "").strip()
    c = str(code or "").strip()
    if not t:
        return True
    if c and t.casefold() == c.casefold():
        return True
    # 素人/无垢等官名常为 2～3 假名（案例 MUKD-244「えれな」）；勿当空题拒写
    if len(t) < 2:
        return True
    # 过短中文残片机译（DV-673「高中部」、FLAV-072「双倍的」）
    if _has_han(t) and not _has_kana(t) and len(t) <= 6:
        return True
    # 纯片假名作品名（女体のしんぴ「オナサポ」）保留，不当空题
    if re.fullmatch(r"[ァ-ヴー]{3,8}", t):
        return False
    # 纯人名感短题（ONS-029「あいら」、STZY「百仁花」）：有更长候选时应让位
    if len(t) <= 4 and not re.search(r"[\s　、，。！!？?【】\[\]「」『』（）()]", t):
        return True
    return False


def _soft_retry_fill_actors(
    *,
    code: str,
    region: str,
    folder: Path,
    nfo: Path,
    detail: dict[str, Any],
) -> list[str]:
    """软成功缺女优时轻量二次拉取（只补 actors，不重跑封面/全字段）。"""
    code_u = str(code or "").strip().upper()
    if not code_u:
        return []
    if _clean_actors(detail.get("actors")):
        return _clean_actors(detail.get("actors"))
    try:
        more = _fetch_detail(
            code_u,
            region=region,
            wait_all=False,
            gaps=["no_actress"],
            adaptive_first=True,
            fast_zh=True,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("soft actress retry fetch failed %s: %s", code_u, e)
        return []
    actors = _clean_actors((more or {}).get("actors"))
    if not actors:
        return []
    detail["actors"] = actors
    fs = detail.get("fieldSources") if isinstance(detail.get("fieldSources"), dict) else {}
    fs = dict(fs or {})
    src = str((more or {}).get("source") or (more or {}).get("provider") or "").strip()
    if src:
        fs["actors"] = src
        detail["fieldSources"] = fs
    try:
        merge_nfo_with_detail(
            nfo,
            {"actors": actors, "code": code_u, "fieldSources": fs},
            overwrite=False,
            force_fields={"actors"},
        )
    except Exception as e:  # noqa: BLE001
        log.debug("soft actress retry merge failed %s: %s", code_u, e)
        return actors
    _push_log(
        f"{code_u} · 软成功补女优 · {len(actors)} · {src or '-'}",
        region=region,
    )
    return actors


def _get_cover_job_pool():
    """封面独立任务池（同进程）；线程数按上限常开，实际并发由闸门限制。"""
    global _cover_job_pool
    from concurrent.futures import ThreadPoolExecutor

    with _cover_job_pool_lock:
        if _cover_job_pool is None:
            from app.core.container_budget import cap_parallel

            cover_n = cap_parallel(
                int(_COVER_JOB_WORKERS),
                tight=2,
                small=4,
                hard=int(_COVER_JOB_WORKERS),
            )
            _cover_job_pool = ThreadPoolExecutor(
                max_workers=max(2, cover_n),
                thread_name_prefix="cover-job",
            )
        return _cover_job_pool


@contextmanager
def _cover_job_slot() -> Any:
    """限制同时进行的整番号封面任务数（可随 itemWorkers 热变）。"""
    global _cover_gate_inflight, _cover_gate_target
    target = _cover_job_workers_target()
    with _cover_gate_lock:
        _cover_gate_target = target
        while _cover_gate_inflight >= _cover_gate_target:
            _cover_gate_lock.wait(timeout=0.4)
            # 等待期间策略可能变：刷新目标
            _cover_gate_target = _cover_job_workers_target()
        _cover_gate_inflight += 1
    try:
        yield
    finally:
        with _cover_gate_lock:
            _cover_gate_inflight = max(0, int(_cover_gate_inflight) - 1)
            _cover_gate_lock.notify_all()


_poster_ok_cache: dict[tuple[str, int, int], bool] = {}


def reingest_folder(folder: Path) -> dict[str, Any] | None:
    """单目录 NFO 重扫并写回向量库（刮削后一步完成）。"""
    nfo = _find_nfo(folder)
    if not nfo:
        return {"ok": False, "embedded": False, "error": "missing_nfo"}
    cfg = resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        meta = parse_nfo(nfo)
        return {
            "ok": False,
            "embedded": False,
            "error": "embed_disabled",
            "title": meta.get("title"),
        }

    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    media_root = media_dir()
    scrap_rel = ""
    try:
        scrap_rel = root.relative_to(media_root.resolve()).as_posix()
    except ValueError:
        scrap_rel = (
            str(settings.get("root") or "scrap-library").replace("\\", "/").strip("/")
        )

    model = str(cfg["model"])
    dim = int(cfg["dim"])
    item = embed_svc._scan_one_nfo(  # noqa: SLF001
        nfo,
        root=root,
        model=model,
        dim=dim,
        media_root=media_root,
        scrap_rel=scrap_rel,
    )
    if not item:
        return {"ok": False, "embedded": False, "error": "scan_nfo_failed"}
    vecs = encode_texts_sync([item["source_text"]], query=False)
    if not vecs or len(vecs[0]) != dim:
        raise RuntimeError("向量编码失败")
    vec_lit = embed_svc._vec_literal(vecs[0])  # noqa: SLF001
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {embed_svc.TABLE}
              (item_id, region, prefix, code, rel_path, title,
               poster_path, thumb_path, fanart_path, cover_url,
               model, dim, content_sha, source_text, embedding, updated_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
            ON CONFLICT (item_id) DO UPDATE SET
              region = EXCLUDED.region,
              prefix = EXCLUDED.prefix,
              code = EXCLUDED.code,
              rel_path = EXCLUDED.rel_path,
              title = EXCLUDED.title,
              poster_path = EXCLUDED.poster_path,
              thumb_path = EXCLUDED.thumb_path,
              fanart_path = EXCLUDED.fanart_path,
              cover_url = EXCLUDED.cover_url,
              model = EXCLUDED.model,
              dim = EXCLUDED.dim,
              content_sha = EXCLUDED.content_sha,
              source_text = EXCLUDED.source_text,
              embedding = EXCLUDED.embedding,
              updated_at = now()
            """,
            (
                item["item_id"],
                item["region"],
                item["prefix"],
                item["code"],
                item["rel_path"],
                item["title"],
                item["poster_path"],
                item["thumb_path"],
                item["fanart_path"],
                item["cover_url"],
                item["model"],
                item["dim"],
                item["content_sha"],
                item["source_text"],
                vec_lit,
            ),
        )
        conn.commit()
    return {
        "ok": True,
        "embedded": True,
        "itemId": item["item_id"],
        "code": item["code"],
        "title": item.get("title"),
    }


def patch_folder_meta_no_embed(folder: Path) -> dict[str, Any]:
    """本地刮削后：回写标题/source_text/封面路径，并覆盖旧 embedding。

    分区批量 sync_vector=False 时必须调用，否则缺口仍按旧向量行计算，
    再启动会把刚刮过的番号又排进队。二次刮削直接覆盖向量库已有行（embedding 置零待再同步）。
    """
    nfo = _find_nfo(folder)
    if not nfo:
        return {"ok": False, "patched": False, "error": "missing_nfo"}
    cfg = resolve_embed_config(include_secret=False)
    model = str(cfg.get("model") or "text-embedding-3-small")
    try:
        dim = int(cfg.get("dim") or 1536)
    except (TypeError, ValueError):
        dim = 1536
    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root"))
    media_root = media_dir()
    scrap_rel = ""
    try:
        scrap_rel = root.relative_to(media_root.resolve()).as_posix()
    except ValueError:
        scrap_rel = (
            str(settings.get("root") or "scrap-library").replace("\\", "/").strip("/")
        )
    item = embed_svc._scan_one_nfo(  # noqa: SLF001
        nfo,
        root=root,
        model=model,
        dim=dim,
        media_root=media_root,
        scrap_rel=scrap_rel,
    )
    if not item:
        return {"ok": False, "patched": False, "error": "scan_nfo_failed"}
    iid = str(item.get("item_id") or "").strip()
    if not iid:
        return {"ok": False, "patched": False, "error": "missing_item_id"}
    # 无行时占位零向量；二次刮削：已有行也覆盖 embedding（清旧向量，待再同步）
    zero_lit = embed_svc._vec_literal([0.0] * dim)  # noqa: SLF001
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {embed_svc.TABLE}
              (item_id, region, prefix, code, rel_path, title,
               poster_path, thumb_path, fanart_path, cover_url,
               model, dim, content_sha, source_text, embedding, updated_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, now())
            ON CONFLICT (item_id) DO UPDATE SET
              region = EXCLUDED.region,
              prefix = EXCLUDED.prefix,
              code = EXCLUDED.code,
              rel_path = EXCLUDED.rel_path,
              title = EXCLUDED.title,
              poster_path = EXCLUDED.poster_path,
              thumb_path = EXCLUDED.thumb_path,
              fanart_path = EXCLUDED.fanart_path,
              cover_url = EXCLUDED.cover_url,
              model = EXCLUDED.model,
              dim = EXCLUDED.dim,
              content_sha = EXCLUDED.content_sha,
              source_text = EXCLUDED.source_text,
              embedding = EXCLUDED.embedding,
              updated_at = now()
            """,
            (
                iid,
                item["region"],
                item["prefix"],
                item["code"],
                item["rel_path"],
                item["title"],
                item["poster_path"],
                item["thumb_path"],
                item["fanart_path"],
                item["cover_url"],
                item["model"],
                item["dim"],
                item["content_sha"],
                item["source_text"],
                zero_lit,
            ),
        )
        conn.commit()
    return {
        "ok": True,
        "patched": True,
        "embedded": False,
        "overwritten": True,
        "itemId": iid,
        "code": item.get("code"),
        "title": item.get("title"),
        "gaps": embed_svc._row_gaps(item),  # noqa: SLF001
    }


def _persist_enrich_result_to_queue_log(
    out: dict[str, Any],
    *,
    row: dict[str, Any],
    region: str = "",
    dry_run: bool = False,
) -> int:
    """刮削结果直接写入 enrich_queue_log（含 fields / sourceTimings）。"""
    if dry_run:
        return 0
    timings = list(out.get("sourceTimings") or [])
    fields = list(out.get("fields") or [])
    if not timings and not fields:
        return 0
    code_u = str(
        out.get("code") or (row or {}).get("code") or ""
    ).strip().upper()
    if not code_u:
        return 0
    rid = (
        _queue_log_region(region)
        or _queue_log_region(str(out.get("region") or ""))
        or _queue_log_region(str((row or {}).get("region") or ""))
    )
    st = "done" if out.get("ok") else "fail"
    gaps_after = list(out.get("gapsAfter") or [])
    # 成功以 gapsAfter 为准（空=缺口已清）；失败保留原 gaps 便于 UI 展示
    if out.get("ok"):
        gaps_persist = gaps_after
    else:
        gaps_persist = gaps_after or list(
            (row or {}).get("gaps") or out.get("gaps") or []
        )
    persist: dict[str, Any] = {
        "logId": _queue_log_int_id(row or {}),
        "itemId": str((row or {}).get("itemId") or out.get("itemId") or ""),
        "code": code_u,
        "status": st,
        "gaps": gaps_persist,
        "error": str(out.get("error") or "")[:500],
        "source": str(out.get("source") or ""),
        "fetchMs": out.get("fetchMs"),
        "detailTitle": str(out.get("detailTitle") or "")[:300],
        "actors": out.get("actors"),
        "nfoChanged": out.get("nfoChanged"),
        "posterDownloaded": out.get("posterDownloaded"),
        "vectorSynced": out.get("vectorSynced"),
        "vectorSkipped": out.get("vectorSkipped"),
        "vectorError": str(out.get("vectorError") or "")[:120],
        "fields": fields,
        "sourceTimings": timings,
        "coverMs": out.get("coverMs"),
        "actressMs": out.get("actressMs"),
        "vectorMs": out.get("vectorMs"),
        "totalMs": out.get("totalMs"),
        "partialOk": bool(out.get("partialOk")),
        "gapsAfter": gaps_after,
    }
    rel_p = str(
        (row or {}).get("rel_path")
        or (row or {}).get("relPath")
        or out.get("relPath")
        or ""
    ).strip()
    if rel_p:
        persist["rel_path"] = rel_p
        persist["relPath"] = rel_p
    try:
        lid = _queue_log_update_row(persist, region=rid or region)
        if st == "done":
            # prune 异步：绝不能挡 _done→item_end，否则监控假死在封面阶段
            _rid = rid or region
            _iid = str(persist.get("itemId") or "")

            def _prune_open_bg() -> None:
                try:
                    _queue_log_prune_open_if_done(
                        _rid, code=code_u, item_id=_iid
                    )
                except Exception:  # noqa: BLE001
                    pass

            threading.Thread(
                target=_prune_open_bg,
                name=f"prune-open-{code_u or 'x'}",
                daemon=True,
            ).start()
        # 番号目录落盘：清空队列表后仍可回读源耗时
        try:
            fol = _resolve_enrich_folder(
                region=rid or region,
                code=code_u,
                item_id=str(
                    persist.get("itemId")
                    or persist.get("relPath")
                    or persist.get("rel_path")
                    or ""
                ),
            )
            if fol is not None:
                write_enrich_sidecar(fol, persist)
        except Exception as se:  # noqa: BLE001
            log.debug("enrich sidecar write skip code=%s: %s", code_u, se)
        src_n = sum(
            1
            for f in fields
            if isinstance(f, dict) and str(f.get("source") or "").strip()
        )
        log.info(
            "enrich queue persist code=%s region=%s lid=%s status=%s "
            "timings=%s fields=%s srcFields=%s",
            code_u,
            rid or region or "-",
            lid,
            st,
            len(timings),
            len(fields),
            src_n,
        )
        return int(lid or 0)
    except Exception as e:  # noqa: BLE001
        log.warning("enrich queue persist failed code=%s: %s", code_u, e)
        return 0


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
        _persist_enrich_result_to_queue_log(
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

    # 队列 gaps 常是向量空壳（仅 no_local）；以本地 NFO 真实缺口为准，避免漏拉剧情
    if not force and folder.is_dir() and _find_nfo(folder):
        _lc, local_gaps = _local_folder_gaps(folder)
        if _lc and not code:
            code = _lc
            out["code"] = code
        if local_gaps:
            gaps = list(dict.fromkeys([*local_gaps, *[g for g in gaps if g]]))
            out["gaps"] = gaps
            row = {**row, "gaps": gaps}

    # E2E 等可传入已合并详情，跳过再拉源（仍写 NFO/封面/向量）
    try:
        enrich_mon.set_phase(code=code, item_id=str(row.get("itemId") or ""), phase="fetch")
        notify_enrich_watchers()
    except Exception:  # noqa: BLE001
        pass
    if isinstance(prefetched_detail, dict) and prefetched_detail:
        detail = dict(prefetched_detail)
        out["prefetched"] = True
    else:
        # 运行中改策略：本条起热切数据源/超时（进行中的其它番号不打断）
        _note_strategy_hot_if_needed(region)
        # 增量：缺口齐了就早停；覆盖：拉满各源再合并写回
        # wait_all=True（详情单刷）时强制自适应优先，不过盾池拖尾
        detail = _fetch_detail(
            code,
            region=region,
            wait_all=force,
            gaps=None if force else gaps,
            # 增量：按需早停（近 MDCX 字段链）；覆盖/单刷再拉满
            adaptive_first=not force,
            # 分区批量只写本地：机翻短超时，避免 LLM 占满番号槽
            fast_zh=not sync_vector,
        )
    if not detail:
        out["error"] = "detail_not_found"
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
    out["fields"] = _detail_field_rows(detail)

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

    nfo = _find_nfo(folder) or (folder / f"{folder.name}.nfo")
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
        notify_enrich_watchers()
    except Exception:  # noqa: BLE001
        pass
    changed = merge_nfo_with_detail(
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
                notify_enrich_watchers()
            except Exception:  # noqa: BLE001
                pass
            t_cover0 = time.perf_counter()
            cover_res = _download_covers(
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
            _push_log(
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

    local_cover_ok = _local_poster_ok(folder)
    cover_required = bool(
        need_cover
        or "no_local" in gaps
        or "no_media" in gaps
    )
    if cover_required and not local_cover_ok:
        _purge_blank_covers(folder)
        local_cover_ok = _local_poster_ok(folder)

    # 字段表：写回后按本地 NFO 刷新（早停未采剧情时不再误报缺剧情）
    fields = _fields_after_local_write(
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
            out["error"] = _cover_fail_message(cover_fail)
            # 封面失败也要记缺口（原先这里直接 return，缺口字段缺失 →
            # 下游无法判断「是否只剩封面缺口」，重试上限就没法生效）
            out["gapsAfter"] = _safe_local_gaps(folder)
            _push_log(
                f"{code or folder.name} · cover_fail · {cover_fail or 'unknown'}",
                region=region,
            )
            return _done(out)
        # 回写缺口判定字段（不重嵌），避免再启动又进增量队列
        remain: list[str] = []
        try:
            patched = patch_folder_meta_no_embed(folder)
            out["metaPatched"] = bool(patched.get("patched"))
        except Exception as e:  # noqa: BLE001
            out["metaPatched"] = False
            out["metaPatchError"] = str(e)[:160]
            _push_log(
                f"{code or folder.name} · 元数据回写失败 · {e}",
                region=region,
            )
        # 成功门槛以本地 NFO 为准（向量 _row_gaps 可能与磁盘不一致）
        try:
            _, remain = _local_folder_gaps(folder)
        except Exception:  # noqa: BLE001
            remain = []
        if remain:
            out["gapsAfter"] = remain
            _push_log(
                f"{code or folder.name} · 元数据已回写 · 仍缺 "
                f"{','.join(remain)}",
                region=region,
            )
        else:
            _push_log(
                f"{code or folder.name} · 元数据已回写 · 缺口已清",
                region=region,
            )

        out["fields"] = _fields_after_local_write(
            folder,
            detail,
            local_cover_ok=local_cover_ok,
            poster_url=poster_url,
        )
        _apply_local_gap_success(
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
            got_actors = _soft_retry_fill_actors(
                code=str(code or ""),
                region=region,
                folder=folder,
                nfo=nfo,
                detail=detail,
            )
            if got_actors:
                try:
                    patched = patch_folder_meta_no_embed(folder)
                    out["metaPatched"] = bool(patched.get("patched"))
                except Exception:  # noqa: BLE001
                    pass
                try:
                    _, remain = _local_folder_gaps(folder)
                except Exception:  # noqa: BLE001
                    remain = [g for g in (remain or []) if g != "no_actress"]
                out["gapsAfter"] = list(remain or [])
                out["softActressRetry"] = True
                out["fields"] = _fields_after_local_write(
                    folder,
                    detail,
                    local_cover_ok=local_cover_ok,
                    poster_url=poster_url,
                )
                _apply_local_gap_success(
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
            _push_log(
                f"{code or folder.name} · 刮削写回完成 · 跳过向量（本地提速）",
                region=region,
            )
        else:
            _push_log(
                f"{code or folder.name} · 刮削写回完成（软成功）· 跳过向量",
                region=region,
            )
        return _done(out)

    # 刮削写回后立刻同步向量库（一步完成）；女优档案并行，省串行等待
    _set_progress(
        stage="enrich",
        label=f"向量 {code or folder.name}",
    )
    _push_log(f"{code or folder.name} · 刮削写回完成 · 同步向量…", region=region)

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
            rein = reingest_folder(folder) or {
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
            notify_enrich_watchers()
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
        _push_log(f"{code or folder.name} · 向量同步失败 · {vec_exc}", region=region)
    else:
        assert rein is not None
        out["reingest"] = rein
        if cover_required and not local_cover_ok:
            out["ok"] = False
            out["vectorSynced"] = bool(rein.get("embedded"))
            cover_fail = str(out.get("coverFail") or "").strip()
            out["error"] = _cover_fail_message(cover_fail)
            # 同批量路径：封面失败也补上缺口记账（重试上限依赖它）
            out["gapsAfter"] = _safe_local_gaps(folder)
            _push_log(
                f"{code or folder.name} · cover_fail · {cover_fail or 'unknown'}",
                region=region,
            )
        elif rein.get("embedded"):
            out["ok"] = True
            out["vectorSynced"] = True
            _push_log(
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
                _push_log(
                    f"{code or folder.name} · 向量跳过（嵌入未启用）",
                    region=region,
                )
            else:
                out["ok"] = False
                out["error"] = f"向量同步失败:{err}"
                _push_log(
                    f"{code or folder.name} · 向量同步失败 · {err}",
                    region=region,
                )

    if do_actress:
        out["actressMs"] = actress_ms
        if act_exc is not None:
            out["actressDb"] = {"ok": False, "error": str(act_exc)}
            _push_log(
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
                _push_log(
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
                _push_log(
                    f"{code or folder.name} · 女优档案部分失败 "
                    f"{issues} · {actress_ms}ms",
                    region=region,
                )

    if cover_required and not local_cover_ok:
        out["fields"] = _fields_after_local_write(
            folder,
            detail,
            local_cover_ok=local_cover_ok,
            poster_url=poster_url,
        )
        return _done(out)

    # 向量路径同样以本地 NFO 硬缺口判定成功（缺剧情/女优/片商→软成功）
    try:
        _, remain = _local_folder_gaps(folder)
    except Exception:  # noqa: BLE001
        remain = []
    if remain:
        out["gapsAfter"] = remain
    out["fields"] = _fields_after_local_write(
        folder,
        detail,
        local_cover_ok=local_cover_ok,
        poster_url=poster_url,
    )
    _apply_local_gap_success(
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
        got_actors = _soft_retry_fill_actors(
            code=str(code or ""),
            region=region,
            folder=folder,
            nfo=nfo,
            detail=detail,
        )
        if got_actors:
            try:
                _, remain = _local_folder_gaps(folder)
            except Exception:  # noqa: BLE001
                remain = [g for g in (remain or []) if g != "no_actress"]
            out["gapsAfter"] = list(remain or [])
            out["softActressRetry"] = True
            out["fields"] = _fields_after_local_write(
                folder,
                detail,
                local_cover_ok=local_cover_ok,
                poster_url=poster_url,
            )
            _apply_local_gap_success(
                out,
                folder=folder,
                code=str(code or ""),
                region=region,
                remain=remain,
                only_if_ok=True,
            )
    return _done(out)


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
    kind_list = [k for k in (kinds or list(_DEFAULT_ENRICH_KINDS)) if k in _ENRICH_KINDS]
    if not kind_list:
        kind_list = list(_DEFAULT_ENRICH_KINDS)
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
    sources = _detail_sources(region=region)
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
    # ① 预览本身不写检查点（见下方 _save_checkpoint 门禁）；
    # ② 一旦续跑，检查点的 queueInLog 会走 _rebuild_checkpoint_queue_from_log
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
            db_pending = int(_queue_log_status_counts(region, fresh=True).get("pending") or 0)
        except Exception:  # noqa: BLE001
            db_pending = 0
        if (
            bool(resume_cp.get("queueInLog"))
            or rem_declared > len(queue)
            or db_pending > len(queue)
        ):
            from_log = _rebuild_checkpoint_queue_from_log(region)
            if from_log:
                queue = from_log
                rem_declared = max(rem_declared, db_pending, len(queue))
        original_total = int(
            resume_cp.get("originalTotal")
            or (prior_done + max(len(queue), rem_declared, db_pending))
        )
        _push_log(
            f"继续 · {mode_label} · {region or '全部'} · "
            f"已完成 {prior_done}/{original_total} · 剩余 {len(queue)}",
            region=region,
        )
        _push_log(
            f"策略 · {cfg.get('mode')} · 过盾={'开' if include_flare else '关'} · "
            f"分组 · {'+'.join(groups) or '-'} · 数据源 · {src_label}",
            region=region,
        )
    else:
        resume_cp = None
        _push_log(
            f"{'预览' if dry_run else '补齐'} · {mode_label} · {region or '全部'} · "
            f"{'全量' if overwrite else 'kinds=' + ','.join(kind_list)} · limit={lim_label}",
            region=region,
        )
        _push_log(
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
                _dirs = _region_local_dirs(_root, region)
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
                        _code, _ = _local_folder_gaps(_folder)
                        queue.append(
                            {
                                "itemId": _rel,
                                "code": _code,
                                "gaps": list(_ENRICH_KINDS),
                                "rel_path": _rel,
                                "relPath": _rel,
                                "region": region,
                            }
                        )
                        if fetch_lim > 0 and len(queue) >= fetch_lim:
                            break
                    if fetch_lim > 0 and len(queue) >= fetch_lim:
                        break
                _push_log("队列来源 · 本地 NFO（覆盖）", region=region)
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
            _push_log(f"队列 {len(queue)} 条", region=region)
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
                    iids, codes = _queue_log_done_keys(region)
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
                if region not in _demoted_false_dones:
                    threading.Thread(
                        target=_queue_log_demote_false_dones_budgeted,
                        kwargs={"region": region, "time_budget_sec": 5.0},
                        name=f"demote-bg-{region}",
                        daemon=True,
                    ).start()
            except Exception as e:  # noqa: BLE001
                log.warning("enrich start demote schedule failed: %s", e)
            try:
                lib = _region_library_progress(region)
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
            _push_log(
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
                    for batch in iter_enrich_pending_batches(
                        region=region,
                        batch_size=200,
                        limit=fetch_lim if fetch_lim > 0 else 0,
                        skip_item_ids=skip_done_iids,
                        skip_codes=skip_done_codes,
                        defer_skip_until=skip_ready,
                    ):
                        if _halt_kind():
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
                        view_batch = _ensure_queue_log_ids(
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
                            _enrich_job["queue"] = _cap_status_queue(qv)
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
                        notify_enrich_watchers()
                        if fetch_lim > 0 and fed >= fetch_lim:
                            break
                except Exception as e:  # noqa: BLE001
                    log.warning("enrich feed loop failed: %s", e)
                    _push_log(f"扫描入队异常 · {e}", region=region)
                finally:
                    feed_done.set()
                    with queue_cv:
                        queue_cv.notify_all()
                    _push_log(f"扫描入队结束 · 共 {len(queue)} 条", region=region)

            feed_th = threading.Thread(
                target=_feed_loop, name="enrich-feed", daemon=True
            )
            feed_th.start()
            with queue_cv:
                if not queue:
                    queue_cv.wait(timeout=2.0)
            if queue:
                _push_log(
                    f"刮削已启动 · 队列 {len(queue)}（只消费未处理队列表，不再扫盘）",
                    region=region,
                )
            else:
                _push_log(
                    "刮削已启动 · 等待未处理入队…",
                    region=region,
                )

    # 历史脏数据清理改后台：同步跑会挡 worker 占槽（处理中一直 0）
    if not dry_run:

        def _prune_bg() -> None:
            try:
                cleaned = _queue_log_prune_open_if_done(region)
                if cleaned:
                    _push_log(f"清理成功残留未处理 {cleaned}", region=region)
                cleaned_run = _queue_log_prune_pending_if_running(region)
                if cleaned_run:
                    _push_log(f"清理处理中残留未处理 {cleaned_run}", region=region)
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
            lid = _queue_log_int_id(r)
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
        queue_view = _ensure_queue_log_ids(region, queue_view, persist=not dry_run)
        for i, vr in enumerate(queue_view):
            if i < len(queue) and isinstance(queue[i], dict):
                lid = _queue_log_int_id(vr)
                if lid:
                    queue[i] = dict(queue[i])
                    queue[i]["logId"] = lid
                if not str(queue[i].get("region") or "").strip():
                    queue[i]["region"] = region
        _set_queue(queue_view)
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
        halted = _halt_kind() in {"pause", "stop"}
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
                    if len(results) > int(_RESULTS_MEM_CAP):
                        del results[: len(results) - int(_RESULTS_MEM_CAP)]
                _patch_queue_item(
                    i, match=row, persist=persist_db, status="fail", error=str(exc)[:120]
                )
                _set_current(
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
                _push_log(f"{row.get('code')}: {exc}", region=region)
                _set_progress(
                    stage="enrich",
                    label=f"处理 {prior_done + cur_ok + cur_fail}/{original_total}",
                    ok=cur_ok,
                    failed=cur_fail,
                )
            else:
                if persist_db:
                    _queue_log_update_row(
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
            folder = _resolve_enrich_folder(
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
            if folder is None or not _local_success_disk_ok(folder):
                one["ok"] = False
                one["partialOk"] = False
                one["error"] = str(one.get("error") or "仍缺:封面 · 落盘校验失败")[
                    :120
                ]
                one["gapsAfter"] = list(one.get("gapsAfter") or ["no_local"])
                _push_log(
                    f"{code_u} · 成功回滚 · 落盘校验失败",
                    region=region,
                )
        # 有界重试记账（封面重试上限 / 源故障补抓）；预览不落库 → 必须跳过
        if persist_db and not bool(one.get("dryRun")):
            try:
                _note_retry_hints(region=region, code=code_u, row=row, one=one)
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
            _patch_queue_item(i, match=row, persist=persist_db, **patch)
        if persist_db:
            # 强制落库：用提交时 row 的 logId/番号（暂停时也写）
            persist = dict(row)
            persist.update(patch)
            persist["code"] = code_u or str(persist.get("code") or "")
            persist["itemId"] = str(
                persist.get("itemId") or row.get("itemId") or ""
            )
            try:
                new_lid = _queue_log_update_row(persist, region=region)
                if st == "done":
                    _iid2 = str(persist.get("itemId") or "")

                    def _prune_open_bg2() -> None:
                        try:
                            _queue_log_prune_open_if_done(
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
                    and int(new_lid) != _queue_log_int_id(persist)
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
        _set_current(
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
            results.append(_slim_one_result_mem(one))
            if len(results) > int(_RESULTS_MEM_CAP):
                del results[: len(results) - int(_RESULTS_MEM_CAP)]
        if one.get("ok"):
            with counters_lock:
                ok_n += 1
                cur_ok, cur_fail = ok_n, fail_n
            if one.get("vectorSynced"):
                _push_log(f"{code_u} · 完成（刮削+向量）", region=region)
            elif one.get("vectorSkipped"):
                _push_log(f"{code_u} · 完成（仅本地）", region=region)
            if persist_db:
                _maybe_prune_done_logs(region)
        else:
            with counters_lock:
                fail_n += 1
                cur_ok, cur_fail = ok_n, fail_n
            _push_log(
                f"{one.get('code') or code_u}: {one.get('error') or 'fail'}",
                region=region,
            )
            if persist_db:
                _maybe_prune_done_logs(region)
        _set_progress(
            stage="enrich",
            label=f"处理 {prior_done + cur_ok + cur_fail}/{original_total}",
            ok=cur_ok,
            failed=cur_fail,
        )

    def _run_one(i: int, row: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any] | None, BaseException | None]:
        if _halt_kind():
            return i, row, None, None
        code_u = str(row.get("code") or "").strip().upper()
        item_id = str(row.get("itemId") or "")
        gaps = list(row.get("gaps") or [])
        abs_i = prior_done + i
        _patch_queue_item(i, match=row, persist=persist_db, status="running")
        if _halt_kind():
            return i, row, None, None
        try:
            enrich_mon.item_start(code=code_u, item_id=item_id, region=region)
            enrich_mon.set_phase(code=code_u, item_id=item_id, phase="fetch")
            notify_enrich_watchers(force=True)
        except Exception:  # noqa: BLE001
            pass
        _set_current(
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
            one = enrich_one_row(
                row,
                dry_run=dry_run,
                # 源故障补抓行：必须允许覆盖写回。`merge_nfo_with_detail` 默认只补
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
                notify_enrich_watchers(force=True)
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
                notify_enrich_watchers(force=True)
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
            lid = _queue_log_int_id(r)
            if lid:
                remaining_by_id[key]["logId"] = lid
        for r in queue[next_i:]:
            if not isinstance(r, dict):
                continue
            key = str(r.get("itemId") or r.get("code") or "").strip()
            if key and key not in remaining_by_id:
                remaining_by_id[key] = dict(r)
        return list(remaining_by_id.values())

    workers = max(1, int(_ITEM_WORKERS_DEFAULT))
    try:
        import app.scrap_library.enrich_strategy as strat

        cfg_w = int(strat.get_strategy().get("itemWorkers") or _ITEM_WORKERS_DEFAULT)
        from app.core.container_budget import cap_parallel

        workers = cap_parallel(
            max(1, min(int(_ITEM_WORKERS_MAX), cfg_w)),
            tight=2,
            small=4,
            hard=int(_ITEM_WORKERS_MAX),
        )
    except Exception:  # noqa: BLE001
        from app.core.container_budget import cap_parallel as _cap_workers

        workers = _cap_workers(
            workers, tight=2, small=4, hard=int(_ITEM_WORKERS_MAX)
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
        notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    _push_log(f"并发番号 · {workers} · 封面池 {_cover_job_workers_target()}", region=region)
    next_i = 0
    inflight: dict[Any, int] = {}
    # 「请求并发超出出站槽档位」只提示一次，避免每轮刷屏
    _outbound_cap_warned = False
    # 池按上限开；循环内按最新 itemWorkers 节流，改策略后下一轮投递即生效
    pool_cap = int(workers)
    from app.core.container_budget import memory_class as _mem_class

    if _mem_class() == "host":
        pool_cap = max(workers, int(_ITEM_WORKERS_MAX))
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
                    or _ITEM_WORKERS_DEFAULT
                )
                want_w = max(1, min(pool_cap, cfg_live))
                if want_w > cfg_workers:
                    if not _outbound_cap_warned:
                        _outbound_cap_warned = True
                        _push_log(
                            f"并发番号请求 {want_w} 超出出站槽档位 {cfg_workers} · "
                            f"已封顶（重开任务后生效）",
                            region=region,
                        )
                    want_w = cfg_workers
                if want_w != workers:
                    workers = want_w
                    _push_log(f"并发番号热更新 · {workers}", region=region)
            except Exception:  # noqa: BLE001
                pass
            with _enrich_lock:
                has_retry = bool(_enrich_retry_front)
            # 边扫边刮：扫描未结束时队列空也继续等
            feeding = bool(live_feed and not feed_done.is_set())
            if not (next_i < len(queue) or inflight or has_retry or feeding):
                break
            halt = _halt_kind()
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
                        _save_checkpoint(
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
                    _push_log(
                        f"已暂停 · 进行中已退回未处理 · 剩余 {len(remaining)}",
                        region=region,
                    )
                else:
                    cancelled = True
                    _clear_checkpoint(region)
                    _clear_runtime_queue()
                    _queue_log_reopen_running(region=region)
                    log.info(
                        "enrich stopped region=%s done=%s/%s",
                        region,
                        prior_done + next_i,
                        original_total,
                    )
                break

            while len(inflight) < workers:
                if _halt_kind():
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
                    lid = _queue_log_int_id(row_retry)
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
            db_pending = int(_queue_log_status_counts(region, fresh=True).get("pending") or 0)
        except Exception:  # noqa: BLE001
            db_pending = 0
        if db_pending > 0:
            _save_checkpoint(
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
            _push_log(
                f"本轮队列已空 · 库内仍有未处理 {db_pending} · 已暂停可继续",
                region=region,
            )
        else:
            _clear_checkpoint(region)

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
                int(_queue_log_status_counts(region, fresh=True).get("pending") or 0)
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
            dbc = _queue_log_status_counts(region, fresh=True)
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
        _push_log(f"已暂停 · 成功 {ok_n} · 失败 {fail_n}", region=region)
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
            dbc = _queue_log_status_counts(region, fresh=True)
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
        _push_log(f"完成 · 成功 {ok_n} · 失败 {fail_n}", region=region)
    return summary


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
    pool = get_meta_pool()
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

    nfo = _find_nfo(folder) or (folder / f"{folder.name}.nfo")
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
    fields = fields_from_movie_root(root_el, code_fallback=str(d.get("code") or ""))
    cur_plot = str(fields.get("plot") or "").strip()
    if cur_plot and cur_plot != plot_zh:
        if not str(fields.get("originalplot") or "").strip():
            fields["originalplot"] = cur_plot
    fields["plot"] = plot_zh
    fields["outline"] = plot_zh
    root_el = build_mdcx_nfo_root(fields)
    write_nfo(nfo, root_el)

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
        rein = reingest_folder(folder)
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
        pool = get_meta_pool()
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
        _push_log(
            f"单条{mode_label} · {code or iid} · gaps={','.join(gaps) or 'none'}"
        )
        _set_progress(
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
            _push_log(f"{code or iid} · 已清空向量行，开始重刮")
            _set_progress(
                stage="enrich",
                percent=25,
                label=f"重刮 {code or iid}",
                done=0,
                total=1,
            )

        one = enrich_one_row(
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
                    rein = reingest_folder(folder)
                    _push_log(
                        f"{code or iid} · 覆盖失败，已尝试从 NFO 救回向量"
                        f" · {rein.get('error') or ('ok' if rein.get('ok') else 'fail')}"
                    )
                except Exception as e:  # noqa: BLE001
                    _push_log(f"{code or iid} · 向量救回失败 · {e}")

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
            _enrich_job["result"] = _slim_result_for_status(out)
            _enrich_job["phase"] = "done" if one.get("ok") else "error"
            if not one.get("ok"):
                _enrich_job["error"] = str(one.get("error") or "fail")
        _set_progress(
            stage="done",
            percent=100,
            label="完成",
            done=1 if one.get("ok") else 0,
            total=1,
        )
        _push_log(
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
        flush_enrich_logs()


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

    _hydrate_enrich_runtime()

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
            # 若让它续跑，检查点的 queueInLog 会让 run_enrich 用
            # _rebuild_checkpoint_queue_from_log 重建整个分区的 pending（有码区 2 万+），
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
                    _queue_log_status_counts(rid, fresh=True).get("pending") or 0
                )
            except Exception:  # noqa: BLE001
                db_pending = 0
            if (
                bool(raw.get("queueInLog"))
                or rem_declared > len(remaining_q)
                or db_pending > len(remaining_q)
            ):
                from_log = _rebuild_checkpoint_queue_from_log(rid)
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
                            if (lid := _queue_log_int_id(r))
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
        badge_seed = _empty_queue_counts()
        badge_rid = next((r for r in region_list if r), "")
        if badge_rid:
            try:
                badge_seed = _apply_local_status_totals(
                    _queue_log_status_counts(badge_rid, fresh=True),
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
    notify_enrich_watchers(force=True)

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
                halt = _halt_kind()
                if halt:
                    if halt == "pause":
                        paused = True
                        _push_log("已暂停，后续分区跳过")
                    else:
                        cancelled = True
                        _clear_checkpoint(rid)
                        _clear_runtime_queue()
                        _queue_log_reopen_running(region=rid)
                        log.info("enrich stopped, skip remaining regions")
                    break
                label = str((REGION_META.get(rid) or {}).get("label") or rid)
                _set_current_region(rid)
                cp = resume_map.get(rid)
                if cp:
                    _push_log(
                        f"分区 {idx + 1}/{len(region_list)} · {label} · 继续",
                        region=rid,
                    )
                else:
                    _push_log(
                        f"分区 {idx + 1}/{len(region_list)} · {label}",
                        region=rid,
                    )
                if budget is not None and budget <= 0 and not cp:
                    _push_log(f"跳过 {label}（预览额度已用完）", region=rid)
                    break
                use_lim = budget if budget is not None else int(limit or 0)
                # 续跑：队列来自检查点；mode/kinds 用本次请求（=最新策略），改策略后立刻生效
                use_mode = mode_norm
                use_kinds = list(kinds or [])
                one = run_enrich(
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
                # 预算按实际处理条数扣减（见 _next_budget 注释）
                if not cp:
                    budget = _next_budget(budget, one)
                if paused or cancelled:
                    break
            _set_current_region("")
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
                _enrich_job["result"] = _slim_result_for_status(result)
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
                    _queue_log_reopen_running(region=str(rid))
            _persist_enrich_runtime()
        except Exception as e:  # noqa: BLE001
            log.exception("scrap library enrich failed")
            with _enrich_lock:
                _enrich_job["error"] = str(e)
                _enrich_job["phase"] = "error"
                log_list = list(_enrich_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _enrich_job["log"] = log_list[-40:]
            _persist_enrich_runtime()
        finally:
            with _enrich_lock:
                _enrich_job["running"] = False
                _enrich_job["halt"] = None
                _enrich_job["cancel"] = False
            # 收尾/暂停/停止都要把攒批的日志落库（否则要等后台线程或进程退出）
            flush_enrich_logs()
            try:
                enrich_mon.clear_job()
            except Exception:  # noqa: BLE001
                pass
            _persist_enrich_runtime()
            notify_enrich_watchers(force=True)

    threading.Thread(target=run, name="scrap-library-enrich", daemon=True).start()
    return {"started": True, "resumed": bool(resume_map)}


# ==========================================================================
# 以下名字已搬到兄弟模块；此处再导出，保证 `enrich.NAME` 调用/打补丁零改动。
# 注意：必须放在文件末尾 —— 兄弟模块会回引本模块的名字，
#       等本模块顶层全部定义完再导入，才能避免循环导入。
# ==========================================================================
from app.scrap_library.enrich_checkpoint import (  # noqa: E402
    _save_checkpoint, _clear_checkpoint, _take_checkpoint, _peek_checkpoint, _slim_checkpoint_queue, _CHECKPOINT_PERSIST_QUEUE_MAX,
    _checkpoint_for_persist, _rebuild_checkpoint_queue_from_log,
)
from app.scrap_library.enrich_cover import (  # noqa: E402
    _cover_fail_message, _poster_rank, _dmm_poster_fallbacks, _rewrite_cover_host_mirrors, _normalize_cover_entries, _cover_job_workers_target,
    _download_covers, _purge_extra_cover_files, _local_poster_ok, _stat_is_file, _local_poster_ok_uncached, _local_success_disk_ok,
    _LOCAL_COVER_FILES, list_local_covers, _purge_blank_covers,
)
from app.scrap_library.enrich_detail import (  # noqa: E402
    _detail_usable, _detail_from_local_folder, _backfill_queue_item_detail, _collect_nfo_folders_parallel, _classify_disk_gaps, _detail_field_rows,
    _fields_after_local_write, _source_in_cooldown, _note_source_fetch_outcome, _src_give_up_reason, _classify_source_failure, _safe_local_gaps,
    _detail_sources, _identity_gate_details, _detail_has_poster, _detail_has_actors, _detail_satisfies_gaps, _prioritize_batch_for_gaps,
    _detail_meta_incomplete, _may_early_stop, _gaps_likely_ready, _fetch_detail, _find_nfo, _ensure_child,
    _resolve_enrich_folder,
)
from app.scrap_library.enrich_history import (  # noqa: E402
    _ENRICH_LOG_KEEP, _ENRICH_LOG_RETURN, _ENRICH_LOG_MEMORY, _enrich_log_region_keys, _canonical_enrich_log_region, _persist_enrich_log,
    flush_enrich_logs, enrich_log_sink_stats, load_enrich_logs, _HIST_LOG_TTL_SEC, _load_enrich_logs_cached, _clear_enrich_logs,
    clear_enrich_logs, _recover_done_from_enrich_logs,
)
from app.scrap_library.enrich_merge import (  # noqa: E402
    _halt_kind, current_strategy_epoch, _note_strategy_hot_if_needed, apply_live_strategy, _field_priority_applies, _strategy_field_priority,
    _strategy_region_sources, _merge_source_allowed, _pick_by_field_priority, _merge_got, _FIELD_LAUNCH_ORDER, _merge_enrich_sidecar_into_item,
    _set_text_if_empty, _merge_list_tags, _merge_actors, merge_nfo_with_detail,
)
from app.scrap_library.enrich_queue import (  # noqa: E402
    _QUEUE_LOG_DONE_KEEP, _QUEUE_LOG_PRUNE_EVERY, _QUEUE_LOG_STATUSES, _QUEUE_LOG_FILTER_STATUSES, _QUEUE_LOG_PAYLOAD_KEYS, _QUEUE_SCAN_SAMPLE_CAP,
    _QUEUE_SCAN_NOTIFY_GAP, _queue_scan_preview_item, _queue_scan_snapshot, _queue_scan_add_sample, _clear_queue_scan_progress, _queue_log_status_counts_db_ex,
    _queue_log_status_counts_db, _queue_log_scrape_counts_db, _queue_log_status_counts, _queue_log_int_id, _queue_log_payload, _queue_log_read_payload,
    _queue_log_insert_params, _queue_log_row_to_item, _clear_queue_log, _queue_log_mark_pending, _queue_log_reopen_running, _queue_log_reopen_stale_running,
    _queue_log_reopen_fails, _queue_log_reopen_softs, _queue_log_find_open, _queue_log_done_keys, _ensure_queue_log_ids, _queue_log_prune_pending_not_in,
    _queue_log_prune_open_if_done, _queue_log_prune_done_keep, _queue_log_prune_pending_if_running, _queue_log_clear_pending, _queue_log_classified_skip_keys, _queue_log_trim_inflated_pending,
    _queue_log_clear_local_scan_status, _QUEUE_LOG_INSERT_CHUNK, _queue_log_insert_local_status_samples, _queue_row_status, _queue_counts_of, _sample_queue_uncached,
    _queue_row_match_index, _payload_field_code, _queue_log_demote_false_dones, _queue_log_demote_false_dones_budgeted, _queue_log_promote_actress_soft_fails, _queue_log_normalize_soft_to_full_success,
)
from app.scrap_library.enrich_retry import (  # noqa: E402
    _SOFT_OK_PREFIX, _SOFT_OK_PREFIXES, _SOFT_PROMOTE_RULE_VER, _SOFT_CORRECTION_MIN_INTERVAL_SEC, _gap_labels, _strip_soft_ok_prefix,
    _is_soft_ok_error, _format_soft_ok_error, _soft_done_sql_pred, _is_soft_remain_error, _soft_gaps_from_remain_error, _RETRY_KIND_COVER,
    _RETRY_KIND_SRC_DOWN, _COVER_RETRY_MAX, _SRC_DOWN_RETRY_MAX, _RETRY_HINT_CACHE_TTL, _retry_next_state, _is_cover_only_gaps,
    _SRC_GIVEUP_POLL_SEC, _SOURCE_COOLDOWN_STREAK, _SOURCE_COOLDOWN_SEC, _MISS_HINTS, _CancelPair, _src_retry_item,
    _retry_hint_load, _retry_hint_invalidate, _retry_hint_clear_region, _retry_hint_clear_codes, _cover_giveup_codes, _should_skip_for_giveup,
    _note_retry_hints, _apply_local_gap_success, _ensure_actress_soft_promoted, _is_cancelled,
)
from app.scrap_library.enrich_scan import (  # noqa: E402
    _SQL_NOT_SCAN_SOURCE, _SQL_IS_SCAN_SOURCE, _CachedLocalMapsMarker, _local_nfo_maps_cache_get, _local_nfo_maps_cache_put, _region_local_dirs,
    _local_scan_workers, _folder_gaps_cache_cap, _SCAN_STREAM_FLUSH, _folder_gaps_stamp, _local_folder_gaps, iter_local_incomplete_items,
    _local_status_item, _LocalNfoMaps, _local_nfo_gap_maps, _rebuild_region_queue_from_scan, _replace_pending_from_vector, _hot_prefixes_for_region,
    scan_enrich_queue, _code_search_match, _lookup_code_from_scan_samples, _lookup_code_outside_queue_log,
)
from app.scrap_library.enrich_sidecar import (  # noqa: E402
    _file_stamp, _ENRICH_SIDECAR_LEGACY, _ENRICH_SIDECAR_VER, _enrich_sidecar_code, _enrich_sidecar_path, write_enrich_sidecar,
    read_enrich_sidecar,
)
from app.scrap_library.enrich_status import (  # noqa: E402
    _persist_local_status_totals, _set_local_status_totals, _clear_local_status_totals, _apply_local_status_totals, _region_counts_ok, _slim_one_result_mem,
    _pending_total_estimate, _clamp_pending_badge, _pending_page_from_vector, _slim_queue_row_for_status, _slim_queue_for_status, _slim_current_for_status,
    _slim_result_for_status, _progress_from_queue_counts, _region_library_progress, get_enrich_status, _cap_status_queue, _empty_queue_counts,
)
from app.scrap_library.enrich_text import (  # noqa: E402
    _NAME_PAIR_CENSOR_RESTORE, _looks_like_actor_sentence_frag, _is_platform_exclusivity_label, _looks_like_act_tag_token, _looks_like_person_name_tag, _names_from_title_pairs,
    _actress_disp_id, _unique_identity_names, _estimate_cast_size, _collapse_few_actress_variants, _titles_compatible, _actors_lifted_from_tags,
    _fold_tag_variant, _fold, _clean_tags, _has_cjk, _has_kana, _has_traditional,
    _has_han, _zh_prefer_bonus, _title_lacks_zh, _normalize_merged_title, _normalize_merged_overview, _mt_junk_penalty,
    _title_trailing_person_name, _title_actress_mismatch_penalty, _score_title, _title_should_prefer_map, _norm_code_token, _trailing_alt_code,
    _strip_trailing_alt_code, _overview_foreign_actress_penalty, _score_overview, _score_studio, _score_date, _score_year,
    _score_actors, _score_poster, _score_tags, _normalize_tag_alias, _pick_best_str, _actor_hints_from_titles,
    _text_needs_zh_llm, _zh_fill_acceptable, _align_llm_text_actors, _got_has_zh_title, _got_has_zh_plot, _prune_junk_actors,
    _replace_actors, _replace_list_tags,
)
