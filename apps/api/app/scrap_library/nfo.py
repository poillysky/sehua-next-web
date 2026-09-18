# -*- coding: utf-8 -*-
"""刮削库 Emby/Kodi NFO 解析 → 嵌入文本。

写出约定对齐 MDCx 参考库（``E:/Project/media/日本有码``）：
  - 字段顺序固定；title/originaltitle/sorttitle/outline/plot 用 CDATA
  - ``<actor><name>…</name><type>Actor</type></actor>``
  - ``<tag>`` 与 ``<genre>`` 镜像（类型 + 前缀 + 女优 + 系列:/片商:/发行:）
  - 不写 actor_all / mosaic / outlineshow / badge 等程序私有节点

解析约定：只认 ``<actor>`` / ``actor_all``；**禁止**从 tag/genre 硬套女优。
无女优则不写女优行 / 不写 ``<actor>``。
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from app.ai.config import resolve_embed_config

_WS_RE = re.compile(r"\s+")
# 剧情译中后需完整进 source_text，详情「再打开」才能读到全文（向量仍可接受 ~2k）
_MAX_EMBED_CHARS = 2400
_MAX_LIST = 12

# MDCx 把片商/系列塞进 tag 的前缀
_TAG_META_PREFIX_RE = re.compile(
    r"^(片商|系列|发行|發行|制作|製作|厂牌|廠牌|导演|導演|賣家|卖家)\s*[:：]"
)
# 番号/前缀状 token（YSN、SSIS-001）不当女优
_CODEISH_RE = re.compile(r"^[A-Za-z]{1,8}(?:-\d{1,6})?$")


def _clip(s: str, n: int = 160) -> str:
    t = _WS_RE.sub(" ", (s or "").strip())
    return t if len(t) <= n else t[: n - 1] + "…"


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return _WS_RE.sub(" ", "".join(el.itertext()).strip())


def _texts(root: ET.Element, tag: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for el in root.findall(f".//{tag}"):
        t = _text(el)
        if not t:
            continue
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
        if len(out) >= _MAX_LIST:
            break
    return out


def _actor_names(root: ET.Element) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for actor in root.findall(".//actor"):
        name = _text(actor.find("name"))
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= _MAX_LIST:
            break
    return out


def _texts_all(root: ET.Element, tag: str) -> list[str]:
    """读取全部同名标签（不截断，供格式归一化保留内容）。"""
    out: list[str] = []
    seen: set[str] = set()
    for el in root.findall(f".//{tag}"):
        t = _text(el)
        if not t:
            continue
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def _looks_like_actress_token(raw: str, *, code: str = "", studio: str = "") -> bool:
    """判断 tag/genre 项是否像女优名（而非类型/片商/番号）。"""
    s = _WS_RE.sub(" ", str(raw or "").strip())
    if not s or len(s) < 2 or len(s) > 24:
        return False
    if _TAG_META_PREFIX_RE.match(s):
        return False
    if _CODEISH_RE.match(s):
        return False
    code_u = str(code or "").strip().upper()
    if code_u and s.upper() == code_u:
        return False
    if code_u and "-" in code_u and s.upper() == code_u.split("-", 1)[0]:
        return False
    studio_u = str(studio or "").strip()
    if studio_u and s.casefold() == studio_u.casefold():
        return False
    # 已知类型词
    try:
        from app.scrap_library.enrich import _JUNK_ACTOR_TAGS, _JUNK_ACTOR_SUBSTR

        if s in _JUNK_ACTOR_TAGS or s.casefold() in _JUNK_ACTOR_TAGS:
            return False
        low = s.casefold()
        if any(p in s or p in low for p in _JUNK_ACTOR_SUBSTR):
            return False
    except Exception:  # noqa: BLE001
        pass
    # 常见类型（转入库高频，未必全在 junk 表）
    if s in {
        "乱伦",
        "亂倫",
        "近亲",
        "近親",
        "受孕",
        "平胸",
        "巨乳",
        "美乳",
        "凌辱",
        "催眠",
        "监禁",
        "監禁",
        "恋物癖",
        "其他恋物癖",
        "其他戀物癖",
        "出轨",
        "出軌",
        "NTR",
        "ntr",
        "滥交",
        "濫交",
        "口交",
        "调教",
        "調教",
        "无套性交",
        "無套性交",
        "户外露出",
        "戶外露出",
        "熟女人妻",
        "偶像艺人",
        "偶像藝人",
        "按摩棒",
        "插入手指",
        "雪白肌肤",
        "雪白肌膚",
        "大保健",
        "主观视角",
        "主觀視角",
        "风俗娘",
        "風俗娘",
        "ご奉仕",
        "エロマッサージ",
        "固定カメラ",
        "なまハメ",
        "自拍",
        "业余",
        "業餘",
    }:
        return False
    # 行为/道具类日文片段
    if re.search(
        r"(マッサージ|カメラ|ハメ|プレイ|オナニー|フェラ|中出し|騎乗)",
        s,
    ):
        return False
    # 行为类中文片段
    if re.search(
        r"(性交|插入|按摩|露出|视角|視角|保健|肌肤|肌膚|手指|无套|無套|中出|骑乘|騎乘|自拍|舔阴|舔陰)",
        s,
    ):
        return False
    # 类型复合：出轨/NTR、痴女/OL
    if "/" in s or "|" in s or "／" in s:
        return False
    # 必须含汉字或假名（纯英文企划词排除）
    if not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", s):
        return False
    # 两字纯汉字多为类型（乱伦/中出/平胸）；艺名常见 3～4 字或带假名
    has_kana = bool(re.search(r"[\u3040-\u30ff]", s))
    han_only = re.fullmatch(r"[\u3400-\u9fff]{2,}", s)
    if han_only and len(s) <= 2 and not has_kana:
        return False
    # 纯汉字 3～4 字题材词仍偏类型（无套性交/户外露出）；真名多带・或假名
    if han_only and len(s) <= 4 and not has_kana and "・" not in s and "·" not in s:
        # 放行像「三上悠亚」这类 4 字常见艺名形态：末字多为常见名用字且非动宾结构
        # 保守：无间隔的 3～4 字纯汉字默认不当女优（FC2 误把标签写入 actor）
        if len(s) <= 3:
            return False
    # 句段/过长短语不像艺名
    if re.search(r"[がをにはへでも]", s) and len(s) >= 4:
        return False
    if any(m in s for m in ("だった", "です", "ます", "系列", "片商", "作品")):
        return False
    return True


def actors_from_mdcx_side_channels(
    *,
    tags: list[str] | None = None,
    genres: list[str] | None = None,
    actors_all: list[str] | None = None,
    code: str = "",
    studio: str = "",
) -> list[str]:
    """仅从 ``actor_all`` 取女优（原文保留）；**不再**从 tag/genre 升格。"""
    del tags, genres, code, studio  # 保留参数兼容旧调用
    out: list[str] = []
    seen: set[str] = set()
    for raw in actors_all or []:
        s = _WS_RE.sub(" ", str(raw or "").strip())
        if not s or _TAG_META_PREFIX_RE.match(s):
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= _MAX_LIST:
            break
    return out


def parse_nfo(path: Path) -> dict[str, Any]:
    """解析 movie NFO；失败返回空 dict。

    只认 ``<actor>`` / ``actor_all``；无则女优为空（不从 tag/genre 硬套）。
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(raw)
    except Exception:
        return {}
    if root.tag.lower() != "movie" and root.find("movie") is not None:
        root = root.find("movie")  # type: ignore[assignment]
    if root is None:
        return {}

    num = _text(root.find("num")) or path.stem
    title = _text(root.find("title"))
    original = _text(root.find("originaltitle"))
    plot = _text(root.find("plot")) or _text(root.find("outline"))
    originalplot = _text(root.find("originalplot"))
    studio = _text(root.find("studio")) or _text(root.find("maker"))
    publisher = _text(root.find("publisher")) or _text(root.find("label"))
    year = _text(root.find("year"))
    premiered = _text(root.find("premiered")) or _text(root.find("releasedate"))
    director = _text(root.find("director"))
    runtime = _text(root.find("runtime"))
    rating = _text(root.find("rating"))
    seller = _text(root.find("seller"))
    genres = _texts(root, "genre")
    tags = _texts(root, "tag")
    badges = _texts(root, "badge")
    actors = _actor_names(root)
    actors_all = _texts(root, "actor_all")
    cover_url = _text(root.find("cover"))
    poster = _text(root.find("poster")) or "poster.jpg"
    thumb = _text(root.find("thumb")) or "thumb.jpg"
    fanart = _text(root.find("fanart")) or "fanart.jpg"
    website = _text(root.find("website"))
    series = _text(root.find("series")) or _text(root.find("set/name"))
    cnsub = _text(root.find("cnsub")).lower() in {"true", "1", "yes"}
    definition = _text(root.find("definition"))
    mosaic = _text(root.find("mosaic"))
    outline_show = _text(root.find("outlineshow")) or "zh"

    # 只认 <actor> / actor_all；按 NFO 原文保留，不做 junk 清洗
    if not actors and actors_all:
        actors = [str(a).strip() for a in actors_all if str(a).strip()]
    # 去重保序
    _seen: set[str] = set()
    _uniq: list[str] = []
    for a in actors:
        s = str(a or "").strip()
        if not s:
            continue
        k = s.casefold()
        if k in _seen:
            continue
        _seen.add(k)
        _uniq.append(s)
    actors = _uniq[:_MAX_LIST]

    # 女优名从 tag/genre 展示列表里拿掉，避免类型区重复
    actor_fold = {a.casefold() for a in actors}
    if actor_fold:
        tags = [t for t in tags if t.casefold() not in actor_fold]
        genres = [g for g in genres if g.casefold() not in actor_fold]

    # 去掉与 genre 重复的 tag，以及「片商:」「发行:」前缀噪音过多时仍保留
    genre_fold = {g.casefold() for g in genres}
    tags = [
        t
        for t in tags
        if t.casefold() not in genre_fold and not _TAG_META_PREFIX_RE.match(t)
    ][:_MAX_LIST]
    genres = [g for g in genres if not _TAG_META_PREFIX_RE.match(g)][:_MAX_LIST]

    return {
        "num": num,
        "title": title,
        "originaltitle": original,
        "titleJa": original,
        "plot": plot,
        "overviewJa": originalplot,
        "studio": studio,
        "publisher": publisher,
        "year": year,
        "premiered": premiered,
        "director": director,
        "runtime": runtime,
        "score": rating,
        "seller": seller,
        "genres": genres,
        "tags": tags,
        "badges": badges,
        "actors": actors,
        "actorsAll": actors_all or list(actors),
        "series": series,
        "website": website,
        "cnsub": cnsub,
        "definition": definition,
        "mosaic": mosaic,
        "outlineShow": outline_show,
        "cover_url": cover_url,
        "poster": poster,
        "thumb": thumb,
        "fanart": fanart,
    }


