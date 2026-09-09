"""出站 HTTP：curl-impersonate + 面板代理 + FlareSolverr（对齐 MDCS）。"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from . import settings_store
from .db import data_dir

log = logging.getLogger(__name__)

# 线程级：补全关掉「包含过盾」时，禁止自适应源遇盾后再打 FlareSolverr
_tls = threading.local()


def set_thread_allow_flare(allowed: bool) -> None:
    _tls.allow_flare = bool(allowed)


def thread_allow_flare() -> bool:
    return bool(getattr(_tls, "allow_flare", True))


_DEFAULT_FLARE_PORT = 8191
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
# curl-impersonate（curl_cffi）浏览器指纹；站点拉页优先
_CURL_IMPERSONATE = "chrome"
_DEFAULT_CLEARANCE_TTL_MS = 45 * 60 * 1000
# 对齐 MDCS：单共享 session 可闲置较久；负载靠 monitor 回收控制
_SESSION_IDLE_MS = 25 * 60 * 1000
_FLARE_MIN_GAP_MS = 120
_FLARE_BUSY_GAP_MS = 250
_FLARE_MONITOR_INTERVAL_MS = 30_000
_FLARE_MAX_SESSIONS_WARN = 1
_FLARE_MAX_SESSIONS_CRITICAL = 2
_BLOCKED_RE = re.compile(
    r"Just a moment|cf-browser-verification|Attention Required|"
    r"Edge IP Restricted|Cloudflare has blocked|403 ERROR|"
    r"The request could not be satisfied|Access Denied|"
    r"Please enable cookies|banned your access|禁止了你的訪問|異常行為|"
    r"Web server is returning an unknown error|520:\s*Web server",
    re.I,
)
# 色花堂等 Discuz 名言/R18 拦截页：var safeid=… → cookie `_safe`
_SAFEID_RE = re.compile(r"safeid\s*=\s*['\"]([^'\"]+)['\"]", re.I)
_R18_HOST_HINT_RE = re.compile(r"(?:^|\.)sehuatang\.(?:net|org)$", re.I)

_soft_cookie_lock = threading.Lock()
# host → "safe=1; _safe=…" 等非 CF 软门 cookie（进程内复用）
_soft_cookies_by_host: dict[str, str] = {}

_clearance_lock = threading.Lock()
_clearance_by_host: dict[str, dict[str, Any]] = {}
_clearance_loaded = False
_persist_timer: threading.Timer | None = None

_flare_lock = threading.Lock()
_shared_session: dict[str, Any] | None = None  # id, proxyUrl, lastUsedAt
_last_flare_finished_at = 0.0
_flare_queue_depth = 0
_flare_traffic_ok = 0
_flare_traffic_err = 0
_flare_monitor_timer: threading.Timer | None = None
_flare_monitor_ticking = False
_flare_monitor_started = False

_host_gates: dict[str, threading.Lock] = {}
_host_gates_mu = threading.Lock()


def normalize_proxy_url(raw: str | None) -> str:
    """裸 host:port → http://；非法则空串。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = f"http://{s}"
    s = s.rstrip("/")
    parsed = urlparse(s)
    if parsed.scheme not in ("http", "https", "socks4", "socks5") or not parsed.netloc:
        return ""
    return s


