"""封面下载：字段优先池全灭时，必须仍然尝试全局回退池。

背景：`download_best_cover` 用 `max_urls`（批量 5 / 单刷 6）限制一次刮削的
候选下载数。原实现这样算全局补充池的剩余额度：

    remain_budget = max(0, max_urls - len(tried))
    take_n = min(GLOBAL_SUPPLEMENT_N, remain_budget, len(global_pool))

`tried` 记录的是**已尝试的 URL**（含失败的）。当 `fieldPriority` 里配了
≥ max_urls 个源时，优先池一跑就把额度占满（哪怕全部下载失败），
`remain_budget` 恒为 0 → `take_n = 0` → **全局池永远不被尝试**。
结果：这些目录的封面直接失败，且因为封面是硬缺口，会被反复重新入队
重刮（浪费网络），形成「有些番号海报怎么都补不上」的观感。

修法：`all_scored` 为空（优先池全灭、一个候选都没有）时放开该额度，
仍以 `GLOBAL_SUPPLEMENT_N` 为上限。
"""

from __future__ import annotations

import io
import random
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import app.scrap_library.embed as embed_svc
from app.scrap_library import cover_download as cd


def _noisy_jpeg(w: int = 400, h: int = 600) -> bytes:
    """生成有内容的竖图（避免被判空白）。"""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    rnd = random.Random(7)
    for y in range(0, h, 16):
        d.line(
            [(0, y), (w, y)],
            fill=(rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)),
            width=8,
        )
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class GlobalFallbackTest(unittest.TestCase):
    def _run(self, *, priority_n: int, global_n: int) -> dict:
        fp = [f"s{i}" for i in range(priority_n)]
        entries = [
            {"source": f"s{i}", "url": f"https://p{i}.example.com/a.jpg"}
            for i in range(priority_n)
        ] + [
            {"source": f"gz{i}", "url": f"https://g{i}.example.com/a.jpg"}
            for i in range(global_n)
        ]
        jpeg = _noisy_jpeg()

        def fake_fetch(url: str, *, slot_timeout=None):
            # 优先池全部下载失败；全局池返回有效图
            if "g0.example.com" in url or "g1.example.com" in url:
                return jpeg, "image/jpeg"
            return None

        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with mock.patch.object(embed_svc, "_fetch_cover_bytes", side_effect=fake_fetch):
                return cd.download_best_cover(
                    folder,
                    entries,
                    region="japan_censored",
                    batch_mode=True,
                    field_priority=fp,
                    region_sources=fp,
                )

    def test_global_pool_reached_when_priority_pool_dies(self):
        """优先池 6 个源全灭（≥ max_urls=5）→ 仍必须试到全局池。"""
        res = self._run(priority_n=6, global_n=2)
        tried = [str(u) for u in (res.get("tried") or [])]
        self.assertTrue(tried, "应当有下载尝试记录")
        reached_global = any("g0.example.com" in u or "g1.example.com" in u for u in tried)
        self.assertTrue(
            reached_global,
            f"优先池全灭后未尝试全局池 —— tried={tried}",
        )

    def test_global_fallback_still_capped(self):
        """放开额度不能变成无限补试：全局池 host 数仍受 GLOBAL_SUPPLEMENT_N 约束。"""
        from urllib.parse import urlparse

        res = self._run(priority_n=6, global_n=6)
        tried = [str(u) for u in (res.get("tried") or [])]
        global_hosts = {
            (urlparse(u).hostname or "")
            for u in tried
            if (urlparse(u).hostname or "").startswith("g")
        }
        global_hosts.discard("")
        self.assertTrue(global_hosts)
        self.assertLessEqual(
            len(global_hosts),
            cd.GLOBAL_SUPPLEMENT_N,
            f"全局池 host 数应 ≤ GLOBAL_SUPPLEMENT_N —— tried={tried}",
        )


