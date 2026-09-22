# -*- coding: utf-8 -*-
"""enrich_text —— 自 scrap_library/enrich.py 拆出（机械搬移，行为不变）。"""

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
import app.scrap_library.enrich_merge as _enrich_merge
from app.scrap_library.enrich import (_ACT_TAG_FRAG_RE, _JUNK_ACTORS, _JUNK_TAGS, _JUNK_TITLE_MARKERS, _TITLE_TAIL_NOISE, _TRAD_HINT_RE, _TRAILING_ALT_CODE_RE)


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


def _looks_like_act_tag_token(name: str) -> bool:
    """类型/玩法标签，不是女优名。"""
    t = str(name or "").strip()
    if not t:
        return False
    if t in _enrich._JUNK_ACTOR_TAGS or t.casefold() in _enrich._JUNK_ACTOR_TAGS:
        return True
    if _ACT_TAG_FRAG_RE.search(t):
        return True
    # 叠词玩法（イチャイチャ / モジモジ）
    if re.fullmatch(r"([ぁ-んァ-ン]{2,4})\1", t):
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
    if key in _JUNK_ACTORS or key in _enrich._JUNK_ACTOR_TAGS or t in _JUNK_TITLE_MARKERS:
        return False
    if any(s in t for s in _enrich._JUNK_ACTOR_SUBSTR):
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
    return _enrich._is_plausible_actress_name(t)


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
            if n in _enrich._JUNK_ACTOR_TAGS or n.casefold() in _enrich._JUNK_ACTOR_TAGS:
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


def _actors_lifted_from_tags(tags: list[str] | None) -> list[str]:
    """已废弃：禁止从标签升格女优（保留空实现，兼容旧调用/测试）。"""
    del tags
    return []


def _fold_tag_variant(tag: str) -> str:
    """繁/日 → 简 折叠（标签去重前统一字形，避免「穿衣幹砲」+「穿衣干炮」重复）。"""
    try:
        from app.scrape.metadata_optimize import _fold_variant

        return _fold_variant(tag)
    except Exception:  # noqa: BLE001
        return tag


def _fold(s: str) -> str:
    """`_fold_variant` + `casefold()`；映射表不可用时退化为普通 `casefold()`。

    女优名 / 标题片段的**同形比较**专用（`_title_actress_mismatch_penalty`、
    `_overview_foreign_actress_penalty`、锚点切换）。与 `_fold_tag_variant`
    的区别：那个失败时返回**原串**（标签展示用），本函数保证返回值一定
    可安全比较。原为四份逐字相同的嵌套实现，已收敛到这里。
    """
    try:
        from app.scrape.metadata_optimize import _fold_variant

        return _fold_variant(s).casefold()
    except Exception:  # noqa: BLE001
        return str(s or "").casefold()


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


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", str(text or "")))


def _has_kana(text: str) -> bool:
    """平假名 / 片假名 → 日文痕迹（忽略间隔号・･）。"""
    t = str(text or "").replace("・", "").replace("･", "")
    return bool(re.search(r"[\u3040-\u309f\u30a0-\u30ff]", t))


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
    if nm.casefold() in _enrich._JUNK_ACTOR_TAGS or nm in _enrich._JUNK_ACTOR_TAGS:
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
    if _enrich._title_is_thin(t, code):
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
    if not m or _enrich._title_is_thin(m, code):
        return False
    c = str(cur or "").strip()
    if not c or _enrich._title_is_thin(c, code):
        return True
    # 同一基准分，只比正文质量（不用 mdcx 的 78 底分压过源站）
    sc_c = _score_title(
        c, code=code, source_id="compare", allowed_actors=allowed_actors
    )
    sc_m = _score_title(
        m, code=code, source_id="compare", allowed_actors=allowed_actors
    )
    return sc_m > sc_c


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

    actors = _enrich._clean_actors(names)
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
    return catalog.field_trust(source_id, "poster") + _enrich_cover._poster_rank(u) * 12


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


def _prune_junk_actors(parent: ET.Element) -> bool:
    before: list[str] = []
    for a in parent.findall("actor"):
        nm = a.find("name")
        if nm is None:
            continue
        text = "".join(nm.itertext()).strip()
        if text:
            before.append(text)
    cleaned = _enrich._clean_actors(before)
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
    _enrich_merge._merge_actors(parent, names, max_n=max_n)
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
    _enrich_merge._merge_list_tags(parent, tag, values, max_n=max_n)
    after = ["".join(el.itertext()).strip() for el in parent.findall(tag)]
    return before != after
