"""_clamp_std_code_digits：DMM 补位 vs 度量粘连。"""

from __future__ import annotations

from app.prefix_code_read import resolve_code_read
from app.search_av import _clamp_std_code_digits


def test_dmm_zero_pad_club():
    club = resolve_code_read("CLUB")
    assert _clamp_std_code_digits("CLUB", "00127", profile=club) == "127"
    assert _clamp_std_code_digits("CLUB", "00001", profile=club) == "1"
    assert _clamp_std_code_digits("CLUB", "00935", profile=club) == "935"
    # 错误 cid club01027 会还原成 1027，再交给 max_serial / 离群过滤
    assert _clamp_std_code_digits("CLUB", "01027", profile=club) == "1027"


def test_plain_serial():
    assert _clamp_std_code_digits("CLUB", "127") == "127"
    assert _clamp_std_code_digits("CLUB", "1027") == "1027"


def test_measure_glue():
    assert _clamp_std_code_digits("EBWH", "061100", following="cm") == "061"
    assert _clamp_std_code_digits("EBWH", "061100", following="CM爆乳") == "061"


if __name__ == "__main__":
    test_dmm_zero_pad_club()
    test_plain_serial()
    test_measure_glue()
    print("ok")
