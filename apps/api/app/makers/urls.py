"""片商目录的 URL 工具。

``catalog_routes`` 与 ``providers_extra`` 曾各写一份**逐字节相同**的 ``_abs``；
这里收敛为单一实现，两个模块各自保留同名薄封装（调用点零改动）。

注意：``scrape_details.common.abs_url`` 是另一个函数（参数顺序为 href, base，
且会先识别完整 http(s):// 前缀），不要与本模块的 ``join_url(base, href)`` 混用。
"""

from __future__ import annotations

from urllib.parse import urljoin


def join_url(base: str, href: str | None) -> str | None:
    """把页面上的相对链接拼成绝对地址；``//`` 开头补 https，失败返回 None。"""
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        return f"https:{href}"
    try:
        return urljoin(base if base.endswith("/") else base + "/", href)
    except Exception:  # noqa: BLE001
        return None
