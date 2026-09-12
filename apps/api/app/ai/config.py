"""AI 模型配置：LLM 聊天 + 向量嵌入（Postgres settings，环境变量可覆盖）。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import app.core.settings_store as settings_store
from app.ai.presets import LOCAL_EMBED_DEVICES, LOCAL_EMBED_MODELS

AI_LLM_KEY = "ai.llm"
AI_EMBED_KEY = "ai.embed"
AI_WEB_SEARCH_KEY = "ai.webSearch"
AI_ASSISTANT_KEY = "ai.assistant"

DEFAULT_LLM_BASE = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4o-mini"
DEFAULT_EMBED_PROVIDER = "local"
DEFAULT_EMBED_MODEL = "intfloat/multilingual-e5-large"
DEFAULT_EMBED_DIM = 1024
DEFAULT_EMBED_TOP_K = 8
DEFAULT_EMBED_MIN_SCORE = 0.35
DEFAULT_EMBED_CHUNK_SIZE = 500
DEFAULT_EMBED_DEVICE = "cpu"
DEFAULT_WEB_SEARCH_PROVIDER = "serper"
DEFAULT_SEARXNG_BASE = "http://192.168.2.38:8085"
EMBED_DEVICE_VALUES = frozenset({"cpu", "cuda", "directml"})
WEB_SEARCH_PROVIDERS = frozenset({"serper", "brave", "searxng"})


def _strip(s: str | None) -> str:
    return str(s or "").strip()


def _api_key_hint(key: str) -> str:
    k = _strip(key)
    if not k:
        return ""
    if len(k) <= 10:
        return "****"
    return f"{k[:4]}…{k[-4:]}"


def normalize_openai_base(raw: str | None, *, default: str = DEFAULT_LLM_BASE) -> str:
    s = _strip(raw) or default
    if "://" not in s:
        s = f"https://{s}"
    return s.rstrip("/")


def _optional_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def parse_custom_headers(text: str | None) -> dict[str, str]:
    """YAML 风格或 JSON 对象；失败则按行 key: value 解析。"""
    raw = _strip(text)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if str(k).strip()}
    except json.JSONDecodeError:
        pass
    out: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def _llm_env() -> dict[str, str]:
    key = _strip(os.environ.get("LLM_API_KEY")) or _strip(os.environ.get("OPENAI_API_KEY"))
    base = _strip(os.environ.get("LLM_BASE_URL"))
    model = _strip(os.environ.get("LLM_MODEL"))
    out: dict[str, str] = {}
    if key:
        out["apiKey"] = key
    if base:
        out["baseUrl"] = base
    if model:
        out["model"] = model
    return out


def _embed_env() -> dict[str, Any]:
    out: dict[str, Any] = {}
    provider = _strip(os.environ.get("EMBED_PROVIDER")).lower()
    if provider in {"local", "openai"}:
        out["provider"] = provider
    base = _strip(os.environ.get("EMBED_BASE_URL"))
    if base:
        out["baseUrl"] = base
    key = _strip(os.environ.get("EMBED_API_KEY"))
    if key:
        out["apiKey"] = key
    model = _strip(os.environ.get("EMBED_MODEL"))
    if model:
        out["model"] = model
    dim_raw = _strip(os.environ.get("EMBED_DIM"))
    if dim_raw.isdigit():
        out["dim"] = int(dim_raw)
    device = _strip(os.environ.get("EMBED_DEVICE")).lower()
    if device in {"nvidia", "n"}:
        device = "cuda"
    elif device in {"amd", "a", "dml"}:
        device = "directml"
    if device in EMBED_DEVICE_VALUES:
        out["device"] = device
    return out


def probe_onnx_providers() -> set[str]:
    try:
        import onnxruntime as ort

        return set(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        return set()


def normalize_embed_device(raw: Any) -> str:
    d = _strip(raw).lower()
    if d in {"nvidia", "n", "gpu-nvidia"}:
        d = "cuda"
    elif d in {"amd", "a", "dml", "gpu-amd"}:
        d = "directml"
    if d in EMBED_DEVICE_VALUES:
        return d
    return ""


def default_embed_device(*, available: set[str] | None = None) -> str:
    """未配置时：有 DirectML 选 A卡，有 CUDA 选 N卡，否则 CPU。"""
    avail = available if available is not None else probe_onnx_providers()
    if "DmlExecutionProvider" in avail:
        return "directml"
    if "CUDAExecutionProvider" in avail:
        return "cuda"
    return DEFAULT_EMBED_DEVICE


def local_embed_devices() -> list[dict[str, Any]]:
    avail = probe_onnx_providers()
    out: list[dict[str, Any]] = []
    for row in LOCAL_EMBED_DEVICES:
        value = str(row["value"])
        if value == "cpu":
            ok = "CPUExecutionProvider" in avail or not avail
        elif value == "cuda":
            ok = "CUDAExecutionProvider" in avail
        elif value == "directml":
            ok = "DmlExecutionProvider" in avail
        else:
            ok = False
        out.append(
            {
                "value": value,
                "label": row["label"],
                "hint": row.get("hint") or "",
                "available": ok,
            }
        )
    return out


def _stored_llm() -> dict[str, Any]:
    raw = settings_store.get_setting(AI_LLM_KEY) or {}
    return raw if isinstance(raw, dict) else {}


def _stored_embed() -> dict[str, Any]:
    raw = settings_store.get_setting(AI_EMBED_KEY) or {}
    return raw if isinstance(raw, dict) else {}


def _merge_llm_stored(stored: dict[str, Any]) -> dict[str, Any]:
    env = _llm_env()
    api_key = _strip(env.get("apiKey")) or _strip(stored.get("apiKey") or stored.get("api_key"))
    base_url = normalize_openai_base(
        _strip(env.get("baseUrl")) or _strip(stored.get("baseUrl") or stored.get("base_url")),
        default=DEFAULT_LLM_BASE,
    )
    model = _strip(env.get("model")) or _strip(stored.get("model")) or DEFAULT_LLM_MODEL
    sampling = stored.get("sampling") if isinstance(stored.get("sampling"), dict) else {}
    return {
        "enabled": bool(stored.get("enabled", True)),
        "chatCompletionSource": _strip(stored.get("chatCompletionSource") or stored.get("chat_completion_source") or "custom"),
        "apiMode": _strip(stored.get("apiMode") or stored.get("api_mode") or "chat") or "chat",
        "baseUrl": base_url,
        "model": model,
        "apiKey": api_key,
        "promptPostProcessing": _strip(stored.get("promptPostProcessing") or stored.get("prompt_post_processing") or ""),
        "customIncludeHeaders": _strip(stored.get("customIncludeHeaders") or stored.get("custom_include_headers") or ""),
        "customIncludeBody": _strip(stored.get("customIncludeBody") or stored.get("custom_include_body") or ""),
        "customExcludeBody": _strip(stored.get("customExcludeBody") or stored.get("custom_exclude_body") or ""),
        "proxyUrl": _strip(stored.get("proxyUrl") or stored.get("proxy_url") or ""),
        "timeoutSec": max(5, min(120, int(_optional_int(stored.get("timeoutSec") or stored.get("timeout_sec")) or 30))),
        "sampling": {
            "temperature": _optional_float(sampling.get("temperature")),
            "topP": _optional_float(sampling.get("topP") if "topP" in sampling else sampling.get("top_p")),
            "maxTokens": _optional_int(
                sampling.get("maxTokens")
                if "maxTokens" in sampling
                else sampling.get("max_tokens")
                if "max_tokens" in sampling
                else sampling.get("openai_max_tokens")
            ),
            "maxContext": _optional_int(
                sampling.get("maxContext")
                if "maxContext" in sampling
                else sampling.get("max_context")
                if "max_context" in sampling
                else sampling.get("openai_max_context")
            ),
            "frequencyPenalty": _optional_float(
                sampling.get("frequencyPenalty")
                if "frequencyPenalty" in sampling
                else sampling.get("frequency_penalty")
            ),
            "presencePenalty": _optional_float(
                sampling.get("presencePenalty")
                if "presencePenalty" in sampling
                else sampling.get("presence_penalty")
            ),
            "topK": _optional_int(sampling.get("topK") if "topK" in sampling else sampling.get("top_k")),
            "minP": _optional_float(sampling.get("minP") if "minP" in sampling else sampling.get("min_p")),
            "repetitionPenalty": _optional_float(
                sampling.get("repetitionPenalty")
                if "repetitionPenalty" in sampling
                else sampling.get("repetition_penalty")
                if "repetition_penalty" in sampling
                else sampling.get("rep_pen")
            ),
            "seed": _optional_int(sampling.get("seed")),
            "n": _optional_int(sampling.get("n")),
            "streamOpenai": (
                bool(sampling["streamOpenai"])
                if "streamOpenai" in sampling
                else (
                    bool(sampling["stream_openai"])
                    if "stream_openai" in sampling
                    else True
                )
            ),
            "maxContextUnlocked": bool(
                sampling.get("maxContextUnlocked")
                if "maxContextUnlocked" in sampling
                else sampling.get("max_context_unlocked")
            ),
            "continuePrefill": bool(
                sampling.get("continuePrefill")
                if "continuePrefill" in sampling
                else sampling.get("continue_prefill")
            ),
            "squashSystemMessages": bool(
                sampling.get("squashSystemMessages")
                if "squashSystemMessages" in sampling
                else sampling.get("squash_system_messages")
            ),
            "showThoughts": bool(
                sampling.get("showThoughts")
                if "showThoughts" in sampling
                else sampling.get("show_thoughts")
            ),
        },
        "fromEnvKey": bool(env.get("apiKey")),
        "fromEnvBase": bool(env.get("baseUrl")),
        "fromEnvModel": bool(env.get("model")),
        "configured": bool(api_key and model and base_url),
    }


def resolve_llm_config(*, include_secret: bool = False, override: dict[str, Any] | None = None) -> dict[str, Any]:
    stored = {**_stored_llm(), **(override or {})}
    cfg = _merge_llm_stored(stored)
    if not include_secret:
        cfg.pop("apiKey", None)
    return cfg


def llm_public(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    stored = raw if isinstance(raw, dict) else _stored_llm()
    cfg = _merge_llm_stored(stored)
    api_key = cfg.get("apiKey") or ""
    sampling = cfg.get("sampling") or {}
    return {
        "enabled": bool(cfg["enabled"]),
        "chatCompletionSource": cfg["chatCompletionSource"],
        "apiMode": cfg["apiMode"],
        "baseUrl": cfg["baseUrl"],
        "model": cfg["model"],
        "promptPostProcessing": cfg["promptPostProcessing"],
        "customIncludeHeaders": cfg["customIncludeHeaders"],
        "customIncludeBody": cfg["customIncludeBody"],
        "customExcludeBody": cfg["customExcludeBody"],
        "proxyUrl": cfg["proxyUrl"],
        "timeoutSec": cfg["timeoutSec"],
        "sampling": sampling,
        "configured": bool(cfg["configured"]),
        "fromEnv": bool(cfg["fromEnvKey"] or cfg["fromEnvBase"] or cfg["fromEnvModel"]),
        "fromEnvKey": bool(cfg["fromEnvKey"]),
        "apiKeyHint": _api_key_hint(str(api_key)),
    }


def _default_dim_for_model(model: str) -> int:
    for row in LOCAL_EMBED_MODELS:
        if row["value"] == model and row.get("dim"):
            try:
                return int(row["dim"])
            except (TypeError, ValueError):
                pass
    if "large" in model.lower():
        return 3072
    if "ada" in model.lower():
        return 1536
    return DEFAULT_EMBED_DIM


def _merge_embed_stored(stored: dict[str, Any]) -> dict[str, Any]:
    env = _embed_env()
    provider = (
        _strip(env.get("provider"))
        or _strip(stored.get("provider"))
        or DEFAULT_EMBED_PROVIDER
    ).lower()
    if provider not in {"local", "openai"}:
        provider = DEFAULT_EMBED_PROVIDER
    use_main_llm = bool(stored.get("useMainLlm") if "useMainLlm" in stored else stored.get("use_main_llm", False))
    llm = _merge_llm_stored(_stored_llm()) if use_main_llm else None
    base_url = normalize_openai_base(
        _strip(env.get("baseUrl"))
        or _strip(stored.get("baseUrl") or stored.get("base_url"))
        or (llm or {}).get("baseUrl", ""),
        default=DEFAULT_LLM_BASE,
    )
    model = (
        _strip(env.get("model"))
        or _strip(stored.get("model"))
        or (llm or {}).get("model", "")
        or DEFAULT_EMBED_MODEL
    )
    api_key = (
        _strip(env.get("apiKey"))
        or _strip(stored.get("apiKey") or stored.get("api_key"))
        or (llm or {}).get("apiKey", "")
    )
    dim = env.get("dim") if isinstance(env.get("dim"), int) else stored.get("dim")
    try:
        dim_i = int(dim) if dim is not None else _default_dim_for_model(model)
    except (TypeError, ValueError):
        dim_i = _default_dim_for_model(model)
    enabled = bool(stored.get("enabled", True))
    top_k = _optional_int(stored.get("topK") if "topK" in stored else stored.get("top_k"))
    min_score = _optional_float(stored.get("minScore") if "minScore" in stored else stored.get("min_score"))
    chunk_size = _optional_int(stored.get("chunkSize") if "chunkSize" in stored else stored.get("chunk_size"))
    device = normalize_embed_device(env.get("device") or stored.get("device"))
    if not device:
        device = default_embed_device()
    configured = enabled and bool(model) and (provider == "local" or bool(api_key))
    return {
        "enabled": enabled,
        "provider": provider,
        "useMainLlm": use_main_llm,
        "baseUrl": base_url,
        "model": model,
        "apiKey": api_key,
        "dim": dim_i,
        "device": device,
        "topK": max(1, min(50, top_k if top_k is not None else DEFAULT_EMBED_TOP_K)),
        "minScore": max(0.0, min(1.0, min_score if min_score is not None else DEFAULT_EMBED_MIN_SCORE)),
        "chunkSize": max(100, min(2000, chunk_size if chunk_size is not None else DEFAULT_EMBED_CHUNK_SIZE)),
        "fromEnv": bool(env),
        "configured": configured,
    }


def resolve_embed_config(
    *,
    include_secret: bool = False,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stored = {**_stored_embed(), **(override or {})}
    cfg = _merge_embed_stored(stored)
    if not include_secret:
        cfg.pop("apiKey", None)
    return cfg


def embed_public(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    stored = raw if isinstance(raw, dict) else _stored_embed()
    cfg = _merge_embed_stored(stored)
    api_key = cfg.get("apiKey") or ""
    return {
        "enabled": bool(cfg["enabled"]),
        "provider": cfg["provider"],
        "useMainLlm": bool(cfg["useMainLlm"]),
        "baseUrl": cfg["baseUrl"],
        "model": cfg["model"],
        "dim": int(cfg["dim"]),
        "device": str(cfg.get("device") or DEFAULT_EMBED_DEVICE),
        "devices": local_embed_devices(),
        "topK": int(cfg["topK"]),
        "minScore": float(cfg["minScore"]),
        "chunkSize": int(cfg["chunkSize"]),
        "configured": bool(cfg["configured"]),
        "fromEnv": bool(cfg["fromEnv"]),
        "apiKeyHint": _api_key_hint(str(api_key)),
    }


def llm_request_headers(cfg: dict[str, Any]) -> dict[str, str]:
    api_key = _strip(cfg.get("apiKey"))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    headers.update(parse_custom_headers(_strip(cfg.get("customIncludeHeaders"))))
    return headers


def llm_sampling_payload(cfg: dict[str, Any]) -> dict[str, Any]:
    """对齐 BrewStory 对话预设：写入 OpenAI-compatible chat/completions body。"""
    sampling = cfg.get("sampling") if isinstance(cfg.get("sampling"), dict) else {}
    out: dict[str, Any] = {}
    if (v := _optional_float(sampling.get("temperature"))) is not None:
        out["temperature"] = v
    if (v := _optional_float(sampling.get("topP"))) is not None:
        out["top_p"] = v
    if (v := _optional_int(sampling.get("maxTokens"))) is not None:
        out["max_tokens"] = max(1, v)
    if (v := _optional_float(sampling.get("frequencyPenalty"))) is not None:
        out["frequency_penalty"] = v
    if (v := _optional_float(sampling.get("presencePenalty"))) is not None:
        out["presence_penalty"] = v
    # 部分上游（如 Gemini 网关）要求 top_k ∈ [1, 65)；0 / 空表示不传
    if (v := _optional_int(sampling.get("topK"))) is not None and 1 <= v <= 64:
        out["top_k"] = v
    if (v := _optional_float(sampling.get("minP"))) is not None and v > 0:
        out["min_p"] = v
    if (v := _optional_float(sampling.get("repetitionPenalty"))) is not None and v > 0:
        out["repetition_penalty"] = v
    seed = _optional_int(sampling.get("seed"))
    if seed is not None and seed >= 0:
        out["seed"] = seed
    n = _optional_int(sampling.get("n"))
    if n is not None:
        out["n"] = max(1, min(8, n))
    # stream 由调用方决定；预设里的 streamOpenai 留给前端/助手可选读取
    if sampling.get("showThoughts"):
        # 兼容部分推理模型；未知字段多数网关会忽略
        out["include_reasoning"] = True
    return out


def chat_completions_url(base_url: str) -> str:
    base = normalize_openai_base(base_url)
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def models_list_url(base_url: str) -> str:
    base = normalize_openai_base(base_url)
    if base.endswith("/models"):
        return base
    return f"{base}/models"


def embeddings_url(base_url: str) -> str:
    base = normalize_openai_base(base_url)
    if base.endswith("/embeddings"):
        return base
    return f"{base}/embeddings"


def _stored_web_search() -> dict[str, Any]:
    raw = settings_store.get_setting(AI_WEB_SEARCH_KEY) or {}
    return raw if isinstance(raw, dict) else {}


def _stored_assistant() -> dict[str, Any]:
    raw = settings_store.get_setting(AI_ASSISTANT_KEY) or {}
    return raw if isinstance(raw, dict) else {}


def _web_search_env() -> dict[str, str]:
    out: dict[str, str] = {}
    key = _strip(os.environ.get("WEB_SEARCH_API_KEY")) or _strip(
        os.environ.get("SERPER_API_KEY")
    ) or _strip(os.environ.get("BRAVE_API_KEY"))
    provider = _strip(os.environ.get("WEB_SEARCH_PROVIDER")).lower()
    base = _strip(os.environ.get("SEARXNG_BASE_URL")) or _strip(
        os.environ.get("WEB_SEARCH_BASE_URL")
    )
    if key:
        out["apiKey"] = key
    if provider in WEB_SEARCH_PROVIDERS:
        out["provider"] = provider
    if base:
        out["baseUrl"] = base.rstrip("/")
    return out


def _merge_web_search_stored(stored: dict[str, Any]) -> dict[str, Any]:
    env = _web_search_env()
    api_key = _strip(env.get("apiKey")) or _strip(stored.get("apiKey") or stored.get("api_key"))
    provider = (
        _strip(env.get("provider"))
        or _strip(stored.get("provider"))
        or DEFAULT_WEB_SEARCH_PROVIDER
    ).lower()
    if provider not in WEB_SEARCH_PROVIDERS:
        provider = DEFAULT_WEB_SEARCH_PROVIDER
    base_url = (
        _strip(env.get("baseUrl"))
        or _strip(stored.get("baseUrl") or stored.get("base_url"))
        or (DEFAULT_SEARXNG_BASE if provider == "searxng" else "")
    ).rstrip("/")
    enabled = bool(stored.get("enabled", False))
    if provider == "searxng":
        configured = bool(base_url)
    else:
        configured = bool(api_key)
    return {
        "enabled": enabled,
        "provider": provider,
        "apiKey": api_key,
        "baseUrl": base_url,
        "configured": configured,
        "fromEnvKey": bool(env.get("apiKey")),
        "fromEnvBase": bool(env.get("baseUrl")),
    }


def resolve_web_search_config(*, include_secret: bool = False) -> dict[str, Any]:
    cfg = _merge_web_search_stored(_stored_web_search())
    if not include_secret:
        cfg.pop("apiKey", None)
    return cfg


def web_search_public(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    stored = raw if isinstance(raw, dict) else _stored_web_search()
    cfg = _merge_web_search_stored(stored)
    return {
        "enabled": bool(cfg["enabled"]),
        "provider": cfg["provider"],
        "baseUrl": cfg.get("baseUrl") or "",
        "configured": bool(cfg["configured"]),
        "fromEnv": bool(cfg["fromEnvKey"] or cfg.get("fromEnvBase")),
        "apiKeyHint": _api_key_hint(str(cfg.get("apiKey") or "")),
    }


def resolve_assistant_config() -> dict[str, Any]:
    from app.ai.assistant_protocol import (
        ASSISTANT_SKILL_GROUPS,
        ASSISTANT_TOOL_META,
        DEFAULT_ASSISTANT_TOOLS,
        DEFAULT_SUGGEST_CHIPS,
        SYSTEM_PROMPT,
    )

    stored = _stored_assistant()
    chips_raw = stored.get("suggestChips") or stored.get("suggest_chips")
    chips: list[str] = []
    if isinstance(chips_raw, list):
        chips = [str(x).strip() for x in chips_raw if str(x).strip()][:12]
    if not chips:
        chips = list(DEFAULT_SUGGEST_CHIPS)
    system = _strip(stored.get("systemPrompt") or stored.get("system_prompt")) or SYSTEM_PROMPT
    tools = _normalize_assistant_tools(stored.get("tools") or stored.get("enabledTools"))
    return {
        "systemPrompt": system,
        "suggestChips": chips,
        "tools": tools,
        "toolMeta": ASSISTANT_TOOL_META,
        "skillGroups": ASSISTANT_SKILL_GROUPS,
    }


def _normalize_assistant_tools(raw: Any) -> dict[str, bool]:
    from app.ai.assistant_protocol import DEFAULT_ASSISTANT_TOOLS

    out = dict(DEFAULT_ASSISTANT_TOOLS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            key = str(k).strip()
            if key in out:
                out[key] = bool(v)
    elif isinstance(raw, list):
        # allow list of enabled tool names
        enabled = {str(x).strip() for x in raw if str(x).strip()}
        if enabled:
            for k in out:
                out[k] = k in enabled
    return out


def assistant_public(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.ai.assistant_protocol import (
        ASSISTANT_SKILL_GROUPS,
        ASSISTANT_TOOL_META,
        DEFAULT_SUGGEST_CHIPS,
        SYSTEM_PROMPT,
    )

    stored = raw if isinstance(raw, dict) else _stored_assistant()
    chips_raw = stored.get("suggestChips") or stored.get("suggest_chips")
    chips: list[str] = []
    if isinstance(chips_raw, list):
        chips = [str(x).strip() for x in chips_raw if str(x).strip()][:12]
    if not chips:
        chips = list(DEFAULT_SUGGEST_CHIPS)
    system = _strip(stored.get("systemPrompt") or stored.get("system_prompt")) or SYSTEM_PROMPT
    tools = _normalize_assistant_tools(stored.get("tools") or stored.get("enabledTools"))
    return {
        "systemPrompt": system,
        "suggestChips": chips,
        "tools": tools,
        "toolMeta": ASSISTANT_TOOL_META,
        "skillGroups": ASSISTANT_SKILL_GROUPS,
    }


def enabled_assistant_tool_names() -> list[str]:
    cfg = resolve_assistant_config()
    tools = cfg.get("tools") if isinstance(cfg.get("tools"), dict) else {}
    return [k for k, on in tools.items() if on]
