"""色花资源嵌入文本：板块 + 清洗标题 + 影片/资源名 + 女优 + 文件名。"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import unquote

from .pack_bleed import first_maker_code_in, get_description_field
from .scrape_forum_title import clean_forum_zh_title

from .ai_config import resolve_embed_config

DEFAULT_EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_EMBED_DIM = 512
# BGE 中文检索：只给「查询」加指令，文档侧不加
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

_EXT_RE = re.compile(r"\.(mp4|mkv|avi|wmv|iso|ts|m2ts|mov|flv|rmvb)$", re.I)
_WS_RE = re.compile(r"\s+")
_ACTOR_SPLIT_RE = re.compile(r"[,，、/|]+")
_DISCUZ_CHROME_RE = re.compile(
    r"Powered by Discuz|98堂\s*[\[【]?原?色花堂",
    re.I,
)
_MAX_EMBED_CHARS = 800
_MAX_ACTORS = 8


def normalize_filename(name: str | None) -> str:
    s = unquote(str(name or "").strip())
    s = _EXT_RE.sub("", s)
    return _WS_RE.sub(" ", s).strip()


def _fold(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", (s or "")).casefold()


def _clip(s: str, n: int = 120) -> str:
    t = _WS_RE.sub(" ", (s or "").strip())
    return t if len(t) <= n else t[: n - 1] + "…"


def _title_code(*parts: str) -> str:
    for p in parts:
        code = first_maker_code_in(p) or ""
        if code:
            return code
    return ""


def _clean_title(raw: str, code: str) -> str:
    t = str(raw or "").strip()
    if not t:
        return ""
    if _DISCUZ_CHROME_RE.search(t):
        return ""
    cleaned = clean_forum_zh_title(t, code, allow_weak=True)
    if cleaned:
        return cleaned
    return _clip(t, 80)


def display_hit_label(
    *,
    title: str | None = None,
    description: str | None = None,
    filename: str | None = None,
) -> str:
    """列表/对话展示用短标题：影片名优先，去掉 Discuz 壳。"""
    film = _film_name(description)
    resource = _resource_name(description)
    file_stem = normalize_filename(filename)
    code = _title_code(file_stem, film, resource, str(title or ""))
    heading = _clean_title(str(title or ""), code)
    label = film or heading or resource or file_stem or code
    if code and label and _fold(code) not in _fold(label):
        label = f"{code} {label}"
    return _clip(label, 72) or "资源"


def _film_name(description: str | None) -> str:
    return str(get_description_field(description, "影片名称") or "").strip()


def _resource_name(description: str | None) -> str:
    return str(get_description_field(description, "资源名称") or "").strip()


def _actors(description: str | None) -> str:
    raw = str(get_description_field(description, "出演女优") or "").strip()
    if not raw:
        return ""
    names: list[str] = []
    seen: set[str] = set()
    for part in _ACTOR_SPLIT_RE.split(raw):
        n = part.strip(" .　·・")
        if not n or len(n) > 16:
            continue
        key = _fold(n)
        if not key or key in seen:
            continue
        seen.add(key)
        names.append(n)
        if len(names) >= _MAX_ACTORS:
            break
    return " ".join(names)


def build_embed_text(
    *,
    board_name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    filename: str | None = None,
) -> str:
    """拼一条送进嵌入模型的文本。缺字段就跳过该行，保证全库都能出文本。"""
    board = _clip(str(board_name or ""), 40)
    file_stem = normalize_filename(filename)
    film = _film_name(description)
    resource = _resource_name(description)
    actors = _actors(description)
    code = _title_code(file_stem, film, resource, str(title or ""))
    heading = _clean_title(str(title or ""), code)

    lines: list[str] = []
    if board:
        lines.append(f"板块：{board}")
    if heading:
        lines.append(f"标题：{heading}")

    film_f = _fold(film)
    head_f = _fold(heading)
    if film and film_f and film_f != head_f:
        lines.append(f"影片：{_clip(film)}")

    res_f = _fold(resource)
    if resource and res_f and res_f != film_f and res_f != head_f:
        lines.append(f"资源：{_clip(resource)}")

    if actors:
        lines.append(f"女优：{actors}")

    file_f = _fold(file_stem)
    already = " ".join(lines)
    if file_stem and file_f and file_f not in _fold(already):
        lines.append(f"文件：{_clip(file_stem, 80)}")

    text = "\n".join(lines).strip()
    if not text:
        text = file_stem or _clip(str(title or ""), 80) or "资源"
    if len(text) > _MAX_EMBED_CHARS:
        text = text[:_MAX_EMBED_CHARS]
    return text


def content_sha(
    source_text: str,
    *,
    model: str | None = None,
    dim: int | None = None,
) -> str:
    cfg = resolve_embed_config()
    m = model or str(cfg["model"])
    d = int(dim if dim is not None else cfg["dim"])
    payload = f"{m}\n{d}\n{source_text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def row_embed_payload(row: dict[str, Any]) -> dict[str, str]:
    cfg = resolve_embed_config()
    model = str(cfg["model"])
    dim = int(cfg["dim"])
    source_text = build_embed_text(
        board_name=row.get("board_name"),
        title=row.get("title"),
        description=row.get("description"),
        filename=row.get("filename"),
    )
    return {
        "hash": str(row.get("hash") or ""),
        "source_text": source_text,
        "content_sha": content_sha(source_text, model=model, dim=dim),
    }


def format_query_text(query: str) -> str:
    q = _WS_RE.sub(" ", str(query or "").strip())
    if not q:
        return ""
    return QUERY_INSTRUCTION + q
