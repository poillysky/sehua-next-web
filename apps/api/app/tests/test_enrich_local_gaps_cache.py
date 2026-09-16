"""`_local_folder_gaps` 结果缓存必须能随文件变化正确失效。

背景：`_local_nfo_gap_maps`（刮削启动/续跑路径）要对整个分区逐目录跑
`parse_nfo` + 空白封面判定，实测 1.1ms/目录，有码区 1349 个目录 ≈ 1.5s。
为此按 (目录 mtime, NFO/海报 mtime+size) 加了结果缓存。

若缓存不能失效，**刚刮好的目录会被继续判成「缺口」→ 重复刮**（浪费网络且
让「越跑越慢」复发）。这三条路径必须各有测试：
  1) NFO 被覆盖写  → 目录 mtime 不变，靠 NFO 自身 mtime/size 失效
  2) 目录里新增 NFO → 靠目录 mtime 失效
  3) 海报被覆盖写  → 靠海报自身 mtime/size 失效
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.scrap_library import embed as embed_svc
from app.scrap_library import enrich as E

_NFO_TMPL = """<?xml version="1.0" encoding="utf-8"?>
<movie>
  <num>{num}</num>
  <title>{title}</title>
  <plot>{plot}</plot>
  <studio>{studio}</studio>
  <actor><name>{actor}</name></actor>
  <cover>{cover}</cover>
