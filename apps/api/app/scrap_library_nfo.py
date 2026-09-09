# -*- coding: utf-8 -*-
"""刮削库 Emby/Kodi NFO 解析 → 嵌入文本。"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .ai_config import resolve_embed_config

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


def item_id_from_rel(rel: str) -> str:
    return str(rel or "").replace("\\", "/").strip().strip("/")