def normalize_flaresolverr_url(raw: str | None) -> str:
    """FlareSolverr 基址，如 http://127.0.0.1:8191（不含 /v1）。"""
    s = str(raw or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = f"http://{s}"
    s = s.rstrip("/")
    if s.lower().endswith("/v1"):
        s = s[:-3].rstrip("/")
    parsed = urlparse(s)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return s


def _library_raw() -> dict[str, Any]:
    raw = settings_store.get_setting(settings_store.LIBRARY_KEY) or {}
    return raw if isinstance(raw, dict) else {}


def resolve_scrape_proxy_url() -> str:
    """仅在面板启用且填写代理时使用；否则直连。"""
    raw = _library_raw()
    enabled = raw.get("proxyEnabled")
    if enabled is None:
        enabled = raw.get("proxy_enabled")
    hit = normalize_proxy_url(
        str(raw.get("proxyUrl") or raw.get("proxy_url") or "")
    )
    if hit:
        if enabled is False or enabled == 0 or enabled == "0" or enabled == "false":
            return ""
        return hit
    legacy = settings_store.get_setting("scrape") or {}
    if isinstance(legacy, dict):
        leg_enabled = legacy.get("proxyEnabled")
        if leg_enabled is None:
            leg_enabled = legacy.get("proxy_enabled")
        if leg_enabled is False or leg_enabled == 0 or leg_enabled == "0" or leg_enabled == "false":
            return ""
        return normalize_proxy_url(
            str(legacy.get("proxyUrl") or legacy.get("proxy_url") or "")
        )
    return ""


def resolve_flaresolverr_url() -> str:
    """面板启用且填写 FlareSolverr 时返回基址；否则空。"""
    raw = _library_raw()
    enabled = raw.get("flareSolverrEnabled")
    if enabled is None:
        enabled = raw.get("flare_solverr_enabled")
    hit = normalize_flaresolverr_url(
        str(
            raw.get("flareSolverrUrl")
            or raw.get("flare_solverr_url")
            or raw.get("flaresolverrUrl")
            or ""
        )
    )
    if not hit:
        return ""
    if enabled is False or enabled == 0 or enabled == "0" or enabled == "false":
        return ""
    return hit


def httpx_client(**kwargs: Any) -> httpx.Client:
    """创建出站客户端；面板启用代理才走代理，否则直连。"""
    proxy = resolve_scrape_proxy_url()
    opts: dict[str, Any] = {"trust_env": False, "follow_redirects": True}
    opts.update(kwargs)
    if proxy:
        opts["proxy"] = proxy
    return httpx.Client(**opts)


def looks_blocked_html(html: str | None) -> bool:
    s = str(html or "")
    if len(s) < 400:
        return True
    return bool(_BLOCKED_RE.search(s[:4000]))


def is_r18_safe_shell(html: str | None) -> bool:
    """色花堂名言/R18 软门（短页 + safeid / static/safe）。"""
    s = str(html or "")
    if not s or len(s) >= 12_000:
        return False
    lowered = s.lower()
    return "var safeid" in s or "static/safe/" in lowered


def extract_safeid(html: str | None) -> str:
    m = _SAFEID_RE.search(html or "")
    return (m.group(1).strip() if m else "") or ""


def _remember_soft_cookies(url: str, cookie_header: str) -> None:
    host = _host_key(url)
    header = str(cookie_header or "").strip()
    if not host or not header:
        return
    with _soft_cookie_lock:
        prev = _soft_cookies_by_host.get(host) or ""
        merged = merge_cookie_headers(prev, header)
        if merged:
            _soft_cookies_by_host[host] = merged


def _cached_soft_cookies(url: str) -> str:
    host = _host_key(url)
    if not host:
        return ""
    with _soft_cookie_lock:
        return str(_soft_cookies_by_host.get(host) or "")


def _sehuatang_like_host(host: str) -> bool:
    h = (host or "").lower().lstrip(".")
    return bool(_R18_HOST_HINT_RE.search(h))


_JAVBUS_HOST_RE = re.compile(r"(?:^|\.)(?:javbus|seejav)\b", re.I)

# 对齐 MDCS flaresolverr NEVER_REGISTER_FLARE_RE：稳定 curl/代理源，勿吸入过盾通道
_NEVER_FLARE_HOST_RE = re.compile(
    r"(?:^|\.)("
    r"madouqu|madou\.club|theporndb|javbus|seejav|caribbeancom|"
    r"jav321|freejavbt|libredmm|contents\.fc2|dmm\.co\.jp|xchina|iqq[0-9]"
    r")\b",
    re.I,
)


def _javbus_like_host(host: str) -> bool:
    """JavBus 走 curl/代理即可，禁止 FlareSolverr 过盾。"""
    h = (host or "").lower().lstrip(".")
    return bool(_JAVBUS_HOST_RE.search(h))


def _skip_flare_host(host: str) -> bool:
    """这些站 curl（+ 站点 Cookie）即可，勿进 Flare 队列（对齐 MDCS）。"""
    h = (host or "").lower().lstrip(".")
    return (
        _sehuatang_like_host(host)
        or _javbus_like_host(host)
        or bool(_NEVER_FLARE_HOST_RE.search(h))
    )


# 最近一次 curl/httpx 未采纳原因（供错误文案；按 host）
_last_http_miss: dict[str, dict[str, Any]] = {}
_last_http_miss_lock = threading.Lock()


def _note_http_miss(url: str, *, status: int | None = None, reason: str = "") -> None:
    host = _host_key(url)
    if not host:
        return
    with _last_http_miss_lock:
        _last_http_miss[host] = {
            "status": status,
            "reason": reason,
            "at": time.time(),
        }


def _take_http_miss(url: str) -> dict[str, Any] | None:
    host = _host_key(url)
    if not host:
        return None
    with _last_http_miss_lock:
        return _last_http_miss.pop(host, None)


def _ensure_safe_gate_cookies(url: str, cookie_header: str | None) -> str:
    """色花堂类主机默认带 safe=1，并合并进程内 _safe。"""
    merged = merge_cookie_headers(cookie_header, _cached_soft_cookies(url))
    host = _host_key(url)
    if _sehuatang_like_host(host):
        lower = f"; {merged.lower()}; "
        if "safe=" not in lower:
            merged = merge_cookie_headers(merged, "safe=1")
    return merged


def normalize_access(access: str | None) -> str:
    a = str(access or "").strip().lower()
    if a == "proxy_flare":
        return "proxy_flare"
    # 仅 curl/代理，永不 Flare（javbus 等）
    if a in {"proxy_only", "proxy_curl", "curl", "direct"}:
        return "proxy_only"
    return "proxy_adaptive"


def _host_key(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _with_host_gate(host: str):
    key = host or "_"
    with _host_gates_mu:
        lock = _host_gates.get(key)
        if lock is None:
            lock = threading.Lock()
            _host_gates[key] = lock
    return lock


def _clearance_store_path() -> Path:
    return data_dir() / "meta" / "cf-clearance.json"


def _ensure_clearance_loaded() -> None:
    global _clearance_loaded
    if _clearance_loaded:
        return
    with _clearance_lock:
        if _clearance_loaded:
            return
        path = _clearance_store_path()
        try:
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                hosts = raw.get("hosts") if isinstance(raw, dict) else None
                now = int(time.time() * 1000)
                n = 0
                if isinstance(hosts, dict):
                    for host, hit in hosts.items():
                        if not isinstance(hit, dict):
                            continue
                        cookie = str(hit.get("cookieHeader") or "").strip()
                        exp = int(hit.get("expiresAt") or 0)
                        if not cookie or exp <= now:
                            continue
                        _clearance_by_host[str(host).lower()] = {
                            "cookieHeader": cookie,
                            "userAgent": str(hit.get("userAgent") or ""),
                            "expiresAt": exp,
                            "preferFlare": bool(hit.get("preferFlare")),
                        }
                        n += 1
                if n:
                    log.info("loaded %s cf-clearance host(s) from disk", n)
        except Exception as e:
            log.warning("cf-clearance load failed: %s", e)
        _clearance_loaded = True


def _persist_clearance_to_disk() -> None:
    path = _clearance_store_path()
    try:
        now = int(time.time() * 1000)
        hosts: dict[str, Any] = {}
        with _clearance_lock:
            for host, hit in _clearance_by_host.items():
                if int(hit.get("expiresAt") or 0) > now:
                    hosts[host] = hit
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "hosts": hosts},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("cf-clearance persist failed: %s", e)


def _schedule_persist_clearance() -> None:
    global _persist_timer
    with _clearance_lock:
        if _persist_timer is not None:
            _persist_timer.cancel()
        _persist_timer = threading.Timer(0.25, _persist_clearance_to_disk)
        _persist_timer.daemon = True
        _persist_timer.start()


def _flush_persist_clearance() -> None:
    global _persist_timer
    with _clearance_lock:
        if _persist_timer is not None:
            _persist_timer.cancel()
            _persist_timer = None
    _persist_clearance_to_disk()


def get_cached_clearance(url: str) -> dict[str, str] | None:
    _ensure_clearance_loaded()
    key = _host_key(url)
    if not key:
        return None
    with _clearance_lock:
        hit = _clearance_by_host.get(key)
        if not hit:
            return None
        if int(time.time() * 1000) >= int(hit.get("expiresAt") or 0):
            _clearance_by_host.pop(key, None)
            _schedule_persist_clearance()
            return None
        return {
            "cookieHeader": str(hit.get("cookieHeader") or ""),
            "userAgent": str(hit.get("userAgent") or ""),
            "preferFlare": bool(hit.get("preferFlare")),
        }


def clear_cached_clearance(url_or_host: str | None = None) -> None:
    _ensure_clearance_loaded()
    with _clearance_lock:
        if not url_or_host:
            _clearance_by_host.clear()
        else:
            key = _host_key(url_or_host) if "://" in url_or_host else str(url_or_host).lower()
            if key:
                _clearance_by_host.pop(key, None)
    _schedule_persist_clearance()


def _cookies_to_header(cookies: list[dict[str, Any]]) -> str:
    mapping: dict[str, str] = {}
    for c in cookies:
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        mapping[name] = str(c.get("value") if c.get("value") is not None else "")
    return "; ".join(f"{k}={v}" for k, v in mapping.items())


def _clearance_expiry(cookies: list[dict[str, Any]]) -> int:
    now = int(time.time() * 1000)
    soonest = now + _DEFAULT_CLEARANCE_TTL_MS
    for c in cookies:
        exp = c.get("expires")
        try:
            exp_n = float(exp)
        except (TypeError, ValueError):
            continue
        if exp_n <= 0:
            continue
        ms = int(exp_n if exp_n > 1e12 else exp_n * 1000)
        if ms <= now:
            continue
        soonest = min(soonest, ms)
    return max(now + 60_000, soonest - 120_000)


def remember_clearance(
    url: str,
    cookies: list[dict[str, Any]],
    user_agent: str,
    *,
    prefer_flare: bool | None = None,
) -> None:
    _ensure_clearance_loaded()
    key = _host_key(url)
    header = _cookies_to_header(cookies)
    if not key or not header:
        return
    with _clearance_lock:
        prev = _clearance_by_host.get(key) or {}
        prefer = (
            bool(prefer_flare)
            if prefer_flare is not None
            else bool(prev.get("preferFlare"))
        )
        _clearance_by_host[key] = {
            "cookieHeader": header,
            "userAgent": user_agent or "",
            "expiresAt": _clearance_expiry(cookies),
            "preferFlare": prefer,
        }
    _flush_persist_clearance()


def mark_prefer_flare(url: str, prefer: bool = True) -> None:
    """curl 无法吃下 Flare 凭证时，后续直接走 Flare 会话，避免每次再烧 curl→全量过盾。"""
    _ensure_clearance_loaded()
    key = _host_key(url)
    if not key:
        return
    with _clearance_lock:
        hit = _clearance_by_host.get(key)
        if not hit:
            return
        if bool(hit.get("preferFlare")) == bool(prefer):
            return
        hit["preferFlare"] = bool(prefer)
    _schedule_persist_clearance()


def merge_cookie_headers(*parts: str | None) -> str:
    mapping: dict[str, str] = {}
    for raw in parts:
        for part in str(raw or "").split(";"):
            idx = part.find("=")
            if idx <= 0:
                continue
            name = part[:idx].strip()
            value = part[idx + 1 :].strip()
            if name:
                mapping[name] = value
    return "; ".join(f"{k}={v}" for k, v in mapping.items())


def _cookie_domain_for_url(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return ""
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) >= 2:
        return f".{'.'.join(parts[-2:])}"
    return host


def _cookie_header_to_fs_cookies(
    cookie_header: str | None, target_url: str | None = None
) -> list[dict[str, str]] | None:
    raw = str(cookie_header or "").strip()
    if not raw:
        return None
    domain = _cookie_domain_for_url(target_url) if target_url else ""
    out: list[dict[str, str]] = []
    for part in raw.split(";"):
        idx = part.find("=")
        if idx <= 0:
            continue
        name = part[:idx].strip()
        value = part[idx + 1 :].strip()
        if not name:
            continue
        item: dict[str, str] = {"name": name, "value": value}
        if domain:
            item["domain"] = domain
            item["path"] = "/"
        out.append(item)
    return out or None


def _flare_api(flare_base: str, body: dict[str, Any], timeout_ms: int) -> dict[str, Any]:
    endpoint = f"{flare_base.rstrip('/')}/v1"
    with httpx.Client(
        timeout=httpx.Timeout(timeout_ms / 1000 + 2, connect=8.0),
        trust_env=False,
    ) as client:
        r = client.post(endpoint, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"FlareSolverr HTTP {r.status_code}")
    data = r.json() if r.content else {}
    if not isinstance(data, dict):
        raise RuntimeError("FlareSolverr 响应无效")
    if str(data.get("status") or "").lower() != "ok":
        msg = str(data.get("message") or data.get("status") or "unknown")
        raise RuntimeError(f"FlareSolverr 失败：{msg}")
    return data


def _destroy_session(flare_base: str, session_id: str) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    try:
        # 短超时：卡死的 Chrome 绝不能拖住整条过盾队列
        _flare_api(flare_base, {"cmd": "sessions.destroy", "session": sid}, 1200)
        log.info("flare session destroy %s…", sid[:8])
    except Exception as e:
        log.warning("flare session destroy fail %s…: %s", sid[:8], e)


def _destroy_session_bg(flare_base: str, session_id: str) -> None:
    """后台销毁，不占用 _flare_lock。"""
    sid = str(session_id or "").strip()
    if not sid or not flare_base:
        return
    threading.Thread(
        target=_destroy_session,
        args=(flare_base, sid),
        name=f"flare-destroy-{sid[:8]}",
        daemon=True,
    ).start()


def _note_flare_request(ok: bool) -> None:
    global _flare_traffic_ok, _flare_traffic_err
    if ok:
        _flare_traffic_ok += 1
    else:
        _flare_traffic_err += 1


def get_flare_traffic_stats() -> dict[str, Any]:
    ok = _flare_traffic_ok
    err = _flare_traffic_err
    total = ok + err
    return {
        "ok": ok,
        "err": err,
        "sample": total,
        "errorRate": (err / total) if total else 0.0,
        "queueDepth": _flare_queue_depth,
    }


def get_shared_session_id() -> str | None:
    hit = _shared_session
    return str(hit["id"]) if hit and hit.get("id") else None


def list_flare_sessions(flare_base: str | None = None) -> list[str]:
    base = normalize_flaresolverr_url(flare_base) if flare_base else resolve_flaresolverr_url()
    if not base:
        return []
    data = _flare_api(base, {"cmd": "sessions.list"}, 10000)
    sessions = data.get("sessions") if isinstance(data.get("sessions"), list) else []
    return [str(s).strip() for s in sessions if str(s or "").strip()]


def recycle_flare_sessions(*, keep_owned: bool = False) -> dict[str, Any]:
    """回收 FS Chrome 会话。list/destroy 在锁外，避免卡住拉页。"""
    global _shared_session
    base = resolve_flaresolverr_url()
    if not base:
        return {"destroyed": 0, "kept": None, "sessionsBefore": 0}
    owned = get_shared_session_id()
    try:
        remote = list_flare_sessions(base)
    except Exception:
        remote = [owned] if owned else []
    to_destroy = [
        sid for sid in remote if not (keep_owned and owned and sid == owned)
    ]
    with _flare_lock:
        if not keep_owned:
            _shared_session = None
        elif owned and owned not in remote:
            _shared_session = None
    for sid in to_destroy:
        _destroy_session_bg(base, sid)
    log.info(
        "flare recycle destroyed=%s keepOwned=%s owned=%s",
        len(to_destroy),
        keep_owned,
        (owned or "-")[:8],
    )
    return {
        "destroyed": len(to_destroy),
        "kept": owned if keep_owned else None,
        "sessionsBefore": len(remote),
    }


def release_flare_session(reason: str = "release") -> None:
    """进程退出 / 停机：关掉本进程持有的 shared Chrome。"""
    global _shared_session
    with _flare_lock:
        hit = _shared_session
        _shared_session = None
    if not hit:
        return
    base = resolve_flaresolverr_url()
    if not base:
        return
    log.info("flare session release (%s) %s…", reason, str(hit.get("id") or "")[:8])
    _destroy_session_bg(base, str(hit.get("id") or ""))


def _flare_monitor_tick() -> None:
    global _flare_monitor_ticking
    if _flare_monitor_ticking:
        return
    _flare_monitor_ticking = True
    try:
        # 有过盾请求在排队时，本轮不抢回收
        if _flare_queue_depth > 0:
            return
        base = resolve_flaresolverr_url()
        if not base:
            return
        try:
            remote = list_flare_sessions(base)
        except Exception as e:
            log.warning("flare-monitor list failed: %s", e)
            return
        owned = get_shared_session_id()
        orphans = [sid for sid in remote if not owned or sid != owned]
        traffic = get_flare_traffic_stats()

        if orphans:
            log.info(
                "flare-monitor orphans=%s total=%s owned=%s → recycle keepOwned",
                len(orphans),
                len(remote),
                (owned or "-")[:8],
            )
            recycle_flare_sessions(keep_owned=True)
            return

        if len(remote) >= _FLARE_MAX_SESSIONS_CRITICAL:
            log.info(
                "flare-monitor critical sessions=%s → recycle keepOwned=false",
                len(remote),
            )
            recycle_flare_sessions(keep_owned=False)
            return

        if len(remote) > _FLARE_MAX_SESSIONS_WARN:
            log.info(
                "flare-monitor warn sessions=%s → recycle keepOwned",
                len(remote),
            )
            recycle_flare_sessions(keep_owned=True)
            return

        if traffic["sample"] >= 5 and float(traffic["errorRate"]) >= 0.55:
            log.info(
                "flare-monitor high errorRate=%.2f sample=%s → recycle keepOwned",
                traffic["errorRate"],
                traffic["sample"],
            )
            recycle_flare_sessions(keep_owned=True)
    except Exception as e:
        log.warning("flare-monitor tick failed: %s", e)
    finally:
        _flare_monitor_ticking = False


def _schedule_flare_monitor() -> None:
    global _flare_monitor_timer
    if not _flare_monitor_started:
        return
    _flare_monitor_timer = threading.Timer(
        _FLARE_MONITOR_INTERVAL_MS / 1000.0, _flare_monitor_loop
    )
    _flare_monitor_timer.daemon = True
    _flare_monitor_timer.start()


def _flare_monitor_loop() -> None:
    _flare_monitor_tick()
    _schedule_flare_monitor()


def start_flare_monitor() -> None:
    """API 启动时开启：定时清孤儿 session、会话数超阈回收。"""
    global _flare_monitor_started
    if _flare_monitor_started:
        return
    _flare_monitor_started = True
    log.info(
        "flare-monitor started interval=%sms warn=%s critical=%s",
        _FLARE_MONITOR_INTERVAL_MS,
        _FLARE_MAX_SESSIONS_WARN,
        _FLARE_MAX_SESSIONS_CRITICAL,
    )
    # 首跳延迟，避开启动尖峰
    t = threading.Timer(8.0, _flare_monitor_loop)
    t.daemon = True
    t.start()


def stop_flare_monitor() -> None:
    global _flare_monitor_started, _flare_monitor_timer
    _flare_monitor_started = False
    if _flare_monitor_timer is not None:
        _flare_monitor_timer.cancel()
        _flare_monitor_timer = None
    release_flare_session("shutdown")


def _ensure_shared_session(flare_base: str, proxy_url: str) -> tuple[str, bool]:
    """返回 (session_id, created)。调用方已持有 _flare_lock。"""
    global _shared_session
    now = int(time.time() * 1000)
    hit = _shared_session
    if (
        hit
        and hit.get("proxyUrl") == proxy_url
        and now - int(hit.get("lastUsedAt") or 0) < _SESSION_IDLE_MS
    ):
        hit["lastUsedAt"] = now
        return str(hit["id"]), False
    if hit:
        old = str(hit.get("id") or "")
        _shared_session = None
        if old:
            _destroy_session_bg(flare_base, old)
    # 孤儿清理交给 monitor，勿在锁内同步 destroy/list
    created = _flare_api(flare_base, {"cmd": "sessions.create"}, 20000)
    sid = str(created.get("session") or "").strip()
    if not sid:
        raise RuntimeError("flaresolverr sessions.create empty")
    _shared_session = {
        "id": sid,
        "proxyUrl": proxy_url,
        "lastUsedAt": now,
    }
    log.info("flare session create session=%s…", sid[:8])
    return sid, True


@dataclass
class FlareFetchResult:
    html: str
    final_url: str
    cookie_header: str = ""
    user_agent: str = ""


def flaresolverr_request(
    url: str,
    *,
    max_timeout_ms: int = 60000,
    referer: str | None = None,
    cookie: str | None = None,
    use_proxy: bool = True,
    no_session_retry: bool = False,
    wait_in_seconds: int = 0,
) -> tuple[str, str]:
    """经 FlareSolverr 拉页。返回 (html, final_url)。兼容旧调用。"""
    hit = flaresolverr_request_full(
        url,
        max_timeout_ms=max_timeout_ms,
        referer=referer,
        cookie=cookie,
        use_proxy=use_proxy,
        no_session_retry=no_session_retry,
        wait_in_seconds=wait_in_seconds,
    )
    return hit.html, hit.final_url


def flaresolverr_request_full(
    url: str,
    *,
    max_timeout_ms: int = 60000,
    referer: str | None = None,
    cookie: str | None = None,
    use_proxy: bool = True,
    no_session_retry: bool = False,
    wait_in_seconds: int = 0,
) -> FlareFetchResult:
    """过盾：同进程复用 FS session；写回 cf_clearance。全局单飞 + 间隔，保护 FS 负载。"""
    global _shared_session, _flare_queue_depth, _last_flare_finished_at
    base = resolve_flaresolverr_url()
    if not base:
        raise RuntimeError("未启用 FlareSolverr")

    max_timeout = max(10000, int(max_timeout_ms))
    proxy = resolve_scrape_proxy_url() if use_proxy else ""
    wait_s = max(0, min(30, int(wait_in_seconds or 0)))
    host = _host_key(url) or "default"
    pad = (
        min(4000, max(1500, int(max_timeout * 0.15)))
        if no_session_retry
        else min(15000, max(3000, max_timeout))
    )

    def run_once(session_id: str | None, reused: bool) -> FlareFetchResult:
        body: dict[str, Any] = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": max_timeout,
        }
        if session_id:
            body["session"] = session_id
        if proxy:
            body["proxy"] = {"url": proxy}
        if wait_s > 0:
            body["waitInSeconds"] = wait_s
        cookies = _cookie_header_to_fs_cookies(cookie, url)
        if cookies:
            body["cookies"] = cookies
        if referer:
            body["headers"] = {"Referer": referer}
        t0 = time.time()
        try:
            data = _flare_api(base, body, max_timeout + pad)
            sol = data.get("solution") if isinstance(data.get("solution"), dict) else {}
            html = str(sol.get("response") or "")
            if not html:
                raise RuntimeError("flaresolverr empty response")
            st = sol.get("status")
            if isinstance(st, int) and st >= 400:
                raise RuntimeError(f"flaresolverr target HTTP {st}")
            sol_cookies = sol.get("cookies") if isinstance(sol.get("cookies"), list) else []
            ua = str(sol.get("userAgent") or "").strip()
            final = str(sol.get("url") or url).strip() or url
            remember_clearance(final or url, [c for c in sol_cookies if isinstance(c, dict)], ua)
            ms = int((time.time() - t0) * 1000)
            log.info(
                "flare %s host=%s%s %sms",
                "reuse" if reused else "fresh",
                host,
                f" wait={wait_s}s" if wait_s else "",
                ms,
            )
            if looks_blocked_html(html) and len(html) < 12000:
                raise RuntimeError("FlareSolverr 仍遇 CF 盾")
            if len(html) < 200:
                raise RuntimeError("FlareSolverr 返回页面过短")
            _note_flare_request(True)
            return FlareFetchResult(
                html=html,
                final_url=final,
                cookie_header=_cookies_to_header([c for c in sol_cookies if isinstance(c, dict)]),
                user_agent=ua,
            )
        except Exception:
            _note_flare_request(False)
            raise

    _flare_queue_depth += 1
    try:
        with _flare_lock:
            gap_ms = (
                _FLARE_BUSY_GAP_MS if _flare_queue_depth > 3 else _FLARE_MIN_GAP_MS
            )
            wait = _last_flare_finished_at + gap_ms / 1000.0 - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                if no_session_retry or wait_s > 0:
                    if wait_s > 0:
                        return run_once(None, False)
                    hit = _shared_session
                    if (
                        hit
                        and hit.get("proxyUrl") == proxy
                        and int(time.time() * 1000)
                        - int(hit.get("lastUsedAt") or 0)
                        < _SESSION_IDLE_MS
                    ):
                        hit["lastUsedAt"] = int(time.time() * 1000)
                        try:
                            return run_once(str(hit["id"]), True)
                        except Exception:
                            pass
                    return run_once(None, False)

                try:
                    sid, created = _ensure_shared_session(base, proxy)
                    try:
                        return run_once(sid, not created)
                    except Exception as e:
                        dead = (_shared_session or {}).get("id") or sid
                        _shared_session = None
                        if dead:
                            _destroy_session_bg(base, str(dead))
                        log.warning(
                            "flare session request fail host=%s → destroy+no-session: %s",
                            host,
                            e,
                        )
                        return run_once(None, False)
                except Exception:
                    return run_once(None, False)
            finally:
                _last_flare_finished_at = time.time()
    finally:
        _flare_queue_depth = max(0, _flare_queue_depth - 1)