class MidScoreSupplementaryTest(unittest.TestCase):
    """优先池「出了图但都不够落盘」时，同样必须补试全局池。

    第七轮补漏：第五轮只放开了「优先池**全灭**（`all_scored` 为空）」这一支，
    另一支仍被 `remain_budget = max(0, max_urls - len(tried))` 卡死。
    触发条件（读 `_run_pool` + `need_more` 分支链可以推出来）：

    - 优先池**有**候选进了 `all_scored`（所以 `not all_scored` 那条放开分支不生效）；
    - 候选尺寸都不到 `meets_disk_min_size`（图标级极小图，`best_disk_ok=False`）
      → 所有 `need_more=False` 的分支都不成立 → `need_more` 保持 True；
    - 优先池源数 ≥ `max_urls`（批量 5），`tried` 被占满 → `remain_budget = 0`。

    结果：`take_n = 0`，全局池拿不到机会，而优先池的图又落不了盘 → 封面直接失败。
    这正是「字段优先级配满 5 个源、全是废图」的现场。
    """

    def _run(self, *, priority_n: int, global_n: int) -> dict:
        fp = [f"s{i}" for i in range(priority_n)]
        entries = [
            {"source": f"s{i}", "url": f"https://p{i}.example.com/a.jpg"}
            for i in range(priority_n)
        ] + [
            # 全局池用 pl 图层 + 高分辨率 → 分数明显更高且能落盘
            {"source": f"gz{i}", "url": f"https://g{i}.example.com/pl.jpg"}
            for i in range(global_n)
        ]
        low = _noisy_jpeg(16, 16)  # 低于落盘地板 → 仍视为不可用
        high = _noisy_jpeg(900, 1300)

        def fake_fetch(url: str, *, slot_timeout=None):
            if "g" in url.split("//", 1)[-1][:2]:
                return high, "image/jpeg"
            return low, "image/jpeg"

        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with mock.patch.object(embed_svc, "_fetch_cover_bytes", side_effect=fake_fetch):
                return cd.download_best_cover(
                    folder,
                    entries,
                    region="japan_censored",
                    batch_mode=True,
                    field_priority=fp,
                    region_sources=fp + ["gz0", "gz1"],
                )

    def test_unusable_priority_candidates_still_try_global(self):
        res = self._run(priority_n=6, global_n=2)
        tried = [str(u) for u in (res.get("tried") or [])]
        self.assertTrue(tried, "应当有下载尝试记录")
        reached_global = any("g0.example.com" in u or "g1.example.com" in u for u in tried)
        self.assertTrue(
            reached_global,
            f"优先池候选都不够落盘时未补试全局池 —— tried={tried}",
        )
        # 优先池 5 个候选（max_urls=5）已占满额度；补试 host 数 ≤ GLOBAL_SUPPLEMENT_N
        # （单 URL 可能被 upgrade 裂成 pl/ps，故按 host 计）
        from urllib.parse import urlparse

        global_hosts = {
            (urlparse(u).hostname or "")
            for u in tried
            if "g" in (urlparse(u).hostname or "")[:2]
        }
        global_hosts.discard("")
        self.assertTrue(global_hosts)
        self.assertLessEqual(
            len(global_hosts),
            cd.GLOBAL_SUPPLEMENT_N,
            f"全局补试 host 数应 ≤ GLOBAL_SUPPLEMENT_N —— tried={tried}",
        )


class FallbackSourceReservedTest(unittest.TestCase):
    """全局补充必须给 miss_av 留席，不能被 jav321 慢 CDN 挤掉。"""

    def test_pick_global_supplement_reserves_miss_av(self) -> None:
        pool = [
            {"source": "jav321", "url": "https://www.jav321.com/a.jpg"},
            {"source": "airav_io", "url": "https://airav.example/a.jpg"},
            {"source": "miss_av", "url": "https://missav.example/a.jpg"},
            {"source": "freejavbt", "url": "https://fjb.example/a.jpg"},
        ]
        # 模拟已按 unstable 殿后排好：airav → freejavbt → miss → jav321
        ordered = [
            pool[1],
            pool[3],
            pool[2],
            pool[0],
        ]
        got = cd.pick_global_supplement(ordered, used=set(), take_n=2)
        srcs = [str(e.get("source")) for e in got]
        self.assertEqual(len(got), 2)
        self.assertIn("miss_av", srcs, f"兜底源必须占一席 —— {srcs}")
        self.assertNotIn("jav321", srcs, f"不稳 CDN 不应挤掉兜底 —— {srcs}")

    def test_miss_av_tried_when_jav321_fails(self) -> None:
        fp = ["mgstage", "javbus"]
        entries = [
            {"source": "mgstage", "url": "https://image.mgstage.com/x.jpg"},
            {"source": "jav321", "url": "https://www.jav321.com/x.jpg"},
            {"source": "miss_av", "url": "https://missav.example/pl.jpg"},
        ]
        jpeg = _noisy_jpeg(420, 600)

        def fake_fetch(url: str, *, slot_timeout=None):
            if "missav.example" in url:
                return jpeg, "image/jpeg"
            return None

        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with mock.patch.object(embed_svc, "_fetch_cover_bytes", side_effect=fake_fetch):
                res = cd.download_best_cover(
                    folder,
                    entries,
                    region="japan_amateur",
                    batch_mode=True,
                    field_priority=fp,
                    region_sources=fp + ["jav321", "miss_av"],
                    overwrite=True,
                )
        tried = [str(u) for u in (res.get("tried") or [])]
        self.assertTrue(
            any("missav.example" in u for u in tried),
            f"jav321/mgstage 失败后应试 miss_av —— tried={tried}",
        )
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("coverSource"), "miss_av")


class FourhoiRefererPlanTest(unittest.TestCase):
    def test_fourhoi_uses_missav_referer(self) -> None:
        from app.scrap_library.cover_focus_routes import _referer_plan

        primary, alt = _referer_plan("fourhoi.com", "https")
        self.assertEqual(primary, "https://missav.ws/")
        self.assertEqual(alt, "https://missav.live/")

    def test_jav321_is_slow_host(self) -> None:
        from app.scrap_library.cover_focus_routes import _is_slow_cover_host

        self.assertTrue(_is_slow_cover_host("www.jav321.com"))
        self.assertTrue(_is_slow_cover_host("jav321.com"))


if __name__ == "__main__":
    unittest.main()
