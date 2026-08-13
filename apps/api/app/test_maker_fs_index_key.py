"""maker-fs 索引键：不漏素人数字头、不误吃异格式、剥尾缀守区间。"""

from __future__ import annotations

from app.maker_fs import _index_code_key, _rekey_covers_to_pad


def test_digit_pad_basic_and_suffix():
    assert _index_code_key("SONE-15", pad=3, prefix="SONE") == "SONE-015"
    assert _index_code_key("SONE-015", pad=3, prefix="SONE") == "SONE-015"
    assert _index_code_key("IPZZ-599C", pad=3, prefix="IPZZ") == "IPZZ-599"
    assert _index_code_key("ADN-749CH", pad=3, prefix="ADN") == "ADN-749"
    assert _index_code_key("DANDY-827A", pad=3, prefix="DANDY") == "DANDY-827"
    assert _index_code_key("ABP-984KK", pad=3, prefix="ABP") == "ABP-984"


def test_china_keep_leading_zeros():
    assert _index_code_key("MDSR-0002", pad=3, prefix="MDSR") == "MDSR-0002"
    assert _index_code_key("DA-03", pad=3, prefix="DA") == "DA-003"


def test_amateur_hub_prefix_not_dropped():
    assert _index_code_key("200GANA-409", pad=4, prefix="200GANA") == "200GANA-0409"
    assert _index_code_key("200GANA-409C", pad=4, prefix="200GANA") == "200GANA-0409"
    # 帖子只有字母前缀时升到索引前缀
    assert _index_code_key("GANA-409", pad=4, prefix="200GANA") == "200GANA-0409"
    assert _index_code_key("300MIUM-611", pad=4, prefix="300MIUM") == "300MIUM-0611"
    # 反方向：索引是字母前缀，源串带数字头
    assert _index_code_key("200GANA-409", pad=4, prefix="GANA") == "GANA-0409"


def test_range_filter():
    assert _index_code_key("FOO-234", pad=3, prefix="FOO", to_n=234) == "FOO-234"
    assert _index_code_key("FOO-720", pad=3, prefix="FOO", to_n=234) is None
    assert _index_code_key("FOO-000", pad=3, prefix="FOO", from_n=1) is None
    assert _index_code_key("FOO-5", pad=3, prefix="FOO", from_n=10, to_n=100) is None


def test_wrong_prefix_rejected():
    assert _index_code_key("IPZZ-599", pad=3, prefix="SONE") is None
    assert _index_code_key("SONE-001", pad=3, prefix="200GANA") is None


def test_non_digit_formats_kept():
    # FC2 / date6 / western / alnum 不应被流水规则误杀
    assert (
        _index_code_key("FC2-PPV-071713", pad=3, prefix="FC2PPV") == "FC2-PPV-071713"
    )
    # 完整 date6
    assert (
        _index_code_key("10MU-260115-001", pad=3, prefix="10MU") == "10MU-260115-001"
    )
    # 缺第三段时 parse 会剥 hub → 仍保留原文，绝不变成 MU-…
    assert _index_code_key("10MU-010123", pad=3, prefix="10MU") == "10MU-010123"
    assert _index_code_key("MU-010123", pad=3, prefix="10MU") is None
    western = _index_code_key(
        "ADULTTIME.2023.02.17", pad=3, prefix="ADULTTIME"
    )
    assert western == "ADULTTIME.2023.02.17"
    assert _index_code_key("C0930-TK0004", pad=3, prefix="C0930") == "C0930-TK0004"
    # 流水区间裁剪不作用于这些格式
    assert (
        _index_code_key("FC2-PPV-999999", pad=3, prefix="FC2PPV", to_n=10)
        == "FC2-PPV-999999"
    )


def test_date6_aliases_to_canonical():
    # 1PONDO 文件夹 ↔ 1PON canonical
    assert (
        _index_code_key("1PONDO-010115-001", pad=3, prefix="1PONDO")
        == "1PON-010115-001"
    )
    assert (
        _index_code_key("1PON-010115-001", pad=3, prefix="1PONDO") == "1PON-010115-001"
    )
    assert (
        _index_code_key("1PONDO-010115-001", pad=3, prefix="1PON") == "1PON-010115-001"
    )
    # CARIBBEAN → CARIB
    assert (
        _index_code_key("CARIBBEAN-010115-001", pad=3, prefix="CARIB")
        == "CARIB-010115-001"
    )


def test_fixed_std_special_forms():
    assert (
        _index_code_key("TOKYOHOT-n1234", pad=3, prefix="TOKYOHOT")
        == "TOKYOHOT-N1234"
    )
    assert (
        _index_code_key("TOKYO-HOT-1234", pad=3, prefix="TOKYOHOT")
        == "TOKYOHOT-N1234"
    )
    assert (
        _index_code_key("MESUBUTA-123456-001", pad=3, prefix="MESUBUTA")
        == "MESUBUTA-123456-001"
    )
    assert _index_code_key("HEYZO-1234", pad=3, prefix="HEYZO") == "HEYZO-1234"
    # GACHINCO ↔ GACHI
    assert _index_code_key("GACHI-123", pad=3, prefix="GACHINCO") == "GACHI-123"
    assert _index_code_key("GACHINCO-123", pad=3, prefix="GACHINCO") == "GACHI-123"
    assert _index_code_key("GACHI-123", pad=3, prefix="GACHI") == "GACHI-123"


def test_rekey_merges_suffix_and_drops_over_to():
    covers = {
        "IPZZ-599C": {"coverUrl": "a"},
        "IPZZ-599": {"forumTitle": "t"},
        "IPZZ-720": {"coverUrl": "x"},
        "IPZZ-001X": {"coverUrl": "b"},
    }
    out = _rekey_covers_to_pad(covers, prefix="IPZZ", pad=3, from_n=1, to_n=600)
    assert set(out) == {"IPZZ-599", "IPZZ-001"}
    assert out["IPZZ-599"].get("coverUrl") == "a"
    assert out["IPZZ-599"].get("forumTitle") == "t"


def test_rekey_amateur_hub():
    covers = {
        "200GANA-409": {"coverUrl": "a"},
        "GANA-409C": {"forumTitle": "t"},
        "200GANA-500": {"coverUrl": "b"},
    }
    out = _rekey_covers_to_pad(covers, prefix="200GANA", pad=4, from_n=1, to_n=1000)
    assert set(out) == {"200GANA-0409", "200GANA-0500"}
    assert out["200GANA-0409"].get("coverUrl") == "a"
    assert out["200GANA-0409"].get("forumTitle") == "t"


if __name__ == "__main__":
    test_digit_pad_basic_and_suffix()
    test_china_keep_leading_zeros()
    test_amateur_hub_prefix_not_dropped()
    test_range_filter()
    test_wrong_prefix_rejected()
    test_non_digit_formats_kept()
    test_date6_aliases_to_canonical()
    test_fixed_std_special_forms()
    test_rekey_merges_suffix_and_drops_over_to()
    test_rekey_amateur_hub()
    print("ok")