def build_nfo_embed_text(
    meta: dict[str, Any],
    *,
    region: str = "",
    prefix: str = "",
) -> str:
    num = str(meta.get("num") or "").strip()
    title = str(meta.get("title") or "").strip()
    original = str(meta.get("originaltitle") or "").strip()
    plot = str(meta.get("plot") or "").strip()
    studio = str(meta.get("studio") or "").strip()
    publisher = str(meta.get("publisher") or "").strip()
    year = str(meta.get("year") or "").strip()
    premiered = str(meta.get("premiered") or "").strip()
    actors = [str(x).strip() for x in (meta.get("actors") or []) if str(x).strip()]
    genres = [str(x).strip() for x in (meta.get("genres") or []) if str(x).strip()]
    tags = [str(x).strip() for x in (meta.get("tags") or []) if str(x).strip()]
    # 女优按 NFO <actor> 原文写入，不清洗、不因撞片商名剔除

    lines: list[str] = []
    if region:
        lines.append(f"分区：{_clip(region, 40)}")
    if prefix:
        lines.append(f"前缀：{_clip(prefix, 40)}")
    if num:
        lines.append(f"番号：{num}")
    if title:
        lines.append(f"标题：{_clip(title, 120)}")
    title_f = title.casefold()
    if original and original.casefold() != title_f:
        lines.append(f"原标题：{_clip(original, 120)}")
    if actors:
        lines.append(f"女优：{' '.join(actors[:8])}")
    if studio:
        lines.append(f"片商：{_clip(studio, 60)}")
    if publisher and publisher.casefold() != studio.casefold():
        lines.append(f"发行：{_clip(publisher, 60)}")
    if year or premiered:
        lines.append(f"年份：{year or premiered[:4]}")
    if genres:
        lines.append(f"类型：{' '.join(genres[:10])}")
    if tags:
        lines.append(f"标签：{' '.join(tags[:10])}")
    badges = [str(x).strip() for x in (meta.get("badges") or []) if str(x).strip()]
    if badges:
        lines.append(f"角标：{' '.join(badges[:8])}")
    for key, label in (
        ("definition", "清晰度"),
        ("mosaic", "马赛克"),
    ):
        v = str(meta.get(key) or "").strip()
        if v and v not in {"zh", "false", "0"}:
            lines.append(f"{label}：{_clip(v, 24)}")
    if meta.get("cnsub") in (True, "true", "1", "yes"):
        lines.append("字幕：中字")
    if plot:
        # 详情页从 source_text 解析剧情；过短会截断译中结果
        lines.append(f"剧情：{_clip(plot, 1800)}")
    originalplot = str(
        meta.get("originalplot") or meta.get("overviewJa") or ""
    ).strip()
    if originalplot and originalplot.casefold() != plot.casefold():
        lines.append(f"原剧情：{_clip(originalplot, 1200)}")
    outline_show = str(meta.get("outlineShow") or "").strip().lower()
    if outline_show in {"zh_jp", "jp_zh"}:
        lines.append(f"双语：{outline_show}")

    text = "\n".join(lines).strip()
    if not text:
        text = num or title or "刮削条目"
    if len(text) > _MAX_EMBED_CHARS:
        text = text[:_MAX_EMBED_CHARS]
    return text


