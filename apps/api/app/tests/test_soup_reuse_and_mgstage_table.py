# -*- coding: utf-8 -*-
"""第八轮：HTML 解析复用 + mgstage 标签表单次扫描 的回归测试。

覆盖三件事：
1. `common.soup` 语义 —— 同线程同对象只解析一次；换内容/换线程各解析一次；
   空串等价 `BeautifulSoup("", "lxml")`（旧行为）。
2. `mgstage._table_value` / `_parse_genres` —— 与「旧实现」逐字等价（子串匹配、
   最后一个命中覆盖、td 缺失跳过、链接拼接、空白折叠）。
3. `lulubar` 不再变异共享解析树（这是 `soup` 复用引入的真实地雷：
   原来在 `soup(html)` 的树上 `decompose()`）。
"""

from __future__ import annotations

import re
import threading
import unittest

from app.scrape_details import common
from app.scrape_details import lulubar
from app.scrape_details import mgstage
from app.scrape_details.common import soup, strip_tags


def _old_table_value(html: str, label: str) -> str:
    """旧实现的原样拷贝（每次都新建解析树），用作等价性基准。"""
    from bs4 import BeautifulSoup

    doc = BeautifulSoup(html or "", "lxml")
    out = ""
    for th in doc.select(".detail_data th"):
        if label not in mgstage._normalize_label(th.get_text()):
            continue
        td = th.find_next_sibling("td")
        if td is None:
            continue
        links = [
            strip_tags(a.get_text()).strip()
            for a in td.select("a")
            if strip_tags(a.get_text()).strip()
        ]
        out = ", ".join(links) if links else strip_tags(td.get_text())
    return re.sub(r"\s+", " ", out).strip()


DETAIL_HTML = """
<html><body>
<div class="detail_data">
  <table>
    <tr><th>品番：</th><td>AGAV-022</td></tr>
    <tr><th>メーカー</th><td><a href="/m/1"> MGStage </a><a href="/m/2"></a></td></tr>
    <tr><th>シリーズ</th><td>系列 名</td></tr>
    <tr><th>配信開始日</th><td>2024/01/02</td></tr>
    <tr><th>収録時間</th><td>120分</td></tr>
    <tr><th>出演</th><td><a href="/a/1">女优A</a>, <a href="/a/2">女优B</a></td></tr>
    <tr><th>ジャンル</th><td><a href="/g/1">巨乳</a><a href="/g/2">単体作品</a></td></tr>
    <tr><th>ジャンル</th><td><a href="/g/1">巨乳</a></td></tr>
    <tr><th>品番(再掲)</th><td>AGAV-022-R2</td></tr>
    <tr><th>孤立标签</th></tr>
  </table>
</div>
</body></html>
"""


class SoupReuseTest(unittest.TestCase):
    def setUp(self) -> None:
        if hasattr(common._tls, "soup_entry"):
            del common._tls.soup_entry

    def test_same_html_same_thread_parses_once(self) -> None:
        h = "<html><body><p>x</p></body></html>"
        self.assertIs(soup(h), soup(h))

    def test_identity_only_shares_object_not_equality(self) -> None:
        """内容相同但**不是同一个对象**时各解析一次（保守，避免内容改动误命中）。"""
        build = lambda: "".join(["<html><body><p>", "x", "</p></body></html>"])
        a, b = build(), build()
        self.assertIsNot(soup(a), soup(b))

    def test_different_html_reparses(self) -> None:
        a = soup("<html><body><p>a</p></body></html>")
        b = soup("<html><body><p>b</p></body></html>")
        self.assertIsNot(a, b)

    def test_not_shared_across_threads(self) -> None:
        h = "<html><body><p>thread</p></body></html>"
        main_doc = soup(h)
        seen: list[object] = []

        def run() -> None:
            seen.append(soup(h))

        t = threading.Thread(target=run)
        t.start()
        t.join()
        self.assertEqual(len(seen), 1)
        self.assertIsNot(main_doc, seen[0])

    def test_empty_html(self) -> None:
        self.assertEqual(soup("").get_text(strip=True), "")
        self.assertEqual(soup(None).get_text(strip=True), "")  # type: ignore[arg-type]

    def test_read_only_tree_survives_repeat_calls(self) -> None:
        """同一棵树被复用后，重复读取结果必须一致（只读语义）。"""
        rows1 = mgstage._table_value(DETAIL_HTML, "品番")
        rows2 = mgstage._table_value(DETAIL_HTML, "品番")
        self.assertEqual(rows1, rows2)


