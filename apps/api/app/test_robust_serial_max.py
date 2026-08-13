"""稳健流水上限：裁掉大空洞后的离群高号。"""

from __future__ import annotations

from app.prefix_ranges import estimate_to, robust_serial_max


def test_mimk_like_outlier():
    # 密到 286，孤立 726
    nums = list(range(2, 287)) + [726]
    assert robust_serial_max(nums) == 286
    assert estimate_to(286) == 300


def test_dense_series_keeps_max():
    nums = list(range(1, 801))
    assert robust_serial_max(nums) == 800


def test_two_dense_blocks_takes_later():
    # 早期 1..50，后期跳号后密集成 200..230
    nums = list(range(1, 51)) + list(range(200, 231))
    assert robust_serial_max(nums) == 230


def test_small_gaps_kept():
    nums = [1, 2, 10, 25, 40, 55]
    assert robust_serial_max(nums) == 55


def test_empty():
    assert robust_serial_max([]) == 0
    assert robust_serial_max({0, -1}) == 0


if __name__ == "__main__":
    test_mimk_like_outlier()
    test_dense_series_keeps_max()
    test_two_dense_blocks_takes_later()
    test_small_gaps_kept()
    test_empty()
    print("ok")
