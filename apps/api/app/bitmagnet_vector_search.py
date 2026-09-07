"""Bitmagnet pgvector 语义检索。"""

from __future__ import annotations

from typing import Any

from .ai_config import resolve_embed_config
from .ai_embed import encode_texts_async
from . import bitmagnet_client, bitmagnet_pg

SEARCH_SQL = """
SELECT
  e.info_hash,
  1 - (e.embedding <=> %s::vector) AS score
FROM bitmagnet_torrent_embed e
WHERE e.dim = %s
ORDER BY e.embedding <=> %s::vector
LIMIT %s
"""

STATS_SQL = """
SELECT
  count(*)::int AS n,
  min(dim)::int AS dim,
  max(dim)::int AS dim_max,
  min(model) AS model
FROM bitmagnet_torrent_embed
"""


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


def embed_stats() -> dict[str, Any]:
    try:
        rows = bitmagnet_pg.query(STATS_SQL)
    except Exception:
        return {"n": 0, "dim": 0, "ok": False}
    row = rows[0] if rows else {}
    n = int(row.get("n") or 0)
    return {
        "n": n,
        "dim": int(row.get("dim") or 0),
        "dimMax": int(row.get("dim_max") or 0),
        "model": str(row.get("model") or ""),
        "ok": n > 0,
    }


async def search_semantic(query: str) -> dict[str, Any]:
    """返回 {ok, reason, items, scores, total}，items 对齐 magnet 列表结构。"""
    q = str(query or "").strip()
    if len(q) < 2:
        return {"ok": False, "reason": "query-short", "items": [], "total": 0}

    cfg = resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        return {"ok": False, "reason": "embed-disabled", "items": [], "total": 0}

    if not bitmagnet_pg.is_configured():
        return {"ok": False, "reason": "bitmagnet-unconfigured", "items": [], "total": 0}

    stats = embed_stats()
    if not stats.get("ok"):
        return {"ok": False, "reason": "empty", "items": [], "total": 0}

    qdim = int(cfg.get("dim") or 0)
    stored_dim = int(stats.get("dim") or 0)
    if stored_dim and qdim and stored_dim != qdim:
        return {
            "ok": False,
            "reason": "dim-mismatch",
            "items": [],
            "total": 0,
            "storedDim": stored_dim,
            "queryDim": qdim,
        }

    top_k = int(cfg.get("topK") or 8)
    top_k = max(1, min(20, top_k))
    min_score = float(cfg.get("minScore") or 0.35)

    try:
        vecs = await encode_texts_async([q], query=True)
    except Exception as e:
        return {"ok": False, "reason": f"embed-error:{e}", "items": [], "total": 0}

    if not vecs or not vecs[0]:
        return {"ok": False, "reason": "embed-empty", "items": [], "total": 0}

    vec = vecs[0]
    if qdim and len(vec) != qdim:
        qdim = len(vec)

    lit = _vec_literal(vec)
    try:
        hits = bitmagnet_pg.query(SEARCH_SQL, [lit, qdim or stored_dim or 1024, lit, top_k * 2])
    except Exception as e:
        return {"ok": False, "reason": f"search-error:{e}", "items": [], "total": 0}

    scored: list[tuple[str, float]] = []
    for row in hits:
        h = str(row.get("info_hash") or "").strip().lower()
        score = float(row.get("score") or 0)
        if h and score >= min_score:
            scored.append((h, score))
        if len(scored) >= top_k:
            break

    items: list[dict[str, Any]] = []
    scores: dict[str, float] = {}
    for h, score in scored:
        try:
            detail = bitmagnet_client.get(h)
        except Exception:
            detail = {
                "hash": h,
                "infoHash": h,
                "info_hash": h,
                "name": h,
                "title": h,
            }
        detail = dict(detail)
        detail["score"] = score
        detail["hash"] = h
        detail["infoHash"] = h
        items.append(detail)
        scores[h] = score

    return {
        "ok": True,
        "reason": "ok",
        "items": items,
        "scores": scores,
        "total": len(items),
        "mode": "semantic",
    }
