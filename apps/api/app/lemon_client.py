"""磁力柠檬：Playwright 代搜 / 取磁力。

默认用 Playwright 自带 Chromium（NAS/Docker 无 Edge/Chrome 也能跑）。
本机可设 LEMON_BROWSER_CHANNEL=chrome|msedge，或 LEMON_BROWSER_EXECUTABLE=绝对路径。
"""

from __future__ import annotations

import logging
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, TypeVar
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DOMAIN_API = os.environ.get(
    "LEMON_DOMAIN_API",
    "https://us.lessapi.com/pa/domain/current/wN0EjL4QjL5UTMucjNt40TNVETtEjd",
)
# 公告域 lemonun 常进「地址安全检查」；优先镜像站
FALLBACK_HOSTS = (
    "lemonrv.top",
    "lemonyc.top",
    "lemonyu.top",
    "lemonxx.top",
    "lemonkz.top",
    "lemonex.top",
    "lemonun.top",
    "lemonuo.top",
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 过盾 Cookie / storage 落盘，下次复用（默认 6h）
_SESSION_TTL = float(os.environ.get("LEMON_SESSION_TTL", str(6 * 3600)))
_SESSION_PATH = Path(
    os.environ.get("LEMON_SESSION_FILE", "").strip()
    or (Path(__file__).resolve().parents[3] / "data" / "lemon-session.json")
)

# Playwright sync API 必须在同一线程；FastAPI 会把 sync 路由丢进线程池
_job_q: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any], queue.Queue]] = (
    queue.Queue()
)
_worker_ready = threading.Event()
_worker_lock = threading.Lock()
_pw = None
_browser = None
_context = None
_page = None
_warm_keyword: str | None = None
_base_url: str | None = None
_base_at = 0.0

_search_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_magnet_cache: dict[str, tuple[float, str]] = {}
SEARCH_TTL = 90.0
MAGNET_TTL = 3600.0
DOMAIN_TTL = 3600.0

T = TypeVar("T")


class LemonError(RuntimeError):
    pass


def _pw_worker() -> None:
    _worker_ready.set()
    while True:
        fn, args, kwargs, out_q = _job_q.get()
        try:
            out_q.put((True, fn(*args, **kwargs)))
        except BaseException as e:  # noqa: BLE001 — 原样传回调用方
            out_q.put((False, e))


def _ensure_worker() -> None:
    with _worker_lock:
        if _worker_ready.is_set():
            return
        threading.Thread(target=_pw_worker, name="lemon-playwright", daemon=True).start()
        _worker_ready.wait(timeout=10)


_op_lock = threading.Lock()
_JOB_TIMEOUT = float(os.environ.get("LEMON_JOB_TIMEOUT", "90"))
_CHALLENGE_WAIT_S = int(os.environ.get("LEMON_CHALLENGE_WAIT", "35"))


def _on_pw_thread(
    fn: Callable[..., T],
    *args: Any,
    timeout: float | None = None,
    **kwargs: Any,
) -> T:
    """把 Playwright 操作派发到专用线程执行（带超时，避免卡死线程池）。"""
    _ensure_worker()
    if threading.current_thread().name == "lemon-playwright":
        return fn(*args, **kwargs)
    out_q: queue.Queue = queue.Queue(maxsize=1)
    _job_q.put((fn, args, kwargs, out_q))
    wait = _JOB_TIMEOUT if timeout is None else timeout
    try:
        ok, val = out_q.get(timeout=wait)
    except queue.Empty as e:
        # 工作线程可能仍堵在浏览器里：强制拆掉，释放后续请求
        logger.error("lemon playwright job timeout (%.0fs), reset browser", wait)
        try:
            _shutdown_browser_unlocked()
        except Exception:
            pass
        raise LemonError("柠檬响应超时，请稍后重试") from e
    if not ok:
        raise val
    return val


def _with_op_lock(fn: Callable[[], T]) -> T:
    """同时只跑一个柠檬任务，避免搜索/翻页/解析互相排队卡死。"""
    if not _op_lock.acquire(blocking=False):
        raise LemonError("柠檬忙碌中，请稍候再试")
    try:
        return fn()
    finally:
        _op_lock.release()


