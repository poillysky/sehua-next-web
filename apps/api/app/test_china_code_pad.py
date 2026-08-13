"""国产番号：四位基号、丢分集。"""

from __future__ import annotations

from app.search_av import extract_maker_codes, std_code_key


def test_mdsr_base_only_four_digit():
    samples = {
        "麻豆传媒 MDSR-0002-ep3《性，工作者》": "MDSR-0002",
        "麻豆传媒 MDSR-0002-4《性，工作者》": "MDSR-0002",
        "麻豆传媒 MDSR 0003-2 性婚姻生活": "MDSR-0003",
        "麻豆传媒 MDSR-0003-EP4《性，婚姻，生活》": "MDSR-0003",
        "【AI】MDSR-0001": "MDSR-0001",
    }
    for text, want in samples.items():
        got = extract_maker_codes(text, "MDSR")
        assert want in got, (text, got)
        assert all("-EP" not in c for c in got), got
        assert std_code_key(want, pad=4) == want


def test_std_code_key_pad4_not_crush():
    assert std_code_key("MDSR-0002", pad=3) == "MDSR-0002"
    assert std_code_key("MDSR-2", pad=4) == "MDSR-0002"
    assert std_code_key("MDSR-0002-EP3", pad=4) == "MDSR-0002"
    assert std_code_key("MDSR-0002-4", pad=4) == "MDSR-0002"


if __name__ == "__main__":
    test_mdsr_base_only_four_digit()
    test_std_code_key_pad4_not_crush()
    print("ok")
