"""向量编码：本地 fastembed 或 OpenAI 兼容 /embeddings。"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

import httpx

from .ai_config import resolve_embed_config
from .sehua_embed import format_query_text

log = logging.getLogger(__name__)

_local_model: Any = None
_local_model_name: str | None = None
_local_providers: tuple[str, ...] | None = None
_onnx_dml_patched = False
# DirectML / ONNX Runtime 非线程安全：多番号并发补齐时必须串行编码，否则整进程崩
_local_embed_lock = threading.RLock()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _patch_onnx_for_directml() -> None:
    """DirectML 要求 enable_mem_pattern=False + sequential execution。"""
    global _onnx_dml_patched
    if _onnx_dml_patched:
        return
    try:
        import onnxruntime as ort
        from fastembed.common.onnx_model import OnnxModel
    except ImportError:
        return

    orig = OnnxModel._load_onnx_model

    def _load(
        self: Any,
        model_dir: Any,
        model_file: Any,
        threads: Any,
        providers: Any = None,
        cuda: Any = False,
        device_id: Any = None,
        extra_session_options: Any = None,
    ) -> Any:
        real = ort.InferenceSession

        def wrapped(
            path: Any,
            sess_options: Any = None,
            providers: Any = None,
            **kw: Any,
        ) -> Any:
            so = sess_options or ort.SessionOptions()
            names = [p if isinstance(p, str) else p[0] for p in (providers or [])]
            if "DmlExecutionProvider" in names:
                so.enable_mem_pattern = False
                so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            return real(path, sess_options=so, providers=providers, **kw)

        ort.InferenceSession = wrapped  # type: ignore[misc,assignment]
        try:
            return orig(
                self,
                model_dir,
                model_file,
                threads,
                providers=providers,
                cuda=cuda,
                device_id=device_id,
                extra_session_options=extra_session_options,
            )
        finally:
            ort.InferenceSession = real  # type: ignore[misc,assignment]

    OnnxModel._load_onnx_model = _load  # type: ignore[method-assign]
    _onnx_dml_patched = True


def _resolve_local_providers(*, device: str | None = None) -> list[str]:
    """按设置选择 CPU / CUDA / DirectML。"""
    if _env_flag("EMBED_FORCE_CPU"):
        return ["CPUExecutionProvider"]

    cfg_device = ""
    if device:
        cfg_device = str(device).strip().lower()
    else:
        try:
            from .ai_config import normalize_embed_device, resolve_embed_config

            cfg = resolve_embed_config(include_secret=False)
            cfg_device = normalize_embed_device(cfg.get("device"))
        except Exception:  # noqa: BLE001
            cfg_device = ""

    if cfg_device in {"nvidia", "n"}:
        cfg_device = "cuda"
    elif cfg_device in {"amd", "a", "dml"}:
        cfg_device = "directml"

    env_device = str(os.environ.get("EMBED_DEVICE") or "").strip().lower()
    if env_device in {"nvidia", "n"}:
        env_device = "cuda"
    elif env_device in {"amd", "a", "dml"}:
        env_device = "directml"
    if env_device in {"cpu", "cuda", "directml"}:
        cfg_device = env_device

    try:
        import onnxruntime as ort

        available = set(ort.get_available_providers())
    except ImportError:
        return ["CPUExecutionProvider"]

    if not cfg_device:
        if "DmlExecutionProvider" in available:
            cfg_device = "directml"
        elif "CUDAExecutionProvider" in available:
            cfg_device = "cuda"
        else:
            cfg_device = "cpu"

    if cfg_device == "cuda":
        if "CUDAExecutionProvider" not in available:
            raise RuntimeError(
                "未检测到 N卡 CUDA。请安装 NVIDIA 驱动与 onnxruntime-gpu"
                "（勿与 onnxruntime-directml 同时安装），或改选 CPU / A卡"
            )
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]

    if cfg_device == "directml":
        if "DmlExecutionProvider" not in available:
            raise RuntimeError(
                "未检测到 A卡 DirectML。Windows 请安装 onnxruntime-directml"
                "（勿与 onnxruntime / onnxruntime-gpu 同时安装），或改选 CPU / N卡"
            )
        return ["DmlExecutionProvider", "CPUExecutionProvider"]

    return ["CPUExecutionProvider"]


def _session_providers(model: Any) -> list[str] | None:
    obj: Any = model
    for _ in range(6):
        sess = getattr(obj, "model", None)
        if sess is not None and hasattr(sess, "get_providers"):
            return list(sess.get_providers())
        if sess is None:
            break
        obj = sess
    return None


def reset_local_embed_model() -> None:
    global _local_model, _local_model_name, _local_providers
    with _local_embed_lock:
        _local_model = None
        _local_model_name = None
        _local_providers = None


def _load_local(model_name: str, *, device: str | None = None) -> Any:
    global _local_model, _local_model_name, _local_providers
    providers = tuple(_resolve_local_providers(device=device))
    with _local_embed_lock:
        if (
            _local_model is not None
            and _local_model_name == model_name
            and _local_providers == providers
        ):
            return _local_model
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise RuntimeError(
                "未安装 fastembed。请执行: pip install -r apps/api/requirements-embed.txt"
            ) from e

        if "DmlExecutionProvider" in providers:
            _patch_onnx_for_directml()

        _local_model = None
        _local_model = TextEmbedding(
            model_name=model_name,
            providers=list(providers),
            cuda=False,
        )
        _local_model_name = model_name
        _local_providers = providers
        active = _session_providers(_local_model) or list(providers)
        log.info("local embed model=%s providers=%s", model_name, active)
        return _local_model


def _encode_local(
    texts: list[str],
    *,
    model_name: str,
    query: bool,
    device: str | None = None,
) -> list[list[float]]:
    with _local_embed_lock:
        model = _load_local(model_name, device=device)
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
    device = str(cfg.get("device") or "") or None
    if cfg["provider"] == "local":
        payload = texts
        if query and len(texts) == 1:
            payload = [format_query_text(texts[0], model=model)]
        return _encode_local(payload, model_name=model, query=query, device=device)
    payload = texts
    if query and len(texts) == 1:
        payload = [format_query_text(texts[0], model=model)]
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
    device = str(cfg.get("device") or "") or None
    if cfg["provider"] == "local":
        payload = texts
        if query and len(texts) == 1:
            payload = [format_query_text(texts[0], model=model)]
        return _encode_local(payload, model_name=model, query=query, device=device)
    return await _encode_openai(
        texts,
        base_url=str(cfg["baseUrl"]),
        model=model,
        api_key=str(cfg.get("apiKey") or ""),
        dim=dim,
    )


async def test_embed_connection(*, override: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = resolve_embed_config(include_secret=True, override=override)
    device = str(cfg.get("device") or "") or None
    if cfg["provider"] == "local":
        reset_local_embed_model()
        payload = ["向量连接测试"]
        vecs = _encode_local(
            payload,
            model_name=str(cfg["model"]),
            query=False,
            device=device,
        )
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
        "device": device or "cpu",
    }


def ensure_local_model_files(
    *,
    model_name: str | None = None,
    override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """确保当前配置的本地模型已在缓存；已有则跳过，没有则下载。"""
    cfg = resolve_embed_config(include_secret=False, override=override)
    if str(cfg.get("provider") or "") != "local":
        raise RuntimeError("仅本地 fastembed 需要下载模型文件")
    name = str(model_name or cfg.get("model") or "").strip()
    if not name:
        raise RuntimeError("未指定嵌入模型")

    try:
        from fastembed import TextEmbedding
        from fastembed.common.utils import define_cache_dir
    except ImportError as e:
        raise RuntimeError(
            "未安装 fastembed。请执行: pip install -r apps/api/requirements-embed.txt"
        ) from e

    cache_dir = str(define_cache_dir(None))
    providers = ["CPUExecutionProvider"]

    def _probe(*, local_only: bool) -> None:
        TextEmbedding(
            model_name=name,
            providers=providers,
            cuda=False,
            lazy_load=True,
            local_files_only=local_only,
        )

    try:
        _probe(local_only=True)
        return {
            "ok": True,
            "skipped": True,
            "downloaded": False,
            "model": name,
            "cacheDir": cache_dir,
            "message": f"已缓存，跳过下载 · {name}",
        }
    except Exception:  # noqa: BLE001
        pass

    try:
        _probe(local_only=False)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"下载失败 · {name}：{e}") from e

    return {
        "ok": True,
        "skipped": False,
        "downloaded": True,
        "model": name,
        "cacheDir": cache_dir,
        "message": f"已下载 · {name}",
    }
