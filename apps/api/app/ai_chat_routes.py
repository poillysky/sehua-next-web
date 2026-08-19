"""对话搜资源：向量检索 → LLM 整理回复；失败再抽关键词搜。"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth_routes import get_optional_user
from .ai_config import (
    chat_completions_url,
    llm_request_headers,
    llm_sampling_payload,
    resolve_llm_config,
)
from .conn_settings_routes import Envelope

router = APIRouter(prefix="/ai", tags=["ai"])

EXTRACT_PROMPT = """你是资源仓库的检索助手。根据用户自然语言，提取适合在资源库标题/文件名里搜的关键词。
只输出一个 JSON 对象，不要 markdown、不要解释：
{"keyword":"2到40字搜索词","reply":"不超过40字中文说明"}
规则：
- 番号原样保留（如 SSIS-001）
- 女优名、片名、类型词保留，去掉「帮我找」「有没有」等口语
- keyword 不要写成完整句子
- 若无法提取，keyword 取用户话里最有信息量的词"""

ORGANIZE_PROMPT = """你是资源仓库的对话助手。用户在用自然语言找片。
下面 JSON 里 hits 是已经检索到的候选（按相关度排序，title 已清洗）。
根据用户问题写一句不超过 60 字的中文回复：
- 点出最贴的 1～3 部，优先「番号 + 短片名」
- 不要罗列全部，不要编造 hits 里没有的片
- 不要 Discuz / 论坛套话，不要提向量、关键词、分数
只输出 JSON：{"reply":"..."}"""


class ChatTurn(BaseModel):
    role: str
    content: str


class AiChatSearchBody(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)


def _extract_json(text: str) -> dict[str, str]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): data[k] for k in data}
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return {str(k): data[k] for k in data} if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _fallback_keyword(message: str) -> str:
    s = re.sub(r"^(帮我找|找一下|有没有|搜一下|搜索|看看)", "", message.strip())
    s = s.strip(" ？?，,。.!！")
    return s[:40] or message.strip()[:40]


def compact_hits(resources: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    from .sehua_embed import display_hit_label

    out: list[dict[str, Any]] = []
    for i, item in enumerate(resources[:limit], 1):
        score = item.get("score")
        row: dict[str, Any] = {
            "n": i,
            "title": display_hit_label(
                title=item.get("title"),
                description=item.get("description"),
                filename=item.get("name") or item.get("filename"),
            ),
        }
        board = str(item.get("board_name") or "").strip()
        if board:
            row["board"] = board[:24]
        if isinstance(score, (int, float)):
            row["score"] = round(float(score), 2)
        out.append(row)
    return out


def _mechanical_reply(total: int, mode: str, keyword: str = "") -> str:
    if total <= 0:
        return "没搜到贴得上的，换个番号、女优或类型再试试"
    if mode == "semantic":
        return f"给你找了 {total} 条相近的"
    if keyword:
        return f"「{keyword}」搜到 {total} 条"
    return f"搜到 {total} 条"


async def _llm_json(
    messages: list[dict[str, str]],
    cfg: dict[str, Any],
    *,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    api_key = str(cfg.get("apiKey") or "").strip()
    model = str(cfg.get("model") or "").strip()
    base_url = str(cfg.get("baseUrl") or "").strip()
    if not (api_key and model and base_url):
        return {}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    payload.update(llm_sampling_payload(cfg))
    payload["temperature"] = temperature
    timeout = max(8, min(60, int(cfg.get("timeoutSec") or 30)))
    url = chat_completions_url(base_url)
    headers = llm_request_headers(cfg)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=8.0)) as client:
        r = await client.post(url, headers=headers, json=payload)
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="LLM API Key 无效")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"LLM 返回 {r.status_code}: {r.text[:200]}")
    reply = ""
    try:
        choices = (r.json() or {}).get("choices") or []
        if choices:
            reply = str((choices[0].get("message") or {}).get("content") or "").strip()
    except Exception:
        reply = ""
    return _extract_json(reply)


async def _llm_extract(message: str, history: list[ChatTurn], cfg: dict[str, Any]) -> dict[str, str]:
    messages: list[dict[str, str]] = [{"role": "system", "content": EXTRACT_PROMPT}]
    for turn in history[-6:]:
        role = turn.role if turn.role in {"user", "assistant"} else "user"
        content = (turn.content or "").strip()
        if content:
            messages.append({"role": role, "content": content[:400]})
    messages.append({"role": "user", "content": message[:400]})
    parsed = await _llm_json(messages, cfg, max_tokens=160, temperature=0.2)
    return {
        "keyword": str(parsed.get("keyword") or "").strip(),
        "reply": str(parsed.get("reply") or "").strip(),
    }


async def _llm_organize(
    message: str,
    hits: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> str:
    if not hits:
        return ""
    body = json.dumps({"q": message[:200], "hits": hits}, ensure_ascii=False)
    parsed = await _llm_json(
        [
            {"role": "system", "content": ORGANIZE_PROMPT},
            {"role": "user", "content": body},
        ],
        cfg,
        max_tokens=140,
        temperature=0.3,
    )
    reply = str(parsed.get("reply") or "").strip()
    reply = re.sub(r"\s+", " ", reply)
    return reply[:80]


async def _safe_organize(
    message: str,
    resources: list[dict[str, Any]],
    cfg: dict[str, Any],
    llm_ok: bool,
) -> tuple[str, bool]:
    if not (llm_ok and resources):
        return "", False
    try:
        reply = await _llm_organize(message, compact_hits(resources), cfg)
        return reply, bool(reply)
    except Exception:
        return "", False


@router.post("/chat-search", response_model=Envelope)
async def ai_chat_search(
    body: AiChatSearchBody,
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Envelope:
    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="请输入要找的内容")

    cfg = resolve_llm_config(include_secret=True)
    llm_ok = bool(cfg.get("enabled") and cfg.get("configured"))
    used_llm = False

    from .sehua_vector_search import search_semantic

    semantic = await search_semantic(message)
    resources: list[dict[str, Any]] = []
    total = 0
    search_mode = "keyword"
    keyword = ""
    reply = ""

    if semantic.get("ok") and semantic.get("resources"):
        search_mode = "semantic"
        resources = list(semantic["resources"])
        total = int(semantic.get("total") or len(resources))
        organized, used_llm = await _safe_organize(message, resources, cfg, llm_ok)
        reply = organized or _mechanical_reply(total, "semantic")
        return Envelope(
            data={
                "reply": reply,
                "keyword": keyword,
                "usedLlm": used_llm,
                "searchMode": search_mode,
                "resources": resources,
                "total_count": total,
            },
            message="ok",
        )

    if llm_ok:
        try:
            parsed = await _llm_extract(message, body.history, cfg)
            keyword = str(parsed.get("keyword") or "").strip()
            reply = str(parsed.get("reply") or "").strip()
            used_llm = bool(keyword or reply)
        except HTTPException:
            raise
        except Exception as e:
            reply = f"模型调用失败，改用原文搜索。{e}"

    if not keyword:
        keyword = _fallback_keyword(message)
    if not reply:
        reply = f"正在搜「{keyword or message}」"

    if len(keyword) < 2:
        return Envelope(
            data={
                "reply": reply or "再说具体一点，比如片名、番号或女优名",
                "keyword": "",
                "usedLlm": used_llm,
                "searchMode": "keyword",
                "resources": [],
                "total_count": 0,
            },
            message="ok",
        )

    reason = str(semantic.get("reason") or "")
    try:
        from . import resource_service

        data = resource_service.search_resources(
            keyword=keyword,
            p=1,
            ps=6,
            sort_type="default",
            match_mode="smart",
            with_total_count=True,
        )
        resources = data.get("resources") or []
        total = int(data.get("total_count") or 0)
    except Exception as e:
        return Envelope(
            data={
                "reply": f"{reply}。搜索失败：{e}",
                "keyword": keyword,
                "usedLlm": used_llm,
                "searchMode": "keyword",
                "resources": [],
                "total_count": 0,
            },
            message="search-failed",
        )

    hint = ""
    if reason == "empty":
        hint = "向量库还是空的"
    elif reason == "dim-mismatch":
        hint = (
            f"向量库 {semantic.get('storedDim')} 维，"
            f"当前模型 {semantic.get('queryDim')} 维，对不上"
        )
    elif reason == "below-min-score":
        hint = "语义分不够"
    elif reason == "embed-disabled":
        hint = "向量未启用"
    elif reason.startswith("embed-error") or reason.startswith("pg-error"):
        hint = "语义检索不可用"

    if resources:
        organized, organized_ok = await _safe_organize(message, resources, cfg, llm_ok)
        if organized_ok:
            used_llm = True
            reply = organized
        elif total > len(resources):
            reply = f"{reply} · 关键词 {total} 条，先看前 {len(resources)} 条"
            if hint:
                reply = f"{reply}（{hint}）"
        elif hint:
            reply = f"{reply} · 关键词 {len(resources)} 条（{hint}）"
        else:
            reply = reply or _mechanical_reply(total, "keyword", keyword)
    else:
        reply = f"{reply}。没有匹配「{keyword}」"
        if hint:
            reply = f"{reply}（{hint}，已改关键词）"

    return Envelope(
        data={
            "reply": reply,
            "keyword": keyword,
            "usedLlm": used_llm,
            "searchMode": "keyword",
            "resources": resources,
            "total_count": total,
        },
        message="ok",
    )
