"""设置页：LLM 聊天 + 向量嵌入模型。"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth_routes import get_optional_user, require_user
from . import settings_store
from .ai_config import (
    AI_EMBED_KEY,
    AI_LLM_KEY,
    DEFAULT_EMBED_DIM,
    DEFAULT_EMBED_MODEL,
    DEFAULT_EMBED_PROVIDER,
    DEFAULT_LLM_BASE,
    DEFAULT_LLM_MODEL,
    chat_completions_url,
    embed_public,
    llm_public,
    llm_request_headers,
    llm_sampling_payload,
    models_list_url,
    normalize_openai_base,
    resolve_embed_config,
    resolve_llm_config,
)
from .ai_presets import (
    CHAT_SOURCES,
    LOCAL_EMBED_MODELS,
    OPENAI_EMBED_MODELS,
    PROMPT_POST_PROCESSING,
)
from .conn_settings_routes import Envelope

router = APIRouter(prefix="/settings/ai", tags=["settings"])


class AiSamplingBody(BaseModel):
    temperature: float | None = None
    top_p: float | None = Field(default=None, alias="topP")
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    frequency_penalty: float | None = Field(default=None, alias="frequencyPenalty")
    presence_penalty: float | None = Field(default=None, alias="presencePenalty")

    model_config = {"populate_by_name": True}


class AiLlmBody(BaseModel):
    enabled: bool | None = None
    chat_completion_source: str | None = Field(default=None, alias="chatCompletionSource")
    api_mode: str | None = Field(default=None, alias="apiMode")
    base_url: str | None = Field(default=None, alias="baseUrl")
    model: str | None = None
    api_key: str | None = Field(default=None, alias="apiKey")
    prompt_post_processing: str | None = Field(default=None, alias="promptPostProcessing")
    custom_include_headers: str | None = Field(default=None, alias="customIncludeHeaders")
    custom_include_body: str | None = Field(default=None, alias="customIncludeBody")
    custom_exclude_body: str | None = Field(default=None, alias="customExcludeBody")
    proxy_url: str | None = Field(default=None, alias="proxyUrl")
    timeout_sec: int | None = Field(default=None, alias="timeoutSec")
    sampling: AiSamplingBody | None = None

    model_config = {"populate_by_name": True}


class AiEmbedBody(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    use_main_llm: bool | None = Field(default=None, alias="useMainLlm")
    base_url: str | None = Field(default=None, alias="baseUrl")
    model: str | None = None
    api_key: str | None = Field(default=None, alias="apiKey")
    dim: int | None = None
    top_k: int | None = Field(default=None, alias="topK")
    min_score: float | None = Field(default=None, alias="minScore")
    chunk_size: int | None = Field(default=None, alias="chunkSize")

    model_config = {"populate_by_name": True}


class AiLlmConnectBody(BaseModel):
    base_url: str | None = Field(default=None, alias="baseUrl")
    api_key: str | None = Field(default=None, alias="apiKey")
    custom_include_headers: str | None = Field(default=None, alias="customIncludeHeaders")
    list_models: bool = Field(default=True, alias="listModels")

    model_config = {"populate_by_name": True}


class AiEmbedConnectBody(BaseModel):
    provider: str | None = None
    use_main_llm: bool | None = Field(default=None, alias="useMainLlm")
    base_url: str | None = Field(default=None, alias="baseUrl")
    api_key: str | None = Field(default=None, alias="apiKey")
    list_models: bool = Field(default=True, alias="listModels")

    model_config = {"populate_by_name": True}


class AiLlmTestBody(AiLlmBody):
    pass


class AiEmbedTestBody(AiEmbedBody):
    pass


def _resolve_llm_key(body_key: str | None, stored: dict[str, Any]) -> str:
    env_key = (
        os.environ.get("LLM_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    return (
        str(body_key or "").strip()
        or env_key
        or str(stored.get("apiKey") or stored.get("api_key") or "").strip()
    )


def _resolve_embed_key(body_key: str | None, stored: dict[str, Any]) -> str:
    return str(body_key or "").strip() or str(stored.get("apiKey") or stored.get("api_key") or "").strip()


_EMBED_MODEL_HINTS = ("embed", "embedding", "bge", "e5", "jina", "voyage", "nomic", "retrieval", "ada")


def _filter_embed_models(models: list[str]) -> list[str]:
    hits = [m for m in models if any(h in m.lower() for h in _EMBED_MODEL_HINTS)]
    return hits


def _pick_embed_model_list(raw: list[str]) -> tuple[list[str], int]:
    """优先返回嵌入模型；若筛出的太少而接口模型较多，则展示全部供手选。"""
    total = len(raw)
    if not raw:
        return [], total
    filtered = _filter_embed_models(raw)
    if len(filtered) >= 2:
        return filtered[:80], total
    if total <= 1:
        return raw[:80], total
    # 仅筛出 0~1 个但接口有多模型：避免误过滤，展示全部
    return raw[:80], total


def _merge_sampling(prev: dict[str, Any], body: AiSamplingBody | None) -> dict[str, Any]:
    base = prev.get("sampling") if isinstance(prev.get("sampling"), dict) else {}
    if body is None:
        return dict(base)
    out = dict(base)
    for src, dst in (
        (body.temperature, "temperature"),
        (body.top_p, "topP"),
        (body.max_tokens, "maxTokens"),
        (body.frequency_penalty, "frequencyPenalty"),
        (body.presence_penalty, "presencePenalty"),
    ):
        if src is not None:
            out[dst] = src
    return out


def _merge_llm_put(prev: dict[str, Any], body: AiLlmBody) -> dict[str, Any]:
    prev_key = str(prev.get("apiKey") or prev.get("api_key") or "").strip()
    next_key = str(body.api_key or "").strip()
    timeout = body.timeout_sec if body.timeout_sec is not None else prev.get("timeoutSec") or prev.get("timeout_sec")
    try:
        timeout_i = max(5, min(120, int(timeout or 30)))
    except (TypeError, ValueError):
        timeout_i = 30
    return {
        "enabled": bool(prev.get("enabled", True)) if body.enabled is None else bool(body.enabled),
        "chatCompletionSource": str(
            body.chat_completion_source
            or prev.get("chatCompletionSource")
            or prev.get("chat_completion_source")
            or "custom"
        ).strip()
        or "custom",
        "apiMode": str(body.api_mode or prev.get("apiMode") or prev.get("api_mode") or "chat").strip()
        or "chat",
        "baseUrl": normalize_openai_base(
            str(body.base_url or prev.get("baseUrl") or prev.get("base_url") or ""),
            default=DEFAULT_LLM_BASE,
        ),
        "model": str(body.model or prev.get("model") or DEFAULT_LLM_MODEL).strip() or DEFAULT_LLM_MODEL,
        "apiKey": next_key or prev_key,
        "promptPostProcessing": str(
            body.prompt_post_processing
            if body.prompt_post_processing is not None
            else prev.get("promptPostProcessing") or prev.get("prompt_post_processing") or ""
        ),
        "customIncludeHeaders": str(
            body.custom_include_headers
            if body.custom_include_headers is not None
            else prev.get("customIncludeHeaders") or prev.get("custom_include_headers") or ""
        ),
        "customIncludeBody": str(
            body.custom_include_body
            if body.custom_include_body is not None
            else prev.get("customIncludeBody") or prev.get("custom_include_body") or ""
        ),
        "customExcludeBody": str(
            body.custom_exclude_body
            if body.custom_exclude_body is not None
            else prev.get("customExcludeBody") or prev.get("custom_exclude_body") or ""
        ),
        "proxyUrl": str(
            body.proxy_url if body.proxy_url is not None else prev.get("proxyUrl") or prev.get("proxy_url") or ""
        ),
        "timeoutSec": timeout_i,
        "sampling": _merge_sampling(prev, body.sampling),
    }


def _merge_embed_put(prev: dict[str, Any], body: AiEmbedBody) -> dict[str, Any]:
    prev_key = str(prev.get("apiKey") or prev.get("api_key") or "").strip()
    next_key = str(body.api_key or "").strip()
    provider = str(body.provider or prev.get("provider") or DEFAULT_EMBED_PROVIDER).strip().lower()
    if provider not in {"local", "openai"}:
        provider = DEFAULT_EMBED_PROVIDER
    dim_raw = body.dim if body.dim is not None else prev.get("dim")
    try:
        dim = int(dim_raw) if dim_raw is not None else DEFAULT_EMBED_DIM
    except (TypeError, ValueError):
        dim = DEFAULT_EMBED_DIM
    dim = max(64, min(4096, dim))
    top_k_raw = body.top_k if body.top_k is not None else prev.get("topK") if "topK" in prev else prev.get("top_k")
    try:
        top_k = max(1, min(50, int(top_k_raw if top_k_raw is not None else 8)))
    except (TypeError, ValueError):
        top_k = 8
    min_score_raw = (
        body.min_score
        if body.min_score is not None
        else prev.get("minScore")
        if "minScore" in prev
        else prev.get("min_score")
    )
    try:
        min_score = max(0.0, min(1.0, float(min_score_raw if min_score_raw is not None else 0.35)))
    except (TypeError, ValueError):
        min_score = 0.35
    chunk_raw = (
        body.chunk_size
        if body.chunk_size is not None
        else prev.get("chunkSize")
        if "chunkSize" in prev
        else prev.get("chunk_size")
    )
    try:
        chunk_size = max(100, min(2000, int(chunk_raw if chunk_raw is not None else 500)))
    except (TypeError, ValueError):
        chunk_size = 500
    use_main = (
        bool(prev.get("useMainLlm") if "useMainLlm" in prev else prev.get("use_main_llm", False))
        if body.use_main_llm is None
        else bool(body.use_main_llm)
    )
    return {
        "enabled": bool(prev.get("enabled", True)) if body.enabled is None else bool(body.enabled),
        "provider": provider,
        "useMainLlm": use_main,
        "baseUrl": normalize_openai_base(
            str(body.base_url or prev.get("baseUrl") or prev.get("base_url") or ""),
            default=DEFAULT_LLM_BASE,
        ),
        "model": str(body.model or prev.get("model") or DEFAULT_EMBED_MODEL).strip() or DEFAULT_EMBED_MODEL,
        "apiKey": next_key or prev_key,
        "dim": dim,
        "topK": top_k,
        "minScore": min_score,
        "chunkSize": chunk_size,
    }


@router.get("/presets", response_model=Envelope)
def get_ai_presets(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    return Envelope(
        data={
            "chatSources": CHAT_SOURCES,
            "localEmbedModels": LOCAL_EMBED_MODELS,
            "openaiEmbedModels": OPENAI_EMBED_MODELS,
            "promptPostProcessing": PROMPT_POST_PROCESSING,
        },
        message="ok",
    )


@router.get("/llm", response_model=Envelope)
def get_ai_llm(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    data = llm_public(settings_store.get_setting(AI_LLM_KEY))
    return Envelope(data=data, message="ok")


@router.put("/llm", response_model=Envelope)
def put_ai_llm(
    body: AiLlmBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    prev = settings_store.get_setting(AI_LLM_KEY) or {}
    next = _merge_llm_put(prev, body)
    saved = settings_store.put_setting(AI_LLM_KEY, next)
    data = llm_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    return Envelope(data=data, message="saved")


@router.post("/llm/connect", response_model=Envelope)
async def connect_ai_llm(
    body: AiLlmConnectBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    stored = settings_store.get_setting(AI_LLM_KEY) or {}
    api_key = _resolve_llm_key(body.api_key, stored)
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 LLM API Key")
    base_url = normalize_openai_base(
        str(body.base_url or stored.get("baseUrl") or stored.get("base_url") or ""),
        default=DEFAULT_LLM_BASE,
    )
    headers_text = (
        str(body.custom_include_headers or "").strip()
        or str(stored.get("customIncludeHeaders") or stored.get("custom_include_headers") or "").strip()
    )
    cfg = {
        "apiKey": api_key,
        "customIncludeHeaders": headers_text,
    }
    headers = llm_request_headers(cfg)
    url = models_list_url(base_url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
            r = await client.get(url, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接 LLM: {e}") from e
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="API Key 无效")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"LLM 返回 {r.status_code}: {r.text[:200]}")
    models: list[str] = []
    if body.list_models:
        try:
            data = (r.json() or {}).get("data") or []
            models = [str(m.get("id") or "").strip() for m in data if isinstance(m, dict)]
            models = [m for m in models if m][:80]
        except Exception:
            models = []
    current = str(stored.get("model") or DEFAULT_LLM_MODEL).strip()
    msg = f"连接成功 · {len(models)} 个模型" if models else "连接成功"
    return Envelope(
        data={
            "ok": True,
            "baseUrl": base_url,
            "modelCount": len(models),
            "models": models,
            "currentModel": current,
        },
        message=msg,
    )


@router.post("/llm/test", response_model=Envelope)
async def test_ai_llm(
    body: AiLlmTestBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    stored = settings_store.get_setting(AI_LLM_KEY) or {}
    merged = _merge_llm_put(stored, body)
    api_key = _resolve_llm_key(body.api_key, stored)
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 LLM API Key")
    merged["apiKey"] = api_key
    base_url = merged["baseUrl"]
    model = merged["model"]
    url = chat_completions_url(base_url)
    headers = llm_request_headers(merged)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
    }
    payload.update(llm_sampling_payload(merged))
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
            r = await client.post(url, headers=headers, json=payload)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接 LLM: {e}") from e
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="API Key 无效")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"LLM 返回 {r.status_code}: {r.text[:200]}")
    reply = ""
    try:
        choices = (r.json() or {}).get("choices") or []
        if choices:
            reply = str((choices[0].get("message") or {}).get("content") or "").strip()
    except Exception:
        reply = ""
    msg = f"测试成功 · {model}"
    if reply:
        msg = f"{msg} · {reply[:40]}"
    return Envelope(data={"ok": True, "model": model, "reply": reply}, message=msg)


@router.get("/embed", response_model=Envelope)
def get_ai_embed(_user: dict[str, Any] | None = Depends(get_optional_user)) -> Envelope:
    data = embed_public(settings_store.get_setting(AI_EMBED_KEY))
    return Envelope(data=data, message="ok")


@router.put("/embed", response_model=Envelope)
def put_ai_embed(
    body: AiEmbedBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    prev = settings_store.get_setting(AI_EMBED_KEY) or {}
    next = _merge_embed_put(prev, body)
    saved = settings_store.put_setting(AI_EMBED_KEY, next)
    data = embed_public(saved["value"])
    data["updated_at"] = saved["updated_at"]
    return Envelope(data=data, message="saved")


@router.post("/embed/connect", response_model=Envelope)
async def connect_ai_embed(
    body: AiEmbedConnectBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    stored = settings_store.get_setting(AI_EMBED_KEY) or {}
    merged = _merge_embed_put(
        stored,
        AiEmbedBody(
            provider=body.provider,
            use_main_llm=body.use_main_llm,
            base_url=body.base_url,
            api_key=body.api_key,
        ),
    )
    provider = str(merged.get("provider") or DEFAULT_EMBED_PROVIDER).lower()
    if provider == "local":
        models = [str(m.get("value") or "").strip() for m in LOCAL_EMBED_MODELS]
        models = [m for m in models if m]
        current = str(merged.get("model") or DEFAULT_EMBED_MODEL).strip()
        return Envelope(
            data={
                "ok": True,
                "provider": "local",
                "baseUrl": "",
                "modelCount": len(models),
                "models": models,
                "currentModel": current,
            },
            message=f"本地 fastembed · {len(models)} 个模型",
        )

    use_main = bool(merged.get("useMainLlm"))
    if use_main:
        llm_stored = settings_store.get_setting(AI_LLM_KEY) or {}
        llm_cfg = resolve_llm_config(include_secret=True)
        api_key = _resolve_llm_key(body.api_key, llm_stored) or str(llm_cfg.get("apiKey") or "").strip()
        base_url = normalize_openai_base(
            str(body.base_url or llm_cfg.get("baseUrl") or ""),
            default=DEFAULT_LLM_BASE,
        )
        headers = llm_request_headers(
            {
                "apiKey": api_key,
                "customIncludeHeaders": llm_cfg.get("customIncludeHeaders") or "",
            }
        )
    else:
        api_key = _resolve_embed_key(body.api_key, stored)
        base_url = normalize_openai_base(
            str(body.base_url or merged.get("baseUrl") or ""),
            default=DEFAULT_LLM_BASE,
        )
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写向量 API Key，或开启「沿用聊天」")

    url = models_list_url(base_url)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0)) as client:
            r = await client.get(url, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"无法连接向量接口: {e}") from e
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="API Key 无效")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"接口返回 {r.status_code}: {r.text[:200]}")

    models: list[str] = []
    total_model_count = 0
    embed_match_count = 0
    if body.list_models:
        try:
            data = (r.json() or {}).get("data") or []
            raw = [str(m.get("id") or "").strip() for m in data if isinstance(m, dict)]
            raw = [m for m in raw if m]
            embed_match_count = len(_filter_embed_models(raw))
            models, total_model_count = _pick_embed_model_list(raw)
        except Exception:
            models = []
            total_model_count = 0
            embed_match_count = 0

    if not models:
        models = [str(m.get("value") or "").strip() for m in OPENAI_EMBED_MODELS]
        models = [m for m in models if m]
        total_model_count = len(models)
        embed_match_count = len(models)

    current = str(merged.get("model") or DEFAULT_EMBED_MODEL).strip()
    if total_model_count <= 1:
        msg = f"连接成功 · 接口共 {total_model_count or len(models)} 个模型"
    elif embed_match_count <= 1 and len(models) > embed_match_count:
        msg = (
            f"连接成功 · 接口 {total_model_count} 个 · "
            f"嵌入名匹配 {embed_match_count} 个 · 已展示全部 {len(models)} 个"
        )
    elif embed_match_count >= 2 and len(models) == embed_match_count:
        msg = f"连接成功 · 接口 {total_model_count} 个 · 嵌入 {embed_match_count} 个"
    else:
        msg = f"连接成功 · {len(models)} 个模型"
    return Envelope(
        data={
            "ok": True,
            "provider": "openai",
            "baseUrl": base_url,
            "modelCount": len(models),
            "totalModelCount": total_model_count,
            "embedMatchCount": embed_match_count,
            "models": models,
            "currentModel": current,
        },
        message=msg,
    )


@router.post("/embed/test", response_model=Envelope)
async def test_ai_embed(
    body: AiEmbedTestBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    stored = settings_store.get_setting(AI_EMBED_KEY) or {}
    merged = _merge_embed_put(stored, body)
    override: dict[str, Any] = dict(merged)
    if str(body.api_key or "").strip():
        override["apiKey"] = str(body.api_key).strip()
    try:
        from .ai_embed import test_embed_connection

        result = await test_embed_connection(override=override)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    cfg = resolve_embed_config(override=override)
    msg = f"测试成功 · {cfg['provider']} · {cfg['model']} · {result.get('dim')} 维"
    return Envelope(data={"ok": True, **result}, message=msg)
