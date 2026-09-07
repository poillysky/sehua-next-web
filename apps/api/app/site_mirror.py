"""站点镜像发现（对齐 mdcs siteMirror / iqqtvMirror）。

流程：seeds → 探测 → 磁盘缓存 → 全局优先使用最新落地基址。
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .db import data_dir

log = logging.getLogger(__name__)

TTL_MS = 6 * 60 * 60 * 1000
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(18.0, connect=6.0)

# —— profiles（对齐 mdcs SITE_MIRROR_PROFILES / iqqtvMirror ENTRY_SEEDS）——

_JAVBUS_SEEDS = (
    "https://www.javbus.com",
    "https://www.seejav.me",
    "https://seejav.me",
)

# mdcs iqqtvMirror ENTRY_SEEDS（探测序；存盘为 root，展示拼 /cn）
_IQQTV_SEEDS = (
    "https://iqqk4.quest",
    "https://www.iqqk4.quest",
    "https://iqq5.xyz",
    "https://www.iqq5.xyz",
    "https://iqq6.xyz",
)

_SEVENMM_SEEDS = (
    "https://7mmtv.sx",
    "https://www.7mmtv.sx",
    "https://7mmtv.com",
    "https://7mm.tv",
)

_MADOU_SEEDS = (
    "https://madou.club",
    "https://www.madou.club",
)

# mdcs miss_av；missav.com 已查封改 ThisAV，探测时仍过滤
_MISSAV_SEEDS = (
    "https://missav123.com",
    "https://www.missav123.com",
    "https://missav.ws",
    "https://missav.live",
    "https://missav.ai",
    "https://missav.li",
)

_IQQTV_REDIRECT_HOSTS = frozenset(
    {
        "iqq5.xyz",
        "iqq6.xyz",
        "iqqtv.net",
        "www.iqqtv.net",
    }
)

# missav.com 已被查封并改成 ThisAV，不可当 MissAV 落地
_MISSAV_DEAD_HOSTS = frozenset({"missav.com", "thisav.com"})

_memory: dict[str, dict[str, Any]] = {}
_resolving: dict[str, bool] = {}


def _store_path() -> Path:
    return data_dir() / "site-mirrors.json"


def _origin(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    try:
        u = urlparse(s)
        if not u.netloc:
            return ""
        return f"{u.scheme or 'https'}://{u.netloc}".rstrip("/")
    except Exception:
        return ""


def origin(raw: str) -> str:
    """公开：归一化为 scheme://host。"""
    return _origin(raw)


def _host(raw: str) -> str:
    try:
        h = urlparse(_origin(raw) or raw).hostname or ""
        return h.lower().replace("www.", "", 1) if h.lower().startswith("www.") else h.lower()
    except Exception:
        return ""


def _load_disk() -> None:
    path = _store_path()
    if not path.is_file():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        now = int(time.time() * 1000)
        mirrors = raw.get("mirrors") if isinstance(raw, dict) else {}
        if not isinstance(mirrors, dict):
            return
        for sid, ent in mirrors.items():
            if not isinstance(ent, dict):
                continue
            base = _origin(str(ent.get("baseUrl") or ""))
            exp = int(ent.get("expiresAt") or 0)
            if not base or exp <= now:
                continue
            if sid == "iqqtv" and _is_iqqtv_redirect_seed(base):
                continue
            _memory[str(sid)] = {
                "baseUrl": base,
                "discoveredFrom": ent.get("discoveredFrom"),
                "updatedAt": ent.get("updatedAt"),
                "expiresAt": exp,
            }
    except Exception as e:
        log.warning("site-mirrors load: %s", e)


def _persist() -> None:
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "mirrors": dict(_memory)}
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("site-mirrors write: %s", e)


def _looks_blocked(html: str) -> bool:
    from .outbound_http import looks_blocked_html

    return looks_blocked_html(html)


def _looks_javbus(html: str) -> bool:
    """必须有真实列表卡片；停放页/空壳（仅域名文案）不算。"""
    return javbus_content_count(html) >= 3


