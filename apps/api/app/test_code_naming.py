"""番号命名：按帖题原样；搜索忽略前导零。"""

from __future__ import annotations

from app.search_av import (
    build_av_code_ilike_patterns,
    extract_maker_codes,
    std_code_key,
)


def test_china_preserve_written_width():
    assert extract_maker_codes("精东-JD-150-杰森", "JD") == ["JD-150"]
    assert "MDSR-0002" in extract_maker_codes("麻豆 MDSR-0002-ep3", "MDSR")
    assert "MDHG-0023" in extract_maker_codes("麻豆传媒映画 MDHG-0023", "MDHG") or extract_maker_codes(
        "麻豆传媒映画 MDHG-23", "MDHG"
    ) == ["MDHG-23"]


def test_std_code_key_not_force_china4():
    assert std_code_key("JD-150", pad=0) == "JD-150"
    assert std_code_key("JD-150", pad=3) == "JD-150"
    assert std_code_key("MDSR-0002", pad=0) == "MDSR-0002"
    assert std_code_key("MDSR-0002", pad=3) == "MDSR-0002"
    assert std_code_key("SONE-15", pad=3) == "SONE-015"
    assert std_code_key("MDSR-2", pad=4) == "MDSR-0002"


def test_std_code_key_strip_letter_suffix():
    assert std_code_key("IPZZ-599C", pad=3) == "IPZZ-599"
    assert std_code_key("SONE-15C", pad=3) == "SONE-015"
    assert std_code_key("ADN-749CH", pad=3) == "ADN-749"
    assert std_code_key("DANDY-827A", pad=3) == "DANDY-827"
    assert std_code_key("DANDY-827B", pad=3) == "DANDY-827"


def test_search_jd0150_matches_jd150():
    pats = build_av_code_ilike_patterns("JD-0150")
    assert any("JD-150" in p or "JD150" in p for p in pats)
    pats2 = build_av_code_ilike_patterns("JD-150")
    assert any("JD-0150" in p or "JD0150" in p for p in pats2)


def test_search_alias_prefix_1pon_and_tokyohot():
    from app.search_av import build_av_code_boundary_re

    pats = build_av_code_ilike_patterns("1PON-010115-001")
    assert any("1PONDO-010115-001" in p for p in pats)
    pats_r = build_av_code_ilike_patterns("1PONDO-010115-001")
    assert any("1PON-010115-001" in p for p in pats_r)

    br = build_av_code_boundary_re("1PON-010115-001")
    assert br.search("1pondo 1PONDO-010115-001 uncensored")
    assert br.search("1PON-010115-001")

    pats_th = build_av_code_ilike_patterns("TOKYOHOT-N1234")
    assert any("TOKYOHOT-1234" in p or "TOKYOHOT1234" in p for p in pats_th)
    br_th = build_av_code_boundary_re("TOKYOHOT-N1234")
    assert br_th.search("Tokyo Hot n1234")
    assert br_th.search("TOKYOHOT-1234")
    assert br_th.search("TOKYOHOT-N1234")

    pats_g = build_av_code_ilike_patterns("GACHI-123")
    assert any("GACHINCO-123" in p for p in pats_g)


def test_western_yyyy():
    assert extract_maker_codes("Brazzers.26.06.01.Title", "BRAZZERS") == [
        "BRAZZERS.2026.06.01"
    ]


if __name__ == "__main__":
    test_china_preserve_written_width()
    test_std_code_key_not_force_china4()
    test_std_code_key_strip_letter_suffix()
    test_search_jd0150_matches_jd150()
    test_search_alias_prefix_1pon_and_tokyohot()
    test_western_yyyy()
    print("ok")
