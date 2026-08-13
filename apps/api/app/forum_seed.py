"""色花堂索引种子聚合（标题 + 女优）。

聚合规则（硬约定）：
1. 中文优先 —— 无假名的中文片名硬优先入选
2. 日文兜底 —— 无合格中文时才用日文正片名
3. 女优从字段取 —— 只认描述【出演女优】等字段，绝不从标题抽/剥女优
4. 标题安全清洗 —— clean_forum_zh_title 去番号/版块/破解字幕等噪声后，
   再经 is_indexable_forum_title 门闸；假壳宁缺
5. 多帖聚合优选 —— 跨帖择优；女优同样跨帖中文名优先
6. 标题字段优先 —— 先【影片名称】/【作品名称】/【资源名称】类字段，
   全空才用帖题 title 兜底

分区：有码/写真索引女优；其余区 want_actors=False 只写标题。
"""

from __future__ import annotations

import re
from typing import Any

from .pack_bleed import get_description_field
from .scrape_forum_title import (
    clean_forum_zh_title,
    is_indexable_forum_title,
    is_likely_chinese,
)
from .scrape_forum_title import (  # noqa: SLF001
    _FORUM_META_ZH_JUNK_RE,
    _META_SHELL_SCORE_LEN,
)

_SCORE_PACK_NOISE_RE = re.compile(
    r"汇总|合集更新至|作品合集|二楼彩蛋|计\s*\d+\s*部|"
    r"\d+(?:\.\d+)?\s*TB\s*/|\d{2,}\s*V\s*/\s*\d",
    re.I,
)
_SCORE_CLIP_RE = re.compile(
    r"修复片段|修復片段|片段\s*\d|剪辑片段|合集片段",
    re.I,
)


def _has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def _has_kana(s: str) -> bool:
    return any("\u3040" <= ch <= "\u30ff" for ch in s)


def _cjk_ratio(s: str) -> float:
    if not s:
        return 0.0
    n = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
    return n / max(len(s), 1)


def _is_chinese_name(name: str) -> bool:
    """汉字女优名（无假名）— 多帖女优优选用。"""
    n = str(name or "").strip()
    if not n or len(n) < 2 or len(n) > 20:
        return False
    if not _has_cjk(n) or _has_kana(n):
        return False
    if re.search(r"[A-Za-z0-9]", n):
        return False
    return True


def _is_actor_name(name: str) -> bool:
    """女优名：中文或日文（可含假名）；拒剧情短句。"""
    n = str(name or "").strip(" .　·・")
    if not n or len(n) < 2 or len(n) > 16:
        return False
    if not (_has_cjk(n) or _has_kana(n)):
        return False
    if re.search(r"[A-Za-z0-9]", n):
        return False
    # 助词夹杂动词尾巴：藤森里穂がイク（が/を/に后仍接字）
    # 注意：は/の常做人名读音（はる香/よしの），不可一律拒绝
    if re.search(r"[がをに][\u4e00-\u9fffぁ-んァ-ン]", n):
        return False
    if _ACTOR_META_JUNK_RE.search(n) or _TITLE_TAIL_JUNK_RE.search(n):
        return False
    # 素人昵称：えびちゃん / みなみさん / 北村さん
    if re.fullmatch(r"[\u4e00-\u9fffぁ-んァ-ン]{1,8}(?:ちゃん|さん|くん)", n):
        return True
    # 无「・」分隔的共演串/长句不当单名
    if "・" not in n and "·" not in n and len(n) > 8:
        return False
    if re.search(
        r"(性交|性爱|中出|解禁|专属|專屬|字幕|腿こき|顔騎|笔おろし|"
        r"気持ち|すぎる|おぼれる|むんむん|されたい|したい|"
        r"射精|弄り|発蒸|蜜写|失神|悶絶|刺激)$",
        n,
    ):
        return False
    if re.search(
        r"(されたい|したい|してる|しましょう|しま$|ってよ|して$|"
        r"で最高|を外|更新至|発蒸中|らしい$|たいらしい$|"
        r"(?:せ|れ|め|て|す)る$)",
        n,
    ):
        return False
    # 短假名艺名（ルナ / あやめ）；长片假名多半是类型词
    if re.fullmatch(r"[ぁ-んァ-ンヴー]{2,6}", n):
        return True
    if re.fullmatch(r"[ァ-ンヴー]{7,10}", n):
        return False
    # 8+ 且假名偏多：多半是短句不是人名
    kana_n = sum(1 for ch in n if "\u3040" <= ch <= "\u30ff")
    if len(n) >= 8 and kana_n >= 4 and "・" not in n and "·" not in n:
        return False
    return True