class MgstageTableEquivalenceTest(unittest.TestCase):
    def setUp(self) -> None:
        if hasattr(common._tls, "soup_entry"):
            del common._tls.soup_entry
        if hasattr(mgstage._tls, "label_rows"):
            del mgstage._tls.label_rows

    def test_table_value_matches_old_impl(self) -> None:
        for label in (
            "品番",
            "メーカー",
            "シリーズ",
            "配信開始日",
            "収録時間",
            "出演",
            "ジャンル",
            "不存在",
        ):
            with self.subTest(label=label):
                self.assertEqual(
                    mgstage._table_value(DETAIL_HTML, label),
                    _old_table_value(DETAIL_HTML, label),
                )

    def test_last_match_wins(self) -> None:
        """`品番` 子串命中两行 → 取**最后**一行（旧语义）。"""
        self.assertEqual(mgstage._table_value(DETAIL_HTML, "品番"), "AGAV-022-R2")

    def test_missing_td_does_not_overwrite(self) -> None:
        """th 无 td 兄弟 → 跳过，不覆盖已有结果。"""
        self.assertIn("AGAV-022", mgstage._table_value(DETAIL_HTML, "品番"))

    def test_genres_matches_old_impl(self) -> None:
        old: list[str] = []
        from bs4 import BeautifulSoup

        doc = BeautifulSoup(DETAIL_HTML, "lxml")
        for th in doc.select(".detail_data th"):
            if "ジャンル" not in mgstage._normalize_label(th.get_text()):
                continue
            td = th.find_next_sibling("td")
            if td is None:
                continue
            for a in td.select("a"):
                g = strip_tags(a.get_text()).strip()
                if g and g not in old:
                    old.append(g)
        self.assertEqual(mgstage._parse_genres(DETAIL_HTML), old[:40])
        self.assertIn("巨乳", mgstage._parse_genres(DETAIL_HTML))

    def test_label_rows_scanned_once(self) -> None:
        """多次取值只应产生 1 次 `.detail_data th` 全树扫描（按解析树身份缓存）。"""
        from bs4.element import Tag

        scans = {"n": 0}
        orig = Tag.select

        def counting(self, *a, **kw):  # noqa: ANN001
            if a and a[0] == ".detail_data th":
                scans["n"] += 1
            return orig(self, *a, **kw)

        Tag.select = counting
        try:
            for label in ("品番", "メーカー", "シリーズ", "配信開始日", "収録時間", "出演"):
                mgstage._table_value(DETAIL_HTML, label)
            mgstage._parse_genres(DETAIL_HTML)
        finally:
            Tag.select = orig
        self.assertEqual(
            scans["n"], 1, f"应只扫 1 遍，实际扫了 {scans['n']} 遍"
        )


def _lulubar_html() -> str:
    pad = "<!-- pad --> " * 400
    return (
        "<html><body>"
        "<div id='detail'>"
        "<h2 class='mb-1'>ABC-123 "
        "<a class='ogtag'>标签文字不该出现</a> 正片标题</h2>"
        "<div class='tag_box'>"
        "<a class='tag' href='/bydatedetail/1'>2024-01-02</a>"
        "</div>"
        "</div>"
        f"{pad}"
        "</body></html>"
    )


class LulubarNoMutationTest(unittest.TestCase):
    def setUp(self) -> None:
        if hasattr(common._tls, "soup_entry"):
            del common._tls.soup_entry

    def test_shared_tree_is_not_mutated(self) -> None:
        html = _lulubar_html()
        first = lulubar._parse_detail(html, "https://example.com/detail/ABC-123/", "ABC-123")
        # 共享树里 a.ogtag 必须还在（说明没有在原树上 decompose）
        doc = soup(html)
        self.assertEqual(
            len(doc.select("h2.mb-1 a.ogtag")),
            1,
            "`lulubar` 不应再变异 `soup()` 返回的共享解析树",
        )
        second = lulubar._parse_detail(html, "https://example.com/detail/ABC-123/", "ABC-123")
        self.assertEqual(first.get("title"), second.get("title"))

    def test_ogtag_text_excluded_from_title(self) -> None:
        html = _lulubar_html()
        out = lulubar._parse_detail(html, "https://example.com/detail/ABC-123/", "ABC-123")
        self.assertNotIn("标签文字不该出现", str(out.get("title") or ""))
        self.assertIn("正片标题", str(out.get("title") or ""))


if __name__ == "__main__":
    unittest.main()
