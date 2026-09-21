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

# 完整补齐：封面 + 女优/片商/剧情/标题等元数据缺口
_DEFAULT_ENRICH_KINDS = tuple(_ENRICH_KINDS)

# 批量补齐同时处理的番号数（策略 itemWorkers 未读到时的回退）。
# 封面另有独立 job 池限流；元数据并发可略高于旧默认。
_ITEM_WORKERS_DEFAULT = 6
_ITEM_WORKERS_MAX = 16
# 封面 job 池：≥ 番号并发并留余量；池线程按上限常开，实际并发用闸门跟随策略。
_COVER_JOB_WORKERS_MIN = 8
_COVER_JOB_WORKERS_MAX = 16
_COVER_JOB_WORKERS = _COVER_JOB_WORKERS_MAX  # ThreadPool 硬上限
_SOURCE_WORKERS_MAX = 64
# 内存里只留最近 N 条结果摘要，避免万级刮削拖垮 GC
_RESULTS_MEM_CAP = 80
# done 日志保留条数；跑中定期裁剪，减轻 COUNT/UPDATE 热路径
_QUEUE_LOG_DONE_KEEP = 4000
_QUEUE_LOG_PRUNE_EVERY = 40

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


_NAME_PAIR_CENSOR_RESTORE = (
    (re.compile(r"輪\s*[●○*＊※]\s*姦?"), "輪姦"),
    (re.compile(r"轮\s*[●○*＊※]\s*姦?"), "轮姦"),
    (re.compile(r"強\s*[●○*＊※]\s*姦?"), "強姦"),
    (re.compile(r"强\s*[●○*＊※]\s*姦?"), "强姦"),
    (re.compile(r"中\s*[●○*＊※]\s*し"), "中出し"),
    (re.compile(r"レ\s*[●○*＊※]\s*プ"), "レイプ"),
    (re.compile(r"リ\s*[●○*＊※]\s*プ"), "レイプ"),
)


def _looks_like_actor_sentence_frag(name: str) -> bool:
    """标题句段/助词串误当女优名（STARS-902：好きだった男が強）。

    注意：假名艺名常含「を/が」（山本かをり）——短「姓+名读」不当句子。
    """
    n = str(name or "").strip()
    if len(n) < 4:
        return False
    # 常见日文姓名形：1～4 汉字姓 + 假名名（可含 を/が）
    if re.fullmatch(r"[一-龥々〆ヵヶ]{1,4}[ぁ-んァ-ンー･・]{1,8}", n):
        return False
    if re.fullmatch(r"[ぁ-んァ-ンー･・]{2,12}", n):
        return False
    # 标题句段硬特征
    if any(
        m in n
        for m in ("だった", "です", "ます", "好き", "とき", "から", "まで", "男が", "女が")
    ):
        return True
    # 助词夹在较长短语中间才当句子（避开短艺名）
    if len(n) >= 6 and re.search(r"[一-龥ぁ-んァ-ン]{2,}[がをにはへでも][一-龥ァ-ンぁ-ん]", n):
        return True
    # 过长假名/汉字混杂短语
    if len(n) >= 8 and re.search(r"[ぁ-ん]", n) and re.search(r"[一-龥ァ-ン]", n):
        if not re.fullmatch(r"[一-龥々]{1,4}[ぁ-んァ-ンー･・\s]{1,10}", n):
            return True
    return False


def _is_platform_exclusivity_label(text: str) -> bool:
    """DMM独家 / FANZA独占 / 独家配信 等发行渠道标签，不是女优名。"""
    t = str(text or "").strip()
    if not t:
        return False
    tl = t.casefold()
    if tl in {
        "dmm独家",
        "dmm獨家",
        "fanza独占",
        "fanza獨占",
        "独家配信",
        "独家發送",
        "独占配信",
        "獨占配信",
        "配信限定",
        "独家",
        "獨家",
        "独占",
        "獨占",
    }:
        return True
    if re.search(r"(?i)(dmm|fanza|mgstage|prestige|sod)\s*(独家|獨家|独占|獨占|专卖|專賣|専売)", t):
        return True
    if re.search(r"(独家|獨家|独占|獨占).*(配信|发送|發送|限定)", t):
        return True
    return False


# 行为/体位/体型/道具类标签碎片（曾被当成纯假名「艺名」写入 <actor>）
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


def _looks_like_act_tag_token(name: str) -> bool:
    """类型/玩法标签，不是女优名。"""
    t = str(name or "").strip()
    if not t:
        return False
    if t in _JUNK_ACTOR_TAGS or t.casefold() in _JUNK_ACTOR_TAGS:
        return True
    if _ACT_TAG_FRAG_RE.search(t):
        return True
    # 叠词玩法（イチャイチャ / モジモジ）
    if re.fullmatch(r"([ぁ-んァ-ン]{2,4})\1", t):
        return True
    return False


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


def _looks_like_person_name_tag(tag: str) -> bool:
    """标签里误塞的女优名（仅识别用；**禁止**再升格进 actor）。"""
    t = str(tag or "").strip()
    if not t or len(t) < 2 or len(t) > 16:
        return False
    if _is_platform_exclusivity_label(t):
        return False
    if _looks_like_act_tag_token(t):
        return False
    key = t.casefold()
    if key in _JUNK_ACTORS or key in _JUNK_ACTOR_TAGS or t in _JUNK_TITLE_MARKERS:
        return False
    if any(s in t for s in _JUNK_ACTOR_SUBSTR):
        return False
    if t.startswith(("系列", "片商", "发行", "發行", "廠商", "厂商", "导演", "導演")):
        return False
    if "/" in t or "|" in t or "／" in t:
        return False
    # 片商/企划长假名（オーロラプロジェクト・アネックス）——勿误伤西洋名「キャンディ・雏・パークス」
    if "プロジェクト" in t or "アネックス" in t or "スタジオ" in t:
        return False
    if "project" in key or "studio" in key:
        return False
    # 前缀/番号
    if re.fullmatch(r"[A-Z]{2,10}-?\d{0,5}[A-Z0-9]*", t, re.I):
        return False
    if _looks_like_actor_sentence_frag(t):
        return False
    return _is_plausible_actress_name(t)


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
    # 助词/句段：タイトル「強×わいせつ」误拆出「好きだった男が強」（STARS-902）
    frag_hint = (
        "に",
        "を",
        "た",
        "が",
        "は",
        "で",
        "の",
        "と",
        "され",
        "だった",
        "好き",
        "とき",
        "男",
        "女",
        "中出",
        "隣人",
        "人妻",
        "夫",
        "妻",
    )
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
            # 句段残片（な隣人に中出しレ × プされ… / 好きだった男が強×わいせつ）
            if sum(1 for h in frag_hint if h in n) >= 2:
                continue
            if _looks_like_actor_sentence_frag(n):
                continue
            seen.add(n)
            out.append(n)
    return out


def _actress_disp_id(name: str) -> tuple[str, str]:
    """(展示名, 身份键)。映射命中用 canon；否则折叠字形。"""
    raw = str(name or "").strip()
    if not raw:
        return "", ""
    try:
        from app.scrape.metadata_optimize import (
            _actor_identity_key,
            polish_actress_names,
        )

        polished = polish_actress_names([raw])
        disp = (polished[0] if polished else raw).strip() or raw
        return disp, (_actor_identity_key(disp) or disp.casefold())
    except Exception:  # noqa: BLE001
        return raw, raw.casefold()


def _unique_identity_names(names: list[str] | None) -> list[str]:
    """名单按身份去重；保留首次原文写法（标题尾名不被映射名盖掉）。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in names or []:
        s = str(raw or "").strip()
        if not s:
            continue
        _disp, kid = _actress_disp_id(s)
        if not kid or kid in seen:
            continue
        seen.add(kid)
        out.append(s)
    return out


def _estimate_cast_size(
    actor_lists: list[tuple[str, list[str], int]],
    *,
    title_pair_n: int = 0,
) -> int:
    """各源身份人数众数估计本片女优数。标题 × 对数可抬高下限。"""
    from collections import Counter

    counts: list[int] = []
    for _sid, names, _sc in actor_lists or []:
        n = len(_unique_identity_names(list(names or [])))
        if n > 0:
            counts.append(n)
    if not counts:
        return max(1, min(int(title_pair_n or 0), 12)) if title_pair_n else 0
    tallies = Counter(counts).most_common()
    mode_n, mode_cnt = tallies[0]
    tied = [n for n, cnt in tallies if cnt == mode_cnt]
    # 平票偏保守取小，避免噪声源把 2 人抬成 3/4；真多人靠「≥2 源共识簇」再抬回
    est = min(tied) if len(tied) > 1 else mode_n
    try:
        from statistics import median

        med = int(median(counts))
        if med != est:
            est = min(est, med)
    except Exception:  # noqa: BLE001
        pass
    if title_pair_n >= 2:
        est = max(est, min(title_pair_n, 12))
    return max(1, min(int(est), 12))


def _collapse_few_actress_variants(
    actors: list[str],
    actor_lists: list[tuple[str, list[str], int]],
    *,
    title_pair_n: int = 0,
) -> tuple[list[str], list[str]]:
    """按「身份簇 + 各源人数」收口女优名单。

    - 估计人数 = 各源身份数众数（标题 × 可抬下限）
    - 同人异写（日/中/别名）并入同一簇；多出的簇按票数裁掉
    - 仅单人时返回 aliases；多人只返回一人一展示名
    """
    out = [str(a).strip() for a in (actors or []) if str(a or "").strip()]
    if not out and not actor_lists:
        return [], []

    spellings: list[str] = []
    seen_sp: set[str] = set()
    vote: dict[str, int] = {}

    def _add_spelling(raw: str, *, weight: int = 1) -> None:
        s = str(raw or "").strip()
        if not s:
            return
        fold = s.casefold()
        if fold not in seen_sp:
            seen_sp.add(fold)
            spellings.append(s)
        if weight <= 0:
            return
        _d, kid = _actress_disp_id(s)
        if kid:
            vote[kid] = int(vote.get(kid) or 0) + int(weight)

    for _sid, names, sc in actor_lists or []:
        # 同源内先按身份去重再计票，避免同人写两次刷票
        local = _unique_identity_names(list(names or []))
        # 仍保留原写法进别名池
        for a in names or []:
            _add_spelling(str(a or ""), weight=0)
        for a in local:
            _add_spelling(a, weight=1)
        _ = sc

    for a in out:
        _add_spelling(a, weight=1)

    # 身份簇：id → 展示候选
    clusters: dict[str, list[str]] = {}
    for raw in spellings:
        disp, kid = _actress_disp_id(raw)
        if not kid:
            continue
        clusters.setdefault(kid, [])
        if raw not in clusters[kid]:
            clusters[kid].append(raw)
        if disp not in clusters[kid]:
            clusters[kid].append(disp)

    if not clusters:
        return _unique_identity_names(out), []

    est = _estimate_cast_size(actor_lists, title_pair_n=title_pair_n)
    if est <= 0:
        est = min(len(clusters), len(_unique_identity_names(out)) or len(clusters))

    # 簇排序：票数 → 已在 out 中
    out_ids = {_actress_disp_id(a)[1] for a in out if _actress_disp_id(a)[1]}

    def _rank(kid: str) -> tuple[int, int]:
        return (
            int(vote.get(kid) or 0),
            1 if kid in out_ids else 0,
        )

    ranked = sorted(clusters.keys(), key=_rank, reverse=True)
    # ≥2 源共识的不同身份 → 人数下限抬到共识人数（防真多人被压成 1）
    # 但若多数源本身只报 1 人，则不因「单源双写别名」抬高（DOJN-001：なお+奈绪）
    strong = [kid for kid in ranked if int(vote.get(kid) or 0) >= 2]
    src_counts = [
        len(_unique_identity_names(list(names or [])))
        for _sid, names, _sc in (actor_lists or [])
        if names
    ]
    ones = sum(1 for c in src_counts if c == 1)
    majority_solo = bool(src_counts) and ones * 2 > len(src_counts)
    if len(strong) >= 2 and not (est <= 1 and majority_solo):
        est = max(est, len(strong))
    keep_ids = ranked[: max(1, est)]

    # 强单人：多数源只有 1 人，或仅 1 个高票簇明显领先
    if est == 1 or (len(keep_ids) == 1):
        kid = keep_ids[0]
        cands = clusters[kid]
        primary = ""
        for a in out:
            if _actress_disp_id(a)[1] == kid:
                primary = a
                break
        if not primary:
            primary = _actress_disp_id(cands[0])[0] or cands[0]
        aliases: list[str] = []
        seen_al = {primary.casefold()}
        # 单人：其它簇也并作别名（映射漏网的同人异写）
        extra_pool = list(cands)
        if est == 1:
            for oid in ranked:
                if oid == kid:
                    continue
                extra_pool.extend(clusters[oid])
        for x in extra_pool:
            if not x or x.casefold() in seen_al:
                continue
            seen_al.add(x.casefold())
            aliases.append(x)
        return [primary], aliases[:16]

    # 多人：一人一展示名
    display: list[str] = []
    seen_disp: set[str] = set()
    for kid in keep_ids:
        cands = clusters[kid]
        pick = ""
        for a in out:
            if _actress_disp_id(a)[1] == kid:
                pick = a
                break
        if not pick:
            pick = _actress_disp_id(cands[0])[0] or cands[0]
        fold = pick.casefold()
        if fold in seen_disp:
            continue
        seen_disp.add(fold)
        display.append(pick)
    return display[:12], []


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


def _actors_lifted_from_tags(tags: list[str] | None) -> list[str]:
    """已废弃：禁止从标签升格女优（保留空实现，兼容旧调用/测试）。"""
    del tags
    return []

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
        if _is_platform_exclusivity_label(raw_tag) or _is_platform_exclusivity_label(tag):
            continue
        # 渠道/马赛克类噪声（大小写不敏感）
        if any(s in key for s in ("数位马赛克", "數字馬賽克", "数字马赛克", "數位馬賽克")):
            continue
        # 前缀代号单独成标签（ALDN / ABP）无信息量
        if re.fullmatch(r"[A-Z]{2,10}", tag, re.I):
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


_enrich_lock = threading.RLock()
# 策略保存代数：运行中下一番号检测到变化即热切数据源/超时
_strategy_epoch = 0
_strategy_epoch_mu = threading.Lock()
# 运行中把失败重试插到下一轮投递（优先于原队列）
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

# SSE 订阅：状态变更时唤醒（替代前端 450ms 轮询）
_enrich_watchers_lock = threading.Lock()
_enrich_watchers: list[threading.Event] = []
_enrich_notify_last = 0.0
_ENRICH_NOTIFY_MIN_GAP = 0.7
# force（阶段切换）也必须留地板：10 番号并发时每条 item 有 2~3 次 force 通知，
# 完全不节流会让 SSE 每帧重建一次状态快照，把 worker / 前端主线程吃光。
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


_ENRICH_LOG_KEEP = 2000
# 状态接口回传本轮尾部；角标按内存实际条数（见 regionLogCounts）
# 200 行 × SSE 高频会拖垮设置页；详情日志另有 /enrich/logs
_ENRICH_LOG_RETURN = 40
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
    """落库/内存统一用稳定 id，避免 日本有码 / japan_censored 分裂。

    注意：禁止在已持有 _enrich_lock 时再 acquire（旧 Lock 会死锁）。
    空 region 时无锁读 currentRegion（可接受极短竞态）。
    """
    raw = str(region or "").strip()
    if not raw:
        raw = str(_enrich_job.get("currentRegion") or "").strip()
    if not raw:
        return "_all"
    from app.core.region_meta import REGION_META

    # 旧逻辑区 fc2_ppv 并回物理 FC2（设置页已合并为一类）
    if raw in {"fc2_ppv", "FC2-PPV 番号", "FC2PPV"}:
        return "fc2"
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


# 运行日志落库缓冲：攒批 + 后台线程写，`push()` 不阻塞调用线程。
# 见 `enrich_log_sink.LogBatcher` 的取舍说明（丢最后 ≤2s 可接受、
# 实时展示走内存 `_enrich_job["log"]`、清空日志必须先 `discard`）。
_enrich_log_sink = enrich_log_sink.LogBatcher(
    _write_enrich_log_batch, flush_sec=0.25, max_delay=3.0, min_rows=24, label="enrich_log"
)


def _persist_enrich_log(region: str, text: str) -> None:
    """刮削日志落元库（**异步攒批**），重启后仍可查。

    ⚠️ 语义变化（第九轮）：返回时只保证「已入缓冲」，不保证已落库。
    需要读回刚写的内容（探针/收尾）请先 `flush_enrich_logs()`。
    """
    rid = _canonical_enrich_log_region(region)
    line = str(text or "").strip()
    if not line:
        return
    _enrich_log_sink.push(rid, line)


def flush_enrich_logs() -> None:
    """把缓冲里的日志立刻写库（任务收尾 / 探针 / 清空日志前用）。"""
    _enrich_log_sink.flush()


def enrich_log_sink_stats() -> dict[str, int]:
    """缓冲状态（诊断用）：pending / written / dropped。"""
    return _enrich_log_sink.stats()


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


# 空闲态历史日志回填缓存：get_enrich_status 会遍历全部 7 个分区各查一次元库
# （~6ms/次），而它只用于「历史日志」展示，秒级延迟无感。
_hist_log_cache: dict[tuple[str, int], tuple[float, list[str]]] = {}
_HIST_LOG_TTL_SEC = 3.0


def _load_enrich_logs_cached(region: str, limit: int) -> list[str]:
    key = (str(region or ""), int(limit))
    hit = _hist_log_cache.get(key)
    if hit and (time.monotonic() - float(hit[0])) < _HIST_LOG_TTL_SEC:
        return list(hit[1])
    rows = load_enrich_logs(region=region, limit=limit)
    if len(_hist_log_cache) > 64:
        _hist_log_cache.clear()
    _hist_log_cache[key] = (time.monotonic(), list(rows))
    return rows


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


def _clear_enrich_logs(*, region: str = "", wipe_all_tail: bool = True) -> None:
    """清分区运行日志（内存 + 元库）；暂停绝不能调用。"""
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

        # ⚠️ 必须先丢掉**未落库**的缓冲行：否则 DELETE 之后后台线程再 flush，
        # 刚清掉的日志又被写回来（`discard` 与写库共用 `_io_lock`，不会交错）。
        if not rid:
            _enrich_log_sink.discard(None)
        else:
            drop_keys = set(keys) | {_canonical_enrich_log_region(rid)}
            if wipe_all_tail:
                drop_keys.add("_all")
            for k in drop_keys:
                _enrich_log_sink.discard(k)
        init_db()
        with connect() as conn:
            if rid:
                for k in keys:
                    conn.execute("DELETE FROM enrich_logs WHERE region = ?", (k,))
                # 兼容历史脏键 + 无分区时落到 _all 的尾日志
                canon = _canonical_enrich_log_region(rid)
                conn.execute("DELETE FROM enrich_logs WHERE region = ?", (canon,))
                if wipe_all_tail:
                    conn.execute("DELETE FROM enrich_logs WHERE region = ?", ("_all",))
            else:
                conn.execute("DELETE FROM enrich_logs")
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("clear enrich logs failed region=%s: %s", rid or "*", e)


def clear_enrich_logs(*, region: str = "") -> dict[str, Any]:
    """清空刮削日志表（文本日志 + 队列记录）并丢掉该区旧检查点。

    清空·扫描后必须以队列表/新扫描为准，不能再让历史 checkpoint
    （如 fail=622）顶掉真实角标。
    已暂停/停止（halt）时允许清空，即使 worker 尚未把 running 置 False。
    """
    rid = _queue_log_region(region) or str(region or "").strip()

    running = False
    cur = ""
    halt = None
    phase = ""
    if not _enrich_lock.acquire(timeout=2.0):
        # 锁被卡：仍允许清库（用户已点暂停），内存态尽量事后对齐
        log.warning("clear_enrich_logs lock busy region=%s — force clear db", rid)
        running = bool(_enrich_job.get("running"))
        cur = _queue_log_region(str(_enrich_job.get("currentRegion") or ""))
        halt = _enrich_job.get("halt")
        phase = str(_enrich_job.get("phase") or "")
        locked = False
    else:
        locked = True
        try:
            running = bool(_enrich_job.get("running"))
            cur = _queue_log_region(str(_enrich_job.get("currentRegion") or ""))
            halt = _enrich_job.get("halt")
            phase = str(_enrich_job.get("phase") or "")
            # 真正在跑且未暂停/停止：拒绝硬清
            paused_like = halt in {"pause", "stop"} or phase in {
                "paused",
                "stopping",
                "stopped",
            }
            if running and rid and cur == rid and not paused_like:
                return {
                    "ok": False,
                    "cleared": False,
                    "busy": True,
                    "error": "刮削进行中，请先暂停再清空·扫描",
                    "region": rid or None,
                }
            # 暂停收尾中：打断残留 running，避免 UI/清空一直以为在刮
            if paused_like and running and rid and cur == rid:
                _enrich_job["running"] = False
                _enrich_job["halt"] = "stop"
                _enrich_job["phase"] = "stopped"
                running = False
        finally:
            if locked:
                _enrich_lock.release()

    _clear_enrich_logs(region=rid, wipe_all_tail=False)
    _clear_queue_log(region=rid)
    _clear_local_status_totals(rid)
    _invalidate_classified_skip_cache(rid)
    if rid:
        _pending_backfill_done.discard(rid)
    else:
        _pending_backfill_done.clear()
    cleared_cp = False
    got_lock = _enrich_lock.acquire(timeout=2.0)
    try:
        if got_lock:
            running = bool(_enrich_job.get("running"))
            cur = _queue_log_region(str(_enrich_job.get("currentRegion") or ""))
            halt = _enrich_job.get("halt")
            phase = str(_enrich_job.get("phase") or "")
            paused_like = halt in {"pause", "stop"} or phase in {
                "paused",
                "stopping",
                "stopped",
            }
            if paused_like:
                _enrich_job["running"] = False
                running = False
            # 非本区运行中才清检查点；本区已暂停/空闲都清
            if rid and (not running or cur != rid or paused_like):
                cps = dict(_enrich_job.get("checkpoints") or {})
                if rid in cps or any(
                    _queue_log_region(str(k)) == rid for k in list(cps.keys())
                ):
                    for k in list(cps.keys()):
                        if _queue_log_region(str(k)) == rid or str(k) == rid:
                            cps.pop(k, None)
                            cleared_cp = True
                    _enrich_job["checkpoints"] = cps
                prog = dict(_enrich_job.get("progress") or {})
                if prog:
                    prog.update(
                        {
                            "done": 0,
                            "ok": 0,
                            "failed": 0,
                            "percent": 0,
                            "label": "已清空",
                            "stage": "idle",
                        }
                    )
                    _enrich_job["progress"] = prog
                result = _enrich_job.get("result")
                if isinstance(result, dict):
                    _enrich_job["result"] = {
                        **result,
                        "ok": 0,
                        "failed": 0,
                        "queued": 0,
                    }
                _enrich_job["queue"] = []
                _enrich_job["queueCounts"] = {
                    "pending": 0,
                    "running": 0,
                    "done": 0,
                    "fail": 0,
                }
                _enrich_job["phase"] = ""
                _enrich_job["halt"] = None
                _enrich_job["paused"] = False
                _enrich_job["cancel"] = False
                if cur == rid:
                    _enrich_job["currentRegion"] = ""
                    _enrich_job["current"] = None
    finally:
        if got_lock:
            _enrich_lock.release()
    if cleared_cp or rid:
        try:
            _persist_enrich_runtime()
        except Exception as e:  # noqa: BLE001
            log.warning("persist after clear enrich logs failed: %s", e)
    try:
        notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "cleared": True,
        "checkpointCleared": bool(cleared_cp),
        "region": rid or None,
    }


_QUEUE_LOG_STATUSES = ("pending", "running", "done", "fail")
# 列表/角标筛选别名：soft = done 且 partialOk（库内仍存 status=done）
_QUEUE_LOG_FILTER_STATUSES = (*_QUEUE_LOG_STATUSES, "soft")
_QUEUE_LOG_PAYLOAD_KEYS = (
    "actors",
    "nfoChanged",
    "posterDownloaded",
    "vectorSynced",
    "vectorSkipped",
    "vectorError",
    "sourceTimings",
    "fields",
    "wouldFill",
    "rel_path",
    "relPath",
    "coverMs",
    "coverFail",
    "coverTried",
    "coverAttempts",
    "actressMs",
    "vectorMs",
    "totalMs",
    "partialOk",
    "gapsAfter",
    "softActressRetry",
)


def _queue_log_region(region: str | None = None) -> str:
    rid = _canonical_enrich_log_region(region or "")
    return "" if rid == "_all" else rid


# 角标计数短缓存：SSE/轮询每秒会问很多次同一个分区。
# ⚠️ 禁止在计数前跑 `_ensure_actress_soft_promoted`：有码区 done/fail 可达 10 万+，
# demote 会对每行做磁盘校验，卡住 GET /enrich/status，进而拖死整页设置接口。
_counts_cache: dict[str, tuple[float, dict[str, int]]] = {}
_COUNTS_CACHE_TTL_SEC = 1.2
# 清空·扫描后的本地全量角标（队列表写全部分类行供翻页；角标与 DB 对齐，落盘防重启丢失）
# 必须落盘：仅内存时 API 重启后角标会退回库内计数
_LOCAL_STATUS_TOTALS: dict[str, dict[str, int]] = {}
_LOCAL_STATUS_TOTALS_LOADED = False
_LOCAL_STATUS_TOTALS_LOCK = threading.Lock()


def _local_status_totals_path() -> Path:
    return media_dir() / "scrap-library" / "_local_status_totals.json"


def _persist_local_status_totals() -> None:
    try:
        from app.core.atomic_io import atomic_write_bytes

        payload = {
            "v": 1,
            "regions": {
                rid: {
                    "done": int(v.get("done") or 0),
                    "soft": int(v.get("soft") or 0),
                    "fail": int(v.get("fail") or 0),
                    **(
                        {"total": int(v.get("total") or 0)}
                        if int(v.get("total") or 0) > 0
                        else {}
                    ),
                }
                for rid, v in _LOCAL_STATUS_TOTALS.items()
                if rid and isinstance(v, dict)
            },
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        atomic_write_bytes(_local_status_totals_path(), raw)
    except Exception as e:  # noqa: BLE001
        log.debug("persist local status totals failed: %s", e)


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


def _set_local_status_totals(
    region: str,
    *,
    done: int = 0,
    soft: int = 0,
    fail: int = 0,
    total: int | None = None,
) -> None:
    rid = _queue_log_region(region)
    if not rid:
        return
    _ensure_local_status_totals_loaded()
    prev = _LOCAL_STATUS_TOTALS.get(rid) or {}
    row: dict[str, int] = {
        "done": max(0, int(done or 0)),
        "soft": max(0, int(soft or 0)),
        "fail": max(0, int(fail or 0)),
    }
    tot = int(prev.get("total") or 0) if total is None else max(0, int(total or 0))
    if tot > 0:
        row["total"] = tot
    _LOCAL_STATUS_TOTALS[rid] = row
    _counts_cache.pop(rid, None)
    _persist_local_status_totals()


def _clear_local_status_totals(region: str = "") -> None:
    _ensure_local_status_totals_loaded()
    rid = _queue_log_region(region) if str(region or "").strip() else ""
    if rid:
        _LOCAL_STATUS_TOTALS.pop(rid, None)
        _counts_cache.pop(rid, None)
    else:
        _LOCAL_STATUS_TOTALS.clear()
        _counts_cache.clear()
    _persist_local_status_totals()


def _apply_local_status_totals(counts: dict[str, int], region: str) -> dict[str, int]:
    """扫描 tip 与库内计数合并。

    - 库分类全 0：用 tip（避免空库盖掉扫描角标）
    - 库有分类：done/fail 取大；soft **以库为准**（软成功升完整成功后必须能下降，
      禁止 tip.soft=1898 把 DB soft=57 永久钉死）
    """
    _ensure_local_status_totals_loaded()
    rid = _queue_log_region(region)
    tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
    db_d = int(counts.get("done") or 0)
    db_s = int(counts.get("soft") or 0)
    db_f = int(counts.get("fail") or 0)
    db_sum = db_d + db_s + db_f
    out = dict(counts)
    if not tip:
        # 热重载后 tip 空但库有数 → 立刻回种，避免 pending 角标按「全未处理」算
        if rid and db_sum > 0:
            _set_local_status_totals(
                rid, done=db_d, soft=db_s, fail=db_f, total=None
            )
        return out
    tip_d = int(tip.get("done") or 0)
    tip_s = int(tip.get("soft") or 0)
    tip_f = int(tip.get("fail") or 0)
    if db_sum <= 0:
        out["done"] = tip_d
        out["soft"] = tip_s
        out["fail"] = tip_f
        return out
    out["done"] = max(tip_d, db_d)
    out["fail"] = max(tip_f, db_f)
    out["soft"] = db_s
    # tip.soft 虚高时回写，避免 _region_library_progress 仍读旧 tip
    if tip_s != db_s or tip_d < out["done"] or tip_f < out["fail"]:
        _set_local_status_totals(
            rid,
            done=out["done"],
            soft=db_s,
            fail=out["fail"],
            total=int(tip.get("total") or 0) or None,
        )
    return out


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
    soft = max(int(tip.get("soft") or 0), int(counts.get("soft") or 0))
    fail = max(int(tip.get("fail") or 0), int(counts.get("fail") or 0))
    tot = int(tip.get("total") or 0)
    if (
        done == int(tip.get("done") or 0)
        and soft == int(tip.get("soft") or 0)
        and fail == int(tip.get("fail") or 0)
    ):
        return
    _set_local_status_totals(rid, done=done, soft=soft, fail=fail, total=tot or None)


# 队列扫描进度（供 SSE/状态接口边扫边看；与刮削 progress 分开）
_QUEUE_SCAN_LOCK = threading.Lock()
_QUEUE_SCAN_SAMPLE_CAP = 80  # 边扫边看：每态最多推送样例条数
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
    "samplesDone": [],
    "samplesSoft": [],
    "samplesFail": [],
    "updatedAt": 0.0,
}
_QUEUE_SCAN_NOTIFY_GAP = 0.35
_queue_scan_notify_last = 0.0


def _queue_scan_preview_item(
    *,
    rel: str,
    code: str,
    gaps: list[str],
    region: str,
    kind: str,
) -> dict[str, Any]:
    """扫描中预览行（轻量，不读 sidecar）。"""
    code_u = str(code or "").strip().upper()
    rid = str(region or "").strip()
    item: dict[str, Any] = {
        "itemId": rel,
        "code": code_u,
        "gaps": list(gaps or []),
        "gapsAfter": list(gaps or []),
        "rel_path": rel,
        "relPath": rel,
        "region": rid,
        "source": "local_scan",
    }
    if kind == "done":
        item["status"] = "done"
        item["partialOk"] = False
        item["error"] = ""
    elif kind == "soft":
        soft_gaps = [g for g in gaps if g in _SOFT_SUCCESS_GAPS]
        labels = _gap_labels(soft_gaps)
        item["status"] = "done"
        item["partialOk"] = True
        item["error"] = _format_soft_ok_error(labels or ["女优"])
        item["gapsAfter"] = soft_gaps
    else:
        block = [g for g in gaps if g in _SUCCESS_BLOCK_GAPS] or list(gaps or [])
        labels = _gap_labels(block)
        item["status"] = "fail"
        item["partialOk"] = False
        item["error"] = f"仍缺:{' · '.join(labels)}" if labels else "仍缺:封面"
    return item


def _queue_scan_snapshot() -> dict[str, Any] | None:
    with _QUEUE_SCAN_LOCK:
        if not _QUEUE_SCAN_STATE.get("active"):
            return None
        return {
            "active": True,
            "region": str(_QUEUE_SCAN_STATE.get("region") or ""),
            "stage": str(_QUEUE_SCAN_STATE.get("stage") or ""),
            "label": str(_QUEUE_SCAN_STATE.get("label") or ""),
            "scanned": int(_QUEUE_SCAN_STATE.get("scanned") or 0),
            "total": int(_QUEUE_SCAN_STATE.get("total") or 0),
            "done": int(_QUEUE_SCAN_STATE.get("done") or 0),
            "soft": int(_QUEUE_SCAN_STATE.get("soft") or 0),
            "fail": int(_QUEUE_SCAN_STATE.get("fail") or 0),
            "samplesDone": list(_QUEUE_SCAN_STATE.get("samplesDone") or []),
            "samplesSoft": list(_QUEUE_SCAN_STATE.get("samplesSoft") or []),
            "samplesFail": list(_QUEUE_SCAN_STATE.get("samplesFail") or []),
        }


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


def _queue_scan_add_sample(kind: str, item: dict[str, Any]) -> None:
    """边扫边把样例推入状态，供前端提前展示列表。"""
    key = {
        "done": "samplesDone",
        "soft": "samplesSoft",
        "fail": "samplesFail",
    }.get(str(kind or "").strip())
    if not key or not isinstance(item, dict):
        return
    with _QUEUE_SCAN_LOCK:
        if not _QUEUE_SCAN_STATE.get("active"):
            return
        bucket = _QUEUE_SCAN_STATE.get(key)
        if not isinstance(bucket, list):
            bucket = []
            _QUEUE_SCAN_STATE[key] = bucket
        if len(bucket) >= _QUEUE_SCAN_SAMPLE_CAP:
            return
        code_u = str(item.get("code") or "").strip().upper()
        iid = str(item.get("itemId") or "").strip()
        for old in bucket:
            if not isinstance(old, dict):
                continue
            if iid and str(old.get("itemId") or "") == iid:
                return
            if code_u and str(old.get("code") or "").strip().upper() == code_u:
                return
        bucket.append(item)


def _clear_queue_scan_progress() -> None:
    _set_queue_scan_progress(active=False, notify=True)


def _queue_log_status_counts_db(region: str) -> dict[str, int]:
    """队列表真实计数（不含本地全量 overlay）。"""
    rid = _queue_log_region(region)
    out = _empty_queue_counts()
    if not rid:
        return out
    try:
        from app.core.db import connect, init_db

        init_db()
        soft_pred = _soft_done_sql_pred(error_col="error")
        with connect() as conn:
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
                n = int((row.get("n") if isinstance(row, dict) else row[1]) or 0)
                if key in out:
                    out[key] = n
    except Exception as e:  # noqa: BLE001
        log.debug("queue log status counts db failed region=%s: %s", rid, e)
    return out


def _queue_log_status_counts(region: str, *, fresh: bool = False) -> dict[str, int]:
    """队列表按 status 计数（角标用；done 再拆完整成功 / 软成功）。

    默认走 ~1.2s 短缓存：状态接口/轮询高频重复查询同一个分区时，1 秒级的
    角标延迟不可见，但能把「每帧一次 DB + 一次纠偏扫描」的固定开销摊掉。
    需要真实值（暂停/结束判定、写检查点）时传 fresh=True。
    """
    rid = _queue_log_region(region)
    out = _empty_queue_counts()
    if not rid:
        return out
    # 纠偏（假成功回滚 / 软成功提升）只在扫描·开刮时跑，绝不挂在状态读路径。
    if not fresh:
        hit = _counts_cache.get(rid)
        if hit and (time.monotonic() - float(hit[0])) < _COUNTS_CACHE_TTL_SEC:
            return dict(hit[1])
    out = _queue_log_status_counts_db(rid)
    out = _apply_local_status_totals(out, rid)
    out = _clamp_pending_badge(out, rid)
    _counts_cache[rid] = (time.monotonic(), dict(out))
    if len(_counts_cache) > 64:
        _counts_cache.clear()
    return out


def _queue_log_int_id(row: dict[str, Any]) -> int:
    raw = row.get("logId")
    if raw is None:
        raw = row.get("log_id")
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _queue_log_payload(row: dict[str, Any], *, base: dict[str, Any] | None = None) -> str:
    extra: dict[str, Any] = {}
    if isinstance(base, dict):
        extra.update(base)

    def _keep_rich(key: str, new_v: Any, old_v: Any) -> Any:
        """空列表/空字段表不要覆盖已有刮削结果。"""
        if key in {"fields", "sourceTimings"}:
            if isinstance(new_v, list) and not new_v and old_v:
                return old_v
            if key == "fields" and isinstance(new_v, list) and isinstance(old_v, list):
                new_src = sum(
                    1
                    for f in new_v
                    if isinstance(f, dict) and str(f.get("source") or "").strip()
                )
                old_src = sum(
                    1
                    for f in old_v
                    if isinstance(f, dict) and str(f.get("source") or "").strip()
                )
                # NFO 回填无站点源时，保留带选用源的旧表
                if old_src > 0 and new_src == 0:
                    return old_v
            if key == "sourceTimings" and isinstance(new_v, list) and isinstance(old_v, list):
                if len(old_v) > len(new_v):
                    return old_v
        return new_v

    for k in _QUEUE_LOG_PAYLOAD_KEYS:
        if k in row and row.get(k) is not None:
            extra[k] = _keep_rich(k, row.get(k), extra.get(k))
    try:
        return json.dumps(extra, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        slim = {
            k: extra.get(k)
            for k in (
                "posterDownloaded",
                "nfoChanged",
                "vectorSynced",
                "vectorSkipped",
                "vectorError",
                "actors",
                "fields",
                "sourceTimings",
                "coverMs",
                "actressMs",
                "vectorMs",
                "totalMs",
            )
            if k in extra
        }
        return json.dumps(slim, ensure_ascii=False, default=str)


def _queue_log_read_payload(conn: Any, lid: int) -> dict[str, Any]:
    if lid <= 0:
        return {}
    try:
        got = conn.execute(
            "SELECT payload_json FROM enrich_queue_log WHERE id=?",
            (lid,),
        ).fetchone()
        if not got:
            return {}
        raw = got["payload_json"] if isinstance(got, dict) else got[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return dict(parsed) if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _detail_from_local_folder(
    folder: Path,
    *,
    code: str = "",
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    """从本地番号目录 NFO + poster 生成展示 detail / fields。

    转移进来的 MDCx NFO 与本系统刮削 NFO 同格式；原先详情只认「刮削结果/向量库」，
    且封面必须是 http 才算有 —— 本地 poster.jpg 会被误报成「无」。
    """
    code_u = str(code or folder.name or "").strip().upper()
    local_ok = False
    try:
        local_ok = bool(_local_poster_ok(folder))
    except Exception:  # noqa: BLE001
        poster = folder / "poster.jpg"
        local_ok = bool(poster.is_file() and poster.stat().st_size >= 400)
    detail: dict[str, Any] = {"code": code_u}
    fields = _fields_after_local_write(
        folder,
        detail,
        local_cover_ok=local_ok,
        poster_url="",
    )
    title = ""
    for f in fields:
        if str(f.get("id") or "") == "title":
            title = str(f.get("value") or "").strip()
            break
    if not title:
        nfo = _find_nfo(folder)
        meta = parse_nfo(nfo) if nfo else None
        if isinstance(meta, dict):
            title = str(meta.get("title") or "").strip()
            code_u = str(meta.get("num") or code_u).strip().upper() or code_u
    out_detail = {
        "code": code_u,
        "title": title,
        "detailTitle": title[:300] if title else "",
        "posterDownloaded": local_ok,
    }
    return out_detail, fields, local_ok


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


def _queue_log_insert_params(
    region: str,
    row: dict[str, Any],
    *,
    payload_base: dict[str, Any] | None = None,
) -> list[Any]:
    st = str(row.get("status") or "pending").strip().lower()
    if st not in _QUEUE_LOG_STATUSES:
        st = "pending"
    fetch_ms = row.get("fetchMs")
    try:
        fetch_i = int(fetch_ms) if fetch_ms is not None else None
    except (TypeError, ValueError):
        fetch_i = None
    return [
        region,
        str(row.get("itemId") or ""),
        str(row.get("code") or "").strip().upper(),
        st,
        json.dumps(list(row.get("gaps") or []), ensure_ascii=False),
        str(row.get("error") or "")[:500],
        str(row.get("source") or ""),
        fetch_i,
        str(row.get("detailTitle") or "")[:300],
        _queue_log_payload(row, base=payload_base),
    ]


def _queue_log_row_to_item(row: dict[str, Any]) -> dict[str, Any]:
    gaps: list[Any] = []
    payload: dict[str, Any] = {}
    try:
        raw_g = row.get("gaps_json") or "[]"
        parsed = json.loads(raw_g) if isinstance(raw_g, str) else raw_g
        if isinstance(parsed, list):
            gaps = parsed
    except Exception:  # noqa: BLE001
        gaps = []
    try:
        raw_p = row.get("payload_json") or "{}"
        parsed_p = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
        if isinstance(parsed_p, dict):
            payload = parsed_p
    except Exception:  # noqa: BLE001
        payload = {}
    st = str(row.get("status") or "pending").strip().lower()
    if st not in _QUEUE_LOG_STATUSES:
        st = "pending"
    fetch_ms = row.get("fetch_ms")
    try:
        fetch_i = int(fetch_ms) if fetch_ms is not None else None
    except (TypeError, ValueError):
        fetch_i = None
    item: dict[str, Any] = {
        "logId": int(row.get("id") or 0),
        "itemId": str(row.get("item_id") or ""),
        "code": str(row.get("code") or ""),
        "gaps": gaps,
        "status": st,
        "error": str(row.get("error") or ""),
        "source": str(row.get("source") or ""),
        "fetchMs": fetch_i,
        "detailTitle": str(row.get("detail_title") or ""),
    }
    for k, v in payload.items():
        if k not in item:
            item[k] = v
    # 完整成功但 gaps_json 未清（历史 bug）：展示层清空缺口，避免「成功还缺封面」
    if st == "done" and not bool(item.get("partialOk")):
        item["gaps"] = []
        if not item.get("gapsAfter"):
            item["gapsAfter"] = []
        # 字段表封面：已落盘则强制 ok，避免陈旧 fields 误报
        if item.get("posterDownloaded") and isinstance(item.get("fields"), list):
            for f in item["fields"]:
                if isinstance(f, dict) and str(f.get("id") or "") == "poster":
                    f["ok"] = True
                    if not str(f.get("value") or "").strip():
                        f["value"] = "已落盘"
    # 伪命中源不展示
    if str(item.get("source") or "").strip() in {"log_recover", "recover"}:
        item["source"] = ""
    return item


def _backfill_queue_item_detail(item: dict[str, Any], *, region: str) -> dict[str, Any]:
    """成功/失败空壳：从 NFO/元库补字段（只补展示；不覆盖已有源耗时/选用源）。"""
    if not isinstance(item, dict):
        return item
    st = str(item.get("status") or "").strip().lower()
    if st not in {"done", "fail"}:
        return item
    fields = item.get("fields")
    has_fields = isinstance(fields, list) and len(fields) > 0
    has_src_fields = has_fields and any(
        isinstance(f, dict) and str(f.get("source") or "").strip()
        for f in fields
    )
    has_timings = isinstance(item.get("sourceTimings"), list) and bool(
        item.get("sourceTimings")
    )
    title = str(item.get("detailTitle") or "").strip()
    # 已有刮削结果（带选用源或源耗时）→ 不回填、不写库
    if (has_src_fields or has_timings) and title:
        if not has_timings:
            item = _merge_enrich_sidecar_into_item(item, region=region)
        return item
    # local_scan 空壳：先读番号目录 enrich.log
    if not has_timings:
        item = _merge_enrich_sidecar_into_item(item, region=region)
        has_timings = isinstance(item.get("sourceTimings"), list) and bool(
            item.get("sourceTimings")
        )
        fields = item.get("fields")
        has_fields = isinstance(fields, list) and len(fields) > 0
        has_src_fields = has_fields and any(
            isinstance(f, dict) and str(f.get("source") or "").strip()
            for f in (fields or [])
        )
        title = str(item.get("detailTitle") or "").strip()
        if (has_src_fields or has_timings) and title:
            return item
    if has_fields and title and not has_src_fields and not has_timings:
        # 仅有 NFO 级字段：仍试本地 enrich.log 补源耗时
        item = _merge_enrich_sidecar_into_item(item, region=region)
        return item
    hydrated = _hydrate_queue_item_from_library(
        code=str(item.get("code") or ""),
        region=region,
        item_id=str(item.get("itemId") or ""),
    )
    if not hydrated:
        return _merge_enrich_sidecar_into_item(item, region=region)
    if hydrated.get("detailTitle") and not title:
        item["detailTitle"] = hydrated["detailTitle"]
    if hydrated.get("itemId") and not item.get("itemId"):
        item["itemId"] = hydrated["itemId"]
    # 本步明确跳过向量时，不要用库里「已有向量行」改成已同步
    if item.get("vectorSkipped"):
        item["vectorSynced"] = False
    elif hydrated.get("vectorSynced") is not None and item.get("vectorSynced") is None:
        item["vectorSynced"] = hydrated.get("vectorSynced")
    if not has_fields and hydrated.get("fields"):
        item["fields"] = hydrated["fields"]
    elif (
        hydrated.get("fields")
        and not has_src_fields
        and not has_timings
        and str(item.get("source") or "").strip()
        in {"", "local_scan", "log_recover", "recover"}
    ):
        # 本地扫描空壳字段（全「无」）用 NFO 覆盖
        item["fields"] = hydrated["fields"]
    if hydrated.get("posterDownloaded"):
        if item.get("posterDownloaded") is None or (
            not has_src_fields and not has_timings
        ):
            item["posterDownloaded"] = hydrated.get("posterDownloaded")
    src = str(item.get("source") or "").strip()
    if src in {"log_recover", "recover"}:
        item["source"] = str(hydrated.get("source") or "").strip()
    # 本地 enrich.log 优先补源耗时（向量/NFO 没有）
    item = _merge_enrich_sidecar_into_item(item, region=region)
    # 只写回缺失的展示字段；绝不传空 sourceTimings（避免冲掉真结果）
    try:
        persist: dict[str, Any] = {
            "logId": item.get("logId"),
            "itemId": item.get("itemId"),
            "code": item.get("code"),
            "status": st,
            "gaps": list(item.get("gaps") or []),
            "error": item.get("error") or "",
            "source": item.get("source") or "",
            "detailTitle": item.get("detailTitle") or "",
        }
        if item.get("fetchMs") is not None:
            persist["fetchMs"] = item.get("fetchMs")
        if item.get("posterDownloaded") is not None:
            persist["posterDownloaded"] = item.get("posterDownloaded")
        if item.get("vectorSynced") is not None:
            persist["vectorSynced"] = item.get("vectorSynced")
        if item.get("vectorSkipped") is not None:
            persist["vectorSkipped"] = item.get("vectorSkipped")
        if item.get("fields"):
            persist["fields"] = item.get("fields")
        if item.get("sourceTimings"):
            persist["sourceTimings"] = item.get("sourceTimings")
        for k in ("coverMs", "actressMs", "vectorMs", "totalMs"):
            if item.get(k) is not None:
                persist[k] = item.get(k)
        _queue_log_update_row(persist, region=region)
    except Exception:  # noqa: BLE001
        pass
    return item


def _clear_queue_log(*, region: str = "") -> None:
    rid = _queue_log_region(region) if str(region or "").strip() else ""
    keys = _enrich_log_region_keys(region) if str(region or "").strip() else []
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if rid or keys:
                want = list(dict.fromkeys([rid, *keys] if rid else keys))
                ph = ",".join(["?"] * len(want))
                conn.execute(
                    f"DELETE FROM enrich_queue_log WHERE region IN ({ph})",
                    want,
                )
            else:
                conn.execute("DELETE FROM enrich_queue_log")
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("clear enrich queue log failed region=%s: %s", rid or "*", e)


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
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET item_id=?, code=?, status=?, gaps_json=?, error=?,
                        source=?, fetch_ms=?, detail_title=?, payload_json=?,
                        updated_at=NOW()
                    WHERE id=?
                    """,
                    (*params[1:], target_id),
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


def _queue_log_mark_pending(ids: list[int]) -> None:
    want = [int(x) for x in ids if int(x or 0) > 0]
    if not want:
        return
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            ph = ",".join(["?"] * len(want))
            conn.execute(
                f"""
                UPDATE enrich_queue_log
                SET status='pending', error='', updated_at=NOW()
                WHERE id IN ({ph}) AND status IN ('pending', 'running')
                """,
                want,
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("mark enrich queue log pending failed: %s", e)


def _queue_log_reopen_running(*, region: str = "") -> None:
    rid = _queue_log_region(region)
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if rid:
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET status='pending', updated_at=NOW()
                    WHERE region=? AND status='running'
                    """,
                    (rid,),
                )
            else:
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET status='pending', updated_at=NOW()
                    WHERE status='running'
                    """
                )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("reopen running enrich queue log failed: %s", e)


_stale_running_last: dict[str, float] = {}
_STALE_RUNNING_MIN_INTERVAL_SEC = 3.0


def _queue_log_reopen_stale_running(
    region: str, *, keep_item_ids: set[str] | None = None, force: bool = False
) -> int:
    """把库里卡住的 running 退回 pending；保留当前 inflight 的 itemId。

    队列截断 / 崩溃后常见：库里残留十几条 running，角标「处理中」虚高。
    限频：状态快照每秒会问好几次，这条 UPDATE 不必每帧都发（WAL/死元组代价）。
    """
    rid = _queue_log_region(region)
    if not rid:
        return 0
    if not force:
        now = time.monotonic()
        if (now - float(_stale_running_last.get(rid) or 0.0)) < _STALE_RUNNING_MIN_INTERVAL_SEC:
            return 0
        _stale_running_last[rid] = now
    keep = {str(x or "").strip() for x in (keep_item_ids or set()) if str(x or "").strip()}
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if keep:
                ph = ",".join(["?"] * len(keep))
                cur = conn.execute(
                    f"""
                    UPDATE enrich_queue_log
                    SET status='pending', updated_at=NOW()
                    WHERE region=? AND status='running'
                      AND COALESCE(item_id,'') NOT IN ({ph})
                    """,
                    (rid, *keep),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET status='pending', updated_at=NOW()
                    WHERE region=? AND status='running'
                    """,
                    (rid,),
                )
            n = int(getattr(cur, "rowcount", 0) or 0)
            conn.commit()
            return max(0, n)
    except Exception as e:  # noqa: BLE001
        log.warning("reopen stale running enrich queue log failed: %s", e)
        return 0


def _queue_log_reopen_fails(region: str) -> list[dict[str, Any]]:
    """失败 → 未处理；同番号已有 pending/running 则跳过，避免重复。返回可投递行。"""
    rid = _queue_log_region(region)
    if not rid:
        return []
    out: list[dict[str, Any]] = []
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            # 先取出将要重开的失败行（排除已有开放行）
            rows = conn.execute(
                """
                SELECT id, item_id, code, status, gaps_json, error, source,
                       fetch_ms, detail_title, payload_json
                FROM enrich_queue_log r
                WHERE r.region=? AND r.status='fail'
                  AND NOT EXISTS (
                    SELECT 1 FROM enrich_queue_log o
                    WHERE o.region=r.region
                      AND o.status IN ('pending', 'running')
                      AND (
                        (NULLIF(r.code, '') <> '' AND o.code=r.code)
                        OR (NULLIF(r.item_id, '') <> '' AND o.item_id=r.item_id)
                      )
                  )
                ORDER BY id ASC
                """,
                (rid,),
            ).fetchall()
            ids: list[int] = []
            for raw in rows or []:
                if isinstance(raw, dict):
                    it = _queue_log_row_to_item(raw)
                    lid = int(raw.get("id") or 0)
                else:
                    it = _queue_log_row_to_item(
                        {
                            "id": raw[0],
                            "item_id": raw[1],
                            "code": raw[2],
                            "status": raw[3],
                            "gaps_json": raw[4],
                            "error": raw[5],
                            "source": raw[6],
                            "fetch_ms": raw[7],
                            "detail_title": raw[8],
                            "payload_json": raw[9],
                        }
                    )
                    lid = int(raw[0] or 0)
                if lid <= 0:
                    continue
                ids.append(lid)
                work = {
                    "itemId": str(it.get("itemId") or ""),
                    "code": str(it.get("code") or "").strip().upper(),
                    "gaps": list(it.get("gaps") or []),
                    "logId": lid,
                    "region": rid,
                    "status": "pending",
                    "error": "",
                }
                rel = str(it.get("rel_path") or it.get("relPath") or "")
                if rel:
                    work["rel_path"] = rel
                    work["relPath"] = rel
                out.append(work)
            if ids:
                # 分批更新
                for i in range(0, len(ids), 500):
                    chunk = ids[i : i + 500]
                    ph = ",".join(["?"] * len(chunk))
                    conn.execute(
                        f"""
                        UPDATE enrich_queue_log
                        SET status='pending', error='', updated_at=NOW()
                        WHERE id IN ({ph}) AND status='fail'
                        """,
                        chunk,
                    )
                conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("reopen fail enrich queue log failed region=%s: %s", rid, e)
        return []
    return out


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
        # 运行中 SSE 只读内存 queueCounts，不改的话失败角标会一直停在重试前
        if cur_reg == rid or not cur_reg:
            qc_mem = dict(_enrich_job.get("queueCounts") or {})
            if qc_mem:
                qc_mem["fail"] = max(0, int(qc_mem.get("fail") or 0) - n)
                qc_mem["pending"] = int(qc_mem.get("pending") or 0) + n
                _enrich_job["queueCounts"] = qc_mem

    try:
        _persist_enrich_runtime()
    except Exception:  # noqa: BLE001
        pass

    # 角标：失败 overlay 必须跟库内走，否则会一直钉在扫描时的全量失败数
    raw = _queue_log_status_counts_db(rid)
    tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
    _set_local_status_totals(
        rid,
        done=int(raw.get("done") or (tip or {}).get("done") or 0),
        soft=int(raw.get("soft") or (tip or {}).get("soft") or 0),
        fail=int(raw.get("fail") or 0),
    )
    _counts_cache.pop(rid, None)

    _push_log(f"失败重试 · {n} 条 → 未处理优先", region=rid)
    try:
        notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    counts = _queue_log_status_counts(rid, fresh=True)
    # pending 以库内为准（重开后的真实未处理）
    counts["pending"] = int(raw.get("pending") or counts.get("pending") or 0)
    counts["fail"] = int(raw.get("fail") or 0)
    return {
        "ok": True,
        "reopened": n,
        "region": rid,
        "counts": counts,
        "injected": injected,
        "running": bool(_enrich_job.get("running")),
    }


def _queue_log_reopen_softs(region: str) -> list[dict[str, Any]]:
    """软成功批量重开为 pending（排除已有开放行）。"""
    rid = _queue_log_region(region)
    if not rid:
        return []
    soft_pred = _soft_done_sql_pred(error_col="r.error")
    out: list[dict[str, Any]] = []
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = conn.execute(
                f"""
                SELECT id, item_id, code, status, gaps_json, error, source,
                       fetch_ms, detail_title, payload_json
                FROM enrich_queue_log r
                WHERE r.region=? AND r.status='done' AND {soft_pred}
                  AND NOT EXISTS (
                    SELECT 1 FROM enrich_queue_log o
                    WHERE o.region=r.region
                      AND o.status IN ('pending', 'running')
                      AND (
                        (NULLIF(r.code, '') <> '' AND o.code=r.code)
                        OR (NULLIF(r.item_id, '') <> '' AND o.item_id=r.item_id)
                      )
                  )
                ORDER BY id ASC
                """,
                (rid,),
            ).fetchall()
            ids: list[int] = []
            for raw in rows or []:
                if isinstance(raw, dict):
                    it = _queue_log_row_to_item(raw)
                    lid = int(raw.get("id") or 0)
                else:
                    it = _queue_log_row_to_item(
                        {
                            "id": raw[0],
                            "item_id": raw[1],
                            "code": raw[2],
                            "status": raw[3],
                            "gaps_json": raw[4],
                            "error": raw[5],
                            "source": raw[6],
                            "fetch_ms": raw[7],
                            "detail_title": raw[8],
                            "payload_json": raw[9],
                        }
                    )
                    lid = int(raw[0] or 0)
                if lid <= 0:
                    continue
                ids.append(lid)
                work = {
                    "itemId": str(it.get("itemId") or ""),
                    "code": str(it.get("code") or "").strip().upper(),
                    "gaps": list(it.get("gaps") or it.get("gapsAfter") or []),
                    "logId": lid,
                    "region": rid,
                    "status": "pending",
                    "error": "",
                }
                rel = str(it.get("rel_path") or it.get("relPath") or "")
                if rel:
                    work["rel_path"] = rel
                    work["relPath"] = rel
                out.append(work)
            if ids:
                soft_upd = _soft_done_sql_pred(error_col="error")
                for i in range(0, len(ids), 500):
                    chunk = ids[i : i + 500]
                    ph = ",".join(["?"] * len(chunk))
                    conn.execute(
                        f"""
                        UPDATE enrich_queue_log
                        SET status='pending', error='', updated_at=NOW()
                        WHERE id IN ({ph}) AND status='done' AND {soft_upd}
                        """,
                        chunk,
                    )
                conn.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("reopen soft enrich queue log failed region=%s: %s", rid, e)
        return []
    return out


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
                qc_mem["soft"] = max(0, int(qc_mem.get("soft") or 0) - n)
                qc_mem["pending"] = int(qc_mem.get("pending") or 0) + n
                _enrich_job["queueCounts"] = qc_mem

    try:
        _persist_enrich_runtime()
    except Exception:  # noqa: BLE001
        pass

    raw = _queue_log_status_counts_db(rid)
    tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
    _set_local_status_totals(
        rid,
        done=int(raw.get("done") or (tip or {}).get("done") or 0),
        soft=int(raw.get("soft") or 0),
        fail=int(raw.get("fail") or (tip or {}).get("fail") or 0),
    )
    _counts_cache.pop(rid, None)

    _push_log(f"软成功重试 · {n} 条 → 未处理优先", region=rid)
    try:
        notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    counts = _queue_log_status_counts(rid, fresh=True)
    counts["pending"] = int(raw.get("pending") or counts.get("pending") or 0)
    counts["soft"] = int(raw.get("soft") or 0)
    counts["done"] = int(raw.get("done") or counts.get("done") or 0)
    return {
        "ok": True,
        "reopened": n,
        "region": rid,
        "counts": counts,
        "injected": injected,
        "running": bool(_enrich_job.get("running")),
    }


def _queue_log_find_open(
    region: str, *, item_id: str = "", code: str = ""
) -> int:
    rid = _queue_log_region(region)
    iid = str(item_id or "").strip()
    code_u = str(code or "").strip().upper()
    if not rid or (not iid and not code_u):
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if iid:
                row = conn.execute(
                    """
                    SELECT id FROM enrich_queue_log
                    WHERE region=? AND status IN ('pending', 'running')
                      AND item_id=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (rid, iid),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id FROM enrich_queue_log
                    WHERE region=? AND status IN ('pending', 'running')
                      AND code=?
                    ORDER BY id DESC LIMIT 1
                    """,
                    (rid, code_u),
                ).fetchone()
            if not row:
                return 0
            return int(row["id"] if isinstance(row, dict) else row[0])
    except Exception as e:  # noqa: BLE001
        log.warning("find open enrich queue log failed: %s", e)
        return 0


def _queue_log_done_keys(region: str) -> tuple[set[str], set[str]]:
    """本分区已成功刮削的 itemId / code（再启动增量时跳过，避免刮过又刮）。"""
    rid = _queue_log_region(region)
    iids: set[str] = set()
    codes: set[str] = set()
    if not rid:
        return iids, codes
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            for raw in conn.execute(
                """
                SELECT item_id, code
                FROM enrich_queue_log
                WHERE region=? AND status='done'
                """,
                (rid,),
            ).fetchall() or []:
                if isinstance(raw, dict):
                    iid = str(raw.get("item_id") or "").strip()
                    code_u = str(raw.get("code") or "").strip().upper()
                else:
                    iid = str(raw[0] or "").strip()
                    code_u = str(raw[1] or "").strip().upper()
                if iid:
                    iids.add(iid)
                if code_u:
                    codes.add(code_u)
    except Exception as e:  # noqa: BLE001
        log.warning("load enrich done keys failed region=%s: %s", rid, e)
    return iids, codes


def _ensure_queue_log_ids(
    region: str, rows: list[dict[str, Any]], *, persist: bool = True
) -> list[dict[str, Any]]:
    """给本轮队列补 logId：批量复用未完成行，再批量插入。

    旧实现逐条 find_open + update，有码区上万条时会卡在「筛选」数分钟。
    persist=False：预览模式，只查不写。
    """
    if not rows:
        return []
    rid = _queue_log_region(region)
    out: list[dict[str, Any]] = [dict(r) for r in rows if isinstance(r, dict)]
    if not out:
        return []
    if not rid:
        return out

    need_idx = [i for i, r in enumerate(out) if _queue_log_int_id(r) <= 0]
    if not need_idx:
        return out

    open_by_iid: dict[str, int] = {}
    open_by_code: dict[str, int] = {}
    # 只查本批 item_id/code，禁止全表扫 pending（边扫边刮时会越扫越卡直至卡死清空）
    batch_iids: list[str] = []
    batch_codes: list[str] = []
    seen_i: set[str] = set()
    seen_c: set[str] = set()
    for i in need_idx:
        row = out[i]
        iid = str(row.get("itemId") or "").strip()
        code_u = str(row.get("code") or "").strip().upper()
        if iid and iid not in seen_i:
            seen_i.add(iid)
            batch_iids.append(iid)
        if code_u and code_u not in seen_c:
            seen_c.add(code_u)
            batch_codes.append(code_u)
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            # 分片 IN，避免单次参数过多
            def _load_chunk(iids: list[str], codes: list[str]) -> None:
                if not iids and not codes:
                    return
                clauses: list[str] = []
                params: list[Any] = [rid]
                if iids:
                    ph = ",".join(["?"] * len(iids))
                    clauses.append(f"item_id IN ({ph})")
                    params.extend(iids)
                if codes:
                    ph = ",".join(["?"] * len(codes))
                    clauses.append(f"code IN ({ph})")
                    params.extend(codes)
                sql = f"""
                    SELECT id, item_id, code
                    FROM enrich_queue_log
                    WHERE region=? AND status IN ('pending', 'running')
                      AND ({' OR '.join(clauses)})
                    ORDER BY id DESC
                    """
                for raw in conn.execute(sql, params).fetchall() or []:
                    if isinstance(raw, dict):
                        lid = int(raw.get("id") or 0)
                        iid = str(raw.get("item_id") or "").strip()
                        code_u = str(raw.get("code") or "").strip().upper()
                    else:
                        lid = int(raw[0] or 0)
                        iid = str(raw[1] or "").strip()
                        code_u = str(raw[2] or "").strip().upper()
                    if lid <= 0:
                        continue
                    if iid and iid not in open_by_iid:
                        open_by_iid[iid] = lid
                    if code_u and code_u not in open_by_code:
                        open_by_code[code_u] = lid

            step = 80
            max_n = max(len(batch_iids), len(batch_codes))
            if max_n <= 0:
                pass
            else:
                for start in range(0, max_n, step):
                    _load_chunk(
                        batch_iids[start : start + step],
                        batch_codes[start : start + step],
                    )
    except Exception as e:  # noqa: BLE001
        log.warning("batch load open enrich queue log failed region=%s: %s", rid, e)

    reuse_ids: list[int] = []
    to_insert: list[dict[str, Any]] = []
    insert_at: list[int] = []
    used_lids: set[int] = set()

    for i in need_idx:
        row = out[i]
        iid = str(row.get("itemId") or "").strip()
        code_u = str(row.get("code") or "").strip().upper()
        lid = 0
        if iid and iid in open_by_iid:
            lid = int(open_by_iid.pop(iid) or 0)
            if code_u and open_by_code.get(code_u) == lid:
                open_by_code.pop(code_u, None)
        elif code_u and code_u in open_by_code:
            lid = int(open_by_code.pop(code_u) or 0)
            # 同步清掉同 id 的 item 映射，避免二次复用
            drop_iid = next(
                (k for k, v in open_by_iid.items() if v == lid),
                "",
            )
            if drop_iid:
                open_by_iid.pop(drop_iid, None)
        if lid > 0 and lid not in used_lids:
            used_lids.add(lid)
            row["logId"] = lid
            row["status"] = "pending"
            reuse_ids.append(lid)
            continue
        insert_at.append(i)
        to_insert.append(row)

    if not persist:
        # 预览（dryRun）：只保留「查已有 pending 行」的复用匹配，不做任何写。
        # 否则预览会凭空插入 pending 行，污染真实队列。
        return out

    # 复用行：只把 running 拨回 pending，不重写 payload（快）
    if reuse_ids:
        try:
            from app.core.db import connect, init_db

            init_db()
            with connect() as conn:
                for start in range(0, len(reuse_ids), 200):
                    chunk = reuse_ids[start : start + 200]
                    ph = ",".join(["?"] * len(chunk))
                    conn.execute(
                        f"""
                        UPDATE enrich_queue_log
                        SET status='pending', updated_at=NOW()
                        WHERE id IN ({ph}) AND status='running'
                        """,
                        chunk,
                    )
                conn.commit()
        except Exception as e:  # noqa: BLE001
            log.warning(
                "batch reset enrich queue pending failed region=%s: %s", rid, e
            )

    if to_insert:
        n = len(to_insert)
        running = False
        with _enrich_lock:
            running = bool(_enrich_job.get("running"))
        if running:
            _set_progress(
                stage="queue",
                label=f"写入队列日志 0/{n}",
                done=0,
                total=n,
            )
        # 分块插入并刷新进度，避免 UI 一直停在「筛选」
        ids: list[int] = []
        chunk_size = 80
        for start in range(0, n, chunk_size):
            chunk = to_insert[start : start + chunk_size]
            got = _queue_log_insert_many(region, chunk)
            ids.extend(got)
            if running:
                _set_progress(
                    stage="queue",
                    label=f"写入队列日志 {min(start + len(chunk), n)}/{n}",
                    done=min(start + len(chunk), n),
                    total=n,
                )
        for pos, new_id in zip(insert_at, ids):
            if new_id:
                out[pos]["logId"] = int(new_id)
    return out


def _queue_log_prune_pending_not_in(region: str, keep_item_ids: set[str]) -> int:
    """扫描后：删除已不在缺口集合里的 pending（保留成功/失败/处理中）。"""
    rid = _queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            if not keep_item_ids:
                cur = conn.execute(
                    """
                    DELETE FROM enrich_queue_log
                    WHERE region=? AND status='pending'
                    """,
                    (rid,),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT id, item_id FROM enrich_queue_log
                    WHERE region=? AND status='pending'
                    """,
                    (rid,),
                )
                drop: list[int] = []
                keep = set(keep_item_ids)
                for row in cur.fetchall() or []:
                    iid = str(
                        (row.get("item_id") if isinstance(row, dict) else row[1])
                        or ""
                    )
                    lid = int(
                        (row.get("id") if isinstance(row, dict) else row[0]) or 0
                    )
                    if lid and iid not in keep:
                        drop.append(lid)
                if not drop:
                    conn.commit()
                    return 0
                ph = ",".join(["?"] * len(drop))
                cur = conn.execute(
                    f"DELETE FROM enrich_queue_log WHERE id IN ({ph})",
                    drop,
                )
            n = int(cur.rowcount or 0)
            conn.commit()
            return n
    except Exception as e:  # noqa: BLE001
        log.warning("prune enrich queue pending failed region=%s: %s", rid, e)
        return 0


def _queue_log_prune_open_if_done(
    region: str, *, code: str = "", item_id: str = ""
) -> int:
    """已有成功行时，删掉同番号/同条目的 pending·running，避免成功还出现在未处理。

    热路径（刚写完 done）只按 code/item_id 定点删，禁止 EXISTS 全表相关子查询：
    后者在 8 万+ done 行上会扫锁数分钟，卡住其它番号的 UPDATE → 监控假死在封面阶段。
    """
    rid = _queue_log_region(region)
    if not rid:
        return 0
    code_u = str(code or "").strip().upper()
    iid = str(item_id or "").strip()
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            # 短超时：prune 失败可下次再清，绝不能堵 worker
            try:
                conn.execute("SET LOCAL statement_timeout = '4s'")
                conn.execute("SET LOCAL lock_timeout = '2s'")
            except Exception:  # noqa: BLE001
                pass
            if code_u or iid:
                # 调用方刚写入 done：无需再 EXISTS 证明「已有成功」
                clauses: list[str] = []
                params: list[Any] = [rid]
                if code_u:
                    clauses.append("code=?")
                    params.append(code_u)
                if iid:
                    clauses.append("item_id=?")
                    params.append(iid)
                cur = conn.execute(
                    f"""
                    DELETE FROM enrich_queue_log
                    WHERE region=?
                      AND status IN ('pending', 'running')
                      AND ({" OR ".join(clauses)})
                    """,
                    params,
                )
                n = int(getattr(cur, "rowcount", 0) or 0)
                conn.commit()
                return max(0, n)

            # 全分区后台清理：分批 + 用 code/item_id 半连接，避免相关 EXISTS 长锁
            total = 0
            for _ in range(40):
                cur = conn.execute(
                    """
                    WITH doomed AS (
                      SELECT o.id
                      FROM enrich_queue_log AS o
                      WHERE o.region=?
                        AND o.status IN ('pending', 'running')
                        AND (
                          (
                            NULLIF(o.code, '') IS NOT NULL
                            AND EXISTS (
                              SELECT 1 FROM enrich_queue_log d
                              WHERE d.region=o.region
                                AND d.status='done'
                                AND d.code=o.code
                              LIMIT 1
                            )
                          )
                          OR (
                            NULLIF(o.item_id, '') IS NOT NULL
                            AND EXISTS (
                              SELECT 1 FROM enrich_queue_log d
                              WHERE d.region=o.region
                                AND d.status='done'
                                AND d.item_id=o.item_id
                              LIMIT 1
                            )
                          )
                        )
                      LIMIT 200
                    )
                    DELETE FROM enrich_queue_log
                    WHERE id IN (SELECT id FROM doomed)
                    """,
                    (rid,),
                )
                n = int(getattr(cur, "rowcount", 0) or 0)
                conn.commit()
                total += max(0, n)
                if n < 200:
                    break
                try:
                    conn.execute("SET LOCAL statement_timeout = '4s'")
                    conn.execute("SET LOCAL lock_timeout = '2s'")
                except Exception:  # noqa: BLE001
                    pass
            return total
    except Exception as e:  # noqa: BLE001
        log.warning(
            "prune open enrich queue if done failed region=%s: %s", rid, e
        )
    return 0


def _queue_log_prune_done_keep(region: str, keep: int = _QUEUE_LOG_DONE_KEEP) -> int:
    """只保留最近 keep 条「刮削完成」done，不删 local_scan 全量分类行。"""
    rid = _queue_log_region(region)
    keep_n = max(500, int(keep or _QUEUE_LOG_DONE_KEEP))
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            # 仅裁剪非本地扫描写入的 done（刮削实时结果）
            row_n = conn.execute(
                """
                SELECT COUNT(*) AS n FROM enrich_queue_log
                WHERE region=? AND status='done'
                  AND COALESCE(source, '') <> 'local_scan'
                """,
                (rid,),
            ).fetchone()
            if isinstance(row_n, dict):
                total = int(row_n.get("n") or 0)
            else:
                total = int((row_n[0] if row_n else 0) or 0)
            if total <= keep_n:
                return 0
            keep_rows = conn.execute(
                """
                SELECT id FROM enrich_queue_log
                WHERE region=? AND status='done'
                  AND COALESCE(source, '') <> 'local_scan'
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT ?
                """,
                (rid, keep_n),
            ).fetchall()
            keep_ids = [
                int((r.get("id") if isinstance(r, dict) else r[0]) or 0)
                for r in (keep_rows or [])
            ]
            keep_ids = [i for i in keep_ids if i > 0]
            if not keep_ids:
                return 0
            ph = ",".join("?" for _ in keep_ids)
            cur = conn.execute(
                f"""
                DELETE FROM enrich_queue_log
                WHERE region=? AND status='done'
                  AND COALESCE(source, '') <> 'local_scan'
                  AND id NOT IN ({ph})
                """,
                (rid, *keep_ids),
            )
            dropped = int(getattr(cur, "rowcount", 0) or 0)
            try:
                conn.commit()
            except Exception:  # noqa: BLE001
                pass
            return max(0, dropped)
    except Exception as e:  # noqa: BLE001
        log.debug("prune done enrich queue failed region=%s: %s", rid, e)
    return 0


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


def _slim_one_result_mem(one: dict[str, Any]) -> dict[str, Any]:
    """内存 results 只留摘要，防止万级刮削占满堆。"""
    if not isinstance(one, dict):
        return {"ok": False}
    return {
        "code": one.get("code"),
        "ok": bool(one.get("ok")),
        "error": str(one.get("error") or "")[:160],
        "partialOk": bool(one.get("partialOk")),
        "posterDownloaded": bool(one.get("posterDownloaded")),
        "fetchMs": one.get("fetchMs"),
        "coverMs": one.get("coverMs"),
        "totalMs": one.get("totalMs"),
    }


def _queue_log_prune_pending_if_running(
    region: str,
    *,
    code: str = "",
    item_id: str = "",
    keep_id: int = 0,
) -> int:
    """进入处理中后：删掉同番号其它 pending，避免处理中还挂在未处理。"""
    rid = _queue_log_region(region)
    if not rid:
        return 0
    code_u = str(code or "").strip().upper()
    iid = str(item_id or "").strip()
    kid = int(keep_id or 0)
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            try:
                conn.execute("SET LOCAL statement_timeout = '4s'")
                conn.execute("SET LOCAL lock_timeout = '2s'")
            except Exception:  # noqa: BLE001
                pass
            if kid > 0 and (code_u or iid):
                clauses: list[str] = []
                params: list[Any] = [rid]
                if code_u:
                    clauses.append("code=?")
                    params.append(code_u)
                if iid:
                    clauses.append("item_id=?")
                    params.append(iid)
                params.append(kid)
                cur = conn.execute(
                    f"""
                    DELETE FROM enrich_queue_log
                    WHERE region=?
                      AND status='pending'
                      AND ({" OR ".join(clauses)})
                      AND id<>?
                    """,
                    params,
                )
            elif code_u or iid:
                # 定点删：有 running 时由调用方保证；勿用全表相关 EXISTS
                clauses = []
                params = [rid]
                if code_u:
                    clauses.append("code=?")
                    params.append(code_u)
                if iid:
                    clauses.append("item_id=?")
                    params.append(iid)
                cur = conn.execute(
                    f"""
                    DELETE FROM enrich_queue_log
                    WHERE region=?
                      AND status='pending'
                      AND ({" OR ".join(clauses)})
                    """,
                    params,
                )
            else:
                # 后台全分区：分批，避免长事务锁死 UPDATE
                total = 0
                for _ in range(40):
                    cur = conn.execute(
                        """
                        WITH doomed AS (
                          SELECT o.id
                          FROM enrich_queue_log AS o
                          WHERE o.region=?
                            AND o.status='pending'
                            AND (
                              (
                                NULLIF(o.code, '') IS NOT NULL
                                AND EXISTS (
                                  SELECT 1 FROM enrich_queue_log r
                                  WHERE r.region=o.region
                                    AND r.status='running'
                                    AND r.code=o.code
                                  LIMIT 1
                                )
                              )
                              OR (
                                NULLIF(o.item_id, '') IS NOT NULL
                                AND EXISTS (
                                  SELECT 1 FROM enrich_queue_log r
                                  WHERE r.region=o.region
                                    AND r.status='running'
                                    AND r.item_id=o.item_id
                                  LIMIT 1
                                )
                              )
                            )
                          LIMIT 200
                        )
                        DELETE FROM enrich_queue_log
                        WHERE id IN (SELECT id FROM doomed)
                        """,
                        (rid,),
                    )
                    n = int(getattr(cur, "rowcount", 0) or 0)
                    conn.commit()
                    total += max(0, n)
                    if n < 200:
                        return total
                    try:
                        conn.execute("SET LOCAL statement_timeout = '4s'")
                        conn.execute("SET LOCAL lock_timeout = '2s'")
                    except Exception:  # noqa: BLE001
                        pass
                return total
            n = int(getattr(cur, "rowcount", 0) or 0)
            conn.commit()
            return max(0, n)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "prune pending if running failed region=%s: %s", rid, e
        )
        return 0


def _queue_log_clear_pending(region: str) -> int:
    """清空该区 pending（保留成功/失败/处理中）。"""
    return _queue_log_prune_pending_not_in(region, set())


def _pending_total_estimate(
    region: str, *, classified: dict[str, int] | None = None
) -> int:
    """未处理角标：向量总数 − 成功/软成功/失败。

    优先 tip.total（扫描落盘）；否则轻量 COUNT，不跑 quality_stats。
    """
    rid = _queue_log_region(region)
    if not rid:
        return 0
    _ensure_local_status_totals_loaded()
    tip = _LOCAL_STATUS_TOTALS.get(rid) if rid else None
    vector_total = int((tip or {}).get("total") or 0)
    if vector_total <= 0:
        try:
            vector_total = int(_region_library_progress(rid).get("total") or 0)
        except Exception:  # noqa: BLE001
            vector_total = 0
    if classified is not None:
        done_n = int(classified.get("done") or 0)
        soft_n = int(classified.get("soft") or 0)
        fail_n = int(classified.get("fail") or 0)
    else:
        raw = _queue_log_status_counts_db(rid)
        done_n = max(int(raw.get("done") or 0), int((tip or {}).get("done") or 0))
        soft_n = max(int(raw.get("soft") or 0), int((tip or {}).get("soft") or 0))
        fail_n = max(int(raw.get("fail") or 0), int((tip or {}).get("fail") or 0))
    return max(0, vector_total - done_n - soft_n - fail_n)


def _clamp_pending_badge(counts: dict[str, int], region: str) -> dict[str, int]:
    """未处理角标禁止被库内样例/虚高补写抬高：以向量−已分类为准。"""
    rid = _queue_log_region(region)
    out = dict(counts)
    if not rid:
        return out
    est = _pending_total_estimate(rid, classified=out)
    db_p = int(out.get("pending") or 0)
    if est > 0:
        out["pending"] = est
    elif db_p > 0:
        # 无向量总数时，仍限制明显虚高（大于已分类总和）
        classified_n = (
            int(out.get("done") or 0)
            + int(out.get("soft") or 0)
            + int(out.get("fail") or 0)
        )
        if classified_n > 0 and db_p > classified_n:
            out["pending"] = 0
    return out


# 已分类 skip 缓存（翻页复用，避免每次读 10 万行）
_classified_skip_cache: dict[str, tuple[float, set[str], set[str]]] = {}
_CLASSIFIED_SKIP_TTL_SEC = 120.0
_pending_backfill_done: set[str] = set()


def _queue_log_classified_skip_keys(
    region: str, *, fresh: bool = False
) -> tuple[set[str], set[str]]:
    """队列表已分类（done/fail，含软成功）+ running 的 itemId/code。"""
    rid = _queue_log_region(region)
    empty: tuple[set[str], set[str]] = (set(), set())
    if not rid:
        return empty
    now = time.time()
    if not fresh:
        hit = _classified_skip_cache.get(rid)
        if hit and now - float(hit[0]) < _CLASSIFIED_SKIP_TTL_SEC:
            return hit[1], hit[2]
    iids: set[str] = set()
    codes: set[str] = set()
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            for raw in (
                conn.execute(
                    """
                    SELECT item_id, code FROM enrich_queue_log
                    WHERE region=? AND status IN ('done', 'fail', 'running')
                    """,
                    (rid,),
                ).fetchall()
                or []
            ):
                if isinstance(raw, dict):
                    iid = str(raw.get("item_id") or "").strip()
                    code_u = str(raw.get("code") or "").strip().upper()
                else:
                    iid = str(raw[0] or "").strip()
                    code_u = str(raw[1] or "").strip().upper()
                if iid:
                    iids.add(iid)
                if code_u:
                    codes.add(code_u)
    except Exception as e:  # noqa: BLE001
        log.warning("load classified skip keys failed region=%s: %s", rid, e)
        return empty
    _classified_skip_cache[rid] = (now, iids, codes)
    return iids, codes


def _invalidate_classified_skip_cache(region: str = "") -> None:
    rid = _queue_log_region(region) if str(region or "").strip() else ""
    if rid:
        _classified_skip_cache.pop(rid, None)
    else:
        _classified_skip_cache.clear()


def _pending_page_from_vector(
    region: str, *, offset: int = 0, limit: int = 100
) -> list[dict[str, Any]]:
    """未处理翻页：读队列表 pending（updated_at 倒序）。

    禁止对向量库做「updated_at + NOT EXISTS 已分类」全表扫描——会拖死 API。
    队列表为空时回退向量 code ASC 分批排除（有索引）。
    """
    from app.core.db import connect, init_db
    from app.scrap_library import embed as embed_svc

    rid = _queue_log_region(region)
    if not rid:
        return []
    off = max(0, int(offset or 0))
    lim = max(1, min(int(limit or 100), 500))
    out: list[dict[str, Any]] = []

    try:
        init_db()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT id, item_id, code, status, gaps_json, error, source,
                       fetch_ms, detail_title, payload_json
                FROM enrich_queue_log
                WHERE region=? AND status='pending'
                ORDER BY updated_at DESC NULLS LAST, id DESC
                LIMIT ? OFFSET ?
                """,
                (rid, lim, off),
            ).fetchall()
        for raw in rows or []:
            if isinstance(raw, dict):
                it = _queue_log_row_to_item(raw)
            else:
                it = _queue_log_row_to_item(
                    {
                        "id": raw[0],
                        "item_id": raw[1],
                        "code": raw[2],
                        "status": raw[3],
                        "gaps_json": raw[4],
                        "error": raw[5],
                        "source": raw[6],
                        "fetch_ms": raw[7],
                        "detail_title": raw[8],
                        "payload_json": raw[9],
                    }
                )
            it["status"] = "pending"
            it["region"] = rid
            if not it.get("gaps"):
                it["gaps"] = list(_ENRICH_KINDS)
            out.append(it)
        if out or off > 0:
            return out
    except Exception as e:  # noqa: BLE001
        log.warning("pending page from queue_log failed region=%s: %s", rid, e)

    # 回退：向量 code ASC（有索引）+ 分批排除已分类
    skipped = 0
    batch_sz = 500
    vec_off = 0
    for _ in range(40):
        if len(out) >= lim:
            break
        try:
            batch = embed_svc.list_region_code_items(
                region=rid, limit=batch_sz, offset=vec_off, order="code"
            )
        except Exception as e:  # noqa: BLE001
            log.warning("pending page vector fallback failed: %s", e)
            break
        if not batch:
            break
        vec_off += len(batch)
        codes = [
            str(r.get("code") or "").strip().upper()
            for r in batch
            if isinstance(r, dict) and str(r.get("code") or "").strip()
        ]
        iids = [
            str(r.get("itemId") or r.get("relPath") or "").strip()
            for r in batch
            if isinstance(r, dict)
        ]
        hit_c: set[str] = set()
        hit_i: set[str] = set()
        try:
            with connect() as conn:
                params: list[Any] = [rid]
                clauses: list[str] = []
                if iids:
                    ph = ",".join(["?"] * len(iids))
                    clauses.append(f"item_id IN ({ph})")
                    params.extend(iids)
                if codes:
                    ph = ",".join(["?"] * len(codes))
                    clauses.append(f"code IN ({ph})")
                    params.extend(codes)
                if clauses:
                    for raw in conn.execute(
                        f"""
                        SELECT item_id, code FROM enrich_queue_log
                        WHERE region=? AND status IN ('done','fail','running')
                          AND ({' OR '.join(clauses)})
                        """,
                        params,
                    ).fetchall() or []:
                        if isinstance(raw, dict):
                            if raw.get("item_id"):
                                hit_i.add(str(raw["item_id"]))
                            if raw.get("code"):
                                hit_c.add(str(raw["code"]).upper())
                        else:
                            if raw[0]:
                                hit_i.add(str(raw[0]))
                            if raw[1]:
                                hit_c.add(str(raw[1]).upper())
        except Exception:  # noqa: BLE001
            pass
        for r in batch:
            if not isinstance(r, dict):
                continue
            iid = str(r.get("itemId") or "").strip()
            rel = str(r.get("relPath") or r.get("rel_path") or iid).strip()
            code_u = str(r.get("code") or "").strip().upper()
            iid2 = iid or rel
            if iid2 in hit_i or (rel and rel in hit_i) or (code_u and code_u in hit_c):
                continue
            if skipped < off:
                skipped += 1
                continue
            item = {
                "itemId": iid2,
                "code": code_u,
                "gaps": list(r.get("gaps") or []) or list(_ENRICH_KINDS),
                "status": "pending",
                "region": rid,
                "shell": bool(r.get("shell")),
            }
            if rel:
                item["rel_path"] = rel
                item["relPath"] = rel
            out.append(item)
            if len(out) >= lim:
                break
        if len(batch) < batch_sz:
            break
    return out


def _queue_log_trim_inflated_pending(region: str) -> int:
    """库内 pending 远高于估算时清掉（多半是旧全量补写），列表改走虚拟翻页。"""
    rid = _queue_log_region(region)
    if not rid:
        return 0
    raw = _queue_log_status_counts_db(rid)
    db_n = int(raw.get("pending") or 0)
    est = _pending_total_estimate(rid)
    if est <= 0 or db_n <= max(int(est * 1.15), est + 200):
        return 0
    n = _queue_log_clear_pending(rid)
    _counts_cache.pop(rid, None)
    log.info(
        "trim inflated pending region=%s db=%s est=%s cleared=%s",
        rid,
        db_n,
        est,
        n,
    )
    return n


def _queue_log_clear_local_scan_status(region: str) -> int:
    """删掉 local_scan 写入的成功/失败行，便于全量重写分类列表。"""
    rid = _queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM enrich_queue_log
                WHERE region=? AND source='local_scan'
                  AND status IN ('done', 'fail')
                """,
                (rid,),
            )
            n = int(getattr(cur, "rowcount", 0) or 0)
            try:
                conn.commit()
            except Exception:  # noqa: BLE001
                pass
            _counts_cache.pop(rid, None)
            return max(0, n)
    except Exception as e:  # noqa: BLE001
        log.warning("clear local_scan status failed region=%s: %s", rid, e)
        return 0


_DONE_LOG_RE = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9\-_]{1,24})\s*·\s*完成"
)


def _recover_done_from_enrich_logs(region: str) -> int:
    """从文本日志里的「番号 · 完成…」回填成功队列（暂停/清检查点后成功 tab 会空）。"""
    rid = _queue_log_region(region)
    if not rid:
        return 0
    codes: list[str] = []
    seen: set[str] = set()
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT line FROM enrich_logs
                WHERE region = ?
                ORDER BY id ASC
                """,
                (rid,),
            ).fetchall()
            for raw in rows or []:
                line = str(
                    (raw.get("line") if isinstance(raw, dict) else raw[0]) or ""
                ).strip()
                m = _DONE_LOG_RE.match(line)
                if not m:
                    continue
                code = m.group(1).strip().upper()
                if not code or code in seen:
                    continue
                seen.add(code)
                codes.append(code)
    except Exception as e:  # noqa: BLE001
        log.warning("recover done from enrich logs failed region=%s: %s", rid, e)
        return 0
    if not codes:
        return 0

    recovered = 0
    for code in codes:
        try:
            # 本地已删 → 不回填 done（否则重扫 demote 后又被日志捞回）
            folder = _resolve_enrich_folder(region=rid, code=code, item_id="")
            if folder is None or not _local_poster_ok(folder):
                continue
            # 已有 pending/running → 改 done；已有 done 跳过；没有则插入
            from app.core.db import connect, init_db

            init_db()
            with connect() as conn:
                row = conn.execute(
                    """
                    SELECT id, status, payload_json, detail_title, source, item_id
                    FROM enrich_queue_log
                    WHERE region=? AND code=?
                    ORDER BY
                      CASE status
                        WHEN 'done' THEN 0
                        WHEN 'fail' THEN 1
                        WHEN 'running' THEN 2
                        ELSE 3
                      END,
                      id DESC
                    LIMIT 1
                    """,
                    (rid, code),
                ).fetchone()
                if row:
                    lid = int(
                        (row.get("id") if isinstance(row, dict) else row[0]) or 0
                    )
                    st = str(
                        (row.get("status") if isinstance(row, dict) else row[1])
                        or ""
                    ).strip().lower()
                    if st == "fail":
                        continue
                    payload_raw = (
                        row.get("payload_json")
                        if isinstance(row, dict)
                        else (row[2] if len(row) > 2 else "{}")
                    )
                    detail_title = str(
                        (
                            row.get("detail_title")
                            if isinstance(row, dict)
                            else (row[3] if len(row) > 3 else "")
                        )
                        or ""
                    ).strip()
                    item_id = str(
                        (
                            row.get("item_id")
                            if isinstance(row, dict)
                            else (row[5] if len(row) > 5 else "")
                        )
                        or ""
                    ).strip()
                    try:
                        payload = (
                            json.loads(payload_raw)
                            if isinstance(payload_raw, str)
                            else (payload_raw or {})
                        )
                    except Exception:  # noqa: BLE001
                        payload = {}
                    if not isinstance(payload, dict):
                        payload = {}
                    has_fields = bool(payload.get("fields"))
                    if st == "done" and has_fields and detail_title:
                        continue
                    # done 但空壳 / pending→done：用本地库补全
                    hydrated = _hydrate_queue_item_from_library(
                        code=code, region=rid, item_id=item_id
                    )
                    if lid > 0:
                        merged = {
                            "itemId": hydrated.get("itemId") or item_id,
                            "code": code,
                            "status": "done",
                            "gaps": [],
                            "error": "",
                            "source": str(
                                hydrated.get("source")
                                or (
                                    row.get("source")
                                    if isinstance(row, dict)
                                    else ""
                                )
                                or ""
                            ).strip(),
                            "detailTitle": hydrated.get("detailTitle")
                            or detail_title,
                            "posterDownloaded": hydrated.get("posterDownloaded"),
                            "vectorSynced": hydrated.get("vectorSynced"),
                            "fields": hydrated.get("fields") or payload.get("fields"),
                            "sourceTimings": payload.get("sourceTimings") or [],
                        }
                        # 去掉伪命中源
                        if merged["source"] in {"log_recover", "recover"}:
                            merged["source"] = ""
                        params = _queue_log_insert_params(rid, merged)
                        conn.execute(
                            """
                            UPDATE enrich_queue_log
                            SET item_id=?, code=?, status=?, gaps_json=?, error=?,
                                source=?, fetch_ms=?, detail_title=?, payload_json=?,
                                updated_at=NOW()
                            WHERE id=?
                            """,
                            (*params[1:], lid),
                        )
                        conn.commit()
                        recovered += 1
                        continue
                # 无行：插入并尽量补全
                hydrated = _hydrate_queue_item_from_library(code=code, region=rid)
                merged = {
                    "itemId": hydrated.get("itemId") or "",
                    "code": code,
                    "status": "done",
                    "gaps": [],
                    "error": "",
                    "source": "",
                    "detailTitle": hydrated.get("detailTitle") or "",
                    "posterDownloaded": hydrated.get("posterDownloaded"),
                    "vectorSynced": hydrated.get("vectorSynced"),
                    "fields": hydrated.get("fields") or [],
                    "sourceTimings": [],
                }
                params = _queue_log_insert_params(rid, merged)
                conn.execute(
                    """
                    INSERT INTO enrich_queue_log (
                      region, item_id, code, status, gaps_json, error, source,
                      fetch_ms, detail_title, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )
                conn.commit()
                recovered += 1
        except Exception as e:  # noqa: BLE001
            log.debug("recover done row failed %s %s: %s", rid, code, e)
    if recovered:
        log.info(
            "recover enrich done from logs region=%s n=%s", rid, recovered
        )
    return recovered


def _region_local_dirs(root: Path, region: str) -> list[Path]:
    """刮削库根下该分区的本地目录（日本有码 / japan_censored …）。

    FC2 区一次扫整区：其下 FC2 / FC2-PPV 前缀夹均进队；落盘路径仍按骨架分夹。
    """
    from app.scrap_library.embed import _region_match_values

    out: list[Path] = []
    seen: set[str] = set()
    for name in _region_match_values(region):
        key = str(name or "").strip()
        if not key or key.casefold() in seen:
            continue
        seen.add(key.casefold())
        p = (root / key).resolve()
        try:
            p.relative_to(root.resolve())
        except ValueError:
            continue
        if p.is_dir():
            out.append(p)
    return out


_folder_gaps_cache: dict[str, tuple[tuple[Any, ...], tuple[str, list[str]]]] = {}
_FOLDER_GAPS_CACHE_CAP = 160_000
_folder_gaps_cache_lock = threading.Lock()


def _local_scan_workers() -> int:
    """清空·扫描分类线程。1G 容器不要按宿主机核数开到 24。"""
    from app.core.container_budget import io_threads, memory_class

    if memory_class() == "host":
        return max(4, min(24, (os.cpu_count() or 8) * 2))
    return io_threads(floor=2, host_max=4)


def _folder_gaps_cache_cap() -> int:
    from app.core.container_budget import memory_class

    kind = memory_class()
    if kind == "tight":
        return 4_000
    if kind == "small":
        return 20_000
    return _FOLDER_GAPS_CACHE_CAP
# 队列表批量 INSERT 每语句行数（过大易超参，过小往返多）
_QUEUE_LOG_INSERT_CHUNK = 500
# 边扫边写：累计这么多分类行就刷一盘
_SCAN_STREAM_FLUSH = 800


def _collect_nfo_folders_parallel(
    dirs: list[Path],
    root: Path,
    *,
    workers: int = 8,
) -> list[tuple[str, Path]]:
    """按前缀目录并行枚举 *.nfo 父目录，返回去重后的 (rel, folder)。"""
    prefixes: list[Path] = []
    for base in dirs:
        try:
            kids = [p for p in base.iterdir() if p.is_dir()]
        except Exception:  # noqa: BLE001
            kids = []
        if kids:
            prefixes.extend(kids)
        else:
            # 分区下无子目录时直接扫 base
            prefixes.append(base)
    if not prefixes:
        return []

    def _scan_prefix(prefix: Path) -> list[tuple[str, Path]]:
        local: list[tuple[str, Path]] = []
        try:
            it = prefix.rglob("*.nfo")
        except Exception:  # noqa: BLE001
            return local
        for nfo in it:
            folder = nfo.parent
            try:
                rel = folder.relative_to(root).as_posix()
            except ValueError:
                continue
            local.append((rel, folder))
        return local

    nw = max(1, min(int(workers or 8), 16, len(prefixes)))
    out: list[tuple[str, Path]] = []
    seen: set[str] = set()
    with ThreadPoolExecutor(max_workers=nw) as pool:
        for chunk in pool.map(_scan_prefix, prefixes, chunksize=1):
            for rel, folder in chunk:
                if not rel or rel in seen:
                    continue
                seen.add(rel)
                out.append((rel, folder))
    return out


def _file_stamp(p: "Path | None") -> tuple[str, int, int]:
    """(路径, mtime_ns, size)；文件不在则全零。"""
    if p is None:
        return ("", 0, 0)
    try:
        st = p.stat()
    except OSError:
        return (str(p), 0, 0)
    return (
        str(p),
        int(getattr(st, "st_mtime_ns", 0) or 0),
        int(getattr(st, "st_size", 0) or 0),
    )


def _folder_gaps_stamp(
    folder: "Path", nfo: "Path | None", posters: list
) -> tuple[Any, ...]:
    """失效指纹：目录 mtime（覆盖目录内增删文件）+ NFO/海报的 mtime/size。

    海报被"覆盖写"不改目录 mtime，但会改海报自身 mtime/size → 仍能失效。
    """
    try:
        dm = int(folder.stat().st_mtime_ns or 0)
    except OSError:
        dm = 0
    parts: list[Any] = [dm, *_file_stamp(nfo)]
    for p in posters:
        parts.extend(_file_stamp(p))
    return tuple(parts)


def _local_folder_gaps(folder: Path) -> tuple[str, list[str]]:
    """只读本地 NFO + poster，算出与增量 kinds 对齐的缺口（不看向量库）。

    ⚠️ 这是启动/续跑路径上的固定开销大头：`_local_nfo_gap_maps` 要对整个分区
    逐目录跑，每目录一次 parse_nfo（读解析 XML）+ 一次空白封面判定（读图），
    实测 1.1ms/目录（冷缓存 9.4ms/目录），有码区 1349 个目录 ≈ 1.5s。
    按 (目录 mtime, NFO/海报 mtime+size) 缓存结果 → 命中只需几次 stat。
    """
    from app.scrap_library import embed as embed_svc

    code_name = str(folder.name or "").strip().upper()
    nfo = _find_nfo(folder)
    posters: list[Path] = []
    if nfo and nfo.is_file():
        for name in ("poster.jpg", "poster.jpeg", "poster.png", "poster.webp"):
            p = folder / name
            if p.is_file():
                posters.append(p)
    ckey = str(folder)
    stamp = _folder_gaps_stamp(folder, nfo, posters)
    with _folder_gaps_cache_lock:
        hit = _folder_gaps_cache.get(ckey)
        if hit is not None and hit[0] == stamp:
            return hit[1][0], list(hit[1][1])

    def _remember(code_u: str, gaps: list[str]) -> tuple[str, list[str]]:
        with _folder_gaps_cache_lock:
            if len(_folder_gaps_cache) > _folder_gaps_cache_cap():
                _folder_gaps_cache.clear()
            _folder_gaps_cache[ckey] = (stamp, (code_u, list(gaps)))
        return code_u, gaps

    if not nfo or not nfo.is_file():
        return _remember(
            code_name,
            ["no_local", "no_media", "no_actress", "no_studio", "no_plot", "thin_title"],
        )
    meta = parse_nfo(nfo) or {}
    code_u = str(meta.get("num") or code_name).strip().upper() or code_name
    title = str(meta.get("title") or "").strip()
    plot = str(meta.get("plot") or meta.get("overview") or "").strip()
    actors = [
        str(a).strip()
        for a in (meta.get("actors") or [])
        if str(a or "").strip()
    ]
    studio = str(meta.get("studio") or meta.get("maker") or "").strip()
    cover_url = str(meta.get("cover_url") or "").strip()

    poster_ok = False
    for p in posters:
        try:
            if not embed_svc._is_blank_cover_file(p):  # noqa: SLF001
                poster_ok = True
                break
        except Exception:  # noqa: BLE001
            poster_ok = True
            break

    gaps: list[str] = []
    if not poster_ok:
        gaps.append("no_local")
    if not cover_url:
        gaps.append("no_media")
    if not actors:
        gaps.append("no_actress")
    if not studio:
        gaps.append("no_studio")
    if len(plot) < 12:
        gaps.append("no_plot")
    if (not title) or len(title) < 4 or title.casefold() == code_u.casefold():
        gaps.append("thin_title")
    elif _title_lacks_zh(title, code_u):
        gaps.append("no_zh_title")
    return _remember(code_u, gaps)


def iter_local_incomplete_items(
    *,
    region: str,
    limit: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """扫描本地分区 NFO：返回 (缺口样例列表, 缺口总数)。limit<=0 表示样例不截断。"""
    from app.scrap_library import embed as embed_svc

    rid = _queue_log_region(region)
    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root")).resolve()
    dirs = _region_local_dirs(root, rid or region)
    if not dirs:
        return [], 0

    lim = int(limit or 0)
    samples: list[dict[str, Any]] = []
    total = 0
    seen: set[str] = set()

    for base in dirs:
        # PREFIX/CODE/*.nfo → nfo.parent 即番号目录
        try:
            nfo_iter = base.rglob("*.nfo")
        except Exception:  # noqa: BLE001
            continue
        for nfo in nfo_iter:
            folder = nfo.parent
            try:
                rel = folder.relative_to(root).as_posix()
            except ValueError:
                continue
            if rel in seen:
                continue
            seen.add(rel)
            code_u, gaps = _local_folder_gaps(folder)
            if not gaps:
                continue
            total += 1
            if lim > 0 and len(samples) >= lim:
                continue
            samples.append(
                {
                    "itemId": rel,
                    "code": code_u,
                    "gaps": gaps,
                    "rel_path": rel,
                    "relPath": rel,
                    "region": rid or region,
                    "status": "pending",
                }
            )
    return samples, total


def _classify_disk_gaps(gaps: list[str] | None) -> str:
    """本地缺口 → done / soft / fail。

    缺封面/空标题 → fail；缺女优/片商 → soft；其余（含缺剧情/外链/中文标题）→ done。
    """
    gs = [str(g) for g in (gaps or []) if str(g).strip()]
    if not gs:
        return "done"
    if any(g in _SUCCESS_BLOCK_GAPS for g in gs):
        return "fail"
    if any(g in _SOFT_SUCCESS_GAPS for g in gs):
        return "soft"
    return "done"


def _local_status_item(
    *,
    rel: str,
    code: str,
    gaps: list[str],
    region: str,
    kind: str,
    root: Path | None = None,
    merge_sidecar: bool = True,
) -> dict[str, Any]:
    """本地分类 → 可入库队列行。"""
    code_u = str(code or "").strip().upper()
    rid = str(region or "").strip()
    item: dict[str, Any] = {
        "itemId": rel,
        "code": code_u,
        "gaps": list(gaps or []),
        "gapsAfter": list(gaps or []),
        "rel_path": rel,
        "relPath": rel,
        "region": rid,
        "source": "local_scan",
    }
    if kind == "done":
        item["status"] = "done"
        item["partialOk"] = False
        item["error"] = ""
    elif kind == "soft":
        soft_gaps = [g for g in gaps if g in _SOFT_SUCCESS_GAPS]
        labels = _gap_labels(soft_gaps)
        item["status"] = "done"
        item["partialOk"] = True
        item["error"] = _format_soft_ok_error(labels or ["女优"])
        item["gapsAfter"] = soft_gaps
    else:
        block = [g for g in gaps if g in _SUCCESS_BLOCK_GAPS] or list(gaps or [])
        labels = _gap_labels(block)
        item["status"] = "fail"
        item["partialOk"] = False
        item["error"] = f"仍缺:{' · '.join(labels)}" if labels else "仍缺:封面"
    if not merge_sidecar:
        # 仍附上本地 NFO 字段，避免详情「标题/封面 · 无」
        try:
            from app.scrap_library import embed as embed_svc

            base = root
            if base is None:
                settings = embed_svc.get_settings()
                base = embed_svc.resolve_root(settings.get("root")).resolve()
            fol = (base / rel).resolve()
            fol.relative_to(base)
            if fol.is_dir():
                local_detail, fields, local_ok = _detail_from_local_folder(
                    fol, code=code_u
                )
                item["fields"] = fields
                if local_detail.get("detailTitle"):
                    item["detailTitle"] = local_detail["detailTitle"]
                item["posterDownloaded"] = bool(local_ok)
        except Exception:  # noqa: BLE001
            pass
        return item
    # 若番号目录已有 enrich.log，合并源耗时/字段（清空扫描后仍可展示）
    try:
        from app.scrap_library import embed as embed_svc

        base = root
        if base is None:
            settings = embed_svc.get_settings()
            base = embed_svc.resolve_root(settings.get("root")).resolve()
        fol = (base / rel).resolve()
        try:
            fol.relative_to(base)
        except ValueError:
            fol = None  # type: ignore[assignment]
        if fol is not None and fol.is_dir():
            item = _merge_enrich_sidecar_into_item(item, folder=fol, region=rid)
            # 无刮削 sidecar 时，用本地 NFO 填字段表（转移入库）
            has_src_fields = isinstance(item.get("fields"), list) and any(
                isinstance(f, dict) and str(f.get("source") or "").strip()
                for f in (item.get("fields") or [])
            )
            if not has_src_fields:
                local_detail, fields, local_ok = _detail_from_local_folder(
                    fol, code=code_u
                )
                item["fields"] = fields
                if local_detail.get("detailTitle") and not str(
                    item.get("detailTitle") or ""
                ).strip():
                    item["detailTitle"] = local_detail["detailTitle"]
                if local_ok:
                    item["posterDownloaded"] = True
    except Exception:  # noqa: BLE001
        pass
    return item


class _LocalNfoMaps:
    """一次磁盘扫描分类结果（全量候选 + 预览样例）。"""

    __slots__ = (
        "complete_rels",
        "soft_rels",
        "hard",
        "done_cands",
        "soft_cands",
        "fail_cands",
        "done_samples",
        "soft_samples",
        "fail_samples",
        "done_n",
        "soft_n",
        "fail_n",
        "stream_written",
    )

    def __init__(self) -> None:
        self.complete_rels: set[str] = set()
        self.soft_rels: set[str] = set()
        self.hard: dict[str, dict[str, Any]] = {}
        # 全量轻量候选 (rel, code, gaps) — 供队列表翻页写入
        self.done_cands: list[tuple[str, str, list[str]]] = []
        self.soft_cands: list[tuple[str, str, list[str]]] = []
        self.fail_cands: list[tuple[str, str, list[str]]] = []
        # 带 sidecar 的预览样例（条数受 sample_cap 限制）
        self.done_samples: list[dict[str, Any]] = []
        self.soft_samples: list[dict[str, Any]] = []
        self.fail_samples: list[dict[str, Any]] = []
        self.done_n = 0
        self.soft_n = 0
        self.fail_n = 0
        self.stream_written = False

    @property
    def skip_rels(self) -> set[str]:
        """本地已分类（成功/软成功/失败）：向量骨架入未处理时应排除。"""
        return self.complete_rels | self.soft_rels | set(self.hard.keys())

    @property
    def classified_codes(self) -> set[str]:
        """本地已分类番号（大写），供与向量骨架 code 对齐排除。"""
        out: set[str] = set()
        for rel in self.skip_rels:
            base = str(rel or "").replace("\\", "/").rstrip("/").split("/")[-1]
            cu = base.strip().upper()
            if cu:
                out.add(cu)
        for item in self.hard.values():
            if not isinstance(item, dict):
                continue
            cu = str(item.get("code") or "").strip().upper()
            if cu:
                out.add(cu)
        return out


def _local_nfo_gap_maps(
    *,
    region: str,
    sample_cap: int = 500,
    report_progress: bool = False,
    workers: int | None = None,
    stream_write_region: str = "",
) -> _LocalNfoMaps:
    """一次扫本地分区：已齐 / 软成功 / 硬缺口（多线程分类）。

    全量候选写入 maps.*_cands；*_samples 仅保留 sample_cap 条富样例供预览。
    sample_cap<=0 时富样例默认取边扫预览上限。
    stream_write_region：边分类边写入该区队列表（与扫盘并行，仍为全量）。
    """
    import queue as queue_mod

    from app.scrap_library import embed as embed_svc

    rid = _queue_log_region(region)
    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root")).resolve()
    dirs = _region_local_dirs(root, rid or region)
    out = _LocalNfoMaps()
    if not dirs:
        return out

    scan_cap = _local_scan_workers()
    n_workers = max(1, min(scan_cap, int(workers or scan_cap)))
    total_est = 0
    if report_progress:
        try:
            total_est = int(
                (_region_library_progress(rid or region) or {}).get("total") or 0
            )
        except Exception:  # noqa: BLE001
            total_est = 0
        _set_queue_scan_progress(
            region=rid or region,
            stage="disk",
            label=f"扫描本地 NFO…（{n_workers} 线程）",
            scanned=0,
            total=total_est,
            done=0,
            soft=0,
            fail=0,
            notify=True,
        )

    rich_cap = (
        max(1, int(sample_cap))
        if int(sample_cap or 0) > 0
        else _QUEUE_SCAN_SAMPLE_CAP
    )
    done_cands = out.done_cands
    soft_cands = out.soft_cands
    fail_cands = out.fail_cands
    last_report = 0
    from app.core.container_budget import memory_class as _mem_class

    inflight_limit = n_workers * 4
    if _mem_class() == "host":
        inflight_limit = max(inflight_limit, 64)

    stream_rid = _queue_log_region(stream_write_region) if stream_write_region else ""
    stream_q: queue_mod.Queue | None = None
    stream_thread: threading.Thread | None = None
    stream_err: list[BaseException] = []
    stream_written_n = [0]
    flush_n = max(200, int(_SCAN_STREAM_FLUSH or 800))

    def _flush_stream_batch(
        batch: list[tuple[str, tuple[str, str, list[str]]]],
    ) -> None:
        if not batch or not stream_rid:
            return
        rows: list[dict[str, Any]] = []
        for kind, trip in batch:
            rel, code_u, gaps = trip
            rows.append(
                _local_status_item(
                    rel=rel,
                    code=code_u,
                    gaps=gaps,
                    region=stream_rid,
                    kind=kind,
                    root=root,
                    merge_sidecar=False,
                )
            )
        if rows:
            _queue_log_insert_many(stream_rid, rows)
            stream_written_n[0] += len(rows)
            if report_progress and (
                stream_written_n[0] < len(rows) + 5
                or stream_written_n[0] % 2000 < len(rows)
            ):
                _set_queue_scan_progress(
                    region=rid or region,
                    stage="disk",
                    label=(
                        f"扫描并写入 · 已分类 {out.done_n + out.soft_n + out.fail_n:,}"
                        f" · 已入库 {stream_written_n[0]:,}"
                        f" · 成功 {out.done_n:,} · 软成功 {out.soft_n:,}"
                        f" · 失败 {out.fail_n:,}"
                    ),
                    scanned=out.done_n + out.soft_n + out.fail_n,
                    total=max(total_est, out.done_n + out.soft_n + out.fail_n),
                    done=out.done_n,
                    soft=out.soft_n,
                    fail=out.fail_n,
                    notify=True,
                )

    if stream_rid:
        stream_q = queue_mod.Queue(maxsize=max(flush_n * 4, 4000))

        def _stream_writer() -> None:
            buf: list[tuple[str, tuple[str, str, list[str]]]] = []
            try:
                while True:
                    try:
                        item = stream_q.get(timeout=0.25)
                    except queue_mod.Empty:
                        if buf:
                            _flush_stream_batch(buf)
                            buf = []
                        continue
                    if item is None:
                        if buf:
                            _flush_stream_batch(buf)
                        break
                    buf.append(item)
                    if len(buf) >= flush_n:
                        _flush_stream_batch(buf)
                        buf = []
            except BaseException as e:  # noqa: BLE001
                stream_err.append(e)
                log.warning(
                    "stream write enrich queue failed region=%s: %s",
                    stream_rid,
                    e,
                )

        stream_thread = threading.Thread(
            target=_stream_writer,
            name="enrich-scan-stream-write",
            daemon=True,
        )
        stream_thread.start()

    def _work(rel: str, folder: Path) -> tuple[str, str, list[str]]:
        code_u, gaps = _local_folder_gaps(folder)
        return rel, code_u, list(gaps)

    def _absorb(rel: str, code_u: str, gaps: list[str]) -> None:
        nonlocal last_report
        kind = _classify_disk_gaps(gaps)
        gaps_l = list(gaps or [])
        if kind == "done":
            out.complete_rels.add(rel)
            out.done_n += 1
            trip = (rel, code_u, [])
            done_cands.append(trip)
            if report_progress and out.done_n <= _QUEUE_SCAN_SAMPLE_CAP:
                _queue_scan_add_sample(
                    "done",
                    _queue_scan_preview_item(
                        rel=rel,
                        code=code_u,
                        gaps=[],
                        region=rid or region,
                        kind="done",
                    ),
                )
        elif kind == "soft":
            out.soft_rels.add(rel)
            out.soft_n += 1
            trip = (rel, code_u, gaps_l)
            soft_cands.append(trip)
            if report_progress and out.soft_n <= _QUEUE_SCAN_SAMPLE_CAP:
                _queue_scan_add_sample(
                    "soft",
                    _queue_scan_preview_item(
                        rel=rel,
                        code=code_u,
                        gaps=gaps_l,
                        region=rid or region,
                        kind="soft",
                    ),
                )
        else:
            out.fail_n += 1
            out.hard[rel] = {
                "itemId": rel,
                "code": code_u,
                "gaps": gaps_l,
                "rel_path": rel,
                "relPath": rel,
                "region": rid or region,
                "status": "pending",
            }
            trip = (rel, code_u, gaps_l)
            fail_cands.append(trip)
            if report_progress and out.fail_n <= _QUEUE_SCAN_SAMPLE_CAP:
                _queue_scan_add_sample(
                    "fail",
                    _queue_scan_preview_item(
                        rel=rel,
                        code=code_u,
                        gaps=gaps_l,
                        region=rid or region,
                        kind="fail",
                    ),
                )
        if stream_q is not None:
            try:
                stream_q.put((kind, trip), timeout=30)
            except Exception:  # noqa: BLE001
                pass
        n = out.done_n + out.soft_n + out.fail_n
        if report_progress and (n - last_report >= 400 or n == 1):
            last_report = n
            tot = max(total_est, n)
            written_tip = (
                f" · 已入库 {stream_written_n[0]:,}" if stream_q is not None else ""
            )
            _set_queue_scan_progress(
                region=rid or region,
                stage="disk",
                label=(
                    f"扫描本地 · {n:,}"
                    + (f"/{tot:,}" if tot > n else "")
                    + written_tip
                    + f" · 成功 {out.done_n:,} · 软成功 {out.soft_n:,} · 失败 {out.fail_n:,}"
                ),
                scanned=n,
                total=tot,
                done=out.done_n,
                soft=out.soft_n,
                fail=out.fail_n,
                notify=True,
            )

    if report_progress:
        _set_queue_scan_progress(
            region=rid or region,
            stage="disk",
            label=f"枚举番号目录…（{n_workers} 线程）",
            notify=True,
        )
    folder_jobs = _collect_nfo_folders_parallel(
        list(dirs), root, workers=min(16, n_workers)
    )
    if report_progress and folder_jobs:
        total_est = max(total_est, len(folder_jobs))
        _set_queue_scan_progress(
            region=rid or region,
            stage="disk",
            label=f"分类本地 NFO… {len(folder_jobs):,} 个（{n_workers} 线程）",
            scanned=0,
            total=total_est,
            notify=True,
        )

    pending: set[Any] = set()
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        for rel, folder in folder_jobs:
            while len(pending) >= inflight_limit:
                done_set, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done_set:
                    try:
                        rel_r, code_u, gaps = fut.result()
                    except Exception:  # noqa: BLE001
                        continue
                    _absorb(rel_r, code_u, gaps)
            pending.add(pool.submit(_work, rel, folder))
        while pending:
            done_set, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done_set:
                try:
                    rel_r, code_u, gaps = fut.result()
                except Exception:  # noqa: BLE001
                    continue
                _absorb(rel_r, code_u, gaps)

    if stream_q is not None and stream_thread is not None:
        try:
            stream_q.put(None, timeout=60)
        except Exception:  # noqa: BLE001
            pass
        stream_thread.join(timeout=900)
        if not stream_err and stream_written_n[0] > 0:
            out.stream_written = True
        elif stream_err:
            log.warning(
                "stream write incomplete region=%s written=%s err=%s",
                stream_rid,
                stream_written_n[0],
                stream_err[0],
            )

    def _mk_sample(
        trip: tuple[str, str, list[str]], kind: str
    ) -> dict[str, Any]:
        rel, code_u, gaps = trip
        return _local_status_item(
            rel=rel,
            code=code_u,
            gaps=gaps,
            region=rid or region,
            kind=kind,
            root=root,
            merge_sidecar=True,
        )

    sample_jobs: list[tuple[str, tuple[str, str, list[str]]]] = []
    for t in done_cands[:rich_cap]:
        sample_jobs.append(("done", t))
    for t in soft_cands[:rich_cap]:
        sample_jobs.append(("soft", t))
    for t in fail_cands[:rich_cap]:
        sample_jobs.append(("fail", t))
    if sample_jobs:
        sw = max(2, min(n_workers, 12))
        with ThreadPoolExecutor(max_workers=sw) as pool:
            futs = [pool.submit(_mk_sample, trip, kind) for kind, trip in sample_jobs]
            for i, fut in enumerate(futs):
                try:
                    item = fut.result()
                except Exception:  # noqa: BLE001
                    kind, trip = sample_jobs[i]
                    item = _local_status_item(
                        rel=trip[0],
                        code=trip[1],
                        gaps=trip[2],
                        region=rid or region,
                        kind=kind,
                        root=root,
                        merge_sidecar=False,
                    )
                kind = sample_jobs[i][0]
                if kind == "done":
                    out.done_samples.append(item)
                elif kind == "soft":
                    out.soft_samples.append(item)
                else:
                    out.fail_samples.append(item)

    if report_progress:
        n = out.done_n + out.soft_n + out.fail_n
        written_tip = (
            f" · 已入库 {stream_written_n[0]:,}" if stream_written_n[0] else ""
        )
        _set_queue_scan_progress(
            region=rid or region,
            stage="disk",
            label=(
                f"本地分类完成 · {n:,}{written_tip}"
                f" · 成功 {out.done_n:,} · 软成功 {out.soft_n:,} · 失败 {out.fail_n:,}"
            ),
            scanned=n,
            total=max(total_est, n),
            done=out.done_n,
            soft=out.soft_n,
            fail=out.fail_n,
            notify=True,
        )
    return out


def _queue_log_insert_local_status_samples(
    region: str,
    maps: _LocalNfoMaps,
    *,
    write_cap: int = 0,
    root: Path | None = None,
) -> dict[str, int]:
    """本地分类全量写入队列表（轻量行，可翻页）；返回全量 done/soft/fail 计数。

    write_cap>0 时仅写入每态前 N 条（兼容旧样例模式）；<=0 写全量。
    """
    rid = _queue_log_region(region)
    empty = {"done": 0, "soft": 0, "fail": 0}
    if not rid or not isinstance(maps, _LocalNfoMaps):
        return empty
    cap = max(0, int(write_cap or 0))

    def _take(
        cands: list[tuple[str, str, list[str]]],
        samples: list[dict[str, Any]],
    ) -> list[tuple[str, str, list[str]]] | list[dict[str, Any]]:
        if cands:
            return cands if cap <= 0 else cands[:cap]
        if samples:
            return samples if cap <= 0 else samples[:cap]
        return []

    jobs: list[tuple[str, list[Any]]] = [
        ("done", _take(list(maps.done_cands or []), list(maps.done_samples or []))),
        ("soft", _take(list(maps.soft_cands or []), list(maps.soft_samples or []))),
        ("fail", _take(list(maps.fail_cands or []), list(maps.fail_samples or []))),
    ]
    total_rows = sum(len(xs) for _, xs in jobs)
    written = 0
    batch = 1000

    base_root = root
    if base_root is None:
        try:
            settings = embed_svc.get_settings()
            base_root = embed_svc.resolve_root(settings.get("root")).resolve()
        except Exception:  # noqa: BLE001
            base_root = None

    def _as_item(kind: str, raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, (tuple, list)) or len(raw) < 2:
            return None
        rel = str(raw[0] or "")
        code_u = str(raw[1] or "")
        gaps = list(raw[2] if len(raw) > 2 else [])
        return _local_status_item(
            rel=rel,
            code=code_u,
            gaps=gaps,
            region=rid,
            kind=kind,
            root=base_root,
            merge_sidecar=False,
        )

    try:
        for kind, xs in jobs:
            for start in range(0, len(xs), batch):
                chunk_raw = xs[start : start + batch]
                rows: list[dict[str, Any]] = []
                for raw in chunk_raw:
                    item = _as_item(kind, raw)
                    if item:
                        rows.append(item)
                if rows:
                    _queue_log_insert_many(rid, rows)
                written += len(rows)
                if total_rows >= 2000 and (
                    written == len(rows)
                    or written % 2000 < batch
                    or written >= total_rows
                ):
                    _set_queue_scan_progress(
                        region=rid,
                        stage="write",
                        label=(
                            f"写入分类队列 · {written:,}/{total_rows:,}"
                            f" · 成功 {maps.done_n:,} · 软成功 {maps.soft_n:,}"
                            f" · 失败 {maps.fail_n:,}"
                        ),
                        scanned=written,
                        total=total_rows,
                        done=int(maps.done_n or 0),
                        soft=int(maps.soft_n or 0),
                        fail=int(maps.fail_n or 0),
                        notify=True,
                    )
    except Exception as e:  # noqa: BLE001
        log.warning(
            "insert local status rows failed region=%s: %s", rid, e
        )
    _counts_cache.pop(rid, None)
    return {
        "done": int(maps.done_n or 0),
        "soft": int(maps.soft_n or 0),
        "fail": int(maps.fail_n or 0),
    }


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

    # 角标：向量库全部番号 − 本地成功/软成功/失败
    try:
        lib = _region_library_progress(rid or region)
        vector_total = int(lib.get("total") or 0)
    except Exception:  # noqa: BLE001
        vector_total = 0
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


def _hot_prefixes_for_region(region: str, *, max_n: int = 80) -> list[str]:
    """空壳降权用：本地已有前缀目录 + 近期成功前缀（高优切片）。"""
    from app.scrap_library import embed as embed_svc

    rid = _queue_log_region(region)
    out: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        p = str(raw or "").strip().upper()
        if not p or p in seen:
            return
        seen.add(p)
        out.append(p)

    try:
        settings = embed_svc.get_settings()
        root = embed_svc.resolve_root(settings.get("root")).resolve()
        for base in _region_local_dirs(root, rid or region):
            try:
                for child in base.iterdir():
                    if child.is_dir() and not child.name.startswith("_"):
                        _add(child.name)
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass

    # 近期成功前缀（队列表）
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT code FROM enrich_queue_log
                WHERE region=? AND status='done'
                ORDER BY id DESC
                LIMIT 200
                """,
                (rid,),
            ).fetchall()
        for r in rows or []:
            d = dict(r) if isinstance(r, dict) else {}
            code = str(d.get("code") or "").strip().upper()
            if "-" in code:
                _add(code.split("-", 1)[0])
            elif code:
                # FC2 等无横杠：取字母前缀
                m = re.match(r"^([A-Z]+)", code)
                if m:
                    _add(m.group(1))
    except Exception:  # noqa: BLE001
        pass

    return out[: max(1, int(max_n or 80))]


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
        maps = _local_nfo_gap_maps(region=rid or region)
        local_maps = maps
        local_classified = maps.skip_rels
        local_codes = maps.classified_codes

    # 「封面已放弃」的番号不再自动入队（否则每轮重抓全部源，且永远清不掉）；
    # 只抑制**仅剩封面缺口**的行 —— 同时缺剧情/女优的仍要重试。
    cover_giveup = _cover_giveup_codes(rid or region)
    # 上一轮因「高优先源不可用」而降级取值的番号：优先补抓（有界，见 _note_retry_hints）
    src_retry = [
        h
        for h in _retry_hint_load(rid or region, _RETRY_KIND_SRC_DOWN)
        if not h.get("giveup") and str(h.get("code") or "").strip()
    ]
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

    # 0) 源故障补抓：这些番号本地 NFO 是齐的，不会出现在下面任何来源里，
    #    必须显式补出来，否则「降级取值」就永远没人回头修。
    if src_retry:
        _push_log(
            f"源故障补抓 · {len(src_retry)} 个番号优先重跑（上一轮高优先源不可用）",
            region=rid or region,
        )
        head: list[dict[str, Any]] = []
        for h in src_retry:
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

    # 0b) 先吃队列表已有 pending（扫描/中断/失败·软成功重试），最新变更优先
    try:
        from app.core.db import connect, init_db

        init_db()
        log_off = 0
        with connect() as conn:
            while True:
                if _halt_kind():
                    return
                rows = conn.execute(
                    """
                    SELECT id, item_id, code, status, gaps_json, error, source,
                           fetch_ms, detail_title, payload_json
                    FROM enrich_queue_log
                    WHERE region=? AND status='pending'
                    ORDER BY updated_at DESC NULLS LAST, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (rid or region, bs, log_off),
                ).fetchall()
                batch_rows = list(rows or [])
                if not batch_rows:
                    break
                log_off += len(batch_rows)
                log_batch: list[dict[str, Any]] = []
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

    # 骨架/向量切片需要 done-keys；开刮线程可能还在加载——最多等几秒，不永久堵死
    if defer_skip_until is not None and not defer_skip_until.is_set():
        defer_skip_until.wait(timeout=15.0)

    # 后续骨架/向量切片才需要本地已分类映射
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


def scan_enrich_queue(
    *,
    region: str,
    limit: int = 0,
) -> dict[str, Any]:
    """打开日志页：重建队列（不启动刮削）。

    增量：向量全部番号 − 本地成功/软成功/失败 → 未处理（含本地已删回填）；
    覆盖：本地分区全部 NFO 进未处理。
    每次扫描强制把「成功/失败但本地已删」回滚为 pending。
    """
    rid = _queue_log_region(region)
    empty = {
        "ok": False,
        "scanned": False,
        "region": rid or None,
        "counts": {"pending": 0, "running": 0, "done": 0, "soft": 0, "fail": 0},
        "items": [],
        "scannedN": 0,
        "listedN": 0,
        "pendingTotal": 0,
        "prunedN": 0,
    }
    if not rid:
        empty["error"] = "region required"
        return empty

    with _enrich_lock:
        running = bool(_enrich_job.get("running"))
        cur_reg = str(_enrich_job.get("currentRegion") or "").strip()
    if running and _canonical_enrich_log_region(cur_reg) == rid:
        out = load_queue_log(region=rid, status="pending", limit=200)
        out["ok"] = True
        out["scanned"] = False
        out["reason"] = "running"
        out["scannedN"] = int((out.get("counts") or {}).get("pending") or 0)
        out["listedN"] = len(out.get("items") or [])
        out["pendingTotal"] = out["scannedN"]
        out["prunedN"] = 0
        return out

    from app.scrap_library.enrich_strategy import get_strategy

    # 扫描只落盘队首样例；未处理列表用虚拟翻页（向量 − 已分类），打开不卡
    _SCAN_WRITE = 500
    strat = get_strategy()
    mode = str(strat.get("fillMode") or "incremental").lower()
    overwrite = mode in {"overwrite", "cover", "force", "replace", "full"}
    fetch_lim = int(limit or 0)
    if fetch_lim <= 0:
        fetch_lim = 0
    else:
        fetch_lim = max(1, min(_SCAN_WRITE, fetch_lim))

    # 每次重扫强制回滚：本地已删的 done/fail → pending（不限频）
    try:
        _demoted_false_dones.discard(rid)
        demoted_scan = _queue_log_demote_false_dones(rid)
        _demoted_false_dones.add(rid)
        if demoted_scan:
            log.info(
                "scan demote missing-local region=%s n=%s", rid, demoted_scan
            )
    except Exception as e:  # noqa: BLE001
        log.warning("scan demote failed region=%s: %s", rid, e)
        demoted_scan = 0

    skip_done_iids, skip_done_codes = (
        (set(), set()) if overwrite else _queue_log_done_keys(rid)
    )

    _pending_backfill_done.discard(rid)
    _invalidate_classified_skip_cache(rid)

    _set_queue_scan_progress(
        region=rid,
        stage="start",
        label="开始扫描队列…",
        scanned=0,
        total=0,
        done=0,
        soft=0,
        fail=0,
        notify=True,
    )

    local_maps: _LocalNfoMaps | None = None
    try:
        if overwrite:
            # 覆盖模式：本地全部 NFO 进队（样例写入 + 全量计数）
            # 覆盖 = 用户明确要求「重来一遍」→ 解除两类有界重试的 giveup（封面 / 源故障），
            # 否则已放弃的番号在全量重扫里依然被跳过，用户没有别的办法把它们捞回来。
            _retry_hint_clear_region(rid)
            from app.scrap_library import embed as embed_svc

            settings = embed_svc.get_settings()
            root = embed_svc.resolve_root(settings.get("root")).resolve()
            dirs = _region_local_dirs(root, rid)
            samples: list[dict[str, Any]] = []
            seen: set[str] = set()
            write_cap = fetch_lim if fetch_lim > 0 else _SCAN_WRITE
            _set_queue_scan_progress(
                region=rid,
                stage="disk",
                label="覆盖模式 · 扫描本地 NFO…",
                notify=True,
            )
            last_report = 0
            for base in dirs:
                try:
                    nfo_iter = base.rglob("*.nfo")
                except Exception:  # noqa: BLE001
                    continue
                for nfo in nfo_iter:
                    folder = nfo.parent
                    try:
                        rel = folder.relative_to(root).as_posix()
                    except ValueError:
                        continue
                    if rel in seen:
                        continue
                    seen.add(rel)
                    if len(samples) < write_cap:
                        code_u, _gaps = _local_folder_gaps(folder)
                        samples.append(
                            {
                                "itemId": rel,
                                "code": code_u,
                                "gaps": list(_ENRICH_KINDS),
                                "rel_path": rel,
                                "relPath": rel,
                                "region": rid,
                                "status": "pending",
                            }
                        )
                    n = len(seen)
                    if n - last_report >= 200 or n == 1:
                        last_report = n
                        _set_queue_scan_progress(
                            region=rid,
                            stage="disk",
                            label=f"覆盖扫描 · 已发现 {n:,} 个番号",
                            scanned=n,
                            total=n,
                            notify=True,
                        )
            pending_total = len(seen)
            rows = samples
            source = "local_nfo_overwrite"
        else:
            write_cap = fetch_lim if fetch_lim > 0 else _SCAN_WRITE
            # 全量准确：先清旧 local_scan 分类行，扫盘时边分类边入库
            _queue_log_clear_local_scan_status(rid)
            local_maps = _local_nfo_gap_maps(
                region=rid,
                sample_cap=write_cap,
                report_progress=True,
                stream_write_region=rid,
            )
            _set_queue_scan_progress(
                region=rid,
                stage="pending",
                label="对照向量骨架生成未处理样例…",
                done=int(local_maps.done_n or 0),
                soft=int(local_maps.soft_n or 0),
                fail=int(local_maps.fail_n or 0),
                notify=True,
            )
            rows, pending_total = iter_enrich_pending_items(
                region=rid,
                limit=write_cap,
                skip_item_ids=skip_done_iids,
                skip_codes=skip_done_codes,
                local_maps=local_maps,
            )
            source = "vector_all_minus_local"

        seen_q: set[str] = set()
        queue_view: list[dict[str, Any]] = []
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            iid = str(r.get("itemId") or "").strip()
            if not iid or iid in seen_q:
                continue
            code_u = str(r.get("code") or "").strip().upper()
            seen_q.add(iid)
            item: dict[str, Any] = {
                "itemId": iid,
                "code": code_u,
                "gaps": list(r.get("gaps") or []),
                "status": "pending",
            }
            rel = str(r.get("rel_path") or r.get("relPath") or "").strip()
            if rel:
                item["rel_path"] = rel
                item["relPath"] = rel
            queue_view.append(item)

        pending_total = max(int(pending_total or 0), len(queue_view))

        _set_queue_scan_progress(
            region=rid,
            stage="write",
            label=(
                "分类已边扫边写，收尾…"
                if local_maps is not None and local_maps.stream_written
                else "写入分类队列（全量可翻页）…"
            ),
            scanned=int(
                (local_maps.done_n + local_maps.soft_n + local_maps.fail_n)
                if local_maps is not None
                else pending_total
            ),
            notify=True,
        )
        pruned = _queue_log_clear_pending(rid)
        queue_view = _ensure_queue_log_ids(rid, queue_view)
        recovered = _recover_done_from_enrich_logs(rid)

        # 成功/软成功/失败：优先用边扫边写结果；失败时再全量补写
        existing = _queue_log_status_counts(rid, fresh=True)
        status_n = (
            int(existing.get("done") or 0)
            + int(existing.get("soft") or 0)
            + int(existing.get("fail") or 0)
        )
        local_counts = {"done": 0, "soft": 0, "fail": 0}
        try:
            vector_total = int(
                (_region_library_progress(rid) or {}).get("total") or 0
            )
        except Exception:  # noqa: BLE001
            vector_total = 0
        if not overwrite and local_maps is not None and (
            local_maps.done_n or local_maps.soft_n or local_maps.fail_n
        ):
            local_counts = {
                "done": int(local_maps.done_n or 0),
                "soft": int(local_maps.soft_n or 0),
                "fail": int(local_maps.fail_n or 0),
            }
            local_status = (
                local_counts["done"] + local_counts["soft"] + local_counts["fail"]
            )
            if local_maps.stream_written and status_n >= max(1, int(local_status * 0.9)):
                # 边扫边写已覆盖绝大部分行
                pass
            else:
                # 未流式写入或写入不完整 → 清后全量补写
                _queue_log_clear_local_scan_status(rid)
                local_counts = _queue_log_insert_local_status_samples(
                    rid, local_maps, write_cap=0
                )
            _set_local_status_totals(
                rid,
                done=local_counts["done"],
                soft=local_counts["soft"],
                fail=local_counts["fail"],
                total=vector_total,
            )
        elif status_n <= 0 and not overwrite:
            if local_maps is None:
                local_maps = _local_nfo_gap_maps(
                    region=rid,
                    sample_cap=_QUEUE_SCAN_SAMPLE_CAP,
                    report_progress=True,
                    stream_write_region=rid,
                )
            if local_maps is not None and not local_maps.stream_written:
                local_counts = _queue_log_insert_local_status_samples(
                    rid, local_maps, write_cap=0
                )
            elif local_maps is not None:
                local_counts = {
                    "done": int(local_maps.done_n or 0),
                    "soft": int(local_maps.soft_n or 0),
                    "fail": int(local_maps.fail_n or 0),
                }
            _set_local_status_totals(
                rid,
                done=local_counts["done"],
                soft=local_counts["soft"],
                fail=local_counts["fail"],
                total=vector_total,
            )

        out = load_queue_log(region=rid, status="pending", limit=200)
        listed = len(queue_view)
        # 角标以扫描全量为准；成功/软成功/失败已全量写入可翻页
        counts = dict(out.get("counts") or {})
        counts["pending"] = int(pending_total)
        if local_counts["done"] or local_counts["soft"] or local_counts["fail"]:
            counts["done"] = int(local_counts["done"])
            counts["soft"] = int(local_counts["soft"])
            counts["fail"] = int(local_counts["fail"])
        else:
            counts = _apply_local_status_totals(counts, rid)
        out["counts"] = counts
        out["ok"] = True
        out["scanned"] = True
        out["scannedN"] = int(pending_total)
        out["listedN"] = listed
        out["pendingTotal"] = int(pending_total)
        out["prunedN"] = int(pruned or 0)
        out["recoveredDone"] = int(recovered or 0)
        out["demotedN"] = int(demoted_scan or 0)
        out["localDone"] = int(counts.get("done") or 0)
        out["localSoft"] = int(counts.get("soft") or 0)
        out["localFail"] = int(counts.get("fail") or 0)
        out["mode"] = "overwrite" if overwrite else "incremental"
        out["source"] = source
        out["truncated"] = listed < int(pending_total)
        return out
    finally:
        _clear_queue_scan_progress()


def _code_search_match(code: str, needle: str) -> bool:
    c = str(code or "").strip().upper().replace(" ", "").replace("　", "")
    n = str(needle or "").strip().upper().replace(" ", "").replace("　", "")
    if not c or not n:
        return False
    return c == n or (len(n) >= 2 and c.startswith(n))


def _lookup_code_from_scan_samples(
    *,
    region: str,
    code_q: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """扫描中内存样例（跨 done/soft/fail，未入库也能搜）。"""
    rid = _queue_log_region(region)
    needle = (
        str(code_q or "").strip().upper().replace(" ", "").replace("　", "")
    )
    if not rid or not needle:
        return []
    lim = max(1, min(int(limit or 20), 100))
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with _QUEUE_SCAN_LOCK:
            snap = {
                "done": list(_QUEUE_SCAN_STATE.get("samplesDone") or []),
                "soft": list(_QUEUE_SCAN_STATE.get("samplesSoft") or []),
                "fail": list(_QUEUE_SCAN_STATE.get("samplesFail") or []),
                "region": str(_QUEUE_SCAN_STATE.get("region") or ""),
                "active": bool(_QUEUE_SCAN_STATE.get("active")),
            }
        if snap["region"] and snap["region"] != rid:
            return []
        if not (snap["active"] or snap["done"] or snap["soft"] or snap["fail"]):
            return []
        for bucket, rows in (
            ("fail", snap["fail"]),
            ("soft", snap["soft"]),
            ("done", snap["done"]),
        ):
            for raw in rows:
                if not isinstance(raw, dict):
                    continue
                code_u = str(raw.get("code") or "").strip().upper()
                if not _code_search_match(code_u, needle):
                    continue
                key = (
                    str(
                        raw.get("itemId")
                        or raw.get("relPath")
                        or raw.get("rel_path")
                        or code_u
                    ).strip()
                )
                if not key or key in seen:
                    continue
                seen.add(key)
                item = dict(raw)
                if bucket == "soft":
                    item["status"] = "done"
                    item["partialOk"] = True
                elif bucket == "done":
                    item["status"] = "done"
                    item["partialOk"] = False
                else:
                    item["status"] = "fail"
                out.append(item)
                if len(out) >= lim:
                    return out
    except Exception:  # noqa: BLE001
        return out
    return out


def _lookup_code_outside_queue_log(
    *,
    region: str,
    code_q: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """队列表未命中时：扫描内存样例 + 本地目录/向量库，跨状态查找番号。"""
    rid = _queue_log_region(region)
    needle = (
        str(code_q or "").strip().upper().replace(" ", "").replace("　", "")
    )
    if not rid or not needle:
        return []
    lim = max(1, min(int(limit or 20), 100))
    out = _lookup_code_from_scan_samples(region=rid, code_q=needle, limit=lim)
    if out:
        return out
    seen = {
        str(it.get("itemId") or it.get("code") or "").strip() for it in out if it
    }

    # 精确：本地番号目录 → 按缺口归类
    try:
        folder = _resolve_enrich_folder(region=rid, code=needle)
        if folder is not None:
            settings = embed_svc.get_settings()
            root = embed_svc.resolve_root(settings.get("root")).resolve()
            try:
                rel = folder.relative_to(root).as_posix()
            except ValueError:
                rel = folder.name
            code_u, gaps = _local_folder_gaps(folder)
            kind = _classify_disk_gaps(gaps)
            item = _local_status_item(
                rel=rel,
                code=code_u or needle,
                gaps=list(gaps or []),
                region=rid,
                kind=kind,
                root=root,
                merge_sidecar=True,
            )
            key = str(item.get("itemId") or item.get("code") or "").strip()
            if key and key not in seen:
                out.append(item)
            if out:
                return out
    except Exception as e:  # noqa: BLE001
        log.debug(
            "code search disk lookup failed region=%s code=%s: %s",
            rid,
            needle,
            e,
        )

    # 向量库：未落盘分类 → 未处理
    try:
        embed_svc.ensure_schema()
        pool = get_meta_pool()
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT item_id, region, prefix, code, title, rel_path
                FROM {embed_svc.TABLE}
                WHERE UPPER(code) = %s
                   OR (LENGTH(%s) >= 2 AND UPPER(code) LIKE %s)
                ORDER BY
                  CASE WHEN UPPER(code) = %s THEN 0 ELSE 1 END,
                  CASE WHEN region = %s THEN 0 ELSE 1 END,
                  updated_at DESC NULLS LAST
                LIMIT %s
                """,
                (needle, needle, f"{needle}%", needle, rid, lim),
            )
            rows = cur.fetchall() or []
        for row in rows:
            d = dict(row) if isinstance(row, dict) else {}
            code_u = str(d.get("code") or "").strip().upper()
            if not _code_search_match(code_u, needle):
                continue
            rel = (
                str(d.get("rel_path") or d.get("item_id") or "")
                .replace("\\", "/")
                .strip()
            )
            key = str(d.get("item_id") or rel or code_u).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "itemId": key,
                    "code": code_u,
                    "status": "pending",
                    "gaps": list(_ENRICH_KINDS),
                    "rel_path": rel,
                    "relPath": rel,
                    "region": rid,
                    "detailTitle": str(d.get("title") or "")[:300],
                    "source": "vector",
                    "error": "待处理",
                }
            )
            if len(out) >= lim:
                break
    except Exception as e:  # noqa: BLE001
        log.debug(
            "code search vector lookup failed region=%s code=%s: %s",
            rid,
            needle,
            e,
        )

    return out


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

    # 未处理：虚高全量补写在后台清掉；列表立即虚拟翻页
    if st == "pending" and not code_q and not bool(_QUEUE_SCAN_STATE.get("active")):
        try:
            raw_p = _queue_log_status_counts_db(rid)
            db_p = int(raw_p.get("pending") or 0)
            est_p = _pending_total_estimate(rid)
            if est_p > 0 and db_p > max(int(est_p * 1.15), est_p + 200):
                threading.Thread(
                    target=_queue_log_trim_inflated_pending,
                    args=(rid,),
                    name=f"trim-pending-{rid}",
                    daemon=True,
                ).start()
        except Exception as e:  # noqa: BLE001
            log.debug("schedule trim inflated pending skipped: %s", e)

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
                    est = _pending_total_estimate(rid)
                    # 翻页总数/角标都以估算为准，不被库内虚高 pending 抬高
                    total = est if est > 0 else int(db_counts.get("pending") or 0)
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


def _queue_row_status(row: Any) -> str:
    """内存队列行的状态串（规范化后）。

    **唯一真相源**：`_queue_counts_of` 与暂停态改写的展示层都走这里，
    避免两处对 status 的读法漂移（曾出现大小写/空白不一致导致计数与展示打架）。

    注意：这里的行是内存队列 dict，不是 DB 行——形态为
    `{"status": "running"|"pending"|"done"|"fail", "code": ..., "itemId": ...}`。
    """
    if not isinstance(row, dict):
        return ""
    return str(row.get("status") or "").strip().lower()


def _queue_counts_of(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = _empty_queue_counts()
    for row in rows:
        if not isinstance(row, dict):
            continue
        st = _queue_row_status(row) or "pending"
        if st == "done":
            if bool(row.get("partialOk")) or _is_soft_ok_error(
                str(row.get("error") or "")
            ):
                counts["soft"] += 1
            else:
                counts["done"] += 1
            continue
        if st not in counts:
            st = "pending"
        counts[st] += 1
    return counts


_QUEUE_SAMPLE_LIMIT = 48
# 最近一次采样缓存：(队列对象, 长度, limit, 结果)。
# 用**对象身份**判定队列是否换过——`_patch_queue_item` 等每次改动都是
# `list(q)` 整体替换，所以身份变化 ⟺ 内容变化。缓存持强引用，旧 list 不会被
# GC，id 也就不会被复用，判定可靠。
_queue_sample_cache: tuple[Any, int, int, list[dict[str, Any]]] | None = None

# 状态/SSE 帧禁止带上的重字段（详情点开再从 queue-log 拉）
_STATUS_QUEUE_HEAVY_KEYS = frozenset(
    {
        "sourceTimings",
        "fields",
        "wouldFill",
        "actors",
    }
)


def _slim_queue_row_for_status(row: dict[str, Any]) -> dict[str, Any]:
    """SSE/status 热路径：只留列表行需要的摘要。

    实测未瘦身时 120 行带 sourceTimings/fields ≈ 150KB+/帧，
    设置页总览 SSE 每 0.2s 解析一次会把主线程卡死。
    """
    if not isinstance(row, dict):
        return {}
    out = {k: v for k, v in row.items() if k not in _STATUS_QUEUE_HEAVY_KEYS}
    title = str(row.get("detailTitle") or "")
    if title:
        out["detailTitle"] = title[:120]
    timings = row.get("sourceTimings")
    if isinstance(timings, list) and timings:
        out["sourceTimingCount"] = len(timings)
    fields = row.get("fields")
    if isinstance(fields, list) and fields:
        out["fieldCount"] = len(fields)
    return out


def _slim_queue_for_status(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        _slim_queue_row_for_status(r) for r in rows if isinstance(r, dict)
    ]


def _slim_current_for_status(current: Any) -> Any:
    """current 里的 sourceTimings 保留精简版（监控条要用），去掉超大字段。"""
    if not isinstance(current, dict):
        return current
    out = dict(current)
    timings = out.get("sourceTimings")
    if isinstance(timings, list) and timings:
        slim_t: list[dict[str, Any]] = []
        for t in timings[:16]:
            if not isinstance(t, dict):
                continue
            slim_t.append(
                {
                    "id": t.get("id"),
                    "status": t.get("status"),
                    "ok": t.get("ok"),
                    "ms": t.get("ms"),
                    "waitMs": t.get("waitMs"),
                    "kind": t.get("kind"),
                    "error": str(t.get("error") or "")[:80],
                    "actors": t.get("actors"),
                    "poster": t.get("poster"),
                }
            )
        out["sourceTimings"] = slim_t
    return out


def _sample_queue_uncached(
    raw_queue: list[Any], *, limit: int
) -> list[dict[str, Any]]:
    """单趟抽样的**实现体**（4 次 C 层推导，常数最小）。

    注意别改成"单次 Python 循环"：实测 2 万行时 1 次 Python 循环反而比
    4 次列表推导慢（4.6ms vs 3.1ms），因为推导的循环体在 C 层跑。
    """
    running = [r for r in raw_queue if isinstance(r, dict) and r.get("status") == "running"]
    pending = [
        r
        for r in raw_queue
        if isinstance(r, dict) and (r.get("status") or "pending") in {"pending", ""}
    ]
    fail = [r for r in raw_queue if isinstance(r, dict) and r.get("status") == "fail"]
    done = [r for r in raw_queue if isinstance(r, dict) and r.get("status") == "done"]
    # 当前 + 未处理头 + 最近失败/成功（新完成的在前）
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in (
        *running[:8],
        *pending[:48],
        *reversed(fail[-32:]),
        *reversed(done[-32:]),
    ):
        key = str(row.get("itemId") or row.get("code") or id(row))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


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


def _slim_result_for_status(result: Any) -> Any:
    """状态/落盘只保留汇总，丢掉 parts/items 明细（可达 100KB+，轮询会拖垮线程池）。"""
    if not isinstance(result, dict):
        return result
    # 批量 enrich：顶层带 parts/items
    if "parts" in result or "items" in result:
        slim_parts: list[dict[str, Any]] = []
        for p in list(result.get("parts") or []):
            if not isinstance(p, dict):
                continue
            items = p.get("items")
            slim_parts.append(
                {
                    "dryRun": bool(p.get("dryRun")),
                    "mode": str(p.get("mode") or ""),
                    "region": str(p.get("region") or ""),
                    "kinds": list(p.get("kinds") or []),
                    "queued": int(p.get("queued") or 0),
                    "ok": int(p.get("ok") or 0),
                    "failed": int(p.get("failed") or 0),
                    "cancelled": bool(p.get("cancelled")),
                    "paused": bool(p.get("paused")),
                    "remaining": int(p.get("remaining") or 0),
                    "itemCount": len(items) if isinstance(items, list) else 0,
                }
            )
        out = {
            k: v
            for k, v in result.items()
            if k not in {"parts", "items", "groups", "sources"}
        }
        out["parts"] = slim_parts
        out["items"] = []
        out["itemsTruncated"] = True
        return out
    # 单条 enrich：保留摘要，去掉嵌套超大字段明细
    nested = result.get("result")
    if isinstance(nested, dict):
        slim_nested = {
            k: v
            for k, v in nested.items()
            if k
            not in {
                "items",
                "parts",
                "groups",
                "sources",
                "sourceTimings",
                "fields",
            }
        }
        if "sourceTimings" in nested and isinstance(nested.get("sourceTimings"), list):
            slim_nested["sourceTimingCount"] = len(nested["sourceTimings"])
        if "fields" in nested and isinstance(nested.get("fields"), list):
            slim_nested["fieldCount"] = len(nested["fields"])
        out = dict(result)
        out["result"] = slim_nested
        # item 行本身不大，保留；若异常巨大则丢掉
        item = out.get("item")
        if isinstance(item, dict) and len(str(item)) > 8000:
            out["item"] = {
                "itemId": item.get("itemId") or item.get("id"),
                "code": item.get("code"),
            }
        return out
    return result


def _progress_from_queue_counts(
    counts: dict[str, int], *, base: dict[str, Any] | None = None
) -> dict[str, Any]:
    """进度只跟本轮队列计数对齐（成功+软成功+失败）/（成功+软成功+失败+未处理）。"""
    ok_n = int(counts.get("done") or 0) + int(counts.get("soft") or 0)
    fin = ok_n + int(counts.get("fail") or 0)
    rem = int(counts.get("pending") or 0) + int(counts.get("running") or 0)
    tot = fin + rem
    cur = dict(base or {})
    cur.update(
        {
            "done": fin,
            "total": tot,
            "ok": ok_n,
            "failed": int(counts.get("fail") or 0),
            "percent": _enrich_percent(fin, tot) if tot > 0 else 0,
        }
    )
    return cur


_incomplete_cache: dict[str, tuple[float, int, int]] = {}
_INCOMPLETE_CACHE_TTL_SEC = 45.0


def _region_library_progress(region: str) -> dict[str, int]:
    """库内进度（状态热路径）：轻量 total + tip 已分类。

    未处理 = total − done − soft − fail（与扫描角标同源）。
    禁止调用 quality_stats（分项 COUNT 在有码区要数秒，会卡死设置页）。
    """
    rid = _queue_log_region(region)
    if not rid:
        return {"total": 0, "incomplete": 0, "complete": 0, "percent": 0}
    _ensure_local_status_totals_loaded()
    tip = _LOCAL_STATUS_TOTALS.get(rid) or {}
    now = time.time()
    hit = _incomplete_cache.get(rid)
    if hit and now - hit[0] < _INCOMPLETE_CACHE_TTL_SEC:
        total = int(hit[1])
    else:
        total = int(tip.get("total") or 0)
        if total <= 0:
            try:
                from app.scrap_library.embed import region_library_totals_fast

                total = int(
                    region_library_totals_fast(region=rid).get("total") or 0
                )
            except Exception:  # noqa: BLE001
                total = 0
        if total > 0:
            # 回写 tip.total，后续状态读 O(1)
            if int(tip.get("total") or 0) != total:
                _set_local_status_totals(
                    rid,
                    done=int(tip.get("done") or 0),
                    soft=int(tip.get("soft") or 0),
                    fail=int(tip.get("fail") or 0),
                    total=total,
                )
                tip = _LOCAL_STATUS_TOTALS.get(rid) or tip
        _incomplete_cache[rid] = (now, total, 0)
    done_n = int(tip.get("done") or 0)
    soft_n = int(tip.get("soft") or 0)
    fail_n = int(tip.get("fail") or 0)
    # 已刮完（含软成功）视为完成；未处理(+fail 仍算待办里的剩余用 pending 公式)
    complete = done_n + soft_n
    incomplete = max(0, total - done_n - soft_n - fail_n) if total > 0 else 0
    # 缓存 incomplete 供同 TTL 复用
    _incomplete_cache[rid] = (now, total, incomplete)
    pct = _enrich_percent(complete, total) if total > 0 else 0
    return {
        "total": total,
        "incomplete": incomplete,
        "complete": complete,
        "percent": int(pct),
    }


def get_enrich_status(*, lite: bool = False) -> dict[str, Any]:
    """刮削状态快照。

    lite=True：总览页 / 角标用，不含 queue 抽样与大段日志（SSE 高频友好）。
    lite=False：详情直播页用，带瘦身后的 queue 抽样。
    """
    _hydrate_enrich_runtime()
    with _enrich_lock:
        region_logs_raw = _enrich_job.get("regionLogs") or {}
        region_logs: dict[str, list[str]] = {}
        region_log_counts: dict[str, int] = {}
        log_tail = 8 if lite else _ENRICH_LOG_RETURN
        if isinstance(region_logs_raw, dict):
            for rid, lines in region_logs_raw.items():
                key = str(rid or "").strip()
                if not key:
                    continue
                full = list(lines or [])
                region_log_counts[key] = len(full)
                if not lite:
                    region_logs[key] = full[-log_tail:]
        checkpoints = _checkpoint_summaries()
        halt = _enrich_job.get("halt")
        current_region = str(_enrich_job.get("currentRegion") or "")
        running = bool(_enrich_job["running"])
        phase_now = str(_enrich_job.get("phase") or "")
        # 已暂停/停止：状态对外一律非 running（避免清空被「繁忙」误拦）
        if halt in {"pause", "stop"} or phase_now in {
            "paused",
            "stopping",
            "stopped",
        }:
            running = False
        # 热路径：队列可达 2 万+ 行。**不要**在这里 `list(...)` 拷贝——
        # 队列每次改动都是整体替换新 list 对象，直接持有引用即可得到一致快照，
        # 而拷贝会破坏 `_sample_queue_for_status` 的按身份缓存（导致每帧重扫）。
        raw_queue = _enrich_job.get("queue") or []
        if lite:
            queue: list[dict[str, Any]] = []
        else:
            queue = _slim_queue_for_status(_sample_queue_for_status(raw_queue))
        stored_counts = _enrich_job.get("queueCounts")
        if isinstance(stored_counts, dict) and any(
            int(stored_counts.get(k) or 0) > 0
            for k in ("pending", "running", "done", "soft", "fail")
        ):
            queue_counts = {
                k: int(stored_counts.get(k) or 0)
                for k in ("pending", "running", "done", "soft", "fail")
            }
        else:
            queue_counts = _queue_counts_of(raw_queue)
        # 暂停后若运行时队列被置空，用检查点剩余队列回填展示（停止则无检查点）
        # 切勿物化 10万+ 行：只抽样 + 用长度/计数填角标
        if not running and not queue:
            raw_cps = dict(_enrich_job.get("checkpoints") or {})
            for rid, cp in raw_cps.items():
                if not isinstance(cp, dict):
                    continue
                remaining = cp.get("queue") or []
                sample_n = (
                    len(remaining) if isinstance(remaining, list) else 0
                )
                rem_n = max(int(cp.get("remainingCount") or 0), sample_n)
                if rem_n <= 0:
                    continue
                done = int(cp.get("done") or 0)
                ok_n = int(cp.get("ok") or 0)
                fail_n = int(cp.get("failed") or 0)
                sample = (
                    [
                        _slim_queue_row_for_status(r)
                        for r in remaining[:48]
                        if isinstance(r, dict)
                    ]
                    if isinstance(remaining, list)
                    else []
                )
                rebuilt: list[dict[str, Any]] = []
                for j, row in enumerate(sample):
                    rebuilt.append(
                        {
                            "index": done + j,
                            "itemId": str(row.get("itemId") or ""),
                            "code": str(row.get("code") or ""),
                            "gaps": list(row.get("gaps") or []),
                            "status": "pending",
                        }
                    )
                queue = rebuilt
                queue_counts = {
                    "pending": rem_n,
                    "running": 0,
                    "done": ok_n,
                    "fail": fail_n,
                }
                break
        progress = _progress_from_queue_counts(
            queue_counts, base=dict(_enrich_job.get("progress") or {})
        )
        if running:
            _enrich_job["progress"] = progress
            _enrich_job["queueCounts"] = queue_counts
        # 暂停/停止：内存队列禁止残留 running（一律视作 pending）
        # 旧实现为此遍历并拷贝整个队列（2 万+ 行）——状态热路径不允许。
        # 计数直接用 queue_counts 的 running 搬移到 pending（O(1)，两者同源），
        # 展示层只对抽样出的行（≤limit）改状态。
        if halt in {"pause", "stop"} or str(_enrich_job.get("phase") or "") in {
            "paused",
            "stopping",
            "stopped",
        }:
            stray = int(queue_counts.get("running") or 0)
            if stray:
                queue_counts = {
                    **queue_counts,
                    "pending": int(queue_counts.get("pending") or 0) + stray,
                    "running": 0,
                }
            queue = [
                (
                    {**r, "status": "pending"}
                    if _queue_row_status(r) == "running"
                    else r
                )
                for r in queue
            ]
        pending_total = int(queue_counts.get("pending") or 0)
        monitor = enrich_mon.snapshot()
        stall_by_code: dict[str, str] = {}
        for it in monitor.get("inflight") or []:
            if not isinstance(it, dict):
                continue
            stall = it.get("stall")
            if not isinstance(stall, dict):
                continue
            lab = str(stall.get("label") or "").strip()
            code_k = str(it.get("code") or "").strip().upper()
            if lab and code_k:
                stall_by_code[code_k] = lab
        if stall_by_code:
            annotated: list[dict[str, Any]] = []
            for r in queue:
                if not isinstance(r, dict):
                    continue
                if str(r.get("status") or "") != "running":
                    annotated.append(r)
                    continue
                lab = stall_by_code.get(str(r.get("code") or "").strip().upper())
                annotated.append({**r, "stallLabel": lab} if lab else r)
            queue = annotated
        queue_total_n = sum(
            int(queue_counts.get(k) or 0)
            for k in ("pending", "running", "done", "fail")
        )
        status = {
            "running": running,
            "phase": _enrich_job.get("phase") or "",
            "progress": progress,
            "log": list(_enrich_job.get("log") or [])[-(8 if lite else 40) :],
            "regionLogs": region_logs,
            "regionLogCounts": region_log_counts,
            "currentRegion": current_region,
            "cancel": bool(_enrich_job.get("cancel")) or halt in {"pause", "stop"},
            "halt": halt,
            "paused": bool(checkpoints),
            "checkpoints": checkpoints,
            "queue": queue,
            "queueTotal": queue_total_n,
            "queueCounts": dict(queue_counts),
            # queueTotal 由计数求和得出，等价于旧 `len(queue_full)`（每行必归一类）
            "queueTruncated": pending_total > len(queue) or queue_total_n > len(queue),
            "current": None if lite else _slim_current_for_status(_enrich_job.get("current")),
            "result": _slim_result_for_status(_enrich_job.get("result")),
            "error": _enrich_job.get("error"),
            "monitor": monitor,
            "queueScan": None if lite else _queue_scan_snapshot(),
            "lite": bool(lite),
        }

    # 角标成功/失败并入库计数（勿在 _enrich_lock 内打 DB）
    # 暂停时 currentRegion 常为空：按检查点分区回填，避免成功/失败仍停在本轮内存 15
    # 完成后检查点已清：仍要从 result.regions/parts 回填，否则角标卡在截断内存队列（如 80/80）
    count_regions: list[str] = []
    cur_rid = _queue_log_region(str(status.get("currentRegion") or ""))
    if cur_rid:
        count_regions.append(cur_rid)
    if not status.get("running"):
        for rid in (status.get("checkpoints") or {}):
            key = _queue_log_region(str(rid or ""))
            if key and key not in count_regions:
                count_regions.append(key)
        result_obj = status.get("result") if isinstance(status.get("result"), dict) else {}
        for rid in list(result_obj.get("regions") or []):
            key = _queue_log_region(str(rid or ""))
            if key and key not in count_regions:
                count_regions.append(key)
        for part in list(result_obj.get("parts") or []):
            if not isinstance(part, dict):
                continue
            key = _queue_log_region(str(part.get("region") or ""))
            if key and key not in count_regions:
                count_regions.append(key)
        # 空闲时把 tip 里已有分区也算上，避免详情页角标停在旧扫描数
        _ensure_local_status_totals_loaded()
        for rid in list(_LOCAL_STATUS_TOTALS.keys()):
            key = _queue_log_region(str(rid or ""))
            if key and key not in count_regions:
                count_regions.append(key)
    if count_regions:
        # 运行中（含详情 SSE）：只用内存 queueCounts / monitor，禁止每帧打库
        if status.get("running"):
            ui_counts = dict(status.get("queueCounts") or {})
            mon = (
                status.get("monitor")
                if isinstance(status.get("monitor"), dict)
                else {}
            )
            inflight_n = len(list(mon.get("inflight") or []))
            if inflight_n > 0:
                ui_counts["running"] = inflight_n
            status["queueCounts"] = ui_counts
            status["queueTotal"] = sum(
                int(ui_counts.get(k) or 0)
                for k in ("pending", "running", "done", "soft", "fail")
            )
            base_prog = dict(status.get("progress") or {})
            status["progress"] = _progress_from_queue_counts(
                ui_counts, base=base_prog
            )
            # 仅用 tip 内存，禁止 region_library_progress / DB
            _ensure_local_status_totals_loaded()
            library: dict[str, Any] = {}
            region_queue_counts: dict[str, dict[str, int]] = {}
            cur_rid_mem = _queue_log_region(str(status.get("currentRegion") or ""))
            for rid_counts in count_regions:
                tip = _LOCAL_STATUS_TOTALS.get(rid_counts) or {}
                total = int(tip.get("total") or 0)
                done_n = int(tip.get("done") or 0)
                soft_n = int(tip.get("soft") or 0)
                fail_n = int(tip.get("fail") or 0)
                complete = done_n + soft_n
                incomplete = (
                    max(0, total - done_n - soft_n - fail_n) if total else 0
                )
                library[rid_counts] = {
                    "total": total,
                    "incomplete": incomplete,
                    "complete": complete,
                    "percent": int(round(100.0 * complete / max(total, 1)))
                    if total > 0
                    else 0,
                }
                if rid_counts == cur_rid_mem:
                    region_queue_counts[rid_counts] = {
                        "pending": int(ui_counts.get("pending") or 0),
                        "running": inflight_n,
                        "done": int(ui_counts.get("done") or 0),
                        "soft": int(ui_counts.get("soft") or 0),
                        "fail": int(ui_counts.get("fail") or 0),
                    }
                else:
                    region_queue_counts[rid_counts] = {
                        "pending": incomplete,
                        "running": 0,
                        "done": done_n,
                        "soft": soft_n,
                        "fail": fail_n,
                    }
            if library:
                status["library"] = library
            status["regionQueueCounts"] = region_queue_counts
            if cur_rid_mem and cur_rid_mem in region_queue_counts:
                status["queueCounts"] = dict(region_queue_counts[cur_rid_mem])
                status["queueCountsRegion"] = cur_rid_mem
            elif count_regions:
                status["queueCountsRegion"] = count_regions[0]
        else:
            ui_counts = dict(status.get("queueCounts") or {})
            cps_ui = dict(status.get("checkpoints") or {})
            for rid_counts in count_regions:
                dbc = _queue_log_status_counts(rid_counts)
                # 空闲时清掉库残留 running，避免「处理中」假数据
                if not status.get("running") and int(dbc.get("running") or 0) > 0:
                    _queue_log_reopen_running(region=rid_counts)
                    dbc = _queue_log_status_counts(rid_counts)
                if status.get("running"):
                    # 运行中：本轮内存与库取大（避免轮询漏计）
                    ui_counts["done"] = max(
                        int(ui_counts.get("done") or 0), int(dbc.get("done") or 0)
                    )
                    ui_counts["soft"] = max(
                        int(ui_counts.get("soft") or 0), int(dbc.get("soft") or 0)
                    )
                    ui_counts["fail"] = max(
                        int(ui_counts.get("fail") or 0), int(dbc.get("fail") or 0)
                    )
                    ui_counts["pending"] = max(
                        int(ui_counts.get("pending") or 0),
                        int(dbc.get("pending") or 0),
                    )
                else:
                    # 暂停/空闲：队列表是唯一真相
                    ui_counts["done"] = int(dbc.get("done") or 0)
                    ui_counts["soft"] = int(dbc.get("soft") or 0)
                    ui_counts["fail"] = int(dbc.get("fail") or 0)
                    ui_counts["pending"] = int(dbc.get("pending") or 0)
                    ui_counts["running"] = 0
                    stray_run = int(dbc.get("running") or 0)
                    if stray_run > 0:
                        ui_counts["pending"] = int(ui_counts["pending"]) + stray_run
                cp = cps_ui.get(rid_counts)
                if isinstance(cp, dict):
                    cp = dict(cp)
                    ok_bucket = int(dbc.get("done") or 0) + int(dbc.get("soft") or 0)
                    if status.get("running"):
                        cp["ok"] = max(int(cp.get("ok") or 0), ok_bucket)
                        cp["failed"] = max(
                            int(cp.get("failed") or 0), int(dbc.get("fail") or 0)
                        )
                    else:
                        cp["ok"] = ok_bucket
                        cp["failed"] = int(dbc.get("fail") or 0)
                        cp["remaining"] = int(ui_counts.get("pending") or 0)
                        done_n = int(cp["ok"]) + int(cp["failed"])
                        rem_n = int(cp["remaining"])
                        cp["total"] = max(int(cp.get("total") or 0), done_n + rem_n)
                        cp["done"] = done_n
                    cps_ui[rid_counts] = cp
            # 「处理中」= 真实 inflight；暂停/停止归零
            halt_now = str(status.get("halt") or "")
            phase_now = str(status.get("phase") or "")
            if (
                not status.get("running")
                or halt_now in {"pause", "stop"}
                or phase_now in {"paused", "stopping", "stopped"}
            ):
                stray = int(ui_counts.get("running") or 0)
                if stray > 0:
                    ui_counts["pending"] = int(ui_counts.get("pending") or 0) + stray
                ui_counts["running"] = 0
            elif status.get("running"):
                mon = (
                    status.get("monitor")
                    if isinstance(status.get("monitor"), dict)
                    else {}
                )
                inflight = list(mon.get("inflight") or [])
                inflight_n = len(inflight)
                ui_counts["running"] = inflight_n
                keep_ids = {
                    str(it.get("itemId") or "").strip()
                    for it in inflight
                    if isinstance(it, dict) and str(it.get("itemId") or "").strip()
                }
                for rid_counts in count_regions:
                    stale = _queue_log_reopen_stale_running(
                        rid_counts, keep_item_ids=keep_ids
                    )
                    if stale:
                        ui_counts["pending"] = int(ui_counts.get("pending") or 0) + stale
                with _enrich_lock:
                    qc_mem = dict(_enrich_job.get("queueCounts") or {})
                    qc_mem["running"] = inflight_n
                    _enrich_job["queueCounts"] = qc_mem
            status["checkpoints"] = cps_ui
            status["queueCounts"] = ui_counts
            status["queueTotal"] = sum(
                int(ui_counts.get(k) or 0)
                for k in ("pending", "running", "done", "fail")
            )
            base_prog = dict(status.get("progress") or {})
            status["progress"] = _progress_from_queue_counts(ui_counts, base=base_prog)

            # 未处理 = 向量库所有番号 − 成功 − 软成功 − 失败（按分区独立，禁止串区）
            library: dict[str, Any] = {}
            region_queue_counts: dict[str, dict[str, int]] = {}
            run_n_global = int(ui_counts.get("running") or 0)
            for rid_counts in count_regions:
                dbc = _queue_log_status_counts(rid_counts)
                tip = _LOCAL_STATUS_TOTALS.get(rid_counts)
                lib = _region_library_progress(rid_counts)
                total = int(lib.get("total") or 0)
                if tip:
                    done_n = int(tip.get("done") or 0)
                    soft_n = int(tip.get("soft") or 0)
                    fail_n = int(tip.get("fail") or 0)
                    tip_total = int(tip.get("total") or 0)
                    if tip_total > total:
                        total = tip_total
                    classified = done_n + soft_n + fail_n
                    pending_n = max(0, total - classified) if total > 0 else 0
                    run_n = (
                        run_n_global
                        if rid_counts
                        == _queue_log_region(str(status.get("currentRegion") or ""))
                        else 0
                    )
                    region_queue_counts[rid_counts] = {
                        "pending": pending_n,
                        "running": run_n,
                        "done": done_n,
                        "soft": soft_n,
                        "fail": fail_n,
                    }
                    complete = done_n + soft_n
                    incomplete = pending_n + run_n
                    library[rid_counts] = {
                        "total": total,
                        "incomplete": incomplete,
                        "complete": complete,
                        "percent": int(round(100.0 * complete / max(total, 1)))
                        if total > 0
                        else 0,
                    }
                else:
                    pending_n = int(dbc.get("pending") or 0)
                    run_n = int(dbc.get("running") or 0)
                    done_n = int(dbc.get("done") or 0)
                    soft_n = int(dbc.get("soft") or 0)
                    fail_n = int(dbc.get("fail") or 0)
                    if (
                        rid_counts
                        == _queue_log_region(str(status.get("currentRegion") or ""))
                        and status.get("running")
                    ):
                        run_n = run_n_global
                    region_queue_counts[rid_counts] = {
                        "pending": pending_n,
                        "running": run_n,
                        "done": done_n,
                        "soft": soft_n,
                        "fail": fail_n,
                    }
                    library[rid_counts] = {
                        "total": int(lib.get("total") or 0),
                        "incomplete": int(lib.get("incomplete") or 0),
                        "complete": int(lib.get("complete") or 0),
                        "percent": int(lib.get("percent") or 0),
                    }
            if library:
                status["library"] = library
            status["regionQueueCounts"] = region_queue_counts
            cur_rid2 = _queue_log_region(str(status.get("currentRegion") or ""))
            if cur_rid2 and cur_rid2 in region_queue_counts:
                status["queueCounts"] = dict(region_queue_counts[cur_rid2])
                status["queueCountsRegion"] = cur_rid2
            elif len(region_queue_counts) == 1:
                only_rid = next(iter(region_queue_counts))
                status["queueCounts"] = dict(region_queue_counts[only_rid])
                status["queueCountsRegion"] = only_rid
            status["queueTotal"] = sum(
                int(status.get("queueCounts", {}).get(k) or 0)
                for k in ("pending", "running", "done", "soft", "fail")
            )
            status["progress"] = _progress_from_queue_counts(
                dict(status.get("queueCounts") or {}),
                base=dict(status.get("progress") or {}),
            )

    # 元库回填：仅空闲时合并历史；运行中只用本轮内存，避免角标被历史顶满
    try:
        from app.core.region_meta import REGION_ORDER

        if not status.get("running"):
            want_regions = set(region_logs.keys()) | set(REGION_ORDER)
            if current_region:
                want_regions.add(current_region)
            for rid in want_regions:
                key = _canonical_enrich_log_region(str(rid or "").strip())
                if not key or key == "_all":
                    continue
                loaded = _load_enrich_logs_cached(region=key, limit=_ENRICH_LOG_RETURN)
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
                loaded_all = _load_enrich_logs_cached(region="_all", limit=80)
                if loaded_all:
                    status["log"] = loaded_all[-40:]
        status["regionLogs"] = region_logs
        status["regionLogCounts"] = region_log_counts
    except Exception:  # noqa: BLE001
        pass
    if lite:
        mon = status.get("monitor")
        if isinstance(mon, dict):
            status["monitor"] = {
                "enabled": mon.get("enabled"),
                "itemWorkers": mon.get("itemWorkers"),
                "perSourceTimeoutSec": mon.get("perSourceTimeoutSec"),
                "region": mon.get("region"),
                "summary": mon.get("summary"),
                "inflight": [
                    {
                        "code": x.get("code"),
                        "phase": x.get("phase"),
                        "elapsedMs": x.get("elapsedMs"),
                        "phaseElapsedMs": x.get("phaseElapsedMs"),
                        "stall": x.get("stall"),
                    }
                    for x in list(mon.get("inflight") or [])
                    if isinstance(x, dict)
                ],
                "recentStalls": [],
            }
        status["queue"] = []
        status["current"] = None
        status["queueScan"] = None
        status["regionLogs"] = {}
        status["lite"] = True
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
    notify_enrich_watchers(force=True)


def _queue_row_match_index(
    queue: list[Any],
    *,
    index: int = -1,
    match: dict[str, Any] | None = None,
) -> int:
    """定位内存队列行：边扫截断后 worker 下标会错位，必须按 logId/itemId/code 对齐。"""
    m = match if isinstance(match, dict) else {}
    lid = _queue_log_int_id(m)
    iid = str(m.get("itemId") or m.get("item_id") or "").strip()
    code_u = str(m.get("code") or "").strip().upper()

    def _at(i: int) -> dict[str, Any] | None:
        if 0 <= i < len(queue) and isinstance(queue[i], dict):
            return queue[i]
        return None

    if lid > 0:
        for i, r in enumerate(queue):
            if isinstance(r, dict) and _queue_log_int_id(r) == lid:
                return i
    if iid:
        for i, r in enumerate(queue):
            if isinstance(r, dict) and str(r.get("itemId") or "").strip() == iid:
                return i
    if code_u:
        # 优先命中处理中/未处理，避免改到已完成的同番号旧行
        prefer = ("running", "pending", "fail", "done")
        best_i, best_rank = -1, 99
        for i, r in enumerate(queue):
            if not isinstance(r, dict):
                continue
            if str(r.get("code") or "").strip().upper() != code_u:
                continue
            st = str(r.get("status") or "pending").strip().lower()
            try:
                rank = prefer.index(st)
            except ValueError:
                rank = 50
            if rank < best_rank:
                best_i, best_rank = i, rank
        if best_i >= 0:
            return best_i
    # 下标仅作兜底：且必须番号一致，防止截断队列串写
    hit = _at(index)
    if hit is not None:
        if not code_u or str(hit.get("code") or "").strip().upper() == code_u:
            return index
    return -1


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
            # 截断后内存里可能已没有该行：仍用 match 身份落库，避免丢终态
            if isinstance(match, dict) and st_in in {"done", "fail", "pending"}:
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
            if lid and not _queue_log_int_id(updated) and resolved_i >= 0:
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


def _detail_field_rows(detail: dict[str, Any] | None) -> list[dict[str, Any]]:
    """E2E 风格字段表：是否采到 + 预览值 + 最终选用源。"""
    d = detail if isinstance(detail, dict) else {}
    fs = d.get("fieldSources") if isinstance(d.get("fieldSources"), dict) else {}
    actors = [str(a).strip() for a in (d.get("actors") or []) if str(a).strip()]
    tags = [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()]
    title = str(d.get("title") or "").strip()
    studio = str(d.get("studio") or d.get("maker") or "").strip()
    overview = str(d.get("overview") or "").strip()
    poster = str(d.get("posterUrl") or d.get("poster") or "").strip()
    year = str(d.get("year") or "").strip()
    date_s = str(d.get("date") or "").strip()
    code = str(d.get("code") or d.get("id") or "").strip().upper()

    def src_of(*keys: str) -> str:
        for k in keys:
            v = str(fs.get(k) or "").strip()
            if v:
                return v
        return ""

    def row(
        fid: str,
        label: str,
        ok: bool,
        value: str = "",
        *,
        source: str = "",
    ) -> dict[str, Any]:
        return {
            "id": fid,
            "label": label,
            "ok": bool(ok),
            "value": (value or "")[:120],
            "source": str(source or "").strip(),
        }

    return [
        row("code", "番号", bool(code), code),
        row(
            "title",
            "标题",
            bool(title) and title.casefold() != code.casefold(),
            title,
            source=src_of("title"),
        ),
        row(
            "poster",
            "封面",
            poster.startswith(("http://", "https://")),
            poster if poster.startswith(("http://", "https://")) else (poster or ""),
            source=src_of("poster"),
        ),
        row(
            "actors",
            "女优",
            bool(actors),
            "、".join(actors[:6]),
            source=src_of("actors"),
        ),
        row(
            "studio",
            "片商",
            bool(studio),
            studio,
            source=src_of("studio", "maker"),
        ),
        row(
            "overview",
            "剧情",
            len(overview) >= 12,
            overview[:80],
            source=src_of("overview"),
        ),
        row("year", "年份", bool(year), year, source=src_of("year")),
        row("date", "日期", bool(date_s), date_s, source=src_of("date")),
        row(
            "tags",
            "标签",
            bool(tags),
            "、".join(tags[:8]),
            source=src_of("tags"),
        ),
    ]


def _fields_after_local_write(
    folder: Path,
    detail: dict[str, Any] | None,
    *,
    local_cover_ok: bool,
    poster_url: str = "",
) -> list[dict[str, Any]]:
    """写回后按本地 NFO 刷新字段表，避免早停没采到剧情却误报「缺剧情」。"""
    d = dict(detail) if isinstance(detail, dict) else {}
    nfo = _find_nfo(folder)
    meta = parse_nfo(nfo) if nfo else None
    if isinstance(meta, dict) and meta:
        plot = str(meta.get("plot") or meta.get("overview") or "").strip()
        title = str(meta.get("title") or "").strip()
        studio = str(meta.get("studio") or meta.get("maker") or "").strip()
        actors = [
            str(a).strip()
            for a in (meta.get("actors") or [])
            if str(a or "").strip()
        ]
        tags = [
            str(t).strip()
            for t in (meta.get("genres") or meta.get("tags") or [])
            if str(t or "").strip()
        ]
        cover = str(meta.get("cover_url") or meta.get("cover") or "").strip()
        year = str(meta.get("year") or "").strip()
        date_s = str(
            meta.get("premiered")
            or meta.get("releasedate")
            or meta.get("date")
            or ""
        ).strip()
        code_u = str(meta.get("num") or d.get("code") or folder.name).strip().upper()
        if plot:
            d["overview"] = plot
        if title:
            d["title"] = title
        if studio:
            d["studio"] = studio
        if actors:
            d["actors"] = actors
        if tags:
            d["tags"] = tags
        if cover:
            d["posterUrl"] = cover
        if year:
            d["year"] = year
        if date_s:
            d["date"] = date_s
        if code_u:
            d["code"] = code_u

    fields = _detail_field_rows(d)
    fs = d.get("fieldSources") if isinstance(d.get("fieldSources"), dict) else {}
    poster_src = str((fs or {}).get("poster") or "").strip()
    for f in fields:
        fid = str(f.get("id") or "")
        if fid != "poster":
            if not str(f.get("source") or "").strip():
                alt = "maker" if fid == "studio" else fid
                src = str((fs or {}).get(fid) or (fs or {}).get(alt) or "").strip()
                if src:
                    f["source"] = src
            continue
        if poster_src and not str(f.get("source") or "").strip():
            f["source"] = poster_src
        if local_cover_ok:
            f["ok"] = True
            f["value"] = "已落盘"
        else:
            f["ok"] = False
            remote = str(f.get("value") or poster_url or "").strip()
            f["value"] = (
                f"空图/未落盘 · {remote[:80]}" if remote else "无封面"
            )
    return fields


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


def _cover_fail_message(cover_fail: str) -> str:
    cf = str(cover_fail or "").strip()
    if not cf:
        return "封面空图或下载失败"
    return f"封面失败:{_COVER_FAIL_LABEL.get(cf, cf)}"

# 硬失败：只缺封面 / 标题空壳（以本地 NFO+poster 为准）
_SUCCESS_BLOCK_GAPS = frozenset({"no_local", "thin_title"})
# 软成功：缺女优 / 片商（封面+非空标题已齐；中文标题不再挡成功）
_SOFT_SUCCESS_GAPS = frozenset({"no_actress", "no_studio"})
_SOFT_GAP_LABELS = frozenset(
    {_GAP_FAIL_LABEL[g] for g in _SOFT_SUCCESS_GAPS if g in _GAP_FAIL_LABEL}
)
# 文案前缀：新写「软成功」；读侧兼容旧「次成功」
_SOFT_OK_PREFIX = "软成功"
_SOFT_OK_PREFIXES = ("软成功", "次成功")
# 软规则版本：去掉「中文标题」软成功后强制再跑一轮纠偏
_SOFT_PROMOTE_RULE_VER = 5

_promoted_actress_soft: dict[str, int] = {}
_demoted_false_dones: set[str] = set()

# ⚠️ 性能：`_ensure_actress_soft_promoted` / demote 会对 done/fail 行做磁盘校验
# （有码区 10 万+ × ~11ms）。只允许挂在「扫描 / 开刮」入口，禁止状态读/日志列表。
_soft_correction_last: dict[str, float] = {}
_SOFT_CORRECTION_MIN_INTERVAL_SEC = 6.0


def _gap_labels(gaps: list[str]) -> list[str]:
    return [_GAP_FAIL_LABEL.get(g, g) for g in gaps]


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


def _empty_queue_counts() -> dict[str, int]:
    return {"pending": 0, "running": 0, "done": 0, "soft": 0, "fail": 0}


def _soft_done_sql_pred(*, error_col: str = "error") -> str:
    """SQL：done 行是否软成功（兼容旧「次成功」前缀）。

    psycopg 要求字面量 ``%`` 写成 ``%%``，否则 LIKE '软成功%' 会报
    placeholders 错误，导致整页队列读失败、列表空白。
    """
    return (
        f"({error_col} LIKE '软成功%%' OR {error_col} LIKE '次成功%%')"
    )


def _is_soft_remain_error(err: str) -> bool:
    """error 是否仅为软缺口「仍缺:…」（可带软成功/次成功前缀；不含封面/标题）。"""
    s = _strip_soft_ok_prefix(err)
    if not s.startswith("仍缺:"):
        return False
    rest = s[len("仍缺:") :].strip()
    parts = [p.strip() for p in re.split(r"[·,，]", rest) if p.strip()]
    return bool(parts) and all(p in _SOFT_GAP_LABELS for p in parts)


def _soft_gaps_from_remain_error(err: str) -> list[str]:
    """从仍缺文案反推 soft gap ids。"""
    s = _strip_soft_ok_prefix(err)
    if not s.startswith("仍缺:"):
        return []
    rest = s[len("仍缺:") :].strip()
    parts = [p.strip() for p in re.split(r"[·,，]", rest) if p.strip()]
    rev = {v: k for k, v in _GAP_FAIL_LABEL.items()}
    out: list[str] = []
    for p in parts:
        gid = rev.get(p)
        if gid and gid in _SOFT_SUCCESS_GAPS and gid not in out:
            out.append(gid)
    return out


# ── 有界重试 / 源故障降级（2026-09-16） ────────────────────────────────────
# 两个此前被静默吞掉的问题：
# ① **封面永久失败的番号没有重试上限**。NFO 已写好、只差海报时本地缺口恒为
#    no_local，于是每轮增量都重新入队、把全部源再抓一遍（纯网络浪费，且永不清空）。
# ② **「源挂了」与「源没有这条番号」没区分**。两者此前都只落进 `errors` 字符串，
#    于是高优先源瞬时抖动会静默退化为低优先源的值，而且不会再补抓。
# 方案：统一用队列表 `enrich_retry_hint` 记录「本该更好但没拿到」的番号（**有界**）。
# 达到上限 → giveup=True，增量扫描不再自动入队；用户可用「覆盖模式重扫」或
# 单号重刮解除。**不要**把这套逻辑塞进状态/通知路径（见 MEMORY 性能约定）。
_RETRY_KIND_COVER = "cover"
_RETRY_KIND_SRC_DOWN = "src_down"
# 只有「封面型缺口」才允许放弃封面重试；同时缺剧情/女优的仍要重试（别把元数据一起放弃）
_COVER_ONLY_GAPS = frozenset({"no_local", "no_media"})
_COVER_RETRY_MAX = 3
_SRC_DOWN_RETRY_MAX = 2
_RETRY_HINT_CACHE_TTL = 20.0
# (region, kind) → (ts, rows)
_retry_hint_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = {}
# (region, kind) → 当前进程已知「库里有行」的番号集合。
# 用途：成功时清零必须先判断「有没有可能真的存在行」，否则每条成功番号都要
# 发一次 DELETE —— 那是 12 万次写库，绝对不能上热路径。
_retry_hint_known: dict[tuple[str, str], set[str]] = {}
# 已经用 DB 灌过 known 的 (region, kind)。首次清零前会做一次预热，
# 否则「单号重刮」这类不走队列构建的路径会漏掉清零。
_retry_hint_primed: set[tuple[str, str]] = set()


def _retry_next_state(attempts: int, *, cap: int) -> tuple[int, bool]:
    """纯函数：累计一次失败后的 (新次数, 是否已放弃)。便于单测锁语义。"""
    n = max(0, int(attempts or 0)) + 1
    return n, n >= int(cap)


def _is_cover_only_gaps(gaps: Any) -> bool:
    """剩余缺口是否「只有封面」（no_local=无合格海报 / no_media=无 cover_url）。"""
    g = {str(x).strip() for x in (gaps or []) if str(x).strip()}
    return bool(g) and g <= _COVER_ONLY_GAPS


# 单源「放弃」轮询步长（秒）：以**工作耗时**（墙钟 − 等出站槽）判定真超时，
# 而不是 `th.join(单源超时)` —— 后者把排队算进源超时（mgstage 433 次假 down）。
_SRC_GIVEUP_POLL_SEC = 0.25

# 源连续 down 冷却：跑久后某站集体超时会占满 page 槽，拖垮其它番号。
# 连续失败达阈值 → 跳过该源一段时间，让活源先跑。
_SOURCE_DOWN_STREAK: dict[str, int] = {}
_SOURCE_COOLDOWN_UNTIL: dict[str, float] = {}
_SOURCE_COOLDOWN_STREAK = 3
_SOURCE_COOLDOWN_SEC = 50.0
_SOURCE_COOLDOWN_LOCK = threading.Lock()


def _source_in_cooldown(sid: str) -> bool:
    key = str(sid or "").strip().lower()
    if not key:
        return False
    with _SOURCE_COOLDOWN_LOCK:
        until = float(_SOURCE_COOLDOWN_UNTIL.get(key) or 0.0)
    return time.monotonic() < until


def _note_source_fetch_outcome(sid: str, *, kind: str) -> None:
    key = str(sid or "").strip().lower()
    if not key:
        return
    with _SOURCE_COOLDOWN_LOCK:
        if kind == "hit":
            _SOURCE_DOWN_STREAK[key] = 0
            _SOURCE_COOLDOWN_UNTIL.pop(key, None)
            return
        if kind != "down":
            return
        n = int(_SOURCE_DOWN_STREAK.get(key) or 0) + 1
        _SOURCE_DOWN_STREAK[key] = n
        if n >= int(_SOURCE_COOLDOWN_STREAK):
            _SOURCE_COOLDOWN_UNTIL[key] = time.monotonic() + float(
                _SOURCE_COOLDOWN_SEC
            )
            _SOURCE_DOWN_STREAK[key] = 0
            log.info(
                "enrich source cooldown sid=%s for %.0fs (down streak)",
                key,
                _SOURCE_COOLDOWN_SEC,
            )


def _src_give_up_reason(
    *,
    elapsed: float,
    waited: float,
    work_budget: float,
    queue_budget: float,
) -> str:
    """单源放弃判定（纯函数，便于单测锁语义）。返回 ""/「down」/「busy」。

    - 工作耗时 = `elapsed - waited`（墙钟 − 等出站槽/限速/退避）
    - 工作耗时 ≥ 工作预算 → `down`：源真的慢/挂
    - 墙钟 ≥ 工作预算 + 排队预算 → `busy`：一直没轮到发请求，**不是源故障**

    顺序有意义：先判 down 再判 busy —— 若两者都超，说明「确实干活干太久」。
    """
    if elapsed - waited >= work_budget:
        return "down"
    if elapsed >= work_budget + queue_budget:
        return "busy"
    return ""


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


# 源「正常响应但没有这条番号」的特征；其余一律按「源不可用」处理（保守：可重试）
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


def _classify_source_failure(err: Any) -> str:
    """源失败四分类：miss（源没这条番号）/ down（源不可用）/ busy（排队未及）/ cancelled（主动放弃）。

    只有 down / busy 才值得补抓；miss 说明源侧确实没有，重抓只是浪费出站槽。
    ⚠️ busy 的语义是「**我们这边**没轮到发请求」（出站槽/限速/退避/过盾通道排满），
    源本身是好的 —— 所以它**不得**计入任何源健康度/退避逻辑，
    但仍要进 `degradedByDown`（高优先源没拿到 = 本轮降级取值，该回头补）。

    另有第五类 **cooldown**（源不健康被主动暂避），**不经过本函数**：
    它在 `_one` 的冷却早退分支上直接产出，由 `_run_pool` 单独归集。
    别把 cooldown 折进 busy —— 那是源健康度结论，busy 不是（见 `_one` 注释）。
    """
    name = err.__class__.__name__ if isinstance(err, BaseException) else ""
    # 类名优先，其次消息标记：中间层可能把异常包成 RuntimeError(str(e)) 丢掉类名
    if name == "OutboundCancelled":
        return "cancelled"
    if name == "OutboundBusy":
        return "busy"
    if isinstance(err, BaseException):
        sc = getattr(err, "status_code", None)
        if isinstance(sc, int):
            if sc in (404, 410):
                return "miss"
            if sc == 429 or sc >= 500:
                return "down"
        s = str(err)
    else:
        s = str(err or "")
    low = s.lower()
    # 排队未及：必须在 "timeout" 之前判 —— OutboundBusy 是 TimeoutError 子类，
    # 消息里也带 timeout，否则会被归成 down。
    if "outbound busy" in low or "排队未及" in s:
        return "busy"
    # 过盾通道排满（curl 直连失败后无 flare 名额）同样是「没轮到」，不是过盾站坏了
    if "繁忙" in s:
        return "busy"
    if "cancel" in low or "取消" in s:
        return "cancelled"
    if "timeout" in low or "timed out" in low or "超时" in s:
        return "down"
    if low.startswith("rejected"):
        # 源页面拿到了但判为不可用（多为别的番号的占位页）→ 源侧没有这条
        return "miss"
    for hint in _MISS_HINTS:
        if hint in s or hint in low:
            return "miss"
    return "down"


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


def _safe_local_gaps(folder: Path) -> list[str]:
    """`_local_folder_gaps` 的安全包装（失败时按空处理，不打断流程）。"""
    try:
        _, gaps = _local_folder_gaps(folder)
        return list(gaps or [])
    except Exception:  # noqa: BLE001
        return []


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
        "gaps": list(_ENRICH_KINDS),
        "rel_path": rel or iid,
        "relPath": rel or iid,
        "region": region,
        "status": "pending",
        "retryKind": _RETRY_KIND_SRC_DOWN,
        # 允许覆盖写回：否则之前被低优先源写死的字段不会被修好
        "overwrite": True,
    }


def _retry_hint_load(region: str, kind: str) -> list[dict[str, Any]]:
    """读某分区某类重试提示（TTL 缓存）。顺带把已知番号灌进 `_retry_hint_known`。

    缓存必须由这里灌 `known` —— 否则进程重启后「成功清零」会因 known 为空而跳过 DELETE，
    提示行会永远留在库里、每轮被重新入队。
    """
    rid = _queue_log_region(region) or region
    key = (rid, str(kind or ""))
    now = time.time()
    hit = _retry_hint_cache.get(key)
    if hit and now - hit[0] < _RETRY_HINT_CACHE_TTL:
        _retry_hint_primed.add(key)
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
    _retry_hint_cache[key] = (now, rows)
    _retry_hint_known.setdefault(key, set()).update(known)
    _retry_hint_primed.add(key)
    return rows


def _retry_hint_invalidate(region: str, kind: str) -> None:
    rid = _queue_log_region(region) or region
    _retry_hint_cache.pop((rid, str(kind or "")), None)


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


def _retry_hint_clear_region(region: str, kind: str | None = None) -> int:
    """清掉某分区（或某类）重试提示 —— 覆盖模式重扫时调用，让用户能强制再来一轮。"""
    rid = _queue_log_region(region) or region
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
            _retry_hint_cache.pop((rid, str(k or "")), None)
            _retry_hint_known.pop((rid, str(k or "")), None)
            _retry_hint_primed.discard((rid, str(k or "")))
        return n
    except Exception as e:  # noqa: BLE001
        log.debug("retry hint clear failed region=%s: %s", rid, e)
        return 0


def _retry_hint_clear_codes(
    region: str, codes: list[str] | set[str], *, kind: str | None = None
) -> int:
    """清掉指定番号的重试放弃标记，让「失败重试」能真正再刮。"""
    rid = _queue_log_region(region) or region
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
            _retry_hint_cache.pop((rid, str(k or "")), None)
            known = _retry_hint_known.get((rid, str(k or "")))
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
            n, giveup = _retry_hint_note(
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
                _push_log(
                    f"{code_u} · 封面连续失败 {n} 次 · 已停止自动重试"
                    "（可用覆盖模式重扫或单号重刮解除）",
                    region=region,
                )
        else:
            _retry_hint_note(
                region=region,
                code=code_u,
                kind=_RETRY_KIND_COVER,
                need=False,
                cap=_COVER_RETRY_MAX,
            )
    else:
        _retry_hint_note(
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
        n, giveup = _retry_hint_note(
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
            _push_log(
                f"{code_u} · 高优先源连续 {n} 轮不可用 · 已停止自动补抓"
                "（源恢复后可用覆盖模式重扫）",
                region=region,
            )
    else:
        _retry_hint_note(
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
    """本地 NFO 缺口收口：缺封面/空标题→失败；缺女优/片商→软成功；其余→成功。"""
    # 无目录/无封面/无 NFO 绝不能算成功（防并发串写把别人的软成功盖到空壳番号）
    if not _local_success_disk_ok(folder):
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
        elif not _find_nfo(folder):
            out["gapsAfter"] = ["thin_title", "no_plot"]
            out["error"] = "仍缺:标题 · 无 NFO"
        else:
            out["gapsAfter"] = ["no_local"]
            out["error"] = "仍缺:封面"
        _push_log(
            f"{code or folder.name} · 未算成功 · {out['error']}",
            region=region,
        )
        return
    if remain is None:
        try:
            _, remain = _local_folder_gaps(folder)
        except Exception:  # noqa: BLE001
            remain = []
    remain = list(remain or [])
    block = [g for g in remain if g in _SUCCESS_BLOCK_GAPS]
    soft = [g for g in remain if g in _SOFT_SUCCESS_GAPS]
    if block:
        if only_if_ok and not out.get("ok"):
            return
        labels = _gap_labels(block)
        out["ok"] = False
        out["partialOk"] = False
        out["gapsAfter"] = remain
        out["error"] = f"仍缺:{' · '.join(labels)}"
        _push_log(
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
        _push_log(
            f"{code or folder.name} · {out['error']}",
            region=region,
        )
        return
    # 硬缺口已清：必须显式 ok=True（调用方初始 ok=False，否则会被当成失败提前 return）
    # 缺剧情/外链等不算软成功 → 完整成功
    if only_if_ok and not out.get("ok"):
        return
    out["ok"] = True
    out["partialOk"] = False
    out["error"] = ""
    out["gapsAfter"] = []
    out["localCoverOk"] = True


def _payload_field_code(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    fields = payload.get("fields")
    if not isinstance(fields, list):
        return ""
    for f in fields:
        if not isinstance(f, dict):
            continue
        if str(f.get("id") or "") != "code":
            continue
        return str(f.get("value") or "").strip().upper()
    return ""


def _queue_log_demote_false_dones(region: str) -> int:
    """成功/软成功/失败但无本地目录或字段番号串号 → 退回 pending 重刮。

    磁盘校验在连接外做：持连接扫 10 万行会锁死其它状态接口。
    """
    rid = _queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT id, code, item_id, error, gaps_json, payload_json, status
                    FROM enrich_queue_log
                    WHERE region=? AND status IN ('done', 'fail')
                    """,
                    (rid,),
                ).fetchall()
                or []
            )
        # 连接已释放；下面只做磁盘判定
        updates: list[tuple[str, str, str, int]] = []
        for raw in rows:
            if isinstance(raw, dict):
                lid = int(raw.get("id") or 0)
                code = str(raw.get("code") or "").strip().upper()
                iid = str(raw.get("item_id") or "").strip()
                payload_raw = raw.get("payload_json")
                st = str(raw.get("status") or "").strip().lower()
            else:
                lid = int(raw[0] or 0)
                code = str(raw[1] or "").strip().upper()
                iid = str(raw[2] or "").strip()
                payload_raw = raw[5]
                st = str(raw[6] if len(raw) > 6 else "").strip().lower()
            if lid <= 0:
                continue
            try:
                payload = (
                    json.loads(payload_raw)
                    if isinstance(payload_raw, str)
                    else (payload_raw if isinstance(payload_raw, dict) else {})
                )
            except Exception:  # noqa: BLE001
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            field_code = _payload_field_code(payload)
            code_mismatch = bool(field_code and code and field_code != code)
            folder = _resolve_enrich_folder(
                region=rid, code=code, item_id=iid
            )
            missing_disk = folder is None or not _local_poster_ok(folder)
            # fail：仅本地已删才回 pending（仍缺封面的 fail 保持失败）
            if st == "fail" and not missing_disk and not code_mismatch:
                continue
            if not code_mismatch and not missing_disk:
                continue
            reason = (
                f"串号回滚:{field_code}"
                if code_mismatch
                else "仍缺:封面 · 无本地目录"
            )
            gaps = [
                "no_local",
                "no_media",
                "no_actress",
                "no_studio",
                "no_plot",
                "thin_title",
            ]
            if folder is not None and folder.is_dir():
                try:
                    _, gaps = _local_folder_gaps(folder)
                except Exception:  # noqa: BLE001
                    gaps = ["no_local"]
            payload["partialOk"] = False
            payload["gapsAfter"] = gaps
            payload.pop("ok", None)
            updates.append(
                (
                    reason[:500],
                    json.dumps(gaps, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    lid,
                )
            )
        if not updates:
            return 0
        n = 0
        with connect() as conn:
            for i in range(0, len(updates), 200):
                chunk = updates[i : i + 200]
                for params in chunk:
                    conn.execute(
                        """
                        UPDATE enrich_queue_log
                        SET status='pending', error=?, gaps_json=?, payload_json=?,
                            updated_at=NOW()
                        WHERE id=? AND status IN ('done', 'fail')
                        """,
                        params,
                    )
                    n += 1
                conn.commit()
        return n
    except Exception as e:  # noqa: BLE001
        log.warning("demote false enrich dones failed region=%s: %s", rid, e)
        return 0


def _queue_log_demote_false_dones_budgeted(
    region: str, *, time_budget_sec: float = 8.0
) -> int:
    """后台有限预算 demote：不挡开刮；扫完或超时即停。"""
    rid = _queue_log_region(region)
    if not rid:
        return 0
    # 标记已调度，避免同一进程反复开线程；未扫完也不再强制全量挡启动
    if rid in _demoted_false_dones:
        return 0
    _demoted_false_dones.add(rid)
    t0 = time.monotonic()
    budget = max(1.0, float(time_budget_sec or 8.0))
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT id, code, item_id, error, gaps_json, payload_json, status
                    FROM enrich_queue_log
                    WHERE region=? AND status IN ('done', 'fail')
                    ORDER BY updated_at ASC NULLS FIRST, id ASC
                    LIMIT 4000
                    """,
                    (rid,),
                ).fetchall()
                or []
            )
        updates: list[tuple[str, str, str, int]] = []
        for raw in rows:
            if (time.monotonic() - t0) >= budget:
                break
            if isinstance(raw, dict):
                lid = int(raw.get("id") or 0)
                code = str(raw.get("code") or "").strip().upper()
                iid = str(raw.get("item_id") or "").strip()
                payload_raw = raw.get("payload_json")
                st = str(raw.get("status") or "").strip().lower()
            else:
                lid = int(raw[0] or 0)
                code = str(raw[1] or "").strip().upper()
                iid = str(raw[2] or "").strip()
                payload_raw = raw[5]
                st = str(raw[6] if len(raw) > 6 else "").strip().lower()
            if lid <= 0:
                continue
            try:
                payload = (
                    json.loads(payload_raw)
                    if isinstance(payload_raw, str)
                    else (payload_raw if isinstance(payload_raw, dict) else {})
                )
            except Exception:  # noqa: BLE001
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            field_code = _payload_field_code(payload)
            code_mismatch = bool(field_code and code and field_code != code)
            folder = _resolve_enrich_folder(region=rid, code=code, item_id=iid)
            missing_disk = folder is None or not _local_poster_ok(folder)
            if st == "fail" and not missing_disk and not code_mismatch:
                continue
            if not code_mismatch and not missing_disk:
                continue
            reason = (
                f"串号回滚:{field_code}"
                if code_mismatch
                else "仍缺:封面 · 无本地目录"
            )
            gaps = [
                "no_local",
                "no_media",
                "no_actress",
                "no_studio",
                "no_plot",
                "thin_title",
            ]
            if folder is not None and folder.is_dir():
                try:
                    _, gaps = _local_folder_gaps(folder)
                except Exception:  # noqa: BLE001
                    gaps = ["no_local"]
            payload["partialOk"] = False
            payload["gapsAfter"] = gaps
            payload.pop("ok", None)
            updates.append(
                (
                    reason[:500],
                    json.dumps(gaps, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    lid,
                )
            )
        if not updates:
            return 0
        n = 0
        with connect() as conn:
            for i in range(0, len(updates), 200):
                chunk = updates[i : i + 200]
                for params in chunk:
                    conn.execute(
                        """
                        UPDATE enrich_queue_log
                        SET status='pending', error=?, gaps_json=?, payload_json=?,
                            updated_at=NOW()
                        WHERE id=? AND status IN ('done', 'fail')
                        """,
                        params,
                    )
                    n += 1
                conn.commit()
        if n:
            log.info(
                "budget demote region=%s n=%s spent=%.1fs",
                rid,
                n,
                time.monotonic() - t0,
            )
        return n
    except Exception as e:  # noqa: BLE001
        log.warning("budget demote failed region=%s: %s", rid, e)
        return 0


def _queue_log_promote_actress_soft_fails(region: str) -> int:
    """历史软缺口失败（不缺封面/标题）→ 软成功（done）。须本地封面已落盘。"""
    rid = _queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT id, code, item_id, error, gaps_json, payload_json
                FROM enrich_queue_log
                WHERE region=? AND status='fail'
                """,
                (rid,),
            ).fetchall()
            ids: list[int] = []
            for raw in rows or []:
                if isinstance(raw, dict):
                    lid = int(raw.get("id") or 0)
                    code = str(raw.get("code") or "").strip().upper()
                    iid = str(raw.get("item_id") or "").strip()
                    err = str(raw.get("error") or "")
                    gaps_raw = raw.get("gaps_json")
                    payload_raw = raw.get("payload_json")
                else:
                    lid = int(raw[0] or 0)
                    code = str(raw[1] or "").strip().upper()
                    iid = str(raw[2] or "").strip()
                    err = str(raw[3] or "")
                    gaps_raw = raw[4]
                    payload_raw = raw[5]
                if lid <= 0:
                    continue
                # 文案已是软缺口，或 gaps_json 不含硬缺口
                gaps_hint: list[str] = []
                try:
                    parsed = (
                        json.loads(gaps_raw)
                        if isinstance(gaps_raw, str)
                        else (gaps_raw if isinstance(gaps_raw, list) else [])
                    )
                    if isinstance(parsed, list):
                        gaps_hint = [str(g) for g in parsed if str(g).strip()]
                except Exception:  # noqa: BLE001
                    gaps_hint = []
                soft_by_err = _is_soft_remain_error(err)
                soft_hint = [g for g in gaps_hint if g in _SOFT_SUCCESS_GAPS]
                # 仅女优/片商软缺口，或「无硬缺口」的历史 fail（可能升完整成功）
                soft_by_gaps = bool(soft_hint) or (
                    bool(gaps_hint)
                    and not any(g in _SUCCESS_BLOCK_GAPS for g in gaps_hint)
                )
                if not soft_by_err and not soft_by_gaps:
                    continue
                folder = _resolve_enrich_folder(
                    region=rid, code=code, item_id=iid
                )
                if folder is None or not _local_poster_ok(folder):
                    continue
                # 再以磁盘为准，避免文案软缺口但实际仍缺硬字段
                try:
                    _, disk_gaps = _local_folder_gaps(folder)
                except Exception:  # noqa: BLE001
                    continue
                if any(g in _SUCCESS_BLOCK_GAPS for g in disk_gaps):
                    continue
                soft_only = [
                    g for g in disk_gaps if g in _SOFT_SUCCESS_GAPS
                ]
                ids.append(lid)
                # 磁盘无女优/片商缺口 → 完整成功（剧情/外链不算软成功）
                soft_gaps = (
                    soft_only
                    or _soft_gaps_from_remain_error(err)
                    or soft_hint
                )
                try:
                    payload = (
                        json.loads(payload_raw)
                        if isinstance(payload_raw, str)
                        else (payload_raw if isinstance(payload_raw, dict) else {})
                    )
                except Exception:  # noqa: BLE001
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                if soft_gaps:
                    payload["partialOk"] = True
                    payload["gapsAfter"] = soft_gaps
                    labels = _gap_labels(soft_gaps)
                    new_err = _format_soft_ok_error(labels)
                    gaps_js = json.dumps(soft_gaps, ensure_ascii=False)
                else:
                    payload["partialOk"] = False
                    payload["gapsAfter"] = []
                    new_err = ""
                    gaps_js = "[]"
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET status='done', error=?, gaps_json=?, payload_json=?,
                        updated_at=NOW()
                    WHERE id=? AND status='fail'
                    """,
                    (
                        new_err[:500],
                        gaps_js,
                        json.dumps(payload, ensure_ascii=False, default=str),
                        lid,
                    ),
                )
            if ids:
                conn.commit()
            return len(ids)
    except Exception as e:  # noqa: BLE001
        log.warning(
            "promote actress soft fails failed region=%s: %s", rid, e
        )
        return 0


def _queue_log_normalize_soft_to_full_success(region: str) -> int:
    """旧规则把「缺剧情/外链」也标成软成功 → 升为完整成功。

    仅保留缺女优/片商为 soft；其余 done+partialOk 清掉 soft 标记。
    """
    rid = _queue_log_region(region)
    if not rid:
        return 0
    try:
        from app.core.db import connect, init_db

        init_db()
        with connect() as conn:
            soft_pred = _soft_done_sql_pred(error_col="error")
            rows = conn.execute(
                f"""
                SELECT id, error, gaps_json, payload_json
                FROM enrich_queue_log
                WHERE region=? AND status='done' AND {soft_pred}
                """,
                (rid,),
            ).fetchall()
            n = 0
            for raw in rows or []:
                if isinstance(raw, dict):
                    lid = int(raw.get("id") or 0)
                    err = str(raw.get("error") or "")
                    gaps_raw = raw.get("gaps_json")
                    payload_raw = raw.get("payload_json")
                else:
                    lid = int(raw[0] or 0)
                    err = str(raw[1] or "")
                    gaps_raw = raw[2]
                    payload_raw = raw[3]
                if lid <= 0:
                    continue
                try:
                    gaps = (
                        json.loads(gaps_raw)
                        if isinstance(gaps_raw, str)
                        else (gaps_raw if isinstance(gaps_raw, list) else [])
                    )
                except Exception:  # noqa: BLE001
                    gaps = []
                try:
                    payload = (
                        json.loads(payload_raw)
                        if isinstance(payload_raw, str)
                        else (payload_raw if isinstance(payload_raw, dict) else {})
                    )
                except Exception:  # noqa: BLE001
                    payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                after = list(payload.get("gapsAfter") or gaps or [])
                soft_gaps = [g for g in after if str(g) in _SOFT_SUCCESS_GAPS]
                # 仍缺女优/片商 → 保留软成功，只规范化文案/gaps
                if soft_gaps or _is_soft_remain_error(err):
                    if soft_gaps and (
                        list(payload.get("gapsAfter") or []) != soft_gaps
                        or not _is_soft_remain_error(err)
                    ):
                        payload["partialOk"] = True
                        payload["gapsAfter"] = soft_gaps
                        conn.execute(
                            """
                            UPDATE enrich_queue_log
                            SET error=?, gaps_json=?, payload_json=?, updated_at=NOW()
                            WHERE id=?
                            """,
                            (
                                _format_soft_ok_error(_gap_labels(soft_gaps)),
                                json.dumps(soft_gaps, ensure_ascii=False),
                                json.dumps(payload, ensure_ascii=False, default=str),
                                lid,
                            ),
                        )
                        n += 1
                    continue
                # 仅缺剧情/外链等 → 升完整成功
                payload["partialOk"] = False
                payload["gapsAfter"] = []
                conn.execute(
                    """
                    UPDATE enrich_queue_log
                    SET error='', gaps_json='[]', payload_json=?, updated_at=NOW()
                    WHERE id=?
                    """,
                    (
                        json.dumps(payload, ensure_ascii=False, default=str),
                        lid,
                    ),
                )
                n += 1
            if n:
                conn.commit()
            # 角标 tip 与库对齐（软成功降档必须立刻反映到 UI）
            try:
                dbc = _queue_log_status_counts_db(rid)
                tip_prev = (_LOCAL_STATUS_TOTALS.get(rid) or {}) if rid else {}
                _ensure_local_status_totals_loaded()
                _set_local_status_totals(
                    rid,
                    done=int(dbc.get("done") or 0),
                    soft=int(dbc.get("soft") or 0),
                    fail=int(dbc.get("fail") or 0),
                    total=int(tip_prev.get("total") or 0) or None,
                )
            except Exception:  # noqa: BLE001
                pass
            return n
    except Exception as e:  # noqa: BLE001
        log.warning(
            "normalize soft→full success failed region=%s: %s", rid, e
        )
        return 0


def _ensure_actress_soft_promoted(region: str, *, force: bool = False) -> int:
    """纠偏队列表：假成功回滚；软缺口失败升软成功；同步内存队列。

    按分区限频（首次 / 规则版本变更必须跑：DB 侧 demote/promote）。
    """
    rid = _queue_log_region(region)
    if not rid:
        return 0
    now = time.monotonic()
    first = (
        rid not in _demoted_false_dones
        or _promoted_actress_soft.get(rid) != _SOFT_PROMOTE_RULE_VER
    )
    if not force and not first:
        last = float(_soft_correction_last.get(rid) or 0.0)
        if (now - last) < _SOFT_CORRECTION_MIN_INTERVAL_SEC:
            return 0
    _soft_correction_last[rid] = now
    demoted = 0
    if rid not in _demoted_false_dones:
        demoted = _queue_log_demote_false_dones(rid)
        _demoted_false_dones.add(rid)
    n = 0
    if _promoted_actress_soft.get(rid) != _SOFT_PROMOTE_RULE_VER:
        n = _queue_log_promote_actress_soft_fails(rid)
        n += _queue_log_normalize_soft_to_full_success(rid)
        _promoted_actress_soft[rid] = _SOFT_PROMOTE_RULE_VER
    # 内存队列同步：假成功→pending；软缺口 fail→软成功（须本地封面）
    mem_n = 0
    with _enrich_lock:
        q = list(_enrich_job.get("queue") or [])
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
                    folder = _resolve_enrich_folder(
                        region=rid, code=code_u, item_id=iid
                    )
                if st == "done" and (
                    (field_code and code_u and field_code != code_u)
                    or folder is None
                    or not _local_poster_ok(folder)
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
                            g in _SUCCESS_BLOCK_GAPS
                            for g in (r.get("gapsAfter") or r.get("gaps") or [])
                        )
                    )
                ):
                    if folder is not None and _local_poster_ok(folder):
                        try:
                            _, disk_gaps = _local_folder_gaps(folder)
                        except Exception:  # noqa: BLE001
                            disk_gaps = []
                        if not any(g in _SUCCESS_BLOCK_GAPS for g in disk_gaps):
                            soft_only = [
                                g
                                for g in disk_gaps
                                if g in _SOFT_SUCCESS_GAPS
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
                    and _local_poster_ok(folder)
                ):
                    try:
                        _, disk_gaps = _local_folder_gaps(folder)
                    except Exception:  # noqa: BLE001
                        disk_gaps = []
                    if not any(g in _SUCCESS_BLOCK_GAPS for g in disk_gaps):
                        soft_only = [
                            g for g in disk_gaps if g in _SOFT_SUCCESS_GAPS
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
                _enrich_job["queue"] = new_q
                counts = dict(_enrich_job.get("queueCounts") or {})
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
                    _enrich_job["queueCounts"] = counts
                    prog = dict(_enrich_job.get("progress") or {})
                    prog["ok"] = int(counts.get("done") or 0) + int(
                        counts.get("soft") or 0
                    )
                    prog["failed"] = int(counts.get("fail") or 0)
                    _enrich_job["progress"] = prog
    if demoted:
        log.info(
            "demoted false enrich dones region=%s n=%s", rid, demoted
        )
    return demoted + n + mem_n


def _halt_kind() -> str | None:
    with _enrich_lock:
        halt = _enrich_job.get("halt")
        if halt in {"pause", "stop"}:
            return str(halt)
        if _enrich_job.get("cancel"):
            # 旧 cancel 视为暂停（保留进度）
            return "pause"
        return None


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


def current_strategy_epoch() -> int:
    with _strategy_epoch_mu:
        return int(_strategy_epoch)


def _note_strategy_hot_if_needed(region: str = "") -> None:
    """若策略刚保存过：本条起用新源，打一条日志（整轮只提示一次）。"""
    ep = current_strategy_epoch()
    if ep <= 0:
        return
    with _enrich_lock:
        applied = int(_enrich_job.get("strategyEpochApplied") or 0)
        if ep <= applied:
            return
        _enrich_job["strategyEpochApplied"] = ep
        running = bool(_enrich_job.get("running"))
    srcs = _detail_sources(region=region)
    ids = [str(s.get("id") or "").strip() for s in srcs if str(s.get("id") or "").strip()]
    label = " → ".join(ids[:14]) if ids else "(无启用源)"
    if len(ids) > 14:
        label += "…"
    tip = f"策略热更新 · 本条起用新数据源 · {label}"
    _push_log(tip, region=region or "")
    if running:
        try:
            notify_enrich_watchers(force=True)
        except Exception:  # noqa: BLE001
            pass


def apply_live_strategy(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """策略刚保存：暂停任务同步 fillMode；运行中 bump epoch，下一番号热切源。

    详情/封面/超时本就按 get_strategy 热读；此处负责提示 + 检查点 mode。
    """
    try:
        from app.scrap_library.enrich_strategy import get_strategy

        data = cfg if isinstance(cfg, dict) else get_strategy()
    except Exception:  # noqa: BLE001
        data = cfg if isinstance(cfg, dict) else {}
    mode_norm = _fill_mode_to_job_mode(str((data or {}).get("fillMode") or ""))
    ep = bump_strategy_epoch()
    mode_changed = False
    paused_like = False
    running = False
    regions: list[str] = []
    cur_region = ""
    with _enrich_lock:
        running = bool(_enrich_job.get("running"))
        cur_region = str(_enrich_job.get("currentRegion") or "").strip()
        prev_mode = str(_enrich_job.get("jobMode") or "")
        if prev_mode != mode_norm:
            _enrich_job["jobMode"] = mode_norm
            mode_changed = True
        # 强制下一番号重新打热更新日志
        _enrich_job["strategyEpochApplied"] = max(0, ep - 1)
        cps = dict(_enrich_job.get("checkpoints") or {})
        new_cps: dict[str, Any] = {}
        for rid, cp in cps.items():
            if not isinstance(cp, dict):
                continue
            row = dict(cp)
            if str(row.get("mode") or "") != mode_norm:
                row["mode"] = mode_norm
                mode_changed = True
            new_cps[str(rid)] = row
            regions.append(str(rid))
        if new_cps:
            _enrich_job["checkpoints"] = new_cps
        phase = str(_enrich_job.get("phase") or "")
        halt = _enrich_job.get("halt")
        paused_like = bool(new_cps) or phase == "paused" or halt == "pause"
        if paused_like:
            prog = dict(_enrich_job.get("progress") or {})
            prog["label"] = "已暂停 · 新策略已生效"
            _enrich_job["progress"] = prog
            if phase == "paused" or halt == "pause":
                _enrich_job["phase"] = "paused"
        elif running:
            prog = dict(_enrich_job.get("progress") or {})
            if prog:
                prog["label"] = str(prog.get("label") or "补齐中") + " · 策略已更新"
                _enrich_job["progress"] = prog
    if mode_changed:
        try:
            _persist_enrich_runtime()
        except Exception:  # noqa: BLE001
            pass
    # 无论 mode 是否变（可能只改了数据源），都提示
    if running:
        tip = f"策略已热更新 #{ep} · 下一番号起用新数据源/超时（{mode_norm}）"
        _push_log(tip, region=cur_region or (regions[0] if regions else ""))
    elif paused_like:
        tip = f"策略已更新 · 续跑用最新配置（{mode_norm}）"
        if regions:
            for rid in regions[:8]:
                _push_log(tip, region=rid)
        else:
            _push_log(tip)
    else:
        _push_log(f"策略已保存（{mode_norm}）")
    try:
        notify_enrich_watchers(force=True)
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "applied": True,
        "epoch": ep,
        "mode": mode_norm,
        "paused": paused_like,
        "running": running,
    }


def _is_cancelled() -> bool:
    """兼容旧名：收到 pause/stop 都视为应中断循环。"""
    return _halt_kind() is not None


def _save_checkpoint(region: str, payload: dict[str, Any]) -> None:
    rid = str(region or "").strip()
    if not rid:
        return
    row = dict(payload or {})
    queue_list = [
        dict(r) for r in list(row.get("queue") or []) if isinstance(r, dict)
    ]
    # 剩余以队列表为准，禁止只用内存抽样长度（重启后续跑会「假完成」）
    try:
        db_pending = int(_queue_log_status_counts(rid, fresh=True).get("pending") or 0)
    except Exception:  # noqa: BLE001
        db_pending = 0
    rem_n = max(
        int(row.get("remainingCount") or 0),
        len(queue_list),
        db_pending,
    )
    row["queue"] = queue_list
    row["remainingCount"] = rem_n
    row["queueInLog"] = bool(row.get("queueInLog")) or rem_n > len(queue_list) or db_pending > len(
        queue_list
    )
    with _enrich_lock:
        cps = dict(_enrich_job.get("checkpoints") or {})
        cps[rid] = row
        _enrich_job["checkpoints"] = cps
    _persist_enrich_runtime()


def _clear_checkpoint(region: str = "") -> None:
    rid = str(region or "").strip()
    with _enrich_lock:
        if not rid:
            _enrich_job["checkpoints"] = {}
        else:
            cps = dict(_enrich_job.get("checkpoints") or {})
            cps.pop(rid, None)
            _enrich_job["checkpoints"] = cps
    _persist_enrich_runtime()


def _take_checkpoint(region: str) -> dict[str, Any] | None:
    rid = str(region or "").strip()
    if not rid:
        return None
    with _enrich_lock:
        cps = dict(_enrich_job.get("checkpoints") or {})
        raw = cps.pop(rid, None)
        _enrich_job["checkpoints"] = cps
    _persist_enrich_runtime()
    return dict(raw) if isinstance(raw, dict) else None


def _peek_checkpoint(region: str) -> dict[str, Any] | None:
    rid = str(region or "").strip()
    if not rid:
        return None
    _hydrate_enrich_runtime()
    with _enrich_lock:
        raw = (dict(_enrich_job.get("checkpoints") or {})).get(rid)
    return dict(raw) if isinstance(raw, dict) else None


def _slim_checkpoint_queue(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        item: dict[str, Any] = {
            "itemId": str(r.get("itemId") or ""),
            "code": str(r.get("code") or ""),
            "gaps": list(r.get("gaps") or []),
        }
        lid = _queue_log_int_id(r)
        if lid:
            item["logId"] = lid
        rel = str(r.get("rel_path") or r.get("relPath") or "")
        if rel:
            item["rel_path"] = rel
            item["relPath"] = rel
        out.append(item)
    return out


# app_settings 里塞 10万+ 队列会到数十 MB，每次 hydrate/status 都会拖垮 API
_CHECKPOINT_PERSIST_QUEUE_MAX = 200


def _checkpoint_for_persist(cp: dict[str, Any]) -> dict[str, Any]:
    """落盘检查点：只保留抽样队列 + remainingCount，完整续跑靠 enrich_queue_log。"""
    queue_raw = cp.get("queue") or []
    queue_list = [r for r in queue_raw if isinstance(r, dict)] if isinstance(queue_raw, list) else []
    declared = int(cp.get("remainingCount") or 0)
    rem_n = max(declared, len(queue_list))
    slim = _slim_checkpoint_queue(queue_list[:_CHECKPOINT_PERSIST_QUEUE_MAX])
    return {
        "region": str(cp.get("region") or ""),
        "mode": str(cp.get("mode") or "incremental"),
        "kinds": list(cp.get("kinds") or []),
        "dryRun": bool(cp.get("dryRun")),
        "ok": int(cp.get("ok") or 0),
        "failed": int(cp.get("failed") or 0),
        "done": int(cp.get("done") or 0),
        "originalTotal": int(cp.get("originalTotal") or 0),
        "queue": slim,
        "remainingCount": rem_n,
        "queueInLog": rem_n > len(slim),
    }


def _rebuild_checkpoint_queue_from_log(region: str) -> list[dict[str, Any]]:
    """检查点队列丢失/截断时，用 enrich_queue_log 的 pending 分页重建。"""
    rid = _queue_log_region(region)
    out: list[dict[str, Any]] = []
    if not rid:
        return out
    try:
        from app.core.db import connect, init_db

        init_db()
        last_id = 0
        log_off = 0
        with connect() as conn:
            while True:
                rows = conn.execute(
                    """
                    SELECT id, item_id, code, status, gaps_json, error, source,
                           fetch_ms, detail_title, payload_json
                    FROM enrich_queue_log
                    WHERE region=? AND status='pending'
                    ORDER BY updated_at DESC NULLS LAST, id DESC
                    LIMIT 2000 OFFSET ?
                    """,
                    (rid, log_off),
                ).fetchall()
                batch = list(rows or [])
                if not batch:
                    break
                log_off += len(batch)
                for r in batch:
                    if isinstance(r, dict):
                        it = _queue_log_row_to_item(r)
                        last_id = int(r.get("id") or last_id)
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
                        last_id = int(r[0] or last_id)
                    out.append(
                        {
                            "itemId": str(it.get("itemId") or ""),
                            "code": str(it.get("code") or ""),
                            "gaps": list(it.get("gaps") or []),
                            **(
                                {"logId": int(it["logId"])}
                                if it.get("logId")
                                else {}
                            ),
                            **(
                                {
                                    "rel_path": str(
                                        it.get("rel_path") or it.get("relPath") or ""
                                    ),
                                    "relPath": str(
                                        it.get("relPath") or it.get("rel_path") or ""
                                    ),
                                }
                                if (it.get("rel_path") or it.get("relPath"))
                                else {}
                            ),
                        }
                    )
                if len(batch) < 2000:
                    break
    except Exception as e:  # noqa: BLE001
        log.warning("rebuild checkpoint queue from log failed region=%s: %s", rid, e)
    return out


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


def _detail_sources(*, region: str = "", code: str = "") -> list[dict[str, Any]]:
    """数据源页：六区对应分组 ∩ 已启用 ∩ 有详情实现，按目录顺序。"""
    import app.scrape.sources_settings as scrape_src

    return list(scrape_src.enabled_enrich_sources(region=region, code=code) or [])


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


def _title_lacks_zh(title: str, code: str = "") -> bool:
    """标题非空但仍非中文（日文假名 / 纯英文等）→ 软成功缺口。"""
    t = str(title or "").strip()
    if not t:
        return False
    code_u = str(code or "").strip().upper()
    if code_u and t.casefold() == code_u.casefold():
        return False
    # 剥番号前缀后再判中文，避免「YSN-661 …」干扰
    try:
        from app.scrap_library.enrich_extras import strip_title_code_prefix

        bare = strip_title_code_prefix(t, code_u) if code_u else t
    except Exception:  # noqa: BLE001
        bare = t
    body = str(bare or t).strip()
    if len(body) < 2:
        return False
    return _zh_prefer_bonus(body) <= 0


def _normalize_merged_title(value: str) -> str:
    """中文标题收尾：修正「…。」夹在序号/女优名前，去掉易被当成脏数据的孤立尾号。"""
    s = str(value or "").strip()
    if not s:
        return s
    # 碟版尾巴
    s = re.sub(r"\s*[\(（]\s*DOD\s*[\)）]\s*$", "", s, flags=re.I).strip()
    # 「出手了…。 2」→「出手了… 2」（句号误夹在系列序号前）
    s = re.sub(r"([…⋯]?)\s*[。．.]\s*(\d{1,2})\s*$", r"\1 \2", s)
    # 「…。」统一成「…」（句中/句末误夹句号，STARS-900：性骚扰…。』）
    s = re.sub(r"([…⋯]+)\s*[。．.]", r"\1", s)
    # 「我…。 和香夏树」→「我… 和香夏树」（句号误夹在尾部女优名前；上式已去句号，再收空白）
    s = re.sub(
        r"([…⋯]+)\s+([\u4e00-\u9fffぁ-んァ-ン]{2,8})\s*$",
        r"\1 \2",
        s,
    )
    # MGS 附赠 / 站点尾巴（只剥尾部，勿把「…MGS…」前整段标题吃掉）
    s = re.sub(
        r"\s*[\[【(（]?\s*MGS\b[^\[】)\]]*[\]】)）]?\s*(?:Video\b)?(?:\s*成人视频流媒体网站)?\s*$",
        "",
        s,
        flags=re.I,
    )
    # 包裹引号 + 站点尾巴残留
    s = s.strip().strip("“”\"'「」『』")
    s = re.sub(r"\s*成人视频流媒体网站\s*$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+", " ", s).strip()
    # 不成对直角引号残留（『…』剥半边后剩 「…』」）
    if "』" in s and "『" not in s:
        s = s.replace("』", "")
    if "」" in s and "「" not in s:
        s = s.replace("」", "")
    # 纯中文标题：繁简字形折叠（哪裡→哪里、一週→一周、奇蹟→奇迹）
    # + 去掉末尾孤立「 2」「 10」——日文官名常带卷号，中译再挂尾号易像刮削残留
    if _zh_prefer_bonus(s) > 0 and not _has_kana(s):
        try:
            from app.scrape.metadata_optimize import _fold_variant

            folded = _fold_variant(s)
            if folded:
                s = folded
        except Exception:  # noqa: BLE001
            pass
        trimmed = re.sub(r"\s+\d{1,2}$", "", s).strip()
        if len(trimmed) >= 12:
            s = trimmed
    return s


def _normalize_merged_overview(value: str) -> str:
    """剧情轻量清洗：叠词、标点前空白；中文剧情做繁简折叠。"""
    s = str(value or "").strip()
    if not s:
        return s
    # 乳头乳头 / 看看看 → 单次
    s = re.sub(r"([\u4e00-\u9fff]{2,6})\1+", r"\1", s)
    s = re.sub(r"\s+([？?！!。．、,，])", r"\1", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = s.strip()
    if _zh_prefer_bonus(s) > 0 and not _has_kana(s):
        try:
            from app.scrape.metadata_optimize import _fold_variant

            folded = _fold_variant(s)
            if folded:
                s = folded
        except Exception:  # noqa: BLE001
            pass
        # 与标题一致：省略号后误夹句号
        s = re.sub(r"([…⋯]+)\s*[。．.]", r"\1", s)
    return s


def _mt_junk_penalty(text: str, *, kind: str = "generic") -> int:
    """机翻垃圾：字面硬译/英日碎片/审查符残留 → 让日文官名胜出。

    kind=title：中文站常保留「チ○ポ」类伏字，○ 只轻罚，避免整题踢出中文池
    （IPZZ-448：airav/iqqtv 被 -35 罚出后 miss_av 脏译上位）。
    """
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
    # miss_av 等：礼貌机翻腔 + 硬译片语（MIDV-850「一个娱乐塔…您可以从…」）
    # 负分会踢出中文标题池，避免压过字段优先的 iqqtv
    if _has_han(t) and not _has_kana(t):
        mt_markers = 0
        if re.search(r"您可以|您将|您会从", t):
            mt_markers += 2
        if any(x in t for x in ("娱乐塔", "风俗塔楼", "一个娱乐", "及膝之间", "膝盖高的袜子")):
            mt_markers += 2
        if "从她" in t and ("享受" in t or "之间的缝隙" in t):
            mt_markers += 1
        if mt_markers >= 2:
            pen -= 50
        elif mt_markers == 1:
            pen -= 20
    # 中文里残留 ○/● 审查符
    if _has_han(t) and ("○" in t or "●" in t):
        n_dot = t.count("○") + t.count("●")
        if kind == "title":
            pen -= min(18, 6 + 4 * n_dot)
        else:
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


def _title_trailing_person_name(title: str) -> str:
    """取标题末尾可能的女优名（空格/破折号/叹号后的 2～8 字）。"""
    t = str(title or "").strip()
    if not t:
        return ""
    t2 = re.sub(r"[\[【(（].*$", "", t).strip()
    m = re.search(
        r"(?:[\s　！!。．.…⋯]+|[—–―－\-]+)([\u4e00-\u9fffぁ-んァ-ン]{2,8})\s*$",
        t2,
    )
    if not m:
        return ""
    nm = m.group(1).strip()
    if len(nm) < 2 or nm in _TITLE_TAIL_NOISE:
        return ""
    if nm.casefold() in _JUNK_ACTOR_TAGS or nm in _JUNK_ACTOR_TAGS:
        return ""
    if _is_platform_exclusivity_label(nm):
        return ""
    # 社团/部活尾巴不当人名
    if nm.endswith(("部", "部活")) and len(nm) <= 4:
        return ""
    return nm


def _title_actress_mismatch_penalty(
    title: str, *, allowed_actors: list[str] | None
) -> int:
    """标题尾名与定稿女优不一致时降权（CAWD-900：真由纪 vs 舞雪）。"""
    if not allowed_actors:
        return 0
    nm = _title_trailing_person_name(title)
    if not nm:
        return 0
    try:
        from app.scrape.metadata_optimize import (
            _actor_maps,
            _actor_should_drop,
            _fold_variant,
            _lookup_actor_hit,
            _map_actor_entry,
            mapping_language_from_settings,
        )
    except Exception:  # noqa: BLE001
        return 0

    def _fold(s: str) -> str:
        try:
            return _fold_variant(s).casefold()
        except Exception:  # noqa: BLE001
            return str(s or "").casefold()

    table = _actor_maps(mapping_language_from_settings())
    allowed: set[str] = set()
    for a in allowed_actors:
        s = str(a or "").strip()
        if not s:
            continue
        allowed.add(s)
        allowed.add(s.casefold())
        allowed.add(_fold(s))
        try:
            mapped, _ = _map_actor_entry(s, table)
            if mapped:
                allowed.add(mapped)
                allowed.add(mapped.casefold())
                allowed.add(_fold(mapped))
        except Exception:  # noqa: BLE001
            pass

    def _is_allowed(name: str) -> bool:
        if name in allowed or name.casefold() in allowed or _fold(name) in allowed:
            return True
        try:
            mapped, _ = _map_actor_entry(name, table)
        except Exception:  # noqa: BLE001
            mapped = ""
        if mapped and (
            mapped in allowed
            or mapped.casefold() in allowed
            or _fold(mapped) in allowed
        ):
            return True
        nm_f = _fold(name)
        return any(
            name in a or a in name or (nm_f and (nm_f in _fold(a) or _fold(a) in nm_f))
            for a in allowed
            if len(str(a)) >= 2
        )

    if _is_allowed(nm):
        return 0

    hit = _lookup_actor_hit(nm, table)
    if hit is not None and not _actor_should_drop(hit) and not _is_allowed(str(hit)):
        return -45

    # 同姓异名（伊藤真由纪 vs 伊藤舞雪）：表里没有错名时也能拉开分差
    nm_f = _fold(nm)
    for a in list(allowed):
        af = _fold(str(a))
        if len(nm_f) >= 3 and len(af) >= 3 and nm_f[:2] == af[:2] and nm_f != af:
            return -40
    return 0


def _score_title(
    value: str,
    *,
    code: str,
    source_id: str,
    allowed_actors: list[str] | None = None,
) -> int:
    import app.scrape.source_catalog as catalog

    t = str(value or "").strip()
    if not t:
        return -10_000
    sid = str(source_id or "").strip()
    # 色花堂/c_number 映射：给稳定中文底分，能与中文站候选公平比较
    if sid in {"mdcx_c_number", "local_code_title"}:
        score = 78
    else:
        score = catalog.field_trust(sid, "title")
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
    score += _mt_junk_penalty(t, kind="title")
    # 站点尾巴当标题（miss_av 把简介塞进 title 再挂 MGS）
    if "成人视频流媒体网站" in t or re.search(r"\bMGS\s*Video\b", t, re.I):
        score -= 50
    # 过长「剧情型」中文标题（整段 overview 塞进 title）
    if _has_han(t) and not _has_kana(t) and n > 90:
        score -= 20
    # 日文标题可用但不额外加分，避免压过中文候选
    # 剥离 DOD 碟版尾巴后更干净
    if re.search(r"\（?\s*DOD\s*\）?|\(DOD\)", t, re.I):
        score -= 6
    # 标题尾挂其它番号（UMD-557 … UD-736R）降权
    if _trailing_alt_code(t, code):
        score -= 18
    score += _title_actress_mismatch_penalty(t, allowed_actors=allowed_actors)
    return score


def _title_should_prefer_map(
    cur: str,
    mapped: str,
    *,
    code: str,
    allowed_actors: list[str] | None = None,
) -> bool:
    """源站标题 vs code-titles 映射：同分/源站更好则留源站；映射明显更好才换。"""
    m = str(mapped or "").strip()
    if not m or _title_is_thin(m, code):
        return False
    c = str(cur or "").strip()
    if not c or _title_is_thin(c, code):
        return True
    # 同一基准分，只比正文质量（不用 mdcx 的 78 底分压过源站）
    sc_c = _score_title(
        c, code=code, source_id="compare", allowed_actors=allowed_actors
    )
    sc_m = _score_title(
        m, code=code, source_id="compare", allowed_actors=allowed_actors
    )
    return sc_m > sc_c


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


def _norm_code_token(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _trailing_alt_code(title: str, code: str) -> str:
    """标题末尾挂的其它品番（与本号不同）；无则空串。"""
    t = str(title or "").strip()
    m = _TRAILING_ALT_CODE_RE.search(t)
    if not m:
        return ""
    alt = _norm_code_token(m.group(1))
    cur = _norm_code_token(code)
    if not alt or (cur and alt == cur):
        return ""
    # 过短噪声（如 HD）忽略
    if len(alt) < 5:
        return ""
    return str(m.group(1)).strip()


def _strip_trailing_alt_code(title: str, code: str) -> str:
    t = str(title or "").strip()
    alt = _trailing_alt_code(t, code)
    if not alt:
        return t
    m = _TRAILING_ALT_CODE_RE.search(t)
    if not m:
        return t
    return t[: m.start()].rstrip(" 　-–—|｜/")


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
            _fold_variant,
            _lookup_actor_hit,
            _map_actor_entry,
            mapping_language_from_settings,
        )
    except Exception:  # noqa: BLE001
        return 0

    def _fold(s: str) -> str:
        try:
            return _fold_variant(s).casefold()
        except Exception:  # noqa: BLE001
            return str(s or "").casefold()

    table = _actor_maps(mapping_language_from_settings())
    allowed: set[str] = set()
    for a in allowed_actors:
        s = str(a or "").strip()
        if not s:
            continue
        allowed.add(s)
        allowed.add(s.casefold())
        allowed.add(_fold(s))
        try:
            mapped, _ = _map_actor_entry(s, table)
            if mapped:
                allowed.add(mapped)
                allowed.add(mapped.casefold())
                allowed.add(_fold(mapped))
        except Exception:  # noqa: BLE001
            pass

    def _is_allowed(nm: str) -> bool:
        if nm in allowed or nm.casefold() in allowed or _fold(nm) in allowed:
            return True
        try:
            mapped, _ = _map_actor_entry(nm, table)
        except Exception:  # noqa: BLE001
            mapped = ""
        if mapped and (mapped in allowed or mapped.casefold() in allowed or _fold(mapped) in allowed):
            return True
        nm_f = _fold(nm)
        return any(
            nm in a or a in nm or (nm_f and (nm_f in _fold(a) or _fold(a) in nm_f))
            for a in allowed
            if len(str(a)) >= 2
        )

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
    # miss_av / 镜像站首页广告当剧情（MDM-003）
    if any(
        x in t
        for x in (
            "免费高清日本",
            "无需下载",
            "超过十万部",
            "十萬部",
            "开始播放后不会再有广告",
            "支援任何装置",
            "免费加入会员后可任意收藏",
            "可以番号，女优或作品系列",
        )
    ):
        return -10_000
    # 剧情几乎等于标题（HUNBL-108）→ 伪剧情
    # 由调用方在有 title 时再扣；此处对极短「整段即标题」形态降权
    if n < 24 and not re.search(r"[。！？!?.]", t):
        score -= 25
    # 「番号 标题 - 站名」一类空壳剧情
    if re.search(r"\s-\s*[a-z0-9.-]+\s*$", t, flags=re.I) and n < 80:
        return -10_000
    # 「EVO-073 职业女人 34」无正文、几乎等于标题
    if n < 48 and re.match(r"^[A-Z0-9]+-\d+\b", t, flags=re.I):
        score -= 45
    score += _overview_foreign_actress_penalty(t, allowed_actors=allowed_actors)
    score += _mt_junk_penalty(t)
    return score


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
    # 不因含汉字加分：女优名不强制中文，避免压过日文官名源
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


def _field_priority_applies(region: str = "") -> bool:
    """字段优先级仅对有码区生效；其它区只看「优先级设置(全局)」分区源。"""
    try:
        from app.scrape.sources_settings import resolve_enrich_region_id

        return resolve_enrich_region_id(region) == "japan_censored"
    except Exception:  # noqa: BLE001
        return False


def _strategy_field_priority(field: str, *, region: str = "") -> list[str] | None:
    if region and not _field_priority_applies(region):
        return None
    try:
        from app.scrap_library.enrich_strategy import get_strategy
        from app.scrape.sources_settings import is_provider_enabled

        fp = get_strategy().get("fieldPriority") or {}
        chain = fp.get(field) if isinstance(fp, dict) else None
        if isinstance(chain, list) and chain:
            # 总开关关闭的源：配置里可留着，合并时一律跳过
            return [str(x) for x in chain if is_provider_enabled(str(x))]
    except Exception:  # noqa: BLE001
        pass
    return None


def _strategy_region_sources(region: str, *, code: str = "") -> list[str]:
    try:
        from app.scrap_library.enrich_strategy import (
            region_sources_for,
            uncensored_official_for_code,
        )
        from app.scrape.sources_settings import (
            is_provider_enabled,
            resolve_enrich_region_id,
        )

        base = [
            s
            for s in (region_sources_for(region) or [])
            if is_provider_enabled(s)
        ]
        rid = resolve_enrich_region_id(region)
        if rid == "japan_uncensored" and code:
            official = [
                s
                for s in (uncensored_official_for_code(code) or [])
                if is_provider_enabled(s)
            ]
            if official:
                seen: set[str] = set()
                out: list[str] = []
                for sid in list(official) + base:
                    if not sid or sid in seen:
                        continue
                    seen.add(sid)
                    out.append(sid)
                return out
        return base
    except Exception:  # noqa: BLE001
        return []


def _merge_source_allowed(source_id: str) -> bool:
    """合并候选是否可用：本地伪源放行；真实站须开着总开关。"""
    sid = str(source_id or "").strip()
    if not sid:
        return False
    # 本地伪源 / 映射表：不走数据源总开关
    if (
        sid.startswith("local_")
        or sid.startswith("mdcx_")
        or sid in {"manual", "nfo", "cache", "mdcx_c_number"}
    ):
        return True
    try:
        from app.scrape.sources_settings import is_provider_enabled

        return is_provider_enabled(sid)
    except Exception:  # noqa: BLE001
        return True


def _pick_by_field_priority(
    candidates: list[tuple[str, str, int]],
    field: str,
    *,
    min_score: int | None = None,
    region: str = "",
) -> tuple[str, str] | None:
    """字段优先级选值。

    有码区：
    1) 字段配置源（设置「字段优先级」）按顺序 —— 已关总开关的跳过
    2) 番号类型全局源（设置「全局优先级」）按顺序 —— 同上
    3) 其余站按可信度链；配置/全局阶段有数据即用

    其它区：跳过字段优先级，只走全局分区源 + 可信度链。
    """
    import app.scrape.source_catalog as catalog

    usable = [
        (catalog.canonicalize_id(sid), str(val or "").strip(), int(score))
        for sid, val, score in candidates
        if str(val or "").strip() and _merge_source_allowed(str(sid or ""))
    ]
    if not usable:
        return None

    by_sid: dict[str, list[tuple[str, int]]] = {}
    for sid, val, score in usable:
        by_sid.setdefault(sid, []).append((val, score))

    preferred = [
        catalog.canonicalize_id(s)
        for s in (_strategy_field_priority(field, region=region) or [])
        if catalog.canonicalize_id(s)
    ]
    pref_seen: set[str] = set()
    preferred_u: list[str] = []
    for sid in preferred:
        if sid not in pref_seen:
            pref_seen.add(sid)
            preferred_u.append(sid)

    region_chain: list[str] = []
    region_seen: set[str] = set()
    for sid in _strategy_region_sources(region):
        cs = catalog.canonicalize_id(sid)
        if cs and cs not in region_seen and cs not in pref_seen:
            region_seen.add(cs)
            region_chain.append(cs)

    def _first_ok(sids: list[str], *, use_margin: bool) -> tuple[str, str] | None:
        best_score = max(sc for _s, _v, sc in usable)
        for sid in sids:
            for val, score in by_sid.get(sid) or []:
                if min_score is not None and score < min_score:
                    continue
                if field == "overview" and score < 0:
                    continue
                if use_margin:
                    if field == "title":
                        margin = 8
                    elif field == "overview":
                        margin = 5
                    else:
                        margin = 35
                    if best_score - score > margin:
                        continue
                return val, sid
        return None

    # 1) 字段配置源
    if preferred_u:
        hit = _first_ok(preferred_u, use_margin=False)
        if hit:
            return hit

    # 2) 番号类型全局有序源
    if region_chain:
        hit = _first_ok(region_chain, use_margin=False)
        if hit:
            return hit

    # 3) 其余
    chain = catalog.field_priority_chain(
        field, override=preferred_u or None
    )
    skip = pref_seen | region_seen
    rest = [
        s
        for s in chain
        if s not in skip and _merge_source_allowed(s)
    ]
    hit = _first_ok(rest, use_margin=True)
    if hit:
        return hit

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
        _top_n = len({m[0] for m in _top})
        _seed_n = len({m[0] for m in _seed_cl}) if _seed_cl else 0
        try:
            from app.scrape.metadata_optimize import _fold_variant as _fold
        except Exception:  # noqa: BLE001
            def _fold(x: str) -> str:  # type: ignore[misc]
                return str(x or "")

        _acts_by_sid = {
            _sid: {
                _fold(str(a).strip()).casefold()
                for a in (_d.get("actors") or [])
                if str(a or "").strip()
            }
            for _sid, _d, _w in prelim
        }
        _old_acts = (
            set().union(*(_acts_by_sid.get(m[0] or "", set()) for m in _seed_cl))
            if _seed_cl
            else set()
        )
        _new_acts = set().union(
            *(_acts_by_sid.get(m[0] or "", set()) for m in _top)
        )
        _overlap = bool(_old_acts & _new_acts)
        _top_title = _top[0][1] if _top else ""
        # 换锚：① 最大簇比种子簇多 ≥2 源（RBD-035）；或
        # ② 种子是单源中文、≥2 源日文同题且标题不兼容且女优无交集
        #    （MDM-003：miss_av「恋爱咖啡馆」错绑日本有码月刊マダム）
        _switch = False
        if _seed_cl is not None and _top is not _seed_cl and _top_n >= 2:
            if _top_n - _seed_n >= 2:
                _switch = True
            elif (
                _seed_n == 1
                and not _overlap
                and not _has_kana(seed)
                and _has_kana(_top_title)
                and not _titles_compatible(seed, _top_title, actors=_all_hints)
            ):
                _switch = True
        if _switch:
            seed = _top_title
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
        if not ok:
            # 标题机翻/意译与日文官名不兼容，但女优与锚点簇有交集 → 同片，保留
            # （OERO/DOJN：miss_av 长中文题被拒后剧情一并清空）
            try:
                from app.scrape.metadata_optimize import _fold_variant as _fold
            except Exception:  # noqa: BLE001

                def _fold(x: str) -> str:  # type: ignore[misc]
                    return str(x or "")

            def _act_keys(names: list[Any] | None) -> set[str]:
                out: set[str] = set()
                for a in names or []:
                    s = str(a or "").strip()
                    if not s:
                        continue
                    # miss_av「さつきさん 27歳…」只取首段
                    head = re.split(r"[\s　(/（]", s, maxsplit=1)[0].strip() or s
                    for piece in (s, head):
                        out.add(_fold(piece).casefold())
                        _d2, kid = _actress_disp_id(piece)
                        if kid:
                            out.add(kid.casefold())
                        if _d2:
                            out.add(_fold(_d2).casefold())
                return out

            src_acts = _act_keys(list(d.get("actors") or []))
            if src_acts:
                anchor_acts: set[str] = set()
                for _sid2, _d2, _w2 in prelim:
                    if _w2:
                        continue
                    t2 = str(_d2.get("title") or "").strip()
                    if not t2:
                        continue
                    if any(
                        _titles_compatible(t2, a, actors=hints) for a in anchors if a
                    ):
                        anchor_acts |= _act_keys(list(_d2.get("actors") or []))
                if src_acts & anchor_acts:
                    ok = True
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


def _merge_got(
    sources: list[dict[str, Any]],
    got: dict[str, dict[str, Any]],
    *,
    region: str = "",
    probe: bool = False,
) -> dict[str, Any] | None:
    """多源字段级可信合并：每字段取 trust+质量 最高；女优/标签并集。

    probe=True：早停探测用轻量合并（跳过标签精修/extras），避免 as_completed
    主线程被反复全量合并拖死。
    """
    import app.scrape.source_catalog as catalog

    try:
        from app.scrap_library.enrich_strategy import local_map_mode

        actors_map_mode = local_map_mode("actors")
        tags_map_mode = local_map_mode("tags")
    except Exception:  # noqa: BLE001
        actors_map_mode = "fallback"
        tags_map_mode = "fallback"
    actors_map_on = actors_map_mode != "off"
    tags_map_on = tags_map_mode != "off"

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
    # 封面候选（带源站），供下载阶段优先池/全局池
    poster_entries: list[dict[str, str]] = []
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
        # code-titles 映射不在此注入：源站先合并定稿，再于 _apply_mdcx_maps 优选/兜底/强制
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
            if s.startswith(("http://", "https://")):
                if s not in all_poster_urls:
                    all_poster_urls.append(s)
                poster_entries.append({"source": sid, "url": s})
        if poster.startswith(("http://", "https://")):
            poster_cands_scored.append(
                (sid, poster, _score_poster(poster, source_id=sid))
            )
        actors = _clean_actors(d.get("actors"))
        # fetch 阶段已 polish 的源不再重跑；未标记的（E2E/预取）才映射
        if actors and not d.get("_actorsPolished"):
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
                actors = polish_actress_names(
                    actors,
                    exclude=directors,
                    enable_mapping=actors_map_on,
                )
            except Exception:  # noqa: BLE001
                pass
        if actors:
            actor_lists.append((sid, actors, _score_actors(actors, source_id=sid)))
        tags = [str(t).strip() for t in (d.get("tags") or []) if str(t).strip()]
        if tags:
            tag_lists.append((sid, tags, _score_tags(tags, source_id=sid)))

    # 本地番号→女优映射（av_metadata 导出）：作为候选源参与共识投票，
    # provider 们都没给出演员时兜底；与 mdcx_c_number 标题兜底同规格。
    if (
        actors_map_on
        and code
        and not any(sid == "local_code_actors" for sid, _a, _s in actor_lists)
    ):
        try:
            from app.core.maps_paths import lookup_code_actors
            from app.scrape.metadata_optimize import polish_actress_names

            local_actors = polish_actress_names(
                list(lookup_code_actors(code)), enable_mapping=True
            )
            local_actors = _clean_actors(local_actors)
            if local_actors:
                actor_lists.append(
                    (
                        "local_code_actors",
                        local_actors,
                        _score_actors(local_actors, source_id="local_code_actors"),
                    )
                )
        except Exception:  # noqa: BLE001
            pass

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
        if _zh_prefer_bonus(str(t or "")) > 0
        # 标题允许轻度 ○ 伏字罚分（kind=title）；真机翻腔仍 < -20 踢出
        and _mt_junk_penalty(str(t or ""), kind="title") >= -20
        and not _title_is_thin(str(t or ""), code)
    ]
    if usable_zh_titles:
        title_pick_cands = usable_zh_titles
    picked = _pick_by_field_priority(title_pick_cands, "title", region=region)
    if picked:
        title_v, title_src = picked
        merged["title"] = _strip_trailing_alt_code(
            _normalize_merged_title(title_v), code
        )
        field_sources["title"] = title_src
    # 定稿仍空或仍薄：回落全候选里「规范化后仍可用」的最高分
    if _title_is_thin(str(merged.get("title") or ""), code) and title_cands:
        ranked = sorted(title_cands, key=lambda x: -x[2])
        for sid, raw, _sc in ranked:
            cand = _strip_trailing_alt_code(_normalize_merged_title(str(raw or "")), code)
            if _title_is_thin(cand, code):
                continue
            merged["title"] = cand
            field_sources["title"] = sid
            break
    # 色花堂标题覆盖改在合并末尾 _apply_mdcx_maps（对齐 MDCX translate_title_outline）
    # 保留最佳日文标题，供机翻过烂时 LLM 回译（须与定稿标题兼容）
    jp_title_cands = [
        (sid, t, sc)
        for sid, t, sc in title_cands
        if _has_kana(str(t or ""))
    ]
    if jp_title_cands:
        jp_picked = _pick_by_field_priority(jp_title_cands, "title", region=region)
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
    picked = _pick_by_field_priority(studio_cands, "studio", region=region)
    if picked:
        merged["studio"], field_sources["studio"] = picked
    picked = _pick_by_field_priority(maker_cands, "maker", region=region)
    if picked:
        merged["maker"], field_sources["maker"] = picked
    elif merged.get("studio"):
        merged["maker"] = merged["studio"]
        field_sources["maker"] = field_sources.get("studio") or ""
    # 合并后再映射展示名（评分仍用源站原串，避免映射后改分）
    studio_raw = str(merged.get("studio") or "").strip()
    maker_raw = str(merged.get("maker") or "").strip()
    if studio_raw:
        merged["studio"] = _polish_studio_name(studio_raw)
    if maker_raw:
        if maker_raw == studio_raw:
            merged["maker"] = str(merged.get("studio") or "")
        else:
            merged["maker"] = _polish_studio_name(maker_raw)
    elif merged.get("studio"):
        merged["maker"] = merged["studio"]
    # overview 延后到女优共识后再选
    picked = _pick_by_field_priority(date_cands, "date", region=region)
    if picked:
        merged["date"], field_sources["date"] = picked
    picked = _pick_by_field_priority(year_cands, "year", region=region)
    if picked:
        merged["year"], field_sources["year"] = picked

    # 封面：候选按质量排序；主图沿 poster 优先级链；下载用带 source 的详细列表
    all_poster_urls.sort(key=_poster_rank, reverse=True)
    if all_poster_urls:
        merged["posterCandidates"] = all_poster_urls[:8]
    # 去重保序；再按「字段优先级 · 海报」排序，下载优先池严格跟设置
    seen_pu: set[str] = set()
    detailed: list[dict[str, str]] = []
    for ent in poster_entries:
        u = ent.get("url") or ""
        if u in seen_pu:
            continue
        seen_pu.add(u)
        detailed.append(ent)
    poster_fp = [
        catalog.canonicalize_id(s)
        for s in (_strategy_field_priority("poster", region=region) or [])
        if catalog.canonicalize_id(s)
    ]
    poster_fp_rank = {sid: i for i, sid in enumerate(poster_fp)}

    def _poster_entry_key(ent: dict[str, str]) -> tuple[int, int]:
        sid = catalog.canonicalize_id(str(ent.get("source") or ""))
        src_i = poster_fp_rank.get(sid, 10_000)
        return (src_i, -_poster_rank(str(ent.get("url") or "")))

    detailed.sort(key=_poster_entry_key)
    if detailed:
        merged["posterCandidatesDetailed"] = detailed[:32]
    best_poster = _pick_by_field_priority(poster_cands_scored, "poster", region=region)
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
    # （local_code_actors 是番号精确键入的本地映射，身份安全，豁免标题过滤）
    titles_alive = {
        sid
        for sid, d in details
        if str(d.get("title") or "").strip()
        or (
            isinstance(d.get("extra"), dict)
            and str((d.get("extra") or {}).get("titleZh") or "").strip()
        )
    }
    titles_alive.add("local_code_actors")
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
        # 按身份键投票（日/中/别名同人只算一票/源）
        vote: Counter[str] = Counter()
        display_for: dict[str, str] = {}
        order_ids: list[str] = []
        for _sid, names, _sc in actor_lists:
            seen_src: set[str] = set()
            for a in _unique_identity_names(list(names or [])):
                _disp, kid = _actress_disp_id(a)
                if not kid or kid in seen_src:
                    continue
                seen_src.add(kid)
                if kid not in display_for:
                    display_for[kid] = a
                    order_ids.append(kid)
                vote[kid] += 1
        n_src = len(actor_lists)
        need = 3 if n_src >= 5 else 2
        consensus_ids = [kid for kid in order_ids if vote[kid] >= need]
        if consensus_ids:
            actors_out = [display_for[kid] for kid in consensus_ids][:12]
            # 高分源名单是共识超集时并入缺员（身份去重）
            top_names = _unique_identity_names(list(actor_lists[0][1] or []))
            cons_ids = set(consensus_ids)
            top_ids = {_actress_disp_id(a)[1] for a in top_names}
            if cons_ids and cons_ids <= top_ids and len(top_names) > len(actors_out):
                actors_out = top_names[:12]
        else:
            title_src = str(field_sources.get("title") or "")
            prefer = next(
                (names for sid, names, _sc in actor_lists if sid == title_src),
                None,
            )
            actors_out = _unique_identity_names(
                list(prefer or actor_lists[0][1])
            )[:12]
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

            mentioned = polish_actress_names(
                title_names, enable_mapping=actors_map_on
            )
            mentioned_ids = {
                _actress_disp_id(n)[1] for n in mentioned if _actress_disp_id(n)[1]
            }
            have = list(actors_out)
            have_ids = {
                _actress_disp_id(n)[1] for n in have if _actress_disp_id(n)[1]
            }
            for _sid, names, _sc in actor_lists:
                for n in names:
                    ns = str(n or "").strip()
                    kid = _actress_disp_id(ns)[1]
                    if ns and kid in mentioned_ids and kid not in have_ids:
                        have.append(ns)
                        have_ids.add(kid)
            for n in mentioned:
                kid = _actress_disp_id(n)[1]
                if kid and kid not in have_ids:
                    have.append(n)
                    have_ids.add(kid)
            if have:
                actors_out = _unique_identity_names(have)[:12]
        except Exception:  # noqa: BLE001
            for n in title_names:
                if n not in actors_out:
                    actors_out.append(n)
            actors_out = _unique_identity_names(actors_out)[:12]
    # 收口映射一次：别名/繁简收敛 + 去重（身份主名，不强制中文）
    try:
        from app.scrape.metadata_optimize import polish_actress_names

        polished = polish_actress_names(
            actors_out, enable_mapping=actors_map_on
        )
        merged["actors"] = polished if polished else _unique_identity_names(actors_out)
    except Exception:  # noqa: BLE001
        merged["actors"] = _unique_identity_names(actors_out)

    # 按身份簇+各源人数收口（不再从标题尾猜人名）
    actor_lists_for_alias = actor_lists
    try:
        raw_sides: list[tuple[str, list[str], int]] = []
        for sid, d in details:
            raw_a = _clean_actors(d.get("actors"))
            if not raw_a:
                continue
            sc = next((s2 for s, n, s2 in actor_lists if s == sid), 0)
            raw_sides.append((sid, raw_a, int(sc or 0)))
        if raw_sides:
            actor_lists_for_alias = raw_sides + [
                (sid, names, sc)
                for sid, names, sc in actor_lists
                if sid not in {s for s, _, _ in raw_sides}
            ]
    except Exception:  # noqa: BLE001
        pass
    pair_n = len(
        _unique_identity_names(_names_from_title_pairs(title_hay) if title_hay else [])
    )
    collapsed, alias_extra = _collapse_few_actress_variants(
        list(merged.get("actors") or []),
        actor_lists_for_alias,
        title_pair_n=pair_n,
    )
    if collapsed and not merged.get("actorsMapForced"):
        merged["actors"] = collapsed
    # 最终再按身份去重，防止别名残留双写
    merged["actors"] = _unique_identity_names(list(merged.get("actors") or []))[:12]
    if (
        alias_extra
        and len(merged["actors"]) == 1
        and not merged.get("actorsMapForced")
    ):
        # 供女优档案 upsert：主名以外的跨源异写
        primary_fold = merged["actors"][0].casefold()
        merged["actorAliases"] = [
            a for a in alias_extra if a and a.casefold() != primary_fold
        ][:16]
        field_sources["actorsNote"] = "singleton_collapse"
    elif "actorAliases" in merged:
        merged.pop("actorAliases", None)

    # 剧情：结合本片女优名单，惩罚串入其他女优名的中文灌水剧情（STAR-795）
    # 并丢弃与已选标题明显不是同一作品的源剧情（ABF-005：ジュポニカ错页）
    allowed_for_plot: list[str] = list(merged.get("actors") or [])
    for _sid, names, _sc in actor_lists:
        for a in names:
            s = str(a or "").strip()
            if s and s not in allowed_for_plot:
                allowed_for_plot.append(s)
    for a in alias_extra or []:
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
            _score_overview(ov, source_id=sid, allowed_actors=allowed_for_plot)
            + (
                -80
                if (
                    str(merged.get("title") or "").strip()
                    and str(ov or "").strip()
                    and (
                        str(ov).strip() == str(merged.get("title") or "").strip()
                        or (
                            len(str(ov).strip()) <= len(str(merged.get("title") or "").strip())
                            + 4
                            and str(merged.get("title") or "").strip() in str(ov).strip()
                            and len(str(ov).strip()) < 40
                        )
                    )
                )
                else 0
            ),
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
    # 与标题同规：有可用中文剧情时只在中文池里走优先级链，避免链首日文
    # 以 margin≤5 反压更高分中文（XRW-394：airav_io@120 日文压过 miss_av@125 中文）。
    overview_pick_cands = overview_usable
    usable_zh_ovs = [
        (sid, ov, sc)
        for sid, ov, sc in overview_usable
        if _zh_prefer_bonus(str(ov or "")) > 0
        and _mt_junk_penalty(str(ov or "")) >= 0
    ]
    if usable_zh_ovs:
        overview_pick_cands = usable_zh_ovs
    picked = _pick_by_field_priority(overview_pick_cands, "overview", region=region)
    if picked:
        ov_v, ov_src = picked
        # 链首仍可能是水印空壳（负分）：强制换成全源最高分
        pick_sc = next(
            (
                int(sc)
                for sid, ov, sc in overview_pick_cands
                if sid == ov_src and ov == ov_v
            ),
            -10_000,
        )
        if pick_sc < 0 and overview_pick_cands:
            best = max(overview_pick_cands, key=lambda x: int(x[2]))
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
        jp_picked = _pick_by_field_priority(jp_ov, "overview", region=region)
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
        # 标签：配置优先源整套打底（顺序如 JavBus→AVBase）；否则按分最高源打底
        tag_lists = [
            (sid, tags, sc)
            for sid, tags, sc in tag_lists
            if _overview_source_ok(sid) and _merge_source_allowed(str(sid))
        ]
        pref_tags = [
            catalog.canonicalize_id(s)
            for s in (_strategy_field_priority("tags", region=region) or [])
            if catalog.canonicalize_id(s)
        ]
        # 字段未配标签源时：用番号类型全局顺序打底
        if not pref_tags:
            pref_tags = [
                catalog.canonicalize_id(s)
                for s in _strategy_region_sources(region)
                if catalog.canonicalize_id(s)
            ]
        if pref_tags:
            by_tags = {
                catalog.canonicalize_id(sid): (list(tags), int(sc))
                for sid, tags, sc in tag_lists
            }
            ordered_tags: list[tuple[str, list[str], int]] = []
            seen_tag_src: set[str] = set()
            for sid in pref_tags:
                hit = by_tags.get(sid)
                if hit and sid not in seen_tag_src:
                    ordered_tags.append((sid, hit[0], hit[1]))
                    seen_tag_src.add(sid)
            for sid, tags, sc in sorted(tag_lists, key=lambda x: -x[2]):
                cs = catalog.canonicalize_id(sid)
                if cs not in seen_tag_src:
                    ordered_tags.append((cs, list(tags), int(sc)))
                    seen_tag_src.add(cs)
            tag_lists = ordered_tags
        else:
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
        if not probe:
            try:
                from app.scrape.metadata_optimize import (
                    code_prefix,
                    polish_tag_names,
                )

                # 排除集用「全源女优名并集」(allowed_for_plot)，而非只排最终 merged 名单：
                # 合集/BEST 里没进最终名单的女优名也会被源站当标签塞进来
                # （CJOB-134：javbus 标签含 ERINA/AIKA/久留木玲，落在最终 12 人名单外 → 漏删）
                # 注意：禁止在热路径 clear_map_cache——多番号并发会反复冷加载
                # actors/tags 大表，把早停探测拖到几十秒。
                tags_out = polish_tag_names(
                    tags_out,
                    exclude=list(allowed_for_plot) + list(title_names or []),
                    prefix=code_prefix(code),
                    enable_mapping=tags_map_on,
                )
            except Exception:  # noqa: BLE001
                pass
    merged["tags"] = tags_out

    # 禁止从标签/标题硬套女优：无 <actor>/actors 字段则保持空

    contrib = list(dict.fromkeys(order_hit))
    merged["sources"] = contrib
    merged["source"] = field_sources.get("title") or (
        contrib[0] if contrib else merged.get("source")
    )
    merged["provider"] = merged.get("source")
    merged["resolvedSources"] = contrib
    merged["fieldSources"] = {k: v for k, v in field_sources.items() if v}

    if probe:
        # 早停探测：只补色花堂标题（常为中文，可免等 airav），不做标签/演员二次精修
        if code:
            try:
                from app.core.maps_paths import lookup_code_title

                mapped = str(lookup_code_title(code) or "").strip()
                cur = str(merged.get("title") or "").strip()
                if mapped and (
                    not cur
                    or _title_is_thin(cur, code)
                    or (
                        _zh_prefer_bonus(mapped) > 0
                        and _zh_prefer_bonus(cur) <= 0
                    )
                ):
                    if cur and _has_kana(cur) and not merged.get("titleJa"):
                        merged["titleJa"] = cur
                    merged["title"] = _strip_trailing_alt_code(
                        _normalize_merged_title(mapped), code
                    )
                    fs = dict(merged.get("fieldSources") or {})
                    fs["title"] = "mdcx_c_number"
                    merged["fieldSources"] = fs
                    merged["titleMapApplied"] = True
            except Exception:  # noqa: BLE001
                pass
        # 轻量补系列/发行/官网等，供早停判断「元数据是否已齐」
        try:
            from app.scrap_library.enrich_extras import pick_secondary_fields

            for k, v in pick_secondary_fields(details).items():
                if v and not merged.get(k):
                    merged[k] = v
        except Exception:  # noqa: BLE001
            pass
        return merged

    # MDCX 映射段：色花堂标题 → 演员 → 标签 → 简介换行（封面下载之前）
    merged = _apply_mdcx_maps(merged, code=code) or merged

    # I41–I52 择优后处理
    try:
        from app.scrap_library.enrich_extras import apply_merge_extras

        apply_merge_extras(
            merged,
            details=details,
            actor_lists=list(actor_lists or []),
            region=region,
        )
    except Exception:  # noqa: BLE001
        pass
    # extras 可能改标题/女优：再收口一次映射，保证表最终生效
    merged = _apply_mdcx_maps(merged, code=code) or merged
    return merged


def _text_needs_zh_llm(text: str, *, kind: str = "generic") -> bool:
    """缺可用中文：日文原文 / 无汉字加成 / 机翻垃圾。"""
    t = str(text or "").strip()
    if not t:
        return False
    if _has_kana(t):
        return True
    # 标题轻度 ○ 不烧 LLM；剧情仍按通用门槛
    thr = -20 if kind == "title" else 0
    if _mt_junk_penalty(t, kind=kind) < thr:
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
    thr = -20 if kind == "title" else 0
    if _mt_junk_penalty(t, kind=kind) < thr:
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
    # ⚠️ `no_zh_title` **刻意不在这里判**（第二十一轮修正）。
    # 它曾是硬闸门：标题非中文就一律不许早停。但 dmm / avbase 这类源给出的是
    # 日文标题（含假名 → `_zh_prefer_bonus` 恒为 0），**永远不可能**满足这条，
    # 于是这些番号必然等到全部源回或超时 —— 早停对它们完全失效（现场 12% 的号）。
    # 正确归属是 `_may_early_stop` 的「中文源等待」逻辑：等中文源跑完即放行，
    # 而不是无限等所有源（含注定给不出中文的那几个）。
    # 反证：把它加回来 → `test_no_zh_title_is_not_a_hard_gate` 与
    # `test_no_zh_title_releases_after_cn_sources_done` 双双 FAILED（后者直接
    # 复现了「中文源已全跑完仍不许放行」的死锁）。
    return True


# 标题/剧情偏中文的源：缺这两项时早停需等它们结束（或已拿到无假名中文）
# （仅影响「能否早停」判定，不改发车顺序；顺序以 regionSources 配置为准）
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


# 缺口 → 策略 fieldPriority 字段（发车提权只读配置，不写死站点快慢）
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
# 同一次发车时字段链合并序：先文本/演员（利早停），海报链靠后
# （站点名单仍完全来自 fieldPriority 配置）
_FIELD_LAUNCH_ORDER: tuple[str, ...] = (
    "title",
    "overview",
    "actors",
    "studio",
    "maker",
    "poster",
    "tags",
)


def _prioritize_batch_for_gaps(
    batch: list[dict[str, Any]],
    gaps: list[str] | None,
    *,
    region: str = "",
) -> list[dict[str, Any]]:
    """按缺口对应的 fieldPriority 配置提权，其余保持 regionSources 原序。

    仅有码区生效；其它区保持 batch 原序（只看全局分区源）。
    例：缺标题/剧情时先发 fieldPriority.title/overview 里的站，
    避免 regionSources 开头的站占满波次槽、字段优先站迟迟发不出。
    """
    if len(batch) <= 1:
        return list(batch)
    if not _field_priority_applies(region):
        return list(batch)
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    if not gap_set:
        return list(batch)

    needed_fields: set[str] = set()
    for gap in gap_set:
        needed_fields.update(_GAP_FIELD_PRIORITY_KEYS.get(gap, ()))
    if not needed_fields:
        return list(batch)
    field_keys = [fk for fk in _FIELD_LAUNCH_ORDER if fk in needed_fields]
    # 配置里有、但不在预置序的字段：按需追加
    for fk in sorted(needed_fields):
        if fk not in field_keys:
            field_keys.append(fk)

    try:
        from app.scrap_library.enrich_strategy import get_strategy
        import app.scrape.source_catalog as catalog

        fp = get_strategy().get("fieldPriority") or {}
    except Exception:  # noqa: BLE001
        return list(batch)
    if not isinstance(fp, dict):
        return list(batch)

    prefer_ids: list[str] = []
    seen_ids: set[str] = set()
    for fk in field_keys:
        raw = fp.get(fk)
        if not isinstance(raw, list):
            continue
        for item in raw:
            sid = catalog.canonicalize_id(str(item or ""))
            if sid and sid not in seen_ids:
                seen_ids.add(sid)
                prefer_ids.append(sid)
    if not prefer_ids:
        return list(batch)

    by_id: dict[str, dict[str, Any]] = {}
    for src in batch:
        sid = catalog.canonicalize_id(str(src.get("id") or ""))
        if sid and sid not in by_id:
            by_id[sid] = src

    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for sid in prefer_ids:
        hit = by_id.get(sid)
        if hit is not None:
            out.append(hit)
            used.add(sid)
    for src in batch:
        sid = catalog.canonicalize_id(str(src.get("id") or ""))
        if sid in used:
            continue
        out.append(src)
        if sid:
            used.add(sid)
    return out


def _got_has_zh_title(got: dict[str, dict[str, Any]]) -> bool:
    for d in got.values():
        if not isinstance(d, dict):
            continue
        if _zh_prefer_bonus(str(d.get("title") or "")) > 0:
            return True
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        if _zh_prefer_bonus(str((extra or {}).get("titleZh") or "")) > 0:
            return True
    return False


def _got_has_zh_plot(got: dict[str, dict[str, Any]]) -> bool:
    for d in got.values():
        if not isinstance(d, dict):
            continue
        ov = str(d.get("overview") or "").strip()
        if len(ov) >= 12 and _zh_prefer_bonus(ov) > 0:
            return True
    return False


# 常能补齐系列/发行/官网/预告的源：缺口齐后仍稍等它们，避免主源早停把这些字段丢掉
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


def _detail_meta_incomplete(detail: dict[str, Any] | None) -> bool:
    """系列 / 发行 / 官网 任一仍缺则视为元数据未齐（预告可选，不挡早停）。"""
    if not detail or not isinstance(detail, dict):
        return True
    series = str(detail.get("series") or detail.get("set") or "").strip()
    publisher = str(detail.get("publisher") or detail.get("label") or "").strip()
    website = str(detail.get("website") or detail.get("url") or "").strip()
    return not (series and publisher and website.startswith(("http://", "https://")))


# 元数据（系列/发行/官网）的**有界等待**预算（秒）。
#
# 为什么需要：`_detail_meta_incomplete` 要求 `series + publisher + website` 三者齐，
# 但大量番号**本来就没有系列**（实测 MUKD-252、AARM-010/018/037/061 合并后
# `series` 均为空串）。于是「主缺口已齐」也无法早停 —— 只要本批还有
# `_META_FILL_SOURCE_IDS`（dmm/jav321/libredmm/avbase…）在飞就一路等到它们
# **全部回或超时**，而 avbase 单独就是 p50≈3.0s（第十七轮 D2）。
#
# 取值依据（`_diag_round17_gate_ab.py`，逐号交替 ON/OFF + 每次单跑前清 cooldown，
# 用真实队列行的 gaps 复测）：
#   现状             Σfetch(6 号) = 23,311ms   字段保有量 series4/pub4/web5/ovLen727
#   关闸门           Σfetch(6 号) =  6,897ms   同上，但 gaps=[] 时会丢 overview/publisher
#   有界等待 1.2s    Σfetch(6 号) = 14,701ms   同上，**一字不差**
# → 比现状快 32%、字段零损失；快源（dmm 488ms / libredmm 664ms）仍来得及补字段，
#   被砍掉的是 avbase 那条 ~3.0s 的尾巴。
# ⚠️ 该 A/B n=5，噪声大。它只是**上限**：预算内源回来了照样补字段，
#   预算用尽才放行早停，所以「字段保有量下降」只可能发生在慢源上。
_META_WAIT_BUDGET_SEC = 1.2

# 中文源（airav/iqqtv…）的**有界等待**预算（秒）。
#
# 缺 thin_title / no_plot / no_zh_title 时本会等 `_CN_TEXT_SOURCE_IDS` 全部结束。
# 现场（SDMUA-042 / SDMS-622）：airav ~2s 已回，iqqtv 却搜无结果/超时拖到 12~20s，
# 墙钟被最慢中文源钉死 → 「时快时慢 + 卡顿源」。预算覆盖 airav 常态回包，
# 超时后放行早停并取消在飞慢源（取消令牌），不再干等 iqqtv/avbase 顶满单源超时。
_CN_WAIT_BUDGET_SEC = 2.8


def _may_early_stop(
    detail: dict[str, Any] | None,
    gaps: list[str] | None,
    *,
    code: str,
    batch: list[dict[str, Any]],
    finished: set[str],
    meta_wait: dict[str, float] | None = None,
) -> bool:
    """缺口齐了才可早停；缺标题/剧情时**有界**等中文源；元数据未齐时**有界**等 DMM/MGS 等。

    meta_wait：本番号的等待状态（调用方持有，跨多次调用累计）。
    键：`since`/`logged`（元数据）、`cn_since`/`cn_logged`（中文源）。
    传 `None` = 旧行为（无限等），便于 A/B 与反证；生产路径必须传。
    """
    import app.scrape.source_catalog as catalog

    if not _detail_satisfies_gaps(detail, gaps, code=code):
        return False
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    # 中文源等待集合。`no_zh_title` 与 `thin_title` 是**同一诉求的两种表述**
    # （标题还没有中文），必须一起处理 —— 第二十一轮修正前它缺席此集合，
    # 却又被 `_detail_satisfies_gaps` 当硬闸门，于是这些番号既不享受
    # 「中文源跑完就放行」，也不被允许早停，只能活活等到全部源超时。
    need_zh = bool(gap_set & {"thin_title", "no_plot", "no_zh_title"})
    if need_zh and detail:
        title_ok = True
        plot_ok = True
        if "thin_title" in gap_set:
            title_ok = _zh_prefer_bonus(str(detail.get("title") or "")) > 0
        if "no_zh_title" in gap_set:
            title_ok = title_ok and not _title_lacks_zh(
                str(detail.get("title") or ""), code
            )
        if "no_plot" in gap_set:
            plot_ok = _zh_prefer_bonus(str(detail.get("overview") or "")) > 0
        if not (title_ok and plot_ok):
            pending = _cn_text_ids_in_batch(batch) - finished
            if pending:
                if meta_wait is None:
                    return False
                now = time.monotonic()
                since = meta_wait.get("cn_since")
                if since is None:
                    meta_wait["cn_since"] = now
                    return False
                if (now - float(since)) < _CN_WAIT_BUDGET_SEC:
                    return False
                if not meta_wait.get("cn_logged"):
                    meta_wait["cn_logged"] = 1.0
                    log.info(
                        "enrich %s cn-wait budget %.1fs expired, early-stop "
                        "pending_cn=%s (中文标题/剧情可能本就缺失)",
                        code,
                        _CN_WAIT_BUDGET_SEC,
                        ",".join(sorted(pending)),
                    )
    # 主缺口已齐，但系列/发行/官网仍缺：若本批还有元数据源未回，**在预算内**继续等。
    # 预算用尽即放行早停 —— 否则「本来就没有系列」的番号会永远等不到早停。
    if _detail_meta_incomplete(detail):
        pending_meta: set[str] = set()
        for src in batch:
            sid = catalog.canonicalize_id(str(src.get("id") or ""))
            if not sid or sid in finished:
                continue
            if sid in _META_FILL_SOURCE_IDS:
                pending_meta.add(sid)
        if pending_meta:
            if meta_wait is None:
                return False
            now = time.monotonic()
            since = meta_wait.get("since")
            if since is None:
                # 第一次需要等：起表，先让快源（dmm/libredmm）把窗口用起来
                meta_wait["since"] = now
                return False
            if (now - float(since)) < _META_WAIT_BUDGET_SEC:
                return False
            if not meta_wait.get("logged"):
                meta_wait["logged"] = 1.0
                log.info(
                    "enrich %s meta-wait budget %.1fs expired, early-stop "
                    "pending_meta=%s (series/publisher/website 可能本就缺失)",
                    code,
                    _META_WAIT_BUDGET_SEC,
                    ",".join(sorted(pending_meta)),
                )
    return True


def _gaps_likely_ready(
    got: dict[str, dict[str, Any]],
    gaps: list[str] | None,
    *,
    code: str = "",
) -> bool:
    """早停廉价闸：跨源 OR 字段是否已可能齐，未齐则跳过整次 `_merge_got`。"""
    if not got:
        return False
    gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
    details = list(got.values())
    if not gap_set:
        return any(
            _detail_has_poster(d) and _detail_has_actors(d) for d in details
        ) or (
            any(_detail_has_poster(d) for d in details)
            and any(_detail_has_actors(d) for d in details)
        )
    if ("no_local" in gap_set or "no_media" in gap_set) and not any(
        _detail_has_poster(d, strict=True) for d in details
    ):
        return False
    if "no_actress" in gap_set and not any(_detail_has_actors(d) for d in details):
        return False
    if "no_studio" in gap_set and not any(
        str(d.get("studio") or d.get("maker") or "").strip() for d in details
    ):
        return False
    if "no_plot" in gap_set and not any(
        len(str(d.get("overview") or "").strip()) >= 12 for d in details
    ):
        return False
    if "thin_title" in gap_set and not any(
        not _title_is_thin(str(d.get("title") or ""), code or str(d.get("code") or ""))
        for d in details
    ):
        return False
    return True


def _fetch_detail(
    code: str,
    *,
    region: str = "",
    wait_all: bool = False,
    gaps: list[str] | None = None,
    adaptive_first: bool = False,
    fast_zh: bool = False,
) -> dict[str, Any] | None:
    """对匹配且已启用的数据源按策略并发拉详情，再按字段可信度合并最优。

    wait_all=True：不按缺口早停（极少用）。
    gaps：缺口字段齐了才允许早停。
    adaptive_first=True：强制先跑自适应源，缺口未齐再跑过盾（详情单刷）。
    fast_zh=True：批量刮削用机翻短超时，避免 LLM 拖死番号槽。
    """
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    import app.scrap_library.enrich_strategy as strat
    import app.scrape.sources_settings as scrape_src
    from app.scrape_details import fetch_detail_for_source

    code_u = str(code or "").strip().upper()
    if not code_u:
        return None
    sources = _detail_sources(region=region, code=code_u)
    if not sources:
        log.info(
            "enrich: no enabled sources for region=%r groups=%s",
            region,
            scrape_src.enrich_groups_for_region(region),
        )
        return None

    cfg = strat.get_strategy()
    mode = str(cfg.get("mode") or "adaptive_first")
    if adaptive_first and mode == "parallel_all":
        mode = "adaptive_first"
    include_flare = bool(cfg.get("includeFlare", True))
    adapt_cfg = int(cfg.get("adaptiveWorkers") if cfg.get("adaptiveWorkers") is not None else 0)
    flare_cfg = int(cfg.get("flareWorkers") if cfg.get("flareWorkers") is not None else 0)
    timeout_sec = int(cfg.get("perSourceTimeoutSec") or 28)
    timeout_sec = max(5, min(180, timeout_sec))
    # 过盾/已知慢源单独封顶，避免拖死番号槽
    flare_timeout_cap = min(18, timeout_sec)
    # 勿每条都推「单源超时」——易被误认为真超时刷屏；只打一次 info
    log.info(
        "enrich %s perSourceTimeout=%ss flareCap=%ss",
        code_u,
        timeout_sec,
        flare_timeout_cap,
    )

    adaptive = [s for s in sources if str(s.get("access") or "") != "proxy_flare"]
    flare = [s for s in sources if str(s.get("access") or "") == "proxy_flare"]
    if not include_flare or mode == "adaptive_only":
        flare = []

    adapt_n = strat.resolve_pool_workers(adapt_cfg, len(adaptive))
    flare_n = strat.resolve_pool_workers(flare_cfg, len(flare)) if flare else 0
    from app.core.container_budget import cap_parallel as _cap_parallel

    if adapt_n:
        adapt_n = _cap_parallel(
            min(adapt_n, int(_SOURCE_WORKERS_MAX)),
            tight=4,
            small=8,
            hard=int(_SOURCE_WORKERS_MAX),
        )
    if flare_n:
        flare_n = _cap_parallel(
            min(flare_n, int(_SOURCE_WORKERS_MAX)),
            tight=2,
            small=4,
            hard=int(_SOURCE_WORKERS_MAX),
        )
    # 对齐 mdc-ng：单番号匹配源全开并发；出站压力交给 host/global 调度，
    # 不再因 itemWorkers 把单条压成 3 路（否则墙钟≈慢源串行、越跑越像超时）。

    if mode == "adaptive_only":
        pools = [("adaptive", adaptive, adapt_n)]
    elif mode == "adaptive_first":
        pools = [("adaptive", adaptive, adapt_n), ("flare", flare, flare_n)]
    else:
        # parallel_all：该番号匹配源一起并发；adaptiveWorkers=0 则全开
        all_batch = adaptive + flare
        all_n = strat.resolve_pool_workers(adapt_cfg, len(all_batch))
        from app.core.container_budget import cap_parallel as _cap_parallel

        all_n = (
            _cap_parallel(
                min(all_n, int(_SOURCE_WORKERS_MAX)),
                tight=4,
                small=8,
                hard=int(_SOURCE_WORKERS_MAX),
            )
            if all_n
            else 0
        )
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
        try:
            enrich_mon.touch_sources(code=code_u, sources=rows)
            notify_enrich_watchers()
        except Exception:  # noqa: BLE001
            pass

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
        kind: str = "",
        wait_ms: float = 0.0,
    ) -> None:
        row = {
            "id": sid,
            "access": access,
            "ms": int(round(ms)),
            # 等出站槽毫秒（第十一轮）：把「排队」从总耗时里显式分出来，
            # 生产上可直接看排队分布 —— 判断「最坏 2× 单源预算」到底是常态还是尾巴。
            "waitMs": int(round(max(0.0, float(wait_ms or 0.0)))),
            "ok": bool(ok),
            "error": (err or "")[:120],
            "actors": int(actors),
            "poster": bool(has_poster),
            "status": "done" if ok else "fail",
            # miss（源没这条番号）/ down（源不可用）/ busy（我们没轮到）/ cancelled（主动放弃）：
            # 只有 down / busy 会让整条番号进入「补抓」提示，见 _finish_one。
            "kind": kind or ("hit" if ok else ""),
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

    # 本番号本轮 fetch 的取消令牌：早停/暂停后置位，让被放弃的在飞源
    # 立刻从出站等槽队列里退出（详见 _run_pool）。
    _fetch_ctx: dict[str, Any] = {"cancel": None}
    # 本番号的「元数据有界等待」状态（详见 _META_WAIT_BUDGET_SEC）。
    # 必须跨多次 `_may_early_stop` 调用累计，所以放在本函数作用域而非函数内部。
    _meta_wait: dict[str, float] = {}

    def _one(src: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str, str]:
        import app.core.outbound_http as outbound_http

        sid = str(src.get("id") or "")
        access = str(src.get("access") or "")
        # 过盾源用更短超时，减轻单番号槽位被盾站占满
        src_timeout = float(timeout_sec)
        if access == "proxy_flare":
            src_timeout = float(min(flare_timeout_cap, timeout_sec))
        # iqqtv 曾双页串行易顶满预算；即便已改中文优先，仍略收紧工作超时，
        # 让放弃后的 curl 僵尸更快释放 page 槽。
        if sid == "iqqtv":
            src_timeout = float(min(src_timeout, 12.0))
        t0 = time.perf_counter()
        if _source_in_cooldown(sid):
            # ⚠️ 用**独立 kind**，不能记成 busy。
            # `busy` 的既定语义是「**我们这边**没轮到发请求（出站槽/限速/退避/过盾通道排满）」，
            # 因此**不计入源健康度**；而 cooldown 恰恰是 `_note_source_fetch_outcome`
            # 依据 down 连击算出来的**源健康度**结论（见其 docstring）。
            # 混用会让 `sourcesBusy` 把「源不健康被主动跳过」报成「排队未及」，
            # 前端/诊断读到的原因与事实相反（第十七轮 D3）。
            # 待遇与 down 一致：仍要补抓（进 degradedByDown），但不重复计 streak。
            err_c = "cooldown:源暂避"
            _record_timing(
                sid=sid,
                access=access,
                ms=0,
                ok=False,
                err=err_c,
                kind="cooldown",
            )
            return sid, None, err_c, "cooldown"
        try:
            applied = scrape_src.apply_provider_link_for_fetch(sid)
        except Exception as e:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000
            _record_timing(
                sid=sid, access=access, ms=ms, ok=False, err=f"link:{e}", kind="down"
            )
            _note_source_fetch_outcome(sid, kind="down")
            return sid, None, f"link:{e}", "down"

        # 本源等槽记账：由 fetch 线程写、本线程（池线程）读 —— 用「墙钟 − 等槽」
        # 判断真超时，别把「排队等出站槽」算成源超时。
        meter = outbound_http.new_slot_wait_meter()
        # 等槽预算与工作预算解耦（详见 outbound_http.source_queue_budget）
        queue_budget = float(outbound_http.source_queue_budget(src_timeout))
        # 本源专属取消令牌：放弃后立刻把僵尸线程从等槽队列里摘出来，
        # 不牵连同池其它源（池级令牌见 _fetch_ctx）。
        src_cancel = threading.Event()
        cancel_pair = _CancelPair(_fetch_ctx.get("cancel"), src_cancel)

        holder: dict[str, Any] = {}

        def _run_fetch() -> None:
            # TLS 必须在真正发请求的线程里设置
            # adaptive_first：自适应源只直连；过盾留给 flare 池，避免 curl→FS 回落占满单飞
            allow_flare = bool(include_flare)
            if mode == "adaptive_first" and access != "proxy_flare":
                allow_flare = False
            elif mode == "adaptive_only":
                allow_flare = False
            outbound_http.set_thread_allow_flare(allow_flare)
            outbound_http.set_thread_request_timeout(float(src_timeout))
            # 绑定取消令牌：置位后出站调度器不再为这个已放弃的源发请求
            outbound_http.set_thread_cancel_event(cancel_pair)
            outbound_http.set_thread_slot_meter(meter)
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
                outbound_http.set_thread_cancel_event(None)
                outbound_http.set_thread_slot_meter(None)

        _upsert_timing(
            {
                "id": sid,
                "access": access,
                "ms": 0,
                "waitMs": 0,
                "ok": False,
                "error": "",
                "actors": 0,
                "poster": False,
                "status": "running",
            }
        )
        th = threading.Thread(
            target=_run_fetch,
            name=f"enrich-src-{sid}",
            daemon=True,
        )
        th.start()
        # 放弃判据（第十轮）：用**工作耗时**而不是墙钟。
        #   工作耗时 = 墙钟 − 等出站槽时间（SlotWaitMeter 记账）
        #   ① 工作耗时 ≥ 单源预算 → down（源真的慢/挂）
        #   ② 墙钟 ≥ 单源预算 + 排队预算 → busy（始终没轮到发请求）
        # 只调大 join 超时是把「假超时」变成「假成功」，所以这里必须记账后判定。
        give_up = ""
        while th.is_alive():
            th.join(timeout=_SRC_GIVEUP_POLL_SEC)
            if not th.is_alive():
                break
            give_up = _src_give_up_reason(
                elapsed=time.perf_counter() - t0,
                waited=float(meter.wait_now()),
                work_budget=src_timeout,
                queue_budget=queue_budget,
            )
            if give_up:
                break
        ms = (time.perf_counter() - t0) * 1000
        applied_access = str(applied.get("access") or access)

        if give_up:
            # 丢弃该源结果（后台线程可能仍在跑，但合并不再采纳）；
            # 置本源令牌 → 它若还在等槽会在 ≤0.2s 内退出，不再占槽/发无用请求。
            src_cancel.set()
            # 分类：早停被主动放弃 ≠ 源故障；「从没拿到过槽」= 没轮到（详见 _give_up_kind）
            t_kind = _give_up_kind(
                give_up=give_up,
                acquired=int(meter.acquired),
                cancelled=_is_cancelled(),
            )
            if t_kind == "busy":
                err_t = f"busy:排队未及 {int(ms)}ms"
            else:
                err_t = f"timeout:{int(src_timeout)}s"
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=err_t,
                kind=t_kind,
                wait_ms=float(meter.wait_now()) * 1000,
            )
            _note_source_fetch_outcome(sid, kind=t_kind)
            return sid, None, err_t, t_kind

        err_obj = holder.get("error")
        if err_obj is not None:
            if isinstance(err_obj, HTTPException):
                err_s = str(err_obj.detail)
            else:
                err_s = str(err_obj)
            err_kind = _refine_kind_with_meter(
                _classify_source_failure(err_obj),
                slot_timeout=int(getattr(meter, "slot_timeout", 0)),
            )
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=err_s,
                kind=err_kind,
                wait_ms=float(meter.wait_now()) * 1000,
            )
            _note_source_fetch_outcome(sid, kind=err_kind)
            return sid, None, err_s, err_kind

        detail = holder.get("detail")
        if not _detail_usable(detail, code=code_u):
            title = str((detail or {}).get("title") or "")[:40]
            err_r = f"rejected:{title}"
            miss_kind = _refine_kind_with_meter(
                "miss", slot_timeout=int(getattr(meter, "slot_timeout", 0))
            )
            _record_timing(
                sid=sid,
                access=applied_access,
                ms=ms,
                ok=False,
                err=err_r,
                # 源正常响应、只是没有这条番号（或返回了别的番号的页面）→ miss，不必补抓；
                # 但若本次出站排到过超时（痕迹在记账里），「未找到」可能是被吞掉的 busy。
                kind=miss_kind,
                wait_ms=float(meter.wait_now()) * 1000,
            )
            _note_source_fetch_outcome(sid, kind=miss_kind)
            return sid, None, err_r, "miss"
        detail = dict(detail)
        try:
            from app.scrape.metadata_optimize import polish_actress_names
            from app.scrap_library.enrich_strategy import local_map_mode

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
                _clean_actors(detail.get("actors")),
                exclude=directors,
                enable_mapping=local_map_mode("actors") != "off",
            )
            detail["_actorsPolished"] = True
        except Exception:  # noqa: BLE001
            detail["actors"] = _clean_actors(detail.get("actors"))
            detail["_actorsPolished"] = False
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
            kind="hit",
            wait_ms=float(meter.wait_now()) * 1000,
        )
        _note_source_fetch_outcome(sid, kind="hit")
        return sid, detail, "", "hit"

    def _run_pool(
        label: str, batch: list[dict[str, Any]], workers: int
    ) -> tuple[
        dict[str, dict[str, Any]],
        list[str],
        set[str],
        set[str],
        set[str],
        set[str],
    ]:
        """返回 (命中详情, 错误串, down 源, miss 源, busy 源, cooldown 源)。

        后四者把「源挂了」「源没这条番号」「我们没轮到」「源不健康被主动暂避」
        分开，别混：
          - down / busy / **cooldown** → 补抓需要（cooldown 是源健康度结论，
            下轮可能已恢复；且进 `degradedByDown` 才会被回头修）
          - miss / cancelled → 不需要补抓（重抓只白占出站槽）
        ⚠️ cooldown 单列的理由见 `_one` 里冷却分支的注释：busy 不算健康度，
        cooldown 算，混用会把「源不健康」报成「排队未及」。
        """
        if not batch or workers <= 0:
            return {}, [], set(), set(), set(), set()
        got: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        down_ids: set[str] = set()
        miss_ids: set[str] = set()
        busy_ids: set[str] = set()
        cooldown_ids: set[str] = set()
        finished: set[str] = set()
        # 每池独立令牌：adaptive 池收尾时置位，只回收本池被放弃的在飞源，
        # 不误伤随后的 flare 池（两池串行，见 _fetch_detail 的 pools）
        cancel_ev = threading.Event()
        _fetch_ctx["cancel"] = cancel_ev
        ordered = _prioritize_batch_for_gaps(batch, gaps, region=region)
        # 对齐 mdc-ng：匹配源一次全开并发；workers=配置上限（0→全开）
        n = max(1, min(workers, len(ordered)))
        pool = ThreadPoolExecutor(
            max_workers=n, thread_name_prefix=f"enrich-{label}"
        )
        futs = {pool.submit(_one, src): src for src in ordered}
        early = False
        probe_keys: frozenset[str] | None = None
        probe_merged: dict[str, Any] | None = None
        gap_set = {str(g).strip() for g in (gaps or []) if str(g).strip()}
        need_zh = bool(gap_set & {"thin_title", "no_plot", "no_zh_title"})
        _push_log(
            f"开跑 · {label} ×{len(ordered)} · workers={n} · 全开并发"
        )
        try:
            pending = set(futs.keys())
            while pending:
                # 暂停/停止：立刻收手，别再为已无意义的番号占出站槽
                if _is_cancelled():
                    log.info(
                        "enrich %s halt-abandon pool=%s inflight=%s",
                        code_u,
                        label,
                        len(pending),
                    )
                    break
                done_set, pending = wait(
                    pending,
                    timeout=0.5,
                    return_when=FIRST_COMPLETED,
                )
                if not done_set:
                    continue
                for fut in done_set:
                    try:
                        sid, detail, err, kind = fut.result(timeout=0.1)
                    except Exception as e:  # noqa: BLE001
                        errors.append(str(e))
                        continue
                    if sid:
                        finished.add(str(sid))
                    if detail:
                        got[sid] = detail
                        if not wait_all and _gaps_likely_ready(
                            got, gaps, code=code_u
                        ):
                            if need_zh:
                                # 与 `_may_early_stop` 的 need_zh 集合同源：
                                # `no_zh_title` 同样表示「标题还没有中文」，也要等中文源
                                title_need = bool(
                                    gap_set & {"thin_title", "no_zh_title"}
                                )
                                plot_need = "no_plot" in gap_set
                                zh_ready = (
                                    not title_need or _got_has_zh_title(got)
                                ) and (not plot_need or _got_has_zh_plot(got))
                                cn_pending = (
                                    _cn_text_ids_in_batch(ordered) - finished
                                )
                                # 有界等中文源：预算内才跳过早停探测。
                                # 否则 iqqtv「搜索无结果」12~20s 会钉死墙钟。
                                if not zh_ready and cn_pending:
                                    now_cn = time.monotonic()
                                    if _meta_wait.get("cn_since") is None:
                                        _meta_wait["cn_since"] = now_cn
                                    if (
                                        now_cn - float(_meta_wait["cn_since"])
                                    ) < _CN_WAIT_BUDGET_SEC:
                                        continue
                            keys_now = frozenset(got.keys())
                            if keys_now != probe_keys:
                                probe_merged = _merge_got(
                                    ordered, got, region=region, probe=True
                                )
                                probe_keys = keys_now
                            if probe_merged and _may_early_stop(
                                probe_merged,
                                gaps,
                                code=code_u,
                                batch=ordered,
                                finished=finished,
                                meta_wait=_meta_wait,
                            ):
                                early = True
                                log.info(
                                    "enrich %s early-stop pool=%s hits=%s gaps=%s",
                                    code_u,
                                    label,
                                    ",".join(got.keys()),
                                    ",".join(gaps or []) or "-",
                                )
                                abandoned = max(
                                    0, len(futs) - len(finished)
                                )
                                _push_log(
                                    f"早停 · {label} · 已齐 gaps={','.join(gaps or []) or '-'} · "
                                    f"命中 {','.join(got.keys())}"
                                    + (
                                        f" · 放弃在飞 {abandoned}（取消令牌，不再占用出站槽）"
                                        if abandoned
                                        else ""
                                    )
                                )
                                break
                    elif err:
                        errors.append(f"{sid}:{err}")
                        # 只有「源不可用 / 我们没轮到」才值得补抓：miss 是源侧确实
                        # 没这条番号，重抓只会白占出站槽（这就是「高优先源抖动 →
                        # 静默降级」的判别点）；busy 是出站槽/限速/过盾通道排满，
                        # 源没坏，但本轮确实没拿到 → 也要补，否则降级取值没人回头修。
                        if kind == "down" and sid:
                            down_ids.add(str(sid))
                        elif kind == "miss" and sid:
                            miss_ids.add(str(sid))
                        elif kind == "busy" and sid:
                            busy_ids.add(str(sid))
                        elif kind == "cooldown" and sid:
                            cooldown_ids.add(str(sid))
                if early:
                    break
        finally:
            # 关键顺序：先置取消令牌，再放池。
            # 被放弃的在飞源此前会堵在出站信号量上，等到槽位后仍会真发一次请求
            # （≤单源超时），把 page 全局槽（默认 20）从活番号手里抢走 ——
            # itemWorkers×源数 可达 100 路，这就是「越刮越慢 + 假超时」的来源。
            # 置位后它们在 ≤0.2s 内抛 OutboundCancelled 退出，不占槽、不发请求。
            cancel_ev.set()
            if _fetch_ctx.get("cancel") is cancel_ev:
                _fetch_ctx["cancel"] = None
            for f in futs:
                f.cancel()
            # 不等剩余慢请求；池线程随后自行结束（已无出站占用）
            pool.shutdown(wait=False, cancel_futures=True)
            if early:
                _mark_pending_skipped("早停跳过")
        if early:
            errors = [e for e in errors if "cancelled" not in e.lower()]
        return got, errors, down_ids, miss_ids, busy_ids, cooldown_ids

    got_all: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    down_all: set[str] = set()
    busy_all: set[str] = set()
    miss_all: set[str] = set()
    cooldown_all: set[str] = set()
    for label, batch, workers in pools:
        if not batch:
            continue
        # adaptive_first：本条缺口已齐再跳过 Flare（标题/剧情未拿中文时仍进过盾池）
        if (
            mode == "adaptive_first"
            and label == "flare"
            and _may_early_stop(
                _merge_got(sources, got_all, region=region, probe=True),
                gaps,
                code=code_u,
                batch=batch,
                finished=set(got_all.keys()),
                meta_wait=_meta_wait,
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
        part, errs, part_down, part_miss, part_busy, part_cooldown = _run_pool(
            label, batch, workers
        )
        got_all.update(part)
        errors.extend(errs)
        down_all |= part_down
        miss_all |= part_miss
        busy_all |= part_busy
        cooldown_all |= part_cooldown

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

    try:
        enrich_mon.set_phase(code=code_u, phase="write")
        enrich_mon.touch_sources(code=code_u, sources=_timings_snapshot())
        notify_enrich_watchers()
    except Exception:  # noqa: BLE001
        pass
    t_merge0 = time.perf_counter()
    merged = _merge_got(sources, got_all, region=region)
    if merged is None:
        return None
    merge_ms = int(round((time.perf_counter() - t_merge0) * 1000))
    try:
        enrich_mon.touch_sources(code=code_u, sources=_timings_snapshot())
        notify_enrich_watchers()
    except Exception:  # noqa: BLE001
        pass
    # 批量：跳过串行译文（机翻/LLM 可占 10–30s+ 番号槽）；中文靠源站合并+映射
    # 单刷/覆盖：可走 LLM 补中文
    if not fast_zh:
        merged = _maybe_llm_fill_zh(merged) or merged
        try:
            enrich_mon.touch_sources(code=code_u, sources=_timings_snapshot())
            notify_enrich_watchers()
        except Exception:  # noqa: BLE001
            pass
        # LLM 可能改写标题/剧情：映射表再盖一次（对齐 MDCX：映射在译后仍以表为准）
        merged = (
            _apply_mdcx_maps(
                merged, code=str(merged.get("code") or code_u or "")
            )
            or merged
        )
    merged["sourceTimings"] = timings_sorted
    merged["fetchMs"] = fetch_ms
    merged["mergeMs"] = merge_ms
    # ⚠️ 「源挂了 / 我们没轮到」≠「源没有这条番号」：只有前者才值得补抓。
    # 判据：某个**没拿到**的源（down 故障 / busy 排队未及 / cooldown 源不健康被暂避）
    # 在优先级上高于所有命中源 → 本轮属于「降级取值」（高优先源抖动/被排队挤掉/
    # 被冷却跳过，结果来自更低优先的源），该番号进补抓提示；若只是尾部低优先源
    # 抖动而头部源已命中，则不打扰（否则会大面积误入重试队列）。
    # cooldown 必须并进来：它和 down 同源（由 down 连击触发），漏掉就没人回头补。
    _prio = {str(s.get("id") or ""): i for i, s in enumerate(sources)}
    _hit_ids = {str(k) for k in got_all.keys()}
    _best_hit = min((_prio.get(i, len(sources)) for i in _hit_ids), default=None)
    degraded_by_down: list[str] = []
    if _best_hit is not None:
        degraded_by_down = sorted(
            sid
            for sid in (down_all | busy_all | cooldown_all)
            if _prio.get(sid, len(sources)) < _best_hit
        )
    merged["sourcesDown"] = sorted(str(x) for x in down_all)
    merged["sourcesBusy"] = sorted(str(x) for x in busy_all)
    merged["sourcesCooldown"] = sorted(str(x) for x in cooldown_all)
    merged["sourcesMiss"] = sorted(str(x) for x in miss_all)
    merged["degradedByDown"] = degraded_by_down
    if degraded_by_down:
        log.info(
            "enrich %s degraded hit=%s down=%s busy=%s cooldown=%s",
            code_u,
            ",".join(sorted(_hit_ids)),
            ",".join(sorted(down_all)),
            ",".join(sorted(busy_all)),
            ",".join(sorted(cooldown_all)),
        )
        _push_log(
            f"降级取值 · 高优先源未拿到 {','.join(degraded_by_down)} · "
            f"命中 {','.join(sorted(_hit_ids)) or '-'}",
            region=region,
        )
    log.info(
        "enrich detail %s mode=%s ok=%s/%s hits=%s fetch=%sms merge=%sms top=%s llm=%s fast_zh=%s",
        code_u,
        mode,
        len(got_all),
        len(sources),
        ",".join(str(x) for x in (merged.get("resolvedSources") or [])[:8]),
        fetch_ms,
        merge_ms,
        ",".join(f"{r['id']}:{r['ms']}" for r in timings_sorted[:5]),
        ",".join(merged.get("llmTranslated") or []) or "-",
        bool(fast_zh),
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


# 番号目录旁路：{CODE}.log（JSON）；兼容旧名 enrich.log
_ENRICH_SIDECAR_LEGACY = "enrich.log"
_ENRICH_SIDECAR_VER = 1


def _enrich_sidecar_code(folder: Path, code: str = "") -> str:
    raw = str(code or "").strip().upper()
    if not raw:
        raw = str(folder.name or "").strip().upper()
    # 文件名安全：去掉路径分隔等
    for ch in ("/", "\\", ":", "*", "?", '"', "<", ">", "|"):
        raw = raw.replace(ch, "_")
    return raw


def _enrich_sidecar_path(folder: Path, code: str = "") -> Path:
    name = _enrich_sidecar_code(folder, code)
    if name:
        return folder / f"{name}.log"
    return folder / _ENRICH_SIDECAR_LEGACY


def write_enrich_sidecar(folder: Path, payload: dict[str, Any]) -> bool:
    """刮削结果写入番号目录 {CODE}.log（JSON）。"""
    if not folder or not isinstance(payload, dict):
        return False
    try:
        if not folder.is_dir():
            return False
    except OSError:
        return False
    timings = list(payload.get("sourceTimings") or [])
    fields = list(payload.get("fields") or [])
    if not timings and not fields:
        return False
    code_u = _enrich_sidecar_code(folder, str(payload.get("code") or ""))
    body = {
        "v": _ENRICH_SIDECAR_VER,
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "code": code_u,
        "source": str(payload.get("source") or "").strip(),
        "error": str(payload.get("error") or "")[:500],
        "partialOk": bool(payload.get("partialOk")),
        "status": str(payload.get("status") or "").strip(),
        "gapsAfter": list(payload.get("gapsAfter") or payload.get("gaps") or []),
        "fields": fields,
        "sourceTimings": timings,
        "detailTitle": str(payload.get("detailTitle") or "")[:300],
        "posterDownloaded": payload.get("posterDownloaded"),
        "vectorSynced": payload.get("vectorSynced"),
        "vectorSkipped": payload.get("vectorSkipped"),
        "coverMs": payload.get("coverMs"),
        "actressMs": payload.get("actressMs"),
        "vectorMs": payload.get("vectorMs"),
        "fetchMs": payload.get("fetchMs"),
        "totalMs": payload.get("totalMs"),
    }
    path = _enrich_sidecar_path(folder, code_u)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        raw = json.dumps(body, ensure_ascii=False, indent=2)
        tmp.write_text(raw, encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("write enrich sidecar failed %s: %s", path, e)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def read_enrich_sidecar(
    folder: Path, *, code: str = ""
) -> dict[str, Any] | None:
    """读取番号目录 {CODE}.log；兼容 enrich.log。损坏/缺失返回 None。"""
    if not folder:
        return None
    code_u = _enrich_sidecar_code(folder, code)
    candidates: list[Path] = []
    if code_u:
        candidates.append(folder / f"{code_u}.log")
        # 大小写变体：目录名可能是 SONE-999
        folder_name = str(folder.name or "").strip()
        if folder_name and folder_name.upper() != code_u:
            candidates.append(folder / f"{folder_name}.log")
    candidates.append(folder / _ENRICH_SIDECAR_LEGACY)
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict):
            return data
    return None


def _merge_enrich_sidecar_into_item(
    item: dict[str, Any],
    *,
    folder: Path | None = None,
    region: str = "",
) -> dict[str, Any]:
    """把本地 {CODE}.log 合并进队列行（不覆盖已有源耗时）。"""
    if not isinstance(item, dict):
        return item
    has_timings = isinstance(item.get("sourceTimings"), list) and bool(
        item.get("sourceTimings")
    )
    has_src_fields = isinstance(item.get("fields"), list) and any(
        isinstance(f, dict) and str(f.get("source") or "").strip()
        for f in (item.get("fields") or [])
    )
    if has_timings and has_src_fields:
        return item

    fol = folder
    if fol is None:
        fol = _resolve_enrich_folder(
            region=region or str(item.get("region") or ""),
            code=str(item.get("code") or ""),
            item_id=str(
                item.get("itemId")
                or item.get("relPath")
                or item.get("rel_path")
                or ""
            ),
        )
    if fol is None:
        return item
    data = read_enrich_sidecar(fol, code=str(item.get("code") or ""))
    if not data:
        return item

    if not has_timings and isinstance(data.get("sourceTimings"), list):
        item["sourceTimings"] = list(data.get("sourceTimings") or [])
    if not item.get("fields") and isinstance(data.get("fields"), list):
        item["fields"] = list(data.get("fields") or [])
    elif (
        not has_src_fields
        and isinstance(data.get("fields"), list)
        and data.get("fields")
    ):
        item["fields"] = list(data.get("fields") or [])

    src = str(item.get("source") or "").strip()
    side_src = str(data.get("source") or "").strip()
    if side_src and (not src or src in {"local_scan", "log_recover", "recover"}):
        item["source"] = side_src

    if not str(item.get("detailTitle") or "").strip():
        title = str(data.get("detailTitle") or "").strip()
        if title:
            item["detailTitle"] = title[:300]

    for k in (
        "posterDownloaded",
        "vectorSynced",
        "vectorSkipped",
        "coverMs",
        "actressMs",
        "vectorMs",
        "fetchMs",
        "totalMs",
        "partialOk",
    ):
        if item.get(k) is None and data.get(k) is not None:
            item[k] = data.get(k)

    if data.get("gapsAfter") and not item.get("gapsAfter"):
        item["gapsAfter"] = list(data.get("gapsAfter") or [])
    return item


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
    nfo_path: Path,
    detail: dict[str, Any],
    *,
    overwrite: bool = False,
    force_fields: set[str] | None = None,
    existing_root: ET.Element | None = None,
    existing_fields: dict[str, Any] | None = None,
    old_bytes: bytes | None = None,
) -> bool:
    """增量仅补空；覆盖模式写入新值。最终按 MDCx 参考布局整文件重排写出。

    force_fields：增量下仍强制写回的字段名集合（title/overview/actors/…）。
    existing_root / existing_fields / old_bytes：调用方已读过文件时跳过二次解析。
    """
    if existing_fields is not None:
        fields = existing_fields
        if old_bytes is None:
            old_bytes = b""
    else:
        old_bytes = b"" if old_bytes is None else old_bytes
        root = existing_root
        if root is None:
            if nfo_path.is_file():
                try:
                    old_bytes = nfo_path.read_bytes()
                    root = ET.fromstring(
                        old_bytes.decode("utf-8", errors="replace")
                    )
                except Exception:
                    root = ET.Element("movie")
            else:
                root = ET.Element("movie")
        if root.tag.lower() != "movie":
            movie = root.find("movie")
            root = movie if movie is not None else ET.Element("movie")
        code_pre = str(detail.get("code") or detail.get("id") or "").strip().upper()
        fields = fields_from_movie_root(root, code_fallback=code_pre)

    force = bool(overwrite)
    ff = {str(x).strip().lower() for x in (force_fields or set()) if str(x).strip()}

    def _force(*keys: str) -> bool:
        return force or any(k in ff for k in keys)

    def _put(key: str, value: str, *, do_force: bool) -> None:
        v = str(value or "").strip()
        if not v:
            return
        cur = str(fields.get(key) or "").strip()
        if cur and not do_force:
            return
        fields[key] = v

    code = str(detail.get("code") or detail.get("id") or "").strip().upper()
    if code:
        _put("num", code, do_force=force)

    title = str(detail.get("title") or "").strip()
    if title and title.upper() != code and not any(
        m in title.casefold() for m in (x.casefold() for x in _JUNK_TITLE_MARKERS)
    ):
        cur_title = str(fields.get("title") or "")
        force_title = _force("title") or _title_is_thin(cur_title, code)
        if title.strip() and not _title_is_thin(title, code):
            _put("title", title, do_force=force_title)

    studio = _polish_studio_name(
        str(detail.get("studio") or detail.get("maker") or "").strip()
    )
    if studio:
        _put("studio", studio, do_force=_force("studio"))
        _put("maker", studio, do_force=_force("studio"))

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
    if director:
        _put("director", director, do_force=force)

    runtime = str(detail.get("runtime") or "").strip()
    if runtime:
        _put("runtime", runtime, do_force=force)

    score = str(detail.get("score") or detail.get("rating") or "").strip()
    if score:
        _put("rating", score, do_force=force)
        # 派生分数字段随 rating 刷新
        if force or not str(fields.get("criticrating") or "").strip():
            fields["criticrating"] = ""
            fields["ratings_value"] = ""

    title_ja = str(detail.get("titleJa") or "").strip()
    if title_ja:
        _put("originaltitle", title_ja, do_force=_force("title"))
        if _force("title") or not str(fields.get("sorttitle") or "").strip():
            fields["sorttitle"] = title_ja

    overview_ja = str(detail.get("overviewJa") or "").strip()
    if overview_ja:
        _put("originalplot", overview_ja, do_force=_force("overview"))

    plot = str(detail.get("overview") or "").strip()
    if plot:
        _put("plot", plot, do_force=_force("overview"))
        _put("outline", plot, do_force=_force("overview"))
        if _force("overview") or not str(fields.get("originalplot") or "").strip():
            # 无日文剧情时用中文填 originalplot（参考库常三者同文）
            if not overview_ja:
                _put("originalplot", plot, do_force=_force("overview"))

    year = str(detail.get("year") or "").strip()
    if year:
        _put("year", year, do_force=force)
    date_s = str(detail.get("date") or "").strip()
    if date_s:
        _put("premiered", date_s, do_force=force)
        _put("releasedate", date_s, do_force=force)
        _put("release", date_s, do_force=force)
        if force or not str(fields.get("tagline") or "").strip():
            fields["tagline"] = f"发行日期: {date_s}"
        if not year and len(date_s) >= 4 and date_s[:4].isdigit():
            _put("year", date_s[:4], do_force=force)

    poster = str(detail.get("posterUrl") or detail.get("poster") or "").strip()
    if poster.startswith(("http://", "https://")):
        _put("cover", poster, do_force=_force("poster"))

    series = str(detail.get("series") or detail.get("set") or "").strip()
    if series:
        _put("series", series, do_force=force)
    publisher = str(
        detail.get("publisher") or detail.get("label") or ""
    ).strip()
    if publisher:
        _put("publisher", publisher, do_force=force)
        _put("label", publisher, do_force=force)
    trailer = str(
        detail.get("trailer") or detail.get("trailerUrl") or ""
    ).strip()
    if trailer:
        _put("trailer", trailer, do_force=force)
    website = str(detail.get("website") or detail.get("url") or "").strip()
    if website:
        _put("website", website, do_force=force)

    actors = _clean_actors(detail.get("actors"))
    actors_all = _clean_actors(detail.get("actorsAll"))
    if actors_all and not actors:
        actors = list(actors_all)
    # 禁止从 tags/标题硬套女优
    try:
        from app.scrape.metadata_optimize import polish_actress_names

        ban = [director] if director else []
        actors = polish_actress_names(actors, exclude=ban)
    except Exception:  # noqa: BLE001
        pass
    if _force("actors"):
        fields["actors"] = list(actors)
    elif actors:
        existing = [str(a).strip() for a in (fields.get("actors") or []) if str(a).strip()]
        # 已有 actor 也滤一遍垃圾标签
        existing = _clean_actors(existing)
        seen = {a.casefold() for a in existing}
        for a in actors:
            if a.casefold() not in seen:
                existing.append(a)
                seen.add(a.casefold())
        fields["actors"] = existing
    else:
        # 无真实女优：清掉历史上从标签写入的垃圾 <actor>
        existing = _clean_actors(
            [str(a).strip() for a in (fields.get("actors") or []) if str(a).strip()]
        )
        fields["actors"] = existing

    tags = _clean_tags(detail.get("tags"))
    # 已是女优的人名不再留在 genre
    act_fold = {
        str(a).casefold()
        for a in (fields.get("actors") or actors or [])
        if str(a).strip()
    }
    if act_fold:
        tags = [t for t in tags if t.casefold() not in act_fold]
    if _force("tags"):
        fields["genres"] = list(tags)
    elif tags:
        existing_g = [
            str(g).strip() for g in (fields.get("genres") or []) if str(g).strip()
        ]
        seen_g = {g.casefold() for g in existing_g}
        for t in tags:
            if t.casefold() not in seen_g and t.casefold() not in act_fold:
                existing_g.append(t)
                seen_g.add(t.casefold())
        fields["genres"] = existing_g

    # 默认图文件名（参考库固定）
    fields.setdefault("poster", "poster.jpg")
    fields.setdefault("thumb", "thumb.jpg")
    fields.setdefault("fanart", "fanart.jpg")
    fields.setdefault("countrycode", "JP")
    fields.setdefault("customrating", "JP-18+")
    fields.setdefault("mpaa", "JP-18+")

    if not str(fields.get("num") or "").strip() and not nfo_path.is_file():
        return False

    new_root = build_mdcx_nfo_root(fields)
    new_bytes = format_nfo_xml(new_root)
    if old_bytes and old_bytes == new_bytes:
        return False
    # 无旧文件且几乎空壳
    if not old_bytes and not str(fields.get("num") or "").strip():
        return False
    write_nfo(nfo_path, new_root)
    return True


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
    field_priority = list(_strategy_field_priority("poster", region=region) or [])
    region_sources = list(_strategy_region_sources(region, code=code_u) or [])

    def _log(msg: str) -> None:
        _push_log(msg, region=region)

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


# poster 校验结果缓存：(路径, mtime_ns, size) → 是否合格。
# 同一张 poster.jpg 在一次运行里会被反复校验（每条 item 3~4 次 + 纠偏扫描），
# 每次都要 stat + PIL 开图；按 mtime+size 做键，落盘覆盖后自然失效。
_poster_ok_cache: dict[tuple[str, int, int], bool] = {}


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
    if not _find_nfo(folder):
        return False
    return _local_poster_ok(folder)


_LOCAL_COVER_FILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("poster", ("poster.jpg", "poster.jpeg", "poster.png", "poster.webp")),
    ("thumb", ("thumb.jpg", "thumb.jpeg", "thumb.png", "thumb.webp")),
    ("fanart", ("fanart.jpg", "fanart.jpeg", "fanart.png", "fanart.webp")),
)


def _resolve_enrich_folder(
    *,
    region: str = "",
    code: str = "",
    item_id: str = "",
) -> Path | None:
    """只看刮削库磁盘：rel 路径 / 分区/厂牌/番号。"""
    settings = embed_svc.get_settings()
    root = embed_svc.resolve_root(settings.get("root")).resolve()
    rid = _queue_log_region(region)
    code_u = str(code or "").strip().upper()
    iid = str(item_id or "").replace("\\", "/").strip().strip("/")

    def _ok_dir(p: Path) -> Path | None:
        try:
            q = p.resolve()
            q.relative_to(root)
        except ValueError:
            return None
        return q if q.is_dir() else None

    # 队列 itemId 经常就是相对目录
    if iid:
        hit = _ok_dir(root / iid)
        if hit:
            return hit
        try:
            embed_svc.ensure_schema()
            pool = get_meta_pool()
            with pool.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT rel_path FROM {embed_svc.TABLE}
                    WHERE item_id = %s
                    LIMIT 1
                    """,
                    (iid,),
                )
                row = cur.fetchone()
            if row:
                rel = str(
                    (row.get("rel_path") if isinstance(row, dict) else row[0]) or ""
                ).replace("\\", "/").strip().strip("/")
                if rel:
                    hit = _ok_dir(root / rel)
                    if hit:
                        return hit
        except Exception:  # noqa: BLE001
            pass

    if not code_u:
        return None
    # FC2：前缀夹是 FC2 / FC2-PPV，不能用 split('-',1)（会把 FC2-PPV-x 拆成 FC2）
    rid_n = str(rid or region or "").strip().casefold()
    if rid_n in {"fc2", "fc2ppv"} or code_u.startswith("FC2"):
        from app.core.region_meta import fc2_fs_prefix, normalize_fc2_code

        code_n = normalize_fc2_code(code_u)
        pref = fc2_fs_prefix(code=code_n)
        for base in _region_local_dirs(root, rid or region):
            for cand in (
                base / pref / code_n,
                base / "FC2-PPV" / code_n,
                base / "FC2PPV" / code_n,
                base / "FC2" / code_n,
                base / code_n,
                base / code_u,
            ):
                hit = _ok_dir(cand)
                if hit:
                    return hit
        return None
    prefix = code_u.split("-", 1)[0] if "-" in code_u else code_u
    for base in _region_local_dirs(root, rid or region):
        for cand in (base / prefix / code_u, base / code_u):
            hit = _ok_dir(cand)
            if hit:
                return hit
    return None


def list_local_covers(
    *,
    region: str = "",
    code: str = "",
    item_id: str = "",
) -> dict[str, Any]:
    """检查用：只返回番号目录里已落盘的本地图。"""
    folder = _resolve_enrich_folder(region=region, code=code, item_id=item_id)
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
                            if len(qv) > 120:
                                qv = qv[:40] + qv[-80:]
                            _enrich_job["queue"] = qv
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
            _push_log(
                f"刮削已启动 · 队列 {len(queue)}（扫描继续）",
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
                if new_lid and not halted and not _queue_log_int_id(persist):
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
                "currentRegion": "",
                "cancel": False,
                "halt": None,
                "queue": seed_queue,
                "queueCounts": {
                    "pending": len(seed_queue),
                    "running": 0,
                    "done": 0,
                    "fail": 0,
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