def _headed() -> bool:
    return os.environ.get("LEMON_HEADED", "").strip() in {"1", "true", "True"}


def _launch_args() -> list[str]:
    return [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--no-sandbox",
        "--disable-gpu",
    ]


def _launch_browser(pw: Any) -> Any:
    """优先环境变量指定浏览器；否则用自带 Chromium（适合 NAS）。"""
    headless = not _headed()
    args = _launch_args()
    executable = os.environ.get("LEMON_BROWSER_EXECUTABLE", "").strip()
    if executable:
        logger.info("lemon browser executable=%s", executable)
        return pw.chromium.launch(
            executable_path=executable,
            headless=headless,
            args=args,
        )

    channel = os.environ.get("LEMON_BROWSER_CHANNEL", "").strip().lower()
    candidates: list[str | None]
    if channel in {"chrome", "msedge", "chrome-beta", "msedge-beta"}:
        candidates = [channel, None]
    elif channel == "chromium":
        candidates = [None]
    elif sys.platform == "win32":
        # Windows：本机 Chrome/Edge 更容易过 Cloudflare；色花同机实测亦然
        candidates = ["chrome", "msedge", None]
    else:
        # NAS/Linux：自带 Chromium → Chrome → Edge
        candidates = [None, "chrome", "msedge"]

    last_err: Exception | None = None
    for ch in candidates:
        try:
            if ch:
                logger.info("lemon browser channel=%s", ch)
                return pw.chromium.launch(channel=ch, headless=headless, args=args)
            logger.info("lemon browser=bundled chromium")
            return pw.chromium.launch(headless=headless, args=args)
        except Exception as e:
            last_err = e
            logger.warning("lemon browser launch failed (%s): %s", ch or "chromium", e)
    raise LemonError(
        f"无法启动浏览器（NAS 请先 playwright install chromium）: {last_err}"
    )


def _looks_like_gate_html(html: str, url: str = "") -> bool:
    u = (url or "").lower()
    h = html or ""
    if "/feo/" in u or "imkaiseng.life" in u:
        return True
    if 'meta[name="rdata"]' in h.replace(" ", "") or 'name="rdata"' in h:
        return True
    if "地址安全检查" in h or "安全检查" in (h[:800] if h else ""):
        return True
    return False


def _decode_gate_rdata(html: str) -> list[str]:
    """解析跳转页 meta[name=rdata] → 真实镜像列表。"""
    import base64
    import json

    m = re.search(
        r'<meta[^>]+name=["\']rdata["\'][^>]+content=["\']([^"\']+)["\']',
        html or "",
        re.I,
    )
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']rdata["\']',
            html or "",
            re.I,
        )
    if not m:
        return []
    raw = (m.group(1) or "").strip()
    if not raw:
        return []
    try:
        decoded = base64.b64decode(raw[::-1]).decode("utf-8", errors="ignore").strip()
        data = json.loads(decoded)
        urls = data.get("urls") if isinstance(data, dict) else None
        out: list[str] = []
        for u in urls or []:
            s = str(u or "").strip()
            if s.startswith("http"):
                out.append(s.rstrip("/") + "/")
        return out
    except Exception as e:
        logger.warning("lemon gate rdata decode failed: %s", e)
        return []


def _probe_lemon_home(url: str, client: httpx.Client) -> bool:
    """首页是否已是柠檬搜索页（非跳转门禁）。"""
    try:
        r = client.get(url, headers={"User-Agent": UA})
        if r.status_code >= 400:
            return False
        html = r.text or ""
        if _looks_like_gate_html(html, str(r.url)):
            return False
        return (
            'name="keyword"' in html
            or "id=\"search-form\"" in html
            or "id='search-form'" in html
            or "/search" in html
        )
    except Exception:
        return False


def _candidate_hosts_from_api() -> list[str]:
    hosts: list[str] = []
    seen: set[str] = set()

    def push(host: str) -> None:
        h = (host or "").strip().lower().removeprefix("https://").removeprefix("http://")
        h = h.split("/")[0].strip()
        if not h or h in seen:
            return
        seen.add(h)
        hosts.append(h)

    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            r = client.get(DOMAIN_API, headers={"User-Agent": UA})
            r.raise_for_status()
            data = r.json()
            for group in data.get("domains") or []:
                for name in group.get("domains") or []:
                    push(str(name))
    except Exception as e:
        logger.warning("lemon domain api failed: %s", e)

    for h in FALLBACK_HOSTS:
        push(h)
    return hosts


