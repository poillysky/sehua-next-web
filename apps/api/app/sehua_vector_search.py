"""色花资源 pgvector 语义检索。"""

from __future__ import annotations

from typing import Any

from .ai_config import resolve_embed_config
from .ai_embed import encode_texts_async
from . import pg
from .resource_format import (
    PUBLIC_RESOURCE_FILTER,
    RESOURCE_SELECT,
    SOURCE_META_JOIN,
    format_resources,
)

SEARCH_SQL = """
SELECT
  e.hash,
  1 - (e.embedding <=> %s::vector) AS score
FROM sehua_resource_embed e
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
FROM sehua_resource_embed
"""


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.7f}" for x in vec) + "]"


def embed_stats() -> dict[str, Any]:
    try:
        rows = pg.query(STATS_SQL)
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


def resources_by_hashes(hashes: list[str]) -> list[dict[str, Any]]:
    if not hashes:
        return []
    placeholders = ",".join(["%s"] * len(hashes))
    sql = f"""
SELECT {RESOURCE_SELECT}
FROM ed2k_resources r
{SOURCE_META_JOIN}
WHERE r.hash IN ({placeholders})
{PUBLIC_RESOURCE_FILTER}
"""
    rows = pg.query(sql, hashes)
    formatted = format_resources(rows, prefetch_torrents=False)
    by_hash = {str(item.get("hash") or "").upper(): item for item in formatted}
    out: list[dict[str, Any]] = []
    for h in hashes:
        item = by_hash.get(str(h).upper())
        if item:
            out.append(item)
    return out


async def search_semantic(query: str) -> dict[str, Any]:
    """返回 {ok, reason, resources, scores, total}。失败不抛，由调用方回退关键词。"""
    q = str(query or "").strip()
    if len(q) < 2:
        return {"ok": False, "reason": "query-short", "resources": [], "total": 0}

    cfg = resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        return {"ok": False, "reason": "embed-disabled", "resources": [], "total": 0}

    stats = embed_stats()
    if not stats.get("ok"):
        return {"ok": False, "reason": "empty", "resources": [], "total": 0}

    qdim = int(cfg.get("dim") or 0)
    stored_dim = int(stats.get("dim") or 0)
    if stored_dim and qdim and stored_dim != qdim:
        return {
            "ok": False,
            "reason": "dim-mismatch",
            "resources": [],
            "total": 0,
            "storedDim": stored_dim,
            "queryDim": qdim,
            "embedCount": int(stats.get("n") or 0),
        }

    top_k = int(cfg.get("topK") or 8)
    top_k = max(1, min(20, top_k))
    min_score = float(cfg.get("minScore") or 0.35)

    try:
        vecs = await encode_texts_async([q], query=True)
    except Exception as e:
        return {"ok": False, "reason": f"embed-error:{e}", "resources": [], "total": 0}

    if not vecs or not vecs[0]:
        return {"ok": False, "reason": "embed-empty", "resources": [], "total": 0}

    vec = vecs[0]
    if qdim and len(vec) != qdim:
        qdim = len(vec)
    lit = _vec_literal(vec)
    try:
        hits = pg.query(SEARCH_SQL, [lit, qdim or stored_dim, lit, top_k * 2])
    except Exception as e:
        return {"ok": False, "reason": f"pg-error:{e}", "resources": [], "total": 0}

    scored: list[tuple[str, float]] = []
    for row in hits:
        h = str(row.get("hash") or "").strip()
        score = float(row.get("score") or 0)
        if h and score >= min_score:
            scored.append((h, score))
        if len(scored) >= top_k:
            break

    if not scored:
        return {
            "ok": False,
            "reason": "below-min-score",
            "resources": [],
            "total": 0,
            "embedCount": int(stats.get("n") or 0),
        }

    resources = resources_by_hashes([h for h, _ in scored])
    score_map = {h.upper(): s for h, s in scored}
    for item in resources:
        item["score"] = score_map.get(str(item.get("hash") or "").upper())

    return {
        "ok": True,
        "reason": "ok",
        "resources": resources,
        "total": len(resources),
        "embedCount": int(stats.get("n") or 0),
        "minScore": min_score,
    }
