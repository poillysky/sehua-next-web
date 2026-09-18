# -*- coding: utf-8 -*-
"""NFO 女优：只认 <actor>/actor_all，禁止 tag/genre 硬套。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.scrap_library.nfo import actors_from_mdcx_side_channels, parse_nfo

_YSN611 = """<?xml version='1.0' encoding='utf-8'?>
<movie>
  <title>YSN-611 やべーほどカワイイ妹を貪りたい</title>
  <originaltitle>YSN-611 やべーほどカワイイ妹を貪りたい 渚みつき</originaltitle>
  <studio>NON</studio>
  <maker>NON</maker>
  <plot>足够长的剧情文本用来通过缺口检查。</plot>
  <tag>乱伦</tag>
  <tag>痴女</tag>
  <tag>中出</tag>
  <tag>单体作品</tag>
  <tag>YSN</tag>
  <tag>渚光希</tag>
  <tag>系列: やべーほどカワイイ妹を貪りたい</tag>
  <tag>片商: NON</tag>
  <genre>乱伦</genre>
  <genre>渚光希</genre>
  <genre>片商: NON</genre>
  <num>YSN-611</num>
  <cover>https://www.javbus.com/pics/cover/a3t7_b.jpg</cover>
</movie>
"""

_PROGRAM = """<?xml version='1.0' encoding='utf-8'?>
<movie>
  <num>AARM-001</num>
  <title>森日向子用苗条美脚帮派遣社员打气</title>
  <studio>阿洛玛企划</studio>
  <plot>足够长的剧情文本用来通过缺口检查。</plot>
  <actor><name>森日向子</name></actor>
  <actor_all>森日向子</actor_all>
  <genre>痴女</genre>
  <genre>单体作品</genre>
</movie>
"""

_JUNK_ACTORS = """<?xml version='1.0' encoding='utf-8'?>
<movie>
  <num>FC2-668848</num>
  <title>FC2-668848 test title long enough</title>
  <plot>足够长的剧情文本用来通过缺口检查。</plot>
  <actor><name>アナル舐め</name><type>Actor</type></actor>
  <actor><name>玉舐め</name><type>Actor</type></actor>
  <actor><name>无套性交</name><type>Actor</type></actor>
  <tag>アナル舐め</tag>
  <tag>玉舐め</tag>
  <tag>无套性交</tag>
  <genre>アナル舐め</genre>
</movie>
"""


class MdcxNfoActorTests(unittest.TestCase):
    def test_no_harvest_from_tags(self) -> None:
        names = actors_from_mdcx_side_channels(
            tags=[
                "痴女",
                "YSN",
                "渚光希",
                "片商: NON",
                "系列: foo",
                "单体作品",
            ],
            genres=["渚光希", "中出"],
            code="YSN-611",
            studio="NON",
        )
        self.assertEqual(names, [])

    def test_actor_all_still_works(self) -> None:
        names = actors_from_mdcx_side_channels(
            tags=["痴女", "渚光希"],
            actors_all=["渚光希", "乱伦"],
            code="YSN-611",
            studio="NON",
        )
        # actor_all 原文保留（不再 junk 清洗）
        self.assertEqual(names, ["渚光希", "乱伦"])

    def test_parse_mdcx_no_actor_stays_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "YSN-611.nfo"
            path.write_text(_YSN611, encoding="utf-8")
            meta = parse_nfo(path)
        self.assertEqual(meta.get("actors") or [], [])
        # 人名仍留在 genre（tag 与 genre 去重后可能只留一侧）
        pool = list(meta.get("tags") or []) + list(meta.get("genres") or [])
        self.assertIn("渚光希", pool)

    def test_parse_keeps_nfo_actors_as_is(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "FC2-668848.nfo"
            path.write_text(_JUNK_ACTORS, encoding="utf-8")
            meta = parse_nfo(path)
        self.assertEqual(
            meta.get("actors") or [],
            ["アナル舐め", "玉舐め", "无套性交"],
        )

    def test_normalize_keeps_nfo_actors(self) -> None:
        from app.scrap_library.nfo import normalize_nfo_file

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "FC2-668848.nfo"
            path.write_text(_JUNK_ACTORS, encoding="utf-8")
            r = normalize_nfo_file(path, force=True)
            self.assertTrue(r.get("ok"))
            text = path.read_text(encoding="utf-8")
        self.assertIn("<name>アナル舐め</name>", text)
        self.assertIn("<name>无套性交</name>", text)
        self.assertIn("<tag>アナル舐め</tag>", text)
        self.assertIn("<genre>アナル舐め</genre>", text)

    def test_normalize_does_not_lift_tag_to_actor(self) -> None:
        from app.scrap_library.nfo import normalize_nfo_file

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "YSN-611.nfo"
            path.write_text(_YSN611, encoding="utf-8")
            r = normalize_nfo_file(path, force=True)
            self.assertTrue(r.get("ok") and r.get("changed"))
            text = path.read_text(encoding="utf-8")
        self.assertNotIn("<name>渚光希</name>", text)
        self.assertIn("<genre>乱伦</genre>", text)
        self.assertIn("<tag>渚光希</tag>", text)

    def test_parse_program_actor_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "AARM-001.nfo"
            path.write_text(_PROGRAM, encoding="utf-8")
            meta = parse_nfo(path)
        self.assertEqual(meta.get("actors"), ["森日向子"])


if __name__ == "__main__":
    unittest.main()