</movie>
"""

_GOOD = {
    "num": "ABP-594",
    "title": "一个足够长的标题用来过 thin_title",
    "plot": "足够长的简介文本，用来通过 no_plot 的长度阈值检查。",
    "studio": "テスト片商",
    "actor": "测试女优",
    "cover": "https://example.com/cover.jpg",
}
_BASE_NS = 1_700_000_000_000_000_000


class LocalFolderGapsCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        E._folder_gaps_cache.clear()  # noqa: SLF001

    def tearDown(self) -> None:
        E._folder_gaps_cache.clear()  # noqa: SLF001

    def _nfo_text(self, **over: str) -> str:
        fields = {**_GOOD, **over}
        return _NFO_TMPL.format(**fields)

    def _write(self, path: Path, text: str, *, tick: int) -> None:
        """写文件并把 mtime 设成一个明确、递增的时间戳（避免同秒同 ns）。"""
        path.write_text(text, encoding="utf-8")
        ns = _BASE_NS + tick * 10**9
        os.utime(path, ns=(ns, ns))

    def _mk_folder(self, td: str) -> Path:
        folder = Path(td) / "ABP-594"
        folder.mkdir()
        return folder

    def test_no_gaps_when_everything_present(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            folder = self._mk_folder(td)
            self._write(folder / "ABP-594.nfo", self._nfo_text(), tick=1)
            (folder / "poster.jpg").write_bytes(b"x" * 2048)
            with mock.patch.object(embed_svc, "_is_blank_cover_file", return_value=False):
                code, gaps = E._local_folder_gaps(folder)  # noqa: SLF001
            self.assertEqual(code, "ABP-594")
            self.assertEqual(gaps, [], f"齐全目录不该有缺口，实得 {gaps}")
            self.assertIn(str(folder), E._folder_gaps_cache)  # noqa: SLF001

    def test_nfo_rewrite_invalidates_cache(self) -> None:
        """覆盖写 NFO：目录 mtime 不变，只有 NFO 的 mtime/size 能作废缓存。"""
        with tempfile.TemporaryDirectory() as td:
            folder = self._mk_folder(td)
            nfo = folder / "ABP-594.nfo"
            (folder / "poster.jpg").write_bytes(b"x" * 2048)
            with mock.patch.object(embed_svc, "_is_blank_cover_file", return_value=False):
                # 1) 先写一个缺 plot 的 NFO
                self._write(nfo, self._nfo_text(plot="短"), tick=1)
                dir_mtime = os.stat(folder).st_mtime_ns
                _, gaps1 = E._local_folder_gaps(folder)  # noqa: SLF001
                self.assertIn("no_plot", gaps1)

                # 2) 覆盖写（同一路径，目录 mtime 不变）→ 补上 plot
                self._write(nfo, self._nfo_text(plot=_GOOD["plot"]), tick=2)
                self.assertEqual(os.stat(folder).st_mtime_ns, dir_mtime, "目录 mtime 不该变")
                _, gaps2 = E._local_folder_gaps(folder)  # noqa: SLF001
            self.assertNotIn("no_plot", gaps2, "NFO 覆盖写后缓存必须失效")

    def test_new_nfo_in_folder_invalidates_cache(self) -> None:
        """目录里新增 NFO：靠目录 mtime 失效。"""
        with tempfile.TemporaryDirectory() as td:
            folder = self._mk_folder(td)
            with mock.patch.object(embed_svc, "_is_blank_cover_file", return_value=False):
                _, gaps1 = E._local_folder_gaps(folder)  # noqa: SLF001
                self.assertIn("no_local", gaps1, "无 NFO 时应报全量缺口")
                self.assertEqual(len(gaps1), 6)

                (folder / "poster.jpg").write_bytes(b"x" * 2048)
                self._write(folder / "ABP-594.nfo", self._nfo_text(), tick=3)
                _, gaps2 = E._local_folder_gaps(folder)  # noqa: SLF001
            self.assertEqual(gaps2, [], "新增 NFO 后缓存必须失效")

    def test_poster_overwrite_invalidates_cache(self) -> None:
        """海报覆盖写：靠海报自身 mtime 失效。"""
        with tempfile.TemporaryDirectory() as td:
            folder = self._mk_folder(td)
            self._write(folder / "ABP-594.nfo", self._nfo_text(), tick=1)
            poster = folder / "poster.jpg"
            poster.write_bytes(b"x" * 2048)
            with mock.patch.object(embed_svc, "_is_blank_cover_file", return_value=True):
                _, gaps1 = E._local_folder_gaps(folder)  # noqa: SLF001
                self.assertIn("no_local", gaps1, "空白海报应报 no_local")

                # 换成合格海报（覆盖写，目录 mtime 不变；mock 改为不合格→合格）
                poster.write_bytes(b"y" * 4096)
                ns = _BASE_NS + 5 * 10**9
                os.utime(poster, ns=(ns, ns))
                with mock.patch.object(
                    embed_svc, "_is_blank_cover_file", return_value=False
                ):
                    _, gaps2 = E._local_folder_gaps(folder)  # noqa: SLF001
            self.assertNotIn("no_local", gaps2, "海报覆盖写后缓存必须失效")

    def test_cached_result_is_returned_as_copy(self) -> None:
        """调用方改返回的 list 不能污染缓存。"""
        with tempfile.TemporaryDirectory() as td:
            folder = self._mk_folder(td)
            with mock.patch.object(embed_svc, "_is_blank_cover_file", return_value=False):
                _, gaps1 = E._local_folder_gaps(folder)  # noqa: SLF001
                gaps1.append("污染")
                _, gaps2 = E._local_folder_gaps(folder)  # noqa: SLF001
            self.assertNotIn("污染", gaps2)

    def test_cache_clear_when_over_cap(self) -> None:
        """超过上限时整表清空（防无界增长），仍要返回正确结果。"""
        with tempfile.TemporaryDirectory() as td:
            folder = self._mk_folder(td)
            with mock.patch.object(embed_svc, "_is_blank_cover_file", return_value=False):
                E._folder_gaps_cache[str(folder)] = ((), ("X", []))  # noqa: SLF001
                with mock.patch.object(E, "_FOLDER_GAPS_CACHE_CAP", 0):
                    _, gaps = E._local_folder_gaps(folder)  # noqa: SLF001
            self.assertEqual(len(gaps), 6)
            self.assertNotIn("X", E._folder_gaps_cache)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
