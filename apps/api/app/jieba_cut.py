"""jieba POS cut — aligned with sehua-search lib/jieba.ts (@node-rs/jieba)."""

from __future__ import annotations

REQUIRED_TAGS = frozenset({"n", "nr", "ns", "nt", "nz", "vn", "x"})


def jieba_cut(text: str) -> list[dict[str, object]]:
    t = (text or "").strip()
    if not t:
        return []
    try:
        import jieba.posseg as pseg
    except ImportError:
        return [{"keyword": t, "required": True}]

    out: list[dict[str, object]] = []
    for w in pseg.cut(t):
        word = (w.word or "").strip()
        if not word:
            continue
        out.append(
            {
                "keyword": word,
                "required": w.flag in REQUIRED_TAGS,
            }
        )
    return out or [{"keyword": t, "required": True}]