# 出演女优字段里的年龄/职业/系列噪声（素人帖极常见）
_ACTOR_META_JUNK_RE = re.compile(
    r"(?:"
    r"\d+\s*歳|歳|"
    r"結婚\d*|未婚|既婚|"
    r"勤務|店員|看護師|介護|教師|学生|社員|"
    r"ネイリスト|トレーナー|ダンサ|アパレル|クリニック|"
    r"ナース|美容師|受付|秘書|主婦|人妻|"
    r"軟派|初撮|ナンパ|連れ込み|ヤリ部屋|隠し撮り|"
    r"素人|未知|不详|不詳|"
    r"スペシャル|SPECIAL|BEST|ドキュメント|"
    r"潮水|壯觀|壮观|"
    r"プロフィール|プロファイル"
    r")",
    re.I,
)

_TITLE_TAIL_JUNK_RE = re.compile(
    r"(?:传媒|视频|先生|工作室|系列|合集|性交|性爱|中出|解禁|"
    r"专属|專屬|字幕|破解|无码|有码|增强|修复|片段|"
    r"耐久|赛|賽|温泉|包场|志愿|女子|美少女|女教师|女教師|"
    r"風俗嬢|ラウンジ嬢|グラドル|女優|女优|"
    r"モニタリング|ベスト|コンプリート|"
    r"前編|後編|后编|前编|総集編|総集编|"
    r"エステ|サロン|回春|倶楽部|クラブ|ライブ|"
    r"全部されたい|エロいこと|新人|専属|專屬|"
    r"やまと|なでしこ|ラウンジ|アップ|作戦|解禁|"
    r"ドキュメント|企画|記念|变化|変化|"
    r"精子|濃厚|誘惑|抱擁|一緒|お風呂|幼い|頃|"
    r"現役|女子大生|大生|未公開|公開|儿子|兒子|顔射|禁欲|トップ|"
    r"彼女|私|僕|俺|自分|母子|総集|"
    # 剧情名词误当人名（体温と吐息が溶け合う… / …筆おろし）
    r"吐息|体温|呼吸|距離|空間|時間|覚悟|離婚|宝物|形見|"
    r"屈辱|面接|母乳|友達|ミルク|密室|密着|筆おろし|おろし|癒し|"
    # 素人系列词
    r"軟派|ナンパ|連れ込み|ヤリ部屋|初撮|隠し撮り|"
    r"ラグジュ|グラマラス|フェロモン|オトナ|悪い|食い物)",
    re.I,
)

# 标题尾罗马字艺名（拒 FIRST/IMPRESSION 等片头词）
_ROMAJI_TAIL_JUNK_RE = re.compile(
    r"(?i)^(?:FIRST|IMPRESSION|IMPRESSIO|SPECIAL|EDITION|VENUS|STYLE|"
    r"BEST|COMPLETE|PREMIUM|DIRECTORS?|CUT|BLU-?RAY|BLUE|RAY|"
    r"DOCUMENT|DOCUMENTARY|THE|AND|OF|AV|DEBUT|NEW|FACE|GIRL|"
    r"VOL|PART|CHAPTER|BEAUTY|MEGA|FAN|THANKS?|HANDS?|MELTY|"
    r"BODY|OVER|SEX|LOVE|WOMAN|WOMEN|GIRLS|BOYS|MEN|MAN|"
    r"SKY|TOWER|WHITE|BLACK|REAL|DOCUMENT|HAPPY|HAPP|SPE|SPEC|"
    r"I{1,3}|IV|VI{0,3}|IX|X{1,3}|\d+)$"
)