def content_sha(source_text: str, *, model: str | None = None, dim: int | None = None) -> str:
    if model is None or dim is None:
        cfg = resolve_embed_config()
        m = model or str(cfg["model"])
        d = int(dim if dim is not None else cfg["dim"])
    else:
        m = str(model)
        d = int(dim)
    payload = f"{m}\n{d}\n{source_text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_ACTRESS_LINE_RE = re.compile(r"^(女优：)(.+)$", re.M)
_STUDIO_LINE_RE = re.compile(r"^片商：(.+)$", re.M)
_PUBLISHER_LINE_RE = re.compile(r"^发行：(.+)$", re.M)


def normalize_source_text_for_diff(source_text: str) -> str:
    """按现行清洗+女优映射规则归一化，便于增量比对。"""
    return polish_source_text_actresses(str(source_text or ""))


def preserve_actress_line(prev_source: str, new_source: str) -> str:
    """NFO 无 actor 时勿用空女优覆盖库内已有女优行。"""
    prev = str(prev_source or "")
    new = str(new_source or "")
    if not prev or not new:
        return new
    old_m = _ACTRESS_LINE_RE.search(prev)
    if not old_m or not str(old_m.group(2) or "").strip():
        return new
    new_m = _ACTRESS_LINE_RE.search(new)
    if new_m and str(new_m.group(2) or "").strip():
        return new
    actress_line = f"女优：{old_m.group(2).strip()}"
    # 插在原标题/标题/番号之后
    anchor = None
    for rx in (r"^原标题：.+$", r"^标题：.+$", r"^番号：.+$", r"^前缀：.+$"):
        m = re.search(rx, new, re.M)
        if m:
            anchor = m
            break
    if anchor is None:
        return f"{actress_line}\n{new}".strip()
    i = anchor.end()
    return f"{new[:i]}\n{actress_line}{new[i:]}".strip()


