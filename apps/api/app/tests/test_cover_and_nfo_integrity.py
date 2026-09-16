"""第七轮审计回归：封面写入门禁 / NFO 原子写 / 目录 helper / resolve_root 记忆化。

覆盖三处真实缺陷（都可复现）：

1. `embed._write_poster_jpg()` 对**非图片字节**不设防 —— `_is_blank_cover_file()`
   对「PIL 打不开」一律 `return False`（当有效图，避免 PIL 缺编解码器时把全部
   封面误判成空白），且 ≥80_000 字节走体积豁免直接放行。于是源站返回的 HTML
   错误页（>1024B）会被落成 `poster.jpg`，并被 `_blank_cover_cache` 标成有效，
   之后既不会被重下也不会被修。实测：`_write_poster_jpg(HTML 2482B)` 落盘成功。
   修法：以**图片容器头**做廉价硬门禁（不解码、不依赖 PIL），写入门禁 + 本地
   封面有效性判定共用同一道闸。
2. `nfo.write_nfo()` 直接 `path.write_bytes()`（截断 + 写）→ 中途失败留半截 XML，
   下次 `ET.fromstring` 抛错后 `merge_nfo_with_detail` 回落到空 `<movie/>` 根，
   只写本次 detail 带的字段 → **其余元数据静默丢失**。改为原子替换。
3. `db.media_dir()/data_dir()/mirrors_dir()` 每次调用都 `mkdir(exist_ok=True)`
   （Windows 实测 0.26ms，`is_dir()` 只要 0.003ms），而 `resolve_root()` →
   `get_settings()` 是**每番号**路径 → 12.3 万番号约 8.5 分钟纯 syscall。
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as ET

import app.core.db as db
import app.scrap_library.embed as embed_svc
from app.core.atomic_io import atomic_write_bytes, atomic_write_text
from app.scrap_library.nfo import format_nfo_xml, write_nfo

_HTML = (
    b"<!DOCTYPE html><html><head><title>404 Not Found</title></head><body>"
    + b"<p>nginx</p>" * 200
    + b"</body></html>"
)


def _noisy_jpeg(w: int = 800, h: int = 1100) -> bytes:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(0, h, 16):
        d.line([(0, y), (w, y)], fill=((y * 7) % 255, (y * 13) % 255, 200), width=8)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class ImageMagicTest(unittest.TestCase):
    def test_accepts_real_containers(self):
        self.assertTrue(embed_svc._image_magic_ok(_noisy_jpeg()))
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
        self.assertTrue(embed_svc._image_magic_ok(png))
        webp = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 40
        self.assertTrue(embed_svc._image_magic_ok(webp))
        self.assertTrue(embed_svc._image_magic_ok(b"GIF89a" + b"\x00" * 40))

    def test_rejects_html_and_short(self):
        self.assertFalse(embed_svc._image_magic_ok(_HTML))
        self.assertFalse(embed_svc._image_magic_ok(b'{"error":"forbidden"}'))
        self.assertFalse(embed_svc._image_magic_ok(b""))
        self.assertFalse(embed_svc._image_magic_ok(b"\xff\xd8\xff"))  # 太短，样例不完整


class PosterWriteGateTest(unittest.TestCase):
    def test_html_bytes_rejected_by_write(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "ABC-123"
            self.assertIsNone(embed_svc._write_poster_jpg(folder, _HTML))
            self.assertFalse((folder / "poster.jpg").is_file())
            self.assertFalse((folder / "poster.jpg.part").is_file())

    def test_real_jpeg_accepted_by_write(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "ABC-124"
            dest = embed_svc._write_poster_jpg(folder, _noisy_jpeg())
            self.assertIsNotNone(dest)
            self.assertTrue((folder / "poster.jpg").is_file())
            self.assertFalse((folder / "poster.jpg.part").is_file())

    def test_blank_file_gate_flags_html(self):
        """历史坏文件（HTML 落成的 poster.jpg）必须被判为坏封面，才能被重下/清除。"""
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "poster.jpg"
            bad.write_bytes(_HTML)
            self.assertTrue(embed_svc._is_blank_cover_file(bad))
            self.assertTrue(embed_svc._is_blank_cover_bytes(_HTML))
        # 真图不能被误判
        self.assertFalse(embed_svc._is_blank_cover_bytes(_noisy_jpeg()))

    def test_download_remote_poster_rejects_html_payload(self):
        """远程返回 HTML → `download_remote_poster` 不得落盘，返回空串。"""
        from unittest import mock

        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "ABC-125"
            folder.mkdir(parents=True)
            with mock.patch.object(
                embed_svc,
                "_fetch_cover_bytes",
                return_value=(_HTML * 40, "text/html"),
            ):
                rel = embed_svc.download_remote_poster(
                    folder, "https://x.example.com/poster.jpg"
                )
            self.assertEqual(rel, "")
            self.assertFalse((folder / "poster.jpg").is_file())


class NfoAtomicWriteTest(unittest.TestCase):
    def test_round_trip_and_no_leftover_tmp(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ABP-001.nfo"
            root = ET.Element("movie")
            ET.SubElement(root, "title").text = "标题"
            ET.SubElement(root, "num").text = "ABP-001"
            write_nfo(path, root)
            self.assertTrue(path.is_file())
            got = ET.fromstring(path.read_text(encoding="utf-8"))
            self.assertEqual(got.findtext("num"), "ABP-001")
            leftovers = [
                p.name for p in Path(tmp).iterdir() if p.name.startswith(".ABP-001.nfo")
            ]
            self.assertEqual(leftovers, [], "原子写不得留下临时文件")

    def test_overwrite_does_not_truncate_on_second_write(self):
        """重复写同一 NFO：内容始终可解析（旧实现是截断写，中途失败就留半截）。"""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ABP-002.nfo"
            for i in range(3):
                root = ET.Element("movie")
                ET.SubElement(root, "title").text = f"t{i}"
                write_nfo(path, root)
                ET.fromstring(path.read_text(encoding="utf-8"))
            self.assertTrue(
                format_nfo_xml(ET.fromstring(path.read_text(encoding="utf-8"))).endswith(
                    b"</movie>"
                )
            )


class AtomicIoToolTest(unittest.TestCase):
    def test_bytes_and_text(self):
        with TemporaryDirectory() as tmp:
            bp = Path(tmp) / "a.bin"
            atomic_write_bytes(bp, b"\x00\x01\x02")
            self.assertEqual(bp.read_bytes(), b"\x00\x01\x02")
            tp = Path(tmp) / "b.txt"
            atomic_write_text(tp, "中文内容")
            self.assertEqual(tp.read_text(encoding="utf-8"), "中文内容")
            self.assertEqual(
                [p.name for p in Path(tmp).iterdir() if p.name.startswith(".")], []
            )

    def test_site_mirror_alias_still_present(self):
        """`site_mirror.atomic_write_text` 是对外名（探针会 getattr），必须保留。"""
        import app.core.site_mirror as sm

        self.assertTrue(callable(getattr(sm, "atomic_write_text", None)))


class DirHelperTest(unittest.TestCase):
    def test_ensure_dir_only_mkdir_when_missing(self):
        calls: list[str] = []
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "x"
            with unittest.mock.patch.object(
                Path, "mkdir", autospec=True, side_effect=lambda self, **kw: calls.append(str(self))
            ):
                db._ensure_dir(p)  # 不存在 → 应 mkdir
            self.assertEqual(calls, [str(p)])

            p.mkdir(parents=True, exist_ok=True)
            calls.clear()
            with unittest.mock.patch.object(
                Path, "mkdir", autospec=True, side_effect=lambda self, **kw: calls.append(str(self))
            ):
                db._ensure_dir(p)  # 已存在 → 不得 mkdir
            self.assertEqual(calls, [])
            self.assertEqual(db._ensure_dir(p), p)

    def test_helpers_return_existing_dirs(self):
        for fn in (db.data_dir, db.media_dir, db.mirrors_dir, db.debug_dir):
            p = fn()
            self.assertTrue(p.is_dir(), f"{fn.__name__} 应返回已存在目录")


class ResolveRootMemoTest(unittest.TestCase):
    def test_memoized_and_stable(self):
        a = embed_svc.resolve_root("scrap-library")
        b = embed_svc.resolve_root("scrap-library")
        self.assertIs(a, b, "同一入参应命中记忆化（同一对象）")
        self.assertTrue(a.is_absolute())
        # None 与默认串等价
        self.assertEqual(embed_svc.resolve_root(None), embed_svc.resolve_root("scrap-library"))

    def test_invalid_still_raises_and_is_not_memoized(self):
        for _ in range(3):
            with self.assertRaises(ValueError):
                embed_svc.resolve_root("../escape")
        self.assertTrue(
            Path(embed_svc.resolve_root("scrap-library")).is_absolute()
        )


if __name__ == "__main__":
    unittest.main()
