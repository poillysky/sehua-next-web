"""AI 设置页预设（对齐 BrewStory 模型连接 / 向量插件）。"""

from __future__ import annotations

CHAT_SOURCES: list[dict[str, str]] = [
    {"value": "custom", "label": "自定义（通用兼容接口）"},
    {"value": "openai", "label": "OpenAI", "baseUrl": "https://api.openai.com/v1"},
    {
        "value": "openrouter",
        "label": "OpenRouter",
        "baseUrl": "https://openrouter.ai/api/v1",
    },
    {
        "value": "deepseek",
        "label": "DeepSeek",
        "baseUrl": "https://api.deepseek.com/v1",
    },
    {"value": "groq", "label": "Groq", "baseUrl": "https://api.groq.com/openai/v1"},
    {
        "value": "mistralai",
        "label": "MistralAI",
        "baseUrl": "https://api.mistral.ai/v1",
    },
    {"value": "xai", "label": "xAI (Grok)", "baseUrl": "https://api.x.ai/v1"},
    {
        "value": "moonshot",
        "label": "Moonshot AI",
        "baseUrl": "https://api.moonshot.cn/v1",
    },
    {
        "value": "siliconflow",
        "label": "SiliconFlow",
        "baseUrl": "https://api.siliconflow.cn/v1",
    },
    {
        "value": "fireworks",
        "label": "Fireworks AI",
        "baseUrl": "https://api.fireworks.ai/inference/v1",
    },
]

OPENAI_EMBED_MODELS: list[dict[str, str]] = [
    {"value": "text-embedding-3-small", "label": "text-embedding-3-small (1536)"},
    {"value": "text-embedding-3-large", "label": "text-embedding-3-large (3072)"},
    {"value": "text-embedding-ada-002", "label": "text-embedding-ada-002 (1536)"},
]

LOCAL_EMBED_MODELS: list[dict[str, str]] = [
    {
        "value": "intfloat/multilingual-e5-large",
        "label": "E5 Large 多语种（1024 维，中日英跨语检索 · 推荐）",
        "dim": "1024",
    },
    {
        "value": "jinaai/jina-embeddings-v3",
        "label": "Jina v3 多语种（1024 维）",
        "dim": "1024",
    },
    {
        "value": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "label": "Multilingual MPNet（768 维，轻量多语）",
        "dim": "768",
    },
    {
        "value": "BAAI/bge-small-zh-v1.5",
        "label": "BGE Small 中文 v1.5（512 维，仅中文）",
        "dim": "512",
    },
    {
        "value": "BAAI/bge-base-zh-v1.5",
        "label": "BGE Base 中文 v1.5（768 维，仅中文）",
        "dim": "768",
    },
    {
        "value": "jinaai/jina-embeddings-v2-base-zh",
        "label": "Jina v2 Base 中文（768 维）",
        "dim": "768",
    },
]

# 本地推理设备：CPU / NVIDIA CUDA / AMD DirectML
LOCAL_EMBED_DEVICES: list[dict[str, str]] = [
    {
        "value": "cpu",
        "label": "CPU",
        "hint": "兼容最好，速度慢",
    },
    {
        "value": "cuda",
        "label": "N卡 (CUDA)",
        "hint": "需 NVIDIA 驱动 + onnxruntime-gpu",
    },
    {
        "value": "directml",
        "label": "A卡 (DirectML)",
        "hint": "Windows AMD/Intel；需 onnxruntime-directml",
    },
]

PROMPT_POST_PROCESSING: list[dict[str, str]] = [
    {"value": "", "label": "未选择（对话助手忽略此项）"},
    {"value": "merge", "label": "合并连续 assistant"},
    {"value": "semi", "label": "半严格交替"},
    {"value": "strict", "label": "严格（用户先说）"},
    {"value": "single", "label": "合并成一条 user 消息"},
    {"value": "merge_tools", "label": "合并连续（含工具）"},
    {"value": "semi_tools", "label": "半严格（含工具）"},
    {"value": "strict_tools", "label": "严格（含工具）"},
]

WEB_SEARCH_PROVIDERS: list[dict[str, str]] = [
    {
        "value": "searxng",
        "label": "SearXNG（自建免费）",
        "hint": "http://192.168.2.38:8085",
    },
    {
        "value": "serper",
        "label": "Serper (Google)",
        "hint": "https://serper.dev",
    },
    {
        "value": "brave",
        "label": "Brave Search",
        "hint": "https://brave.com/search/api",
    },
]

