"""刮削目录 / 文件命名模板（基础 {var} + Jinja2 {{ var }}）。

七区默认路径：
- 有码/写真/无码/素人：日本有码/S1/SONE/SONE-001
- FC2：FC2/作者/FC2PPV/FC2PPV-0454667
- 国产/欧美：国产无码/麻豆/MD/MD-013
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, StrictUndefined, Undefined
except ImportError:  # pragma: no cover
    Environment = None  # type: ignore[misc, assignment]
    StrictUndefined = None  # type: ignore[misc, assignment]
    Undefined = None  # type: ignore[misc, assignment]

_BAD_CHARS_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
_MULTI_SLASH_RE = re.compile(r"[/\\]+")
_BASIC_VAR_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

IMAGE_NAME_MODES = frozenset({"plain", "number"})
_DIR_STD = "{category}/{studio}/{series_name}/{number}"

KIND_ORDER = (
    "japan_censored",
    "japan_gravure",
    "japan_uncensored",
    "japan_amateur",
    "fc2",
    "china",
    "western",
)

KIND_LABELS: dict[str, str] = {
    "japan_censored": "日本有码",
    "japan_gravure": "日本写真",
    "japan_uncensored": "日本无码",
    "japan_amateur": "日本素人",
    "fc2": "FC2",
    "china": "国产无码",
    "western": "欧美无码",
}

KIND_PATH_EXAMPLES: dict[str, str] = {
    "japan_censored": "日本有码/S1/SONE/SONE-001",
    "japan_gravure": "日本写真/Graphis/GRA/GRA-001",
    "japan_uncensored": "日本无码/Caribbean/CARIB/CARIB-001",
    "japan_amateur": "日本素人/厂牌/SIRO/SIRO-001",
    "fc2": "FC2/作者名/FC2PPV/FC2PPV-0454667",
    "china": "国产无码/麻豆/MD/MD-013",
    "western": "欧美无码/Studio/ABC/ABC-001",
}

DEFAULT_KIND_RULE: dict[str, str] = {
    "directoryTemplate": _DIR_STD,
}


def _default_by_kind() -> dict[str, dict[str, str]]:
    return {kid: dict(DEFAULT_KIND_RULE) for kid in KIND_ORDER}


DEFAULT_NAMING: dict[str, Any] = {
    "directoryTemplate": _DIR_STD,
    "directoryMaxLength": 0,
    "imageNameMode": "plain",
    "actorLimit": 0,
    "byKind": _default_by_kind(),
    "namingSchema": 3,
}

NAMING_VARS_DOC: list[dict[str, str]] = [
    {"id": "number", "label": "番号 (如 ABS-001)"},
    {"id": "publish_number", "label": "发行号 (如 118abs001)"},
    {"id": "series_name", "label": "番号前缀 (如 ABS)"},
    {"id": "serial_number", "label": "番号后缀 (如 001)"},
    {"id": "first_letter", "label": "番号前缀首字母 (如 A)"},
    {"id": "series", "label": "系列"},
    {"id": "category", "label": "分类"},
    {"id": "actor", "label": "演员"},
    {"id": "first_actor", "label": "首位演员"},
    {"id": "title", "label": "标题"},
    {"id": "originaltitle", "label": "原标题"},
    {"id": "year", "label": "发布年份"},
    {"id": "director", "label": "导演"},
    {"id": "studio", "label": "制片方 / FC2作者"},
    {"id": "publisher", "label": "发行方"},
    {"id": "runtime", "label": "时长(分钟)"},
    {"id": "release", "label": "发布日期"},
    {"id": "source_filename", "label": "源文件名 (不含扩展名)"},
    {"id": "filename", "label": "源文件名别名"},
    {"id": "source_path", "label": "源文件完整路径"},
    {"id": "subtitle", "label": "中文字幕标识"},
    {"id": "mosaic", "label": "有码/无码标识"},
    {"id": "resolution", "label": "分辨率"},
]


def normalize_naming(raw: Any = None) -> dict[str, Any]:
    """落盘路径固定为四级目录；忽略用户自定义模板（本地库文件夹为准）。"""
    del raw  # 兼容旧调用，一律固定默认
    by_kind = _default_by_kind()
    return {
        "directoryTemplate": _DIR_STD,
        "directoryMaxLength": 0,
        "imageNameMode": "plain",
        "actorLimit": 0,
        "namingSchema": 3,
        "byKind": by_kind,
        "directoryByKind": {
            kid: by_kind[kid]["directoryTemplate"] for kid in KIND_ORDER
        },
        "kindLabels": dict(KIND_LABELS),
        "kindExamples": dict(KIND_PATH_EXAMPLES),
        "varsDoc": [],
    }


def fixed_naming() -> dict[str, Any]:
    return normalize_naming(None)

def resolve_kind(
    *,
    kind: str | None = None,
    region: str | None = None,
    code: str = "",
) -> str:
    k = str(kind or "").strip()
    if k in KIND_ORDER:
        return k
    r = str(region or "").strip()
    if r in KIND_ORDER:
        return r
    c = str(code or "").strip().upper()
    if c.startswith("FC2"):
        return "fc2"
    return "japan_censored"


def kind_rule(naming: dict[str, Any], kind: str | None) -> dict[str, str]:
    kid = resolve_kind(kind=kind)
    by = naming.get("byKind") if isinstance(naming.get("byKind"), dict) else {}
    cur = by.get(kid) if isinstance(by.get(kid), dict) else {}
    return {
        "directoryTemplate": str(
            (cur or {}).get("directoryTemplate")
            or naming.get("directoryTemplate")
            or _DIR_STD
        ),
    }


def _actor_limit(naming: dict[str, Any]) -> int:
    n = int(naming.get("actorLimit") or 0)
    return 3 if n <= 0 else n


def _safe_segment(name: str) -> str:
    s = _BAD_CHARS_RE.sub("", str(name or "")).strip()
    s = s.replace("/", "／").replace("\\", "＼")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .") or "未知"


def _split_code(code: str) -> tuple[str, str, str]:
    c = str(code or "").strip().upper().replace("_", "-")
    m = re.match(r"^FC2(?:-?PPV)?-?(\d+)$", c)
    if m:
        return "FC2PPV", m.group(1), "F"
    if "-" in c:
        pre, suf = c.split("-", 1)
        return pre, suf, (pre[:1] if pre else "")
    m2 = re.match(r"^([A-Z]+)(\d+)$", c)
    if m2:
        return m2.group(1), m2.group(2), m2.group(1)[:1]
    return c, "", (c[:1] if c else "")


def _normalize_fc2_number(number: str, serial: str) -> str:
    digits = re.sub(r"\D", "", serial or "")
    if not digits:
        digits = re.sub(r"\D", "", number)
    return f"FC2PPV-{digits}" if digits else "FC2PPV"


def build_naming_context(
    *,
    code: str,
    meta: dict[str, Any],
    target: dict[str, Any],
    category: str,
    naming: dict[str, Any],
    kind: str | None = None,
    missing: str = "未知",
) -> dict[str, Any]:
    kid = resolve_kind(
        kind=kind or str(meta.get("scrapeKind") or ""),
        region=str(target.get("region") or meta.get("region") or ""),
        code=code,
    )
    number = str(code or meta.get("code") or "").strip().upper()
    prefix, serial, first_letter = _split_code(number)
    target_prefix = str(target.get("prefix") or prefix or "").strip().upper() or prefix

    if kid == "fc2":
        prefix = "FC2PPV"
        target_prefix = "FC2PPV"
        number = _normalize_fc2_number(number, serial)
        serial = number.split("-", 1)[-1] if "-" in number else serial
        first_letter = "F"

    actors_raw = meta.get("actors") if isinstance(meta.get("actors"), list) else []
    actors = [str(a).strip() for a in actors_raw if str(a).strip()]
    limit = _actor_limit(naming)
    if len(actors) > limit:
        actor_str = "多人作品"
    else:
        actor_str = " ".join(actors) if actors else missing

    title = str(meta.get("titleZh") or meta.get("title") or "").strip() or missing
    original = (
        str(
            meta.get("originalTitle")
            or meta.get("originaltitle")
            or meta.get("title")
            or ""
        ).strip()
        or missing
    )
    studio = (
        str(
            meta.get("studio")
            or (meta.get("makers") or [None])[0]
            or target.get("maker")
            or ""
        ).strip()
        or missing
    )
    maker = str(target.get("maker") or studio or "").strip() or missing
    if kid == "fc2" and (not maker or maker in {"未知", "未分组"}):
        maker = actors[0] if actors else "未知作者"
        if studio in {"未知", "未分组"}:
            studio = maker

    product_id = str(meta.get("productId") or meta.get("publish_number") or "").strip()
    premiered = str(meta.get("premiered") or meta.get("release") or "").strip()
    year = ""
    if premiered and len(premiered) >= 4 and premiered[:4].isdigit():
        year = premiered[:4]
    elif meta.get("year"):
        year = str(meta.get("year")).strip()

    cat = category or KIND_LABELS.get(kid) or missing

    return {
        "number": number or missing,
        "publish_number": product_id or missing,
        "series_name": target_prefix or missing,
        "serial_number": serial or missing,
        "first_letter": first_letter or missing,
        "series": str(meta.get("series") or "").strip() or missing,
        "category": cat,
        "actor": actor_str,
        "first_actor": (actors[0] if actors else missing),
        "title": title,
        "originaltitle": original,
        "year": year or missing,
        "director": str(meta.get("director") or "").strip() or missing,
        "studio": maker if maker not in {"未知", "未分组"} else studio,
        "publisher": str(meta.get("publisher") or studio or "").strip() or missing,
        "runtime": (
            str(meta.get("runtime"))
            if meta.get("runtime") is not None and str(meta.get("runtime")).strip()
            else missing
        ),
        "release": premiered or missing,
        "source_filename": str(
            meta.get("source_filename") or meta.get("filename") or ""
        ).strip()
        or missing,
        "filename": str(
            meta.get("filename") or meta.get("source_filename") or ""
        ).strip()
        or missing,
        "source_path": str(meta.get("source_path") or "").strip() or missing,
        "subtitle": str(meta.get("subtitle") or "").strip() or missing,
        "mosaic": str(meta.get("mosaic") or "").strip() or missing,
        "resolution": str(meta.get("resolution") or "").strip() or missing,
        "_kind": kid,
    }


def _jinja_env(*, strict: bool) -> Any:
    if Environment is None:
        return None

    def _split(value: Any, sep: str = "-") -> list[str]:
        return str(value or "").split(sep)

    def _truncate(
        value: Any, length: int = 20, killwords: bool = True, end: str = "..."
    ) -> str:
        del killwords
        s = str(value or "")
        if len(s) <= length:
            return s
        return s[: max(0, length - len(end))] + end

    undefined = StrictUndefined if strict else Undefined
    env = Environment(undefined=undefined, autoescape=False)
    env.filters["split"] = _split
    env.filters["truncate"] = _truncate
    env.filters["trim"] = lambda v: str(v or "").strip()
    env.filters["upper"] = lambda v: str(v or "").upper()
    env.filters["lower"] = lambda v: str(v or "").lower()
    env.filters["replace"] = lambda v, a, b: str(v or "").replace(str(a), str(b))
    return env


def render_template(
    template: str,
    ctx: dict[str, Any],
    *,
    missing_basic: str = "未知",
) -> str:
    tpl = str(template or "")
    if not tpl:
        return ""
    if ("{{" in tpl or "{%" in tpl) and Environment is not None:
        jctx = {
            k: ("" if v in (missing_basic, "未知") else v) for k, v in ctx.items()
        }
        env = _jinja_env(strict=False)
        assert env is not None
        try:
            return env.from_string(tpl).render(**jctx)
        except Exception:
            pass

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        val = ctx.get(key)
        if val is None or str(val).strip() == "":
            return missing_basic
        return str(val)

    return _BASIC_VAR_RE.sub(repl, tpl)


def render_directory_rel(
    naming: dict[str, Any],
    ctx: dict[str, Any],
    *,
    kind: str | None = None,
) -> str:
    kid = str(kind or ctx.get("_kind") or "")
    rule = kind_rule(naming, kid)
    tpl = rule["directoryTemplate"]
    raw = render_template(tpl, ctx)
    parts = [
        _safe_segment(p)
        for p in _MULTI_SLASH_RE.split(raw.replace("\\", "/"))
        if p and p.strip()
    ]
    rel = "/".join(parts) if parts else _safe_segment(str(ctx.get("number") or "unknown"))

    max_len = int(naming.get("directoryMaxLength") or 0)
    if max_len > 0 and len(rel) > max_len:
        title = str(ctx.get("title") or "")
        if title and title != "未知" and "title" in tpl:
            cut = max(4, max_len // 4)
            ctx2 = {**ctx, "title": title[:cut]}
            raw2 = render_template(tpl, ctx2)
            parts2 = [
                _safe_segment(p)
                for p in _MULTI_SLASH_RE.split(raw2.replace("\\", "/"))
                if p and p.strip()
            ]
            rel = "/".join(parts2) if parts2 else rel
        if len(rel) > max_len:
            rel = rel[:max_len].rstrip("/ ")
    return rel


def image_filename(naming: dict[str, Any], kind: str, number: str) -> str:
    del naming, number  # 固定 poster.jpg
    base = kind if kind in {"poster", "fanart", "thumb"} else "poster"
    return f"{base}.jpg"


def resolve_entry_dir(
    library: Path,
    naming: dict[str, Any],
    *,
    code: str,
    meta: dict[str, Any],
    target: dict[str, Any],
    category: str,
    kind: str | None = None,
) -> Path:
    kid = resolve_kind(
        kind=kind or str(meta.get("scrapeKind") or ""),
        region=str(target.get("region") or ""),
        code=code,
    )
    ctx = build_naming_context(
        code=code,
        meta=meta,
        target=target,
        category=category,
        naming=naming,
        kind=kid,
    )
    rel = render_directory_rel(naming, ctx, kind=kid)
    return library.joinpath(*rel.split("/"))
