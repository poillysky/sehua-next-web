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
        "value": "BAAI/bge-small-zh-v1.5",
        "label": "BGE Small 中文 v1.5（512 维，推荐）",
        "dim": "512",
    },
    {
        "value": "BAAI/bge-base-zh-v1.5",
        "label": "BGE Base 中文 v1.5（768 维）",
        "dim": "768",
    },
    {
        "value": "jinaai/jina-embeddings-v2-base-zh",
        "label": "Jina v2 Base 中文（768 维）",
        "dim": "768",
    },
]

PROMPT_POST_PROCESSING: list[dict[str, str]] = [
    {"value": "", "label": "未选择"},
    {"value": "merge", "label": "合并连续 assistant"},
    {"value": "semi", "label": "半严格交替"},
    {"value": "strict", "label": "严格（用户先说）"},
    {"value": "single", "label": "合并成一条 user 消息"},
    {"value": "merge_tools", "label": "合并连续（含工具）"},
    {"value": "semi_tools", "label": "半严格（含工具）"},
    {"value": "strict_tools", "label": "严格（含工具）"},
]
