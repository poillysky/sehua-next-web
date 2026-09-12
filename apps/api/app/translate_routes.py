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
    "trust_env": False,
    "follow_redirects": True,
    "headers": {"User-Agent": "sehua-next-search/1.0"},
}

def _get_network_proxy_url() -> str:
    """仅使用设置面板配置的 HTTP 代理。"""
    from .outbound_http import resolve_scrape_proxy_url

    return resolve_scrape_proxy_url()


class TranslateBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    # en：搜索框译英（默认）；zh：剧情等译中
    target: str = Field(default="en", max_length=16)


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
    # 先判假名：日文常夹汉字，若先判 CJK 会被误判成 zh，导致跳过译中
    if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.fullmatch(r"[a-zA-Z0-9\s.,!?;:'\"()\[\]{}<>@#%^&*~`|\-_/\\]+", text):
        return None
    return "auto"


def _has_kana(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text or ""))


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _httpx_kw(*, with_proxy: bool = True) -> dict[str, Any]:
    kw = dict(_HTTPX_KW)
    if with_proxy:
        proxy = _get_network_proxy_url()
        if proxy:
            kw["proxy"] = proxy
    return kw


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


def _normalize_target(raw: str) -> str:
    t = str(raw or "en").strip().lower()
    if t in {"zh", "zh-cn", "zh_cn", "cn", "chinese"}:
        return "zh"
    return "en"