def resolve_base_url(force: bool = False) -> str:
    global _base_url, _base_at
    now = time.time()
    if not force and _base_url and now - _base_at < DOMAIN_TTL:
        return _base_url

    picked = FALLBACK_HOSTS[0]
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            for host in _candidate_hosts_from_api():
                home = f"https://{host}/"
                if _probe_lemon_home(home, client):
                    picked = host
                    break
                # 公告域名若进门禁：解析 rdata 拿真实镜像
                try:
                    r = client.get(home, headers={"User-Agent": UA})
                    mirrors = _decode_gate_rdata(r.text or "")
                except Exception:
                    mirrors = []
                for mirror in mirrors:
                    if _probe_lemon_home(mirror, client):
                        picked = (
                            mirror.removeprefix("https://")
                            .removeprefix("http://")
                            .split("/")[0]
                        )
                        break
                else:
                    continue
                break
    except Exception as e:
        logger.warning("lemon resolve_base_url probe failed: %s", e)

    _base_url = f"https://{picked}"
    _base_at = now
    logger.info("lemon baseUrl=%s", _base_url)
    return _base_url


def _session_path() -> Path:
    return _SESSION_PATH


def _session_fresh() -> bool:
    p = _session_path()
    if not p.is_file():
        return False
    try:
        age = time.time() - p.stat().st_mtime
    except OSError:
        return False
    return age < _SESSION_TTL


def _clear_session() -> None:
    p = _session_path()
    try:
        if p.is_file():
            p.unlink()
            logger.info("lemon session cleared")
    except OSError as e:
        logger.warning("lemon session clear failed: %s", e)


def _persist_session(context: Any) -> None:
    """过盾成功后写入 Playwright storage_state，供下次 new_context 复用。"""
    if context is None:
        return
    p = _session_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        state = context.storage_state()
        cookies = state.get("cookies") if isinstance(state, dict) else None
        n = len(cookies) if isinstance(cookies, list) else 0
        # 无 Cookie 时不覆盖旧文件
        if n <= 0:
            return
        context.storage_state(path=str(p))
        logger.info("lemon session saved → %s (%s cookies)", p, n)
    except Exception as e:
        logger.warning("lemon session save failed: %s", e)


def _looks_like_challenge(url: str = "", html: str = "", title: str = "") -> bool:
    u = (url or "").lower()
    t = title or ""
    h = html or ""
    if "recaptcha" in u or "/challenge" in u or "cf-chl" in u:
        return True
    if "Bot Challenge" in t or "Just a moment" in t:
        return True
    head = h[:4000]
    return (
        "Checking your browser" in head
        or "Just a moment" in head
        or "cf-browser-verification" in head
        or "Recaptcha - Bot Challenge" in head
    )


def _page_snapshot(page: Any) -> tuple[str, str, str]:
    """读取 url/title/html；导航抖动时短暂重试。"""
    url = title = html = ""
    for _ in range(4):
        try:
            url = page.url or ""
            title = page.title() or ""
            html = page.content() or ""
            return url, title, html
        except Exception:
            page.wait_for_timeout(400)
    try:
        url = page.url or ""
    except Exception:
        pass
    return url, title, html


def _wait_past_challenge(page: Any, *, seconds: int | None = None) -> str:
    """等 Cloudflare / recaptcha 自动放行，返回最终 HTML。"""
    wait_s = _CHALLENGE_WAIT_S if seconds is None else max(1, int(seconds))
    url, title, html = _page_snapshot(page)
    if html.count("/detail/") > 0 and not _looks_like_challenge(url, html, title):
        return html
    if not _looks_like_challenge(url, html, title):
        # 已在搜索页但结果尚未渲染
        if "/search" in url and 'name="keyword"' in html:
            page.wait_for_timeout(800)
            return _page_snapshot(page)[2]
        return html

    # 旧会话失效：清掉再等本次过盾
    _clear_session()
    logger.info("lemon challenge wait up to %ss (%s)", wait_s, url[:120])
    cleared = False
    for i in range(wait_s):
        page.wait_for_timeout(1000)
        url, title, html = _page_snapshot(page)
        if html.count("/detail/") > 0 and not _looks_like_challenge(url, html, title):
            logger.info("lemon challenge cleared at %ss", i + 1)
            cleared = True
            break
        if not _looks_like_challenge(url, html, title) and (
            "/search" in url or 'name="keyword"' in html
        ):
            if html.count("/detail/") > 0 or "/search" in url:
                logger.info("lemon challenge cleared at %ss (search)", i + 1)
                cleared = True
                break
    if cleared:
        try:
            _persist_session(page.context)
        except Exception:
            pass
    return html