def javbus_content_count(html: str) -> int:
    if not html or len(html) < 1200:
        return 0
    if _looks_blocked(html) and len(html) < 12000:
        return 0
    return len(re.findall(r'class=["\'][^"\']*movie-box', html, re.I))


def _looks_iqqtv(html: str) -> bool:
    """必须有真实作品链（/h/ 或番号详情），空壳/跳转页不算。"""
    return iqqtv_content_count(html) >= 3


def iqqtv_content_count(html: str) -> int:
    """与列表解析对齐：player.php?uuid= 或 /h/{id} 均算真实作品。"""
    if not html or len(html) < 1200:
        return 0
    if _looks_blocked(html) and len(html) < 8000:
        return 0
    skip = {
        "hot",
        "new",
        "top",
        "index",
        "page",
        "search",
        "menu",
        "list",
        "tag",
        "actor",
        "makers",
        "genre",
    }
    ids: set[str] = set()
    for m in re.finditer(
        r"player\.php\?[^\"'\s>]*uuid=([A-Za-z0-9_-]{4,40})",
        html,
        re.I,
    ):
        ids.add(m.group(1).lower())
        if len(ids) >= 20:
            return len(ids)
    for m in re.finditer(
        r'href=["\']([^"\']*/(?:cn/)?h/([A-Za-z0-9][A-Za-z0-9_-]{1,40}))(?:\.html)?/?["\']',
        html,
        re.I,
    ):
        slug = m.group(2).lower()
        if slug in skip or (slug.isdigit() and len(slug) < 2):
            continue
        ids.add(slug)
        if len(ids) >= 20:
            break
    return len(ids)


def _looks_sevenmm(html: str) -> bool:
    return sevenmm_content_count(html) >= 3


def sevenmm_content_count(html: str) -> int:
    if not html or len(html) < 1200:
        return 0
    if _looks_blocked(html):
        return 0
    # 真实列表：*_content/{id}/CODE(.html)
    return len(set(re.findall(r"_content/\d+/[A-Za-z0-9_-]+", html, re.I)))


def _looks_madou(html: str) -> bool:
    return madou_content_count(html) >= 3


def madou_content_count(html: str) -> int:
    if not html or len(html) < 800:
        return 0
    if _looks_blocked(html):
        return 0
    # WordPress 文章卡片
    arts = len(re.findall(r"<article\b", html, re.I))
    if arts >= 3:
        return arts
    # 兜底：entry-title 链接（镜像域名不一）
    titles = len(re.findall(r'class=["\'][^"\']*entry-title', html, re.I))
    if titles >= 3:
        return titles
    return 0


def _looks_missav(html: str) -> bool:
    return missav_content_count(html) >= 3


def _is_missav_dead_host(root: str) -> bool:
    return _host(root) in _MISSAV_DEAD_HOSTS


def is_missav_dead_host(root: str) -> bool:
    return _is_missav_dead_host(root)


def missav_content_count(html: str) -> int:
    if not html or len(html) < 2000:
        return 0
    if _looks_blocked(html):
        return 0
    # 查封后的 ThisAV / 占位页
    if re.search(r"thisav|page-feature", html, re.I) and not re.search(
        r"missav", html, re.I
    ):
        return 0
    skip = re.compile(
        r"/(search|genres?|makers?|actresses?|directors?|studios?|labels?|series|"
        r"lists?|login|register|page|tags?|type|filter|new|release|uncensored|"
        r"fc2|chinese|madou|today|weekly|monthly)(?:/|$)",
        re.I,
    )
    n = 0
    seen: set[str] = set()
    for m in re.finditer(
        r'href=["\']([^"\']+/(?:dm\d+/)?cn/([a-z0-9][a-z0-9-]{2,80}))/?["\']',
        html,
        re.I,
    ):
        full, slug = m.group(1), m.group(2).lower()
        if skip.search(full) or slug in seen:
            continue
        if re.match(
            r"^(new|release|uncensored-leak|uncensored|fc2|chinese-av|madou|"
            r"chinese-subtitle|today|weekly|monthly)$",
            slug,
        ):
            continue
        seen.add(slug)
        n += 1
        if n >= 20:
            break
    return n


