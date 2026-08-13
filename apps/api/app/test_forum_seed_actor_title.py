"""女优名不可盖掉日文正片标题。"""

from __future__ import annotations

from .forum_seed import (
    _finalize_seed_title,
    _looks_like_bare_actor_title,
    _score_zh_title,
    _title_is_actor_echo,
    pick_forum_seed_from_posts,
)


def test_bare_actor_title_not_scored_as_zh():
    assert _looks_like_bare_actor_title("木村愛心")
    assert _score_zh_title("木村愛心", needle="SONE-994") < 0


def test_real_short_zh_title_still_scored():
    # 含剧情/内容提示词，不当人名
    assert not _looks_like_bare_actor_title("少女流出")
    assert _score_zh_title("少女流出", needle="FC2-1") >= 0


def test_actor_echo():
    assert _title_is_actor_echo("木村愛心", ["木村愛心"])
    assert not _title_is_actor_echo("无胸罩走光", ["木村愛心"])


def test_finalize_drops_bare_actor_even_without_ja():
    assert (
        _finalize_seed_title(
            best_zh="木村愛心",
            best_zh_score=249,
            best_ja="",
            best_ja_score=-1,
            actors=["木村愛心"],
        )
        == ""
    )
    assert (
        _finalize_seed_title(
            best_zh="花咲澪",
            best_zh_score=100,
            best_ja="",
            best_ja_score=-1,
            actors=["金松季歩"],
        )
        == ""
    )


def test_finalize_prefers_ja_over_actor_name():
    ja = "ノーブラ！ポロリ！透け乳首！死ぬほどシコれるLcup"
    out = _finalize_seed_title(
        best_zh="木村愛心",
        best_zh_score=249,
        best_ja=ja,
        best_ja_score=50,
        actors=["木村愛心"],
    )
    assert out == ja


def test_pick_seed_keeps_japanese_when_zh_is_actress():
    ja = (
        "ノーブラ！ポロリ！透け乳首！死ぬほどシコれるLcup"
        "エロスシチュエーション無防備着衣おっぱいで全力誘惑！木村愛心"
    )
    seed = pick_forum_seed_from_posts(
        "SONE-994",
        [
            {
                "title": f"【磁力】SONE-994 {ja}",
                "description": "【出演女优】木村愛心\n【影片名称】木村愛心",
            },
            {
                "title": f"SONE-994 {ja}",
                "description": "【出演女优】木村愛心",
            },
        ],
        want_actors=True,
    )
    assert seed["actors"] == ["木村愛心"]
    assert "ノーブラ" in seed["title"]
    assert seed["title"] != "木村愛心"
