# -*- coding: utf-8 -*-
"""年份提取的两套口径（曾各自复制在 media / makers / scrape_details 共 5 处）。

两个函数**语义不同，不要合并**：

- `year_prefix`：只认「字符串开头就是 4 位数字」的日期，适合 ISO 日期
  （TMDB `release_date` / Douban `pubdate` / Bangumi `date`）；
- `year_search`：在整串里找 19xx/20xx，适合抓来的自由文本
  （片商目录的标题、日期串）。

反例说明差异：`"abcd2020"` → `year_prefix` 返回 `None`，`year_search` 返回 `"2020"`。
"""

from __future__ import annotations

import re

_YEAR_RE = re.compile(r"(20\d{2}|19\d{2})")


def year_prefix(date_s: str | None) -> str | None:
    """ISO 日期取前 4 位；不足 4 位或前 4 位非数字则 None。"""
    s = str(date_s or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return None


def year_search(s: str | None) -> str | None:
    """在整串中搜索第一个 19xx/20xx。"""
    m = _YEAR_RE.search(str(s or ""))
    return m.group(1) if m else None