def _is_iqqtv_redirect_seed(root: str) -> bool:
    return _host(root) in {h.replace("www.", "") for h in _IQQTV_REDIRECT_HOSTS} or _host(
        root
    ) in _IQQTV_REDIRECT_HOSTS


def is_iqqtv_redirect_seed(root: str) -> bool:
    return _is_iqqtv_redirect_seed(root)


def _is_iqqtv_family(host: str) -> bool:
    h = (host or "").lower().replace("www.", "")
    if h in _IQQTV_REDIRECT_HOSTS or h.replace("www.", "") in {
        x.replace("www.", "") for x in _IQQTV_REDIRECT_HOSTS
    }:
        return True
    # 镜像域名变化快：凡带 iqq 的主机均视为同族（如 iqqn.work / iqqk4.quest）
    if "iqq" in h:
        return True
    return bool(re.match(r"^iqqk?\d+\.(xyz|quest|net|tv|cc|top|fun|work)$", h) or h.startswith("iqqtv."))


def _extract_redirect_targets(html: str, final_url: str) -> list[str]:
    out: list[str] = []

    def push(raw: str | None) -> None:
        o = _origin(str(raw or "").strip())
        if o and o not in out:
            out.append(o)

    push(final_url)
    text = str(html or "")
    patterns = [
        r'http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\'>\s]+)',
        r'content=["\'][^"\']*url=([^"\'>\s]+)["\'][^>]*http-equiv=["\']refresh["\']',
        r"(?:window\.)?location(?:\.href|\.replace)?\s*=\s*['\"](https?://[^'\"]+)['\"]",
        r"location\.replace\(\s*['\"](https?://[^'\"]+)['\"]",
        r"(?:window\.)?location\.assign\(\s*['\"](https?://[^'\"]+)['\"]",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.I):
            push(m.group(1))
    return out


def _fetch(
    url: str,
    *,
    referer: str | None = None,
    source_id: str | None = None,
    fresh_probe: bool = False,
) -> tuple[str, str]:
    """探测拉页：走 outbound fetch_page（clearance → 直连 → Flare）。"""
    from .outbound_http import fetch_page

    cookie = None
    if "javbus" in url.lower() or "seejav" in url.lower():
        try:
            from . import makers_settings

            cookie = makers_settings.javbus_cookie() or None
        except Exception:
            pass
    access = "proxy_adaptive"
    if source_id:
        try:
            from . import makers_settings

            access = makers_settings.provider_access(source_id)
        except Exception:
            pass
    page = fetch_page(
        url,
        referer=referer,
        cookie=cookie,
        access=access,
        timeout=_TIMEOUT,
        fresh_probe=fresh_probe,
        source_id=source_id,
    )
    return page.html, page.final_url