def flaresolverr_ping(base_url: str | None = None) -> dict[str, Any]:
    """探测 FlareSolverr 是否可达。"""
    base = normalize_flaresolverr_url(base_url) if base_url is not None else resolve_flaresolverr_url()
    if not base:
        raise RuntimeError("请先填写 FlareSolverr 地址")
    data = _flare_api(base, {"cmd": "sessions.list"}, 10000)
    return {
        "ok": True,
        "version": data.get("version") or data.get("startTimestamp"),
        "sessions": data.get("sessions") if isinstance(data.get("sessions"), list) else [],
    }


@dataclass
class FetchPageResult:
    html: str
    final_url: str
    via: str = "curl"  # curl | flare | httpx


def _timeout_seconds(timeout: httpx.Timeout | float | None, default: float = 22.0) -> float:
    if timeout is None:
        return default
    if isinstance(timeout, httpx.Timeout):
        return float(getattr(timeout, "read", None) or getattr(timeout, "timeout", None) or default)
    return float(timeout)


def curl_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: Any = None,
    json_body: Any = None,
    proxy: str | None = None,
    use_panel_proxy: bool = True,
    timeout: httpx.Timeout | float | None = 22.0,
    verify: bool = True,
    allow_redirects: bool = True,
) -> Any:
    """站点出站：curl-impersonate（curl_cffi）。失败抛异常。"""
    from curl_cffi import requests as creq

    if use_panel_proxy:
        use_proxy = proxy if proxy is not None else resolve_scrape_proxy_url()
    else:
        use_proxy = proxy or ""
    kwargs: dict[str, Any] = {
        "headers": headers or {},
        "timeout": _timeout_seconds(timeout),
        "allow_redirects": allow_redirects,
        "verify": verify,
        "impersonate": _CURL_IMPERSONATE,
    }
    if use_proxy:
        kwargs["proxy"] = use_proxy
    if json_body is not None:
        kwargs["json"] = json_body
    if data is not None:
        kwargs["data"] = data
    return creq.request(method.upper(), url, **kwargs)