def _score_zh_title(
    t: str,
    *,
    needle: str,
    from_film_name: bool = False,
    from_resource: bool = False,
) -> int:
    """越高越像可用中文题；日文假名大幅降权。"""
    if not t or not _has_cjk(t):
        return -1
    if t.upper() == needle or re.fullmatch(rf"{re.escape(needle)}", t, re.I):
        return -1
    # 纯女优名不当中文片名（会盖掉日文正片）
    if _looks_like_bare_actor_title(t):
        return -1
    # 合集/容量噪声题不要
    if _SCORE_PACK_NOISE_RE.search(t):
        return -1
    # 增强帖题「4K修复片段1 女优」不当正片中文名
    if _SCORE_CLIP_RE.search(t):
        return -1
    # 合集壳伪中文「含单体+共演+写真」等复合特征
    if _FORUM_META_ZH_JUNK_RE.search(t) and len(t) < _META_SHELL_SCORE_LEN:
        return -1
    ratio = _cjk_ratio(t)
    score = int(ratio * 220) + min(len(t), 36)
    if from_film_name:
        score += 50
    elif from_resource:
        score += 30
    if _has_kana(t):
        score -= 140
    if ratio < 0.4:
        score -= 40
    if 4 <= len(t) <= 48:
        score += 25
    if len(t) > 60:
        score -= 30
    return score


_TITLE_CONTENT_HINT_RE = re.compile(
    r"[的了是与和在被把给跟给對对]|[！!？?…—\-~～「」『』《》【】]"
    r"|流出|盗撮|中出|解禁|专属|專屬|性交|性爱|诱惑|誘惑|毕业|卒業"
)


def _norm_title_token(s: str) -> str:
    return re.sub(r"[\s\u3000·・、,，/|]+", "", str(s or "")).casefold()


def _title_is_actor_echo(title: str, actors: list[str] | None) -> bool:
    """标题是否其实只是女优名（与出演字段相同）。"""
    t = str(title or "").strip()
    if not t or not actors:
        return False
    nt = _norm_title_token(t)
    if not nt:
        return False
    names = [str(a).strip() for a in actors if str(a or "").strip()]
    if any(nt == _norm_title_token(a) for a in names):
        return True
    joined = _norm_title_token("、".join(names[:4]))
    return bool(joined) and nt == joined


def _looks_like_bare_actor_title(t: str) -> bool:
    """短串且像单一人名（无剧情词/标点）——常被误当中文片名。"""
    s = str(t or "").strip()
    if not s or len(s) < 2 or len(s) > 8:
        return False
    if _TITLE_CONTENT_HINT_RE.search(s) or re.search(r"[\s\u3000]", s):
        return False
    return _is_actor_name(s)


def _finalize_seed_title(
    *,
    best_zh: str,
    best_zh_score: int,
    best_ja: str,
    best_ja_score: int,
    actors: list[str],
) -> str:
    """中文优先；女优名形中文一律不当标题（有日文则让位，无则宁缺）。"""
    zh = best_zh if best_zh_score >= 0 else ""
    ja = best_ja if best_ja_score >= 0 else ""
    if zh and (
        _title_is_actor_echo(zh, actors) or _looks_like_bare_actor_title(zh)
    ):
        return ja if ja and len(ja) >= 5 else ""
    if zh:
        return zh
    return ja


