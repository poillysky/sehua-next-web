# -*- coding: utf-8 -*-
"""多源中文字幕：SubtitleCat / 迅雷 / Assrt / SubHD，评分后下载最优。

出站必须用 curl_cffi（与站点抓取一致）；纯 httpx 常被 RST。
- SubtitleCat: https://www.subtitlecat.com
- 迅雷: https://api-shoulei-ssl.xunlei.com/oracle/subtitle
- Assrt(伪射手): https://api.assrt.net （需 Token，环境变量 ASSRT_TOKEN 或设置）
- SubHD: https://subhd.tv （网页搜 + prepare-download）
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import zipfile
from typing import Any
from urllib.parse import quote, urljoin, urlparse

log = logging.getLogger(__name__)

BASE = "https://www.subtitlecat.com"
XUNLEI_API = "https://api-shoulei-ssl.xunlei.com/oracle/subtitle"
ASSRT_API = "https://api.assrt.net"
ASSRT_API_MIRROR = "https://api.makedie.me"
SUBHD_BASE = "https://subhd.tv"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# 源偏好：同分时 Assrt/SubtitleCat 略优先
_SOURCE_BONUS = {
    "assrt": 8,
    "subtitlecat": 6,
    "xunlei": 4,
    "subhd": 5,
}

_LANG_RANK = {
    "zh-cn": 0,
    "zh-hans": 1,
    "zh": 2,
    "chs": 2,
    "zh-tw": 3,
    "zh-hant": 4,
    "cht": 4,
    "chi": 5,
    "cn": 6,
    "zh-hk": 4,
    "ja": 40,
    "jp": 41,
    "en": 80,
}

# 仅接受中文（简繁均可）；非中文一律不要
_CHINESE_LANG_MAX_RANK = 6
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ZH_NAME_HINT = re.compile(
    r"(中文|简体|繁体|繁體|双语|雙語|chs|cht|zh[-_.]?cn|zh[-_.]?tw|zh[-_.]?hk)",
    re.I,
)
_NON_ZH_ONLY_HINT = re.compile(
    r"(?:^|[.\-_ \[\]()])(en|eng|english|ja|jp|jpn|japanese|ko|kor|korean)(?:$|[.\-_ \[\]()])",
    re.I,
)


class SubtitleFetchError(RuntimeError):
    """可展示给用户的拉字幕失败。"""


def _headers() -> dict[str, str]:
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
        "Referer": BASE + "/",
    }


def _get_text(url: str, *, prefer_json: bool = False) -> str:
    """优先 curl-impersonate；失败再试 httpx（带面板代理）。"""
    from . import outbound_http as o

    min_len = 8 if prefer_json else 80
    last: Exception | None = None
    # 1) curl_cffi + 面板代理
    try:
        r = o.curl_request(
            "GET",
            url,
            headers=_headers(),
            timeout=28.0,
            verify=False,
            use_panel_proxy=True,
        )
        code = int(getattr(r, "status_code", 0) or 0)
        text = str(getattr(r, "text", "") or "")
        if code < 400 and len(text) >= min_len:
            return text
        last = RuntimeError(f"HTTP {code}")
    except Exception as e:  # noqa: BLE001
        last = e
        log.debug("subtitle curl+proxy fail: %s", e)

    # 2) curl_cffi 直连
    try:
        r = o.curl_request(
            "GET",
            url,
            headers=_headers(),
            timeout=28.0,
            verify=False,
            use_panel_proxy=False,
            proxy="",
        )
        code = int(getattr(r, "status_code", 0) or 0)
        text = str(getattr(r, "text", "") or "")
        if code < 400 and len(text) >= min_len:
            return text
        last = RuntimeError(f"HTTP {code}")
    except Exception as e:  # noqa: BLE001
        last = e
        log.debug("subtitle curl direct fail: %s", e)

    # 3) httpx 兜底
    try:
        import httpx

        proxy = o.resolve_scrape_proxy_url()
        opts: dict[str, Any] = {
            "timeout": 28.0,
            "trust_env": False,
            "follow_redirects": True,
            "verify": False,
            "headers": _headers(),
        }
        if proxy:
            opts["proxy"] = proxy
        with httpx.Client(**opts) as client:
            r = client.get(url)
            if r.status_code < 400 and len(r.text) >= min_len:
                return r.text
            last = RuntimeError(f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        last = e

    raise SubtitleFetchError(
        f"无法访问字幕站（{urlparse(url).hostname}）：{last}"
    ) from last


def _get_bytes(url: str) -> bytes:
    from . import outbound_http as o

    last: Exception | None = None
    for use_proxy in (True, False):
        try:
            r = o.curl_request(
                "GET",
                url,
                headers=_headers(),
                timeout=40.0,
                verify=False,
                use_panel_proxy=use_proxy,
                proxy="" if not use_proxy else None,
            )
            code = int(getattr(r, "status_code", 0) or 0)
            data = bytes(getattr(r, "content", b"") or b"")
            if code < 400 and len(data) >= 16:
                return data
            last = RuntimeError(f"HTTP {code}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise SubtitleFetchError(f"下载字幕失败：{last}") from last


def _abs(href: str) -> str:
    return urljoin(BASE + "/", href.lstrip("/"))


def query_variants(query: str) -> list[str]:
    """番号查询变体：原样 / 去横杠 / 补横杠。"""
    raw = str(query or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def add(s: str) -> None:
        t = s.strip()
        if not t or t.casefold() in seen:
            return
        seen.add(t.casefold())
        out.append(t)

    add(raw)
    compact = re.sub(r"[\s_\-]+", "", raw)
    add(compact)
    m = re.match(r"^([A-Za-z]{2,10})(\d{2,6})$", compact)
    if m:
        add(f"{m.group(1).upper()}-{m.group(2)}")
    m2 = re.match(r"^([A-Za-z]{2,10})[-_\s]?(\d{2,6})$", raw, re.I)
    if m2:
        add(f"{m2.group(1).upper()}-{m2.group(2)}")
        add(f"{m2.group(1).upper()}{m2.group(2)}")
    return out


def _lang_from_name(name: str) -> str:
    m = re.search(
        r"(?:^|[.\-_ ])(zh-cn|zh-hans|zh-tw|zh-hant|zh-hk|zh|chs|cht|chi|cn|ja|jp|en|eng)(?:$|[.\-_ ])",
        name,
        re.I,
    )
    return (m.group(1) if m else "").lower()


def _rank_lang(lang: str) -> int:
    return _LANG_RANK.get((lang or "").lower(), 90)


def is_chinese_lang(lang: str | None) -> bool:
    return _rank_lang(str(lang or "")) <= _CHINESE_LANG_MAX_RANK


def looks_chinese_subtitle(data: bytes, *, filename: str = "") -> bool:
    """内容/文件名判定：必须是中文字幕。"""
    name = str(filename or "")
    if _ZH_NAME_HINT.search(name):
        # 文件名已标明中文，仍要排除明显「纯英/日」误标
        if _NON_ZH_ONLY_HINT.search(name) and not _CJK_RE.search(name):
            pass
        else:
            return True
    lang = _lang_from_name(name)
    if lang and is_chinese_lang(lang):
        return True
    if lang and not is_chinese_lang(lang) and lang != "und":
        return False
    text = ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            text = data.decode(enc)
            break
        except Exception:
            continue
    if not text:
        text = data.decode("utf-8", errors="ignore")
    sample = text[:12000]
    cjk = len(_CJK_RE.findall(sample))
    # 正常对白字幕至少会有若干汉字
    return cjk >= 12


def search_subtitlecat(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """搜索字幕条目（详情页列表）。"""
    q = str(query or "").strip()
    if len(q) < 2:
        return []
    url = f"{BASE}/index.php?search={quote(q)}"
    html = _get_text(url)
    if "Just a moment" in html or "cf-browser-verification" in html.lower():
        raise SubtitleFetchError("SubtitleCat 被 Cloudflare 拦截，请检查代理/FlareSolverr")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    # 与 PotPlayer 插件一致：href="subs/..."
    for m in re.finditer(
        r'href="(subs/\d+/[^"]+\.html)"[^>]*>([^<]*)',
        html,
        re.I,
    ):
        href = m.group(1).strip()
        title = re.sub(r"\s+", " ", m.group(2) or "").strip()
        abs_url = _abs(href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        out.append(
            {
                "id": href,
                "title": title or abs_url.rsplit("/", 1)[-1],
                "detailUrl": abs_url,
                "source": "subtitlecat",
            }
        )
        if len(out) >= max(1, min(20, int(limit))):
            break
    # 兜底 BeautifulSoup（结构变动时）
    if not out:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "").strip()
            if not re.search(r"subs/\d+/", href):
                continue
            if href.lower().endswith(".srt"):
                continue
            abs_url = _abs(href)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            out.append(
                {
                    "id": href,
                    "title": a.get_text(" ", strip=True) or abs_url.rsplit("/", 1)[-1],
                    "detailUrl": abs_url,
                    "source": "subtitlecat",
                }
            )
            if len(out) >= max(1, min(20, int(limit))):
                break
    return out


def list_srt_on_detail(detail_url: str) -> list[dict[str, Any]]:
    url = str(detail_url or "").strip()
    if not url:
        return []
    html = _get_text(url)
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(r'href="(/subs/\d+/[^"]+\.srt)"', html, re.I):
        href = m.group(1)
        abs_url = _abs(href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        name = abs_url.rsplit("/", 1)[-1]
        lang = _lang_from_name(name)
        files.append(
            {
                "url": abs_url,
                "filename": name,
                "lang": lang or "und",
                "label": name,
            }
        )
    files.sort(
        key=lambda x: (_rank_lang(str(x.get("lang") or "")), str(x.get("filename")))
    )
    return files


def pick_best_srt(files: list[dict[str, Any]]) -> dict[str, Any] | None:
    """只选中文；没有中文则返回 None（不要英文/日文）。"""
    if not files:
        return None
    chinese = [
        f
        for f in files
        if is_chinese_lang(str(f.get("lang") or ""))
        or _ZH_NAME_HINT.search(str(f.get("filename") or f.get("label") or ""))
    ]
    if not chinese:
        return None
    chinese.sort(
        key=lambda x: (
            _rank_lang(str(x.get("lang") or "")),
            str(x.get("filename") or ""),
        )
    )
    return chinese[0]


def download_bytes(url: str) -> tuple[bytes, str]:
    data = _get_bytes(url)
    if len(data) > 8 * 1024 * 1024:
        raise SubtitleFetchError("字幕文件过大")
    name = urlparse(url).path.rsplit("/", 1)[-1] or "subtitle.srt"
    return data, name


def search_xunlei(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """迅雷公开字幕接口（PotPlayer 插件同款）。"""
    q = str(query or "").strip()
    if len(q) < 2:
        return []
    url = f"{XUNLEI_API}?gcid=&cid=&name={quote(q)}"
    try:
        text = _get_text(url, prefer_json=True)
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        log.debug("xunlei search fail: %s", e)
        return []
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows[: max(1, min(20, int(limit)))]:
        if not isinstance(row, dict):
            continue
        dl = str(row.get("url") or "").strip()
        ext = str(row.get("ext") or "srt").strip().lstrip(".") or "srt"
        if not dl:
            continue
        name = str(row.get("name") or q).strip() or q
        out.append(
            {
                "id": dl,
                "title": f"{name}（迅雷）",
                "detailUrl": dl,
                "downloadUrl": dl,
                "filename": f"{name}.{ext}",
                "lang": "zh-cn",
                "source": "xunlei",
                "ext": ext,
            }
        )
    return out


def resolve_assrt_token() -> str:
    env = os.environ.get("ASSRT_TOKEN", "").strip()
    if env:
        return env
    try:
        from . import settings_store

        raw = settings_store.get_setting(settings_store.SUBTITLE_KEY) or {}
        return str(raw.get("assrtToken") or raw.get("assrt_token") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _assrt_get(path: str, *, token: str, params: dict[str, Any]) -> dict[str, Any]:
    q = dict(params)
    q["token"] = token
    qs = "&".join(f"{k}={quote(str(v))}" for k, v in q.items() if v is not None)
    last: Exception | None = None
    for base in (ASSRT_API, ASSRT_API_MIRROR):
        url = f"{base.rstrip('/')}{path}?{qs}"
        try:
            text = _get_text(url, prefer_json=True)
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except Exception as e:  # noqa: BLE001
            last = e
            log.debug("assrt %s fail: %s", base, e)
    raise SubtitleFetchError(f"Assrt 请求失败：{last}") from last


def _assrt_lang(row: dict[str, Any]) -> str:
    lang = row.get("lang") if isinstance(row.get("lang"), dict) else {}
    desc = str((lang or {}).get("desc") or "")
    lst = (lang or {}).get("langlist") if isinstance((lang or {}).get("langlist"), dict) else {}
    blob = f"{desc} {json.dumps(lst, ensure_ascii=False)}"
    if re.search(r"简|chs|langchs|zh-cn|zh_hans", blob, re.I):
        return "zh-cn"
    if re.search(r"繁|cht|langcht|zh-tw|zh_hant", blob, re.I):
        return "zh-tw"
    if re.search(r"双|双语|langdou|中文|chi|zh", blob, re.I):
        return "zh"
    return "und"


def search_assrt(query: str, *, limit: int = 8, token: str = "") -> list[dict[str, Any]]:
    """Assrt API 搜索（需 token）。"""
    q = str(query or "").strip()
    tok = (token or resolve_assrt_token()).strip()
    if len(q) < 3 or not tok:
        return []
    try:
        data = _assrt_get(
            "/v1/sub/search",
            token=tok,
            params={"q": q, "cnt": max(1, min(15, int(limit))), "filelist": 0},
        )
    except Exception as e:  # noqa: BLE001
        log.debug("assrt search fail: %s", e)
        return []
    if int(data.get("status") or 0) != 0:
        log.debug("assrt status=%s", data.get("status"))
        return []
    sub = data.get("sub") if isinstance(data.get("sub"), dict) else {}
    rows = sub.get("subs") if isinstance(sub, dict) else None
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("id")
        if sid is None:
            continue
        title = str(row.get("native_name") or row.get("videoname") or sid)
        subtype = str(row.get("subtype") or "")
        lang = _assrt_lang(row)
        if not is_chinese_lang(lang) and not _ZH_NAME_HINT.search(
            f"{title} {subtype} {lang}"
        ):
            # Assrt 常只标「双语」；仍保留，下载后再 content-check
            if "双" not in str((row.get("lang") or {}).get("desc") or ""):
                if lang == "und" and not _ZH_NAME_HINT.search(title):
                    # 无中文线索则跳过明显外语
                    if re.search(r"\b(eng|english|japanese)\b", title, re.I):
                        continue
        out.append(
            {
                "id": str(sid),
                "title": title,
                "detailUrl": f"assrt://{sid}",
                "filename": str(row.get("videoname") or title),
                "lang": lang,
                "source": "assrt",
                "ext": "srt" if "srt" in subtype.lower() or "subrip" in subtype.lower() else "ass",
                "vote": int(row.get("vote_score") or 0),
                "subtype": subtype,
            }
        )
    return out


def _assrt_resolve_download(sub_id: str, *, token: str = "") -> list[dict[str, Any]]:
    tok = (token or resolve_assrt_token()).strip()
    if not tok:
        return []
    data = _assrt_get("/v1/sub/detail", token=tok, params={"id": sub_id})
    if int(data.get("status") or 0) != 0:
        return []
    sub = data.get("sub") if isinstance(data.get("sub"), dict) else {}
    rows = sub.get("subs") if isinstance(sub, dict) else None
    if not isinstance(rows, list) or not rows:
        return []
    row = rows[0] if isinstance(rows[0], dict) else {}
    files: list[dict[str, Any]] = []
    filelist = row.get("filelist")
    if isinstance(filelist, list) and filelist:
        for f in filelist:
            if not isinstance(f, dict):
                continue
            url = str(f.get("url") or "").strip()
            name = str(f.get("f") or "subtitle.srt")
            if not url:
                continue
            files.append({"url": url, "filename": name, "lang": _assrt_lang(row)})
    else:
        url = str(row.get("url") or "").strip()
        name = str(row.get("filename") or "subtitle.zip")
        if url:
            files.append({"url": url, "filename": name, "lang": _assrt_lang(row)})
    return files


def search_subhd(query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """SubHD 搜索：只收 /a/ 真实字幕条目，且标题需命中查询词。"""
    q = str(query or "").strip()
    if len(q) < 2:
        return []
    url = f"{SUBHD_BASE}/search/{quote(q)}"
    try:
        html = _get_text(url)
    except Exception as e:  # noqa: BLE001
        log.debug("subhd search fail: %s", e)
        return []
    idx = html.find("搜索结果")
    section = html[idx:] if idx >= 0 else html
    # 截断热门侧栏：搜索结果卡片后常接其他大段
    cut = section.find("热门")
    if cut > 200:
        section = section[:cut]
    qn = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]", "", q).upper()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'href=[\'"](/a/([A-Za-z0-9]+))[\'"][^>]*>(.*?)</a>',
        section,
        re.I | re.S,
    ):
        path, sid, raw_title = m.group(1), m.group(2), m.group(3)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw_title)).strip()
        if not title or path in seen:
            continue
        tn = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]", "", title).upper()
        if qn and qn not in tn and q.upper() not in title.upper():
            continue
        seen.add(path)
        lang = "zh-cn"
        if re.search(r"繁体|繁體|cht", title, re.I):
            lang = "zh-tw"
        elif re.search(r"简体|簡體|chs", title, re.I):
            lang = "zh-cn"
        elif re.search(r"双语|雙語", title):
            lang = "zh"
        out.append(
            {
                "id": sid,
                "title": title,
                "detailUrl": urljoin(SUBHD_BASE + "/", path.lstrip("/")),
                "filename": f"{title}.srt",
                "lang": lang,
                "source": "subhd",
                "ext": "srt",
            }
        )
        if len(out) >= max(1, min(20, int(limit))):
            break
    return out


def _code_match_score(query: str, title: str) -> int:
    q = str(query or "").strip()
    t = str(title or "")
    if not q or not t:
        return 0
    qn = re.sub(r"[^A-Za-z0-9]", "", q).upper()
    tn = re.sub(r"[^A-Za-z0-9]", "", t).upper()
    if not qn:
        return 90 if q in t else 0
    if tn == qn or tn.startswith(qn):
        return 100
    if qn in tn:
        return 85
    m = re.match(r"^([A-Z]+)(\d+)$", qn)
    if m and m.group(1) in tn and m.group(2) in tn:
        return 55
    return 0


def _file_ext(name: str) -> str:
    n = str(name or "")
    if "." in n:
        return n.rsplit(".", 1)[-1].lower()
    return "srt"


def score_candidate(query: str, hit: dict[str, Any]) -> int:
    """越高越好：番号命中 > 语言 > 格式 > 源偏好 > 评分。"""
    title = str(hit.get("title") or hit.get("filename") or "")
    lang = str(hit.get("lang") or "")
    filename = str(hit.get("filename") or title)
    source = str(hit.get("source") or "")
    ext = str(hit.get("ext") or _file_ext(filename)).lower().lstrip(".")
    match = _code_match_score(query, f"{title} {filename}")
    if match <= 0:
        if source == "xunlei":
            match = 45
        else:
            return -1
    score = match
    if is_chinese_lang(lang):
        score += max(0, 30 - _rank_lang(lang) * 3)
    if _ZH_NAME_HINT.search(f"{title} {filename}"):
        score += 8
    if ext in ("srt", "subrip"):
        score += 12
    elif ext in ("ass", "ssa"):
        score += 8
    elif ext == "vtt":
        score += 4
    score += int(_SOURCE_BONUS.get(source, 0))
    score += min(20, int(hit.get("vote") or 0) // 5)
    return score


def _extract_subtitle_from_bytes(
    data: bytes, *, preferred_name: str = ""
) -> tuple[bytes, str] | None:
    """纯字幕或 zip 内挑最优中文字幕。"""
    if not data:
        return None
    name = preferred_name or "subtitle.srt"
    lower = name.lower()
    if lower.endswith((".srt", ".ass", ".ssa", ".vtt")):
        return data, name
    # zip
    if data[:2] == b"PK" or lower.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                cands: list[tuple[int, str, bytes]] = []
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    fn = info.filename.rsplit("/", 1)[-1]
                    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else ""
                    if ext not in ("srt", "ass", "ssa", "vtt"):
                        continue
                    raw = zf.read(info)
                    if len(raw) < 16:
                        continue
                    lang = _lang_from_name(fn)
                    sc = 0
                    if is_chinese_lang(lang) or _ZH_NAME_HINT.search(fn):
                        sc += 50
                    if looks_chinese_subtitle(raw, filename=fn):
                        sc += 40
                    if ext == "srt":
                        sc += 10
                    cands.append((sc, fn, raw))
                if not cands:
                    return None
                cands.sort(key=lambda x: (-x[0], x[1]))
                best = cands[0]
                if best[0] < 40 and not looks_chinese_subtitle(best[2], filename=best[1]):
                    return None
                return best[2], best[1]
        except zipfile.BadZipFile:
            return None
    # 当作字幕正文
    if looks_chinese_subtitle(data, filename=name) or len(data) < 2 * 1024 * 1024:
        return data, name if "." in name else f"{name}.srt"
    return None


def _download_subhd(detail_url: str) -> tuple[bytes, str]:
    """同一 curl 会话：详情 → prepare-download → /down/。"""
    from curl_cffi import requests as creq

    from . import outbound_http as o

    proxy = o.resolve_scrape_proxy_url()
    session = creq.Session(impersonate="chrome")
    headers = {
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": SUBHD_BASE + "/",
    }
    kw: dict[str, Any] = {"timeout": 28, "verify": False, "headers": headers}
    if proxy:
        kw["proxy"] = proxy
    r = session.get(detail_url, **kw)
    html = str(getattr(r, "text", "") or "")
    if int(getattr(r, "status_code", 0) or 0) >= 400 or len(html) < 200:
        raise SubtitleFetchError(f"SubHD 详情失败 HTTP {getattr(r, 'status_code', '?')}")
    m = re.search(r'data-sid=["\']([^"\']+)["\']', html)
    if not m:
        raise SubtitleFetchError("SubHD 详情无下载按钮")
    sid = m.group(1)
    r2 = session.post(
        f"{SUBHD_BASE}/api/sub/prepare-download",
        headers={
            **headers,
            "Referer": detail_url,
            "Origin": SUBHD_BASE,
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"sid": sid},
        timeout=28,
        verify=False,
        **({"proxy": proxy} if proxy else {}),
    )
    try:
        payload = r2.json()
    except Exception as e:  # noqa: BLE001
        raise SubtitleFetchError(f"SubHD prepare 无效响应：{e}") from e
    if not payload.get("success") or not str(payload.get("url") or "").startswith("/down/"):
        raise SubtitleFetchError(
            str(payload.get("msg") or "SubHD 无法准备下载（可能需登录/风控）")
        )
    dl = urljoin(SUBHD_BASE + "/", str(payload["url"]).lstrip("/"))
    r3 = session.get(
        dl,
        headers={**headers, "Referer": detail_url},
        timeout=45,
        verify=False,
        allow_redirects=True,
        **({"proxy": proxy} if proxy else {}),
    )
    data = bytes(getattr(r3, "content", b"") or b"")
    if int(getattr(r3, "status_code", 0) or 0) >= 400 or len(data) < 16:
        raise SubtitleFetchError("SubHD 下载失败")
    # filename from content-disposition
    cd = str((getattr(r3, "headers", {}) or {}).get("content-disposition") or "")
    fname = "subhd.srt"
    m2 = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
    if m2:
        fname = m2.group(1).strip()
    return data, fname


def _materialize_candidate(hit: dict[str, Any]) -> tuple[bytes, str]:
    """把候选解析成字幕 bytes + 文件名。"""
    source = str(hit.get("source") or "")
    if source == "assrt":
        files = _assrt_resolve_download(str(hit.get("id") or ""))
        if not files:
            raise SubtitleFetchError("Assrt 无下载文件")
        # 优先中文 srt
        files.sort(
            key=lambda f: (
                0 if is_chinese_lang(str(f.get("lang") or "")) else 1,
                0 if str(f.get("filename") or "").lower().endswith(".srt") else 1,
                str(f.get("filename") or ""),
            )
        )
        last_err: Exception | None = None
        for f in files[:6]:
            try:
                raw = _get_bytes(str(f["url"]))
                picked = _extract_subtitle_from_bytes(
                    raw, preferred_name=str(f.get("filename") or "")
                )
                if picked:
                    return picked
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise SubtitleFetchError(f"Assrt 下载失败：{last_err}") from last_err
    if source == "subhd":
        raw, fname = _download_subhd(str(hit.get("detailUrl") or ""))
        picked = _extract_subtitle_from_bytes(raw, preferred_name=fname)
        if not picked:
            raise SubtitleFetchError("SubHD 压缩包内无中文字幕")
        return picked
    # subtitlecat / xunlei direct
    dl = str(hit.get("downloadUrl") or hit.get("detailUrl") or "").strip()
    if not dl:
        raise SubtitleFetchError("无下载地址")
    raw = _get_bytes(dl)
    fname = str(hit.get("filename") or urlparse(dl).path.rsplit("/", 1)[-1] or "subtitle.srt")
    picked = _extract_subtitle_from_bytes(raw, preferred_name=fname)
    if not picked:
        raise SubtitleFetchError("文件不是可用字幕")
    return picked


def collect_candidates(query: str) -> list[dict[str, Any]]:
    """各源搜索并打分；不下载正文。"""
    variants = query_variants(query)
    if not variants:
        return []
    primary = variants[0]
    scored: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(hit: dict[str, Any], *, q: str) -> None:
        key = f"{hit.get('source')}|{hit.get('id') or hit.get('downloadUrl') or hit.get('detailUrl')}"
        if key in seen:
            return
        sc = score_candidate(q, hit)
        if sc < 0:
            return
        seen.add(key)
        row = dict(hit)
        row["query"] = q
        row["score"] = sc
        scored.append(row)

    # SubtitleCat：各变体搜，展开中文 srt
    for q in variants:
        try:
            hits = search_subtitlecat(q, limit=6)
        except Exception as e:  # noqa: BLE001
            log.debug("subtitlecat search %s: %s", q, e)
            continue
        qn = re.sub(r"[^A-Za-z0-9]", "", q).upper()
        ranked = []
        for h in hits:
            t = re.sub(r"[^A-Za-z0-9]", "", str(h.get("title") or "")).upper()
            if qn and qn not in t:
                continue
            ranked.append(h)
        for hit in ranked[:4]:
            try:
                files = list_srt_on_detail(str(hit["detailUrl"]))
            except Exception as e:  # noqa: BLE001
                log.debug("subtitlecat detail: %s", e)
                continue
            for f in files:
                if not (
                    is_chinese_lang(str(f.get("lang") or ""))
                    or _ZH_NAME_HINT.search(str(f.get("filename") or ""))
                ):
                    continue
                add(
                    {
                        "id": f.get("url"),
                        "title": hit.get("title"),
                        "detailUrl": hit.get("detailUrl"),
                        "downloadUrl": f.get("url"),
                        "filename": f.get("filename"),
                        "lang": f.get("lang") or "zh",
                        "source": "subtitlecat",
                        "ext": "srt",
                    },
                    q=q,
                )

    # 迅雷
    for q in variants:
        try:
            for hit in search_xunlei(q, limit=8):
                add(hit, q=q)
        except Exception as e:  # noqa: BLE001
            log.debug("xunlei: %s", e)

    # Assrt
    tok = resolve_assrt_token()
    if tok:
        for q in variants:
            if len(q) < 3:
                continue
            try:
                for hit in search_assrt(q, limit=8, token=tok):
                    add(hit, q=q)
            except Exception as e:  # noqa: BLE001
                log.debug("assrt: %s", e)

    # SubHD（片名/番号均可；无命中则空）
    for q in variants[:2]:
        try:
            for hit in search_subhd(q, limit=8):
                add(hit, q=q)
        except Exception as e:  # noqa: BLE001
            log.debug("subhd: %s", e)

    scored.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("source")), str(x.get("title"))))
    # 同 query 下保留前 16
    return scored[:16]


def fetch_best_for_query(query: str) -> dict[str, Any] | None:
    """多源搜索 → 按分下载，内容校验中文后返回最优。"""
    q0 = str(query or "").strip()
    if not q0:
        return None
    last_err: Exception | None = None
    try:
        cands = collect_candidates(q0)
    except SubtitleFetchError:
        raise
    except Exception as e:  # noqa: BLE001
        last_err = e
        cands = []

    if not cands:
        # 兼容旧路径：若 collect 全空且网络全挂，抛错
        if last_err:
            raise SubtitleFetchError(str(last_err)) from last_err
        return None

    tried = 0
    for hit in cands:
        if tried >= 8:
            break
        tried += 1
        try:
            data, fname = _materialize_candidate(hit)
            if len(data) > 8 * 1024 * 1024:
                continue
            title = str(hit.get("title") or "")
            if not looks_chinese_subtitle(data, filename=f"{fname} {title}"):
                log.debug("skip non-chinese from %s: %s", hit.get("source"), fname)
                continue
            return {
                "query": hit.get("query") or q0,
                "title": hit.get("title"),
                "detailUrl": hit.get("detailUrl") or hit.get("downloadUrl"),
                "lang": hit.get("lang") or "zh",
                "filename": fname,
                "source": hit.get("source"),
                "bytes": data,
                "score": hit.get("score"),
                "candidates": len(cands),
            }
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.debug("download %s fail: %s", hit.get("source"), e)
            continue

    if last_err and tried == 0:
        raise SubtitleFetchError(str(last_err)) from last_err
    return None
