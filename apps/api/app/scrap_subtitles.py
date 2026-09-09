# -*- coding: utf-8 -*-
"""刮削库本地字幕：搜索下载到番号目录，供 115 转存附带上传。

规则：
- 只要中文（简繁）；非中文不保存、不上传
- 本地/上传文件名：ABC-123.srt（番号 + 扩展名）
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from . import scrap_library_embed as scrap
from . import subtitlecat
from .db import get_meta_pool

log = logging.getLogger(__name__)

_SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sup"}


def _safe_code_filename(code: str) -> str:
    """规范为 ABC-123 风格文件名主体。"""
    raw = str(code or "").strip().upper()
    raw = re.sub(r"[\s_]+", "-", raw)
    raw = re.sub(r"[^\w.\-]+", "", raw, flags=re.UNICODE)
    # SSIS949 → SSIS-949
    m = re.match(r"^([A-Z]{2,12})(\d{2,6})$", raw.replace("-", ""))
    if m:
        raw = f"{m.group(1)}-{m.group(2)}"
    return (raw or "subtitle")[:80]


def upload_filename_for_code(code: str, path: Path | str) -> str:
    """115 上传名：ABC-123.srt（番号 + 扩展名，不加语言后缀）。"""
    ext = Path(path).suffix.lower() or ".srt"
    if ext not in _SUB_EXTS:
        ext = ".srt"
    base = _safe_code_filename(code)
    return f"{base}{ext}"


def item_folder_from_row(row: dict[str, Any]) -> Path:
    rel = str(row.get("rel_path") or "").strip().replace("\\", "/")
    root = scrap.resolve_root(scrap.get_settings().get("root"))
    folder = (root / rel).resolve()
    folder.relative_to(root.resolve())
    return folder


def _is_chinese_local_file(path: Path) -> bool:
    name = path.name
    lang = subtitlecat._lang_from_name(name)
    if lang and not subtitlecat.is_chinese_lang(lang) and lang not in ("", "und"):
        return False
    if subtitlecat._ZH_NAME_HINT.search(name) or subtitlecat.is_chinese_lang(lang):
        return True
    # 无语言标记：读内容（Emby 友好名 ABC-123.srt）
    try:
        data = path.read_bytes()[:64 * 1024]
    except OSError:
        return False
    return subtitlecat.looks_chinese_subtitle(data, filename=name)


def list_local_subtitles(
    folder: Path, *, chinese_only: bool = True
) -> list[dict[str, Any]]:
    if not folder.is_dir():
        return []
    out: list[dict[str, Any]] = []
    try:
        for p in sorted(folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() not in _SUB_EXTS:
                continue
            if chinese_only and not _is_chinese_local_file(p):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            out.append(
                {
                    "name": p.name,
                    "path": str(p),
                    "size": size,
                    "rel": scrap._media_rel(p),
                }
            )
    except OSError:
        return []
    return out


def _load_item(
    *,
    item_id: str = "",
    code: str = "",
) -> dict[str, Any] | None:
    scrap.ensure_schema()
    pool = get_meta_pool()
    iid = str(item_id or "").strip()
    code_q = str(code or "").strip()
    with pool.connection() as conn, conn.cursor() as cur:
        if iid:
            cur.execute(
                f"""
                SELECT item_id, region, prefix, code, rel_path, title, cover_url
                FROM {scrap.TABLE}
                WHERE item_id = %s
                LIMIT 1
                """,
                (iid,),
            )
            row = cur.fetchone()
            if row:
                return dict(row) if isinstance(row, dict) else None
        if code_q:
            cur.execute(
                f"""
                SELECT item_id, region, prefix, code, rel_path, title, cover_url
                FROM {scrap.TABLE}
                WHERE upper(code) = upper(%s)
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 1
                """,
                (code_q,),
            )
            row = cur.fetchone()
            if row:
                return dict(row) if isinstance(row, dict) else None
    return None


def normalize_srt_bytes(data: bytes) -> bytes:
    """修正常见坏 SRT，并统一为 UTF-8：
    - 全角冒号 ：→ :
    - 毫秒用点 → 逗号
    - 箭头 -> → 标准 -->
    """
    if not data:
        return data
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            text = data.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        return data
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 全角冒号 → ASCII（时间轴里最常见）
    text = text.replace("\uff1a", ":")
    # 00:00:15.410-> 00:00:17.410  /  --> 且毫秒用点
    text = re.sub(
        r"(?m)^(\d{2}:\d{2}:\d{2})\.(\d{3})\s*-+>\s*(\d{2}:\d{2}:\d{2})\.(\d{3})\s*$",
        r"\1,\2 --> \3,\4",
        text,
    )
    # 已是逗号毫秒但箭头写成 ->
    text = re.sub(
        r"(?m)^(\d{2}:\d{2}:\d{2}),(\d{3})\s*-+>\s*(\d{2}:\d{2}:\d{2}),(\d{3})\s*$",
        r"\1,\2 --> \3,\4",
        text,
    )
    # 统一 UTF-8（播放器/Emby 最稳）
    return text.encode("utf-8")


def prepare_subtitle_for_upload(path: Path | str) -> tuple[Path, bool]:
    """上传前规范化本地字幕并回写。返回 (path, changed)。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    if p.suffix.lower() != ".srt":
        return p, False
    raw = p.read_bytes()
    fixed = normalize_srt_bytes(raw)
    if fixed == raw:
        return p, False
    tmp = p.with_suffix(p.suffix + ".part")
    tmp.write_bytes(fixed)
    tmp.replace(p)
    log.info("normalized srt before upload: %s (%d -> %d bytes)", p.name, len(raw), len(fixed))
    return p, True


