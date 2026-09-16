# -*- coding: utf-8 -*-
"""女优详细资料：本地 Actress.db / JSON 缓存；年龄按生日实时计算。

浏览/详情默认不联网。E2E 刮削时从本地 DB 写入 PG；头像另在 E2E 落盘。
minnano 仅 allow_online=True 时可用（默认关）。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import unicodedata
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from app.core.db import ROOT, media_dir

log = logging.getLogger(__name__)

_BIO_CACHE_NAME = "_bio.json"
_MINNANO_BASE = "https://www.minnano-av.com"
_NAME_LINE_RE = re.compile(
    r"^(?P<name>.+?)\s*[（(]\s*(?P<kana>[^/（）()]+?)\s*/\s*(?P<roma>[^）)]+?)\s*[）)]\s*$"
)
_FIGURE_RE = re.compile(
    r"T\s*(?P<t>\d+)\s*/\s*B\s*(?P<b>\d+)\s*"
    r"(?:\(\s*(?:<[^>]+>)?(?P<cup>[A-Z]+)(?:カップ)?(?:</[^>]+>)?\s*\))?\s*"
    r"/\s*W\s*(?P<w>\d+)\s*/\s*H\s*(?P<h>\d+)",
    re.IGNORECASE,
)
_CUP_RE = re.compile(r"([A-Z]+)カップ", re.IGNORECASE)
_ACTRESS_HREF_RE = re.compile(r"actress\d+\.html", re.IGNORECASE)
_BIRTHDAY_RE = re.compile(r"(19|20)\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}")

_cache_lock = threading.Lock()


def bio_cache_path() -> Path:
    d = (media_dir() / "scrap-library" / "_actress").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d / _BIO_CACHE_NAME


def actress_db_candidates() -> list[Path]:
    base = ROOT / "apps" / "api" / "_local_refs" / "mdcx"
    out: list[Path] = []
    if base.is_dir():
        out.extend(sorted(base.glob("Actress*.db"), reverse=True))
    # gap_reports / 备份兼容
    gap = ROOT / "apps" / "api" / "_gap_reports"
    if gap.is_dir():
        out.extend(sorted(gap.glob("*Actress*.db"), reverse=True))
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        k = str(p.resolve())
        if k in seen or not p.is_file():
            continue
        seen.add(k)
        uniq.append(p)
    return uniq


def fold_key(name: str) -> str:
    s = unicodedata.normalize("NFKC", str(name or "")).strip().casefold()
    s = re.sub(r"[\s\-_.·・/／\\]+", "", s)
    return s


def age_from_birthday(
    birthday: str | None, *, today: date | None = None
) -> int | None:
    """按公历生日计算当前真实年龄（已过生日才 +1 岁）。"""
    d = parse_birthday(birthday)
    if not d:
        return None
    now = today or date.today()
    years = now.year - d.year
    if (now.month, now.day) < (d.month, d.day):
        years -= 1
    return years if years >= 0 else None


def parse_birthday(raw: str | None) -> date | None:
    s = unicodedata.normalize("NFKC", str(raw or "")).strip()
    if not s:
        return None
    m = _BIRTHDAY_RE.search(s)
    if m:
        s = m.group(0)
    s = (
        s.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
        .replace(".", "-")
    )
    s = re.sub(r"\s+", "", s)
    parts = s.split("-")
    if len(parts) < 3:
        return None
    try:
        y, mo, da = int(parts[0]), int(parts[1]), int(parts[2])
        return date(y, mo, da)
    except Exception:
        return None


def format_birthday(raw: str | None) -> str:
    d = parse_birthday(raw)
    return d.isoformat() if d else ""


def _load_bio_cache() -> dict[str, Any]:
    path = bio_cache_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_bio_cache(data: dict[str, Any]) -> None:
    path = bio_cache_path()
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _cache_get(keys: list[str]) -> dict[str, Any] | None:
    with _cache_lock:
        store = _load_bio_cache()
    for k in keys:
        fk = fold_key(k)
        if not fk:
            continue
        hit = store.get(fk)
        if isinstance(hit, dict) and (
            hit.get("birthday")
            or hit.get("height")
            or hit.get("cup")
            or hit.get("bust")
            or hit.get("source")
        ):
            return dict(hit)
    return None


def _cache_put(keys: list[str], bio: dict[str, Any]) -> None:
    if not bio:
        return
    row = {k: v for k, v in bio.items() if v not in (None, "", [], {})}
    row["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    with _cache_lock:
        store = _load_bio_cache()
        for k in keys:
            fk = fold_key(k)
            if fk:
                store[fk] = row
        _save_bio_cache(store)


def _norm_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        n = int(str(v).strip())
        return n if n > 0 else None
    except Exception:
        return None


def _norm_cup(v: Any) -> str:
    s = unicodedata.normalize("NFKC", str(v or "")).strip().upper()
    s = s.replace("カップ", "").replace("罩杯", "")
    m = re.search(r"[A-Z]{1,3}", s)
    return m.group(0) if m else ""


def _empty_bio() -> dict[str, Any]:
    return {
        "birthday": "",
        "age": None,
        "height": None,
        "bust": None,
        "waist": None,
        "hip": None,
        "cup": "",
        "birthplace": "",
        "careerPeriod": "",
        "debutWork": "",
        "source": "",
        "sourceUrl": "",
    }


def _finalize(bio: dict[str, Any]) -> dict[str, Any]:
    out = _empty_bio()
    out.update({k: v for k, v in (bio or {}).items() if k in out or k in ("roma",)})
    out["birthday"] = format_birthday(out.get("birthday"))
    out["age"] = age_from_birthday(out.get("birthday"))
    out["height"] = _norm_int(out.get("height"))
    out["bust"] = _norm_int(out.get("bust"))
    out["waist"] = _norm_int(out.get("waist"))
    out["hip"] = _norm_int(out.get("hip"))
    out["cup"] = _norm_cup(out.get("cup"))
    for k in ("birthplace", "careerPeriod", "debutWork", "source", "sourceUrl"):
        out[k] = str(out.get(k) or "").strip()
    # 生涯文案轻度清洗
    if out["careerPeriod"]:
        out["careerPeriod"] = (
            out["careerPeriod"].replace(" ", "").replace("年-", "年 – ")
        )
    return out


def _bio_has_body(bio: dict[str, Any]) -> bool:
    return bool(
        bio.get("birthday")
        or bio.get("height")
        or bio.get("cup")
        or bio.get("bust")
        or bio.get("birthplace")
        or bio.get("careerPeriod")
    )


@lru_cache(maxsize=1)
def _db_path() -> str | None:
    for p in actress_db_candidates():
        return str(p.resolve())
    return None


def expand_actress_query_names(
    seeds: list[str], *, limit: int = 64
) -> list[str]:
    """刮削/查库用：标准名 + 映射别名 + Actress.db Names 连通分量。

    只扩名字、不联网。顺序：种子 → 映射别名 → DB 别名链。
    """
    out: list[str] = []
    seen: set[str] = set()

    def add(n: str) -> None:
        s = str(n or "").strip()
        if not s:
            return
        k = fold_key(s)
        if not k or k in seen:
            return
        seen.add(k)
        out.append(s)

    for seed in seeds or []:
        add(seed)
    if not out:
        return []

    # 映射表别名（日文键/繁简）
    try:
        from app.scrap_library.actress_avatar import _alias_names
        from app.scrape.metadata_optimize import polish_actress_names

        polished = polish_actress_names(list(out))
        for p in polished:
            add(p)
        for seed in list(out)[:12]:
            for a in _alias_names(seed):
                add(a)
                if len(out) >= max(8, int(limit) // 2):
                    break
            if len(out) >= max(8, int(limit) // 2):
                break
    except Exception as e:  # noqa: BLE001
        log.debug("expand map aliases failed: %s", e)

    # Actress.db Names 连通：把中间别名也纳入查询（神乐凛↔神楽りん↔本田かなの）
    path = _db_path()
    if path and len(out) < int(limit):
        try:
            con = sqlite3.connect(path)
            cur = con.cursor()
            queue = list(out)
            qi = 0
            while qi < len(queue) and len(out) < int(limit):
                q = queue[qi]
                qi += 1
                for row in cur.execute(
                    "SELECT Name, Alias FROM Names WHERE Alias = ? OR Name = ?",
                    (q, q),
                ).fetchall():
                    for col in (0, 1):
                        nxt = str(row[col] or "").strip()
                        if not nxt:
                            continue
                        k = fold_key(nxt)
                        if not k or k in seen:
                            continue
                        seen.add(k)
                        out.append(nxt)
                        queue.append(nxt)
                        if len(out) >= int(limit):
                            break
                    if len(out) >= int(limit):
                        break
            con.close()
        except Exception as e:  # noqa: BLE001
            log.debug("expand db aliases failed: %s", e)

    return out[: max(1, int(limit))]


def lookup_actress_db(names: list[str]) -> dict[str, Any] | None:
    path = _db_path()
    if not path:
        return None
    cands = [str(n or "").strip() for n in names if str(n or "").strip()]
    if not cands:
        return None
    try:
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        # BFS：Names 可能只指到中间别名（神乐凛→神楽りん→本田かなの），需跟随到 Info
        queue: list[str] = list(cands)
        seen: set[str] = set()
        while queue:
            q = queue.pop(0)
            if not q or q in seen:
                continue
            seen.add(q)
            row = cur.execute(
                "SELECT Name, NameCN, Href, Roma, Birthday, Height, Bust, Waist, Hip, "
                "Cup, Birthplace, CareerPeriod, DebutWork "
                "FROM Info WHERE Name = ? OR NameCN = ? LIMIT 1",
                (q, q),
            ).fetchone()
            if row:
                return _row_to_bio(row)
            for nr in cur.execute(
                "SELECT Name, Alias FROM Names WHERE Alias = ? OR Name = ?",
                (q, q),
            ).fetchall():
                for key in ("Name", "Alias"):
                    nxt = str(nr[key] or "").strip()
                    if nxt and nxt not in seen:
                        queue.append(nxt)
        return None
    except Exception as e:  # noqa: BLE001
        log.debug("actress db lookup failed: %s", e)
        return None
    finally:
        try:
            con.close()
        except Exception:
            pass


def _row_to_bio(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    href = str(row["Href"] or "").strip()
    url = ""
    if href.startswith("http"):
        url = href.split("?", 1)[0]
    elif href:
        url = f"{_MINNANO_BASE}/{href.split('?', 1)[0]}"
    bio = _finalize(
        {
            "birthday": row["Birthday"],
            "height": row["Height"],
            "bust": row["Bust"],
            "waist": row["Waist"],
            "hip": row["Hip"],
            "cup": row["Cup"],
            "birthplace": row["Birthplace"],
            "careerPeriod": row["CareerPeriod"],
            "debutWork": row["DebutWork"],
            "source": "actress_db",
            "sourceUrl": url,
            "roma": row["Roma"],
        }
    )
    return bio if _bio_has_body(bio) or url else None


def _fetch_html(url: str) -> tuple[str, str]:
    from app.core.outbound_http import fetch_page

    page = fetch_page(
        url,
        access="proxy_adaptive",
        timeout=22.0,
        referer=_MINNANO_BASE + "/",
    )
    html = str(getattr(page, "html", "") or getattr(page, "text", "") or "")
    final = str(getattr(page, "final_url", "") or url)
    return html, final


def _parse_name_line(raw: str) -> tuple[str, list[str]]:
    text = unicodedata.normalize("NFKC", raw).strip()
    m = _NAME_LINE_RE.match(text)
    if not m:
        return text, []
    name = m.group("name").strip()
    aliases = [a.strip() for a in (m.group("kana"), m.group("roma")) if a and a.strip()]
    return name, aliases


def _profile_fields(profile: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in profile.select("tr"):
        span = row.select_one("td span")
        if not span:
            continue
        key = span.get_text(" ", strip=True)
        if not key:
            continue
        p = row.select_one("td p")
        val = p.get_text(" ", strip=True) if p else row.get_text(" ", strip=True)
        if val.startswith(key):
            val = val[len(key) :].strip()
        if val:
            out[key] = val
    return out


def _parse_figure(
    raw: str,
) -> tuple[int | None, int | None, int | None, int | None, str]:
    text = unicodedata.normalize("NFKC", raw or "")
    text = re.sub(r"<[^>]+>", "", text)
    m = _FIGURE_RE.search(text)
    cup_m = _CUP_RE.search(text)
    cup = ""
    if m and m.group("cup"):
        cup = m.group("cup").upper()
    elif cup_m:
        cup = cup_m.group(1).upper()
    if not m:
        return None, None, None, None, cup
    return (
        int(m.group("t")),
        int(m.group("b")),
        int(m.group("w")),
        int(m.group("h")),
        cup,
    )


def parse_minnano_html(html: str, *, page_url: str = "") -> dict[str, Any] | None:
    soup = BeautifulSoup(html or "", "lxml")
    profile = soup.select_one("div.act-profile")
    if not profile:
        return None
    h2 = profile.select_one("h2")
    raw_name = h2.get_text(" ", strip=True) if h2 else ""
    if not raw_name:
        return None
    name, aliases = _parse_name_line(raw_name)
    fields = _profile_fields(profile)
    height, bust, waist, hip, cup = _parse_figure(fields.get("サイズ", ""))
    canon = ""
    link = soup.select_one('link[rel="canonical"]')
    if link and link.get("href"):
        canon = str(link["href"]).strip()
    if not canon:
        og = soup.select_one('meta[property="og:url"]')
        if og and og.get("content"):
            canon = str(og["content"]).strip()
    bio = _finalize(
        {
            "birthday": fields.get("生年月日", ""),
            "height": height,
            "bust": bust,
            "waist": waist,
            "hip": hip,
            "cup": cup,
            "birthplace": fields.get("出身地", ""),
            "careerPeriod": fields.get("AV出演期間", "") or fields.get("出演期間", ""),
            "debutWork": "",
            "source": "minnano",
            "sourceUrl": canon or page_url,
            "nameJa": name,
            "aliasesJa": aliases,
        }
    )
    return bio if _bio_has_body(bio) or bio.get("sourceUrl") else None


def _search_minnano(name: str) -> str | None:
    q = quote(str(name or "").strip())
    if not q:
        return None
    url = (
        f"{_MINNANO_BASE}/search_result.php"
        f"?search_scope=actress&search_word={q}&search=Go"
    )
    html, final = _fetch_html(url)
    soup = BeautifulSoup(html or "", "lxml")
    if soup.select_one("div.act-profile"):
        link = soup.select_one('link[rel="canonical"]')
        if link and link.get("href"):
            return str(link["href"]).strip()
        og = soup.select_one('meta[property="og:url"]')
        if og and og.get("content"):
            return str(og["content"]).strip()
        img = soup.select_one('div.thumb img[src*="p_actress"]')
        if img and img.get("src"):
            m = re.search(r"/(\d+)\.jpg", str(img["src"]))
            if m:
                return f"{_MINNANO_BASE}/actress{m.group(1)}.html"
        return final if _ACTRESS_HREF_RE.search(final) else None

    exact = first = None
    for row in soup.select("table.tbllist.actress tr"):
        a = row.select_one("h2.ttl a") or row.select_one("h2 a") or row.select_one("a")
        if not a or not a.get("href"):
            continue
        href = str(a.get("href") or "")
        if not _ACTRESS_HREF_RE.search(href):
            continue
        clean = href.split("?", 1)[0]
        full = urljoin(_MINNANO_BASE + "/", clean)
        title = a.get_text(" ", strip=True)
        if first is None:
            first = full
        if title and title.strip() == name:
            exact = full
            break
    return exact or first


def fetch_minnano_bio(
    names: list[str], *, prefer_url: str = ""
) -> dict[str, Any] | None:
    urls: list[str] = []
    if prefer_url and "minnano-av.com" in prefer_url:
        urls.append(prefer_url.split("?", 1)[0])
    for n in names:
        n = str(n or "").strip()
        if not n:
            continue
        try:
            hit = _search_minnano(n)
            if hit and hit not in urls:
                urls.append(hit)
        except Exception as e:  # noqa: BLE001
            log.debug("minnano search failed %s: %s", n, e)
    for u in urls:
        try:
            html, final = _fetch_html(u)
            bio = parse_minnano_html(html, page_url=final or u)
            if bio and _bio_has_body(bio):
                return bio
        except Exception as e:  # noqa: BLE001
            log.debug("minnano detail failed %s: %s", u, e)
    return None


def resolve_actress_bio(
    *,
    display: str,
    query_name: str = "",
    aliases: list[str] | None = None,
    map_url: str = "",
    refresh: bool = False,
    online_timeout_s: float = 4.0,
    allow_online: bool = False,
) -> dict[str, Any]:
    """解析女优详细资料。

    默认只走本地：JSON 缓存 → Actress.db（别名 BFS）。
    不在运行时打 minnano；allow_online=True 才允许联网（工具/手工，默认关）。
    """
    names: list[str] = []
    for n in [display, query_name, *(aliases or [])]:
        s = str(n or "").strip()
        if s and s not in names:
            names.append(s)

    # 映射别名 + Actress.db 连通名全扩，避免只查中文标准名落空
    try:
        names = expand_actress_query_names(names or [display, query_name], limit=64)
    except Exception as e:  # noqa: BLE001
        log.debug("actress bio alias expand failed: %s", e)
        if not aliases:
            try:
                from app.scrap_library.actress_avatar import _alias_names

                for seed in (display, query_name):
                    if not str(seed or "").strip():
                        continue
                    for a in _alias_names(str(seed)):
                        if a not in names:
                            names.append(a)
            except Exception as e2:  # noqa: BLE001
                log.debug("actress bio alias expand fallback failed: %s", e2)
    if not refresh:
        cached = _cache_get(names)
        if cached:
            return _finalize(cached)

    db_bio = lookup_actress_db(names)
    if db_bio and _bio_has_body(db_bio):
        _cache_put(names, db_bio)
        return db_bio

    if not allow_online:
        if db_bio:
            _cache_put(names, db_bio)
            return db_bio
        return _finalize({"source": "", "sourceUrl": map_url or ""})

    online: dict[str, Any] | None = None
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fetch_minnano_bio, names, prefer_url=map_url)
            try:
                online = fut.result(timeout=max(1.0, float(online_timeout_s)))
            except FutTimeout:
                log.debug("minnano bio timeout %s", display)
                online = None
    except Exception as e:  # noqa: BLE001
        log.debug("minnano bio failed %s: %s", display, e)
        online = None

    if online and _bio_has_body(online):
        _cache_put(names, online)
        return online

    if db_bio:
        _cache_put(names, db_bio)
        return db_bio

    return _finalize({"source": "", "sourceUrl": map_url or ""})
