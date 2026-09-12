# -*- coding: utf-8 -*-
"""刮削库元数据补全：按配置片商源拉详情 → 写回 NFO/封面 → 重嵌入。"""

from __future__ import annotations

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from fastapi import HTTPException

import app.scrap_library.embed as embed_svc
from app.ai.config import resolve_embed_config
from app.ai.embed import encode_texts_sync
from app.core.db import get_meta_pool, media_dir
from app.scrap_library.nfo import parse_nfo, write_nfo

log = logging.getLogger(__name__)

_ENRICH_KINDS = (
    "no_local",
    "no_media",
    "no_actress",
    "no_studio",
    "no_plot",
    "thin_title",
)

# 完整补齐：封面 + 女优/片商/剧情/标题等元数据缺口
_DEFAULT_ENRICH_KINDS = tuple(_ENRICH_KINDS)

# 批量补齐时同时处理的番号数（源站并发仍由策略配置）
_ITEM_WORKERS = 3

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

# 类型/站点标签常被误塞进女优字段（MissAV 等）
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
)


_NAME_PAIR_CENSOR_RESTORE = (
    (re.compile(r"輪\s*[●○*＊※]\s*姦?"), "輪姦"),
    (re.compile(r"轮\s*[●○*＊※]\s*姦?"), "轮姦"),
    (re.compile(r"強\s*[●○*＊※]\s*姦?"), "強姦"),
    (re.compile(r"强\s*[●○*＊※]\s*姦?"), "强姦"),
    (re.compile(r"中\s*[●○*＊※]\s*し"), "中出し"),
    (re.compile(r"レ\s*[●○*＊※]\s*プ"), "レイプ"),
    (re.compile(r"リ\s*[●○*＊※]\s*プ"), "レイプ"),
)


def _names_from_title_pairs(title: str) -> list[str]:
    """从「A×B」「A × B」标题对里抽出人名（SOD 社员企划等演员栏常空）。

    审查伏字（● ○ * ＊ ※）**不是**人名对分隔符：先还原「輪●/強●/中●し/レ●プ」
    等惯用伏字，再把残余伏字当噪声删除；只有真正的 ×/x/X 才视为分隔符。
    （案例 RLMP-014：「轮●粉丝服务」曾被拆出「作共用飞机杯的轮」「粉丝服务」垃圾人名。）
    """
    t = str(title or "")
    if not t:
        return []
    for _pat, _rep in _NAME_PAIR_CENSOR_RESTORE:
        t = _pat.sub(_rep, t)
    # 残余伏字直接删除，不再一律换成 ×（否则会造出假人名对）
    t = re.sub(r"[●○*＊※]", "", t)
    out: list[str] = []
    seen: set[str] = set()
    genre_hint = ("レズ", "女同", "蕾丝", "莱斯", "ビアン", "lesbian", "系列", "作品")
    frag_hint = ("に", "を", "た", "され", "中出", "隣人", "人妻", "夫", "妻")
    for a, b in re.findall(
        r"([\u4e00-\u9fffぁ-んァ-ン]{2,8})\s*[×xX]\s*([\u4e00-\u9fffぁ-んァ-ン]{2,8})",
        t,
    ):
        for n in (a.strip(), b.strip()):
            if len(n) < 2 or n in seen:
                continue
            if n in {"SOD", "Vol"} or re.fullmatch(r"\d+", n):
                continue
            # 题材对（痴女×痴女レズビアン）不是人名（CESD-204）
            if n in _JUNK_ACTOR_TAGS or n.casefold() in _JUNK_ACTOR_TAGS:
                continue
            if any(h in n for h in genre_hint):
                continue
            # 句段残片（な隣人に中出しレ × プされ…）
            if sum(1 for h in frag_hint if h in n) >= 2:
                continue
            seen.add(n)
            out.append(n)
    return out


def _titles_compatible(
    a: str, b: str, *, actors: list[str] | None = None
) -> bool:
    """两标题是否像同一作品（错页如「ジュポニカ」vs「最愛の妻」→ False）。"""

    def toks(s: str) -> set[str]:
        # 去掉审查占位，避免「レ●プ」把前后汉字拆断后无法对齐中文标题
        cleaned = re.sub(r"[●○\*＊※]+", "", str(s or ""))
        out: set[str] = set()
        for run in re.findall(r"[\u4e00-\u9fffぁ-んァ-ン]+", cleaned):
            if len(run) < 2:
                continue
            out.add(run)
            # 长串无空格时整段成一词，繁简会零交集；补二字滑动窗
            if len(run) >= 4:
                for i in range(len(run) - 1):
                    out.add(run[i : i + 2])
        return {m for m in out if len(m) >= 2}

    sa, sb = str(a or ""), str(b or "")
    ta, tb = toks(sa), toks(sb)
    if not ta or not tb:
        return True
    if ta & tb:
        return True
    # 中日译名常无字面交集：用本片女优别名两边是否都出现来判定
    acts = [str(x).strip() for x in (actors or []) if str(x or "").strip()]
    if not acts:
        return False
    try:
        from app.scrape.metadata_optimize import (
            _actor_maps,
            _lookup_actor_hit,
            mapping_language_from_settings,
        )

        table = _actor_maps(mapping_language_from_settings())
    except Exception:  # noqa: BLE001
        table = {}
    for act in acts:
        aliases: set[str] = {act}
        hit = _lookup_actor_hit(act, table) if table else None
        canon = act
        if isinstance(hit, dict):
            canon = str(hit.get("name") or hit.get("zh") or act).strip() or act
        elif isinstance(hit, str) and hit.strip():
            canon = hit.strip()
        aliases.add(canon)
        if table:
            for k, v in table.items():
                name = ""
                if isinstance(v, dict):
                    if v.get("drop"):
                        continue
                    name = str(v.get("name") or v.get("zh") or "").strip()
                elif isinstance(v, str):
                    name = v.strip()
                if name == canon or name == act:
                    aliases.add(str(k))
                    if name:
                        aliases.add(name)
        aliases = {x for x in aliases if len(x) >= 2}
        in_a = any(al in sa for al in aliases)
        in_b = any(al in sb for al in aliases)
        if in_a and in_b:
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
        if any(s in name for s in _JUNK_ACTOR_SUBSTR):
            continue
        # 带数字的前缀/番号（SOD123 / MIMK-286）；纯字母艺名如 Rio 保留
        if re.fullmatch(r"[A-Z]{2,10}-?\d{2,}[A-Z0-9]*", name, re.I):
            continue
        # 纯数字 / URL / HTML
        if re.fullmatch(r"\d+", name) or re.search(r"https?://|<|>", name, re.I):
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


def _fold_tag_variant(tag: str) -> str:
    """繁/日 → 简 折叠（标签去重前统一字形，避免「穿衣幹砲」+「穿衣干炮」重复）。"""
    try:
        from app.scrape.metadata_optimize import _fold_variant

        return _fold_variant(tag)
    except Exception:  # noqa: BLE001
        return tag


def _clean_tags(tags: list[str] | None, *, fold: bool = True) -> list[str]:
    """清洗标签：去空/超长/垃圾词/按字形去重。

    `fold=True`（默认）会先做繁简/异体/日文旧字归一，用于**最终输出**去重。
    `fold=False` 用于**源侧明细**（`_detail_usable` 与源解析后的 detail）：
    因为 `_score_tags` 依赖「繁体惩罚」来偏好简中源，若提前折叠，
    javbus 这类繁中源会失去惩罚、反压过 airav/iqqtv（案例 ACHJ-078：
    折叠后 javbus 116→134，与 E2E 预期 airav_io@123 冲突）。
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        raw_tag = str(raw or "").strip()
        if not raw_tag:
            continue
        # 先按字形归一（繁简/异体折叠），再去重、再长度门禁
        tag = _fold_tag_variant(raw_tag) if fold else raw_tag
        if not tag or len(tag) > 30:
            continue
        key = tag.casefold()
        if raw_tag.casefold() in _JUNK_TAGS or key in _JUNK_TAGS or key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def _detail_usable(detail: dict[str, Any] | None, *, code: str) -> bool:
    """拒绝登录页/盾页等脏详情，避免写坏 NFO。"""
    if not detail or not isinstance(detail, dict):
        return False
    code_u = str(code or detail.get("code") or "").strip().upper()
    title = str(detail.get("title") or "").strip()
    title_l = title.casefold()
    if not title:
        return False
    if any(m in title_l for m in (x.casefold() for x in _JUNK_TITLE_MARKERS)):
        return False
    if _title_is_thin(title, code_u) and not (
        detail.get("posterUrl") or detail.get("overview") or _clean_actors(detail.get("actors"))
    ):
        return False
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    overview = str(detail.get("overview") or "").strip()
    studio = str(detail.get("studio") or detail.get("maker") or "").strip()
    actors = _clean_actors(detail.get("actors"))
    tags = _clean_tags(detail.get("tags"), fold=False)  # 源侧：勿折叠，保留繁简信息给评分
    code_in_title = bool(code_u) and code_u.casefold() in title_l
    # 至少有一项可用信号
    if poster.startswith(("http://", "https://")):
        return True
    if overview and len(overview) >= 12:
        return True
    if studio and actors:
        return True
    if actors and (code_in_title or len(title) >= 8):
        return True
    if studio and code_in_title and len(title) > len(code_u) + 2:
        return True
    if tags and code_in_title and len(title) > len(code_u) + 2:
        return True
    return False


_enrich_lock = threading.Lock()
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
}


def _checkpoint_summaries() -> dict[str, Any]:
    raw = dict(_enrich_job.get("checkpoints") or {})
    out: dict[str, Any] = {}
    for rid, cp in raw.items():
        key = str(rid or "").strip()
        if not key or not isinstance(cp, dict):
            continue
        remaining = list(cp.get("queue") or [])
        done = int(cp.get("done") or 0)
        total = int(cp.get("originalTotal") or (done + len(remaining)))
        out[key] = {
            "region": key,
            "mode": str(cp.get("mode") or "incremental"),
            "dryRun": bool(cp.get("dryRun")),
            "done": done,
            "remaining": len(remaining),
            "total": total,
            "ok": int(cp.get("ok") or 0),
            "failed": int(cp.get("failed") or 0),
        }
    return out


_ENRICH_LOG_KEEP = 2000
# 状态接口回传本轮尾部；角标按内存实际条数（见 regionLogCounts）
_ENRICH_LOG_RETURN = 200
_ENRICH_LOG_MEMORY = 500


def _enrich_log_region_keys(region: str) -> list[str]:
    """分区日志可能的键：稳定 id + 中文目录名 + 短标签。"""
    raw = str(region or "").strip()
    if not raw:
        return ["_all"]
    from app.core.region_meta import REGION_META, REGION_ORDER

    keys: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        s = str(v or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        keys.append(s)

    add(raw)
    # id → label
    meta = REGION_META.get(raw)
    if meta:
        add(str(meta.get("label") or ""))
        add(str(meta.get("id") or ""))
    # label / 目录名 → id
    for rid, m in REGION_META.items():
        label = str(m.get("label") or "").strip()
        if raw == label or raw == rid:
            add(rid)
            add(label)
    # 短标签「有码」等
    for rid in REGION_ORDER:
        m = REGION_META.get(rid) or {}
        label = str(m.get("label") or "")
        if raw in label or label.endswith(raw):
            add(rid)
            add(label)
    return keys or [raw]


def _canonical_enrich_log_region(region: str | None = None) -> str:
    """落库/内存统一用稳定 id，避免 日本有码 / japan_censored 分裂。"""
    raw = str(region or "").strip()
    if not raw:
        with _enrich_lock:
            raw = str(_enrich_job.get("currentRegion") or "").strip()
    if not raw:
        return "_all"
    from app.core.region_meta import REGION_META

    if raw in REGION_META:
        return raw
    for rid, m in REGION_META.items():
        if raw == str(m.get("label") or "").strip():
            return rid
    # 短名：有码 → 日本有码
    for rid, m in REGION_META.items():
        label = str(m.get("label") or "")
        if label.endswith(raw) or raw in label:
            return rid
    return raw


def _persist_enrich_log(region: str, text: str) -> None:
    """刮削日志落元库，重启后仍可查。"""
    rid = _canonical_enrich_log_region(region)
    line = str(text or "").strip()
    if not line:
        return
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            conn.execute(
                "INSERT INTO enrich_logs (region, line) VALUES (?, ?)",
                (rid, line[:2000]),
            )
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
    except Exception as e:  # noqa: BLE001
        log.warning("persist enrich log failed region=%s: %s", rid, e)


def load_enrich_logs(*, region: str = "", limit: int = 200) -> list[str]:
    rid = str(region or "").strip()
    lim = max(1, min(int(limit or 200), 500))
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if rid:
                keys = _enrich_log_region_keys(rid)
                # 多键合并后按 id 排序取尾
                placeholders = ",".join(["?"] * len(keys))
                rows = conn.execute(
                    f"""
                    SELECT line FROM enrich_logs
                    WHERE region IN ({placeholders})
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (*keys, lim),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT line FROM enrich_logs
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (lim,),
                ).fetchall()
        out = [
            str((r.get("line") if isinstance(r, dict) else r[0]) or "")
            for r in (rows or [])
        ]
        out.reverse()
        return [x for x in out if x]
    except Exception as e:  # noqa: BLE001
        log.warning("load enrich logs failed: %s", e)
        return []


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


def _clear_enrich_logs(*, region: str = "") -> None:
    """停止时清分区运行日志（内存 + 元库）；暂停绝不能调用。"""
    rid = str(region or "").strip()
    keys = _enrich_log_region_keys(rid) if rid else []
    with _enrich_lock:
        if rid:
            region_logs = dict(_enrich_job.get("regionLogs") or {})
            for k in keys:
                region_logs.pop(k, None)
            # 当前分区停止时顺带清空全局尾日志，避免 UI 回退到 st.log
            cur = str(_enrich_job.get("currentRegion") or "").strip()
            if not cur or cur == rid or cur in keys or _canonical_enrich_log_region(cur) == _canonical_enrich_log_region(rid):
                _enrich_job["log"] = []
            _enrich_job["regionLogs"] = region_logs
        else:
            _enrich_job["regionLogs"] = {}
            _enrich_job["log"] = []
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if rid:
                for k in keys:
                    conn.execute("DELETE FROM enrich_logs WHERE region = ?", (k,))
                # 兼容历史脏键 + 无分区时落到 _all 的尾日志
                canon = _canonical_enrich_log_region(rid)
                conn.execute("DELETE FROM enrich_logs WHERE region = ?", (canon,))
                conn.execute("DELETE FROM enrich_logs WHERE region = ?", ("_all",))
            else:
                conn.execute("DELETE FROM enrich_logs")
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("clear enrich logs failed region=%s: %s", rid or "*", e)


def _queue_counts_of(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"pending": 0, "running": 0, "done": 0, "fail": 0}
    for row in rows:
        if not isinstance(row, dict):
            continue
        st = str(row.get("status") or "pending").strip().lower()
        if st not in counts:
            st = "pending"
        counts[st] += 1
    return counts