def save_subtitle_bytes(
    folder: Path,
    *,
    code: str,
    data: bytes,
    lang: str = "zh",
    preferred_name: str = "",
) -> Path:
    """保存为 ABC-123.srt（只要中文；不加 .chi / .chs 语言后缀）。"""
    if not subtitlecat.is_chinese_lang(lang) and not subtitlecat.looks_chinese_subtitle(
        data, filename=preferred_name
    ):
        raise ValueError("非中文字幕，已拒绝保存")
    folder.mkdir(parents=True, exist_ok=True)
    base = _safe_code_filename(code)
    ext = ".srt"
    prefer = (preferred_name or "").lower()
    for cand in (".ass", ".ssa", ".vtt"):
        if prefer.endswith(cand):
            ext = cand
            break
    payload = data
    if ext == ".srt":
        payload = normalize_srt_bytes(data)
    dest = folder / f"{base}{ext}"
    # 清掉旧的语言后缀文件，避免同目录 ABC-123.chi.srt 残留
    for legacy in folder.glob(f"{base}.*{ext}"):
        if legacy.name.lower() == dest.name.lower():
            continue
        stem = legacy.name[: -len(ext)].lower()
        if stem.startswith(base.lower() + ".") and stem[len(base) + 1 :] in {
            "chi",
            "chs",
            "cht",
            "zh",
            "zh-cn",
            "cn",
        }:
            try:
                legacy.unlink(missing_ok=True)
            except OSError:
                pass
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(payload)
    tmp.replace(dest)
    return dest


def fetch_and_save_for_item(
    *,
    item_id: str = "",
    code: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """搜 SubtitleCat → 写入刮削番号目录。仅中文；已有中文字幕且非 force 则跳过。"""
    row = _load_item(item_id=item_id, code=code)
    if not row:
        return {"ok": False, "reason": "item_not_found"}
    folder = item_folder_from_row(row)
    code_s = str(row.get("code") or code or "").strip()
    local = list_local_subtitles(folder, chinese_only=True)
    if local and not force:
        return {
            "ok": True,
            "skipped": True,
            "code": code_s,
            "itemId": row.get("item_id"),
            "files": local,
            "message": f"本地已有 {len(local)} 个中文字幕",
        }
    if not code_s:
        return {"ok": False, "reason": "no_code"}

    try:
        got = subtitlecat.fetch_best_for_query(code_s)
    except subtitlecat.SubtitleFetchError as e:
        return {
            "ok": False,
            "reason": "network",
            "code": code_s,
            "files": local,
            "message": str(e),
        }
    except Exception as e:  # noqa: BLE001
        log.exception("subtitle fetch")
        return {
            "ok": False,
            "reason": "error",
            "code": code_s,
            "files": local,
            "message": f"搜字幕异常：{e}",
        }
    if not got:
        return {
            "ok": False,
            "reason": "not_found",
            "code": code_s,
            "files": local,
            "message": f"未找到「{code_s}」中文字幕（已试 SubtitleCat / 迅雷 / Assrt / SubHD）",
        }

    try:
        path = save_subtitle_bytes(
            folder,
            code=code_s,
            data=got["bytes"],
            lang=str(got.get("lang") or "zh"),
            preferred_name=str(got.get("filename") or ""),
        )
    except ValueError as e:
        return {
            "ok": False,
            "reason": "not_chinese",
            "code": code_s,
            "files": local,
            "message": str(e),
        }
    files = list_local_subtitles(folder, chinese_only=True)
    src = str(got.get("source") or "")
    sc = got.get("score")
    extra = f" · {src}" if src else ""
    if sc is not None:
        extra += f" · score {sc}"
    return {
        "ok": True,
        "skipped": False,
        "code": code_s,
        "itemId": row.get("item_id"),
        "saved": path.name,
        "lang": got.get("lang"),
        "source": got.get("source"),
        "score": got.get("score"),
        "candidates": got.get("candidates"),
        "title": got.get("title"),
        "files": files,
        "message": f"已保存中文字幕 {path.name}{extra}",
    }


def local_subs_for_code_or_item(
    *,
    item_id: str = "",
    code: str = "",
) -> dict[str, Any]:
    row = _load_item(item_id=item_id, code=code)
    if not row:
        return {"ok": False, "reason": "item_not_found", "files": []}
    folder = item_folder_from_row(row)
    files = list_local_subtitles(folder, chinese_only=True)
    return {
        "ok": True,
        "itemId": row.get("item_id"),
        "code": row.get("code"),
        "region": row.get("region"),
        "relPath": row.get("rel_path"),
        "folder": str(folder),
        "files": files,
    }
