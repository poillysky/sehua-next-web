"""稳健流水上限：裁掉大空洞后的离群高号。"""

from __future__ import annotations

from app.prefix.ranges import estimate_to, robust_serial_max


def test_mimk_like_outlier():
    # 密到 286，孤立 726
    nums = list(range(2, 287)) + [726]
    assert robust_serial_max(nums) == 286
    assert estimate_to(286) == 300


def test_dense_series_keeps_max():
    nums = list(range(1, 801))
    assert robust_serial_max(nums) == 800


def test_two_dense_blocks_takes_later_when_similar_size():
    # 跳号后更大主簇 → 取更高代（空隙被 cap 切开后按规模选）
    nums = list(range(1, 51)) + list(range(200, 280))
    assert robust_serial_max(nums) == 279


def test_two_dense_blocks_near_tie_prefers_higher():
    # 两簇规模接近（≥90%）→ 取更高号那簇
    nums = list(range(1, 51)) + list(range(80, 131))  # 50 vs 51，空隙 30 < cap
    # 空隙小会并成一簇
    assert robust_serial_max(nums) == 130
    nums2 = list(range(1, 101)) + list(range(250, 350))  # 100 vs 100，空隙 150 > cap
    assert robust_serial_max(nums2) == 349



def test_two_dense_blocks_prefers_larger():
    # 主簇更大时不要被更高的小簇带走
    nums = list(range(1, 101)) + list(range(5000, 5031))
    assert robust_serial_max(nums) == 100


def test_club_like_pollution():
    # CLUB：1..935 主簇 + 7000 段脏号 → 上限停在主簇
    nums = list(range(1, 936)) + list(range(7000, 7515))
    assert robust_serial_max(nums) == 935


def test_club_near_miss_four_digit():
    # 935 后粘少量四位脏号，空隙被 cap 后仍应停在三位数主簇附近
    nums = list(range(1, 936)) + [983, 1027, 1047] + list(range(7000, 7200))
    assert robust_serial_max(nums) <= 1047
    assert robust_serial_max(nums) >= 935



def test_small_gaps_kept():
    nums = [1, 2, 10, 25, 40, 55]
    assert robust_serial_max(nums) == 55


def test_empty():
    assert robust_serial_max([]) == 0
    assert robust_serial_max({0, -1}) == 0


if __name__ == "__main__":
    test_mimk_like_outlier()
    test_dense_series_keeps_max()
    test_two_dense_blocks_takes_later_when_similar_size()
    test_two_dense_blocks_near_tie_prefers_higher()
    test_two_dense_blocks_prefers_larger()
    test_club_like_pollution()
    test_club_near_miss_four_digit()
    test_small_gaps_kept()
    test_empty()
    print("ok")
