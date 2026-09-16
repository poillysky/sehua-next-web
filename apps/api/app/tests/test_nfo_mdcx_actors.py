# -*- coding: utf-8 -*-
"""MDCx 转入 NFO：从 tag/genre 识别女优；与本程序 <actor> 格式对齐。"""

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


class MdcxNfoActorTests(unittest.TestCase):
    def test_harvest_skips_meta_and_code_tags(self) -> None:
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
        self.assertEqual(names, ["渚光希"])

    def test_parse_mdcx_ysn611_gets_actress(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "YSN-611.nfo"
            path.write_text(_YSN611, encoding="utf-8")
            meta = parse_nfo(path)
        self.assertEqual(meta.get("actors"), ["渚光希"])
        # 女优不应再留在 tag/genre 展示列表
        self.assertNotIn("渚光希", meta.get("tags") or [])
        self.assertNotIn("渚光希", meta.get("genres") or [])
        # 类型词不能进女优
        for junk in ("乱伦", "受孕", "平胸", "痴女"):
            self.assertNotIn(junk, meta.get("actors") or [])

    def test_reject_ntr_genre_as_actress(self) -> None:
        from app.scrap_library.nfo import normalize_nfo_file

        raw = """<?xml version='1.0' encoding='utf-8'?>
<movie>
  <num>FPRE-002</num>
  <title>FPRE-002 测试标题足够长</title>
  <studio>Fitch</studio>
  <plot>足够长的剧情文本用来通过缺口检查。</plot>
  <tag>出轨/NTR</tag>
  <tag>天月あず</tag>
  <tag>巨乳</tag>
  <genre>口交</genre>
  <genre>出轨/NTR</genre>
  <genre>天月あず</genre>
</movie>
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "FPRE-002.nfo"
            path.write_text(raw, encoding="utf-8")
            r = normalize_nfo_file(path, force=True)
            self.assertTrue(r.get("ok") and r.get("changed"))
            text = path.read_text(encoding="utf-8")
        self.assertIn("<name>天月あず</name>", text)
        self.assertIn("<type>Actor</type>", text)
        self.assertNotIn("<name>出轨/NTR</name>", text)
        self.assertIn("<genre>出轨/NTR</genre>", text)
        self.assertIn("<tag>出轨/NTR</tag>", text)
        self.assertIn("<genre>巨乳</genre>", text)
        self.assertNotIn("actor_all", text)
        self.assertIn("<![CDATA[", text)

    def test_normalize_to_mdcx_layout(self) -> None:
        from app.scrap_library.nfo import normalize_nfo_file

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "YSN-611.nfo"
            path.write_text(_YSN611, encoding="utf-8")
            r = normalize_nfo_file(path, force=True)
            self.assertTrue(r.get("ok") and r.get("changed"))
            text = path.read_text(encoding="utf-8")
        self.assertIn("<actor>", text)
        self.assertIn("<name>渚光希</name>", text)
        self.assertIn("<type>Actor</type>", text)
        self.assertIn("<genre>乱伦</genre>", text)
        self.assertIn("<tag>乱伦</tag>", text)
        self.assertIn("<genre>中出</genre>", text)
        self.assertIn("<tag>渚光希</tag>", text)
        self.assertIn("片商: NON", text)
        self.assertIn("<series>", text)
        self.assertIn("https://www.javbus.com", text)
        self.assertIn('<?xml version="1.0" encoding="UTF-8" ?>', text)
        self.assertNotIn("actor_all", text)
        self.assertNotIn("outlineshow", text)

    def test_parse_program_actor_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "AARM-001.nfo"
            path.write_text(_PROGRAM, encoding="utf-8")
            meta = parse_nfo(path)
        self.assertEqual(meta.get("actors"), ["森日向子"])


if __name__ == "__main__":
    unittest.main()