def remember(source_id: str, base_url: str, *, discovered_from: str | None = None) -> str | None:
    sid = str(source_id or "").strip().lower()
    base = _origin(base_url)
    if not sid or not base:
        return None
    if sid == "iqqtv":
        if _is_iqqtv_redirect_seed(base):
            return None
        if not _is_iqqtv_family(_host(base)):
            return None
    if sid == "javbus":
        if not re.search(r"javbus|seejav", _host(base), re.I):
            return None
    if sid == "7mmtv":
        if not re.search(r"7mm", _host(base), re.I):
            return None
    if sid == "madou":
        if not re.search(r"madou\.club", _host(base), re.I):
            return None
    if sid == "missav":
        if _is_missav_dead_host(base):
            return None
        if not re.search(r"missav", _host(base), re.I):
            return None
    prev = _memory.get(sid)
    now = int(time.time() * 1000)
    if prev and prev.get("baseUrl") == base and int(prev.get("expiresAt") or 0) > now:
        return base
    ent = {
        "baseUrl": base,
        "discoveredFrom": discovered_from or (prev or {}).get("discoveredFrom"),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "expiresAt": now + TTL_MS,
    }
    _memory[sid] = ent
    _persist()
    # 兼容旧 iqqtv-mirror.json
    if sid == "iqqtv":
        try:
            legacy = data_dir() / "iqqtv-mirror.json"
            legacy.write_text(
                json.dumps(
                    {
                        "baseUrl": base,
                        "discoveredFrom": ent.get("discoveredFrom"),
                        "updatedAt": ent["updatedAt"],
                        "expiresAt": time.time() + TTL_MS / 1000,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
    log.info("site mirror %s → %s", sid, base)
    return base


def remember_from_final_url(source_id: str, final_url: str) -> str | None:
    return remember(source_id, final_url, discovered_from=final_url)


def invalidate(source_id: str) -> None:
    sid = str(source_id or "").strip().lower()
    _memory.pop(sid, None)
    _persist()


def get_cached(source_id: str) -> str | None:
    sid = str(source_id or "").strip().lower()
    if not _memory and _store_path().is_file():
        _load_disk()
    ent = _memory.get(sid)
    if not ent:
        # 兼容旧 iqqtv 缓存
        if sid == "iqqtv":
            try:
                path = data_dir() / "iqqtv-mirror.json"
                if path.is_file():
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    base = _origin(str(raw.get("baseUrl") or ""))
                    exp = float(raw.get("expiresAt") or 0)
                    # 旧文件 expiresAt 可能是秒
                    now_s = time.time()
                    now_ms = int(now_s * 1000)
                    if base and not _is_iqqtv_redirect_seed(base):
                        if exp > now_ms or exp > now_s:
                            remember("iqqtv", base, discovered_from=str(raw.get("discoveredFrom") or ""))
                            return base
            except Exception:
                pass
        return None
    if int(ent.get("expiresAt") or 0) <= int(time.time() * 1000):
        return None
    base = str(ent.get("baseUrl") or "")
    if sid == "iqqtv" and _is_iqqtv_redirect_seed(base):
        return None
    return base or None


def list_live() -> dict[str, str]:
    out: dict[str, str] = {}
    for sid in ("javbus", "iqqtv", "missav", "7mmtv", "madou"):
        u = get_cached(sid)
        if u:
            out[sid] = u
    return out


def _probe_javbus(seed: str) -> str | None:
    preferred = _origin(seed)
    if not preferred:
        return None
    try:
        html, final = _fetch(f"{preferred}/", referer=f"{preferred}/", source_id="javbus")
    except Exception as e:
        log.debug("javbus probe %s: %s", preferred, e)
        return None
    ordered = []
    for cand in [_origin(final), *_extract_redirect_targets(html, final), preferred]:
        o = _origin(cand)
        if o and o not in ordered:
            ordered.append(o)
    for cand in ordered:
        if not re.search(r"javbus|seejav", _host(cand), re.I):
            continue
        check_html, check_final = html, final
        if _origin(final) != cand:
            try:
                check_html, check_final = _fetch(f"{cand}/", referer=f"{cand}/", source_id="javbus")
            except Exception:
                continue
        if not _looks_javbus(check_html):
            continue
        return _origin(check_final) or cand
    return None


def _probe_iqqtv_root(seed: str) -> str | None:
    root = _origin(seed)
    if not root:
        return None
    try:
        html, final = _fetch(f"{root}/cn/", referer=f"{root}/cn/", source_id="iqqtv")
    except Exception as e:
        log.debug("iqqtv probe %s: %s", root, e)
        return None
    if not _looks_iqqtv(html):
        return None
    landed = _origin(final) or root
    if _is_iqqtv_redirect_seed(landed):
        # 入口跳转网关：再跟一次
        try:
            html2, final2 = _fetch(f"{landed}/cn/", referer=f"{landed}/cn/", source_id="iqqtv")
            if _looks_iqqtv(html2):
                landed2 = _origin(final2) or landed
                if not _is_iqqtv_redirect_seed(landed2):
                    return landed2
        except Exception:
            pass
        return None
    if landed != root:
        try:
            html2, final2 = _fetch(f"{landed}/cn/", referer=f"{landed}/cn/", source_id="iqqtv")
            if html2 and _looks_iqqtv(html2):
                return _origin(final2) or landed
        except Exception:
            pass
    return landed


def _probe_sevenmm(seed: str) -> str | None:
    root = _origin(seed)
    if not root:
        return None
    try:
        html, final = _fetch(f"{root}/zh/", referer=f"{root}/zh/", source_id="7mmtv")
    except Exception as e:
        log.debug("7mmtv probe %s: %s", root, e)
        return None
    if not _looks_sevenmm(html):
        return None
    landed = _origin(final) or root
    # 跟 meta/JS 跳转，日常直连落地站
    for cand in [_origin(final), *_extract_redirect_targets(html, final), root]:
        o = _origin(cand)
        if not o:
            continue
        check_html = html
        check_final = final
        if o != _origin(final):
            try:
                check_html, check_final = _fetch(f"{o}/zh/", referer=f"{o}/zh/", source_id="7mmtv")
            except Exception:
                continue
            if not _looks_sevenmm(check_html):
                continue
        return _origin(check_final) or o
    return landed if _looks_sevenmm(html) else None


def _probe_madou(seed: str) -> str | None:
    root = _origin(seed)
    if not root:
        return None
    try:
        html, final = _fetch(f"{root}/", referer=f"{root}/", source_id="madou")
    except Exception as e:
        log.debug("madou probe %s: %s", root, e)
        return None
    if not _looks_madou(html):
        return None
    for cand in [_origin(final), *_extract_redirect_targets(html, final), root]:
        o = _origin(cand)
        if not o:
            continue
        check_html = html
        check_final = final
        if o != _origin(final):
            try:
                check_html, check_final = _fetch(f"{o}/", referer=f"{o}/", source_id="madou")
            except Exception:
                continue
            if not _looks_madou(check_html):
                continue
        return _origin(check_final) or o
    return None


def _probe_missav(seed: str) -> str | None:
    root = _origin(seed)
    if not root or _is_missav_dead_host(root):
        return None
    try:
        html, final = _fetch(f"{root}/cn/", referer=f"{root}/cn/", source_id="missav")
    except Exception as e:
        log.debug("missav probe %s: %s", root, e)
        return None
    if not _looks_missav(html):
        return None
    for cand in [_origin(final), *_extract_redirect_targets(html, final), root]:
        o = _origin(cand)
        if not o or _is_missav_dead_host(o):
            continue
        check_html = html
        check_final = final
        if o != _origin(final):
            try:
                check_html, check_final = _fetch(f"{o}/cn/", referer=f"{o}/cn/", source_id="missav")
            except Exception:
                continue
            if not _looks_missav(check_html):
                continue
        landed = _origin(check_final) or o
        if _is_missav_dead_host(landed):
            continue
        return landed
    return None


def resolve(
    source_id: str,
    *,
    seeds: list[str] | tuple[str, ...] | None = None,
    force: bool = False,
) -> str:
    """解析可用基址；iqqtv 返回 root（不含 /cn）。"""
    sid = str(source_id or "").strip().lower()
    if not force:
        hit = get_cached(sid)
        if hit:
            return hit

    if sid == "javbus":
        preferred = list(seeds or ())
        try:
            from . import makers_settings

            preferred = list(makers_settings.javbus_bases()) + preferred
        except Exception:
            pass
        uniq: list[str] = []
        for s in [*preferred, *_JAVBUS_SEEDS]:
            o = _origin(s)
            if o and o not in uniq:
                uniq.append(o)
        for seed in uniq:
            hit = _probe_javbus(seed)
            if hit:
                remember("javbus", hit, discovered_from=seed)
                return hit
        raise RuntimeError("javbus mirror unavailable")

    if sid == "iqqtv":
        preferred = list(seeds or ())
        try:
            from . import makers_settings

            preferred = list(makers_settings.iqqtv_seeds()) + preferred
        except Exception:
            pass
        uniq = []
        for s in [*preferred, *_IQQTV_SEEDS]:
            o = _origin(s)
            if o and o not in uniq:
                uniq.append(o)
        for seed in uniq:
            hit = _probe_iqqtv_root(seed)
            if hit:
                remember("iqqtv", hit, discovered_from=seed)
                return hit
        raise RuntimeError("iqqtv mirror unavailable")

    if sid == "7mmtv":
        preferred = list(seeds or ())
        try:
            from . import makers_settings

            preferred = list(makers_settings.sevenmm_seeds()) + preferred
        except Exception:
            pass
        uniq = []
        for s in [*preferred, *_SEVENMM_SEEDS]:
            o = _origin(s)
            if o and o not in uniq:
                uniq.append(o)
        for seed in uniq:
            hit = _probe_sevenmm(seed)
            if hit:
                remember("7mmtv", hit, discovered_from=seed)
                return hit
        raise RuntimeError("7mmtv mirror unavailable")

    if sid == "madou":
        preferred = list(seeds or ())
        try:
            from . import makers_settings

            preferred = list(makers_settings.madou_seeds()) + preferred
        except Exception:
            pass
        uniq = []
        for s in [*preferred, *_MADOU_SEEDS]:
            o = _origin(s)
            if o and o not in uniq:
                uniq.append(o)
        for seed in uniq:
            hit = _probe_madou(seed)
            if hit:
                remember("madou", hit, discovered_from=seed)
                return hit
        raise RuntimeError("madou mirror unavailable")

    if sid == "missav":
        preferred = list(seeds or ())
        try:
            from . import makers_settings

            preferred = list(makers_settings.missav_seeds()) + preferred
        except Exception:
            pass
        uniq = []
        for s in [*preferred, *_MISSAV_SEEDS]:
            o = _origin(s)
            if o and o not in uniq:
                uniq.append(o)
        for seed in uniq:
            hit = _probe_missav(seed)
            if hit:
                remember("missav", hit, discovered_from=seed)
                return hit
        raise RuntimeError("missav mirror unavailable")

    raise ValueError(f"unknown source: {sid}")


def ordered_bases(source_id: str, configured: list[str] | tuple[str, ...]) -> list[str]:
    """拉页候选：设置里的 activeBase（最快站）优先，再跟配置种子。"""
    sid = str(source_id or "").strip().lower()
    live = get_cached(sid)
    if not live:
        try:
            from . import makers_settings

            cfg = makers_settings.resolve_makers_catalog()
            if sid == "javbus":
                live = _origin(str(cfg["javbus"].get("activeBase") or ""))
            elif sid == "iqqtv":
                raw = str(cfg["iqqtv"].get("activeBase") or "")
                live = _origin(re.sub(r"/cn/?$", "", raw, flags=re.I))
            elif sid == "missav":
                raw = str(cfg["missav"].get("activeBase") or "")
                live = _origin(re.sub(r"/cn/?$", "", raw, flags=re.I))
            elif sid == "7mmtv":
                live = _origin(str(cfg["7mmtv"].get("activeBase") or ""))
            elif sid == "madou":
                live = _origin(str(cfg["madou"].get("activeBase") or ""))
            if live:
                remember(sid, live, discovered_from=live)
        except Exception:
            live = None
    if not live:
        try:
            live = resolve(sid, seeds=configured, force=False)
        except Exception:
            live = None
    out: list[str] = []
    if live:
        out.append(live)
    for u in configured:
        o = _origin(u)
        if o and o not in out:
            out.append(o)
    return out or [_origin(u) for u in configured if _origin(u)]


def active_public(source_id: str) -> dict[str, Any]:
    sid = str(source_id or "").strip().lower()
    ent = _memory.get(sid) if get_cached(sid) else None
    base = get_cached(sid)
    if not base:
        return {"activeBase": "", "cached": False}
    display = f"{base}/cn" if sid in ("iqqtv", "missav") else base
    return {
        "activeBase": display,
        "root": base,
        "cached": True,
        "updatedAt": (ent or {}).get("updatedAt"),
        "discoveredFrom": (ent or {}).get("discoveredFrom"),
    }


_load_disk()
