"""AV maker-code parse / ILIKE / boundary — port of sehua-search makerCodeMatch.ts (regex-only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .search_constants import escape_ilike

WESTERN_STUDIO_PREFIXES = {
    s.upper()
    for s in (
        "BRAZZERS",
        "BLACKED",
        "BLACKEDRAW",
        "TUSHY",
        "TUSHYRAW",
        "VIXEN",
        "DEEPER",
        "REALITYKINGS",
        "RK",
        "RKPRIME",
        "NAUGHTYAMERICA",
        "BANGBROS",
        "BANGBUS",
        "MOFOS",
        "FAKETAXI",
        "FAKEHUB",
        "EVILANGEL",
        "JULESJORDAN",
        "PURETABOO",
        "ADULTTIME",
        "DORCEL",
        "DORCELCLUB",
        "PRIVATE",
        "ONLYFANS",
        "MANYVIDS",
        "DIGITALPLAYGROUND",
        "ELEGANTANGEL",
        "LETHALHARDCORE",
        "ANALVIDS",
        "KINK",
        "PUBLICAGENT",
        "FAMILYSTROKES",
        "TEAMSKEET",
        "BRATTYSIS",
        "NUBILES",
        "NUBILEFILMS",
        "LEGALPORNO",
        "SEXMEX",
        "PORNWORLD",
        "MILFY",
        "WICKED",
        "SEXART",
        "WATCH4BEAUTY",
        "PLAYBOYPLUS",
    )
}

DATE6_PREFIX_LABEL = {
    "CARIB": "CARIB",
    "CARIBBEAN": "CARIB",
    "CARIBBEANCOM": "CARIB",
    "CARIBPR": "CARIBPR",
    "1PON": "1PON",
    "1PONDO": "1PON",
    "PACO": "PACO",
    "PACOPACOMAMA": "PACO",
    "10MU": "10MU",
    "10MUSUME": "10MU",
}

# 索引 / 解析统一 canonical：别名输入 → 规范前缀
PREFIX_CANONICAL: dict[str, str] = {
    **DATE6_PREFIX_LABEL,
    "GACHI": "GACHI",
    "GACHINCO": "GACHI",
    "TOKYOHOT": "TOKYOHOT",
    "TOKYO-HOT": "TOKYOHOT",
}

PREFIX_SHAPE: dict[str, str] = {
    "FC2": "fc2",
    "FC2PPV": "fc2ppv",
    "H0930": "alnum_id",
    "C0930": "alnum_id",
    "H4610": "alnum_id",
    "KIN8": "std",
    "GACHI": "std",
    "GACHINCO": "std",
}
for p in DATE6_PREFIX_LABEL:
    PREFIX_SHAPE[p] = "date6"
for p in WESTERN_STUDIO_PREFIXES:
    PREFIX_SHAPE[p] = "western_date"

UNCENSORED_PREFIX_RE = re.compile(
    r"^(FC2|CARIB|1PON|HEYZO|TOKYO|PACO|KIN8|H0930|C0930|H4610|10MU|GACHI|COSPURI|XXX)",
    re.I,
)


@dataclass
class ParsedMakerCode:
    shape: str
    canonical: str
    parts: list[str]
    prefix: str


def _escape_re(s: str) -> str:
    return re.escape(s)


def normalize_maker_code(keyword: str) -> str:
    s = str(keyword or "").strip()
    s = re.sub(r"[－—–﹣]", "-", s)

    def half(ch: str) -> str:
        o = ord(ch)
        if 0xFF10 <= o <= 0xFF19 or 0xFF21 <= o <= 0xFF3A or 0xFF41 <= o <= 0xFF5A:
            return chr(o - 0xFEE0)
        return ch

    return "".join(half(c) for c in s)


def _prefix_key(prefix: str) -> str:
    return re.sub(r"[_\s]+", "-", (prefix or "").strip().upper())


def _western_key(prefix: str) -> str:
    return re.sub(r"[_\-\s]", "", (prefix or "").strip().upper())


def canonical_prefix(prefix: str) -> str:
    """别名 → 规范前缀（1PONDO→1PON、GACHINCO→GACHI、TOKYO-HOT→TOKYOHOT）。"""
    key = _prefix_key(prefix)
    compact = _western_key(prefix)
    if not key and not compact:
        return ""
    if key in PREFIX_CANONICAL:
        return PREFIX_CANONICAL[key]
    if compact in PREFIX_CANONICAL:
        return PREFIX_CANONICAL[compact]
    return key or compact


def prefixes_equivalent(a: str, b: str) -> bool:
    ca, cb = canonical_prefix(a), canonical_prefix(b)
    return bool(ca) and ca == cb


def prefix_aliases(prefix: str) -> frozenset[str]:
    """与 prefix 同属一组的全部写法（含 canonical）。"""
    can = canonical_prefix(prefix)
    if not can:
        return frozenset()
    out = {can, _prefix_key(prefix), _western_key(prefix)}
    for k, v in PREFIX_CANONICAL.items():
        if v == can:
            out.add(k)
            out.add(_western_key(k))
    return frozenset(x for x in out if x)


_western_config_loaded = False


def _ensure_western_from_config() -> None:
    """把 av-makers.western.json 前缀并入欧美集合（配置为准，硬编码作底）。"""
    global _western_config_loaded
    if _western_config_loaded:
        return
    _western_config_loaded = True
    try:
        from .db import ROOT

        path = ROOT / "apps" / "web" / "src" / "config" / "av-makers.western.json"
        if not path.exists():
            return
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        for m in data if isinstance(data, list) else []:
            if not isinstance(m, dict):
                continue
            for p in m.get("prefixes") or []:
                wk = _western_key(str(p))
                if not wk:
                    continue
                WESTERN_STUDIO_PREFIXES.add(wk)
                PREFIX_SHAPE[wk] = "western_date"
                PREFIX_SHAPE[_prefix_key(str(p))] = "western_date"
    except Exception:
        pass


def is_western_studio_prefix(prefix: str) -> bool:
    _ensure_western_from_config()
    return _western_key(prefix) in WESTERN_STUDIO_PREFIXES


def resolve_maker_shape(prefix: str) -> str:
    _ensure_western_from_config()
    key = _prefix_key(prefix)
    compact = _western_key(prefix)
    if key in PREFIX_SHAPE:
        return PREFIX_SHAPE[key]
    if compact in PREFIX_SHAPE:
        return PREFIX_SHAPE[compact]
    if key == "FC2-PPV" or compact == "FC2PPV":
        return "fc2ppv"
    if is_western_studio_prefix(prefix):
        return "western_date"
    return "std"


def _pad_skip_set() -> set[str]:
    try:
        from .prefix_ranges import SKIP_PREFIXES

        out: set[str] = set()
        for s in SKIP_PREFIXES:
            out.add(_prefix_key(s))
            out.add(_western_key(s))
        return out
    except Exception:
        return set()


def prefix_format_meta(prefix: str) -> dict[str, Any]:
    """按前缀配置解析规范格式（非按区猜测）。

    来源：PREFIX_SHAPE / DATE6 / 欧美 JSON / FC2 / alnum；
    可编辑位数仅 std 且不在 SKIP_PREFIXES，位数读 prefix-code-ranges。
    """
    raw = str(prefix or "").strip()
    key = _prefix_key(raw)
    compact = _western_key(raw)
    shape = resolve_maker_shape(raw)

    if shape == "western_date":
        wk = compact or key
        return {
            "prefix": key or wk,
            "shape": shape,
            "codeFormat": "western_date",
            "codeSample": f"{wk}.2026.01.15",
            "pad": 0,
            "padLocked": False,
            "padEditable": False,
        }
    if shape == "fc2ppv":
        return {
            "prefix": "FC2PPV",
            "shape": shape,
            "codeFormat": "fc2ppv",
            "codeSample": "FC2-PPV-1234567",
            "pad": 0,
            "padLocked": False,
            "padEditable": False,
        }
    if shape == "fc2":
        return {
            "prefix": "FC2",
            "shape": shape,
            "codeFormat": "fc2",
            "codeSample": "FC2-1234567",
            "pad": 0,
            "padLocked": False,
            "padEditable": False,
        }
    if shape == "date6":
        label = (
            DATE6_PREFIX_LABEL.get(key)
            or DATE6_PREFIX_LABEL.get(compact)
            or key
        )
        return {
            "prefix": label,
            "shape": shape,
            "codeFormat": "date6",
            "codeSample": f"{label}-260115-001",
            "pad": 0,
            "padLocked": False,
            "padEditable": False,
        }
    if shape == "alnum_id":
        # H0930 / C0930 / H4610：字母数字流水，非零补流水号
        sample_id = {
            "H0930": "H0930-ORI123",
            "C0930": "C0930-ABC123",
            "H4610": "H4610-ABC123",
        }.get(key, f"{key}-ABC123")
        return {
            "prefix": key,
            "shape": shape,
            "codeFormat": "alnum_id",
            "codeSample": sample_id,
            "pad": 0,
            "padLocked": False,
            "padEditable": False,
        }

    # std：仅非 SKIP 前缀可读/改 ranges.pad
    skip = _pad_skip_set()
    if key in skip or compact in skip:
        # 无码等特殊厂：号码形态仍是横杠流水，但不用日有码 pad 编辑
        fixed = {
            "HEYZO": "HEYZO-1234",
            "TOKYOHOT": "TOKYOHOT-N1234",
            "TOKYO-HOT": "TOKYOHOT-N1234",
            "XXX-AV": "XXX-AV-12345",
            "HEYDOUGA": "HEYDOUGA-1234",
            "MESUBUTA": "MESUBUTA-123456-001",
            "SPERMMANIA": "SPERMMANIA-123",
            "RHJ": "RHJ-123",
            "COSPURI": "COSPURI-123",
            "JVID": "JVID-123",
            "KIN8": "KIN8-1234",
            "GACHI": "GACHI-123",
            "GACHINCO": "GACHI-123",
        }
        sample = fixed.get(key) or fixed.get(compact) or f"{key}-1234"
        return {
            "prefix": key,
            "shape": "std",
            "codeFormat": "fixed_std",
            "codeSample": sample,
            "pad": 0,
            "padLocked": False,
            "padEditable": False,
        }

    pad = 3
    pad_locked = False
    sample = f"{key}-001"
    try:
        from .prefix_ranges import get_range

        rng = get_range(key)
        if rng:
            pad = max(1, min(8, int(rng.get("pad") or 3)))
            pad_locked = bool(rng.get("padLocked"))
            sample = str(rng.get("sample") or f"{key}-{1:0{pad}d}")
    except Exception:
        pass
    return {
        "prefix": key,
        "shape": "std",
        "codeFormat": "digit_pad",
        "codeSample": sample,
        "pad": pad,
        "padLocked": pad_locked,
        "padEditable": True,
    }


def maker_code_parts(code: str) -> list[str]:
    raw = normalize_maker_code(code).upper()
    spaced = [p for p in re.split(r"[-_\s.]+", raw) if p]
    if len(spaced) >= 2:
        return spaced
    piece = spaced[0] if spaced else raw
    if not piece:
        return []
    if re.fullmatch(r"\d+", piece):
        return [piece]
    glued = re.fullmatch(r"([A-Z]{2,20})(\d{2,10})", piece)
    if glued:
        return [glued.group(1), glued.group(2)]
    return [piece]


def _parse_fc2(raw: str) -> ParsedMakerCode | None:
    u = normalize_maker_code(raw).upper()
    m = re.fullmatch(r"FC2[-_\s.]?PPV[-_\s.]?(\d{5,10})", u, re.I)
    if m:
        return ParsedMakerCode(
            "fc2ppv", f"FC2-PPV-{m.group(1)}", ["FC2", "PPV", m.group(1)], "FC2PPV"
        )
    m = re.fullmatch(r"FC2(?![-_\s.]?PPV)[-_\s.]?(\d{5,10})", u, re.I)
    if m:
        return ParsedMakerCode(
            "fc2", f"FC2-{m.group(1)}", ["FC2", m.group(1)], "FC2"
        )
    return None


def _parse_date6(raw: str) -> ParsedMakerCode | None:
    u = normalize_maker_code(raw).upper()
    m = re.fullmatch(
        r"([A-Z0-9]{2,20})[-_\s.]?(\d{6})[-_\s.](\d{2,3})(?:[-_\s.]?[A-Z]{0,2})?",
        u,
        re.I,
    )
    if not m:
        return None
    label = (
        DATE6_PREFIX_LABEL.get(_prefix_key(m.group(1)))
        or DATE6_PREFIX_LABEL.get(_western_key(m.group(1)))
        or _prefix_key(m.group(1))
    )
    if PREFIX_SHAPE.get(_prefix_key(m.group(1))) == "date6" or label in DATE6_PREFIX_LABEL.values():
        return ParsedMakerCode(
            "date6",
            f"{label}-{m.group(2)}-{m.group(3)}",
            [label, m.group(2), m.group(3)],
            label,
        )
    return None


def _parse_alnum(raw: str) -> ParsedMakerCode | None:
    u = normalize_maker_code(raw).upper()
    m = re.fullmatch(r"([HC]0930|H4610)[-_\s.]?([A-Z0-9]{3,24})", u, re.I)
    if not m:
        return None
    prefix = m.group(1).upper()
    ident = m.group(2).upper()
    return ParsedMakerCode("alnum_id", f"{prefix}-{ident}", [prefix, ident], prefix)


def _parse_tokyohot(raw: str) -> ParsedMakerCode | None:
    """TOKYOHOT-n1234 / TOKYO-HOT-1234 → TOKYOHOT-N1234。"""
    u = normalize_maker_code(raw).upper()
    m = re.fullmatch(r"TOKYO[-_\s]?HOT[-_\s.]?N?(\d{3,5})", u, re.I)
    if not m:
        return None
    body = f"N{m.group(1)}"
    return ParsedMakerCode(
        "fixed_std", f"TOKYOHOT-{body}", ["TOKYOHOT", body], "TOKYOHOT"
    )


def _parse_mesubuta(raw: str) -> ParsedMakerCode | None:
    """MESUBUTA-123456-001（勿被 std 剥成两段）。"""
    u = normalize_maker_code(raw).upper()
    m = re.fullmatch(r"MESUBUTA[-_\s.]?(\d{6})[-_\s.](\d{2,3})", u, re.I)
    if not m:
        return None
    can = f"MESUBUTA-{m.group(1)}-{m.group(2)}"
    return ParsedMakerCode(
        "fixed_std", can, ["MESUBUTA", m.group(1), m.group(2)], "MESUBUTA"
    )


def _parse_gachi(raw: str) -> ParsedMakerCode | None:
    """GACHI-123 / GACHINCO-123 → GACHI-123。"""
    u = normalize_maker_code(raw).upper()
    m = re.fullmatch(r"GACHI(?:NCO)?[-_\s.]?(\d{3,5})", u, re.I)
    if not m:
        return None
    can = f"GACHI-{m.group(1)}"
    return ParsedMakerCode("std", can, ["GACHI", m.group(1)], "GACHI")


def _western_yyyy(yy_or_yyyy: str) -> str:
    """两位年 → 四位年（26 → 2026）；已是 19xx/20xx 则原样。"""
    s = str(yy_or_yyyy or "").strip()
    if re.fullmatch(r"19\d{2}|20\d{2}", s):
        return s
    if re.fullmatch(r"\d{2}", s):
        return f"20{s}"
    return s


def _western_date_key(prefix: str, y: str, mo: str, d: str) -> str:
    return f"{_western_key(prefix)}.{_western_yyyy(y)}.{mo}.{d}"


def _parse_western(raw: str) -> ParsedMakerCode | None:
    u = normalize_maker_code(raw).upper()
    # KEY.YYYY.MM.DD（四位年完整日）
    m = re.fullmatch(
        r"([A-Z]{2,24})[._\-\s]?(19\d{2}|20\d{2})[._\-](\d{2})[._\-](\d{2})",
        u,
        re.I,
    )
    if m and is_western_studio_prefix(m.group(1)):
        key = _western_key(m.group(1))
        yyyy, mo, d = m.group(2), m.group(3), m.group(4)
        can = f"{key}.{yyyy}.{mo}.{d}"
        return ParsedMakerCode("western_date", can, [key, yyyy, mo, d], key)
    # KEY.YY.MM.DD / KEY-YY-MM-DD（两位年 → 四位）
    m = re.fullmatch(
        r"([A-Z]{2,24})[._\-\s]?(\d{2})[._\-](\d{2})[._\-](\d{2})", u, re.I
    )
    if m and is_western_studio_prefix(m.group(1)):
        key = _western_key(m.group(1))
        y, mo, d = m.group(2), m.group(3), m.group(4)
        # 避免把 2023.06.24 误拆成 20.23.06
        if y in ("19", "20"):
            return None
        yyyy = _western_yyyy(y)
        can = f"{key}.{yyyy}.{mo}.{d}"
        return ParsedMakerCode(
            "western_date", can, [key, yyyy, mo, d], key
        )
    # KEY-260513 / KEY.260513 紧凑六位 → KEY.2026.05.13
    m = re.fullmatch(r"([A-Z]{2,24})[-_\s.](\d{6})", u, re.I)
    if m and is_western_studio_prefix(m.group(1)):
        key = _western_key(m.group(1))
        ymd = m.group(2)
        y, mo, d = ymd[:2], ymd[2:4], ymd[4:6]
        yyyy = _western_yyyy(y)
        can = f"{key}.{yyyy}.{mo}.{d}"
        return ParsedMakerCode(
            "western_date", can, [key, yyyy, mo, d], key
        )
    # KEY.YYYY.MM 合集月号
    m = re.fullmatch(
        r"([A-Z]{2,24})[._\-\s]?(19\d{2}|20\d{2})[._\-](\d{2})", u, re.I
    )
    if m and is_western_studio_prefix(m.group(1)):
        key = _western_key(m.group(1))
        return ParsedMakerCode(
            "western_ym",
            f"{key}.{m.group(2)}.{m.group(3)}",
            [key, m.group(2), m.group(3)],
            key,
        )
    # KEY.YYYY / KEY-YYYY 年份
    m = re.fullmatch(
        r"([A-Z]{2,24})[._\-\s]?(19\d{2}|20\d{2})", u, re.I
    )
    if m and is_western_studio_prefix(m.group(1)):
        key = _western_key(m.group(1))
        return ParsedMakerCode(
            "western_year",
            f"{key}.{m.group(2)}",
            [key, m.group(2)],
            key,
        )
    # 不再把裸数字当成欧美集数键（易误吃 2160/4K 等）
    return None


def _china_prefix_set() -> set[str]:
    try:
        from .prefix_ranges import load_china_prefixes

        return load_china_prefixes()
    except Exception:
        return set()


def _parse_std(raw: str) -> ParsedMakerCode | None:
    u = normalize_maker_code(raw).upper()
    # 先剥国产分集尾巴，番号键只要基号：MDSR-0002-EP3 / MDSR-0002-4 → MDSR-0002
    u = re.sub(r"[-_\s.](?:EP|E)?[-_\s.]?\d{1,2}$", "", u, flags=re.I)
    m = re.fullmatch(
        r"(?:(\d{2,3}))?([A-Z]{2,20})[-_\s.]?(\d{2,10})(?:[-_\s.]?([A-Z0-9]{1,6}))?",
        u,
        re.I,
    )
    if not m:
        return None
    leading = (m.group(1) or "").strip()
    letters = m.group(2).upper()
    num = m.group(3)
    # 默认丢掉前缀数字板号（259LUXU → LUXU）；国产 91CM 等保留
    prefix = letters
    if leading:
        combined = f"{leading}{letters}"
        try:
            if combined in _china_prefix_set():
                prefix = combined
        except Exception:
            pass
    shape = resolve_maker_shape(prefix)
    if shape in {"fc2", "fc2ppv", "date6", "alnum_id"}:
        return None
    return ParsedMakerCode("std", f"{prefix}-{num}", [prefix, num], prefix)


def std_code_key(code: str, *, pad: int = 3) -> str:
    """统一番号键：短号按 pad 补零；已带前导零的保留源串位数。

    例：SONE-15 + pad3 → SONE-015；JD-150 + pad3 → JD-150；MDSR-0002 保持四位。
    分集 / -C / -CH / 分盘字母等尾缀不进键（IPZZ-599C → IPZZ-599）。
    欧美为点分 YYYY.MM.DD。
    """
    raw = str(code or "").strip().upper().replace("_", "-")
    raw = re.sub(r"(?<=\d)-(?:EP|E)?\d{1,2}$", "", raw, flags=re.I)
    try:
        parsed = parse_maker_code(raw)
        if parsed and parsed.shape in {
            "western_date",
            "western_ym",
            "western_year",
            "western_ep",
            "fc2",
            "fc2ppv",
            "alnum_id",
            "date6",
            "fixed_std",
        }:
            return parsed.canonical
        # std：用解析后的 PREFIX-数字（丢掉破解/分盘字母尾缀）
        if parsed and parsed.shape == "std" and parsed.canonical:
            raw = parsed.canonical
    except Exception:
        pass
    m = re.fullmatch(r"([A-Z0-9]+)-(\d+)", raw)
    if not m:
        return raw
    prefix, num_s = m.group(1), m.group(2)
    n = int(num_s)
    # pad<=0：完全保留源串位数（国产按帖题原样）
    if int(pad or 0) <= 0:
        width = max(len(str(n)), len(num_s))
    elif len(num_s) > len(str(n)):
        # 源串已有前导零（MDSR-0002）→ 保留
        width = max(len(num_s), len(str(n)))
    else:
        # 短号按 pad 补（SONE-15 → SONE-015）
        width = max(1, int(pad or 3), len(str(n)))
    return f"{prefix}-{n:0{width}d}"


def parse_maker_code(keyword: str) -> ParsedMakerCode | None:
    raw = normalize_maker_code(keyword)
    if not raw or len(raw) > 48:
        return None
    return (
        _parse_fc2(raw)
        or _parse_alnum(raw)
        or _parse_date6(raw)
        or _parse_tokyohot(raw)
        or _parse_mesubuta(raw)
        or _parse_gachi(raw)
        or _parse_western(raw)
        or _parse_std(raw)
    )


def is_av_code_keyword(keyword: str) -> bool:
    return parse_maker_code(keyword) is not None


def is_uncensored_maker_code(keyword: str) -> bool:
    parsed = parse_maker_code(keyword)
    if parsed and parsed.shape in {"fc2", "fc2ppv", "date6", "alnum_id"}:
        return True
    return bool(UNCENSORED_PREFIX_RE.match(normalize_maker_code(keyword)))


def _parts_for_patterns(canonical: str, shape: str) -> list[str]:
    if shape == "fc2ppv":
        m = re.fullmatch(r"FC2-PPV-(\d+)", canonical, re.I)
        if m:
            return ["FC2", "PPV", m.group(1)]
    if shape == "fc2":
        m = re.fullmatch(r"FC2-(\d+)", canonical, re.I)
        if m:
            return ["FC2", m.group(1)]
    if shape == "date6":
        m = re.fullmatch(r"([A-Z0-9]+)-(\d{6})-(\d{2,3})", canonical, re.I)
        if m:
            return [m.group(1), m.group(2), m.group(3)]
    if shape == "fixed_std":
        # TOKYOHOT-N1234 / MESUBUTA-123456-001
        m = re.fullmatch(r"TOKYOHOT[-_.\s]?N?(\d{3,5})", canonical, re.I)
        if m:
            return ["TOKYOHOT", f"N{m.group(1)}"]
        m = re.fullmatch(r"MESUBUTA[-_.\s]?(\d{6})[-_.\s](\d{2,3})", canonical, re.I)
        if m:
            return ["MESUBUTA", m.group(1), m.group(2)]
    if shape == "western_date":
        m = re.fullmatch(
            r"([A-Z]{2,24})[._\-](19\d{2}|20\d{2})[._\-](\d{2})[._\-](\d{2})",
            canonical,
            re.I,
        )
        if m:
            return [
                m.group(1).upper(),
                m.group(2),
                m.group(3),
                m.group(4),
            ]
        m = re.fullmatch(
            r"([A-Z]{2,24})[._\-](\d{2})[._\-](\d{2})[._\-](\d{2})",
            canonical,
            re.I,
        )
        if m:
            return [
                m.group(1).upper(),
                f"{m.group(2)}{m.group(3)}{m.group(4)}",
            ]
        m = re.fullmatch(r"([A-Z]{2,24})[-_.](\d{6})", canonical, re.I)
        if m:
            return [m.group(1).upper(), m.group(2)]
    if shape == "western_ym":
        m = re.fullmatch(
            r"([A-Z]{2,24})[._\-](19\d{2}|20\d{2})[._\-](\d{2})",
            canonical,
            re.I,
        )
        if m:
            return [m.group(1).upper(), m.group(2), m.group(3)]
    if shape == "western_year":
        m = re.fullmatch(
            r"([A-Z]{2,24})[._\-](19\d{2}|20\d{2})",
            canonical,
            re.I,
        )
        if m:
            return [m.group(1).upper(), m.group(2)]
    return maker_code_parts(canonical)


def _search_prefix_heads(keyword: str, head: str) -> list[str]:
    """精确搜索用的前缀写法：canonical 别名 + 素人数字头。"""
    heads: set[str] = set()
    if head:
        heads.add(_prefix_key(head))
        heads |= set(prefix_aliases(head))
    raw = normalize_maker_code(keyword).upper().replace("_", "-")
    m = re.match(r"^(\d{2,3}[A-Z]{2,20})", raw)
    if m:
        hub = m.group(1)
        heads.add(hub)
        letter = re.sub(r"^\d+", "", hub)
        if letter:
            heads.add(letter)
            heads |= set(prefix_aliases(letter))
    # 去空、去纯重复 compact
    out = [h for h in heads if h]
    out.sort(key=lambda s: (-len(s), s))
    return out


def _part_lists_for_search(keyword: str, parts: list[str], shape: str) -> list[list[str]]:
    """同一番号的多套 parts（前缀别名 / TOKYOHOT 有无 N）。"""
    if not parts:
        return []
    head, *tail = parts
    heads = _search_prefix_heads(keyword, head)
    if not heads:
        heads = [head]

    bodies: list[list[str]] = [tail]
    # TOKYOHOT-N1234 ↔ TOKYOHOT-1234
    if shape == "fixed_std" and prefixes_equivalent(head, "TOKYOHOT") and tail:
        dig = re.sub(r"^[Nn]", "", str(tail[0]))
        if dig.isdigit():
            bodies = [[f"N{dig}"], [dig]]

    out: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for h in heads:
        for body in bodies:
            row = [h, *body]
            key = tuple(row)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
    return out or [parts]


def _ilike_patterns_for_parts(parts: list[str], shape: str) -> list[str]:
    esc = [escape_ilike(p) for p in parts]
    if not esc:
        return []
    if len(esc) == 1:
        return [f"%{esc[0]}%"]
    out = [
        f"%{'-'.join(esc)}%",
        f"%{''.join(esc)}%",
        f"%{'_'.join(esc)}%",
        f"%{' '.join(esc)}%",
    ]
    if len(esc) >= 3:
        head = "".join(esc[:-1])
        num = esc[-1]
        out.extend([f"%{head}_{num}%", f"%{head}-{num}%"])
    if shape == "std" and len(parts) == 2 and str(parts[1]).isdigit():
        pref, num = parts[0], parts[1]
        bare = str(int(num))
        variants = {num, bare}
        for w in (2, 3, 4, 5, 6):
            if len(bare) <= w <= 6:
                variants.add(bare.zfill(w))
        ep = escape_ilike(pref)
        for v in variants:
            ev = escape_ilike(v)
            out.extend(
                [
                    f"%{ep}-{ev}%",
                    f"%{ep}{ev}%",
                    f"%{ep}_{ev}%",
                    f"%{ep} {ev}%",
                ]
            )
    if shape == "western_date" and len(parts) == 2 and len(parts[1]) == 6:
        y, mo, d = esc[1][:2], esc[1][2:4], esc[1][4:6]
        studio = esc[0]
        out.extend(
            [
                f"%{studio}.{y}.{mo}.{d}%",
                f"%{studio}_{y}.{mo}.{d}%",
                f"%{studio}-{y}-{mo}-{d}%",
            ]
        )
    if shape == "western_date" and len(parts) == 4:
        studio, yyyy, mo, d = esc[0], esc[1], esc[2], esc[3]
        out.extend(
            [
                f"%{studio}.{yyyy}.{mo}.{d}%",
                f"%{studio}_{yyyy}.{mo}.{d}%",
                f"%{studio}-{yyyy}-{mo}-{d}%",
            ]
        )
    if shape in {"western_ym", "western_year", "western_ep"} and len(esc) >= 2:
        out.append(f"%{'.'.join(esc)}%")
        out.append(f"%{esc[0]}_{'.'.join(esc[1:])}%")
    if shape == "date6" and len(parts) == 3:
        out.extend([f"%{esc[1]}-{esc[2]}%", f"%{esc[1]}_{esc[2]}%"])
    if shape == "fixed_std" and len(parts) == 2 and prefixes_equivalent(parts[0], "TOKYOHOT"):
        # Tokyo Hot / TOKYO-HOT 空格写法
        dig = re.sub(r"^[Nn]", "", parts[1])
        out.extend(
            [
                f"%TOKYO HOT%{escape_ilike(dig)}%",
                f"%TOKYO-HOT-{escape_ilike(dig)}%",
                f"%TOKYO-HOT-N{escape_ilike(dig)}%",
            ]
        )
    return out


def build_av_code_ilike_patterns(canonical: str) -> list[str]:
    """ILIKE patterns with ESCAPE '\\': literals escaped; bare `_` = any single sep.

    规范键会展开前缀别名（1PON↔1PONDO、GACHI↔GACHINCO）及 TOKYOHOT 有无 N。
    """
    parsed = parse_maker_code(canonical)
    shape = parsed.shape if parsed else "std"
    # 优先用解析后的 canonical parts（date6/fixed_std 更稳）
    base_src = parsed.canonical if parsed and parsed.canonical else canonical
    parts = _parts_for_patterns(base_src, shape)
    if not parts:
        u = normalize_maker_code(canonical).upper()
        return [f"%{escape_ilike(u)}%"] if u else []

    out: list[str] = []
    for plist in _part_lists_for_search(canonical, parts, shape):
        out.extend(_ilike_patterns_for_parts(plist, shape))

    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _boundary_tail(parts: list[str]) -> str:
    last = parts[-1] if parts else ""
    return r"(?![A-Za-z0-9])" if re.search(r"[A-Z]", last, re.I) else r"(?![0-9])"


def build_av_code_boundary_re(canonical: str) -> re.Pattern[str]:
    parsed = parse_maker_code(canonical)
    shape = parsed.shape if parsed else "std"
    base_src = parsed.canonical if parsed and parsed.canonical else canonical
    parts = _parts_for_patterns(base_src, shape)
    if not parts:
        return re.compile(r"(?!)")

    alts: list[str] = []
    for plist in _part_lists_for_search(canonical, parts, shape):
        compact = "[-_.\\s]?".join(_escape_re(p) for p in plist)
        alts.append(compact)
        # 标准番号：前导零可选
        if shape == "std" and len(plist) == 2 and re.fullmatch(r"\d+", plist[1]):
            pref = _escape_re(plist[0])
            bare = str(int(plist[1]))
            alts.append(rf"{pref}[-_.\s]?0*{_escape_re(bare)}")
        # 欧美日戳
        if shape == "western_date" and len(plist) == 2 and re.fullmatch(r"\d{6}", plist[1]):
            y, mo, d = plist[1][:2], plist[1][2:4], plist[1][4:6]
            studio = _escape_re(plist[0])
            alts.append(
                rf"{studio}[._\-\s]?{_escape_re(y)}[._\-]{_escape_re(mo)}[._\-]{_escape_re(d)}"
            )
        if shape == "western_date" and len(plist) == 4:
            studio, yyyy, mo, d = (_escape_re(x) for x in plist)
            if re.fullmatch(r"20\d{2}", plist[1]):
                yy = _escape_re(plist[1][2:])
                alts.append(rf"{studio}[._\-\s]?{yy}[._\-]{mo}[._\-]{d}")

    # TOKYOHOT：TOKYO HOT / 可选 N
    if shape == "fixed_std" and prefixes_equivalent(parts[0], "TOKYOHOT"):
        dig = re.sub(r"^[Nn]", "", parts[1] if len(parts) > 1 else "")
        if dig.isdigit():
            alts.append(
                rf"(?:TOKYO[-_\s]?HOT|TOKYOHOT)[-_.\s]?N?{_escape_re(dig)}"
            )

    # dedupe alts
    seen_a: set[str] = set()
    uniq_alts: list[str] = []
    for a in alts:
        if a not in seen_a:
            seen_a.add(a)
            uniq_alts.append(a)
    if not uniq_alts:
        return re.compile(r"(?!)")

    body = "(?:" + "|".join(uniq_alts) + ")"
    cid = r"(?:\d{2,3})?" if shape == "std" else ""
    tail = _boundary_tail(parts)
    if shape == "western_date" and len(uniq_alts) > 1:
        tail = r"(?![0-9])"
    if shape == "fixed_std" and prefixes_equivalent(parts[0], "TOKYOHOT"):
        tail = r"(?![0-9])"
    return re.compile(
        rf"(^|[^A-Za-z0-9]){cid}{body}{tail}",
        re.I,
    )


def build_av_code_continuation_reject(canonical: str) -> str | None:
    """SQL !~* 拒绝续写：字母尾 C0930-HITOZUMA0759；数字尾 SSIS-0012。"""
    parsed = parse_maker_code(canonical)
    shape = parsed.shape if parsed else "std"
    base_src = parsed.canonical if parsed and parsed.canonical else canonical
    parts = _parts_for_patterns(base_src, shape)
    if not parts:
        return None
    last = parts[-1]
    # 多前缀别名：(1PON|1PONDO)[-_.[:space:]]?…
    heads = _search_prefix_heads(canonical, parts[0])
    if len(heads) > 1:
        pref = "(?:" + "|".join(_escape_re(h) for h in heads) + ")"
    else:
        pref = _escape_re(parts[0])
    rest = parts[1:]
    if rest:
        body = pref + "[-_.[:space:]]?" + "[-_.[:space:]]?".join(
            _escape_re(p) for p in rest
        )
    else:
        body = pref
    if shape == "fixed_std" and prefixes_equivalent(parts[0], "TOKYOHOT"):
        dig = re.sub(r"^[Nn]", "", last)
        if dig.isdigit():
            body = (
                r"(?:TOKYO[-_[:space:]]?HOT|TOKYOHOT)[-_.[:space:]]?N?"
                + _escape_re(dig)
            )
            return f"{body}\\d"
    if re.search(r"[A-Z]", last, re.I):
        return f"{body}[A-Za-z0-9]"
    if re.fullmatch(r"\d+", last) or (
        shape == "fixed_std" and re.fullmatch(r"N?\d+", last, re.I)
    ):
        return f"{body}\\d"
    return None


def apply_av_code_boundary_filter(
    rows: list[dict[str, Any]], code_keywords: list[str]
) -> list[dict[str, Any]]:
    if not code_keywords:
        return rows
    regs = [build_av_code_boundary_re(k) for k in code_keywords]
    out: list[dict[str, Any]] = []
    for row in rows:
        blob = f"{row.get('filename') or row.get('name') or ''}\n{row.get('title') or ''}"
        if all(r.search(blob) for r in regs):
            out.append(row)
    return out


def _extract_fc2(upper: str, want_ppv: bool, out: set[str]) -> None:
    if want_ppv:
        for m in re.finditer(r"FC2[-_\s]?PPV[-_\s]?(\d{5,10})", upper, re.I):
            out.add(f"FC2-PPV-{m.group(1)}")
        return
    if re.search(r"FC2[-_\s]?PPV", upper, re.I):
        return
    for m in re.finditer(
        r"(?:^|[^A-Z0-9])FC2(?![-_\s]?PPV)[-_\s]?(\d{5,10})(?![A-Z0-9])",
        upper,
        re.I,
    ):
        out.add(f"FC2-{m.group(1)}")


def _extract_date6(upper: str, prefix: str, out: set[str]) -> None:
    label = (
        DATE6_PREFIX_LABEL.get(_prefix_key(prefix))
        or DATE6_PREFIX_LABEL.get(_western_key(prefix))
        or _prefix_key(prefix)
    )
    if (
        _prefix_key(prefix) in upper
        or _western_key(prefix) in upper
        or label in upper
    ):
        for m in re.finditer(
            r"(?:^|[^A-Z0-9])(\d{6})[-_](\d{2,3})(?![A-Z0-9])", upper, re.I
        ):
            out.add(f"{label}-{m.group(1)}-{m.group(2)}")
    esc = _escape_re(_prefix_key(prefix))
    for m in re.finditer(
        rf"{esc}[-_\s]?(\d{{6}})[-_](\d{{2,3}})(?![A-Z0-9])", upper, re.I
    ):
        out.add(f"{label}-{m.group(1)}-{m.group(2)}")


def _extract_alnum_id(upper: str, prefix: str, out: set[str]) -> None:
    p = _prefix_key(prefix)
    esc = _escape_re(p)
    for m in re.finditer(
        rf"{esc}[-_\s]?([A-Z]{{0,12}}\d[A-Z0-9]{{0,20}})(?![A-Z0-9])",
        upper,
        re.I,
    ):
        ident = m.group(1).upper()
        if not re.search(r"\d", ident) or len(ident) < 3:
            continue
        out.add(f"{p}-{ident}")


def _extract_western(upper: str, prefix: str, out: set[str]) -> None:
    """欧美抽码：规范键 PREFIX.YYYY.MM.DD / PREFIX.YYYY.MM / PREFIX.YYYY。"""
    key = _western_key(prefix)
    esc = _escape_re(key)
    # 1) KEY.YYYY.MM.DD
    for m in re.finditer(
        rf"{esc}[._\-\s]?(19\d{{2}}|20\d{{2}})[._\-](\d{{2}})[._\-](\d{{2}})(?!\d)",
        upper,
        re.I,
    ):
        out.add(f"{key}.{m.group(1)}.{m.group(2)}.{m.group(3)}")
    # 2) KEY.YY.MM.DD → KEY.20YY.MM.DD
    for m in re.finditer(
        rf"{esc}[._\-\s]?(\d{{2}})[._\-](\d{{2}})[._\-](\d{{2}})(?!\d)",
        upper,
        re.I,
    ):
        if m.group(1) in ("19", "20"):
            continue
        yyyy = _western_yyyy(m.group(1))
        out.add(f"{key}.{yyyy}.{m.group(2)}.{m.group(3)}")
    # 3) KEY.YYYY.MM 合集月（后面不能再跟 .日）
    for m in re.finditer(
        rf"{esc}[._\-\s]?(19\d{{2}}|20\d{{2}})[._\-](\d{{2}})(?![._\-]?\d)",
        upper,
        re.I,
    ):
        out.add(f"{key}.{m.group(1)}.{m.group(2)}")
    # 4) KEY.YYYY 纯年（后面不能再跟 .月）
    for m in re.finditer(
        rf"{esc}[._\-\s]?(19\d{{2}}|20\d{{2}})(?![._\-]?\d)",
        upper,
        re.I,
    ):
        out.add(f"{key}.{m.group(1)}")
    # 5) 六位紧凑日戳 KEY.260513 → KEY.2026.05.13（不要裸 2160 等伪集数）
    for m in re.finditer(
        rf"{esc}[._\-\s]?(\d{{6}})(?![A-Z0-9])", upper, re.I
    ):
        num = m.group(1)
        if re.fullmatch(r"19\d{2}|20\d{2}", num[:4]) and int(num[4:6]) <= 12:
            # 误把 YYYYMM 当 YYMMDD 的少见情况：若前四位是年且后两位像月，跳过交给上面
            pass
        yyyy = _western_yyyy(num[:2])
        mo, d = num[2:4], num[4:6]
        if 1 <= int(mo) <= 12 and 1 <= int(d) <= 31:
            out.add(f"{key}.{yyyy}.{mo}.{d}")


def _extract_std(upper: str, prefix: str, out: set[str]) -> None:
    p = _prefix_key(prefix)
    if p in {"GACHI", "GACHINCO"}:
        for m in re.finditer(r"GACHI(?:NCO)?[-_\s]?GACHI?(\d{3,5})", upper, re.I):
            out.add(f"GACHI-{m.group(1)}")
        if out:
            return
    esc = _escape_re(p)
    china = p in _china_prefix_set()
    if china:
        # 按帖题原样保留位数：JD-150 / MDSR-0002 / YCM086，不强制四位
        for m in re.finditer(
            rf"(?:^|[^A-Z0-9])(?:\d{{2,3}})?{esc}[-_\s]?(\d{{1,6}})"
            rf"(?:[-_\s]?(?:EP|E)[-_\s]?\d{{1,2}}|[-_]\d{{1,2}})?(?![A-Z0-9])",
            upper,
            re.I,
        ):
            raw_num = m.group(1)
            if not re.fullmatch(r"\d{1,6}", raw_num):
                continue
            n = int(raw_num)
            if n <= 0:
                continue
            out.add(f"{p}-{raw_num}")
        return
    # 数字与可选分集后缀分开：避免 EBWH-061100cm 把 CM 吃进番号
    for m in re.finditer(
        rf"(?:^|[^A-Z0-9])(?:\d{{2,3}})?{esc}[-_\s]?(\d{{2,6}})([A-Z]{{1,2}})?(?![A-Z0-9])",
        upper,
        re.I,
    ):
        raw_num = m.group(1)
        suf = str(m.group(2) or "").upper()
        unit = bool(suf and _CODE_UNIT_SUFFIX_RE.fullmatch(suf))
        # 单位后缀（cm）并入 following，便于 061100+CM → 截成 061
        following = ((suf if unit else "") + upper[m.end() : m.end() + 12])
        clamped = _clamp_std_code_digits(p, raw_num, following=following)
        if not clamped:
            continue
        # 合法分集后缀（如 ABC-123AB）保留；单位后缀丢掉
        if suf and not unit and len(clamped) == len(raw_num):
            out.add(f"{p}-{clamped}{suf}")
        else:
            out.add(f"{p}-{clamped}")


_CODE_UNIT_SUFFIX_RE = re.compile(r"^(CM|MM|KG|MIN|FPS|MS)$", re.I)
_MEASURE_AFTER_CODE_RE = re.compile(
    r"^(?:\d{0,4})?(?:CM|MM|KG|MIN|FPS|秒|分|歳|才|P\b|K\b)",
    re.I,
)


def _pad_for_extract(prefix: str) -> int:
    try:
        from .prefix_ranges import get_range

        r = get_range(prefix)
        if r and int(r.get("pad") or 0) > 0:
            return max(1, min(8, int(r["pad"])))
    except Exception:
        pass
    return 3


def _clamp_std_code_digits(
    prefix: str, raw_num: str, *, following: str = ""
) -> str | None:
    """按前缀规范位数截断：EBWH-061100cm → 061（pad=3）。"""
    if not re.fullmatch(r"\d{2,6}", raw_num):
        return None
    n = int(raw_num)
    if n <= 0:
        return None
    pad = _pad_for_extract(prefix)
    if len(raw_num) <= pad:
        return raw_num
    head, tail = raw_num[:pad], raw_num[pad:]
    follow = f"{tail}{following or ''}"
    if _MEASURE_AFTER_CODE_RE.match(follow):
        return head
    # 超长流水（pad+2 及以上）多半是把 100cm 等粘进来了
    if len(raw_num) >= pad + 2:
        try:
            from .prefix_ranges import get_range

            r = get_range(prefix)
            to = int((r or {}).get("to") or 0)
            if to <= 0 or int(head) <= to:
                return head
        except Exception:
            return head
    return raw_num


def extract_maker_codes(text: str, prefix: str) -> list[str]:
    """Extract canonical codes for a maker prefix from filename/title blob."""
    src = str(text or "")
    p = str(prefix or "").strip()
    if not src or not p:
        return []
    upper = src.upper()
    shape = resolve_maker_shape(p)
    out: set[str] = set()
    if shape == "fc2":
        _extract_fc2(upper, False, out)
    elif shape == "fc2ppv":
        _extract_fc2(upper, True, out)
    elif shape == "date6":
        _extract_date6(upper, p, out)
    elif shape == "alnum_id":
        _extract_alnum_id(upper, p, out)
    elif shape in {"western_date", "western_ep"}:
        _extract_western(upper, p, out)
    else:
        _extract_std(upper, p, out)
    return list(out)


def code_sort_key(code: str) -> tuple[int, int, str]:
    parts = re.findall(r"\d+", str(code or "").upper())
    a = int(parts[0]) if parts else 0
    b = int(parts[1]) if len(parts) > 1 else 0
    return a, b, str(code or "").upper()


def compare_codes(a: str, b: str) -> int:
    ka, kb = code_sort_key(a), code_sort_key(b)
    if ka[0] != kb[0]:
        return -1 if ka[0] < kb[0] else 1
    if ka[1] != kb[1]:
        return -1 if ka[1] < kb[1] else 1
    if ka[2] < kb[2]:
        return -1
    if ka[2] > kb[2]:
        return 1
    return 0