def _parse_actors(desc: str, *, needle: str) -> list[str]:
    raw = get_description_field(desc, "出演女优") or ""
    if not raw:
        # 兼容其它标签（含繁体/演出者等，经 DESCRIPTION_LABEL_ALIASES 归一）
        for lab in (
            "女优名称",
            "女优",
            "女優",
            "演员",
            "主演",
            "演出者",
            "出演者",
            "出演",
            "女优名",
            "女優名",
            "表演者",
            "艺人",
        ):
            raw = get_description_field(desc, lab) or ""
            if raw:
                break
    if not raw:
        return []
    # 去掉括号备注：波多野结衣（はたの ゆい）
    raw = re.sub(r"[（(][^）)]{0,40}[）)]", " ", raw)
    # 「32歳リホさ」年龄与名粘连 → 拆开
    raw = re.sub(r"(\d{1,2})\s*歳", r" \1歳 ", raw)
    parts = re.split(r"[,，、/|｜\s　]+", raw)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        name = str(p or "").strip(" .　·・")
        if not name or name in seen:
            continue
        if name.upper() == needle or len(name) > 24:
            continue
        if _ACTOR_META_JUNK_RE.search(name):
            continue
        if re.search(
            r"(未知|不详|素人|共演|ほか|他|女優|女优|出演|"
            r"中出|解禁|特別|特别|专属|專屬|SP\b|編|编)",
            name,
            re.I,
        ):
            continue
        # 纯罗马字艺名（RARA / Soa / miru）放行；拒 FIRST 等片头词
        if re.search(r"[A-Za-z]{2,}", name) and not _has_cjk(name):
            if not _is_romaji_actor_name(name):
                continue
            seen.add(name)
            out.append(name)
            if len(out) >= 8:
                break
            continue
        if re.fullmatch(r"[\d.]+", name):
            continue
        # 中出解禁SP / 纯标签
        if re.fullmatch(r".*(?:解禁|中出|专属|專屬).*(?:SP|編|编)?", name, re.I):
            continue
        if len(name) < 2:
            continue
        # 统一走人名校验（含短假名艺名 / ちゃんさん昵称）
        if not (_is_actor_name(name) or _is_romaji_actor_name(name)):
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= 8:
            break
    return out


def _is_romaji_actor_name(name: str) -> bool:
    """标题尾罗马字艺名：AIKA / miru / RARA；拒片头词与驼峰品牌。"""
    n = str(name or "").strip(" .　·・")
    if not n or len(n) < 2 or len(n) > 12:
        return False
    if not re.fullmatch(r"[A-Za-z][A-Za-z.\-]{1,11}", n):
        return False
    # MeltyHands 一类店名/品牌
    if re.search(r"[a-z][A-Z]", n):
        return False
    if _ROMAJI_TAIL_JUNK_RE.fullmatch(n):
        return False
    letters = re.sub(r"[.\-]", "", n)
    if len(letters) < 3:
        return False
    return True


def _score_actors(acts: list[str]) -> int:
    if not acts:
        return -1
    zh_n = sum(1 for a in acts if _is_chinese_name(a))
    ja_n = sum(1 for a in acts if _is_actor_name(a) and _has_kana(a))
    cjk_n = sum(1 for a in acts if _has_cjk(a) and not _has_kana(a))
    ro_n = sum(1 for a in acts if _is_romaji_actor_name(a))
    # 中文硬优先，日文假名名 / 罗马字艺名也可入库
    return zh_n * 80 + cjk_n * 20 + ja_n * 40 + ro_n * 35 + len(acts) * 5


def _desc_title_candidates(desc: str) -> list[tuple[str, str]]:
    """描述里片名类字段（影片名称 → 资源名称），不含帖题。"""
    out: list[tuple[str, str]] = []
    film = str(
        get_description_field(desc, "影片名称")
        or get_description_field(desc, "影片名稱")
        or get_description_field(desc, "作品名称")
        or get_description_field(desc, "作品名稱")
        or get_description_field(desc, "片名")
        or ""
    ).strip()
    if film:
        out.append((film, "film"))
    resource = str(
        get_description_field(desc, "资源名称")
        or get_description_field(desc, "资源名稱")
        or get_description_field(desc, "資源名稱")
        or get_description_field(desc, "资源名")
        or ""
    ).strip()
    if resource and resource != film:
        out.append((resource, "resource"))
    return out


