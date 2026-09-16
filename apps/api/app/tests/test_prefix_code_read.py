"""按前缀 code_read：推断 / clamp / accept / filter。"""

from __future__ import annotations

from app.prefix.code_read import infer_code_read, resolve_code_read
from app.prefix.catalog_store import _normalize_prefix_entry
from app.search.av import _clamp_std_code_digits

# 直接测扫描脚本内的验收/过滤（sys.path 由 pytest/apps 配置）
import sys
from pathlib import Path

# app/tests/… → parents[4] = repo root
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from scripts.index_codes_from_local_dbs import (  # noqa: E402
    accept_std_serial,
    filter_outlier_codes,
    format_std,
    ingest_line,
)


def test_infer_club_ssis_siro():
    assert infer_code_read("CLUB") == "std3_dmm"
    assert infer_code_read("SSIS") == "std3_open"
    assert infer_code_read("SIRO") == "amateur4"
    assert infer_code_read("259LUXU") == "amateur4"
    assert infer_code_read("LUXU") == "amateur4"


def test_normalize_writes_code_read():
    club = _normalize_prefix_entry("CLUB", {"pad": 3})
    assert club["code_read"] == "std3_dmm"
    assert club["serial_max_hint"] <= 999 or club["serial_max_hint"] == 0

    ssis = _normalize_prefix_entry("SSIS", {})
    assert ssis["code_read"] == "std3_open"

    siro = _normalize_prefix_entry("SIRO", {"pad": 3})
    assert siro["code_read"] == "amateur4"
    assert siro["pad"] == 4


def test_clamp_club_dmm_and_reject_via_accept():
    club = resolve_code_read("CLUB")
    assert club["id"] == "std3_dmm"
    assert club["max_serial"] == 999
    assert _clamp_std_code_digits("CLUB", "00127", profile=club) == "127"
    assert _clamp_std_code_digits("CLUB", "01027", profile=club) == "1027"
    assert accept_std_serial("CLUB", 127, club) is True
    assert accept_std_serial("CLUB", 1027, club) is False


def test_clamp_measure_glue():
    ebwh = resolve_code_read("EBWH")
    assert ebwh["measure_glue"] is True
    assert _clamp_std_code_digits("EBWH", "061100", following="cm", profile=ebwh) == "061"


def test_ssis_open_keeps_four_digit():
    ssis = resolve_code_read("SSIS")
    assert ssis["id"] == "std3_open"
    assert ssis["max_serial"] is None
    assert accept_std_serial("SSIS", 1027, ssis) is True
    # 主簇已跨入四位：robust 应保留；远端孤立脏号砍掉
    codes = [f"SSIS-{i}" for i in range(800, 1100)] + ["SSIS-9999"]
    kept = filter_outlier_codes("SSIS", codes, ssis)
    assert "SSIS-1001" in kept
    assert "SSIS-9999" not in kept
    assert accept_std_serial("SSIS", 9999, ssis) is True  # 硬顶不拒，靠离群过滤


def test_siro_amateur4_keeps_four_digit_core():
    siro = resolve_code_read("SIRO")
    assert siro["id"] == "amateur4"
    assert siro["prefer_digit_len"] == 4
    # 三位数少、四位真号多：不应被「三位数主簇」清空
    codes = [f"SIRO-{i}" for i in range(1000, 1100)] + [
        "SIRO-12",
        "SIRO-55",
        "SIRO-99",
    ]
    kept = filter_outlier_codes("SIRO", codes, siro)
    four = [c for c in kept if int(c.rsplit("-", 1)[-1]) >= 1000]
    assert len(four) >= 50


def test_club_filter_hard_cap():
    club = resolve_code_read("CLUB")
    codes = [f"CLUB-{i:03d}" for i in range(1, 100)] + [
        "CLUB-1027",
        "CLUB-7001",
        "CLUB-8175",
    ]
    kept = filter_outlier_codes("CLUB", codes, club)
    nums = [int(c.rsplit("-", 1)[-1]) for c in kept]
    assert max(nums) <= 999
    assert 1027 not in nums


def test_ingest_club_sample():
    club = resolve_code_read("CLUB")
    profiles = {"CLUB": club}
    bucket: dict = {}
    from collections import defaultdict

    bucket = defaultdict(lambda: defaultdict(set))
    ingest_line(
        "club00127.mp4",
        {"CLUB"},
        {},
        set(),
        None,
        None,
        {},
        {"CLUB": ["japan_censored"]},
        bucket,
        profiles,
    )
    ingest_line(
        "CLUB-1027 dirty club01027",
        {"CLUB"},
        {},
        set(),
        None,
        None,
        {},
        {"CLUB": ["japan_censored"]},
        bucket,
        profiles,
    )
    codes = set()
    for regs in bucket.get("CLUB", {}).values():
        codes |= regs
    assert "CLUB-127" in codes
    assert "CLUB-1027" not in codes


def test_format_std_uses_pad():
    amateur = resolve_code_read("SIRO")
    assert format_std("SIRO", 12, amateur) == "SIRO-0012"
    club = resolve_code_read("CLUB")
    assert format_std("CLUB", 7, club) == "CLUB-007"


if __name__ == "__main__":
    test_infer_club_ssis_siro()
    test_normalize_writes_code_read()
    test_clamp_club_dmm_and_reject_via_accept()
    test_clamp_measure_glue()
    test_ssis_open_keeps_four_digit()
    test_siro_amateur4_keeps_four_digit_core()
    test_club_filter_hard_cap()
    test_ingest_club_sample()
    test_format_std_uses_pad()
    print("ok")
