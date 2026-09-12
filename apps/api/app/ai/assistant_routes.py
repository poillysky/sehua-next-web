"""小花智能搜片助手：多工具 agent + 可选 SSE。"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth.routes import get_optional_user
from app.ai.assistant_protocol import (
    BEHAVIOR_APPENDIX,
    SYSTEM_PROMPT,
    compact_cards_for_llm,
    user_wants_resource_cards,
)
from app.ai.assistant_tools import (
    TOOL_STATUS_LABEL,
    collect_cards_from_results,
    collect_ui_cards,
    dispatch_tool,
    filter_tools_by_enabled,
    filter_tools_by_prefer,
    heuristic_local_search,
    tool_definitions,
    tool_result_for_llm,
)
from app.ai.chat_preset_store import active_system_prompt, merge_active_sampling
from app.ai.config import (
    chat_completions_url,
    enabled_assistant_tool_names,
    llm_request_headers,
    llm_sampling_payload,
    resolve_assistant_config,
    resolve_llm_config,
    resolve_web_search_config,
)
from app.core.conn_settings_routes import Envelope

router = APIRouter(prefix="/ai", tags=["ai"])

MAX_TOOL_STEPS = 6


class ChatTurn(BaseModel):
    role: str
    content: str
    summary: str | None = None


class AssistantChatBody(BaseModel):
    message: str
    history: list[ChatTurn] = Field(default_factory=list)
    prefer_sources: list[str] = Field(default_factory=list, alias="preferSources")
    stream: bool = False

    model_config = {"populate_by_name": True}


def _history_messages(history: list[ChatTurn]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for turn in history[-8:]:
        role = turn.role if turn.role in {"user", "assistant"} else "user"
        content = (turn.content or "").strip()
        if turn.summary:
            content = f"{content}\n（上次工具摘要：{turn.summary.strip()[:240]}）"
        if content:
            out.append({"role": role, "content": content[:800]})
    return out


async def _llm_chat(
    messages: list[dict[str, Any]],
    cfg: dict[str, Any],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
    max_tokens: int = 600,
) -> dict[str, Any]:
    api_key = str(cfg.get("apiKey") or "").strip()
    model = str(cfg.get("model") or "").strip()
    base_url = str(cfg.get("baseUrl") or "").strip()
    if not (api_key and model and base_url):
        raise HTTPException(status_code=400, detail="请先在设置中配置聊天模型")

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    payload.update(llm_sampling_payload(cfg))
    if tools:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

    timeout = max(12, min(90, int(cfg.get("timeoutSec") or 45)))
    url = chat_completions_url(base_url)
    headers = llm_request_headers(cfg)
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        r = await client.post(url, headers=headers, json=payload)
    if r.status_code == 401:
        raise HTTPException(status_code=400, detail="LLM API Key 无效")
    if not r.is_success:
        raise HTTPException(status_code=502, detail=f"LLM 返回 {r.status_code}: {r.text[:220]}")
    try:
        data = r.json() or {}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 响应无法解析: {e}") from e
    choices = data.get("choices") or []
    if not choices:
        return {}
    return choices[0].get("message") or {}


def _mechanical_reply(cards: list[dict[str, Any]]) -> str:
    if not cards:
        return "没搜到贴得上的，换个番号、女优、片名或类型再试试"
    by_src: dict[str, int] = {}
    for c in cards:
        src = str(c.get("source") or "")
        by_src[src] = by_src.get(src, 0) + 1
    parts = []
    labels = {"sehua": "仓库", "scrap": "片商", "magnet": "磁力", "media": "影视", "web": "网络"}
    for k, n in by_src.items():
        parts.append(f"{labels.get(k, k)} {n}")
    top = cards[0]
    title = str(top.get("subtitle") or top.get("title") or "")[:40]
    return f"找到一些结果（{' · '.join(parts)}），先看「{title}」"


def _build_system(prefer: list[str], enabled_tools: list[str] | None = None) -> str:
    # 优先：启用中的聊天预设提示词 → 设置里的小花 systemPrompt → 内置默认
    preset_text = active_system_prompt()
    if preset_text:
        base = preset_text
    else:
        cfg = resolve_assistant_config()
        base = str(cfg.get("systemPrompt") or SYSTEM_PROMPT).strip() or SYSTEM_PROMPT
    base = base.rstrip() + "\n" + BEHAVIOR_APPENDIX.strip()
    if enabled_tools is not None:
        if enabled_tools:
            base += f"\n\n当前可用工具（仅可调用这些）：{', '.join(enabled_tools)}。"
        else:
            base += "\n\n当前未启用任何检索工具；请如实告知用户去设置里打开技能。"
    if prefer:
        base += f"\n\n用户希望优先检索来源：{', '.join(prefer)}。尽量先用对应工具。"
    return base


async def _dispatch_tool_calls(
    tool_calls: list[dict[str, Any]],
    *,
    step_idx: int,
    emit: Any,
) -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    """并行执行同一轮多个 tool_calls；返回 (call_id, name, result, step) 且顺序与输入一致。"""

    async def one(call: dict[str, Any]) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        fn = call.get("function") or {}
        name = str(fn.get("name") or "").strip()
        args_raw = fn.get("arguments") or "{}"
        call_id = str(call.get("id") or name)
        label = TOOL_STATUS_LABEL.get(name, f"正在调用 {name}…")
        await emit("status", {"text": label, "tool": name})
        result = await dispatch_tool(name, args_raw)
        result["_step"] = step_idx
        query = ""
        if isinstance(result.get("query"), str):
            query = str(result.get("query") or "").strip()
        step = {
            "tool": name,
            "label": TOOL_STATUS_LABEL.get(name, name),
            "query": query,
            "status": "done",
            "ok": bool(result.get("ok")),
            "summary": result.get("summary") or result.get("error") or "",
        }
        return call_id, name, result, step

    if len(tool_calls) <= 1:
        return [await one(tool_calls[0])] if tool_calls else []

    await emit("status", {"text": f"并行检索 {len(tool_calls)} 项…"})
    return list(await asyncio.gather(*[one(c) for c in tool_calls]))


_SYNTH_HINT = (
    "请根据工具结果用中文整合回答用户问题："
    "直接给结论，提炼最相关的要点；用换行和「· 」列条目；"
    "不要复读整份搜索列表，不要提工具名。"
)

_TRIVIAL_REPLIES = {
    "",
    "搜完了",
    "整理好了",
    "好的",
    "完成",
    "ok",
    "done",
    "完毕",
}


def _is_trivial_reply(text: str) -> bool:
    t = (text or "").strip().lower()
    if t in _TRIVIAL_REPLIES:
        return True
    # 过短且无实质信息
    if len(t) < 8 and "·" not in t and "《" not in t:
        return True
    return False


def _facts_from_results(results: list[dict[str, Any]]) -> list[Any]:
    out: list[Any] = []
    for r in results:
        facts = r.get("facts")
        if isinstance(facts, list):
            out.extend(facts[:4])
        if len(out) >= 8:
            break
    return out[:8]


async def _synthesize_reply(
    *,
    message: str,
    llm_cfg: dict[str, Any],
    results: list[dict[str, Any]],
    draft: str = "",
) -> str:
    """工具跑完后强制整合成可读答复（不依赖模型是否在 tool 循环里主动收尾）。"""
    evidence = collect_cards_from_results(results)
    facts = _facts_from_results(results)
    summaries = [
        str(r.get("summary") or r.get("error") or "").strip()
        for r in results
        if isinstance(r, dict) and (r.get("summary") or r.get("error"))
    ][:8]
    if not (evidence or facts or summaries):
        return ""
    try:
        org = await _llm_chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是搜片助手「小花」。根据素材用中文回答用户："
                        "先一句结论，再按需用「· 」列 3～8 条（片名/年份/角色若有）；"
                        "保留换行；可标来源（豆瓣/TMDB/网络）；禁止复读原始列表或编造；"
                        "不要只回复「搜完了」「好的」这类空话。只输出纯文本。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "q": message[:240],
                            "hits": compact_cards_for_llm(evidence, limit=16),
                            "facts": facts,
                            "toolSummaries": summaries,
                            "draft": (draft or "")[:400],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            llm_cfg,
            tools=None,
            tool_choice=None,
            max_tokens=420,
        )
        return str(org.get("content") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _fallback_reply_from_results(results: list[dict[str, Any]]) -> str:
    """模型整合失败时，用工具 facts/cards 拼一条可读底稿。"""
    facts = _facts_from_results(results)
    for f in facts:
        if not isinstance(f, dict):
            continue
        person = str(f.get("person") or "").strip()
        works = f.get("works")
        if person and isinstance(works, list) and works:
            lines = [f"根据检索，{person} 的相关作品包括："]
            for w in works[:8]:
                title = str(w or "").strip()
                if title:
                    lines.append(f"· {title}")
            return "\n".join(lines)
        cast = f.get("cast")
        title = str(f.get("title") or "").strip()
        if title and isinstance(cast, list) and cast:
            names = "、".join(str(x) for x in cast[:5] if str(x).strip())
            if names:
                return f"《{title}》主要演员包括：{names}。若要作品列表，请再说一下演员名。"
    evidence = collect_cards_from_results(results)
    if evidence:
        lines = ["找到这些相关结果："]
        for c in evidence[:8]:
            t = str(c.get("title") or "").strip()
            meta = str(c.get("meta") or "").strip()
            if t:
                lines.append(f"· {t}" + (f"（{meta}）" if meta else ""))
        return "\n".join(lines)
    return "这次没整理出有效结论，换个问法或稍后再试。"


async def run_assistant(
    *,
    message: str,
    history: list[ChatTurn],
    prefer_sources: list[str],
    on_status: Any | None = None,
) -> dict[str, Any]:
    message = (message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="请输入要找的内容")

    async def emit(event: str, data: dict[str, Any]) -> None:
        if on_status:
            await on_status(event, data)

    llm_cfg = resolve_llm_config(include_secret=True)
    llm_cfg = merge_active_sampling(llm_cfg)
    llm_ok = bool(llm_cfg.get("enabled") and llm_cfg.get("configured"))
    web_cfg = resolve_web_search_config(include_secret=False)
    enabled_tools = enabled_assistant_tool_names()
    # 网络工具还需设置里打开网络搜索且已配置（Key 或 SearXNG 地址）
    if not (web_cfg.get("enabled") and web_cfg.get("configured")):
        enabled_tools = [t for t in enabled_tools if t != "web_search"]
    include_web = "web_search" in enabled_tools
    tools = filter_tools_by_enabled(
        tool_definitions(include_web=include_web),
        enabled_tools,
    )
    tools = filter_tools_by_prefer(tools, prefer_sources)

    await emit("status", {"text": "小花在想…"})

    if not llm_ok:
        await emit("status", {"text": "未配置模型，改用本地快搜…"})
        # 降级也尊重已启用工具对应的来源
        skill_prefer = prefer_sources[:] if prefer_sources else []
        if not skill_prefer:
            if any(t.startswith("sehua_") for t in enabled_tools):
                skill_prefer.append("sehua")
            if any(t.startswith("scrap_") for t in enabled_tools):
                skill_prefer.append("scrap")
            if "magnet_search" in enabled_tools or "magnet_semantic" in enabled_tools:
                skill_prefer.append("magnet")
            if "media_search" in enabled_tools or "media_person_works" in enabled_tools:
                skill_prefer.append("media")
        cards, steps = await heuristic_local_search(
            message,
            prefer=skill_prefer or None,
            enabled_tools=enabled_tools,
        )
        if not user_wants_resource_cards(message):
            cards = []
        reply = _mechanical_reply(cards) if cards else "本地快搜未命中可展示资源；配置聊天模型后可整合回答。"
        await emit("status", {"text": "搜完了"})
        return {
            "reply": reply,
            "cards": cards,
            "steps": steps,
            "usedLlm": False,
            "usedTools": [s.get("tool") for s in steps],
            "toolSummary": "；".join(str(s.get("summary") or "") for s in steps if s.get("summary"))[:240],
        }

    tool_names = [
        str((t.get("function") or {}).get("name") or "")
        for t in tools
        if (t.get("function") or {}).get("name")
    ]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _build_system(prefer_sources, tool_names)}
    ]
    messages.extend(_history_messages(history))
    messages.append({"role": "user", "content": message[:800]})

    all_results: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    used_tools: list[str] = []
    final_text = ""

    for step_idx in range(MAX_TOOL_STEPS):
        msg = await _llm_chat(messages, llm_cfg, tools=tools, tool_choice="auto")
        tool_calls = msg.get("tool_calls") or []
        content = str(msg.get("content") or "").strip()

        if not tool_calls:
            final_text = content
            break

        # append assistant tool-call message
        messages.append(
            {
                "role": "assistant",
                "content": content or None,
                "tool_calls": tool_calls,
            }
        )

        outcomes = await _dispatch_tool_calls(tool_calls, step_idx=step_idx, emit=emit)
        for call_id, name, result, step in outcomes:
            all_results.append(result)
            used_tools.append(name)
            steps.append(step)
            await emit("step", step)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": tool_result_for_llm(result),
                }
            )

        ui_partial = collect_ui_cards(all_results, message=message)
        if ui_partial:
            await emit("cards_partial", {"cards": ui_partial})
    else:
        # hit max steps — ask for final summary without tools
        cards_so_far = collect_cards_from_results(all_results)
        messages.append(
            {
                "role": "user",
                "content": (
                    f"{_SYNTH_HINT}不要再调用工具。"
                    f"素材：{json.dumps(compact_cards_for_llm(cards_so_far), ensure_ascii=False)}"
                ),
            }
        )
        msg = await _llm_chat(messages, llm_cfg, tools=None, tool_choice=None, max_tokens=420)
        final_text = str(msg.get("content") or "").strip()

    cards = collect_ui_cards(all_results, message=message)

    # 工具已跑但正文为空/敷衍 → 强制再整合一轮（对标 Grok：有过程也要有答案）
    if all_results and _is_trivial_reply(final_text):
        await emit("status", {"text": "正在整理答案…"})
        final_text = await _synthesize_reply(
            message=message,
            llm_cfg=llm_cfg,
            results=all_results,
            draft=final_text,
        )

    if _is_trivial_reply(final_text):
        if all_results:
            final_text = _fallback_reply_from_results(all_results)
        else:
            final_text = _mechanical_reply(cards)

    # 有工具结果但模型仍几乎复读列表时，再压一轮整合
    if all_results and final_text and _looks_like_raw_dump(final_text, all_results):
        rewritten = await _synthesize_reply(
            message=message,
            llm_cfg=llm_cfg,
            results=all_results,
            draft=final_text,
        )
        if rewritten and not _is_trivial_reply(rewritten):
            final_text = rewritten

    tool_summary = "；".join(
        str(s.get("summary") or "") for s in steps if s.get("summary")
    )[:240]

    await emit("status", {"text": "整理好了"})
    return {
        "reply": (final_text or _fallback_reply_from_results(all_results))[:1200],
        "cards": cards,
        "steps": steps,
        "usedLlm": True,
        "usedTools": used_tools,
        "toolSummary": tool_summary,
    }


def _looks_like_raw_dump(text: str, results: list[dict[str, Any]]) -> bool:
    """粗判：回复是否像在堆标题列表而非整合。"""
    t = (text or "").strip()
    if len(t) < 40:
        return False
    titles: list[str] = []
    for r in results:
        for c in list(r.get("cards") or [])[:6]:
            title = str(c.get("title") or "").strip()
            if len(title) >= 4:
                titles.append(title)
    if len(titles) < 3:
        return False
    hit = sum(1 for title in titles if title in t)
    return hit >= 3


@router.post("/assistant/chat", response_model=Envelope)
async def assistant_chat(
    body: AssistantChatBody,
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Envelope | StreamingResponse:
    if body.stream:
        return await assistant_chat_stream(body, _user)

    data = await run_assistant(
        message=body.message,
        history=body.history,
        prefer_sources=body.prefer_sources,
    )
    return Envelope(data=data, message="ok")


@router.post("/assistant/chat/stream")
async def assistant_chat_stream(
    body: AssistantChatBody,
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> StreamingResponse:
    queue: list[dict[str, Any]] = []

    async def on_status(event: str, data: dict[str, Any]) -> None:
        queue.append({"event": event, "data": data})

    async def gen() -> AsyncIterator[bytes]:
        # drain pattern: run assistant while yielding queued events
        import asyncio

        result_holder: dict[str, Any] = {}
        error_holder: dict[str, str] = {}

        async def runner() -> None:
            try:
                result_holder["data"] = await run_assistant(
                    message=body.message,
                    history=body.history,
                    prefer_sources=body.prefer_sources,
                    on_status=on_status,
                )
            except HTTPException as e:
                error_holder["detail"] = str(e.detail)
            except Exception as e:  # noqa: BLE001
                error_holder["detail"] = str(e)

        task = asyncio.create_task(runner())
        while not task.done() or queue:
            while queue:
                item = queue.pop(0)
                payload = json.dumps(item, ensure_ascii=False)
                yield f"data: {payload}\n\n".encode("utf-8")
            if not task.done():
                await asyncio.sleep(0.05)

        if error_holder.get("detail"):
            err = json.dumps(
                {"event": "error", "data": {"message": error_holder["detail"]}},
                ensure_ascii=False,
            )
            yield f"data: {err}\n\n".encode("utf-8")
        else:
            done = json.dumps(
                {"event": "done", "data": result_holder.get("data") or {}},
                ensure_ascii=False,
            )
            yield f"data: {done}\n\n".encode("utf-8")

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/assistant/meta", response_model=Envelope)
def assistant_meta(
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Envelope:
    cfg = resolve_assistant_config()
    web = resolve_web_search_config(include_secret=False)
    tools = cfg.get("tools") if isinstance(cfg.get("tools"), dict) else {}
    sources: list[str] = []
    if tools.get("sehua_keyword") or tools.get("sehua_semantic"):
        sources.append("sehua")
    if tools.get("scrap_search") or tools.get("scrap_list"):
        sources.append("scrap")
    if tools.get("magnet_search") or tools.get("magnet_semantic"):
        sources.append("magnet")
    if tools.get("media_search") or tools.get("media_person_works"):
        sources.append("media")
    if tools.get("web_search") and web.get("enabled") and web.get("configured"):
        sources.append("web")
    return Envelope(
        data={
            "suggestChips": cfg.get("suggestChips") or [],
            "webSearchEnabled": bool(web.get("enabled") and web.get("configured")),
            "sources": sources or ["sehua", "scrap", "magnet", "media"],
            "tools": tools,
            "skillGroups": cfg.get("skillGroups") or [],
            "toolMeta": cfg.get("toolMeta") or [],
        },
        message="ok",
    )