def _try_clean_title(raw: str, needle: str, *, allow_weak: bool = False) -> str:
    cleaned = clean_forum_zh_title(
        raw, needle, actors=None, allow_weak=allow_weak
    )
    if cleaned and is_indexable_forum_title(
        cleaned, needle, assume_not_fake=True
    ):
        return cleaned
    return ""


def _pick_post_title(
    desc: str,
    post_title: str,
    *,
    needle: str,
) -> tuple[str, str]:
    """单帖标题：片名/资源名字段优先 → 帖题 title 最后兜底。

    返回 (cleaned, source)，source ∈ film|resource|post|""。
    """
    for raw, source in _desc_title_candidates(desc):
        cleaned = _try_clean_title(raw, needle)
        if cleaned:
            return cleaned, source
    post = str(post_title or "").strip()
    if post:
        cleaned = _try_clean_title(post, needle)
        if cleaned:
            return cleaned, "post"
    return "", ""


def _consider_title_candidate(
    cleaned: str,
    source: str,
    *,
    needle: str,
    best_zh: str,
    best_zh_score: int,
    best_ja: str,
    best_ja_score: int,
) -> tuple[str, int, str, int]:
    """按中文优先 / 日文兜底更新最佳候选；字段源加权高于帖题。"""
    from_film = source == "film"
    from_resource = source == "resource"
    if is_likely_chinese(cleaned):
        zh_sc = _score_zh_title(
            cleaned,
            needle=needle,
            from_film_name=from_film,
            from_resource=from_resource,
        )
        # 帖题中文再降一档，避免盖过同质量字段名
        if source == "post":
            zh_sc -= 20
        if zh_sc >= 0 and zh_sc > best_zh_score:
            return cleaned, zh_sc, best_ja, best_ja_score
        return best_zh, best_zh_score, best_ja, best_ja_score

    ja_sc = min(len(cleaned), 40)
    if from_film:
        ja_sc += 40
    elif from_resource:
        ja_sc += 30
    elif source == "post":
        ja_sc -= 10
        if _SCORE_CLIP_RE.search(cleaned):
            ja_sc -= 40
    if _has_kana(cleaned):
        ja_sc += 15
    elif _has_cjk(cleaned):
        ja_sc += 10
    if ja_sc > best_ja_score:
        return best_zh, best_zh_score, cleaned, ja_sc
    return best_zh, best_zh_score, best_ja, best_ja_score