def polish_source_text_actresses(
    source_text: str, *, exclude: list[str] | None = None
) -> str:
    """保留女优行原文（不再 junk 清洗 / 撞名剔除）。``exclude`` 仅兼容旧调用。"""
    del exclude
    return str(source_text or "")


def item_id_from_rel(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip().strip("/")


# 参考库 MDCx：这些字段用 CDATA 包一层
_CDATA_TAGS = frozenset({"title", "originaltitle", "sorttitle", "outline", "plot"})


def _xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def format_nfo_xml(root: ET.Element) -> bytes:
    """按参考库格式输出：声明带空格、字段分行、指定标签用 CDATA。"""
    lines: list[str] = ['<?xml version="1.0" encoding="UTF-8" ?>', "<movie>"]

    def _emit(el: ET.Element, indent: int = 1) -> None:
        pad = "  " * indent
        tag = str(el.tag)
        kids = list(el)
        attr = "".join(
            f' {k}="{_xml_escape(v)}"' for k, v in (el.attrib or {}).items()
        )
        text = "".join(el.itertext()).strip() if not kids else (el.text or "").strip()
        if not kids:
            if text:
                if tag in _CDATA_TAGS:
                    # CDATA 内若出现 ]]> 极少见；按参考库原样写入
                    safe = text.replace("]]>", "]]]]><![CDATA[>")
                    lines.append(f"{pad}<{tag}{attr}><![CDATA[{safe}]]></{tag}>")
                else:
                    lines.append(f"{pad}<{tag}{attr}>{_xml_escape(text)}</{tag}>")
            else:
                lines.append(f"{pad}<{tag}{attr}/>")
            return
        lines.append(f"{pad}<{tag}{attr}>")
        for ch in kids:
            _emit(ch, indent + 1)
        lines.append(f"{pad}</{tag}>")

    for child in list(root):
        _emit(child, 1)
    lines.append("</movie>")
    # 参考库无文件尾空行
    return "\n".join(lines).encode("utf-8")


def write_nfo(path: Path, root: ET.Element) -> None:
    """写入易读 NFO（字段分行）。**原子替换**。

    ⚠️ 不要退回 `path.write_bytes()`：直接截断写在中途失败（进程被杀 / 磁盘满）
    会留下**半截 XML**；下次 `merge_nfo_with_detail` 读它时 `ET.fromstring` 抛错
    → 回落到空的 `<movie/>` 根 → 只写本次 detail 带的字段，**其余元数据静默丢失**。
    原子替换保证读者只会看到「旧文件」或「新文件」。
    """
    from app.core.atomic_io import atomic_write_bytes

    atomic_write_bytes(Path(path), format_nfo_xml(root))


def _el_text_raw(el: ET.Element | None) -> str:
    """保留原文空白（剧情等），只做 strip。"""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _append_text(parent: ET.Element, tag: str, value: str, *, empty_ok: bool = False) -> None:
    v = str(value or "")
    if not empty_ok:
        v = v.strip()
        if not v:
            return
    else:
        v = v.strip()
    el = ET.SubElement(parent, tag)
    el.text = v if v else None


def _append_many(parent: ET.Element, tag: str, values: list[str]) -> None:
    seen: set[str] = set()
    for raw in values or []:
        v = str(raw or "").strip()
        if not v:
            continue
        key = v.casefold()
        if key in seen:
            continue
        seen.add(key)
        el = ET.SubElement(parent, tag)
        el.text = v


def _append_actors_mdcx(parent: ET.Element, names: list[str]) -> None:
    seen: set[str] = set()
    for raw in names or []:
        v = str(raw or "").strip()
        if not v:
            continue
        key = v.casefold()
        if key in seen:
            continue
        seen.add(key)
        actor = ET.SubElement(parent, "actor")
        nm = ET.SubElement(actor, "name")
        nm.text = v
        typ = ET.SubElement(actor, "type")
        typ.text = "Actor"


def _num_prefix(num: str) -> str:
    n = str(num or "").strip().upper()
    if not n:
        return ""
    if "-" in n:
        return n.split("-", 1)[0].strip()
    m = re.match(r"^([A-Z]+)", n)
    return m.group(1) if m else ""


def _with_code_prefix(text: str, num: str) -> str:
    """标题类字段：参考库习惯 ``番号 + 空格 + 文案``。"""
    t = str(text or "").strip()
    n = str(num or "").strip()
    if not t:
        return n
    if not n:
        return t
    if t.upper().startswith(n.upper()):
        return t
    return f"{n} {t}"


def _rating_derived(score: str) -> tuple[str, str, str]:
    """返回 (rating, criticrating, javdb_value)。"""
    raw = str(score or "").strip()
    if not raw:
        return "", "", ""
    try:
        r = float(raw)
    except ValueError:
        return raw, "", ""
    # 展示尽量贴近参考：整数不带 .0
    rating_s = str(int(r)) if float(r).is_integer() else str(r)
    critic = r * 10.0
    critic_s = str(int(critic)) if float(critic).is_integer() else str(round(critic, 1))
    jav = r / 2.0
    jav_s = str(int(jav)) if float(jav).is_integer() else str(round(jav, 2))
    return rating_s, critic_s, jav_s


def build_mdcx_tag_genre_list(
    *,
    genres: list[str] | None = None,
    actors: list[str] | None = None,
    num: str = "",
    series: str = "",
    studio: str = "",
    publisher: str = "",
    director: str = "",
) -> list[str]:
    """参考库 tag/genre 镜像列表。"""
    out: list[str] = []
    seen: set[str] = set()

    def push(raw: str) -> None:
        s = str(raw or "").strip()
        if not s:
            return
        key = s.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(s)

    pref = _num_prefix(num)
    actor_fold = {a.casefold() for a in (actors or []) if str(a).strip()}
    # 卖家/片商当 actor 时（FC2 常见）不进 tag/genre，参考库只留「片商:」
    meta_fold = {
        str(x).strip().casefold()
        for x in (studio, publisher, director)
        if str(x).strip()
    }
    for item in genres or []:
        s = str(item or "").strip()
        if not s:
            continue
        if _TAG_META_PREFIX_RE.match(s):
            continue
        if pref and s.upper() == pref:
            continue
        if s.casefold() in actor_fold:
            continue
        push(s)
    if pref:
        push(pref)
    for a in actors or []:
        name = str(a).strip()
        if not name:
            continue
        if name.casefold() in meta_fold:
            continue
        push(name)
    if series:
        push(f"系列: {series}")
    if studio:
        push(f"片商: {studio}")
    if publisher:
        push(f"发行: {publisher}")
    return out


def fields_from_movie_root(src: ET.Element, *, code_fallback: str = "") -> dict[str, Any]:
    """从任意 movie 根抽出扁平字段（供 MDCx 重建）。"""
    num = _el_text_raw(src.find("num")) or str(code_fallback or "").strip()
    title = _el_text_raw(src.find("title"))
    original = _el_text_raw(src.find("originaltitle"))
    sorttitle = _el_text_raw(src.find("sorttitle"))
    tagline = _el_text_raw(src.find("tagline"))
    studio = _el_text_raw(src.find("studio")) or _el_text_raw(src.find("maker"))
    maker = _el_text_raw(src.find("maker")) or studio
    director = _el_text_raw(src.find("director"))
    runtime = _el_text_raw(src.find("runtime"))
    rating = _el_text_raw(src.find("rating"))
    plot = _el_text_raw(src.find("plot")) or _el_text_raw(src.find("outline"))
    outline = _el_text_raw(src.find("outline")) or plot
    originalplot = _el_text_raw(src.find("originalplot")) or plot
    year = _el_text_raw(src.find("year"))
    premiered = _el_text_raw(src.find("premiered")) or _el_text_raw(
        src.find("releasedate")
    )
    releasedate = _el_text_raw(src.find("releasedate")) or premiered
    release = _el_text_raw(src.find("release")) or releasedate
    cover = _el_text_raw(src.find("cover"))
    website = _el_text_raw(src.find("website"))
    series = _el_text_raw(src.find("series")) or _el_text_raw(src.find("set/name"))
    publisher = _el_text_raw(src.find("publisher")) or _el_text_raw(src.find("label"))
    label = _el_text_raw(src.find("label")) or publisher
    poster = _el_text_raw(src.find("poster")) or "poster.jpg"
    thumb = _el_text_raw(src.find("thumb")) or "thumb.jpg"
    fanart = _el_text_raw(src.find("fanart")) or "fanart.jpg"
    trailer = _el_text_raw(src.find("trailer"))
    countrycode = _el_text_raw(src.find("countrycode")) or "JP"
    customrating = _el_text_raw(src.find("customrating")) or "JP-18+"
    mpaa = _el_text_raw(src.find("mpaa")) or customrating or "JP-18+"
    criticrating = _el_text_raw(src.find("criticrating"))

    raw_tags = _texts_all(src, "tag")
    raw_genres = _texts_all(src, "genre")
    raw_actors = _actor_names(src)
    raw_actor_all = _texts_all(src, "actor_all")

    for item in [*raw_tags, *raw_genres]:
        m = _TAG_META_PREFIX_RE.match(item)
        if not m:
            continue
        kind = m.group(1)
        val = item[m.end() :].strip()
        if not val:
            continue
        if kind in {"片商", "厂牌", "廠牌", "制作", "製作"} and not studio:
            studio = val
            maker = maker or val
        elif kind in {"系列"} and not series:
            series = val
        elif kind in {"发行", "發行"} and not publisher:
            publisher = val
            label = label or val
        elif kind in {"导演", "導演"} and not director:
            director = val

    # 按 NFO <actor> / actor_all 原文保留
    actors = [str(a).strip() for a in raw_actors if str(a).strip()]
    if not actors and raw_actor_all:
        actors = [str(a).strip() for a in raw_actor_all if str(a).strip()]
    _seen_a: set[str] = set()
    _uniq_a: list[str] = []
    for a in actors:
        k = a.casefold()
        if k in _seen_a:
            continue
        _seen_a.add(k)
        _uniq_a.append(a)
    actors = _uniq_a[:_MAX_LIST]

    # 类型池：原 genre/tag，去掉元数据前缀 / 女优 / 纯前缀（重建时再补）
    actor_fold = {a.casefold() for a in actors}
    pref = _num_prefix(num)
    genres: list[str] = []
    gseen: set[str] = set()
    for item in [*raw_genres, *raw_tags]:
        s = str(item or "").strip()
        if not s or _TAG_META_PREFIX_RE.match(s):
            continue
        if s.casefold() in actor_fold:
            continue
        if pref and s.upper() == pref:
            continue
        if num and s.upper() == num.upper():
            continue
        key = s.casefold()
        if key in gseen:
            continue
        gseen.add(key)
        genres.append(s)

    if not year and premiered and len(premiered) >= 4 and premiered[:4].isdigit():
        year = premiered[:4]
    if not tagline and premiered:
        tagline = f"发行日期: {premiered}"
    if not sorttitle:
        sorttitle = original or title
    if not criticrating and rating:
        _, criticrating, _ = _rating_derived(rating)

    ratings_value = ""
    ratings_el = src.find("ratings/rating/value")
    if ratings_el is not None:
        ratings_value = _el_text_raw(ratings_el)
    if not ratings_value and rating:
        _, _, ratings_value = _rating_derived(rating)

    return {
        "num": num,
        "title": title,
        "originaltitle": original,
        "sorttitle": sorttitle,
        "tagline": tagline,
        "countrycode": countrycode,
        "customrating": customrating,
        "mpaa": mpaa,
        "series": series,
        "studio": studio,
        "maker": maker or studio,
        "year": year,
        "outline": outline,
        "plot": plot,
        "originalplot": originalplot,
        "runtime": runtime,
        "director": director,
        "poster": poster,
        "thumb": thumb,
        "fanart": fanart,
        "trailer": trailer,
        "actors": actors,
        "publisher": publisher,
        "label": label or publisher,
        "genres": genres,
        "premiered": premiered,
        "releasedate": releasedate,
        "release": release,
        "rating": rating,
        "criticrating": criticrating,
        "ratings_value": ratings_value,
        "cover": cover,
        "website": website,
    }


def build_mdcx_nfo_root(fields: dict[str, Any]) -> ET.Element:
    """按参考库字段顺序组装 movie 根（写出用）。"""
    f = fields or {}
    num = str(f.get("num") or "").strip()
    title = _with_code_prefix(str(f.get("title") or ""), num)
    original = _with_code_prefix(str(f.get("originaltitle") or ""), num) or title
    sorttitle = str(f.get("sorttitle") or "").strip() or original
    if num and sorttitle and not sorttitle.upper().startswith(num.upper()):
        sorttitle = _with_code_prefix(sorttitle, num)
    premiered = str(f.get("premiered") or f.get("releasedate") or "").strip()
    releasedate = str(f.get("releasedate") or premiered).strip()
    release = str(f.get("release") or releasedate).strip()
    tagline = str(f.get("tagline") or "").strip()
    if not tagline and premiered:
        tagline = f"发行日期: {premiered}"
    studio = str(f.get("studio") or "").strip()
    maker = str(f.get("maker") or studio).strip()
    series = str(f.get("series") or "").strip()
    publisher = str(f.get("publisher") or "").strip()
    label = str(f.get("label") or publisher).strip()
    actors = [str(a).strip() for a in (f.get("actors") or []) if str(a).strip()]
    genres = [str(g).strip() for g in (f.get("genres") or []) if str(g).strip()]
    # 参考库常把系列名塞进 director；有真导演则用真导演，否则系列；都空则用片商（FC2）
    director = str(f.get("director") or "").strip() or series or studio
    tag_genre = build_mdcx_tag_genre_list(
        genres=genres,
        actors=actors,
        num=num,
        series=series,
        studio=studio,
        publisher=publisher,
        director=director,
    )
    rating = str(f.get("rating") or "").strip()
    criticrating = str(f.get("criticrating") or "").strip()
    ratings_value = str(f.get("ratings_value") or "").strip()
    if rating and (not criticrating or not ratings_value):
        r_s, c_s, j_s = _rating_derived(rating)
        rating = rating or r_s
        criticrating = criticrating or c_s
        ratings_value = ratings_value or j_s

    plot = str(f.get("plot") or "").strip()
    outline = str(f.get("outline") or plot).strip()
    originalplot = str(f.get("originalplot") or plot).strip()
    year = str(f.get("year") or "").strip()
    if not year and len(premiered) >= 4 and premiered[:4].isdigit():
        year = premiered[:4]

    movie = ET.Element("movie")
    _append_text(movie, "title", title)
    _append_text(movie, "originaltitle", original)
    _append_text(movie, "sorttitle", sorttitle)
    _append_text(movie, "tagline", tagline)
    _append_text(movie, "countrycode", str(f.get("countrycode") or "JP"))
    _append_text(movie, "customrating", str(f.get("customrating") or "JP-18+"))
    _append_text(movie, "mpaa", str(f.get("mpaa") or "JP-18+"))
    # 有系列才写 set；无系列仍保留空 <series/>（与参考库一致）
    if series:
        set_el = ET.SubElement(movie, "set")
        set_name = ET.SubElement(set_el, "name")
        set_name.text = series
    _append_text(movie, "series", series, empty_ok=True)
    _append_text(movie, "studio", studio)
    _append_text(movie, "maker", maker or studio)
    _append_text(movie, "year", year)
    _append_text(movie, "outline", outline)
    _append_text(movie, "plot", plot)
    _append_text(movie, "originalplot", originalplot)
    _append_text(movie, "runtime", str(f.get("runtime") or ""))
    _append_text(movie, "director", director)
    _append_text(movie, "poster", str(f.get("poster") or "poster.jpg"))
    _append_text(movie, "thumb", str(f.get("thumb") or "thumb.jpg"))
    _append_text(movie, "fanart", str(f.get("fanart") or "fanart.jpg"))
    _append_text(movie, "trailer", str(f.get("trailer") or ""))
    _append_actors_mdcx(movie, actors)
    # 空也写 <publisher/><label/>（FC2 参考库如此）
    _append_text(movie, "publisher", publisher, empty_ok=True)
    _append_text(movie, "label", label or publisher, empty_ok=True)
    _append_many(movie, "tag", tag_genre)
    _append_many(movie, "genre", tag_genre)
    _append_text(movie, "num", num)
    _append_text(movie, "premiered", premiered)
    _append_text(movie, "releasedate", releasedate)
    _append_text(movie, "release", release)
    # 无评分也保留空节点
    _append_text(movie, "rating", rating, empty_ok=True)
    _append_text(movie, "criticrating", criticrating, empty_ok=True)
    # ratings + 空 votes（与参考一致）
    ratings = ET.SubElement(movie, "ratings")
    rating_el = ET.SubElement(
        ratings, "rating", {"name": "javdb", "max": "5", "default": "true"}
    )
    value_el = ET.SubElement(rating_el, "value")
    if ratings_value:
        value_el.text = ratings_value
    ET.SubElement(rating_el, "votes")
    ET.SubElement(movie, "votes")
    _append_text(movie, "cover", str(f.get("cover") or ""))
    _append_text(movie, "website", str(f.get("website") or ""))
    return movie


def is_mdcx_style_nfo(root: ET.Element) -> bool:
    """粗判是否已是参考 MDCx 形态（有 CDATA 字段布局特征）。"""
    if root.find("sorttitle") is None or root.find("tagline") is None:
        return False
    if root.find("tag") is None or root.find("genre") is None:
        return False
    actor = root.find("actor")
    if actor is not None and actor.find("type") is not None:
        return True
    # 有片商:/系列: tag 也算
    tags = _texts_all(root, "tag")
    return any(_TAG_META_PREFIX_RE.match(t) for t in tags)


def build_program_nfo_root(src: ET.Element, *, code_fallback: str = "") -> ET.Element:
    """兼容旧名：改写成参考库 MDCx 布局。"""
    fields = fields_from_movie_root(src, code_fallback=code_fallback)
    return build_mdcx_nfo_root(fields)


def normalize_nfo_file(
    path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """把单个 NFO 改写成程序格式。返回 {ok, changed, path, actors, genres}。"""
    p = Path(path)
    out: dict[str, Any] = {
        "ok": False,
        "changed": False,
        "path": str(p),
        "actors": [],
        "genres": [],
        "skipped": False,
    }
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
        root = ET.fromstring(raw)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
        return out
    if root.tag.lower() != "movie" and root.find("movie") is not None:
        root = root.find("movie")  # type: ignore[assignment]
    if root is None:
        out["error"] = "no movie root"
        return out
    if not force and not is_mdcx_style_nfo(root):
        out["ok"] = True
        out["skipped"] = True
        return out

    code_fb = p.stem
    new_root = build_program_nfo_root(root, code_fallback=code_fb)
    actors = [
        _text(a.find("name"))
        for a in new_root.findall("actor")
        if a.find("name") is not None
    ]
    genres = [_text(g) for g in new_root.findall("genre")]
    out["actors"] = [a for a in actors if a]
    out["genres"] = [g for g in genres if g]
    new_xml = format_nfo_xml(new_root)
    old_norm = re.sub(r"\s+", " ", raw).strip()
    new_norm = re.sub(r"\s+", " ", new_xml.decode("utf-8", errors="replace")).strip()
    if old_norm == new_norm:
        out["ok"] = True
        out["skipped"] = True
        return out
    if not dry_run:
        write_nfo(p, new_root)
    out["ok"] = True
    out["changed"] = True
    return out


def normalize_nfo_tree(
    root_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    """批量把目录下 *.nfo 改成程序格式。"""
    base = Path(root_dir)
    changed = 0
    skipped = 0
    failed = 0
    samples: list[dict[str, Any]] = []
    n = 0
    try:
        it = base.rglob("*.nfo")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    for path in it:
        n += 1
        if limit > 0 and n > limit:
            break
        r = normalize_nfo_file(path, force=force, dry_run=dry_run)
        if not r.get("ok"):
            failed += 1
            if len(samples) < 20:
                samples.append(r)
            continue
        if r.get("changed"):
            changed += 1
            if len(samples) < 12:
                samples.append(
                    {
                        "path": r.get("path"),
                        "actors": r.get("actors"),
                        "genres": (r.get("genres") or [])[:8],
                    }
                )
        else:
            skipped += 1
    return {
        "ok": True,
        "scanned": n if limit <= 0 else min(n, limit),
        "changed": changed,
        "skipped": skipped,
        "failed": failed,
        "dryRun": bool(dry_run),
        "samples": samples,
    }