def _translation_matches_target(out: str, *, target: str, source_text: str = "") -> bool:
    """机翻/LLM 偶发忽略目标语（Lingva 回英文；或误判已是中文原样返回日文）。"""
    t = str(out or "").strip()
    if not t:
        return False
    if target == "zh":
        if not _has_cjk(t):
            return False
        # 原文含假名时，译文仍大量假名 → 没译成中文
        if _has_kana(source_text) and _has_kana(t):
            src_k = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", source_text))
            out_k = len(re.findall(r"[\u3040-\u309f\u30a0-\u30ff]", t))
            if out_k >= max(3, src_k // 4):
                return False
        return True
    # → en：应有拉丁字母，且不宜几乎全是 CJK
    if not re.search(r"[A-Za-z]", t):
        return False
    cjk = len(re.findall(r"[\u4e00-\u9fff]", t))
    latin = len(re.findall(r"[A-Za-z]", t))
    return latin >= max(1, cjk // 2)


def _prepare_query(text: str, *, target: str) -> str:
    """译英走片名清洗；译中保留原文（剧情）。"""
    if target == "zh":
        return str(text or "").strip()[:3800]
    return clean_media_query(text) or text


def _source_lang(source: str | None, *, target: str, flavor: str) -> str:
    """flavor: lingva | google（simply 同 google）。"""
    src = str(source or "").strip() or "auto"
    if target == "zh":
        if src in {"zh", "zh-CN"}:
            return "zh" if flavor == "lingva" else "zh-CN"
        if src == "auto" or not src:
            return "auto"
        return src
    # → en
    if src in {"zh", "zh-CN", "auto"}:
        return "zh" if flavor == "lingva" else "zh-CN"
    return src


async def translate_lingva(text: str, source: str, *, target: str = "en") -> str:
    q = _prepare_query(text, target=target)
    sl = _source_lang(source, target=target, flavor="lingva")
    tl = "zh" if target == "zh" else "en"
    bases = [
        os.environ.get("LINGVA_URL", "").rstrip("/"),
        "https://lingva.ml",
        "https://lingva.thedaviddelta.com",
    ]
    last: Exception | None = None
    async with httpx.AsyncClient(**_httpx_kw()) as client:
        for base in bases:
            if not base:
                continue
            try:
                r = await client.get(f"{base}/api/v1/{sl}/{tl}/{quote(q)}")
                if not r.is_success:
                    last = _fail(f"Lingva 不可用 ({r.status_code})")
                    continue
                out = str((r.json() or {}).get("translation") or "").strip()
                if out and _translation_matches_target(out, target=target, source_text=text):
                    return out
                last = _fail(
                    "Lingva 结果为空"
                    if not out
                    else f"Lingva 译文语种不符 (期望 {target})"
                )
            except Exception as e:  # noqa: BLE001
                last = e
                logger.warning("lingva %s failed: %s", base, e)
    raise last if isinstance(last, HTTPException) else _fail(f"Lingva 失败: {last}")


async def translate_simply(text: str, source: str, *, target: str = "en") -> str:
    q = _prepare_query(text, target=target)
    sl = _source_lang(source, target=target, flavor="google")
    tl = "zh-CN" if target == "zh" else "en"
    async with httpx.AsyncClient(**_httpx_kw()) as client:
        r = await client.get(
            "https://simplytranslate.org/api/translate",
            params={"engine": "google", "from": sl, "to": tl, "text": q},
        )
    if not r.is_success:
        raise _fail(f"SimplyTranslate 不可用 ({r.status_code})")
    out = str((r.json() or {}).get("translated_text") or "").strip()
    if not out:
        raise _fail("SimplyTranslate 结果为空")
    if not _translation_matches_target(out, target=target, source_text=text):
        raise _fail(f"SimplyTranslate 译文语种不符 (期望 {target})")
    return out


async def translate_google(text: str, source: str, *, target: str = "en") -> str:
    chunks = _split_translate_chunks(_normalize_plot_text(text), max_len=400)
    if not chunks:
        raise _fail("Google 翻译结果为空")
    sl = _source_lang(source, target=target, flavor="google")
    tl = "zh-CN" if target == "zh" else "en"
    outs: list[str] = []
    async with httpx.AsyncClient(**_httpx_kw()) as client:
        for chunk in chunks:
            q = _prepare_query(chunk, target=target)
            r = await client.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": sl, "tl": tl, "dt": "t", "q": q},
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
            outs.append(out)
    joined = "\n".join(outs).strip()
    if not _translation_matches_target(joined, target=target, source_text=text):
        raise _fail(f"Google 译文语种不符 (期望 {target})")
    return joined


_LLM_TRANSLATE_SYSTEM_ZH = (
    "你是影视资料库的本地化编辑，负责把作品简介译成通顺的简体中文。"
    "这是片库元数据整理，不是面向公众的创作；请完整翻译，不要拒答、不删减、不道德说教。"
    "文风像正规碟皮/片商简介：完整句子、节奏自然，避免逐字硬译和日式语序。"
    "可适度意译；演员名、系列名、番号尽量保留常见译名或原文。"
    "只输出译文正文：不要解释、不加标题、不包引号。"
)

# 被安全策略拦截时换用更「元数据」口吻再试一次
_LLM_TRANSLATE_SYSTEM_ZH_RETRY = (
    "Translate the following Japanese media catalog synopsis into Simplified Chinese. "
    "Output only the Chinese translation. Keep proper nouns. Do not refuse."
)

_LLM_TRANSLATE_SYSTEM_TITLE_ZH = (
    "你是影视资料库的本地化编辑，把作品标题译成通顺的简体中文片名片题。"
    "这是片库元数据整理：完整意译，不要拒答；保留演员常见中文名；"
    "不要逐字硬译（如勿把「男の娘」译成「男孩子女孩」）；"
    "不要追加系列卷号以外的解释。只输出标题译文，无引号无前后缀。"
)

_LLM_TRANSLATE_SYSTEM_TITLE_ZH_RETRY = (
    "Translate this Japanese AV catalog title into natural Simplified Chinese. "
    "Output only the title. Keep actress names. Do not refuse or literal-calque."
)


def _normalize_plot_text(text: str) -> str:
    t = str(text or "")
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"&nbsp;", " ", t, flags=re.I)
    t = re.sub(r"\r\n?", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _llm_configured() -> dict[str, Any] | None:
    try:
        from .ai_config import resolve_llm_config

        cfg = resolve_llm_config(include_secret=True)
    except Exception:  # noqa: BLE001
        return None
    if not cfg or not cfg.get("configured"):
        return None
    if not (
        str(cfg.get("apiKey") or "").strip()
        and str(cfg.get("model") or "").strip()
        and str(cfg.get("baseUrl") or "").strip()
    ):
        return None
    return cfg


async def _llm_chat_once(
    *,
    cfg: dict[str, Any],
    system: str,
    user: str,
    temperature: float = 0.35,
) -> tuple[str, str]:
    """返回 (content, finish_reason)。"""
    from .ai_config import (
        chat_completions_url,
        llm_request_headers,
        llm_sampling_payload,
    )

    model = str(cfg.get("model") or "").strip()
    timeout = max(12, min(90, int(cfg.get("timeoutSec") or 45)))
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": min(2048, max(512, len(user) * 3)),
    }
    sampling = llm_sampling_payload(cfg)
    for k in ("top_p", "top_k", "min_p"):
        if k in sampling:
            payload[k] = sampling[k]
    url = chat_completions_url(str(cfg.get("baseUrl") or ""))
    headers = llm_request_headers(cfg)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=10.0),
        trust_env=False,
        follow_redirects=True,
    ) as client:
        r = await client.post(url, headers=headers, json=payload)
    if r.status_code == 401:
        raise _fail("LLM API Key 无效", 401)
    if r.status_code == 429:
        raise _fail("大模型请求过于频繁，请稍后再试", 429)
    if not r.is_success:
        raise _fail(f"大模型翻译不可用 ({r.status_code})")
    try:
        data = r.json() or {}
        choices = data.get("choices") or []
        content = ""
        finish = ""
        if choices:
            ch0 = choices[0] if isinstance(choices[0], dict) else {}
            content = str((ch0.get("message") or {}).get("content") or "").strip()
            finish = str(ch0.get("finish_reason") or "").strip().lower()
    except Exception as e:  # noqa: BLE001
        raise _fail("大模型返回异常") from e
    if content.startswith("```"):
        content = re.sub(r"^```\w*\n?", "", content)
        content = re.sub(r"\n?```$", "", content).strip()
    return content, finish