def pick_forum_seed_from_posts(
    code: str,
    posts: list[dict[str, Any]] | None,
    *,
    max_posts: int = 96,
    want_actors: bool = True,
) -> dict[str, Any]:
    """多帖聚合选标题/女优。

    标题：先跨帖聚合【影片名称】/【资源名称】类字段（中文优先→日文兜底），
    全空再用帖题 title 兜底。女优只从描述字段。
    """
    needle = str(code or "").strip().upper()
    empty: dict[str, Any] = {"title": "", "actors": [], "postsScanned": 0}
    if not needle or not posts:
        return empty

    best_zh = ""
    best_zh_score = -1
    best_ja = ""
    best_ja_score = -1
    best_zh_actors: list[str] = []
    best_zh_actors_score = -1
    best_actors: list[str] = []
    best_actors_score = -1
    scanned = 0

    rows = [r for r in list(posts)[:max_posts] if isinstance(r, dict)]

    # —— 女优：跨帖字段聚合（与标题无关）——
    for row in rows:
        desc = str(row.get("description") or "")
        post_title = str(row.get("title") or "").strip()
        if not desc.strip() and not post_title:
            continue
        scanned += 1
        if not want_actors:
            continue
        acts = _parse_actors(desc, needle=needle)
        if not acts:
            continue
        zh_acts = [a for a in acts if _is_chinese_name(a)]
        if zh_acts:
            zsc = _score_actors(zh_acts)
            if zsc > best_zh_actors_score:
                best_zh_actors_score = zsc
                best_zh_actors = zh_acts
        ascore = _score_actors(acts)
        if ascore > best_actors_score:
            best_actors_score = ascore
            best_actors = acts

    # —— 标题阶段 1：只认影片名称 / 资源名称类字段 ——
    for row in rows:
        desc = str(row.get("description") or "")
        for raw, source in _desc_title_candidates(desc):
            cleaned = _try_clean_title(raw, needle)
            if not cleaned:
                continue
            best_zh, best_zh_score, best_ja, best_ja_score = _consider_title_candidate(
                cleaned,
                source,
                needle=needle,
                best_zh=best_zh,
                best_zh_score=best_zh_score,
                best_ja=best_ja,
                best_ja_score=best_ja_score,
            )

    actors_out = (
        (
            best_zh_actors
            if best_zh_actors_score >= 0
            else (best_actors if best_actors_score >= 0 else [])
        )
        if want_actors
        else []
    )
    if actors_out:
        try:
            from .scrape_metadata_optimize import normalize_actor_names

            actors_out = normalize_actor_names(actors_out)
        except Exception:
            pass

    title_out = _finalize_seed_title(
        best_zh=best_zh,
        best_zh_score=best_zh_score,
        best_ja=best_ja,
        best_ja_score=best_ja_score,
        actors=actors_out,
    )

    # —— 标题阶段 2：字段全空 → 帖题 title 兜底 ——
    if not title_out:
        for row in rows:
            post = str(row.get("title") or "").strip()
            if not post:
                continue
            cleaned = _try_clean_title(post, needle)
            if not cleaned:
                continue
            best_zh, best_zh_score, best_ja, best_ja_score = _consider_title_candidate(
                cleaned,
                "post",
                needle=needle,
                best_zh=best_zh,
                best_zh_score=best_zh_score,
                best_ja=best_ja,
                best_ja_score=best_ja_score,
            )
        title_out = _finalize_seed_title(
            best_zh=best_zh,
            best_zh_score=best_zh_score,
            best_ja=best_ja,
            best_ja_score=best_ja_score,
            actors=actors_out,
        )

    # —— 弱清洗：同样字段优先，title 最后 ——
    if not title_out:
        weak_zh = ""
        weak_zh_score = -1
        weak_ja = ""
        weak_ja_score = -1
        for phase in ("fields", "post"):
            for row in rows:
                desc = str(row.get("description") or "")
                post_title = str(row.get("title") or "").strip()
                candidates: list[tuple[str, str]] = (
                    _desc_title_candidates(desc)
                    if phase == "fields"
                    else ([(post_title, "post")] if post_title else [])
                )
                for raw, source in candidates:
                    weak = _try_clean_title(raw, needle, allow_weak=True)
                    if not weak:
                        continue
                    weak_zh, weak_zh_score, weak_ja, weak_ja_score = (
                        _consider_title_candidate(
                            weak,
                            source,
                            needle=needle,
                            best_zh=weak_zh,
                            best_zh_score=weak_zh_score,
                            best_ja=weak_ja,
                            best_ja_score=weak_ja_score,
                        )
                    )
            title_out = _finalize_seed_title(
                best_zh=weak_zh,
                best_zh_score=weak_zh_score,
                best_ja=weak_ja,
                best_ja_score=weak_ja_score,
                actors=actors_out,
            )
            if title_out:
                break

    title_zh = title_out if is_likely_chinese(title_out) else ""
    return {
        "title": title_out,
        "actors": actors_out,
        "postsScanned": scanned,
        "titleZh": title_zh,
        "hadJaTitle": bool(best_ja),
        "jaTitleSample": (best_ja or "")[:80],
    }
