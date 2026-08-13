"""封面取景：代理原图 + 粗略人脸/肤色重心（供显示侧 object-position）。"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from .auth_routes import require_user
from .outbound_http import httpx_client

log = logging.getLogger(__name__)

router = APIRouter(tags=["cover-focus"])

_FOCUS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_FOCUS_TTL = 3600.0
_FOCUS_MAX = 400

_ALLOWED_HOST_SUFFIX = (
    ".la",
    ".com",
    ".net",
    ".org",
    ".cc",
    ".io",
    ".top",
    ".xyz",
)


def _cache_get(key: str) -> dict[str, Any] | None:
    hit = _FOCUS_CACHE.get(key)
    if not hit:
        return None
    ts, data = hit
    if time.time() - ts > _FOCUS_TTL:
        _FOCUS_CACHE.pop(key, None)
        return None
    return data


def _cache_put(key: str, data: dict[str, Any]) -> None:
    if len(_FOCUS_CACHE) >= _FOCUS_MAX:
        oldest = min(_FOCUS_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _FOCUS_CACHE.pop(oldest, None)
    _FOCUS_CACHE[key] = (time.time(), data)


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
    return headers


def _fetch_bytes(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # 论坛图床常校验 Referer；无 Referer / 错 Referer 会 403
    scheme = parsed.scheme or "https"
    referers: list[str | None] = []
    if host:
        referers.append(f"{scheme}://{host}/")
    referers.extend(
        [
            "https://www.sehuatang.org/",
            "https://sehuatang.net/",
            None,
        ]
    )
    last_status = 0
    last_err: Exception | None = None
    # 走设置里的 proxyUrl，否则浏览器直连 CDN 会 ERR_CONNECTION_CLOSED
    with httpx_client(timeout=20.0) as client:
        for ref in referers:
            try:
                r = client.get(url, headers=_image_headers(url, referer=ref))
            except Exception as e:
                last_err = e
                log.warning("cover fetch transport error ref=%s: %s", ref, e)
                continue
            last_status = r.status_code
            if r.status_code == 403:
                continue
            if r.status_code >= 400:
                raise HTTPException(
                    status_code=502, detail=f"拉图失败 {r.status_code}"
                )
            ctype = (r.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
            if "image" not in ctype and not url.lower().endswith(
                (".jpg", ".jpeg", ".png", ".webp", ".gif")
            ):
                raise HTTPException(status_code=415, detail="非图片内容")
            data = r.content
            if not data or len(data) > 12 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="图片过大或空")
            return data, ctype or "image/jpeg"
    if last_err is not None and last_status == 0:
        raise HTTPException(status_code=502, detail=f"拉图失败: {last_err}") from last_err
    raise HTTPException(status_code=502, detail=f"拉图失败 {last_status or 403}")


def _skin_focus_xy(data: bytes) -> tuple[float, float] | None:
    """YCbCr 肤色质心，偏上半幅；失败返回 None。"""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        im = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return None
    # 缩小加速
    im.thumbnail((160, 240))
    w, h = im.size
    if w < 16 or h < 16:
        return None
    px = im.load()
    sx = sy = 0.0
    n = 0
    y_limit = int(h * 0.85)
    for y in range(0, y_limit):
        for x in range(w):
            r, g, b = px[x, y]
            # RGB → 近似 YCbCr
            cb = 128 + (-0.168736 * r - 0.331264 * g + 0.5 * b)
            cr = 128 + (0.5 * r - 0.418688 * g - 0.081312 * b)
            if 77 <= cb <= 127 and 133 <= cr <= 173:
                # 权重：越靠上权重越大（人脸常在上半）
                weight = 1.0 + (y_limit - y) / max(1, y_limit)
                sx += x * weight
                sy += y * weight
                n += weight
    if n < max(40.0, w * h * 0.01):
        return None
    return sx / n / w, sy / n / h


def _focus_for_bytes(data: bytes) -> dict[str, Any]:
    xy = _skin_focus_xy(data)
    if xy:
        x, y = xy
        # 略上移，避免下巴顶满
        y = max(0.08, min(0.72, y * 0.92))
        x = max(0.12, min(0.88, x))
        return {"x": round(x, 4), "y": round(y, 4), "source": "skin"}
    return {"x": 0.5, "y": 0.28, "source": "fallback"}


@router.get("/cover-proxy")
def cover_proxy(
    url: str = Query(..., min_length=8),
    _user: dict[str, Any] = Depends(require_user),
) -> Response:
    """同源代理封面图，供浏览器 FaceDetector 读像素。"""
    safe = _safe_image_url(url)
    try:
        data, ctype = _fetch_bytes(safe)
    except HTTPException:
        raise
    except Exception as e:
        log.warning("cover-proxy fetch failed: %s", e)
        raise HTTPException(status_code=502, detail="拉图失败") from e
    return Response(
        content=data,
        media_type=ctype,
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/cover-focus")
def cover_focus(
    url: str = Query(..., min_length=8),
    _user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """返回归一化取景点 {x,y}∈[0,1]，用于 object-position。"""
    safe = _safe_image_url(url)
    key = hashlib.sha1(safe.encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if cached:
        return {"data": cached, "message": "ok", "status": 200}

    try:
        data, _ctype = _fetch_bytes(safe)
    except HTTPException:
        raise
    except Exception as e:
        log.warning("cover-focus fetch failed: %s", e)
        raise HTTPException(status_code=502, detail="拉图失败") from e

    focus = _focus_for_bytes(data)
    _cache_put(key, focus)
    return {"data": focus, "message": "ok", "status": 200}
