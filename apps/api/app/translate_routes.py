"""关键词一键翻译（对齐色花：TMDB 标准片名优先，再机翻）。"""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import settings_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["translate"])

MEDIA_NOISE_REGEX = re.compile(
    r"\b(1080[pP]?|720[pP]?|2160[pP]?|4[kK]|x26[45]|HEVC|H\.?264|H\.?265|"
    r"BluRay|Blu-Ray|WEB[- ]?DL|WEBRip|HDR10?|DV|Remux|REPACK|PROPER|"
    r"中字|简繁|繁体|简体|国语|粤语|双语|内嵌|外挂|合集|全集|完結|完结|"
    r"第[一二三四五六七八九十\d]+季|第[一二三四五六七八九十\d]+集|"
    r"S\d{1,2}E\d{1,2}|EP?\d{1,3}|\d{4}年?)\b|[\[\]()【】（）]",
    re.I,
)

_LATIN_TITLE = re.compile(r"^[a-zA-Z0-9\s:.'&!?,\-]+$")

_HTTPX_KW: dict[str, Any] = {
    "timeout": 12.0,
    "trust_env": True,
    "follow_redirects": True,
    "headers": {"User-Agent": "sehua-next-search/1.0"},
}

def _get_network_proxy_url() -> str:
    """从网络管理配置里取 HTTP 代理 URL（用于 TMDB 外联）。"""
    raw = settings_store.get_setting(settings_store.SCRAPE_KEY) or {}
    proxy = str(raw.get("proxyUrl") or raw.get("proxy_url") or "").strip()
    if not proxy:
        return ""
    # 容错：如果没有协议头，默认补 http://
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return proxy.rstrip("/")


class TranslateBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)


def _wrap(data: Any, message: str = "ok", status: int = 200) -> dict[str, Any]:
    return {"data": data, "message": message, "status": status}


def get_tmdb_api_key() -> str:
    """环境变量优先，其次设置页保存的 key。"""
    env = os.environ.get("TMDB_API_KEY", "").strip()
    if env:
        return env
    raw = settings_store.get_setting(settings_store.TMDB_KEY) or {}
    if isinstance(raw, dict):
        return str(raw.get("apiKey") or raw.get("api_key") or "").strip()
    return ""