def _slim_queue_for_status(
    queue_full: list[dict[str, Any]], *, limit: int = 120
) -> list[dict[str, Any]]:
    """状态轮询只带回抽样队列，避免 5 万+ 条 JSON 卡死进度。"""
    if len(queue_full) <= limit:
        return queue_full
    running = [r for r in queue_full if str(r.get("status") or "") == "running"]
    pending = [r for r in queue_full if str(r.get("status") or "pending") in {"pending", ""}]
    fail = [r for r in queue_full if str(r.get("status") or "") == "fail"]
    done = [r for r in queue_full if str(r.get("status") or "") == "done"]
    # 当前 + 未处理头 + 最近失败/成功
    out: list[dict[str, Any]] = []
    out.extend(running[:8])
    out.extend(pending[:48])
    out.extend(fail[-32:])
    out.extend(done[-32:])
    # 去重保序
    seen: set[str] = set()
    slim: list[dict[str, Any]] = []
    for row in out:
        key = str(row.get("itemId") or row.get("code") or id(row))
        if key in seen:
            continue
        seen.add(key)
        slim.append(row)
        if len(slim) >= limit:
            break
    return slim


def _progress_from_queue_counts(
    counts: dict[str, int], *, base: dict[str, Any] | None = None
) -> dict[str, Any]:
    """进度只跟本轮队列计数对齐（成功+失败）/（成功+失败+未处理）。"""
    fin = int(counts.get("done") or 0) + int(counts.get("fail") or 0)
    rem = int(counts.get("pending") or 0) + int(counts.get("running") or 0)
    tot = fin + rem
    cur = dict(base or {})
    cur.update(
        {
            "done": fin,
            "total": tot,
            "ok": int(counts.get("done") or 0),
            "failed": int(counts.get("fail") or 0),
            "percent": _enrich_percent(fin, tot) if tot > 0 else 0,
        }
    )
    return cur


def get_enrich_status() -> dict[str, Any]:
    with _enrich_lock:
        region_logs_raw = _enrich_job.get("regionLogs") or {}
        region_logs: dict[str, list[str]] = {}
        region_log_counts: dict[str, int] = {}
        if isinstance(region_logs_raw, dict):
            for rid, lines in region_logs_raw.items():
                key = str(rid or "").strip()
                if not key:
                    continue
                full = list(lines or [])
                region_log_counts[key] = len(full)
                region_logs[key] = full[-_ENRICH_LOG_RETURN:]
        checkpoints = _checkpoint_summaries()
        halt = _enrich_job.get("halt")
        current_region = str(_enrich_job.get("currentRegion") or "")
        running = bool(_enrich_job["running"])
        queue_full = [
            dict(r) for r in list(_enrich_job.get("queue") or []) if isinstance(r, dict)
        ]
        # 每次按全量队列重算（快）；瓶颈是 JSON 体积，不是计数
        queue_counts = _queue_counts_of(queue_full)
        # 暂停后若运行时队列被置空，用检查点剩余队列回填展示（停止则无检查点）
        if not running and not queue_full:
            raw_cps = dict(_enrich_job.get("checkpoints") or {})
            for rid, cp in raw_cps.items():
                if not isinstance(cp, dict):
                    continue
                remaining = list(cp.get("queue") or [])
                if not remaining:
                    continue
                done = int(cp.get("done") or 0)
                rebuilt: list[dict[str, Any]] = []
                for j, row in enumerate(remaining):
                    if not isinstance(row, dict):
                        continue
                    rebuilt.append(
                        {
                            "index": done + j,
                            "itemId": str(row.get("itemId") or ""),
                            "code": str(row.get("code") or ""),
                            "gaps": list(row.get("gaps") or []),
                            "status": "pending",
                        }
                    )
                if rebuilt:
                    queue_full = rebuilt
                    queue_counts = _queue_counts_of(rebuilt)
                break
        progress = _progress_from_queue_counts(
            queue_counts, base=dict(_enrich_job.get("progress") or {})
        )
        if running:
            _enrich_job["progress"] = progress
            _enrich_job["queueCounts"] = queue_counts
        queue = _slim_queue_for_status(queue_full)
        status = {
            "running": running,
            "phase": _enrich_job.get("phase") or "",
            "progress": progress,
            "log": list(_enrich_job.get("log") or [])[-40:],
            "regionLogs": region_logs,
            "regionLogCounts": region_log_counts,
            "currentRegion": current_region,
            "cancel": bool(_enrich_job.get("cancel")) or halt in {"pause", "stop"},
            "halt": halt,
            "paused": bool(checkpoints),
            "checkpoints": checkpoints,
            "queue": queue,
            "queueTotal": sum(int(queue_counts.get(k) or 0) for k in ("pending", "running", "done", "fail")),
            "queueCounts": queue_counts,
            "queueTruncated": len(queue_full) > len(queue),
            "current": _enrich_job.get("current"),
            "result": _enrich_job.get("result"),
            "error": _enrich_job.get("error"),
        }

    # 元库回填：仅空闲时合并历史；运行中只用本轮内存，避免角标被历史顶满
    try:
        from app.core.region_meta import REGION_ORDER

        if not running:
            want_regions = set(region_logs.keys()) | set(REGION_ORDER)
            if current_region:
                want_regions.add(current_region)
            for rid in want_regions:
                key = _canonical_enrich_log_region(str(rid or "").strip())
                if not key or key == "_all":
                    continue
                loaded = load_enrich_logs(region=key, limit=_ENRICH_LOG_RETURN)
                mem = list(region_logs.get(key) or [])
                for alias in _enrich_log_region_keys(key):
                    if alias == key:
                        continue
                    for line in list(region_logs.get(alias) or []):
                        if not line:
                            continue
                        if mem and mem[-1] == line:
                            continue
                        mem.append(line)
                if loaded and mem:
                    merged = list(loaded)
                    for line in mem:
                        if merged and merged[-1] == line:
                            continue
                        merged.append(line)
                    region_logs[key] = merged[-_ENRICH_LOG_RETURN:]
                elif loaded:
                    region_logs[key] = loaded[-_ENRICH_LOG_RETURN:]
                elif mem:
                    region_logs[key] = mem[-_ENRICH_LOG_RETURN:]
                region_log_counts[key] = len(region_logs.get(key) or [])
            if not status["log"]:
                loaded_all = load_enrich_logs(region="_all", limit=80)
                if loaded_all:
                    status["log"] = loaded_all[-40:]
        status["regionLogs"] = region_logs
        status["regionLogCounts"] = region_log_counts
    except Exception:  # noqa: BLE001
        pass
    return status


def _set_current_region(region_id: str = "") -> None:
    with _enrich_lock:
        _enrich_job["currentRegion"] = str(region_id or "").strip()


def _set_queue(rows: list[dict[str, Any]]) -> None:
    """写入完整处理队列；状态接口只抽样回传。"""
    with _enrich_lock:
        cleaned = [dict(r) for r in (rows or []) if isinstance(r, dict)]
        _enrich_job["queue"] = cleaned
        _enrich_job["queueCounts"] = _queue_counts_of(cleaned)


def _patch_queue_item(index: int, **fields: Any) -> None:
    with _enrich_lock:
        queue = list(_enrich_job.get("queue") or [])
        if 0 <= index < len(queue):
            row = dict(queue[index] or {})
            old_st = str(row.get("status") or "pending").strip().lower()
            if old_st not in {"pending", "running", "done", "fail"}:
                old_st = "pending"
            row.update(fields)
            new_st = str(row.get("status") or "pending").strip().lower()
            if new_st not in {"pending", "running", "done", "fail"}:
                new_st = "pending"
            queue[index] = row
            _enrich_job["queue"] = queue
            counts = dict(_enrich_job.get("queueCounts") or {}) or _queue_counts_of(queue)
            if old_st != new_st:
                counts[old_st] = max(0, int(counts.get(old_st) or 0) - 1)
                counts[new_st] = int(counts.get(new_st) or 0) + 1
            for k in ("pending", "running", "done", "fail"):
                counts[k] = int(counts.get(k) or 0)
            _enrich_job["queueCounts"] = counts
            # 同步进度，避免轮询间隙 percent 乱跳
            base = dict(_enrich_job.get("progress") or {})
            _enrich_job["progress"] = _progress_from_queue_counts(counts, base=base)


def _set_current(payload: dict[str, Any] | None) -> None:
    with _enrich_lock:
        _enrich_job["current"] = payload


def _detail_field_rows(detail: dict[str, Any] | None) -> list[dict[str, Any]]:
    """E2E 风格字段表：是否采到 + 预览值。"""
    d = detail if isinstance(detail, dict) else {}
    actors = [str(a).strip() for a in (d.get("actors") or []) if str(a).strip()]
    tags = [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()]
    title = str(d.get("title") or "").strip()
    studio = str(d.get("studio") or d.get("maker") or "").strip()
    overview = str(d.get("overview") or "").strip()
    poster = str(d.get("posterUrl") or d.get("poster") or "").strip()
    year = str(d.get("year") or "").strip()
    date_s = str(d.get("date") or "").strip()
    code = str(d.get("code") or d.get("id") or "").strip().upper()

    def row(fid: str, label: str, ok: bool, value: str = "") -> dict[str, Any]:
        return {
            "id": fid,
            "label": label,
            "ok": bool(ok),
            "value": (value or "")[:120],
        }

    return [
        row("code", "番号", bool(code), code),
        row("title", "标题", bool(title) and title.casefold() != code.casefold(), title),
        row("actors", "女优", bool(actors), "、".join(actors[:6])),
        row("studio", "片商", bool(studio), studio),
        row("overview", "剧情", bool(overview), overview[:80]),
        row(
            "poster",
            "封面",
            poster.startswith(("http://", "https://")),
            poster,
        ),
        row("year", "年份", bool(year), year),
        row("date", "日期", bool(date_s), date_s),
        row("tags", "标签", bool(tags), "、".join(tags[:8])),
    ]


def _halt_kind() -> str | None:
    with _enrich_lock:
        halt = _enrich_job.get("halt")
        if halt in {"pause", "stop"}:
            return str(halt)
        if _enrich_job.get("cancel"):
            # 旧 cancel 视为暂停（保留进度）
            return "pause"
        return None


def _is_cancelled() -> bool:
    """兼容旧名：收到 pause/stop 都视为应中断循环。"""
    return _halt_kind() is not None


def _save_checkpoint(region: str, payload: dict[str, Any]) -> None:
    rid = str(region or "").strip()
    if not rid:
        return
    with _enrich_lock:
        cps = dict(_enrich_job.get("checkpoints") or {})
        cps[rid] = dict(payload or {})
        _enrich_job["checkpoints"] = cps


def _clear_checkpoint(region: str = "") -> None:
    rid = str(region or "").strip()
    with _enrich_lock:
        if not rid:
            _enrich_job["checkpoints"] = {}
            return
        cps = dict(_enrich_job.get("checkpoints") or {})
        cps.pop(rid, None)
        _enrich_job["checkpoints"] = cps


def _take_checkpoint(region: str) -> dict[str, Any] | None:
    rid = str(region or "").strip()
    if not rid:
        return None
    with _enrich_lock:
        cps = dict(_enrich_job.get("checkpoints") or {})
        raw = cps.pop(rid, None)
        _enrich_job["checkpoints"] = cps
    return dict(raw) if isinstance(raw, dict) else None


def _peek_checkpoint(region: str) -> dict[str, Any] | None:
    rid = str(region or "").strip()
    if not rid:
        return None
    with _enrich_lock:
        raw = (dict(_enrich_job.get("checkpoints") or {})).get(rid)
    return dict(raw) if isinstance(raw, dict) else None


def request_enrich_pause() -> dict[str, Any]:
    """暂停：停在当前番号后，保留剩余队列与日志，再开继续。"""
    with _enrich_lock:
        if not _enrich_job.get("running"):
            return {"ok": True, "paused": False, "running": False}
        _enrich_job["halt"] = "pause"
        _enrich_job["cancel"] = True
        _enrich_job["phase"] = "pausing"
        cur = dict(_enrich_job.get("progress") or {})
        cur["label"] = "正在暂停…"
        _enrich_job["progress"] = cur
    _push_log("收到暂停请求 · 保留进度")
    return {"ok": True, "paused": True, "running": True}


def request_enrich_stop(*, region: str = "") -> dict[str, Any]:
    """停止：清除队列/检查点/当前任务/日志，下次从头开始。"""
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
            cur["label"] = "已清除"
            cur["stage"] = "cleared"
            cur["done"] = 0
            cur["total"] = 0
            cur["percent"] = 0
            _enrich_job["progress"] = cur
            _enrich_job["phase"] = "cleared"
            _enrich_job["result"] = None
    # 立刻清日志（含历史脏键），UI 马上变空；halt=stop 后也不再写入
    _clear_enrich_logs(region=rid)
    log.info(
        "enrich stop%s running=%s",
        f" region={rid}" if rid else "",
        running,
    )
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


def request_enrich_cancel() -> dict[str, Any]:
    """兼容旧接口：等同暂停（保留进度）。"""
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


def _enrich_percent(done: int, total: int) -> int:
    """按已完成条数映射 0–100；不再人为从 10% 起跳。"""
    t = int(total or 0)
    if t <= 0:
        return 0
    d = max(0, min(int(done or 0), t))
    if d >= t:
        return 100
    return max(0, min(99, int(round(100.0 * d / t))))


def _detail_sources(*, region: str = "") -> list[dict[str, Any]]:
    """数据源页：七区对应分组 ∩ 已启用 ∩ 有详情实现，按目录顺序。"""
    import app.scrape.sources_settings as scrape_src

    return list(scrape_src.enabled_enrich_sources(region=region) or [])


def _poster_rank(url: str) -> int:
    """封面 URL 质量：DMM CDN > mono/pl > 其它；慢图床垫底。"""
    u = str(url or "").strip().lower()
    if not u.startswith(("http://", "https://")):
        return 0
    # javbus/seejav 图床常超时，仅作末位兜底
    if "javbus.com" in u or "seejav." in u:
        return 0
    # E2E 实测最终成功几乎全是 DMM；优先试，避免 airav/fourhoi 抢先拖慢
    if "dmm.co.jp" in u or "awsimgsrc.dmm." in u:
        if "/mono/movie/" in u:
            return 8
        if u.endswith("pl.jpg") or "/pics_dig/" in u or "pl.jpg" in u:
            return 7
        return 6
    if "/mono/movie/" in u:
        return 5
    if "jdbstatic.com/covers" in u:
        return 4
    # airav/fourhoi/123av 的 /cover 易慢，勿压过 DMM pl
    if "airav.io" in u or "fourhoi.com" in u or "123av.me" in u:
        return 1
    if u.endswith("pl.jpg") or "_b.jpg" in u or "bigImage" in u:
        return 3
    if "/cover" in u:
        return 2
    # DMM digital 常返回很小的空图，合并时勿压过 mono
    if "/digital/video/" in u:
        return 1
    return 2


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", str(text or "")))


def _has_kana(text: str) -> bool:
    """平假名 / 片假名 → 日文痕迹（忽略间隔号・･）。"""
    t = str(text or "").replace("・", "").replace("･", "")
    return bool(re.search(r"[\u3040-\u309f\u30a0-\u30ff]", t))


_TRAD_HINT_RE = re.compile(r"[體後國興專質畫婦獨數碼溫亂戀顏觀恥縛緊嗎麼萬與幹]")


def _has_traditional(text: str) -> bool:
    return bool(_TRAD_HINT_RE.search(str(text or "")))