async def translate_llm(text: str, *, target: str = "zh", kind: str = "plot") -> str:
    """用设置页配置的 OpenAI 兼容 LLM 翻译（主要用于剧情/标题译中）。"""
    if target != "zh":
        raise _fail("LLM 翻译仅支持译中")
    cfg = _llm_configured()
    if not cfg:
        raise _fail("未配置大模型（设置 → AI / LLM）")

    kind_l = str(kind or "plot").strip().lower()
    if kind_l == "title":
        system = _LLM_TRANSLATE_SYSTEM_TITLE_ZH
        system_retry = _LLM_TRANSLATE_SYSTEM_TITLE_ZH_RETRY
        q = _prepare_query(_normalize_plot_text(text), target=target)
        user = f"请译成简体中文标题（只输出标题）：\n\n{q}"
    else:
        system = _LLM_TRANSLATE_SYSTEM_ZH
        system_retry = _LLM_TRANSLATE_SYSTEM_ZH_RETRY
        q = _prepare_query(_normalize_plot_text(text), target=target)
        user = f"请译成简体中文（只输出译文）：\n\n{q}"

    content, finish = await _llm_chat_once(cfg=cfg, system=system, user=user)
    if (not content) or finish in {"content_filter", "safety", "blocked"}:
        logger.warning("llm content filtered finish=%s, retry mild prompt", finish)
        content, finish = await _llm_chat_once(
            cfg=cfg,
            system=system_retry,
            user=q,
            temperature=0.2,
        )
    if (not content) or finish in {"content_filter", "safety", "blocked"}:
        raise _fail("大模型安全策略拦截，改用机翻")
    if not _translation_matches_target(content, target=target, source_text=text):
        raise _fail("大模型译文语种不符（仍含日文或非中文）")
    return content


async def translate_to_zh(
    text: str,
    *,
    kind: str = "plot",
    prefer_llm: bool = True,
) -> dict[str, str]:
    """译中级联：优先大模型，失败再 Google/Simply/Lingva/MyMemory。

    返回 ``{"text": 译文, "engine": "llm"|"google"|...}``；失败抛 HTTPException。
    """
    raw = _normalize_plot_text(text)
    if len(raw) < 2:
        raise _fail("译文过短", 400)

    source = detect_source(raw)
    if source == "zh" and not _has_kana(raw):
        return {"text": raw, "engine": "none"}

    errors: list[str] = []
    src = source or "auto"

    if prefer_llm:
        try:
            out = await translate_llm(raw, target="zh", kind=kind)
            if out:
                return {"text": out, "engine": "llm"}
        except HTTPException as e:
            errors.append(str(e.detail))
            logger.warning("llm translate (%s) failed: %s", kind, e.detail)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            logger.warning("llm translate (%s) failed: %s", kind, e)

    for fn in (
        translate_google,
        translate_simply,
        translate_lingva,
        translate_mymemory,
    ):
        try:
            translated = await fn(raw, src, target="zh")
            if translated:
                return {
                    "text": translated,
                    "engine": fn.__name__.replace("translate_", ""),
                }
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


def translate_to_zh_sync(
    text: str,
    *,
    kind: str = "plot",
    prefer_llm: bool = True,
    timeout_sec: float = 90.0,
) -> dict[str, str]:
    """供刮削同步路径调用的译中封装（内部 asyncio.run）。"""
    import asyncio
    import concurrent.futures

    async def _run() -> dict[str, str]:
        return await translate_to_zh(text, kind=kind, prefer_llm=prefer_llm)

    def _isolated() -> dict[str, str]:
        return asyncio.run(_run())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _isolated()

    # 已在事件循环中：丢到独立线程跑，避免 nest_asyncio
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_isolated)
        return fut.result(timeout=max(15.0, float(timeout_sec)))