def _accept_http_body(
    url: str,
    *,
    status: int,
    html: str,
    final_url: str,
    via: str,
) -> tuple[str, str, str] | None:
    """对齐 MDCS：≥400 默认丢弃；但 404 站点模板页交给上层解析「未找到」。"""
    if looks_blocked_html(html):
        _note_http_miss(url, status=status, reason="blocked")
        return None
    if status >= 400:
        # 软 404：完整站点 404 页（如 JavBus），供 parse 报「未找到影片」
        if status == 404 and len(html) >= 400:
            return html, final_url, via
        _note_http_miss(url, status=status, reason="http_error")
        return None
    if len(html) < 200:
        _note_http_miss(url, status=status, reason="thin")
        return None
    return html, final_url, via


def _http_get_once(
    url: str,
    *,
    headers: dict[str, str],
    timeout: httpx.Timeout,
    proxy: str | None,
    verify: bool,
) -> tuple[str, str, str] | None:
    """优先 curl-impersonate；不可用时回退 httpx。返回 (html, final_url, via)。"""
    try:
        from curl_cffi import requests as creq

        kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": _timeout_seconds(timeout),
            "allow_redirects": True,
            "verify": verify,
            "impersonate": _CURL_IMPERSONATE,
        }
        if proxy:
            kwargs["proxy"] = proxy
        r = creq.get(url, **kwargs)
        status = int(getattr(r, "status_code", 500) or 500)
        html = str(getattr(r, "text", "") or "")
        final = str(getattr(r, "url", "") or url)
        hit = _accept_http_body(
            url, status=status, html=html, final_url=final, via="curl"
        )
        if hit:
            return hit
    except Exception as e:
        log.debug("curl-impersonate miss %s: %s", _host_key(url), e)

    opts: dict[str, Any] = {
        "timeout": timeout,
        "trust_env": False,
        "follow_redirects": True,
        "verify": verify,
    }
    if proxy:
        opts["proxy"] = proxy
    try:
        with httpx.Client(**opts) as client:
            r2 = client.get(url, headers=headers)
        status = int(r2.status_code or 500)
        html = r2.text or ""
        hit = _accept_http_body(
            url,
            status=status,
            html=html,
            final_url=str(r2.url or url),
            via="httpx",
        )
        if hit:
            return hit
    except Exception:
        _note_http_miss(url, reason="exception")
    return None