def _has_han(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


def _zh_prefer_bonus(text: str) -> int:
    """中文（含繁体）优先；带假名的日文不加分。

    加成需压过高 trust 日文源（如 airav_io title trust≈98 vs miss_av≈69）。
    """
    t = str(text or "").strip()
    if not t:
        return 0
    if _has_kana(t):
        return 0
    if _has_han(t):
        return 40
    return 0


def _normalize_merged_title(value: str) -> str:
    """中文标题收尾：修正「…。 2」类系列序号，去掉易被当成脏数据的孤立尾号。"""
    s = str(value or "").strip()
    if not s:
        return s
    # 碟版尾巴
    s = re.sub(r"\s*[\(（]\s*DOD\s*[\)）]\s*$", "", s, flags=re.I).strip()
    # 「出手了…。 2」→「出手了… 2」（句号误夹在系列序号前）
    s = re.sub(r"([…⋯]?)\s*[。．.]\s*(\d{1,2})\s*$", r"\1 \2", s)
    # MGS 附赠尾巴
    s = re.sub(
        r"\s*[\[【(（]?[^\[】)\]]*MGS[^\]】)\]]*[\]】)）]?",
        "",
        s,
        flags=re.I,
    )
    s = re.sub(r"\s+", " ", s).strip()
    # 纯中文标题：去掉末尾孤立「 2」「 10」——日文官名常带卷号，中译再挂尾号易像刮削残留；
    # 剧情里通常已有「第N弹」。保留日文标题原样。
    if _zh_prefer_bonus(s) > 0 and not _has_kana(s):
        trimmed = re.sub(r"\s+\d{1,2}$", "", s).strip()
        if len(trimmed) >= 12:
            s = trimmed
    return s


def _normalize_merged_overview(value: str) -> str:
    """剧情轻量清洗：叠词、标点前空白。"""
    s = str(value or "").strip()
    if not s:
        return s
    # 乳头乳头 / 看看看 → 单次
    s = re.sub(r"([\u4e00-\u9fff]{2,6})\1+", r"\1", s)
    s = re.sub(r"\s+([？?！!。．、,，])", r"\1", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def _mt_junk_penalty(text: str) -> int:
    """机翻垃圾：字面硬译/英日碎片/审查符残留 → 让日文官名胜出。"""
    t = str(text or "").strip()
    if not t:
        return 0
    pen = 0
    if any(
        x in t
        for x in (
            "男孩子女孩",
            "男声女儿",
            "男孩子女孩女演员",
            "男の娘女演员",
        )
    ):
        pen -= 55
    if re.search(r"penikuri", t, re.I):
        pen -= 40
    # 中文剧情里残留 ○ 审查或 ma ○ co
    if _has_han(t) and ("○" in t or "●" in t):
        pen -= 35
    # 「中文」里塞太多拉丁片段（Cosplay/SEX 除外也照罚）
    if _has_han(t) and not _has_kana(t):
        latin_n = len(re.findall(r"[A-Za-z]", t))
        if latin_n >= 10:
            pen -= min(36, 12 + latin_n)
    # 女优名乱译打架的弱信号：同一段里多种「莫莫/麻里/桃麻」混用
    name_hits = sum(
        1
        for x in ("莫莫里", "麻里莫莫", "莫莫玛丽", "桃麻里", "麻里桃", "桃玛莉")
        if x in t
    )
    if name_hits >= 2:
        pen -= 20
    return pen


def _score_title(value: str, *, code: str, source_id: str) -> int:
    import app.scrape.source_catalog as catalog

    t = str(value or "").strip()
    if not t:
        return -10_000
    score = catalog.field_trust(source_id, "title")
    if _title_is_thin(t, code):
        score -= 55
    else:
        score += 12
    n = len(t)
    if 6 <= n <= 90:
        score += 8
    elif n > 120:
        score -= 8
    score += _zh_prefer_bonus(t)
    score += _mt_junk_penalty(t)
    # 日文标题可用但不额外加分，避免压过中文候选
    # 剥离 DOD 碟版尾巴后更干净
    if re.search(r"\（?\s*DOD\s*\）?|\(DOD\)", t, re.I):
        score -= 6
    return score


def _overview_foreign_actress_penalty(
    text: str, *, allowed_actors: list[str] | None
) -> int:
    """剧情串台：文中出现映射表里的「另一女优」且不在本片女优名单 → 重罚。"""
    t = str(text or "").strip()
    if not t or not allowed_actors:
        return 0
    try:
        from app.scrape.metadata_optimize import (
            _actor_maps,
            _actor_should_drop,
            _lookup_actor_hit,
            _map_actor_entry,
            mapping_language_from_settings,
        )
    except Exception:  # noqa: BLE001
        return 0

    table = _actor_maps(mapping_language_from_settings())
    allowed: set[str] = set()
    for a in allowed_actors:
        s = str(a or "").strip()
        if not s:
            continue
        allowed.add(s)
        allowed.add(s.casefold())
        try:
            mapped, _ = _map_actor_entry(s, table)
            if mapped:
                allowed.add(mapped)
                allowed.add(mapped.casefold())
        except Exception:  # noqa: BLE001
            pass

    def _is_allowed(nm: str) -> bool:
        if nm in allowed or nm.casefold() in allowed:
            return True
        try:
            mapped, _ = _map_actor_entry(nm, table)
        except Exception:  # noqa: BLE001
            mapped = ""
        if mapped and (mapped in allowed or mapped.casefold() in allowed):
            return True
        return any(nm in a or a in nm for a in allowed if len(str(a)) >= 2)

    # 在连续汉字串上滑窗 3～4 字查映射，避免全文扫 1 万名字
    for run in re.findall(r"[\u4e00-\u9fff]{3,}", t):
        for length in (4, 3):
            if len(run) < length:
                continue
            for i in range(0, len(run) - length + 1):
                nm = run[i : i + length]
                hit = _lookup_actor_hit(nm, table)
                if hit is None or _actor_should_drop(hit):
                    continue
                if _is_allowed(nm):
                    continue
                return -90
    return 0


def _score_overview(
    value: str,
    *,
    source_id: str,
    allowed_actors: list[str] | None = None,
) -> int:
    import app.scrape.source_catalog as catalog

    t = str(value or "").strip()
    if not t:
        return -10_000
    score = catalog.field_trust(source_id, "overview")
    n = len(t)
    if n < 12:
        score -= 40
    elif n >= 100:
        score += 18
    elif n >= 40:
        score += 12
    elif n >= 20:
        score += 6
    score += _zh_prefer_bonus(t)
    low = t.casefold()
    # 站点水印 / 伪剧情（「番号 标题 - airav.io」一类空壳直接淘汰）
    if any(
        x in low
        for x in (
            "http://",
            "https://",
            "点击",
            "加微信",
            "telegram",
            "airav.io",
            "iqqtv",
            "missav",
            "コンビニ受取",
            "詳しくはこちら",
        )
    ):
        return -10_000
    # 「番号 标题 - 站名」一类空壳剧情
    if re.search(r"\s-\s*[a-z0-9.-]+\s*$", t, flags=re.I) and n < 80:
        return -10_000
    # 「EVO-073 职业女人 34」无正文、几乎等于标题
    if n < 48 and re.match(r"^[A-Z0-9]+-\d+\b", t, flags=re.I):
        score -= 45
    score += _overview_foreign_actress_penalty(t, allowed_actors=allowed_actors)
    score += _mt_junk_penalty(t)
    return score


def _score_studio(value: str, *, source_id: str) -> int:
    import app.scrape.source_catalog as catalog

    t = str(value or "").strip()
    if not t:
        return -10_000
    score = catalog.field_trust(source_id, "studio")
    if 2 <= len(t) <= 40:
        score += 6
    if _has_cjk(t) or re.search(r"[A-Za-z]", t):
        score += 2
    return score


def _score_date(value: str, *, source_id: str) -> int:
    import app.scrape.source_catalog as catalog

    t = str(value or "").strip()
    if not t:
        return -10_000
    score = catalog.field_trust(source_id, "date")
    if re.match(r"^\d{4}-\d{2}-\d{2}", t):
        score += 16
    elif re.match(r"^\d{4}/\d{1,2}/\d{1,2}", t):
        score += 10
    return score


def _score_year(value: str, *, source_id: str) -> int:
    import app.scrape.source_catalog as catalog

    t = str(value or "").strip()
    if not t:
        return -10_000
    score = catalog.field_trust(source_id, "year")
    if re.match(r"^(19|20)\d{2}$", t):
        score += 12
    return score


def _score_actors(names: list[str] | None, *, source_id: str) -> int:
    import app.scrape.source_catalog as catalog

    actors = _clean_actors(names)
    if not actors:
        return -10_000
    score = catalog.field_trust(source_id, "actors")
    n = len(actors)
    if 1 <= n <= 4:
        score += 16
    elif 5 <= n <= 8:
        score += 6
    elif n > 12:
        score -= 12
    if any(_has_cjk(a) for a in actors):
        score += 12
    return score


def _score_poster(url: str, *, source_id: str) -> int:
    import app.scrape.source_catalog as catalog

    u = str(url or "").strip()
    if not u.startswith(("http://", "https://")):
        return -10_000
    return catalog.field_trust(source_id, "poster") + _poster_rank(u) * 12


def _score_tags(tags: list[str] | None, *, source_id: str) -> int:
    """标签列表分：站点 trust + 中文优先（对齐标题/剧情）。

    含假名的日文标签降权；纯汉字/汉+拉丁列表加权。
    """
    import app.scrape.source_catalog as catalog

    cleaned = [str(t).strip() for t in (tags or []) if str(t or "").strip()]
    if not cleaned:
        return -10_000
    score = catalog.field_trust(source_id, "tags")
    n = len(cleaned)
    if n >= 4:
        score += 6
    elif n >= 2:
        score += 3
    else:
        score -= 2
    zh_n = sum(1 for t in cleaned if _zh_prefer_bonus(t) > 0)
    kana_n = sum(1 for t in cleaned if _has_kana(t))
    trad_n = sum(1 for t in cleaned if _has_traditional(t))
    # 中文优先：比旧版 max+8 更强，能压过「日文源条数略多」
    if zh_n:
        score += min(24, zh_n * 3)
    if kana_n:
        score -= min(16, kana_n * 3)
    # 繁体标签略降，让简中源（airav/iqqtv/miss_av）优先于 javbus 繁中
    if trad_n:
        score -= min(14, trad_n * 2)
    if cleaned and kana_n == 0 and trad_n == 0 and zh_n >= max(2, (n + 1) // 2):
        score += 12
    elif cleaned and kana_n == 0 and zh_n >= max(2, (n + 1) // 2):
        score += 6
    return score


def _normalize_tag_alias(tag: str) -> str:
    """优先走 tags.zh-CN.json；无表时原样返回。"""
    t = str(tag or "").strip()
    if not t:
        return ""
    try:
        from app.scrape.metadata_optimize import polish_tag_names

        out = polish_tag_names([t])
        return out[0] if out else ""
    except Exception:  # noqa: BLE001
        import unicodedata

        return unicodedata.normalize("NFKC", t)


def _pick_best_str(
    candidates: list[tuple[str, str, int]],
) -> tuple[str, str] | None:
    """candidates: (source_id, value, score) → (value, source_id)."""
    best: tuple[str, str, int] | None = None
    for sid, val, score in candidates:
        if not str(val or "").strip():
            continue
        if best is None or score > best[2]:
            best = (sid, str(val).strip(), score)
    if best is None:
        return None
    return best[1], best[0]


def _strategy_field_priority(field: str) -> list[str] | None:
    try:
        from app.scrap_library.enrich_strategy import get_strategy

        fp = get_strategy().get("fieldPriority") or {}
        chain = fp.get(field) if isinstance(fp, dict) else None
        if isinstance(chain, list) and chain:
            return [str(x) for x in chain]
    except Exception:  # noqa: BLE001
        pass
    return None


def _pick_by_field_priority(
    candidates: list[tuple[str, str, int]],
    field: str,
    *,
    min_score: int | None = None,
) -> tuple[str, str] | None:
    """对齐 Amane：沿字段优先级链取第一个合格非空；未命中再回落最高分。

    质量门槛：若给定 min_score，链上低分候选跳过（继续下一站），避免 junk 占位。
    """
    import app.scrape.source_catalog as catalog

    usable = [
        (catalog.canonicalize_id(sid), str(val or "").strip(), int(score))
        for sid, val, score in candidates
        if str(val or "").strip()
    ]
    if not usable:
        return None

    by_sid: dict[str, list[tuple[str, int]]] = {}
    for sid, val, score in usable:
        by_sid.setdefault(sid, []).append((val, score))

    best_score = max(sc for _s, _v, sc in usable)
    chain = catalog.field_priority_chain(
        field, override=_strategy_field_priority(field)
    )
    for sid in chain:
        for val, score in by_sid.get(sid) or []:
            if min_score is not None and score < min_score:
                continue
            # 明显劣于最优则跳过（烂机翻不靠链抢占官名）
            # 标题中文池更严：长机翻常只低 10～20 分，旧 -35 挡不住
            # 剧情：链只裁决「近似平手」——分数里已含源站信任 + 长度 + 中文加成，
            # 放宽到 35 会让链首用一段明显更短的剧情反超高分长文
            # （KUSE-029：miss_av@119 len=56 反压 sevenmmtv@126 len=104）。
            if field == "title":
                margin = 8
            elif field == "overview":
                margin = 5
            else:
                margin = 35
            if field == "overview" and score < 0:
                continue
            if best_score - score > margin:
                continue
            return val, sid

    # 链外源 / 全被门槛跳过 → 回落最高分
    return _pick_best_str(usable)


def _actor_hints_from_titles(titles: list[str]) -> list[str]:
    """从候选标题提取可能的女优名（×对 + 尾名），供身份门禁对齐中日标题。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in titles:
        t = str(raw or "").strip()
        if not t:
            continue
        for n in _names_from_title_pairs(t):
            if n not in seen:
                seen.add(n)
                out.append(n)
        # 去 MGS 尾巴后再取末尾人名
        t2 = re.sub(r"[\[【(（].*$", "", t).strip()
        m = re.search(
            r"[\s　]([\u4e00-\u9fffぁ-んァ-ン]{2,8})\s*$",
            t2,
        )
        if m:
            n = m.group(1).strip()
            if len(n) >= 2 and n not in seen and n not in {"Vol", "SOD"}:
                seen.add(n)
                out.append(n)
    return out


def _identity_gate_details(
    code: str,
    details: list[tuple[str, dict[str, Any]]],
) -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """身份门禁（对齐 MDCX：不对的整页不进字段池）。

    返回 (kept_details, rejected_source_ids)。
    错页源仍可贡献封面 URL，但清空 title/overview/actors/tags。
    """
    if not details:
        return [], []

    code_u = str(code or "").strip().upper()
    prelim: list[tuple[str, dict[str, Any], bool]] = []
    for sid, d in details:
        dd = dict(d)
        usable = _detail_usable(dd, code=code_u)
        title = str(dd.get("title") or "").strip()
        weak = (not usable) or _title_is_thin(title, code_u)
        prelim.append((sid, dd, weak))

    title_scores: list[tuple[str, str, int]] = []
    for sid, d, weak in prelim:
        if weak:
            continue
        t = str(d.get("title") or "").strip()
        if not t:
            continue
        title_scores.append(
            (sid, t, _score_title(t, code=code_u, source_id=sid))
        )
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        tzh = str((extra or {}).get("titleZh") or "").strip()
        if tzh and tzh != t:
            title_scores.append(
                (sid, tzh, _score_title(tzh, code=code_u, source_id=sid))
            )

    if len(title_scores) < 2:
        return [(sid, d) for sid, d, _ in prelim], []

    title_scores.sort(key=lambda x: -x[2])
    seed = title_scores[0][1]
    # 簇多数防错页抢锚（RBD-035：airav/airav_io/iqqtv 镜像同一错页且分最高，
    # 旧 seed=纯最高分 → 7 家真源被整批拒、合并锚定到错页片）。
    # 贪心聚簇（按分数序入簇，簇代表=簇内最高分题）；仅当最大簇比种子所在簇
    # 多 ≥2 个源时才改用最大簇内最高分为种子，差距小则维持旧行为（SCPX-287：
    # 单源中文意译 vs 2 源官名，不换锚，仍由「≥2 源同题日文作第二锚」兜底）。
    _all_hints = _actor_hints_from_titles([t for _s, t, _c in title_scores])
    _extra_anchor = ""
    _clusters: list[list[tuple[str, str, int]]] = []
    for _sid, _t, _sc in title_scores:
        for _cl in _clusters:
            if _titles_compatible(_t, _cl[0][1], actors=_all_hints):
                _cl.append((_sid, _t, _sc))
                break
        else:
            _clusters.append([(_sid, _t, _sc)])
    if len(_clusters) >= 2:
        _seed_cl = next(
            (c for c in _clusters if any(m[1] == seed for m in c)),
            None,
        )
        _top = max(_clusters, key=lambda c: len({m[0] for m in c}))
        if (
            _seed_cl is not None
            and _top is not _seed_cl
            and len({m[0] for m in _top}) - len({m[0] for m in _seed_cl}) >= 2
        ):
            # 换锚前先判「同片证据」：旧种子簇与新种子簇的女优名单有交集 →
            # 旧种子只是同一部片的烂机翻（FAX-185 miss_av），换锚后要把它
            # 保留为附加锚；零交集才是真错页（RBD-035 滩纯 vs 翔田千里）。
            try:
                _fold = _fold_variant
            except NameError:
                from app.scrape.metadata_optimize import _fold_variant as _fold  # noqa: F401
            _acts_by_sid = {
                _sid: {
                    _fold(str(a).strip()).casefold()
                    for a in (_d.get("actors") or [])
                    if str(a or "").strip()
                }
                for _sid, _d, _w in prelim
            }
            _old_acts = set().union(
                *(_acts_by_sid.get(m[0] or "", set()) for m in _seed_cl)
            ) if _seed_cl else set()
            _new_acts = set().union(
                *(_acts_by_sid.get(m[0] or "", set()) for m in _top)
            )
            _overlap = bool(_old_acts & _new_acts)
            seed = _top[0][1]
            if _overlap:
                _extra_anchor = _seed_cl[0][1]
    # 锚点只能是 seed，以及与 seed 兼容的日文标题。
    # 禁止把不兼容的假名错页（如ジュポニカ）也塞进 anchors，否则错页自证通过。
    seed_hints = _actor_hints_from_titles([seed])
    anchors = [seed]
    for _sid, t, _sc in title_scores:
        if t == seed or not _has_kana(t):
            continue
        if _titles_compatible(t, seed, actors=seed_hints):
            anchors.append(t)
            break
    # 簇换锚但有「同片证据」（女优重叠）时保留的旧种子锚（FAX-185 miss_av 烂机翻）
    if _extra_anchor and all(_extra_anchor != a for a in anchors):
        anchors.append(_extra_anchor)
    # 中文自由译常与日文官名零交集：尚未挂日文锚时，用 ≥2 源同题日文作第二锚，
    # 避免误杀女优（案例 SCPX-287 传播妹意译 vs マドンナ官名）。
    if not any(_has_kana(a) for a in anchors):
        from collections import Counter

        def _jp_title_key(t: str) -> str:
            s = re.sub(r"\s*[（(]\s*DOD\s*[）)]\s*$", "", str(t or "").strip(), flags=re.I)
            return s

        jp_votes: Counter[str] = Counter()
        jp_sample: dict[str, str] = {}
        for _sid, t, _sc in title_scores:
            if not _has_kana(t):
                continue
            k = _jp_title_key(t)
            # 素人短官名（2～3 假名）也要能成簇，否则中文意译种子会误杀女优（MUKD-244）
            if len(k) < 2:
                continue
            jp_votes[k] += 1
            jp_sample.setdefault(k, t)
        for k, cnt in jp_votes.most_common(3):
            if cnt < 2:
                break
            anchors.append(jp_sample[k])
            break
    hints = _actor_hints_from_titles(
        [
            seed,
            *anchors,
            *[
                t
                for _s, t, _c in title_scores[:8]
                if _titles_compatible(t, seed, actors=seed_hints)
            ],
        ]
    )

    kept: list[tuple[str, dict[str, Any]]] = []
    rejected: list[str] = []
    for sid, d, weak in prelim:
        if weak:
            w = dict(d)
            w["title"] = ""
            w["overview"] = ""
            w["actors"] = []
            w["tags"] = []
            if isinstance(w.get("extra"), dict):
                ex = dict(w["extra"])
                ex.pop("titleZh", None)
                w["extra"] = ex
            kept.append((sid, w))
            continue
        t = str(d.get("title") or "").strip()
        if not t:
            kept.append((sid, d))
            continue
        ok = any(
            _titles_compatible(t, a, actors=hints) for a in anchors if a
        )
        if ok:
            kept.append((sid, d))
            continue
        rejected.append(sid)
        w = dict(d)
        w["title"] = ""
        w["overview"] = ""
        w["actors"] = []
        w["tags"] = []
        if isinstance(w.get("extra"), dict):
            ex = dict(w["extra"])
            ex.pop("titleZh", None)
            w["extra"] = ex
        kept.append((sid, w))
    return kept, rejected


def _merge_detail_fields(
    base: dict[str, Any], extra: dict[str, Any]
) -> dict[str, Any]:
    """兼容旧双路合并：委托字段级可信合并。"""
    sid_a = str(base.get("source") or (base.get("sources") or ["a"])[0] or "a")
    sid_b = str(extra.get("source") or extra.get("provider") or "b")
    fake_sources = [{"id": sid_a}, {"id": sid_b}]
    got = {sid_a: base, sid_b: extra}
    merged = _merge_got(fake_sources, got)
    return merged if merged is not None else dict(base)


def _merge_got(
    sources: list[dict[str, Any]], got: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """多源字段级可信合并：每字段取 trust+质量 最高；女优/标签并集。"""
    import app.scrape.source_catalog as catalog

    order_hit: list[str] = []
    details: list[tuple[str, dict[str, Any]]] = []
    for src in sources:
        raw_id = str(src.get("id") or "")
        sid = catalog.canonicalize_id(raw_id)
        detail = got.get(sid) or got.get(raw_id)
        if not detail:
            continue
        key = sid or raw_id
        order_hit.append(key)
        details.append((key, dict(detail)))
    if not details:
        # got 可能只按返回 id 存、sources 顺序不同：兜底遍历 got
        for sid, detail in got.items():
            if not detail:
                continue
            cid = catalog.canonicalize_id(str(sid))
            order_hit.append(cid)
            details.append((cid, dict(detail)))
    if not details:
        return None

    code = ""
    for _, d in details:
        code = str(d.get("code") or d.get("id") or "").strip().upper()
        if code:
            break

    details, rejected_ids = _identity_gate_details(code, details)
    if not details:
        return None

    title_cands: list[tuple[str, str, int]] = []
    studio_cands: list[tuple[str, str, int]] = []
    maker_cands: list[tuple[str, str, int]] = []
    overview_cands: list[tuple[str, str, int]] = []
    date_cands: list[tuple[str, str, int]] = []
    year_cands: list[tuple[str, str, int]] = []
    poster_cands_scored: list[tuple[str, str, int]] = []
    actor_lists: list[tuple[str, list[str], int]] = []
    tag_lists: list[tuple[str, list[str], int]] = []
    all_poster_urls: list[str] = []

    for sid, d in details:
        title = str(d.get("title") or "").strip()
        if title:
            title_cands.append((sid, title, _score_title(title, code=code, source_id=sid)))
        # 部分源（iqqtv）把中文标题放在 extra.titleZh
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        title_zh = str((extra or {}).get("titleZh") or "").strip()
        if title_zh and title_zh != title:
            title_cands.append(
                (sid, title_zh, _score_title(title_zh, code=code, source_id=sid))
            )
        studio = str(d.get("studio") or "").strip()
        if studio:
            studio_cands.append((sid, studio, _score_studio(studio, source_id=sid)))
        maker = str(d.get("maker") or d.get("studio") or "").strip()
        if maker:
            maker_cands.append(
                (sid, maker, catalog.field_trust(sid, "maker") + (6 if maker else 0))
            )
        overview = str(d.get("overview") or "").strip()
        if overview:
            # 先收集原文，女优定稿后再打分（防串台剧情）
            overview_cands.append((sid, overview, 0))
        date_s = str(d.get("date") or "").strip()
        if date_s:
            date_cands.append((sid, date_s, _score_date(date_s, source_id=sid)))
        year = str(d.get("year") or "").strip()
        if year:
            year_cands.append((sid, year, _score_year(year, source_id=sid)))
        poster = str(d.get("posterUrl") or d.get("poster") or "").strip()
        for u in list(d.get("posterCandidates") or []) + [poster]:
            s = str(u or "").strip()
            if s.startswith(("http://", "https://")) and s not in all_poster_urls:
                all_poster_urls.append(s)
        if poster.startswith(("http://", "https://")):
            poster_cands_scored.append(
                (sid, poster, _score_poster(poster, source_id=sid))
            )
        actors = _clean_actors(d.get("actors"))
        if actors:
            try:
                from app.scrape.metadata_optimize import polish_actress_names

                directors: list[str] = []
                d0 = str(d.get("director") or "").strip()
                if d0:
                    directors.append(d0)
                for raw_d in d.get("directors") or []:
                    if isinstance(raw_d, dict):
                        n = str(raw_d.get("name") or "").strip()
                    else:
                        n = str(raw_d or "").strip()
                    if n:
                        directors.append(n)
                actors = polish_actress_names(actors, exclude=directors)
            except Exception:  # noqa: BLE001
                pass
        if actors:
            actor_lists.append((sid, actors, _score_actors(actors, source_id=sid)))
        tags = [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()]
        if tags:
            tag_lists.append((sid, tags, _score_tags(tags, source_id=sid)))

    field_sources: dict[str, str] = {}
    merged: dict[str, Any] = {"code": code} if code else {}
    if rejected_ids:
        merged["identityRejected"] = list(rejected_ids)

    # 标量字段：字段优先级链首个合格非空（Amane）；女优仍用共识投票
    # 标题：有可用中文时跳过假名原文，避免 airav 等中文位源回落日文占链首、再烧 LLM
    title_pick_cands = title_cands
    usable_zh_titles = [
        (sid, t, sc)
        for sid, t, sc in title_cands
        if _zh_prefer_bonus(str(t or "")) > 0 and _mt_junk_penalty(str(t or "")) >= 0
    ]
    if usable_zh_titles:
        title_pick_cands = usable_zh_titles
    picked = _pick_by_field_priority(title_pick_cands, "title")
    if picked:
        title_v, title_src = picked
        merged["title"] = _normalize_merged_title(title_v)
        field_sources["title"] = title_src
    # 保留最佳日文标题，供机翻过烂时 LLM 回译（须与定稿标题兼容）
    jp_title_cands = [
        (sid, t, sc)
        for sid, t, sc in title_cands
        if _has_kana(str(t or ""))
    ]
    if jp_title_cands:
        jp_picked = _pick_by_field_priority(jp_title_cands, "title")
        ja = ""
        if jp_picked:
            ja = str(jp_picked[0] or "").strip()
        if not ja:
            jp_title_cands.sort(key=lambda x: -x[2])
            ja = str(jp_title_cands[0][1] or "").strip()
        final_t = str(merged.get("title") or "").strip()
        # 日文标题若有多源共识，则即便与「中文机翻定稿」措辞不同也采信：
        # 否则后续标题门禁会把全部日文源挡在标签/剧情合并之外，导致内容塌缩
        # （NSPS-015：定稿是 miss_av 机翻，titleJa 空 → 只剩 miss_av 的 3 个标签）。
        ja_votes = 0
        if ja:
            for _jid, _jt, _jsc in jp_title_cands:
                tt = str(_jt or "").strip()
                if not tt:
                    continue
                if tt == ja or _titles_compatible(
                    tt, ja, actors=_actor_hints_from_titles([tt, ja])
                ):
                    ja_votes += 1
        if ja and (
            not final_t
            or _has_kana(final_t)
            or _titles_compatible(ja, final_t, actors=_actor_hints_from_titles([ja, final_t]))
            or ja_votes >= 2
        ):
            merged["titleJa"] = ja
    picked = _pick_by_field_priority(studio_cands, "studio")
    if picked:
        merged["studio"], field_sources["studio"] = picked
    picked = _pick_by_field_priority(maker_cands, "maker")
    if picked:
        merged["maker"], field_sources["maker"] = picked
    elif merged.get("studio"):
        merged["maker"] = merged["studio"]
        field_sources["maker"] = field_sources.get("studio") or ""
    # overview 延后到女优共识后再选
    picked = _pick_by_field_priority(date_cands, "date")
    if picked:
        merged["date"], field_sources["date"] = picked
    picked = _pick_by_field_priority(year_cands, "year")
    if picked:
        merged["year"], field_sources["year"] = picked

    # 封面：候选按质量排序；主图沿 poster 优先级链
    all_poster_urls.sort(key=_poster_rank, reverse=True)
    if all_poster_urls:
        merged["posterCandidates"] = all_poster_urls[:8]
    best_poster = _pick_by_field_priority(poster_cands_scored, "poster")
    if best_poster:
        merged["posterUrl"], field_sources["poster"] = best_poster
    elif all_poster_urls:
        merged["posterUrl"] = all_poster_urls[0]
        field_sources["poster"] = ""

    # 女优：跨源「共识」合并——先各源映射到标准名，再按出现源数投票。
    # 避免 javlibrary 错页女优与正确源并集成一长串（SDMUA-008 案例）。
    # 身份门禁已清空的源（无 title）不参与女优投票。
    actors_out: list[str] = []
    rejected_set = {str(x) for x in (rejected_ids or [])}
    actor_lists = [
        (sid, names, sc)
        for sid, names, sc in actor_lists
        if sid not in rejected_set and names
    ]
    # 二次过滤：该源标题已被 gate 清空则跳过
    titles_alive = {
        sid
        for sid, d in details
        if str(d.get("title") or "").strip()
        or (
            isinstance(d.get("extra"), dict)
            and str((d.get("extra") or {}).get("titleZh") or "").strip()
        )
    }
    if titles_alive:
        actor_lists = [
            (sid, names, sc)
            for sid, names, sc in actor_lists
            if sid in titles_alive
        ]
    if actor_lists:
        from collections import Counter

        actor_lists.sort(key=lambda x: x[2], reverse=True)
        field_sources["actors"] = actor_lists[0][0]
        vote: Counter[str] = Counter()
        order: list[str] = []
        for _sid, names, _sc in actor_lists:
            seen_src: set[str] = set()
            for a in names:
                k = str(a or "").strip()
                if not k:
                    continue
                fold = k.casefold()
                if fold in seen_src:
                    continue
                seen_src.add(fold)
                if fold not in {x.casefold() for x in order}:
                    order.append(k)
                vote[k] += 1
        # 票数门槛：源多时要求 ≥3，避免两源错页互证（如 javlibrary+freejavbt）
        n_src = len(actor_lists)
        need = 3 if n_src >= 5 else 2
        consensus = [n for n in order if vote[n] >= need]
        if consensus:
            actors_out = consensus[:12]
        else:
            # 无共识时：优先与定稿标题同源的女优，而非「人数最多」的错页源
            title_src = str(field_sources.get("title") or "")
            prefer = next(
                (names for sid, names, _sc in actor_lists if sid == title_src),
                None,
            )
            actors_out = list(prefer or actor_lists[0][1])[:12]
    # 标题用 × 点名的女优：演员栏常漏（SDMU-088 四人只刮到两人）→ 并入
    title_hay = " ".join(
        [
            str(merged.get("title") or ""),
            str(merged.get("titleJa") or ""),
            *[str(t) for _sid, t, _sc in title_cands[:12]],
        ]
    )
    title_names = _names_from_title_pairs(title_hay)
    if title_names:
        try:
            from app.scrape.metadata_optimize import polish_actress_names

            mentioned = polish_actress_names(title_names)
            pool = list(actors_out)
            for _sid, names, _sc in actor_lists:
                pool.extend(names)
            pool.extend(title_names)
            polished_pool = polish_actress_names(pool)
            have = polish_actress_names(actors_out) if actors_out else []
            mentioned_fold = {n.casefold() for n in mentioned}
            for n in polished_pool:
                if n.casefold() in mentioned_fold and n not in have:
                    have.append(n)
            for n in mentioned:
                if n not in have:
                    have.append(n)
            if have:
                actors_out = have[:12]
        except Exception:  # noqa: BLE001
            for n in title_names:
                if n not in actors_out:
                    actors_out.append(n)
            actors_out = actors_out[:12]
    merged["actors"] = actors_out
    try:
        from app.scrape.metadata_optimize import polish_actress_names

        # 再映射一次：简繁/别名收敛；共识票在映射前已按原名计，映射后去重
        polished = polish_actress_names(actors_out)
        if polished:
            merged["actors"] = polished
    except Exception:  # noqa: BLE001
        pass

    # 剧情：结合本片女优名单，惩罚串入其他女优名的中文灌水剧情（STAR-795）
    # 并丢弃与已选标题明显不是同一作品的源剧情（ABF-005：ジュポニカ错页）
    allowed_for_plot: list[str] = list(merged.get("actors") or [])
    for _sid, names, _sc in actor_lists:
        for a in names:
            s = str(a or "").strip()
            if s and s not in allowed_for_plot:
                allowed_for_plot.append(s)
    title_by_sid: dict[str, str] = {}
    for sid, t, _sc in title_cands:
        prev = title_by_sid.get(sid) or ""
        if len(str(t or "")) > len(prev):
            title_by_sid[sid] = str(t or "")
    anchors = [
        str(merged.get("title") or "").strip(),
        str(merged.get("titleJa") or "").strip(),
    ]
    anchors = [a for a in anchors if a]

    def _overview_source_ok(sid: str) -> bool:
        if not anchors:
            return True
        st = title_by_sid.get(sid) or ""
        if not st:
            return True
        acts = list(merged.get("actors") or [])
        return any(_titles_compatible(st, a, actors=acts) for a in anchors)

    overview_scored = [
        (
            sid,
            ov,
            _score_overview(ov, source_id=sid, allowed_actors=allowed_for_plot),
        )
        for sid, ov, _ in overview_cands
        if _overview_source_ok(sid)
    ]
    # 空壳水印被打到负分后：若标题门禁又挡掉日文长剧情，只剩伪剧情 → 回落全源最高分
    overview_usable = [x for x in overview_scored if int(x[2]) >= 0]
    if not overview_usable:
        overview_scored = [
            (
                sid,
                ov,
                _score_overview(ov, source_id=sid, allowed_actors=allowed_for_plot),
            )
            for sid, ov, _ in overview_cands
        ]
        overview_usable = [x for x in overview_scored if int(x[2]) >= 0] or list(
            overview_scored
        )
    picked = _pick_by_field_priority(overview_usable, "overview")
    if picked:
        ov_v, ov_src = picked
        # 链首仍可能是水印空壳（负分）：强制换成全源最高分
        pick_sc = next(
            (int(sc) for sid, ov, sc in overview_usable if sid == ov_src and ov == ov_v),
            -10_000,
        )
        if pick_sc < 0 and overview_usable:
            best = max(overview_usable, key=lambda x: int(x[2]))
            if int(best[2]) > pick_sc:
                ov_v, ov_src = best[1], best[0]
        merged["overview"] = _normalize_merged_overview(ov_v)
        field_sources["overview"] = ov_src
    jp_ov = [
        (sid, ov, sc)
        for sid, ov, sc in overview_scored
        if _has_kana(str(ov or "")) and int(sc) >= 0
    ]
    if jp_ov:
        jp_picked = _pick_by_field_priority(jp_ov, "overview")
        ja_ov = str((jp_picked[0] if jp_picked else "") or "").strip()
        if not ja_ov:
            jp_ov.sort(key=lambda x: -x[2])
            ja_ov = str(jp_ov[0][1] or "").strip()
        final_ov = str(merged.get("overview") or "").strip()
        if ja_ov and (
            not final_ov
            or _has_kana(final_ov)
            or _titles_compatible(
                ja_ov[:80],
                final_ov[:80],
                actors=list(merged.get("actors") or []),
            )
        ):
            merged["overviewJa"] = ja_ov

    tags_out: list[str] = []
    seen_t: set[str] = set()
    if tag_lists:
        # 标签：中文分最高的源整套打底，其余源仅补中文/已映射项（避免中日重复堆叠）
        # 错页源标签不进（ABF-005 高中生来自ジュポニカ）
        tag_lists = [
            (sid, tags, sc)
            for sid, tags, sc in tag_lists
            if _overview_source_ok(sid)
        ]
        tag_lists.sort(key=lambda x: x[2], reverse=True)
        if tag_lists:
            field_sources["tags"] = tag_lists[0][0]
        base_zh = 0
        for i, (_sid, tags, _sc) in enumerate(tag_lists):
            for raw in tags:
                t = _normalize_tag_alias(str(raw or "").strip())
                if not t:
                    continue
                # 字形归一（繁简/异体/日文旧字），再去重：
                # 否则「穿衣幹砲」与「穿衣干炮」等异体会同时留在合并结果里
                t = _fold_tag_variant(t)
                # 已有足够中文底时，跳过带假名的日文标签
                if i > 0 and base_zh >= 3 and _has_kana(t):
                    continue
                k = t.casefold()
                if k in seen_t:
                    continue
                seen_t.add(k)
                tags_out.append(t)
                if _zh_prefer_bonus(t) > 0:
                    base_zh += 1
                if len(tags_out) >= 24:
                    break
            if len(tags_out) >= 24:
                break
        try:
            from app.scrape.metadata_optimize import code_prefix, polish_tag_names

            # 排除集用「全源女优名并集」(allowed_for_plot)，而非只排最终 merged 名单：
            # 合集/BEST 里没进最终名单的女优名也会被源站当标签塞进来
            # （CJOB-134：javbus 标签含 ERINA/AIKA/久留木玲，落在最终 12 人名单外 → 漏删）
            tags_out = polish_tag_names(
                tags_out,
                exclude=list(allowed_for_plot) + list(title_names or []),
                prefix=code_prefix(code),
            )
        except Exception:  # noqa: BLE001
            pass
    merged["tags"] = tags_out

    # 标题/剧情里的女优异写对齐到标准名
    try:
        acts = list(merged.get("actors") or [])
        if acts:
            if merged.get("title"):
                merged["title"] = _align_llm_text_actors(str(merged["title"]), acts)
            if merged.get("overview"):
                merged["overview"] = _align_llm_text_actors(
                    str(merged["overview"]), acts
                )
    except Exception:  # noqa: BLE001
        pass

    contrib = list(dict.fromkeys(order_hit))
    merged["sources"] = contrib
    merged["source"] = field_sources.get("title") or (
        contrib[0] if contrib else merged.get("source")
    )
    merged["provider"] = merged.get("source")
    merged["resolvedSources"] = contrib
    merged["fieldSources"] = {k: v for k, v in field_sources.items() if v}
    return merged


def _text_needs_zh_llm(text: str) -> bool:
    """缺可用中文：日文原文 / 无汉字加成 / 机翻垃圾。"""
    t = str(text or "").strip()
    if not t:
        return False
    if _has_kana(t):
        return True
    if _mt_junk_penalty(t) < 0:
        return True
    if _zh_prefer_bonus(t) <= 0:
        return True
    return False


def _zh_fill_acceptable(text: str, *, kind: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return False
    if _has_kana(t):
        return False
    if _mt_junk_penalty(t) < 0:
        return False
    if _zh_prefer_bonus(t) <= 0:
        return False
    if kind == "title" and len(t) < 4:
        return False
    if kind == "plot" and len(t) < 12:
        return False
    return True


def _align_llm_text_actors(text: str, actors: list[str]) -> str:
    """把译文里常见女优异写对齐到已映射标准名。"""
    s = str(text or "")
    if not s or not actors:
        return s
    try:
        from app.scrape.metadata_optimize import (
            _actor_maps,
            _lookup_actor_hit,
            mapping_language_from_settings,
        )
    except Exception:  # noqa: BLE001
        return s
    table = _actor_maps(mapping_language_from_settings())
    for canon in actors:
        c = str(canon or "").strip()
        if not c:
            continue
        # 收集指向同一 canon 的别名键
        aliases: list[str] = [c]
        for key, hit in table.items():
            if not isinstance(hit, dict):
                if str(hit or "").strip() == c:
                    aliases.append(str(key))
                continue
            if hit.get("drop"):
                continue
            name = str(hit.get("name") or hit.get("zh") or "").strip()
            if name == c:
                aliases.append(str(key))
                aliases.append(name)
        # 长别名优先替换
        for alias in sorted(set(aliases), key=len, reverse=True):
            if len(alias) < 2 or alias == c:
                continue
            if alias in s:
                s = s.replace(alias, c)
    return s


def _maybe_llm_fill_zh(detail: dict[str, Any] | None) -> dict[str, Any] | None:
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

    title = str(detail.get("title") or "").strip()
    if title and _text_needs_zh_llm(title):
        # 只译已校验日文：优先 titleJa；若定稿标题本身是日文也可
        src = str(detail.get("titleJa") or "").strip()
        if not src and _has_kana(title):
            src = title
        if src and _has_kana(src):
            try:
                got = translate_to_zh_sync(src, kind="title", prefer_llm=True)
                zh = _normalize_merged_title(str(got.get("text") or ""))
                eng = str(got.get("engine") or "llm")
                if _zh_fill_acceptable(zh, kind="title"):
                    detail["title"] = _align_llm_text_actors(
                        zh, list(detail.get("actors") or [])
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
                got = translate_to_zh_sync(src, kind="plot", prefer_llm=True)
                zh = _normalize_merged_overview(str(got.get("text") or ""))
                eng = str(got.get("engine") or "llm")
                if _zh_fill_acceptable(zh, kind="plot"):
                    detail["overview"] = _align_llm_text_actors(
                        zh, list(detail.get("actors") or [])
                    )
                    fs["overview"] = f"llm:{eng}" if eng != "none" else fs.get("overview") or "llm"
                    filled.append(f"overview/{eng}")
            except Exception as e:  # noqa: BLE001
                log.info("enrich llm overview fill skip: %s", e)

    if filled:
        detail["fieldSources"] = {k: v for k, v in fs.items() if v}
        detail["llmTranslated"] = filled
        log.info("enrich llm fill %s → %s", detail.get("code") or "", ",".join(filled))
    return detail


def _detail_has_poster(detail: dict[str, Any] | None, *, strict: bool = False) -> bool:
    """是否有封面 URL。strict=True（补封面早停）时拒绝单条弱 digital 占位。"""
    if not detail:
        return False
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    if not poster.startswith(("http://", "https://")):
        return False
    if not strict:
        return True
    cands = [
        str(u).strip()
        for u in list(detail.get("posterCandidates") or []) + [poster]
        if str(u or "").strip().startswith(("http://", "https://"))
    ]
    # 去重保序
    seen: set[str] = set()
    uniq: list[str] = []
    for u in cands:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    ranks = [_poster_rank(u) for u in uniq]
    if ranks and max(ranks) >= 4:
        return True
    hosts: set[str] = set()
    for u in uniq:
        try:
            from urllib.parse import urlparse

            h = (urlparse(u).netloc or "").lower()
            if h:
                hosts.add(h)
        except Exception:
            pass
    # 至少两个不同站封面互证，才够早停（单条 pl/digital 常是空图）
    if len(hosts) >= 2 and ranks and max(ranks) >= 3:
        return True
    return False


def _detail_has_actors(detail: dict[str, Any] | None) -> bool:
    if not detail:
        return False
    return bool(_clean_actors(detail.get("actors")))


def _detail_satisfies_gaps(
    detail: dict[str, Any] | None,
    gaps: list[str] | None = None,
    *,
    code: str = "",
) -> bool:
    """按本条缺口判断是否可提前收工；缺口字段齐了才停，避免丢掉稍后返回的源。"""
    if not detail:
        return False
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    # 无显式缺口：至少封面+女优（兼容旧逻辑）
    if not gap_set:
        return _detail_has_poster(detail) and _detail_has_actors(detail)

    if ("no_local" in gap_set or "no_media" in gap_set) and not _detail_has_poster(
        detail, strict=True
    ):
        return False
    if "no_actress" in gap_set and not _detail_has_actors(detail):
        return False
    if "no_studio" in gap_set and not str(
        detail.get("studio") or detail.get("maker") or ""
    ).strip():
        return False
    if "no_plot" in gap_set and len(str(detail.get("overview") or "").strip()) < 12:
        return False
    if "thin_title" in gap_set and _title_is_thin(
        str(detail.get("title") or ""), code or str(detail.get("code") or "")
    ):
        return False
    return True


# 标题/剧情偏中文的源：缺这两项时早停需等它们结束（或已拿到无假名中文）
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


def _may_early_stop(
    detail: dict[str, Any] | None,
    gaps: list[str] | None,
    *,
    code: str,
    batch: list[dict[str, Any]],
    finished: set[str],
) -> bool:
    """缺口齐了才可早停；缺标题/剧情时优先等中文源，避免日文先回就掐掉 airav/iqqtv。"""
    if not _detail_satisfies_gaps(detail, gaps, code=code):
        return False
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    need_zh = bool(gap_set & {"thin_title", "no_plot"})
    if not need_zh or not detail:
        return True
    title_ok = True
    plot_ok = True
    if "thin_title" in gap_set:
        title_ok = _zh_prefer_bonus(str(detail.get("title") or "")) > 0
    if "no_plot" in gap_set:
        plot_ok = _zh_prefer_bonus(str(detail.get("overview") or "")) > 0
    if title_ok and plot_ok:
        return True
    pending = _cn_text_ids_in_batch(batch) - finished
    return not pending


def _fetch_detail(
    code: str,
    *,
    region: str = "",
    wait_all: bool = False,
    gaps: list[str] | None = None,
    adaptive_first: bool = False,
) -> dict[str, Any] | None:
    """对匹配且已启用的数据源按策略并发拉详情，再按字段可信度合并最优。

    wait_all=True：不按缺口早停（极少用）。
    gaps：缺口字段齐了才允许早停。
    adaptive_first=True：强制先跑自适应源，缺口未齐再跑过盾（详情单刷）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import app.scrap_library.enrich_strategy as strat
    import app.scrape.sources_settings as scrape_src
    from app.scrape_details import fetch_detail_for_source

    code_u = str(code or "").strip().upper()
    if not code_u:
        return None
    sources = _detail_sources(region=region)
    if not sources:
        log.info(
            "enrich: no enabled sources for region=%r groups=%s",
            region,
            scrape_src.enrich_groups_for_region(region),
        )
        return None

    cfg = strat.get_strategy()
    mode = str(cfg.get("mode") or "parallel_all")
    if adaptive_first and mode == "parallel_all":
        mode = "adaptive_first"
    include_flare = bool(cfg.get("includeFlare", True))
    adapt_cfg = int(cfg.get("adaptiveWorkers") if cfg.get("adaptiveWorkers") is not None else 0)
    flare_cfg = int(cfg.get("flareWorkers") if cfg.get("flareWorkers") is not None else 0)
    timeout_sec = int(cfg.get("perSourceTimeoutSec") or 45)
    timeout_sec = max(5, min(180, timeout_sec))
    _push_log(f"单源超时 · {timeout_sec}s")

    adaptive = [s for s in sources if str(s.get("access") or "") != "proxy_flare"]
    flare = [s for s in sources if str(s.get("access") or "") == "proxy_flare"]
    if not include_flare or mode == "adaptive_only":
        flare = []

    adapt_n = strat.resolve_pool_workers(adapt_cfg, len(adaptive))
    flare_n = strat.resolve_pool_workers(flare_cfg, len(flare)) if flare else 0

    if mode == "adaptive_only":
        pools = [("adaptive", adaptive, adapt_n)]
    elif mode == "adaptive_first":
        pools = [("adaptive", adaptive, adapt_n), ("flare", flare, flare_n)]
    else:
        # parallel_all：该番号匹配源一起并发；adaptiveWorkers=0 则全开
        all_batch = adaptive + flare
        all_n = strat.resolve_pool_workers(adapt_cfg, len(all_batch))
        pools = [("all", all_batch, all_n)]
        log.info(
            "enrich %s parallel_all workers=%s/%s (cfg=%s)",
            code_u,
            all_n,
            len(all_batch),
            adapt_cfg,
        )

    if mode != "parallel_all":
        log.info(
            "enrich %s region=%r mode=%s sources=%s adapt=%s/%s flare=%s/%s",
            code_u,
            region,
            mode,
            len(sources),
            adapt_n,
            len(adaptive),
            flare_n,
            len(flare),
        )

    timings: list[dict[str, Any]] = []
    timings_lock = threading.Lock()
    t_fetch0 = time.perf_counter()

    def _timings_snapshot() -> list[dict[str, Any]]:
        with timings_lock:
            return [dict(r) for r in timings]

    def _publish_timings() -> None:
        """把当前源耗时推到 live current + 对应队列行（支持多番号并发）。"""
        rows = _timings_snapshot()
        with _enrich_lock:
            cur = _enrich_job.get("current")
            if isinstance(cur, dict):
                code_cur = str(cur.get("code") or "").strip().upper()
                if not code_cur or code_cur == code_u:
                    nxt = dict(cur)
                    nxt["sourceTimings"] = rows
                    if code_u:
                        nxt["code"] = code_u
                    _enrich_job["current"] = nxt
            # 队列行也写源耗时，点开任一「处理中」都能看实时进度
            queue = list(_enrich_job.get("queue") or [])
            changed = False
            for i, r in enumerate(queue):
                if not isinstance(r, dict):
                    continue
                if str(r.get("code") or "").strip().upper() != code_u:
                    continue
                queue[i] = {**r, "sourceTimings": rows}
                changed = True
                break
            if changed:
                _enrich_job["queue"] = queue

    def _upsert_timing(row: dict[str, Any]) -> None:
        sid = str(row.get("id") or "")
        with timings_lock:
            for i, r in enumerate(timings):
                if str(r.get("id") or "") == sid:
                    timings[i] = {**r, **row}
                    break
            else:
                timings.append(dict(row))
        _publish_timings()

    def _mark_pending_skipped(reason: str) -> None:
        with timings_lock:
            for i, r in enumerate(timings):
                st = str(r.get("status") or "")
                if st in {"pending", ""}:
                    timings[i] = {
                        **r,
                        "status": "skipped",
                        "ok": False,
                        "ms": int(r.get("ms") or 0),
                        "error": reason[:120],
                    }
        _publish_timings()

    # 预置全部启用源，保证 UI 能看到完整名单（含早停未跑完的）
    for src in sources:
        sid = str(src.get("id") or "").strip()
        if not sid:
            continue
        _upsert_timing(
            {
                "id": sid,
                "access": str(src.get("access") or ""),
                "ms": 0,
                "ok": False,
                "error": "",
                "actors": 0,
                "poster": False,
                "status": "pending",
            }
        )

    def _record_timing(
        *,
        sid: str,
        access: str,
        ms: float,
        ok: bool,
        err: str = "",
        actors: int = 0,
        has_poster: bool = False,
    ) -> None:
        row = {
            "id": sid,
            "access": access,
            "ms": int(round(ms)),
            "ok": bool(ok),
            "error": (err or "")[:120],
            "actors": int(actors),
            "poster": bool(has_poster),
            "status": "done" if ok else "fail",
        }
        _upsert_timing(row)
        status = "ok" if ok else f"fail:{row['error'] or '-'}"
        extras = []
        if ok:
            if has_poster:
                extras.append("封面")
            if actors:
                extras.append(f"女优×{actors}")
        _push_log(
            f"{sid} {row['ms']}ms {status}"
            + (f" · {'/'.join(extras)}" if extras else "")
        )
        done_n = sum(
            1
            for r in _timings_snapshot()
            if str(r.get("status") or "") in {"done", "fail"}
        )
        _set_progress(
            stage="enrich",
            label=f"{sid} {row['ms']}ms",
            done=done_n,
            total=max(len(sources), done_n),
        )

    def _one(src: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str]:
        import app.core.outbound_http as outbound_http

        sid = str(src.get("id") or "")
        access = str(src.get("access") or "")
        t0 = time.perf_counter()
        try:
            applied = scrape_src.apply_provider_link_for_fetch(sid)
        except Exception as e:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000
            _record_timing(sid=sid, access=access, ms=ms, ok=False, err=f"link:{e}")
            return sid, None, f"link:{e}"

        holder: dict[str, Any] = {}

        def _run_fetch() -> None:
            # TLS 必须在真正发请求的线程里设置
            outbound_http.set_thread_allow_flare(include_flare)
            outbound_http.set_thread_request_timeout(float(timeout_sec))
            try:
                detail = fetch_detail_for_source(
                    sid,
                    code_u,
                    base_url=str(applied.get("baseUrl") or src.get("baseUrl") or ""),
                    cookie=str(applied.get("cookie") or src.get("cookie") or ""),
                    api_key=str(applied.get("apiKey") or src.get("apiKey") or ""),
                )
                holder["detail"] = detail
            except Exception as e:  # noqa: BLE001
                holder["error"] = e
            finally:
                outbound_http.set_thread_request_timeout(None)

        th = threading.Thread(
            target=_run_fetch,
            name=f"enrich-src-{sid}",
            daemon=True,
        )
        th.start()
        th.join(timeout=float(timeout_sec))
        ms = (time.perf_counter() - t0) * 1000
        applied_access = str(applied.get("access") or access)

        if th.is_alive():
            # 超时：丢弃该源结果（后台线程可能仍在跑，但合并不再采纳）
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=f"timeout:{timeout_sec}s",
            )
            return sid, None, f"timeout:{timeout_sec}s"

        err_obj = holder.get("error")
        if err_obj is not None:
            if isinstance(err_obj, HTTPException):
                err_s = str(err_obj.detail)
            else:
                err_s = str(err_obj)
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=err_s,
            )
            return sid, None, err_s

        detail = holder.get("detail")
        if not _detail_usable(detail, code=code_u):
            title = str((detail or {}).get("title") or "")[:40]
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=f"rejected:{title}",
            )
            return sid, None, f"rejected:{title}"
        detail = dict(detail)
        try:
            from app.scrape.metadata_optimize import polish_actress_names

            directors: list[str] = []
            d0 = str(detail.get("director") or "").strip()
            if d0:
                directors.append(d0)
            for raw_d in detail.get("directors") or []:
                if isinstance(raw_d, dict):
                    n = str(raw_d.get("name") or "").strip()
                else:
                    n = str(raw_d or "").strip()
                if n:
                    directors.append(n)
            detail["actors"] = polish_actress_names(
                _clean_actors(detail.get("actors")), exclude=directors
            )
        except Exception:  # noqa: BLE001
            detail["actors"] = _clean_actors(detail.get("actors"))
        # 源侧明细标签：**不折叠**字形。此处结果会喂给 `_score_tags`
        # （via `_merge_got` 读 `d.get("tags")`），提前折叠会让繁中源
        # 失去「繁体惩罚」而反压简中源（案例 ACHJ-078）。输出侧折叠在合并主循环做。
        detail["tags"] = _clean_tags(detail.get("tags"), fold=False)
        detail["source"] = detail.get("source") or sid
        detail["provider"] = detail.get("provider") or sid
        detail["resolvedBase"] = applied.get("baseUrl") or src.get("baseUrl")
        detail["access"] = applied.get("access") or src.get("access")
        _record_timing(
            sid=sid,
            access=str(detail.get("access") or access),
            ms=ms,
            ok=True,
            actors=len(detail.get("actors") or []),
            has_poster=_detail_has_poster(detail),
        )
        return sid, detail, ""

    def _run_pool(
        label: str, batch: list[dict[str, Any]], workers: int
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        if not batch or workers <= 0:
            return {}, []
        got: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        finished: set[str] = set()
        n = max(1, min(workers, len(batch)))
        pool = ThreadPoolExecutor(
            max_workers=n, thread_name_prefix=f"enrich-{label}"
        )
        futs = [pool.submit(_one, src) for src in batch]
        early = False
        try:
            for fut in as_completed(futs):
                try:
                    sid, detail, err = fut.result(timeout=timeout_sec + 5)
                except Exception as e:  # noqa: BLE001
                    errors.append(str(e))
                    continue
                if sid:
                    finished.add(str(sid))
                if detail:
                    got[sid] = detail
                    # 按本条缺口齐了才早停；缺标题/剧情时还要等中文源
                    merged_now = _merge_got(batch, got)
                    if not wait_all and _may_early_stop(
                        merged_now,
                        gaps,
                        code=code_u,
                        batch=batch,
                        finished=finished,
                    ):
                        early = True
                        log.info(
                            "enrich %s early-stop pool=%s hits=%s gaps=%s",
                            code_u,
                            label,
                            ",".join(got.keys()),
                            ",".join(gaps or []) or "-",
                        )
                        _push_log(
                            f"早停 · {label} · 已齐 gaps={','.join(gaps or []) or '-'} · "
                            f"命中 {','.join(got.keys())}"
                        )
                        break
                elif err:
                    errors.append(f"{sid}:{err}")
        finally:
            for f in futs:
                f.cancel()
            # 不阻塞等剩余慢请求（过盾 45s+）；后台线程自然结束
            pool.shutdown(wait=False, cancel_futures=True)
            if early:
                _mark_pending_skipped("早停跳过")
        if early:
            errors = [e for e in errors if "cancelled" not in e.lower()]
        return got, errors

    got_all: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for label, batch, workers in pools:
        if not batch:
            continue
        # adaptive_first：本条缺口已齐再跳过 Flare（标题/剧情未拿中文时仍进过盾池）
        if (
            mode == "adaptive_first"
            and label == "flare"
            and _may_early_stop(
                _merge_got(sources, got_all),
                gaps,
                code=code_u,
                batch=batch,
                finished=set(got_all.keys()),
            )
        ):
            log.info(
                "enrich %s skip flare pool (gaps satisfied: %s)",
                code_u,
                ",".join(gaps or []) or "-",
            )
            _push_log("跳过过盾池 · 缺口已齐")
            # 仅把本池（过盾）里还 pending 的标跳过
            flare_ids = {str(s.get("id") or "") for s in batch}
            with timings_lock:
                for i, r in enumerate(timings):
                    if str(r.get("id") or "") in flare_ids and str(
                        r.get("status") or ""
                    ) in {"pending", ""}:
                        timings[i] = {
                            **r,
                            "status": "skipped",
                            "ok": False,
                            "error": "跳过过盾池",
                        }
            _publish_timings()
            break
        _push_log(
            f"开跑 · {label} ×{len(batch)} · workers={workers}"
        )
        part, errs = _run_pool(label, batch, workers)
        got_all.update(part)
        errors.extend(errs)

    _mark_pending_skipped("未完成")
    fetch_ms = int(round((time.perf_counter() - t_fetch0) * 1000))
    # 保持启用源目录顺序，方便对照「全部数据源」
    by_id = {str(r.get("id") or ""): r for r in _timings_snapshot()}
    timings_sorted = [
        by_id[str(s.get("id") or "")]
        for s in sources
        if str(s.get("id") or "") in by_id
    ]
    # 兜底：不在 sources 里但已有记录的也附上
    seen = {str(r.get("id") or "") for r in timings_sorted}
    for r in _timings_snapshot():
        sid = str(r.get("id") or "")
        if sid and sid not in seen:
            timings_sorted.append(r)
    if timings_sorted:
        finished = [
            r
            for r in timings_sorted
            if str(r.get("status") or "") in {"done", "fail"}
        ]
        finished.sort(key=lambda r: int(r.get("ms") or 0), reverse=True)
        top = " · ".join(
            f"{r['id']} {r['ms']}ms{'✓' if r.get('ok') else '✗'}"
            for r in finished[:6]
        )
        if top:
            _push_log(f"耗时排行 · {top}")
        skip_n = sum(
            1 for r in timings_sorted if str(r.get("status") or "") == "skipped"
        )
        _push_log(
            f"拉详情合计 {fetch_ms}ms · 源 {len(timings_sorted)} 个"
            + (f" · 跳过 {skip_n}" if skip_n else "")
        )
    if not got_all:
        if errors:
            log.info("enrich detail miss %s: %s", code_u, "; ".join(errors[:6]))
        return None

    merged = _merge_got(sources, got_all)
    if merged is None:
        return None
    merged = _maybe_llm_fill_zh(merged) or merged
    merged["sourceTimings"] = timings_sorted
    merged["fetchMs"] = fetch_ms
    log.info(
        "enrich detail %s mode=%s ok=%s/%s hits=%s fetch=%sms top=%s llm=%s",
        code_u,
        mode,
        len(got_all),
        len(sources),
        ",".join(str(x) for x in (merged.get("resolvedSources") or [])[:8]),
        fetch_ms,
        ",".join(f"{r['id']}:{r['ms']}" for r in timings_sorted[:5]),
        ",".join(merged.get("llmTranslated") or []) or "-",
    )
    return merged


def _find_nfo(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    preferred = [
        folder / "movie.nfo",
        folder / f"{folder.name}.nfo",
    ]
    for p in preferred:
        if p.is_file():
            return p
    nfos = sorted(folder.glob("*.nfo"))
    return nfos[0] if nfos else None


def _ensure_child(parent: ET.Element, tag: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    return el


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
    return False


def _set_text_if_empty(parent: ET.Element, tag: str, value: str, *, force: bool = False) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    el = parent.find(tag)
    cur = "".join(el.itertext()).strip() if el is not None else ""
    if cur and not force:
        return False
    node = _ensure_child(parent, tag)
    node.text = text
    return True


def _merge_list_tags(
    parent: ET.Element, tag: str, values: list[str], *, max_n: int = 16
) -> bool:
    existing = {
        "".join(el.itertext()).strip().casefold()
        for el in parent.findall(tag)
        if "".join(el.itertext()).strip()
    }
    changed = False
    for raw in values:
        v = str(raw or "").strip()
        if not v or v.casefold() in existing:
            continue
        el = ET.SubElement(parent, tag)
        el.text = v
        existing.add(v.casefold())
        changed = True
        if len(existing) >= max_n:
            break
    return changed


def _merge_actors(parent: ET.Element, names: list[str], *, max_n: int = 12) -> bool:
    # 先清掉已写入的标签/登录页噪声，再合并新名单
    pruned = _prune_junk_actors(parent)
    existing: set[str] = set()
    for a in parent.findall("actor"):
        nm = a.find("name")
        if nm is None:
            continue
        text = "".join(nm.itertext()).strip()
        if text:
            existing.add(text.casefold())
    changed = pruned
    for raw in _clean_actors(names):
        name = str(raw or "").strip()
        if not name or name.casefold() in existing:
            continue
        actor = ET.SubElement(parent, "actor")
        nm_el = ET.SubElement(actor, "name")
        nm_el.text = name
        existing.add(name.casefold())
        changed = True
        if len(existing) >= max_n:
            break
    return changed


def _prune_junk_actors(parent: ET.Element) -> bool:
    before: list[str] = []
    for a in parent.findall("actor"):
        nm = a.find("name")
        if nm is None:
            continue
        text = "".join(nm.itertext()).strip()
        if text:
            before.append(text)
    cleaned = _clean_actors(before)
    if cleaned == before:
        return False
    for a in list(parent.findall("actor")):
        parent.remove(a)
    for name in cleaned:
        actor = ET.SubElement(parent, "actor")
        nm_el = ET.SubElement(actor, "name")
        nm_el.text = name
    return True


def _replace_actors(parent: ET.Element, names: list[str], *, max_n: int = 12) -> bool:
    before: list[str] = []
    for a in parent.findall("actor"):
        nm = a.find("name")
        if nm is not None:
            text = "".join(nm.itertext()).strip()
            if text:
                before.append(text)
    for a in list(parent.findall("actor")):
        parent.remove(a)
    _merge_actors(parent, names, max_n=max_n)
    after: list[str] = []
    for a in parent.findall("actor"):
        nm = a.find("name")
        if nm is not None:
            text = "".join(nm.itertext()).strip()
            if text:
                after.append(text)
    return before != after


def _replace_list_tags(
    parent: ET.Element, tag: str, values: list[str], *, max_n: int = 16
) -> bool:
    before = ["".join(el.itertext()).strip() for el in parent.findall(tag)]
    for el in list(parent.findall(tag)):
        parent.remove(el)
    _merge_list_tags(parent, tag, values, max_n=max_n)
    after = ["".join(el.itertext()).strip() for el in parent.findall(tag)]
    return before != after


def merge_nfo_with_detail(
    nfo_path: Path, detail: dict[str, Any], *, overwrite: bool = False
) -> bool:
    """增量仅补空；覆盖模式写入新值并替换已有字段。返回是否有改动。"""
    if nfo_path.is_file():
        try:
            raw = nfo_path.read_text(encoding="utf-8", errors="replace")
            root = ET.fromstring(raw)
        except Exception:
            root = ET.Element("movie")
    else:
        root = ET.Element("movie")
    if root.tag.lower() != "movie":
        movie = root.find("movie")
        root = movie if movie is not None else ET.Element("movie")

    changed = False
    force = bool(overwrite)
    title = str(detail.get("title") or "").strip()
    code = str(detail.get("code") or detail.get("id") or "").strip().upper()
    studio = str(detail.get("studio") or detail.get("maker") or "").strip()
    plot = str(detail.get("overview") or "").strip()
    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    year = str(detail.get("year") or "").strip()
    date_s = str(detail.get("date") or "").strip()
    actors = _clean_actors(detail.get("actors"))
    tags = _clean_tags(detail.get("tags"))
    director = str(detail.get("director") or "").strip()
    if not director:
        for d in detail.get("directors") or []:
            if isinstance(d, dict):
                n = str(d.get("name") or "").strip()
            else:
                n = str(d or "").strip()
            if n:
                director = n
                break
    try:
        from app.scrape.metadata_optimize import polish_actress_names

        ban = [director] if director else []
        actors = polish_actress_names(actors, exclude=ban)
    except Exception:  # noqa: BLE001
        pass

    if code:
        changed = _set_text_if_empty(root, "num", code, force=force) or changed
    if title and title.upper() != code and not any(
        m in title.casefold() for m in (x.casefold() for x in _JUNK_TITLE_MARKERS)
    ):
        cur_title = ""
        te = root.find("title")
        if te is not None:
            cur_title = "".join(te.itertext()).strip()
        force_title = force or _title_is_thin(cur_title, code)
        if title.strip() and not _title_is_thin(title, code):
            changed = (
                _set_text_if_empty(root, "title", title, force=force_title) or changed
            )
    if studio:
        changed = _set_text_if_empty(root, "studio", studio, force=force) or changed
        changed = _set_text_if_empty(root, "maker", studio, force=force) or changed
    if director:
        changed = _set_text_if_empty(root, "director", director, force=force) or changed
    if plot:
        changed = _set_text_if_empty(root, "plot", plot, force=force) or changed
        changed = _set_text_if_empty(root, "outline", plot, force=force) or changed
    if year:
        changed = _set_text_if_empty(root, "year", year, force=force) or changed
    if date_s:
        changed = _set_text_if_empty(root, "premiered", date_s, force=force) or changed
        changed = _set_text_if_empty(root, "releasedate", date_s, force=force) or changed
    if poster.startswith(("http://", "https://")):
        changed = _set_text_if_empty(root, "cover", poster, force=force) or changed
    # 无论是否补到新女优，先清掉已写入的标签/登录噪声
    changed = _prune_junk_actors(root) or changed
    if force:
        # 覆盖：女优/类型整表替换（可为空，表示清空旧脏数据）
        changed = _replace_actors(root, actors) or changed
        if tags:
            changed = _replace_list_tags(root, "genre", tags) or changed
    else:
        if actors:
            changed = _merge_actors(root, actors) or changed
        if tags:
            changed = _merge_list_tags(root, "genre", tags) or changed

    if not changed and not nfo_path.is_file():
        # 新建空壳也算变更
        if code:
            _ensure_child(root, "num").text = code
            changed = True

    if not changed:
        return False

    write_nfo(nfo_path, root)
    return True


def _dmm_poster_fallbacks(url: str) -> list[str]:
    """digital 空图时尝试 mono 实图路径；ps 补 pl。"""
    u = str(url or "").strip()
    out: list[str] = []
    m = re.search(
        r"pics\.dmm\.co\.jp/digital/video/([^/]+)/\1(p[sl])\.jpg", u, re.I
    )
    if m:
        cid = m.group(1)
        # 常见：sspd00024 → sspd024；去掉中间多余 0
        short = re.sub(r"^([a-z]+)0+(\d+)$", r"\1\2", cid, flags=re.I)
        for name in (short, cid):
            out.append(f"https://pics.dmm.co.jp/mono/movie/adult/{name}/{name}pl.jpg")
            out.append(f"https://pics.dmm.co.jp/mono/movie/adult/{name}/{name}ps.jpg")
            out.append(f"http://pics.dmm.co.jp/mono/movie/adult/{name}/{name}pl.jpg")
        # digital ps 空图时务必再试 pl
        out.append(f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}pl.jpg")
        out.append(f"https://pics.dmm.co.jp/digital/video/{cid}/{cid}ps.jpg")
    return out


def _download_covers(
    folder: Path,
    cover_url: str | list[str],
    *,
    region: str = "",
    overwrite: bool = False,
    cover_cfg: dict | None = None,
) -> tuple[str, str, list[str]]:
    """返回 (poster_rel, thumb_rel, tried_urls)。

    本地番号目录只保留一张 poster.jpg：
    需要裁剪时写入裁剪后的图；不裁剪则写入原图。
    顺带清掉 thumb.jpg / fanart.jpg，避免多图并存。
    """
    from app.scrap_library.cover_scrape import (
        cover_crop_for_region,
        normalize_cover_settings,
        process_cover_bytes,
        rewrite_cover_url_for_quality,
    )
    from app.scrap_library.enrich_strategy import get_strategy

    cfg = normalize_cover_settings(
        cover_cfg
        if cover_cfg is not None
        else (get_strategy().get("cover") or {})
    )
    quality = str(cfg.get("quality") or "high")
    crop_ratio = str(cfg.get("cropRatio") or "full")
    crop_mode = cover_crop_for_region(region, cfg)

    raw_list = cover_url if isinstance(cover_url, list) else [cover_url]
    urls: list[str] = []
    for u in raw_list:
        s = str(u or "").strip()
        if not s.startswith(("http://", "https://")):
            continue
        for cand in rewrite_cover_url_for_quality(s, quality):
            if cand not in urls:
                urls.append(cand)
        for alt in _dmm_poster_fallbacks(s):
            for cand in rewrite_cover_url_for_quality(alt, quality):
                if cand not in urls:
                    urls.append(cand)
    # 去重后排序：DMM 等高质量源优先；有 DMM 时 javbus 仍保留作空图兜底，但排最后
    # 注意：_poster_rank 越大越好；低画质组内也必须好源先于慢图床
    def _cover_try_key(u: str) -> tuple[int, int]:
        low_size = (
            0
            if any(x in u for x in ("ps.jpg", "_s.jpg", "/small/", "cover-t"))
            else 1
        )
        size_pref = low_size if quality == "low" else -low_size
        return (-_poster_rank(u), size_pref)

    # 已有 https 时丢掉同路径 http，少一轮必败/慢请求
    https_paths = {
        u[8:] for u in urls if u.lower().startswith("https://")
    }
    urls = [
        u
        for u in urls
        if not (
            u.lower().startswith("http://")
            and u[7:] in https_paths
        )
    ]
    urls = list(dict.fromkeys(urls))
    urls.sort(key=_cover_try_key)
    # DMM 常有一串空图变体：先各抽 digital/mono 各 1 张，立刻回落 javbus 等，再补剩余
    dmm_u = [
        u
        for u in urls
        if "dmm.co.jp" in u.lower() or "awsimgsrc.dmm." in u.lower()
    ]
    other_u = [u for u in urls if u not in dmm_u]
    if dmm_u and other_u:
        digital = [u for u in dmm_u if "/digital/" in u.lower()]
        mono = [u for u in dmm_u if "/mono/" in u.lower()]
        head: list[str] = []
        for pool in (digital, mono):
            pl = [u for u in pool if "pl.jpg" in u.lower()]
            pick = (pl[0] if pl else None) or (pool[0] if pool else None)
            if pick:
                head.append(pick)
        if not head:
            head = dmm_u[:2]
        urls = list(dict.fromkeys([*head[:2], *other_u, *dmm_u]))

    poster_file = folder / "poster.jpg"
    if not overwrite:
        if poster_file.is_file() and not embed_svc._is_blank_cover_file(
            poster_file
        ):  # noqa: SLF001
            _purge_extra_cover_files(folder)
            rel = embed_svc._media_rel(poster_file)  # noqa: SLF001
            return rel, "", []

    tried: list[str] = []
    for url in urls:
        tried.append(url)
        got = embed_svc._fetch_cover_bytes(url)  # noqa: SLF001
        if not got:
            continue
        raw, ctype = got
        # 非 JPEG 先转 RGB JPEG，再走统一裁剪/画质
        if "png" in (ctype or "").lower() or "webp" in (ctype or "").lower():
            try:
                import io

                from PIL import Image

                im = Image.open(io.BytesIO(raw))
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                elif im.mode == "L":
                    im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=90, optimize=True)
                raw = buf.getvalue()
            except Exception:
                pass
        # 空图拒写（内存探测，不落临时文件：避免写/删临时图）
        try:
            if embed_svc._is_blank_cover_bytes(raw):  # noqa: SLF001
                continue
        except Exception:
            pass

        # 裁剪后也可能变「空图」（低画质 ps + 右裁常见）→ 试下一候选
        poster_data = process_cover_bytes(
            raw,
            crop_mode=crop_mode,
            quality=quality,
            crop_ratio=crop_ratio,
        )
        dest = embed_svc._write_poster_jpg(folder, poster_data)  # noqa: SLF001
        if not dest:
            continue
        _purge_extra_cover_files(folder)
        poster = embed_svc._media_rel(dest)  # noqa: SLF001
        return poster, "", tried

    return "", "", tried


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
    poster_file = folder / "poster.jpg"
    return poster_file.is_file() and not embed_svc._is_blank_cover_file(poster_file)


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


def enrich_one_row(
    row: dict[str, Any],
    *,
    dry_run: bool = False,
    wait_all: bool = False,
    overwrite: bool = False,
    prefetched_detail: dict[str, Any] | None = None,
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
    }
    if not code or not rel:
        out["error"] = "missing code/relPath"
        return out

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

    # E2E 等可传入已合并详情，跳过再拉源（仍写 NFO/封面/向量）
    if isinstance(prefetched_detail, dict) and prefetched_detail:
        detail = dict(prefetched_detail)
        out["prefetched"] = True
    else:
        # 增量：缺口齐了就早停；覆盖：拉满各源再合并写回
        # wait_all=True（详情单刷）时强制自适应优先，不过盾池拖尾
        detail = _fetch_detail(
            code,
            region=region,
            wait_all=force,
            gaps=None if force else gaps,
            adaptive_first=wait_all and not force,
        )
    if not detail:
        out["error"] = "detail_not_found"
        return out
    out["source"] = detail.get("source") or detail.get("provider")
    out["detailTitle"] = detail.get("title")
    out["sourceTimings"] = list(detail.get("sourceTimings") or [])
    out["fetchMs"] = detail.get("fetchMs")
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
    changed = merge_nfo_with_detail(nfo, detail, overwrite=force)
    poster_url = str(detail.get("posterUrl") or "").strip()
    poster_file = folder / "poster.jpg"
    blank_local = poster_file.is_file() and embed_svc._is_blank_cover_file(
        poster_file
    )
    need_cover = force or (
        "no_local" in gaps
        or "no_media" in gaps
        or blank_local
        or not poster_file.is_file()
    )
    if need_cover:
        cands: list[str] = []
        if poster_url.startswith(("http://", "https://")):
            cands.append(poster_url)
        for u in detail.get("posterCandidates") or []:
            s = str(u or "").strip()
            if s.startswith(("http://", "https://")) and s not in cands:
                cands.append(s)
        if cands:
            got_p, got_t, tried = _download_covers(
                folder,
                cands,
                region=region,
                overwrite=force,
            )
            if got_p or got_t:
                changed = True
                out["posterDownloaded"] = bool(got_p)
                out["coverTried"] = (tried or cands)[:4]
            else:
                out["posterDownloaded"] = False
                out["coverTried"] = (tried or cands)[:4]
        else:
            out["posterDownloaded"] = False
            out["coverTried"] = []
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

    # 字段表：封面以本地有效图为准（有 URL 但空图不算成功）
    fields = list(out.get("fields") or _detail_field_rows(detail))
    for f in fields:
        if str(f.get("id") or "") != "poster":
            continue
        if local_cover_ok:
            f["ok"] = True
            f["value"] = "已落盘"
        else:
            f["ok"] = False
            remote = str(f.get("value") or poster_url or "").strip()
            f["value"] = (
                f"空图/未落盘 · {remote[:80]}" if remote else "无封面"
            )
    out["fields"] = fields
    out["localCoverOk"] = local_cover_ok

    # 刮削写回后立刻同步向量库（一步完成）
    _set_progress(
        stage="enrich",
        label=f"向量 {code or folder.name}",
    )
    _push_log(f"{code or folder.name} · 刮削写回完成 · 同步向量…", region=region)
    try:
        rein = reingest_folder(folder) or {
            "ok": False,
            "embedded": False,
            "error": "reingest_none",
        }
        out["reingest"] = rein
        if cover_required and not local_cover_ok:
            out["ok"] = False
            out["vectorSynced"] = bool(rein.get("embedded"))
            out["error"] = "封面空图或下载失败"
            _push_log(
                f"{code or folder.name} · 封面失败（源站空图/未落盘）",
                region=region,
            )
            return out
        if rein.get("embedded"):
            out["ok"] = True
            out["vectorSynced"] = True
            _push_log(
                f"{code or folder.name} · 向量已同步",
                region=region,
            )
        else:
            err = str(rein.get("error") or "vector_skip")
            out["vectorSynced"] = False
            out["vectorError"] = err
            # 刮削本身已完成；向量失败单独标出，仍记为本条失败以便重试
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
    except Exception as e:  # noqa: BLE001
        out["ok"] = False
        out["vectorSynced"] = False
        out["error"] = f"向量同步失败:{e}"
        out["reingest"] = {"ok": False, "embedded": False, "error": str(e)}
        _push_log(f"{code or folder.name} · 向量同步失败 · {e}", region=region)
    return out


def run_enrich(
    *,
    region: str = "japan_censored",
    kinds: list[str] | None = None,
    limit: int = 0,
    dry_run: bool = False,
    mode: str = "incremental",
    resume: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overwrite = str(mode or "incremental").strip().lower() in {
        "overwrite",
        "cover",
        "force",
        "replace",
    }
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
    mode_label = "覆盖" if overwrite else "增量"
    mode_norm = "overwrite" if overwrite else "incremental"

    resume_cp = resume if isinstance(resume, dict) else None
    ok_n = int((resume_cp or {}).get("ok") or 0) if resume_cp else 0
    fail_n = int((resume_cp or {}).get("failed") or 0) if resume_cp else 0
    prior_done = int((resume_cp or {}).get("done") or 0) if resume_cp else 0
    original_total = 0

    if resume_cp and list(resume_cp.get("queue") or []):
        queue = [
            dict(r) for r in list(resume_cp.get("queue") or []) if isinstance(r, dict)
        ]
        original_total = int(
            resume_cp.get("originalTotal") or (prior_done + len(queue))
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
            label="全量队列" if overwrite else "筛选缺口",
            done=0,
            total=0,
            ok=0,
            failed=0,
        )

        seen: set[str] = set()
        queue = []
        fetch_lim = 0 if lim <= 0 else lim
        if overwrite:
            for r in embed_svc.enrich_all_items(region=region, limit=fetch_lim):
                iid = str(r.get("itemId") or "")
                if not iid or iid in seen:
                    continue
                seen.add(iid)
                queue.append(r)
                if lim > 0 and len(queue) >= lim:
                    break
        else:
            # 先空壳（仅骨架）再补缺；不再按 kind 重复扫目录
            for r in embed_svc.quality_incomplete_items(
                region=region, limit=fetch_lim
            ):
                iid = str(r.get("itemId") or "")
                if not iid or iid in seen:
                    continue
                seen.add(iid)
                queue.append(r)
                if lim > 0 and len(queue) >= lim:
                    break
        original_total = len(queue)
        prior_done = 0
        ok_n = 0
        fail_n = 0
        _push_log(f"队列 {len(queue)} 条", region=region)

    queue_view = [
        {
            "index": prior_done + i,
            "itemId": str(r.get("itemId") or ""),
            "code": str(r.get("code") or "").strip().upper(),
            "gaps": list(r.get("gaps") or []),
            "status": "pending",
        }
        for i, r in enumerate(queue)
    ]
    _set_queue(queue_view)
    # original_total 仅用于暂停检查点/日志；UI 进度条跟本轮 queueCounts
    original_total = int(prior_done or 0) + len(queue_view)
    _set_progress(
        stage="enrich",
        label=f"处理 {prior_done}/{original_total}"
        if prior_done
        else f"队列 {len(queue_view)}",
        ok=ok_n,
        failed=fail_n,
    )

    results: list[dict[str, Any]] = []
    cancelled = False
    paused = False
    halt_at = -1
    results_lock = threading.Lock()
    counters_lock = threading.Lock()
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    def _finish_one(i: int, row: dict[str, Any], one: dict[str, Any] | None, exc: BaseException | None) -> None:
        nonlocal ok_n, fail_n
        code_u = str(row.get("code") or "").strip().upper()
        gaps = list(row.get("gaps") or [])
        abs_i = prior_done + i
        if exc is not None:
            with counters_lock:
                fail_n += 1
                cur_ok, cur_fail = ok_n, fail_n
            with results_lock:
                results.append({"code": row.get("code"), "ok": False, "error": str(exc)})
            _patch_queue_item(i, status="fail", error=str(exc)[:120])
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
            return

        assert one is not None
        st = "done" if one.get("ok") else "fail"
        _patch_queue_item(
            i,
            status=st,
            error=str(one.get("error") or "")[:120],
            source=str(one.get("source") or ""),
            fetchMs=one.get("fetchMs"),
            detailTitle=str(one.get("detailTitle") or "")[:200],
            actors=one.get("actors"),
            nfoChanged=bool(one.get("nfoChanged")),
            posterDownloaded=bool(one.get("posterDownloaded")),
            vectorSynced=bool(one.get("vectorSynced")),
            vectorError=str(one.get("vectorError") or "")[:120],
            sourceTimings=list(one.get("sourceTimings") or []),
            fields=list(one.get("fields") or []),
            wouldFill=one.get("wouldFill"),
        )
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
                "actors": one.get("actors"),
                "nfoChanged": one.get("nfoChanged"),
                "posterDownloaded": one.get("posterDownloaded"),
                "vectorSynced": bool(one.get("vectorSynced")),
                "vectorError": one.get("vectorError"),
                "sourceTimings": list(one.get("sourceTimings") or []),
                "fields": list(one.get("fields") or []),
                "wouldFill": one.get("wouldFill"),
            }
        )
        with results_lock:
            results.append(one)
        if one.get("ok"):
            with counters_lock:
                ok_n += 1
                cur_ok, cur_fail = ok_n, fail_n
            if one.get("vectorSynced"):
                _push_log(f"{code_u} · 完成（刮削+向量）", region=region)
        else:
            with counters_lock:
                fail_n += 1
                cur_ok, cur_fail = ok_n, fail_n
            _push_log(
                f"{one.get('code') or code_u}: {one.get('error') or 'fail'}",
                region=region,
            )
        _set_progress(
            stage="enrich",
            label=f"处理 {prior_done + cur_ok + cur_fail}/{original_total}",
            ok=cur_ok,
            failed=cur_fail,
        )

    def _run_one(i: int, row: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any] | None, BaseException | None]:
        code_u = str(row.get("code") or "").strip().upper()
        gaps = list(row.get("gaps") or [])
        abs_i = prior_done + i
        _patch_queue_item(i, status="running")
        _set_current(
            {
                "code": code_u,
                "itemId": str(row.get("itemId") or ""),
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
            one = enrich_one_row(row, dry_run=dry_run, overwrite=overwrite)
            return i, row, one, None
        except BaseException as e:  # noqa: BLE001
            return i, row, None, e

    workers = max(1, min(int(_ITEM_WORKERS), len(queue) or 1))
    _push_log(f"并发番号 · {workers}", region=region)
    next_i = 0
    inflight: dict[Any, int] = {}
    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="enrich-item"
    ) as pool:
        while next_i < len(queue) or inflight:
            halt = _halt_kind()
            if halt:
                # 不再投新任务；等在飞的收尾后再写检查点/停止
                if inflight:
                    done_set, _ = wait(
                        list(inflight.keys()), return_when=FIRST_COMPLETED
                    )
                    for fut in done_set:
                        inflight.pop(fut, None)
                        try:
                            i, row, one, exc = fut.result()
                        except BaseException as e:  # noqa: BLE001
                            # 理论上 _run_one 已吞异常
                            continue
                        _finish_one(i, row, one, exc)
                    continue
                halt_at = next_i
                if halt == "pause":
                    paused = True
                    remaining = [dict(r) for r in queue[next_i:]]
                    with counters_lock:
                        cur_ok, cur_fail = ok_n, fail_n
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
                            "done": prior_done + next_i,
                            "originalTotal": original_total,
                        },
                    )
                    _push_log(
                        f"已暂停 · 已处理 {prior_done + next_i}/{original_total} · "
                        f"剩余 {len(remaining)}",
                        region=region,
                    )
                else:
                    cancelled = True
                    _clear_checkpoint(region)
                    _clear_runtime_queue()
                    _clear_enrich_logs(region=region)
                    log.info(
                        "enrich stopped region=%s done=%s/%s",
                        region,
                        prior_done + next_i,
                        original_total,
                    )
                break

            while len(inflight) < workers and next_i < len(queue):
                if _halt_kind():
                    break
                idx = next_i
                row = queue[idx]
                next_i += 1
                fut = pool.submit(_run_one, idx, row)
                inflight[fut] = idx

            if not inflight:
                break
            done_set, _ = wait(list(inflight.keys()), return_when=FIRST_COMPLETED)
            for fut in done_set:
                inflight.pop(fut, None)
                try:
                    i, row, one, exc = fut.result()
                except BaseException as e:  # noqa: BLE001
                    continue
                _finish_one(i, row, one, exc)

    if not paused and not cancelled:
        _clear_checkpoint(region)

    summary = {
        "dryRun": dry_run,
        "mode": mode_norm,
        "region": region,
        "groups": list(groups),
        "kinds": kind_list,
        "queued": original_total,
        "ok": ok_n,
        "failed": fail_n,
        "cancelled": cancelled,
        "paused": paused,
        "remaining": (
            len(queue[halt_at:]) if (paused or cancelled) and halt_at >= 0 else 0
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

    # 原日文剧情备份到 plotoriginal（仅首次）
    cur_plot = ""
    pe = root_el.find("plot")
    if pe is not None:
        cur_plot = "".join(pe.itertext()).strip()
    if cur_plot and cur_plot != plot_zh:
        _set_text_if_empty(root_el, "plotoriginal", cur_plot, force=False)
    _set_text_if_empty(root_el, "plot", plot_zh, force=True)
    _set_text_if_empty(root_el, "outline", plot_zh, force=True)

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
) -> dict[str, Any]:
    """详情页单番号刷新：默认全量覆盖（重刮 → 覆盖 NFO → 重写向量）。"""
    iid = str(item_id or "").strip()
    if not iid:
        raise ValueError("itemId 必填")
    force = bool(overwrite)

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

        # 覆盖：先清空该条向量，再刮削写回（失败则尽量回滚提示）
        if force and not dry_run:
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
        )

        # 覆盖失败且已删向量：尝试用旧 NFO 救回一条，避免详情变 404
        if force and not dry_run and not one.get("ok"):
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
            _enrich_job["result"] = out
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

    requested = [str(r).strip() for r in (regions or []) if str(r).strip()]
    if not requested:
        one = str(region or "").strip()
        if one:
            requested = [one]
    enabled = set(strat.enabled_region_ids())
    if requested:
        # 显式指定分区：按请求跑（开关打开即开始，不二次过滤）
        want = set(requested)
        region_list = [r for r in REGION_ORDER if r in want]
        for r in requested:
            if r not in region_list:
                region_list.append(r)
    else:
        region_list = list(enabled)
    if not region_list:
        raise ValueError("未开启任何刮削分区")

    mode_norm = (
        "overwrite"
        if str(mode or "").strip().lower() in {"overwrite", "cover", "force", "replace"}
        else "incremental"
    )

    with _enrich_lock:
        if _enrich_job["running"]:
            raise RuntimeError("刮削补齐已在运行")
        if embed_svc.get_job_status().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        prev_logs = dict(_enrich_job.get("regionLogs") or {})
        resume_map: dict[str, dict[str, Any]] = {}
        cps = dict(_enrich_job.get("checkpoints") or {})
        for rid in region_list:
            raw = cps.get(rid)
            if not isinstance(raw, dict):
                continue
            if bool(raw.get("dryRun")) != bool(dry_run):
                continue
            if str(raw.get("mode") or "incremental") != mode_norm:
                continue
            if not list(raw.get("queue") or []):
                continue
            resume_map[rid] = dict(raw)
            cps.pop(rid, None)
        _enrich_job["checkpoints"] = cps
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
        _enrich_job.update(
            {
                "running": True,
                "phase": "starting",
                "progress": {
                    "stage": "prepare",
                    "done": 0,
                    "total": 0,
                    "percent": 0,
                    "ok": 0,
                    "failed": 0,
                    "label": "继续" if keep_log else "starting",
                },
                "log": list(_enrich_job.get("log") or [])[-40:] if keep_log else [],
                "regionLogs": region_logs,
                "currentRegion": "",
                "cancel": False,
                "halt": None,
                "queue": [],
                "current": None,
                "result": None,
                "error": None,
            }
        )

    # 非续跑分区：清掉历史日志，避免 UI 角标一开就是 200
    for rid in region_list:
        if rid not in resume_map:
            _clear_enrich_logs(region=rid)

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
                        _clear_enrich_logs(region=rid)
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
                one = run_enrich(
                    region=rid,
                    kinds=list(cp.get("kinds") or kinds or []) if cp else kinds,
                    limit=use_lim,
                    dry_run=dry_run,
                    mode=mode_norm,
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
                if budget is not None and not cp:
                    budget = max(0, budget - q)
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
                _enrich_job["result"] = result
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
                        "label": "已停止 · 队列与日志已清除",
                    }
                else:
                    _enrich_job["phase"] = "done"
            if cancelled:
                for rid in region_list:
                    _clear_enrich_logs(region=str(rid))
        except Exception as e:  # noqa: BLE001
            log.exception("scrap library enrich failed")
            with _enrich_lock:
                _enrich_job["error"] = str(e)
                _enrich_job["phase"] = "error"
                log_list = list(_enrich_job.get("log") or [])
                log_list.append(f"失败: {e}")
                _enrich_job["log"] = log_list[-40:]
        finally:
            with _enrich_lock:
                _enrich_job["running"] = False
                _enrich_job["halt"] = None
                _enrich_job["cancel"] = False

    threading.Thread(target=run, name="scrap-library-enrich", daemon=True).start()
    return {"started": True, "resumed": bool(resume_map)}
