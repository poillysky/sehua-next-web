"""向量编码：本地 fastembed 或 OpenAI 兼容 /embeddings。"""

from __future__ import annotations

from typing import Any

import httpx

from .ai_config import resolve_embed_config
from .sehua_embed import format_query_text


_local_model: Any = None
_local_model_name: str | None = None


def _load_local(model_name: str) -> Any:
    global _local_model, _local_model_name
    if _local_model is not None and _local_model_name == model_name:
        return _local_model
    try:
        from fastembed import TextEmbedding
    except ImportError as e:
        raise RuntimeError(
            "未安装 fastembed。请执行: pip install -r apps/api/requirements-embed.txt"
        ) from e
    _local_model = TextEmbedding(model_name=model_name)
    _local_model_name = model_name
    return _local_model


def _encode_local(texts: list[str], *, model_name: str, query: bool) -> list[list[float]]:
    model = _load_local(model_name)
    if query and len(texts) == 1 and hasattr(model, "query_embed"):
        vecs = list(model.query_embed(texts))
        if vecs:
            return [list(map(float, vecs[0]))]
    return [list(map(float, vec)) for vec in model.embed(texts)]


async def _encode_openai(
    texts: list[str],
    *,
    base_url: str,
    model: str,
    api_key: str,
    dim: int | None = None,
) -> list[list[float]]:
    if not api_key:
        raise RuntimeError("OpenAI 兼容向量需配置 API Key")
    url = base_url.rstrip("/")
    if not url.endswith("/embeddings"):
        url = f"{url}/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"model": model, "input": texts}
    if dim and dim > 0:
        payload["dimensions"] = int(dim)
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        r = await client.post(url, headers=headers, json=payload)
    if r.status_code == 401:
        raise RuntimeError("API Key 无效")
    if not r.is_success:
        raise RuntimeError(f"embeddings 返回 {r.status_code}: {r.text[:200]}")
    data = r.json().get("data") or []
    if len(data) != len(texts):
        raise RuntimeError(f"向量条数不匹配: {len(data)} != {len(texts)}")
    out: list[list[float]] = []
    for item in sorted(data, key=lambda x: int(x.get("index") or 0)):
        vec = item.get("embedding")
        if not isinstance(vec, list):
            raise RuntimeError("embedding 字段无效")
        out.append([float(x) for x in vec])
    return out


def _encode_openai_sync(
    texts: list[str],
    *,
    base_url: str,
    model: str,
    api_key: str,
    dim: int | None = None,
) -> list[list[float]]:
    if not api_key:
        raise RuntimeError("OpenAI 兼容向量需配置 API Key")
    url = base_url.rstrip("/")
    if not url.endswith("/embeddings"):
        url = f"{url}/embeddings"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"model": model, "input": texts}
    if dim and dim > 0:
        payload["dimensions"] = int(dim)
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        r = client.post(url, headers=headers, json=payload)
    if r.status_code == 401:
        raise RuntimeError("API Key 无效")
    if not r.is_success:
        raise RuntimeError(f"embeddings 返回 {r.status_code}: {r.text[:200]}")
    data = r.json().get("data") or []
    if len(data) != len(texts):
        raise RuntimeError(f"向量条数不匹配: {len(data)} != {len(texts)}")
    out: list[list[float]] = []
    for item in sorted(data, key=lambda x: int(x.get("index") or 0)):
        vec = item.get("embedding")
        if not isinstance(vec, list):
            raise RuntimeError("embedding 字段无效")
        out.append([float(x) for x in vec])
    return out


def encode_texts_sync(texts: list[str], *, query: bool = False) -> list[list[float]]:
    cfg = resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        raise RuntimeError("向量模型未启用")
    model = str(cfg["model"])
    dim = int(cfg["dim"]) if cfg.get("dim") else None
    if cfg["provider"] == "local":
        payload = texts
        if query and len(texts) == 1:
            payload = [format_query_text(texts[0])]
        return _encode_local(payload, model_name=model, query=query)
    payload = texts
    if query and len(texts) == 1:
        payload = [format_query_text(texts[0])]
    return _encode_openai_sync(
        payload,
        base_url=str(cfg["baseUrl"]),
        model=model,
        api_key=str(cfg.get("apiKey") or ""),
        dim=dim,
    )


async def encode_texts_async(texts: list[str], *, query: bool = False) -> list[list[float]]:
    cfg = resolve_embed_config(include_secret=True)
    if not cfg.get("enabled"):
        raise RuntimeError("向量模型未启用")
    model = str(cfg["model"])
    dim = int(cfg["dim"]) if cfg.get("dim") else None
    if cfg["provider"] == "local":
        payload = texts
        if query and len(texts) == 1:
            payload = [format_query_text(texts[0])]
        return _encode_local(payload, model_name=model, query=query)
    return await _encode_openai(
        texts,
        base_url=str(cfg["baseUrl"]),
        model=model,
        api_key=str(cfg.get("apiKey") or ""),
        dim=dim,
    )


async def test_embed_connection(*, override: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = resolve_embed_config(include_secret=True, override=override)
    if cfg["provider"] == "local":
        payload = ["向量连接测试"]
        vecs = _encode_local(payload, model_name=str(cfg["model"]), query=False)
    else:
        vecs = await _encode_openai(
            ["向量连接测试"],
            base_url=str(cfg["baseUrl"]),
            model=str(cfg["model"]),
            api_key=str(cfg.get("apiKey") or ""),
            dim=int(cfg["dim"]) if cfg.get("dim") else None,
        )
    dim = len(vecs[0]) if vecs else 0
    return {
        "ok": True,
        "provider": cfg["provider"],
        "model": cfg["model"],
        "dim": dim,
    }