def clean_media_query(text: str) -> str:
    t = MEDIA_NOISE_REGEX.sub(" ", text)
    t = re.sub(r"[._\-+]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:80]


def detect_source(text: str) -> str | None:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.fullmatch(r"[a-zA-Z0-9\s.,!?;:'\"()\[\]{}<>@#%^&*~`|\-_/\\]+", text):
        return None
    return "auto"


def _fail(msg: str, status: int = 502) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


def _is_latin_title(text: str) -> bool:
    return bool(_LATIN_TITLE.match(text.strip()))


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _pick_best_tmdb(results: list[dict[str, Any]], query: str) -> dict[str, Any]:
    nq = _norm(query)

    def score(item: dict[str, Any]) -> float:
        titles = [
            item.get("title"),
            item.get("name"),
            item.get("original_title"),
            item.get("original_name"),
        ]
        value = float(item.get("popularity") or 0)
        for title in titles:
            if not title:
                continue
            nt = _norm(str(title))
            if nt == nq:
                value += 1000
            elif nq in nt or nt in nq:
                value += 300
        return value

    return sorted(results, key=score, reverse=True)[0]


async def _tmdb_english_detail(
    client: httpx.AsyncClient, item: dict[str, Any], api_key: str
) -> str | None:
    media = item.get("media_type")
    item_id = item.get("id")
    if media not in {"movie", "tv"} or not item_id:
        return None
    path = f"/3/{media}/{item_id}"
    r = await client.get(
        f"https://api.themoviedb.org{path}",
        params={"api_key": api_key, "language": "en-US"},
    )
    if not r.is_success:
        return None
    data = r.json() or {}
    for key in ("original_title", "title", "original_name", "name"):
        val = str(data.get(key) or "").strip()
        if val and _is_latin_title(val):
            return val
    return None


async def translate_tmdb(text: str) -> str | None:
    api_key = get_tmdb_api_key()
    if not api_key:
        return None
    query = clean_media_query(text)
    if len(query) < 2:
        return None
    proxy = _get_network_proxy_url()
    client_kw = dict(_HTTPX_KW)
    if proxy:
        # 明确走配置的代理，避免 trust_env 把系统代理干扰进来
        client_kw["trust_env"] = False
        client_kw["proxy"] = proxy

    async with httpx.AsyncClient(**client_kw) as client:
        r = await client.get(
            "https://api.themoviedb.org/3/search/multi",
            params={
                "api_key": api_key,
                "query": query,
                "language": "zh-CN",
                "include_adult": "false",
            },
        )
        if not r.is_success:
            logger.warning("tmdb search failed: %s", r.status_code)
            return None
        results = [
            x
            for x in (r.json() or {}).get("results") or []
            if isinstance(x, dict) and x.get("media_type") in {"movie", "tv"}
        ]
        if not results:
            return None
        best = _pick_best_tmdb(results, query)
        for key in ("original_title", "original_name", "title", "name"):
            val = str(best.get(key) or "").strip()
            if val and _is_latin_title(val):
                return val
        return await _tmdb_english_detail(client, best, api_key)


async def translate_lingva(text: str, source: str) -> str:
    q = clean_media_query(text) or text
    sl = "zh" if source in {"zh", "zh-CN", "auto"} else source
    bases = [
        os.environ.get("LINGVA_URL", "").rstrip("/"),
        "https://lingva.ml",
        "https://lingva.thedaviddelta.com",
    ]
    last: Exception | None = None
    async with httpx.AsyncClient(**_HTTPX_KW) as client:
        for base in bases:
            if not base:
                continue
            try:
                r = await client.get(f"{base}/api/v1/{sl}/en/{quote(q)}")
                if not r.is_success:
                    last = _fail(f"Lingva 不可用 ({r.status_code})")
                    continue
                out = str((r.json() or {}).get("translation") or "").strip()
                if out:
                    return out
                last = _fail("Lingva 结果为空")
            except Exception as e:  # noqa: BLE001
                last = e
                logger.warning("lingva %s failed: %s", base, e)
    raise last if isinstance(last, HTTPException) else _fail(f"Lingva 失败: {last}")


async def translate_simply(text: str, source: str) -> str:
    q = clean_media_query(text) or text
    sl = "zh" if source in {"zh", "zh-CN", "auto"} else source
    async with httpx.AsyncClient(**_HTTPX_KW) as client:
        r = await client.get(
            "https://simplytranslate.org/api/translate",
            params={"engine": "google", "from": sl, "to": "en", "text": q},
        )
    if not r.is_success:
        raise _fail(f"SimplyTranslate 不可用 ({r.status_code})")
    out = str((r.json() or {}).get("translated_text") or "").strip()
    if not out:
        raise _fail("SimplyTranslate 结果为空")
    return out


async def translate_google(text: str, source: str) -> str:
    q = clean_media_query(text) or text
    sl = "zh-CN" if source in {"zh", "zh-CN", "auto"} else source
    async with httpx.AsyncClient(**_HTTPX_KW) as client:
        r = await client.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": sl, "tl": "en", "dt": "t", "q": q},
        )
    if r.status_code == 429:
        raise _fail("翻译请求过于频繁，请稍后再试", 429)
    if not r.is_success:
        raise _fail(f"Google 翻译不可用 ({r.status_code})")
    try:
        data = r.json()
    except Exception as e:
        raise _fail("Google 翻译返回异常") from e
    parts = data[0] if isinstance(data, list) and data else []
    out = "".join(str(p[0]) for p in parts if p and p[0]).strip()
    if not out:
        raise _fail("Google 翻译结果为空")
    return out


@router.post("/translate")
async def translate(body: TranslateBody) -> dict[str, Any]:
    text = body.text.strip()
    if len(text) < 2:
        raise HTTPException(status_code=400, detail="请输入至少 2 个字符")

    source = detect_source(text)
    if source is None:
        return _wrap(
            {"text": text, "alreadyEnglish": True, "engine": "none"},
            "success",
        )

    # 1) TMDB 官方片名（影视最准）
    try:
        tmdb = await translate_tmdb(text)
        if tmdb:
            return _wrap(
                {"text": tmdb, "alreadyEnglish": False, "engine": "tmdb"},
                "success",
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("tmdb translate failed: %s", e)

    # 2) 机翻回落
    errors: list[str] = []
    for fn in (translate_lingva, translate_simply, translate_google):
        try:
            translated = await fn(text, source)
            return _wrap(
                {
                    "text": translated,
                    "alreadyEnglish": False,
                    "engine": fn.__name__.replace("translate_", ""),
                },
                "success",
            )
        except HTTPException as e:
            errors.append(str(e.detail))
            logger.warning("%s failed: %s", fn.__name__, e.detail)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            logger.warning("%s failed: %s", fn.__name__, e)

    raise HTTPException(
        status_code=502,
        detail=errors[-1] if errors else "翻译失败，请稍后重试",
    )
