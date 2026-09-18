"""carib / CARIBPR 番号解析与详情路径。"""

from __future__ import annotations

from app.scrape_details.carib import (
    carib_detail_url,
    carib_path_key,
    is_carib_premium_code,
    parse_carib_movie_key,
    parse_carib_premiered_from_key,
)


def test_parse_carib_and_caribpr_keys():
    assert parse_carib_movie_key("CARIB-011317-002") == "011317-002"
    assert parse_carib_movie_key("CARIBPR-011317-002") == "011317-002"
    assert parse_carib_movie_key("011317_002") == "011317-002"
    assert parse_carib_movie_key("PACO-122615-557") is None
    assert is_carib_premium_code("CARIBPR-011317-002")
    assert not is_carib_premium_code("CARIB-011317-002")


def test_caribpr_url_uses_underscore_path():
    assert carib_path_key("011317-002", premium=True) == "011317_002"
    assert carib_path_key("011317-002", premium=False) == "011317-002"
    url = carib_detail_url(
        "https://www.caribbeancompr.com", "011317-002", premium=True
    )
    assert url.endswith("/moviepages/011317_002/index.html")
    assert parse_carib_premiered_from_key("011317-002") == "2017-01-13"


def test_caribpr_ignores_regular_catalog_base(monkeypatch):
    """enrich 传入目录 baseUrl=caribbeancom.com 时，Premium 仍应打 compr 站。"""
    from app.scrape_details import carib as mod

    seen: dict[str, str] = {}

    def fake_fetch(url: str, **kwargs):  # noqa: ANN003
        seen["url"] = url
        raise RuntimeError("stop-after-url")

    monkeypatch.setattr(mod, "fetch_html", fake_fetch)
    try:
        mod.scrape_detail(
            "CARIBPR-011317-002",
            base_url="https://www.caribbeancom.com",
        )
    except RuntimeError as e:
        assert "stop-after-url" in str(e)
    assert "caribbeancompr.com" in seen.get("url", "")
    assert "/moviepages/011317_002/" in seen.get("url", "")
