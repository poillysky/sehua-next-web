"""封面图同源代理（搜索卡片防盗链）+ 列表缩略图缓存。"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import threading
from collections import OrderedDict
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.auth.routes import require_user
from app.core.db import cover_cache_dir
from app.core.outbound_http import httpx_client

log = logging.getLogger(__name__)

router = APIRouter(tags=["cover-proxy"])

_FORUM_IMG_HOST_RE = re.compile(
    r"(?:^|\.)("
    r"ewrewej\.la|ymawv\.la|ldkms\.la|picdcd\.com|adipcd\.com|"
    r"pkapic\.cc|imgccc\.com|11img\.com|yichkp\.com|qpic\.ws|"
    r"gdvdvb\.com|img906\.com|microsoftsa\.com|xunse\.pics|"
    r"023pic3\.cc|pic26077\.cc|pic2607a\.cc|pic505hz\.cc|pid505st\.cc|"
    r"djhdhs\.us"
    r")(?:$|:)",
    re.I,
)

_COVER_FETCH_TIMEOUT = httpx.Timeout(6.0, connect=2.5)
_MEM_CACHE_MAX = 96
_MEM_CACHE_MAX_BYTES = 24 * 1024 * 1024
_DISK_MAX_BYTES = 256 * 1024 * 1024

_mem_lock = threading.Lock()
_mem_cache: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
_mem_bytes = 0


def _safe_image_url(raw: str) -> str:
    u = str(raw or "").strip()
    if not u or len(u) > 2000:
        raise HTTPException(status_code=400, detail="无效图片地址")
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise HTTPException(status_code=400, detail="仅支持 http(s) 图片")
    host = p.hostname or ""
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.startswith("192.168."):
        raise HTTPException(status_code=400, detail="禁止内网地址")
    if host.endswith("doubanio.com"):
        u = re.sub(
            r"https?://img\d+\.doubanio\.com",
            "https://img3.doubanio.com",
            u,
            count=1,
            flags=re.I,
        )
    return u


def _image_headers(url: str, *, referer: str | None) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if "javbus" in host or "seejav" in host:
        try:
            from app.makers.settings import javbus_cookie

            cookie = javbus_cookie()
            if cookie:
                headers["Cookie"] = cookie
        except Exception:
            pass
    return headers


def _looks_like_image(data: bytes, ctype: str) -> bool:
    ct = (ctype or "").lower()
    if "image/" in ct and "svg" not in ct:
        return True
    if not data or len(data) < 4:
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def _is_forum_image_host(host: str) -> bool:
    return bool(_FORUM_IMG_HOST_RE.search(host or ""))


def _is_slow_cover_host(host: str) -> bool:
    h = (host or "").lower()
    return "javbus" in h or "seejav" in h


def _is_dmm_cover_host(host: str) -> bool:
    h = (host or "").lower()
    return "dmm.co.jp" in h or "awsimgsrc.dmm." in h or "netcdn.space" in h


def _referers_for_host(host: str, scheme: str) -> list[str | None]:
    """论坛图床优先 sehuatang Referer；CDN 只用同源/官方 Referer，避免无用重试拖超时。"""
    referers: list[str | None] = []
    if host.endswith("doubanio.com") or host.endswith("douban.com"):
        referers.extend(
            [
                "https://m.douban.com/",
                "https://movie.douban.com/",
            ]
        )
    if _is_dmm_cover_host(host):
        # DMM 图床：官方 Referer + 无 Referer 即可，勿叠论坛站
        referers.append("https://www.dmm.co.jp/")
        if host:
            referers.append(f"{scheme}://{host}/")
        referers.append(None)
    elif _is_slow_cover_host(host):
        # javbus/seejav：最多试 2 个同源镜像，超时即放弃（见 _fetch_bytes_unlocked）
        referers.extend(
            [
                "https://www.javbus.com/",
                f"{scheme}://{host}/" if host else None,
                None,
            ]
        )
    else:
        if _is_forum_image_host(host):
            referers.extend(
                [
                    "https://www.sehuatang.org/",
                    "https://sehuatang.net/",
                ]
            )
        if host:
            referers.append(f"{scheme}://{host}/")
        if not _is_forum_image_host(host):
            referers.extend(
                [
                    "https://www.sehuatang.org/",
                    "https://sehuatang.net/",
                ]
            )
        referers.append(None)
    seen: set[str | None] = set()
    uniq: list[str | None] = []
    for ref in referers:
        if ref in seen:
            continue
        seen.add(ref)
        uniq.append(ref)
    return uniq


def _fetch_bytes(url: str) -> tuple[bytes, str]:
    """列表/代理拉图：走调度器 ui 档，超时仍 503（避免 UI 挂死）。"""
    from app.core.outbound_scheduler import get_scheduler

    sched = get_scheduler()
    try:
        with sched.slot(url, kind="ui", timeout=10.0):
            return _fetch_bytes_core(url, sched=sched)
    except TimeoutError as e:
        raise HTTPException(status_code=503, detail="封面队列繁忙") from e


def _fetch_bytes_for_enrich(
    url: str, *, timeout: float = 8.0
) -> tuple[bytes, str]:
    """刮削拉封面：cover 档。

    timeout 为抢槽上限（批量应传 1～3s，勿再等 45s 把封面预算拖死）。
    抢不到槽抛 TimeoutError，由上层记 slot_blocked 并换下一 URL。
    """
    from app.core.outbound_scheduler import get_scheduler

    sched = get_scheduler()
    to = max(0.35, float(timeout or 8.0))
    with sched.slot(url, kind="cover", timeout=to):
        return _fetch_bytes_core(url, sched=sched)


def _fetch_bytes_unlocked(url: str) -> tuple[bytes, str]:
    """兼容旧调用：无调度包装（调度应在外层）。"""
    from app.core.outbound_scheduler import get_scheduler

    return _fetch_bytes_core(url, sched=get_scheduler())


def _fetch_bytes_core(
    url: str, *, sched: Any | None = None
) -> tuple[bytes, str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    scheme = parsed.scheme or "https"
    uniq_refs = _referers_for_host(host, scheme)
    slow = _is_slow_cover_host(host)
    dmm = _is_dmm_cover_host(host)
    # 慢图床少试 Referer；DMM 也只需 2 个
    ref_cap = 2 if (slow or dmm) else 4
    # 慢图床/DMM：连接失败立刻换下一 URL，勿连撞 3 次超时
    fail_cap = 1 if (slow or dmm) else 3
    timeout = (
        httpx.Timeout(3.0, connect=1.5)
        if slow
        else (
            httpx.Timeout(4.0, connect=2.0)
            if dmm
            else _COVER_FETCH_TIMEOUT
        )
    )

    from app.core.outbound_http import resolve_scrape_proxy_url
    from app.core.outbound_scheduler import get_scheduler

    scheduler = sched or get_scheduler()
    proxy = resolve_scrape_proxy_url()
    # 先代理再直连；共用长寿命 Client
    attempts: list[tuple[str | None, bool]] = []
    if proxy:
        attempts.append((proxy, False))
    attempts.append((None, False))

    last_status = 0
    last_err: Exception | None = None
    transport_fails = 0
    for proxy_u, verify in attempts:
        try:
            client = scheduler.shared_client(
                proxy=proxy_u, verify=verify, timeout=timeout
            )
            for ref in uniq_refs[:ref_cap]:
                try:
                    headers = _image_headers(url, referer=ref)
                    if host.endswith("doubanio.com"):
                        headers["User-Agent"] = (
                            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                            "Mobile/15E148 Safari/604.1"
                        )
                    r = client.get(url, headers=headers, timeout=timeout)
                except Exception as e:
                    last_err = e
                    transport_fails += 1
                    log.warning("cover fetch transport error ref=%s: %s", ref, e)
                    if transport_fails >= fail_cap:
                        break
                    continue
                last_status = r.status_code
                if last_status in {429, 503}:
                    ra = r.headers.get("Retry-After")
                    try:
                        if ra and str(ra).strip().isdigit():
                            scheduler.note_retry_after(url, float(ra))
                        else:
                            scheduler.note_status(url, last_status)
                    except Exception:  # noqa: BLE001
                        scheduler.note_status(url, last_status)
                    continue
                if r.status_code in {403, 404, 418}:
                    continue
                if r.status_code >= 400:
                    continue
                ctype = (
                    (r.headers.get("content-type") or "image/jpeg")
                    .split(";")[0]
                    .strip()
                )
                data = r.content
                if not data or len(data) > 12 * 1024 * 1024:
                    continue
                if not _looks_like_image(data, ctype):
                    continue
                return data, ctype if "image/" in ctype.lower() else "image/jpeg"
        except Exception as e:
            last_err = e
            log.warning("cover client proxy=%s: %s", bool(proxy_u), e)
            continue
        if transport_fails >= fail_cap:
            break
    if last_err is not None and last_status == 0:
        raise HTTPException(status_code=502, detail=f"拉图失败: {last_err}") from last_err
    raise HTTPException(status_code=502, detail=f"拉图失败 {last_status or 403}")


def _cache_key(url: str, w: int | None, *, rp: bool = False) -> str:
    raw = f"{url}|w={w or 0}|rp={1 if rp else 0}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def _cover_cache_dir():
    return cover_cache_dir()


def _mem_get(key: str) -> tuple[bytes, str] | None:
    global _mem_bytes
    with _mem_lock:
        hit = _mem_cache.get(key)
        if hit is None:
            return None
        _mem_cache.move_to_end(key)
        return hit


def _mem_put(key: str, data: bytes, ctype: str) -> None:
    global _mem_bytes
    if len(data) > 2 * 1024 * 1024:
        return
    with _mem_lock:
        old = _mem_cache.pop(key, None)
        if old is not None:
            _mem_bytes -= len(old[0])
        while (
            _mem_cache
            and (
                len(_mem_cache) >= _MEM_CACHE_MAX
                or _mem_bytes + len(data) > _MEM_CACHE_MAX_BYTES
            )
        ):
            _, evicted = _mem_cache.popitem(last=False)
            _mem_bytes -= len(evicted[0])
        _mem_cache[key] = (data, ctype)
        _mem_bytes += len(data)


def _disk_paths(key: str):
    base = _cover_cache_dir() / key
    return base.with_suffix(".bin"), base.with_suffix(".ct")


def _disk_get(key: str) -> tuple[bytes, str] | None:
    bin_p, ct_p = _disk_paths(key)
    try:
        if not bin_p.is_file() or not ct_p.is_file():
            return None
        data = bin_p.read_bytes()
        ctype = ct_p.read_text(encoding="utf-8").strip() or "image/jpeg"
        if not data:
            return None
        return data, ctype
    except OSError:
        return None


def _disk_put(key: str, data: bytes, ctype: str) -> None:
    if len(data) > 4 * 1024 * 1024:
        return
    bin_p, ct_p = _disk_paths(key)
    try:
        bin_p.write_bytes(data)
        ct_p.write_text(ctype or "image/jpeg", encoding="utf-8")
        _maybe_trim_disk()
    except OSError as e:
        log.debug("cover disk cache write failed: %s", e)


def _maybe_trim_disk() -> None:
    try:
        root = _cover_cache_dir()
        files = sorted(
            (p for p in root.glob("*.bin") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
        )
        total = sum(p.stat().st_size for p in files)
        while files and total > _DISK_MAX_BYTES:
            oldest = files.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink(missing_ok=True)
            oldest.with_suffix(".ct").unlink(missing_ok=True)
    except OSError:
        pass


def _crop_right_portrait(im):
    """有码横图右裁竖幅：与入库 `_crop_right` 一致——只削左右，高度不变。"""
    w, h = im.size
    if w <= h or h <= 0:
        return im
    ratio = 2.12 / 3
    cw = max(1, min(w, int(round(h * ratio))))
    left = max(0, w - cw)
    return im.crop((left, 0, left + cw, h))


def _resize_cover(
    data: bytes,
    max_w: int,
    *,
    right_portrait: bool = False,
) -> tuple[bytes, str] | None:
    """列表缩略：最长边缩到 max_w，输出 JPEG。失败则返回 None（用原图）。"""
    if max_w <= 0 or len(data) < 32:
        return None
    try:
        from PIL import Image, ImageOps

        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        before = im.size
        if right_portrait:
            im = _crop_right_portrait(im)
        cropped = im.size != before

        # 列表小图也用 LANCZOS，避免发糊
        if im.width > max_w or im.height > max_w:
            im.thumbnail((max_w, max_w), Image.Resampling.LANCZOS)
        elif not cropped:
            return None

        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        elif im.mode == "L":
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=78, optimize=False)
        out = buf.getvalue()
        if not out:
            return None
        if not cropped and len(out) >= len(data):
            return None
        return out, "image/jpeg"
    except Exception as e:
        log.debug("cover resize skipped: %s", e)
        return None


def _get_cover(url: str, w: int | None, *, rp: bool = False) -> tuple[bytes, str]:
    key = _cache_key(url, w, rp=rp)
    hit = _mem_get(key)
    if hit is not None:
        return hit
    hit = _disk_get(key)
    if hit is not None:
        _mem_put(key, hit[0], hit[1])
        return hit

    # 原图缓存可复用再缩略
    full_key = _cache_key(url, None)
    full = _mem_get(full_key) or _disk_get(full_key)
    if full is None:
        full = _fetch_bytes(url)
        _mem_put(full_key, full[0], full[1])
        _disk_put(full_key, full[0], full[1])

    data, ctype = full
    if w and w > 0:
        resized = _resize_cover(data, w, right_portrait=rp)
        if resized is not None:
            data, ctype = resized

    _mem_put(key, data, ctype)
    _disk_put(key, data, ctype)
    return data, ctype


@router.get("/cover-proxy")
def cover_proxy(
    url: str = Query(..., min_length=8),
    w: int | None = Query(
        None,
        ge=32,
        le=1280,
        description="列表缩略最长边像素；省略则原图",
    ),
    rp: int | None = Query(
        None,
        ge=0,
        le=1,
        description="1=横图裁右侧竖幅（列表厂牌/女优）",
    ),
    _user: dict[str, Any] = Depends(require_user),
) -> Response:
    """同源代理封面图（防盗链）；可选 w 输出列表缩略。"""
    safe = _safe_image_url(url)
    try:
        data, ctype = _get_cover(safe, w, rp=bool(rp))
    except HTTPException:
        raise
    except Exception as e:
        log.warning("cover-proxy fetch failed: %s", e)
        raise HTTPException(status_code=502, detail="拉图失败") from e
    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Cache-Control": "private, max-age=604800",
            "X-Content-Type-Options": "nosniff",
        },
    )
