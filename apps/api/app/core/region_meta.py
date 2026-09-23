"""六区元数据与番号前缀规范化（供 prefix 扫库 / 搜索共用）。"""

from __future__ import annotations

import re

from app.core.maps_paths import regions_doc

_REGION_DOC = regions_doc()
REGION_META: dict[str, dict[str, str]] = {
    str(k): {str(sk): str(sv) for sk, sv in dict(v).items()}
    for k, v in dict(_REGION_DOC.get("regions") or {}).items()
}
_ORDER = [str(x) for x in (_REGION_DOC.get("order") or [])]
REGION_ORDER = [x for x in _ORDER if x in REGION_META] or list(REGION_META.keys())

# 仅日本有码把女优名写入索引副文案；其它区只保留标题
# （原 japan_gravure / 日本写真已并入 japan_censored）
FORUM_ACTORS_INDEX_REGIONS = frozenset({"japan_censored"})

# 旧区 id / 中文标签 → 现 canonical（写真并入有码）
_LEGACY_REGION_REDIRECT: dict[str, str] = {
    "japan_gravure": "japan_censored",
    "gravure": "japan_censored",
    "写真": "japan_censored",
    "日本写真": "japan_censored",
}


def std_prefix(prefix: str) -> str:
    """前缀键规范化；FC2-PPV / FC2PPV 一律归并为 FC2。"""
    p = str(prefix or "").strip().upper().replace("_", "-")
    compact = re.sub(r"[\s\-]", "", p)
    if compact == "FC2PPV" or p in {"FC2-PPV", "FC2_PPV"}:
        return "FC2"
    return p


def resolve_fs_region(region: str | None) -> str | None:
    """前端 / 白名单 region → 六区 id（写真已并入有码）。"""
    raw = str(region or "").strip()
    if not raw:
        return None
    key = raw.lower()
    # 别名表（含 japan_gravure → japan_censored）
    aliases = {
        str(k).strip().lower(): str(v).strip()
        for k, v in dict(_REGION_DOC.get("aliases") or {}).items()
        if str(k).strip() and str(v).strip()
    }
    if key in aliases:
        mapped = aliases[key]
        if mapped in REGION_META:
            return mapped
        # aliases 里 japan → japan（粗粒度）等：再走下面
        key = mapped.lower()
    if raw in _LEGACY_REGION_REDIRECT:
        return _LEGACY_REGION_REDIRECT[raw]
    if key in _LEGACY_REGION_REDIRECT:
        return _LEGACY_REGION_REDIRECT[key]
    if key in ("amateur", "素人"):
        return "japan_amateur"
    if key in ("fc2ppv",):
        return "fc2"
    if key in REGION_META:
        return key
    # 中文全称
    for rid, meta in REGION_META.items():
        label = str(meta.get("label") or "")
        if raw == label or key == label.casefold():
            return rid
    return None


def indexes_forum_actors(region: str | None) -> bool:
    """是否索引女优（日本有码，含原写真前缀）。"""
    rid = resolve_fs_region(region)
    return bool(rid and rid in FORUM_ACTORS_INDEX_REGIONS)


def is_fc2_plate_maker_name(name: str) -> bool:
    """论坛板名/前缀壳，不是真实 FC2 作者名。"""
    s = re.sub(r"[\s·\-_/=]+", "", str(name or "").strip().lower())
    if not s:
        return True
    return s in {"fc2", "fc2ppv", "fc2ppvfc2"} or s.startswith("fc2fc2") or bool(
        re.fullmatch(r"fc2(ppv)?", s)
    )


def fc2_prefix_from_code(code: str) -> str:
    """番号 → catalog 前缀键：一律 FC2（旧 FC2PPV 写入也归并）。"""
    _ = code
    return "FC2"


def fc2_fs_prefix(prefix: str = "", *, code: str = "") -> str:
    """catalog 前缀 / 番号 → 磁盘前缀夹名：一律 FC2。

    旧夹 ``FC2-PPV`` / ``FC2PPV`` 仅作读路径兼容，写入不再产出。
    """
    p = str(prefix or "").strip().upper().replace("_", "-")
    if not p and code:
        p = "FC2"
    compact = re.sub(r"[\s\-]", "", p)
    if compact.startswith("FC2") or (
        code and re.search(r"FC2", str(code or ""), re.I)
    ):
        return "FC2"
    return p or "FC2"


def normalize_fc2_code(code: str) -> str:
    """统一番号写法：一律 ``FC2-{num}``（含旧 FC2-PPV / FC2PPV）。"""
    s = str(code or "").strip().upper().replace("_", "-")
    m = re.search(r"FC2(?:-?PPV)?-?(\d+)", s, re.I)
    if m:
        return f"FC2-{m.group(1)}"
    return s


def db_region_for(fs_region: str | None) -> str | None:
    meta = REGION_META.get(str(fs_region or ""))
    if not meta:
        return None
    return str(meta.get("db_region") or "").strip() or None