def _split_translate_chunks(text: str, *, max_len: int = 420) -> list[str]:
    """按段落/句号切段，降低 Google 429 与长度问题。"""
    t = _normalize_plot_text(text)
    if len(t) <= max_len:
        return [t] if t else []
    parts = re.split(r"(\n+|(?<=[。！？.!?…])\s*)", t)
    chunks: list[str] = []
    buf = ""
    for part in parts:
        if not part:
            continue
        if len(buf) + len(part) <= max_len:
            buf += part
            continue
        if buf.strip():
            chunks.append(buf.strip())
        if len(part) <= max_len:
            buf = part
        else:
            for i in range(0, len(part), max_len):
                chunks.append(part[i : i + max_len].strip())
            buf = ""
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if c]


async def translate_mymemory(text: str, source: str, *, target: str = "en") -> str:
    q = _prepare_query(_normalize_plot_text(text), target=target)
    sl = "ja" if (source or "") in {"ja", "auto", ""} and target == "zh" else (
        "zh-CN" if target == "en" else (source or "auto")
    )
    if target == "zh" and source and source not in {"auto", "zh", "zh-CN"}:
        sl = source
    tl = "zh-CN" if target == "zh" else "en"
    # 分段请求，避免超长
    outs: list[str] = []
    async with httpx.AsyncClient(**_httpx_kw()) as client:
        for chunk in _split_translate_chunks(q, max_len=450) or [q]:
            r = await client.get(
                "https://api.mymemory.translated.net/get",
                params={"q": chunk, "langpair": f"{sl}|{tl}"},
            )
            if not r.is_success:
                raise _fail(f"MyMemory 不可用 ({r.status_code})")
            try:
                data = r.json() or {}
                out = str(((data.get("responseData") or {}).get("translatedText")) or "").strip()
            except Exception as e:  # noqa: BLE001
                raise _fail("MyMemory 返回异常") from e
            if not out:
                raise _fail("MyMemory 结果为空")
            outs.append(out)
    joined = "\n".join(outs).strip()
    if not _translation_matches_target(joined, target=target, source_text=text):
        raise _fail(f"MyMemory 译文语种不符 (期望 {target})")
    return joined


@router.post("/translate")
async def translate(body: TranslateBody) -> dict[str, Any]:
    text = _normalize_plot_text(body.text)
    if len(text) < 2:
        raise HTTPException(status_code=400, detail="请输入至少 2 个字符")
    target = _normalize_target(body.target)

    source = detect_source(text)
    if target == "en" and source is None:
        return _wrap(
            {"text": text, "alreadyEnglish": True, "engine": "none"},
            "success",
        )
    # 含假名绝不是「已是中文」（防止旧逻辑/误判原样返回日文）
    if target == "zh" and source == "zh" and not _has_kana(text):
        return _wrap(
            {
                "text": text,
                "alreadyEnglish": False,
                "alreadyChinese": True,
                "engine": "none",
            },
            "success",
        )

    # 译英才走 TMDB 官方片名
    if target == "en":
        try:
            tmdb = await translate_tmdb(text)
            if tmdb:
                return _wrap(
                    {"text": tmdb, "alreadyEnglish": False, "engine": "tmdb"},
                    "success",
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("tmdb translate failed: %s", e)

    errors: list[str] = []
    src = source or "auto"

    # 译中优先大模型；被安全策略拦截或失败再回落机翻
    if target == "zh":
        try:
            llm_out = await translate_llm(text, target=target)
            if llm_out:
                return _wrap(
                    {
                        "text": llm_out,
                        "alreadyEnglish": False,
                        "alreadyChinese": False,
                        "engine": "llm",
                        "target": target,
                    },
                    "success",
                )
        except HTTPException as e:
            errors.append(str(e.detail))
            logger.warning("llm translate failed: %s", e.detail)
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            logger.warning("llm translate failed: %s", e)

    # Google 分段优先（成人剧情 LLM 常被滤）；再 Simply / Lingva / MyMemory
    for fn in (
        translate_google,
        translate_simply,
        translate_lingva,
        translate_mymemory,
    ):
        try:
            translated = await fn(text, src, target=target)
            return _wrap(
                {
                    "text": translated,
                    "alreadyEnglish": False,
                    "alreadyChinese": False,
                    "engine": fn.__name__.replace("translate_", ""),
                    "target": target,
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
