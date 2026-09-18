"""女优清洗：DMM独家过滤；かをり不被当句子；禁止标签升格女优。"""

from __future__ import annotations

from app.scrap_library.enrich import (
    _actors_lifted_from_tags,
    _clean_actors,
    _clean_tags,
    _is_platform_exclusivity_label,
    _looks_like_act_tag_token,
    _looks_like_actor_sentence_frag,
    _looks_like_person_name_tag,
    _title_trailing_person_name,
)


def test_dmm_exclusive_not_actress():
    assert _is_platform_exclusivity_label("DMM独家")
    assert _is_platform_exclusivity_label("FANZA独占")
    assert "DMM独家" not in _clean_actors(["DMM独家", "山本香织"])
    assert "山本香织" in _clean_actors(["DMM独家", "山本香织"])
    assert "DMM独家" not in _clean_tags(["DMM独家", "人妻", "山本かをり"])


def test_kawori_name_not_sentence_frag():
    assert not _looks_like_actor_sentence_frag("山本かをり")
    assert "山本かをり" in _clean_actors(["山本かをり"])
    # 真标题句段仍要拦
    assert _looks_like_actor_sentence_frag("好きだった男が強")


def test_no_lift_person_from_tags():
    """标签里即使有真名也不再升格进 actor。"""
    assert _looks_like_person_name_tag("山本かをり")
    assert not _looks_like_person_name_tag("DMM独家")
    assert not _looks_like_person_name_tag("ALDN")
    assert _actors_lifted_from_tags(
        ["人妻", "DMM独家", "山本かをり", "单体作品", "ALDN"]
    ) == []


def test_act_tags_not_actress():
    for junk in (
        "アナル舐め",
        "玉舐め",
        "无套性交",
        "無套性交",
        "主观视角",
        "オリジナル",
        "半外半中",
        "ダブルフェラ",
        "后背位",
        "デカ尻",
        "イチャイチャ",
        "ちっぱい",
    ):
        assert _looks_like_act_tag_token(junk), junk
        assert junk not in _clean_actors([junk, "山本かをり"]), junk
        assert not _looks_like_person_name_tag(junk), junk
    assert _clean_actors(
        ["アナル舐め", "玉舐め", "无套性交", "デカ尻", "イチャイチャ", "山本かをり"]
    ) == ["山本かをり"]


def test_genre_kinship_not_actress():
    for junk in ("乱伦", "继母", "丈母娘", "高中生", "连裤袜", "眼镜娘"):
        assert not _looks_like_person_name_tag(junk), junk
        assert junk not in _clean_actors([junk, "山本かをり"])
    assert "山本かをり" in _clean_actors(["乱伦", "山本かをり", "继母"])
    assert "オーロラプロジェクト・アネックス" not in _clean_actors(
        ["オーロラプロジェクト・アネックス", "青叶春"]
    )


def test_five_kanji_actress_name_kept():
    """纯汉字 5 字姓名（宮田加奈子）不得被 {2,4} 上限误杀。"""
    from app.scrap_library.enrich import _is_plausible_actress_name

    assert _is_plausible_actress_name("宮田加奈子")
    assert _is_plausible_actress_name("小向美奈子")
    assert "宮田加奈子" in _clean_actors(["宮田加奈子"])
    # 角色词结尾仍拒
    assert "人妻女" not in _clean_actors(["人妻女"])
    # 官网空格分隔姓名
    assert _is_plausible_actress_name("横畠 杏菜")
    assert "横畠 杏菜" in _clean_actors(["横畠 杏菜"])


def test_katakana_short_title_not_thin():
    from app.scrap_library.enrich import _title_is_thin

    assert not _title_is_thin("オナサポ", "NYOSHIN-2500")
    assert _title_is_thin("あいら", "ONS-029")  # 平假名短人名仍 thin
    assert _title_is_thin("NYOSHIN-2500", "NYOSHIN-2500")


def test_title_tail_zh_name():
    assert (
        _title_trailing_person_name("ALDN-344 婆婆比我老婆好多了…山本香织")
        == "山本香织"
    )
