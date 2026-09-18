"""无码官网专用站：解析 + 注册 + 前缀注入。"""

from __future__ import annotations

from app.scrape_details.heyzo import parse_heyzo_movie_key
from app.scrape_details.onespondo import parse_1pondo_movie_key
from app.scrape_details.pacopacomama import parse_paco_movie_key
from app.scrape_details.kin8 import parse_kin8_movie_key
from app.scrape_details.h0930 import parse_h0930_movie_key
from app.scrape_details.h4610 import parse_h4610_movie_key
from app.scrape_details.c0930 import parse_c0930_movie_key
from app.scrape_details.tokyohot import parse_tokyohot_movie_key
from app.scrape_details.nyoshin import parse_nyoshin_movie_key
from app.scrape_details.heydouga import parse_heydouga_movie_key
from app.scrape_details import resolve_detail_fn
from app.scrap_library.enrich_strategy import (
    UNCENSORED_OFFICIAL_SOURCE_IDS,
    uncensored_official_for_code,
)


def test_heyzo_key():
    assert parse_heyzo_movie_key("HEYZO-2034") == "2034"
    assert parse_heyzo_movie_key("heyzo-02034") == "2034"
    assert parse_heyzo_movie_key("2034") == "2034"
    assert parse_heyzo_movie_key("PACO-1") is None


def test_1pondo_key():
    assert parse_1pondo_movie_key("1PON-062014-830") == "062014_830"
    assert parse_1pondo_movie_key("1pondo-062014_830") == "062014_830"
    assert parse_1pondo_movie_key("CARIB-1") is None


def test_paco_key():
    assert parse_paco_movie_key("PACO-122615-557") == "122615_557"
    assert parse_paco_movie_key("pacopacomama-122615_557") == "122615_557"
    assert parse_paco_movie_key("HEYZO-1") is None


def test_kin8_key():
    assert parse_kin8_movie_key("KIN8-3500") == "3500"
    assert parse_kin8_movie_key("kin8tengoku-03500") == "3500"
    assert parse_kin8_movie_key("3500") == "3500"
    assert parse_kin8_movie_key("HEYZO-1") is None


def test_h0930_family_keys():
    assert parse_h0930_movie_key("H0930-ki260908") == "ki260908"
    assert parse_h0930_movie_key("H0930-ori1224") == "ori1224"
    assert parse_h0930_movie_key("h0930_gol195") == "gol195"
    assert parse_h0930_movie_key("HEYZO-1") is None

    assert parse_h4610_movie_key("H4610-ki260908") == "ki260908"
    assert parse_h4610_movie_key("CARIB-1") is None

    assert parse_c0930_movie_key("C0930-hitozuma1369") == "hitozuma1369"
    assert parse_c0930_movie_key("c0930_hitozuma1369") == "hitozuma1369"
    assert parse_c0930_movie_key("H0930-ki1") is None


def test_tokyohot_key():
    assert parse_tokyohot_movie_key("TOKYOHOT-N1234") == "n1234"
    assert parse_tokyohot_movie_key("TOKYO-HOT-n1234") == "n1234"
    assert parse_tokyohot_movie_key("TOKYOHOT-1234") == "n1234"
    assert parse_tokyohot_movie_key("k1454") == "k1454"
    assert parse_tokyohot_movie_key("n1234") == "n1234"
    assert parse_tokyohot_movie_key("HEYZO-1") is None


def test_nyoshin_key():
    assert parse_nyoshin_movie_key("NYOSHIN-2500") == "n2500"
    assert parse_nyoshin_movie_key("NYOSHIN-n2500") == "n2500"
    assert parse_nyoshin_movie_key("n2500") == "n2500"
    assert parse_nyoshin_movie_key("HEYZO-1") is None


def test_heydouga_key():
    assert parse_heydouga_movie_key("HEYDOUGA-4030-001") == ("4030", "001")
    assert parse_heydouga_movie_key("heydouga_4030_1") == ("4030", "001")
    assert parse_heydouga_movie_key("4030-002") == ("4030", "002")
    assert parse_heydouga_movie_key("HEYZO-2034") is None


def test_providers_registered():
    for sid in (
        "heyzo",
        "1pondo",
        "pacopacomama",
        "kin8",
        "h0930",
        "h4610",
        "c0930",
        "tokyohot",
        "nyoshin",
        "heydouga",
    ):
        assert resolve_detail_fn(sid) is not None, sid


def test_uncensored_official_prefix_map():
    assert uncensored_official_for_code("HEYDOUGA-4030-001") == ["heydouga"]
    assert uncensored_official_for_code("HEYZO-2034") == ["heyzo"]
    assert uncensored_official_for_code("1PON-062014-830") == ["1pondo"]
    assert uncensored_official_for_code("1PONDO-062014-830") == ["1pondo"]
    assert uncensored_official_for_code("PACO-122615-557") == ["pacopacomama"]
    assert uncensored_official_for_code("PACOMA-1") == ["pacopacomama"]
    assert uncensored_official_for_code("CARIB-011317-002") == ["carib"]
    assert uncensored_official_for_code("CARIBPR-011317-002") == ["carib"]
    assert uncensored_official_for_code("10MU-051124-01") == ["10musume"]
    assert uncensored_official_for_code("10MUSUME-051124-01") == ["10musume"]
    assert uncensored_official_for_code("KIN8-3500") == ["kin8"]
    assert uncensored_official_for_code("KIN8TENGOKU-3500") == ["kin8"]
    assert uncensored_official_for_code("H0930-ki260908") == ["h0930"]
    assert uncensored_official_for_code("H4610-ki260908") == ["h4610"]
    assert uncensored_official_for_code("C0930-hitozuma1369") == ["c0930"]
    assert uncensored_official_for_code("TOKYOHOT-N1234") == ["tokyohot"]
    assert uncensored_official_for_code("TOKYO-HOT-N1234") == ["tokyohot"]
    assert uncensored_official_for_code("NYOSHIN-2500") == ["nyoshin"]
    assert uncensored_official_for_code("SSIS-001") == []
    for sid in (
        "heyzo",
        "carib",
        "kin8",
        "h0930",
        "h4610",
        "c0930",
        "tokyohot",
        "nyoshin",
        "heydouga",
    ):
        assert sid in UNCENSORED_OFFICIAL_SOURCE_IDS
