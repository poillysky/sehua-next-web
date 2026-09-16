# -*- coding: utf-8 -*-
"""G34：单条刮削合格门禁（只读）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def evaluate_quality_gate(
    *,
    folder: Path | None = None,
    meta: dict[str, Any] | None = None,
    code: str = "",
) -> dict[str, Any]:
    """返回 hard_fail / soft / ok，对齐 E2E 八大块的可读摘要。"""
    hard: list[str] = []
    soft: list[str] = []
    info: dict[str, Any] = {}

    m = dict(meta or {})
    if folder and folder.is_dir() and not m:
        try:
            from app.scrap_library.nfo import parse_nfo

            nfo = None
            for cand in (
                folder / "movie.nfo",
                folder / f"{folder.name}.nfo",
            ):
                if cand.is_file():
                    nfo = cand
                    break
            if nfo is None:
                nfos = sorted(folder.glob("*.nfo"))
                nfo = nfos[0] if nfos else None
            if nfo:
                m = parse_nfo(nfo)
        except Exception:  # noqa: BLE001
            hard.append("nfo_unreadable")

    code_u = (
        str(code or m.get("num") or m.get("code") or "").strip().upper()
        or (folder.name.upper() if folder else "")
    )
    info["code"] = code_u
    title = str(m.get("title") or "").strip()
    plot = str(m.get("plot") or m.get("overview") or "").strip()
    actors = [str(a).strip() for a in (m.get("actors") or []) if str(a).strip()]
    studio = str(m.get("studio") or "").strip()
    tags = list(m.get("genres") or []) + list(m.get("tags") or [])

    if not title or title.upper() == code_u:
        hard.append("thin_or_empty_title")
    elif len(title) < 4:
        hard.append("thin_title")

    if not actors:
        soft.append("no_actors")
    if not plot or len(plot) < 12:
        soft.append("empty_or_short_plot")
    if not studio:
        soft.append("no_studio")

    poster_path: Path | None = None
    if folder and folder.is_dir():
        p = folder / "poster.jpg"
        if p.is_file():
            poster_path = p
    if poster_path is None:
        hard.append("missing_poster")
    else:
        try:
            from app.scrap_library.cover_scrape import analyze_local_poster

            ana = analyze_local_poster(poster_path)
            info["poster"] = {
                "width": ana.get("width"),
                "height": ana.get("height"),
                "issues": list(ana.get("issues") or []),
            }
            issues = set(ana.get("issues") or [])
            if "blank" in issues or "missing" in issues or "unreadable" in issues:
                hard.append("bad_poster")
            elif "too_small" in issues:
                # 真小图可落盘；门禁只软提示，不当硬失败
                soft.append("poster_small")
            elif "face_off" in issues:
                soft.append("poster_face_off")
            elif "landscape" in issues:
                soft.append("poster_landscape")
        except Exception as e:  # noqa: BLE001
            soft.append(f"poster_analyze_error:{e}")

    junk = 0
    for t in tags:
        s = str(t or "")
        if any(x in s for x in ("登录", "會員", "Cloudflare", "セール")):
            junk += 1
    if junk:
        soft.append("noisy_tags")

    if m.get("seller") and str(m.get("actorRole") or "") == "seller":
        soft.append("fc2_seller_as_actor")

    info["badges"] = list(m.get("badges") or [])
    info["actorsN"] = len(actors)
    info["actorsAllN"] = len(m.get("actorsAll") or [])
    info["hasTitleJa"] = bool(
        str(m.get("titleJa") or m.get("originaltitle") or "").strip()
    )
    info["hasOverviewJa"] = bool(str(m.get("overviewJa") or "").strip())

    return {
        "ok": not hard,
        "code": code_u,
        "hardFail": hard,
        "soft": soft,
        "info": info,
    }