def _pass_entry_gate(page: Any) -> str | None:
    """若停在「地址安全检查」页：解析镜像并跳转到可用站。返回新 base 或 None。"""
    try:
        url = page.url or ""
        html = page.content() or ""
    except Exception:
        return None
    if not _looks_like_gate_html(html, url):
        return None

    mirrors = _decode_gate_rdata(html)
    if not mirrors:
        try:
            btn = page.query_selector("button.k, .k, #B")
            if btn:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
                    btn.click()
                page.wait_for_timeout(800)
        except Exception:
            pass
        try:
            page.wait_for_selector('input[name="keyword"]', timeout=12000)
        except Exception:
            pass
        return None

    # obfuscation 模式不会自动跳：直接 goto 可用镜像
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for mirror in mirrors:
            if not _probe_lemon_home(mirror, client):
                continue
            try:
                page.goto(mirror, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(600)
                page.wait_for_selector('input[name="keyword"]', timeout=12000)
                global _base_url, _base_at
                _base_url = mirror.rstrip("/")
                _base_at = time.time()
                logger.info("lemon gate bypass -> %s", _base_url)
                return _base_url
            except Exception as e:
                logger.warning("lemon mirror failed %s: %s", mirror, e)
    raise LemonError("柠檬入口被拦截，且镜像均不可用")


def _ensure_browser() -> Any:
    global _pw, _browser, _context, _page, _warm_keyword
    from playwright.sync_api import sync_playwright

    if _page is not None:
        return _page
    _pw = sync_playwright().start()
    _browser = _launch_browser(_pw)
    ctx_kwargs: dict[str, Any] = {
        "locale": "zh-CN",
        "user_agent": UA,
        "viewport": {"width": 1280, "height": 900},
    }
    if _session_fresh():
        sp = str(_session_path())
        ctx_kwargs["storage_state"] = sp
        logger.info("lemon session restore ← %s", sp)
    try:
        _context = _browser.new_context(**ctx_kwargs)
    except Exception as e:
        logger.warning("lemon session restore failed, fresh context: %s", e)
        _clear_session()
        ctx_kwargs.pop("storage_state", None)
        _context = _browser.new_context(**ctx_kwargs)
    _page = _context.new_page()
    _page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    _page.set_default_timeout(45000)
    _warm_keyword = None
    return _page


def _shutdown_browser_unlocked() -> None:
    global _pw, _browser, _context, _page, _warm_keyword
    try:
        if _context is not None:
            _context.close()
    except Exception:
        pass
    try:
        if _browser is not None:
            _browser.close()
    except Exception:
        pass
    try:
        if _pw is not None:
            _pw.stop()
    except Exception:
        pass
    _pw = _browser = _context = _page = None
    _warm_keyword = None


def shutdown_browser() -> None:
    def _run() -> None:
        _shutdown_browser_unlocked()

    try:
        # 热重载时绝不能等满 LEMON_JOB_TIMEOUT
        _on_pw_thread(_run, timeout=2.0)
    except Exception:
        try:
            _shutdown_browser_unlocked()
        except Exception:
            pass


def _reset_browser() -> None:
    _shutdown_browser_unlocked()
    _ensure_browser()


def search_url(base: str, keyword: str) -> str:
    return f"{base.rstrip('/')}/search?keyword={quote(keyword)}"


def parse_has_more(html: str, page: int) -> bool:
    """柠檬分页：.pagination a[onclick=searchWithPath(n)]。"""
    nums = [int(x) for x in re.findall(r"searchWithPath\((\d+)\)", html or "")]
    if not nums:
        return False
    return max(nums) > page


def _soup(html: str) -> Any:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def parse_search_html(html: str, base: str) -> list[dict[str, Any]]:
    soup = _soup(html)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in soup.select(".panel.panel-default .panel-title a[href*='/detail/']"):
        path = (a.get("href") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        title = a.get_text(" ", strip=True)
        panel = a.find_parent(
            "div",
            class_=lambda c: bool(c and "panel-default" in c),
        )
        footer = ""
        if panel is not None:
            foot_el = panel.select_one(".panel-footer")
            if foot_el is not None:
                footer = foot_el.get_text(" ", strip=True)
        size_m = re.search(r"文件大小:\s*(\S+(?:\s*[KMGT]?B)?)", footer)
        files_m = re.search(r"文件数量:\s*(\d+)", footer)
        date_m = re.search(r"收录时间:\s*([^\s]+)", footer)
        detail_url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
        items.append(
            {
                "title": title,
                "path": path,
                "detailUrl": detail_url,
                "sizeText": (size_m.group(1) if size_m else "") or "",
                "fileCount": int(files_m.group(1)) if files_m else None,
                "createdAt": (date_m.group(1) if date_m else "") or "",
                "magnet": None,
            }
        )
    return items


def _detail_slug(path: str) -> str:
    """柠檬详情第二段相对稳定；第一段会轮换。"""
    parts = [p for p in (path or "").split("/") if p]
    if len(parts) >= 3 and parts[0] == "detail":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "detail":
        return parts[1]
    return parts[-1] if parts else ""


_MAGNET_RE = re.compile(r"magnet:\?[^\s\"'<>]+", re.I)


def _normalize_magnets(raw: list[str] | None) -> list[str]:
    """去重并清洗；同一详情可能有多条 magnet。"""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        for m in _MAGNET_RE.findall(str(item or "")):
            link = m.strip().rstrip(".,;)]}>'\"")
            if not link.lower().startswith("magnet:"):
                continue
            key = link.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(link)
    return out


def _read_magnets_from_page(page: Any) -> list[str]:
    """抓取详情页全部磁力（#magnet / a[href] / 页面 HTML），不只第一条。"""
    try:
        page.wait_for_selector(
            "#magnet, a[href^='magnet:'], textarea[id*='magnet'], input[id*='magnet']",
            timeout=8000,
        )
    except Exception:
        pass
    try:
        raw = page.evaluate(
            """() => {
              const out = [];
              const push = (s) => {
                if (!s) return;
                const t = String(s);
                const re = /magnet:\\?[^\\s"'<>]+/gi;
                let m;
                while ((m = re.exec(t))) out.push(m[0]);
              };
              document
                .querySelectorAll(
                  '#magnet, textarea[id*="magnet"], input[id*="magnet"], textarea[class*="magnet"], [class*="magnet"]'
                )
                .forEach((el) => {
                  push(el.value || el.textContent || el.innerText || '');
                });
              document
                .querySelectorAll('a[href^="magnet:"]')
                .forEach((a) => push(a.getAttribute('href')));
              push(document.documentElement.innerHTML || '');
              return out;
            }"""
        )
    except Exception:
        raw = []
    magnets = _normalize_magnets(list(raw or []))
    if magnets:
        return magnets
    # 兜底：整页 HTML 再扫一遍
    try:
        html = page.content() or ""
    except Exception:
        html = ""
    return _normalize_magnets(_MAGNET_RE.findall(html))


def _find_slug_href(page: Any, slug: str) -> str | None:
    href = page.evaluate(
        """(slug) => {
          const links = Array.from(document.querySelectorAll('a[href*="/detail/"]'));
          const hit = links.find((a) => (a.getAttribute('href') || '').includes(slug));
          return hit ? hit.getAttribute('href') : null;
        }""",
        slug,
    )
    return (href or "").strip() or None


def _fresh_detail_path(page: Any, path: str) -> str:
    """在当前搜索页按 slug 找回最新 /detail/... 路径（不扫多页，避免卡死）。"""
    slug = _detail_slug(path)
    if not slug:
        return path
    return _find_slug_href(page, slug) or path


def _open_detail(page: Any, path: str) -> None:
    fresh = _fresh_detail_path(page, path)
    page.evaluate(f"location.href = {fresh!r}")
    try:
        page.wait_for_url("**/detail/**", timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(1200)


def _click_search_page(page: Any, page_num: int) -> None:
    """柠檬站内翻页：searchWithPath → 提交 #so-page。"""
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=25000):
            page.evaluate(
                """(p) => {
                  if (typeof searchWithPath === 'function') {
                    searchWithPath(p);
                    return;
                  }
                  const el = document.getElementById('so-page');
                  if (el) {
                    el.value = String(p);
                    const form = document.getElementById('search-form');
                    if (form) form.submit();
                  }
                }""",
                page_num,
            )
    except Exception:
        # 有的环境 submit 不触发 navigation 事件
        page.wait_for_timeout(800)
    page.wait_for_timeout(1200)


def _goto_search(page: Any, base: str, keyword: str, page_num: int = 1) -> str:
    global _warm_keyword
    page_num = max(1, int(page_num or 1))
    # 已在同关键词结果页：直接翻页（最快）
    if (
        _warm_keyword == keyword
        and "/search" in (page.url or "")
        and page_num > 1
        and page.query_selector("#so-page, .pagination") is not None
    ):
        _click_search_page(page, page_num)
        html = _wait_past_challenge(page, seconds=12)
        if html.count("/detail/") > 0:
            return html

    page.goto(base, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(400)
    bypassed = _pass_entry_gate(page)
    if bypassed:
        base = bypassed
    inp = page.query_selector('input[name="keyword"]')
    if inp is None:
        # 仍无搜索框：可能还在门禁或直链失败
        page.goto(base, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(500)
        bypassed = _pass_entry_gate(page)
        if bypassed:
            base = bypassed
        inp = page.query_selector('input[name="keyword"]')

    if inp is not None:
        inp.fill(keyword)
        # 第 N 页：提交前写入 so-page，避免先搜第 1 页再翻
        if page_num > 1:
            page.evaluate(
                """(p) => {
                  let el = document.getElementById('so-page');
                  if (!el) {
                    el = document.createElement('input');
                    el.type = 'hidden';
                    el.name = 'page';
                    el.id = 'so-page';
                    document.getElementById('search-form')?.appendChild(el);
                  }
                  el.value = String(p);
                }""",
                page_num,
            )
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                page.click('button[type="submit"]')
        except Exception:
            page.wait_for_timeout(800)
        html = _wait_past_challenge(page)
    else:
        # 无表单时再尝试直链；过盾中勿重复 goto（易 ERR_ABORTED）
        try:
            page.goto(search_url(base, keyword), wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("lemon direct search goto: %s", e)
        html = _wait_past_challenge(page)

    if html.count("/detail/") == 0:
        url, title, html2 = _page_snapshot(page)
        html = html2 or html
        if html.count("/detail/") == 0 and not _looks_like_challenge(url, html, title):
            # 非过盾但仍无结果：再试一次直链
            try:
                page.goto(search_url(base, keyword), wait_until="domcontentloaded", timeout=30000)
                html = _wait_past_challenge(page, seconds=20)
            except Exception as e:
                logger.warning("lemon search fallback goto: %s", e)
                html = _page_snapshot(page)[2]
        if page_num > 1 and html.count("/detail/") > 0:
            _click_search_page(page, page_num)
            html = _wait_past_challenge(page, seconds=12)

    if html.count("/detail/") == 0:
        url, title, _ = _page_snapshot(page)
        raise LemonError(f"柠檬搜索无结果或被拦截（{url} / {title}）")

    # 直链进的第 1 页再翻
    if page_num > 1:
        active = page.evaluate(
            """() => {
              const t = document.querySelector('.pagination li.active')?.innerText || '1';
              return Number(String(t).trim()) || 1;
            }"""
        )
        if int(active or 1) != page_num:
            _click_search_page(page, page_num)
            html = _wait_past_challenge(page, seconds=12)
        if html.count("/detail/") == 0:
            raise LemonError(f"柠檬第 {page_num} 页无结果")

    _warm_keyword = keyword
    # 成功结果页：刷新落盘（即使未触发 challenge 也更新 mtime / cookies）
    try:
        _persist_session(page.context)
    except Exception:
        pass
    return html


def _search_uncached(kw: str, page_num: int) -> dict[str, Any]:
    base = resolve_base_url()
    t0 = time.time()
    try:
        page = _ensure_browser()
        html = _goto_search(page, base, kw, page_num)
    except Exception as e:
        logger.warning("lemon search retry after reset: %s", e)
        _reset_browser()
        page = _ensure_browser()
        base = resolve_base_url(force=True)
        html = _goto_search(page, base, kw, page_num)
    items = parse_search_html(html, base)
    has_more = parse_has_more(html, page_num)
    return {
        "keyword": kw,
        "page": page_num,
        "source": "lemon",
        "baseUrl": base,
        "openUrl": search_url(base, kw),
        "items": items,
        "total": len(items),
        "hasMore": has_more,
        "costMs": int((time.time() - t0) * 1000),
    }


def search(keyword: str, *, page: int = 1, use_cache: bool = True) -> dict[str, Any]:
    kw = keyword.strip()
    if not kw:
        raise LemonError("关键词为空")
    if len(kw) > 80:
        raise LemonError("关键词过长")
    page_num = max(1, min(int(page or 1), 100))

    cache_key = f"{kw.lower()}|{page_num}"
    if use_cache:
        hit = _search_cache.get(cache_key)
        if hit and time.time() - hit[0] < SEARCH_TTL:
            return hit[1]

    def _run() -> dict[str, Any]:
        data = _on_pw_thread(_search_uncached, kw, page_num)
        _search_cache[cache_key] = (time.time(), data)
        return data

    return _with_op_lock(_run)


def _resolve_uncached(path: str, kw: str) -> dict[str, Any]:
    base = resolve_base_url()
    t0 = time.time()

    def _attempt(page: Any) -> list[str]:
        # 始终回到搜索页再按 slug 取最新详情路径（前缀会轮换）
        _goto_search(page, base, kw)
        _open_detail(page, path)
        if "/detail/" not in (page.url or ""):
            _goto_search(page, base, kw)
            _open_detail(page, path)
        magnets = _read_magnets_from_page(page)
        if not magnets:
            raise LemonError("详情页未找到磁力链接")
        try:
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_timeout(600)
        except Exception:
            pass
        return magnets

    page = _ensure_browser()
    try:
        magnets = _attempt(page)
    except LemonError:
        raise
    except Exception as e:
        logger.warning("resolve failed, reset: %s", e)
        _reset_browser()
        page = _ensure_browser()
        try:
            magnets = _attempt(page)
        except LemonError:
            raise
        except Exception as e2:
            raise LemonError("解析磁力失败，请稍后重试") from e2

    return {
        "path": path,
        "magnet": magnets[0],
        "magnets": magnets,
        "detailUrl": urljoin(base.rstrip("/") + "/", path.lstrip("/")),
        "cached": False,
        "costMs": int((time.time() - t0) * 1000),
    }


def resolve_magnet(path: str, keyword: str) -> dict[str, Any]:
    path = (path or "").strip()
    kw = (keyword or "").strip()
    if not path.startswith("/detail/"):
        raise LemonError("无效详情路径")
    if not kw:
        raise LemonError("需要 keyword 以维持会话")

    slug = _detail_slug(path)
    cached = _magnet_cache.get(slug) or _magnet_cache.get(path)
    if cached and time.time() - cached[0] < MAGNET_TTL:
        base = resolve_base_url()
        raw = cached[1]
        magnets = _normalize_magnets(raw if isinstance(raw, list) else [str(raw)])
        if magnets:
            return {
                "path": path,
                "magnet": magnets[0],
                "magnets": magnets,
                "detailUrl": urljoin(base.rstrip("/") + "/", path.lstrip("/")),
                "cached": True,
            }

    def _run() -> dict[str, Any]:
        data = _on_pw_thread(_resolve_uncached, path, kw)
        magnets = list(data.get("magnets") or [])
        if magnets:
            _magnet_cache[slug or path] = (time.time(), magnets)
            _magnet_cache[path] = (time.time(), magnets)
        return data

    return _with_op_lock(_run)