def fetch_page(
    url: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    user_agent: str | None = None,
    access: str | None = None,
    timeout: httpx.Timeout | float | None = None,
    fresh_probe: bool = False,
    source_id: str | None = None,
) -> FetchPageResult:
    """
    对齐 MDCS fetchPage 阶梯：
    clearance + curl-impersonate →（adaptive 短探）→ FlareSolverr。
    """
    host = _host_key(url)
    with _with_host_gate(host):
        return _fetch_page_unlocked(
            url,
            referer=referer,
            cookie=cookie,
            user_agent=user_agent,
            access=access,
            timeout=timeout,
            fresh_probe=fresh_probe,
            source_id=source_id,
        )


def _fetch_page_unlocked(
    url: str,
    *,
    referer: str | None = None,
    cookie: str | None = None,
    user_agent: str | None = None,
    access: str | None = None,
    timeout: httpx.Timeout | float | None = None,
    fresh_probe: bool = False,
    source_id: str | None = None,
) -> FetchPageResult:
    del source_id  # 预留：按源覆盖 access
    host = _host_key(url)
    mode = normalize_access(access)
    if isinstance(timeout, httpx.Timeout):
        to = timeout
    elif timeout is not None:
        to = httpx.Timeout(float(timeout), connect=min(8.0, float(timeout)))
    else:
        to = httpx.Timeout(22.0, connect=8.0)

    flare_url = resolve_flaresolverr_url()
    flare_on = bool(flare_url)
    cached = None if fresh_probe else get_cached_clearance(url)
    merged_cookie = _ensure_safe_gate_cookies(
        url,
        merge_cookie_headers(cookie, (cached or {}).get("cookieHeader")),
    )
    ua = (
        str(user_agent or "").strip()
        or (cached or {}).get("userAgent")
        or _DEFAULT_UA
    )
    has_clearance = bool((cached or {}).get("cookieHeader"))
    prefer_flare = bool((cached or {}).get("preferFlare"))

    headers: dict[str, str] = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
    }
    if referer:
        headers["Referer"] = referer
    if merged_cookie:
        headers["Cookie"] = merged_cookie

    proxy = resolve_scrape_proxy_url()
    # 对齐 MDCS download.fetchPage：
    # - 全源优先 impersonate curl（含 proxy_flare），失败再 Flare
    # - 勿因 proxy_flare / preferFlare 跳过 curl（否则「全部走 Flare」）
    # - NEVER_FLARE / proxy_only：禁过盾
    skip_direct = False
    no_flare = (
        mode == "proxy_only"
        or _skip_flare_host(host)
        or not thread_allow_flare()
    )
    if no_flare:
        prefer_flare = False
        flare_on = False

    def _apply_r18_bypass(html: str) -> bool:
        """命中名言壳则写 _safe，刷新 Cookie 头；成功返回 True。"""
        nonlocal merged_cookie
        if not is_r18_safe_shell(html):
            return False
        safeid = extract_safeid(html)
        if not safeid:
            return False
        soft = f"safe=1; _safe={safeid}"
        _remember_soft_cookies(url, soft)
        merged_cookie = merge_cookie_headers(merged_cookie, soft)
        headers["Cookie"] = merged_cookie
        log.info("r18-safeid host=%s → _safe set", _host_key(url))
        return True

    def _accept_or_bypass_r18(
        html: str, final_url: str, via: str, *, opts: dict[str, Any], direct_to: httpx.Timeout
    ) -> FetchPageResult | None:
        if not is_r18_safe_shell(html):
            return FetchPageResult(html=html, final_url=final_url, via=via)
        if not _apply_r18_bypass(html):
            return None
        hit2 = _http_get_once(
            url,
            headers=headers,
            timeout=direct_to,
            proxy=opts.get("proxy"),
            verify=bool(opts.get("verify")),
        )
        if not hit2:
            return None
        html2, final2, via2 = hit2
        if is_r18_safe_shell(html2):
            return None
        return FetchPageResult(html=html2, final_url=final2, via=via2)

    last_err: Exception | None = None
    if not skip_direct:
        attempts: list[dict[str, Any]] = []
        if proxy:
            attempts.append({"proxy": proxy, "verify": False})
            attempts.append({"proxy": proxy, "verify": True})
        attempts.append({"proxy": None, "verify": False})
        attempts.append({"proxy": None, "verify": True})
        seen: set[str] = set()
        for opts in attempts:
            key = repr(sorted(opts.items()))
            if key in seen:
                continue
            seen.add(key)
            # 对齐 MDCS curlOpts：至少 15s（有 clearance 12s+），勿把 adaptive 压成 8s 导致误进 Flare
            base_read = float(getattr(to, "read", 22) or 22)
            if has_clearance:
                direct_to = httpx.Timeout(max(12.0, base_read), connect=8.0)
            else:
                direct_to = httpx.Timeout(max(15.0, base_read), connect=8.0)
            hit = _http_get_once(
                url,
                headers=headers,
                timeout=direct_to,
                proxy=opts.get("proxy"),
                verify=bool(opts.get("verify")),
            )
            if hit:
                html, final_url, via = hit
                accepted = _accept_or_bypass_r18(
                    html, final_url, via, opts=opts, direct_to=direct_to
                )
                if accepted:
                    if has_clearance:
                        mark_prefer_flare(url, False)
                        log.info(
                            "clearance-curl-ok host=%s %sb via=%s",
                            _host_key(url),
                            len(accepted.html),
                            accepted.via,
                        )
                    else:
                        log.info(
                            "curl-ok host=%s %sb via=%s",
                            _host_key(url),
                            len(accepted.html),
                            accepted.via,
                        )
                    if no_flare:
                        mark_prefer_flare(url, False)
                    return accepted
        miss = _take_http_miss(url)
        st = int((miss or {}).get("status") or 0)
        if st == 404:
            last_err = RuntimeError("未找到影片 (HTTP 404)")
        elif st in (401, 403):
            last_err = RuntimeError(f"拒绝访问 (HTTP {st})")
        elif st >= 500:
            last_err = RuntimeError(f"站点错误 (HTTP {st})")
        elif (miss or {}).get("reason") == "blocked":
            last_err = RuntimeError("curl/直连遇盾")
        else:
            last_err = RuntimeError("curl/直连失败或遇盾")
        # 404/5xx 不是盾：不要 sticky preferFlare，也不必为 404 烧 Flare
        if has_clearance and not no_flare and (miss or {}).get("reason") == "blocked":
            mark_prefer_flare(url, True)
            log.info("clearance-curl-miss host=%s → preferFlare", _host_key(url))

    # HTTP 404：直接失败，禁止回落 Flare（对齐「未找到」语义）
    if isinstance(last_err, RuntimeError) and "HTTP 404" in str(last_err):
        raise last_err

    if flare_on:
        log.info(
            "curl-miss → flare host=%s access=%s err=%s",
            _host_key(url),
            mode,
            str(last_err)[:80] if last_err else "",
        )
        try:
            flare_timeout = int(
                max(
                    35000 if fresh_probe else 45000,
                    (getattr(to, "read", None) or 22) * 1000,
                )
            )
            # 有磁盘 clearance 时一并注入，避免年龄门/二次挑战
            flare_cookie = merged_cookie or None
            result = flaresolverr_request_full(
                url,
                max_timeout_ms=flare_timeout,
                referer=referer,
                cookie=flare_cookie,
                no_session_retry=fresh_probe,
            )
            if is_r18_safe_shell(result.html) and _apply_r18_bypass(result.html):
                result = flaresolverr_request_full(
                    url,
                    max_timeout_ms=flare_timeout,
                    referer=referer,
                    cookie=merged_cookie or None,
                    no_session_retry=fresh_probe,
                )
            if is_r18_safe_shell(result.html):
                raise RuntimeError("flare 仍停在 R18 名言壳")
            # 刚过盾成功：默认下次仍可先试 curl；若本次因 preferFlare 跳过 curl，保持标记
            if prefer_flare or skip_direct:
                mark_prefer_flare(url, True)
            return FetchPageResult(
                html=result.html,
                final_url=result.final_url,
                via="flare",
            )
        except Exception as e:
            last_err = e
            log.warning("flare fallback %s: %s", url, e)

    raise last_err or RuntimeError(f"拉页失败 {url}")
