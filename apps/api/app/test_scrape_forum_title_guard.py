"""标题清洗 / 假壳：防误伤回归。"""

from __future__ import annotations

from app.scrape_forum_title import (
    clean_forum_zh_title,
    is_fake_forum_title,
    is_fake_forum_title_fast,
    is_indexable_forum_title,
)


def test_bare_words_not_fake():
    """写真/共演/合集/封面裸词不应单独判假。"""
    for t in (
        "姐妹共演",
        "人体写真",
        "封面女郎的秘密",
        "整理房间的女人",
        "禁忌合集夜曲",
    ):
        assert not is_fake_forum_title_fast(t), t
        assert not is_fake_forum_title(t), t
        out = clean_forum_zh_title(t, "SSIS-001")
        assert out, f"cleaned empty: {t!r} -> {out!r}"


def test_collection_shell_still_fake():
    shells = (
        "含单体+共演+写真 截止SSIS",
        "单体+共演+写真集",
        "共演+写真 原档+竖版",
        "合集更新至 SSIS-100",
    )
    for t in shells:
        assert is_fake_forum_title_fast(t) or is_fake_forum_title(t), t


def test_latest_girlfriend_kept():
    out = clean_forum_zh_title("最新女友的秘密", "START-001")
    assert "最新女友" in out or out == "最新女友的秘密", out


def test_rabbit_sensei_in_plot_kept():
    out = clean_forum_zh_title("我的兔子先生", "MDX-001")
    assert "兔子先生" in out, out


def test_rabbit_sensei_leading_stripped():
    out = clean_forum_zh_title("兔子先生 放学后的秘密", "MDX-002")
    assert not out.startswith("兔子先生"), out
    assert "秘密" in out, out


def test_liuchu_plot_tail_kept():
    out = clean_forum_zh_title("少女流出", "FC2-123")
    assert out == "少女流出" or "少女" in out and "流出" in out, out


def test_uncensored_liuchu_tail_stripped():
    out = clean_forum_zh_title("放学后的约定无码流出", "FC2-124")
    assert not out.endswith("流出"), out
    assert "约定" in out or "約定" in out, out


def test_short_zh_indexable():
    assert is_indexable_forum_title("绿帽", "ABC-001")
    assert is_indexable_forum_title("上海滩", "ABC-002")


def test_leading_episode_ord_stripped():
    assert clean_forum_zh_title("2郝叔叔和他的女人", "MDSR-013").startswith("郝叔叔")
    assert clean_forum_zh_title("1《警探姐妹花》续", "MDSR-010").startswith("《警探")
    out = clean_forum_zh_title("情色文学作品❤ -1极品嫂子", "MDSR-009")
    assert "极品嫂子" in out and "-1" not in out
    assert clean_forum_zh_title("18岁的秘密", "MD-001") == "18岁的秘密"


def test_orphan_paren_date_prefix_stripped():
    """麻豆傳媒)(mdwp-0033)(20230104)… → 不残留 ) (日期)。"""
    raw = "【BT种子】麻豆傳媒)(mdwp-0033)(20230104)淫行KTV-趙曉涵"
    out = clean_forum_zh_title(raw, "MDWP-0033")
    assert not out.startswith(")"), out
    assert "20230104" not in out, out
    assert "淫行KTV" in out, out

    raw2 = "【BT种子】麻豆傳媒)(mdwp-0031)(20230108)淫行日漫店-姚宛兒"
    out2 = clean_forum_zh_title(raw2, "MDWP-0031")
    assert out2.startswith("淫行"), out2

    # 已入库坏题 / 片商残括号 + 日期壳
    assert clean_forum_zh_title(") (20230104)淫行KTV-赵晓涵", "MDWP-0033").startswith(
        "淫行"
    )
    sat = clean_forum_zh_title(
        "SA國際傳媒) (20230105)戀上冥婚美人兒 2-溫芮欣", "SAT-0049"
    )
    assert not sat.startswith("SA"), sat
    assert "20230105" not in sat, sat
    assert "冥婚" in sat or "戀上" in sat, sat


if __name__ == "__main__":
    test_bare_words_not_fake()
    test_collection_shell_still_fake()
    test_latest_girlfriend_kept()
    test_rabbit_sensei_in_plot_kept()
    test_rabbit_sensei_leading_stripped()
    test_liuchu_plot_tail_kept()
    test_uncensored_liuchu_tail_stripped()
    test_short_zh_indexable()
    test_leading_episode_ord_stripped()
    test_orphan_paren_date_prefix_stripped()
    print("ok")
