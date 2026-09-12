# -*- coding: utf-8 -*-
"""刮削库 Emby/Kodi NFO 解析 → 嵌入文本。"""

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


def parse_nfo(path: Path) -> dict[str, Any]:
    """解析 movie NFO；失败返回空 dict。"""
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
    studio = _text(root.find("studio")) or _text(root.find("maker"))
    publisher = _text(root.find("publisher")) or _text(root.find("label"))
    year = _text(root.find("year"))
    premiered = _text(root.find("premiered")) or _text(root.find("releasedate"))
    genres = _texts(root, "genre")
    tags = _texts(root, "tag")
    actors = _actor_names(root)
    cover_url = _text(root.find("cover"))
    poster = _text(root.find("poster")) or "poster.jpg"
    thumb = _text(root.find("thumb")) or "thumb.jpg"
    fanart = _text(root.find("fanart")) or "fanart.jpg"

    # 去掉与 genre 重复的 tag，以及「片商:」「发行:」前缀噪音过多时仍保留
    genre_fold = {g.casefold() for g in genres}
    tags = [t for t in tags if t.casefold() not in genre_fold][:_MAX_LIST]

    return {
        "num": num,
        "title": title,
        "originaltitle": original,
        "plot": plot,
        "studio": studio,
        "publisher": publisher,
        "year": year,
        "premiered": premiered,
        "genres": genres,
        "tags": tags,
        "actors": actors,
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
    # 入库前滤掉类型标签 / 登录页噪声，并映射标准女优名、排除导演
    try:
        from app.scrap_library.enrich import _clean_actors
        from app.scrape.metadata_optimize import polish_actress_names

        actors = _clean_actors(actors)
        directors: list[str] = []
        for key in ("director",):
            d = str(meta.get(key) or "").strip()
            if d:
                directors.append(d)
        actors = polish_actress_names(actors, exclude=directors)
    except Exception:  # noqa: BLE001
        pass
    # 仅排除片商/发行商撞名；类型/标签里常带真名，不能当女优黑名单
    skip = {studio.casefold(), publisher.casefold()} - {""}
    actors = [a for a in actors if a.casefold() not in skip]

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
    if plot:
        # 详情页从 source_text 解析剧情；过短会截断译中结果
        lines.append(f"剧情：{_clip(plot, 1800)}")

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
    """对 source_text 女优行做标准名映射 + 排除导演/男优（刮削/同步自动调用）。"""
    text = str(source_text or "")
    if not text or "女优：" not in text:
        return text
    try:
        from app.scrap_library.enrich import _clean_actors
        from app.scrape.metadata_optimize import polish_actress_names
    except Exception:  # noqa: BLE001
        return text

    studio_m = _STUDIO_LINE_RE.search(text)
    publisher_m = _PUBLISHER_LINE_RE.search(text)
    ban = {
        str(x).strip()
        for x in (exclude or [])
        if str(x or "").strip()
    }
    ban |= {
        str(studio_m.group(1) if studio_m else "").strip(),
        str(publisher_m.group(1) if publisher_m else "").strip(),
    } - {""}

    def _repl(m: re.Match[str]) -> str:
        parts = [p for p in re.split(r"[\s、,/|]+", m.group(2).strip()) if p.strip()]
        cleaned = _clean_actors(parts)
        polished = polish_actress_names(cleaned, exclude=list(ban))
        if not polished:
            return ""
        return f"{m.group(1)}{' '.join(polished[:8])}"

    out = _ACTRESS_LINE_RE.sub(_repl, text)
    return re.sub(r"\n{2,}", "\n", out).strip()


def item_id_from_rel(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip().strip("/")


def format_nfo_xml(root: ET.Element) -> bytes:
    """NFO 易读输出：每个字段单独一行（含声明与末尾换行）。"""
    # 去掉旧缩进残留，再统一排版
    for el in root.iter():
        if el.text is not None:
            t = el.text.strip()
            el.text = t if t else None
        if el.tail is not None:
            el.tail = None
    try:
        ET.indent(root, space="  ")
    except AttributeError:
        # Python <3.9 兜底：至少保证根下子节点分行
        pass
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if not payload.endswith(b"\n"):
        payload += b"\n"
    return payload


def write_nfo(path: Path, root: ET.Element) -> None:
    """写入易读 NFO（字段分行）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(format_nfo_xml(root))
