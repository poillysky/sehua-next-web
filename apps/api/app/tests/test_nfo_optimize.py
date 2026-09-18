# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.scrap_library.nfo import build_mdcx_nfo_root, write_nfo
from app.scrap_library.nfo_optimize import optimize_one_nfo


def _write_sample(path: Path, *, title: str, actors: list[str], studio: str) -> None:
    root = build_mdcx_nfo_root(
        {
            "num": "SSIS-001",
            "title": title,
            "actors": actors,
            "studio": studio,
            "maker": studio,
            "genres": ["巨乳", "ドラマ"],
            "plot": "测试剧情",
        }
    )
    write_nfo(path, root)


def test_optimize_one_nfo_applies_title_and_actor_maps(tmp_path: Path) -> None:
    nfo = tmp_path / "SSIS-001.nfo"
    _write_sample(
        nfo,
        title="SSIS-001 旧标题",
        actors=["新有菜"],
        studio="S1 NO.1 STYLE",
    )

    # `optimize_one_nfo` 在函数内 `from app.core.maps_paths import lookup_*`
    # → 必须 patch 调用点符号；打在 `nfo_optimize` 模块属性上必然 AttributeError。
    with (
        patch(
            "app.core.maps_paths.lookup_code_title",
            return_value="更好的中文标题",
        ),
        patch(
            "app.core.maps_paths.lookup_code_actors",
            return_value=("桥本有菜",),
        ),
        patch(
            "app.scrape.metadata_optimize.polish_actress_names",
            side_effect=lambda names, **kw: list(names),
        ),
        patch(
            "app.scrap_library.enrich._apply_mdcx_maps",
            side_effect=lambda detail, **kw: detail,
        ),
        patch(
            "app.scrap_library.enrich._polish_studio_name",
            side_effect=lambda s: s,
        ),
    ):
        changed, applied = optimize_one_nfo(nfo, force=True)

    assert changed is True
    assert any(str(x).startswith("title") or x == "title" for x in applied)
    text = nfo.read_text(encoding="utf-8")
    assert "更好的中文标题" in text
    assert "桥本有菜" in text


def test_optimize_one_nfo_noop_when_unchanged(tmp_path: Path) -> None:
    nfo = tmp_path / "SSIS-001.nfo"
    _write_sample(
        nfo,
        title="SSIS-001 定稿标题",
        actors=["桥本有菜"],
        studio="S1 NO.1 STYLE",
    )
    before = nfo.read_bytes()

    with (
        patch(
            "app.core.maps_paths.lookup_code_title",
            return_value="",
        ),
        patch(
            "app.core.maps_paths.lookup_code_actors",
            return_value=(),
        ),
        patch(
            "app.scrap_library.enrich._apply_mdcx_maps",
            side_effect=lambda detail, **kw: detail,
        ),
        patch(
            "app.scrap_library.enrich._polish_studio_name",
            side_effect=lambda s: s,
        ),
    ):
        changed, applied = optimize_one_nfo(nfo, force=False)

    assert changed is False
    assert applied == []
    assert nfo.read_bytes() == before
