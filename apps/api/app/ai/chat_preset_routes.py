"""设置：BrewStory 风格对话预设（导入 / 启用 / 参数 / 提示词）。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth.routes import get_optional_user, require_user
import app.ai.chat_preset_store as store
from app.core.conn_settings_routes import Envelope

router = APIRouter(prefix="/settings/ai/chat-presets", tags=["settings"])


class ActivateBody(BaseModel):
    id: str | None = None


class ImportBody(BaseModel):
    name: str | None = None
    data: dict[str, Any]


class SaveParamsBody(BaseModel):
    temperature: float | None = None
    top_p: float | None = Field(default=None, alias="topP")
    top_k: int | None = Field(default=None, alias="topK")
    min_p: float | None = Field(default=None, alias="minP")
    frequency_penalty: float | None = Field(default=None, alias="frequencyPenalty")
    presence_penalty: float | None = Field(default=None, alias="presencePenalty")
    repetition_penalty: float | None = Field(default=None, alias="repetitionPenalty")
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    max_context: int | None = Field(default=None, alias="maxContext")
    seed: int | None = None
    n: int | None = None
    stream_openai: bool | None = Field(default=None, alias="streamOpenai")
    max_context_unlocked: bool | None = Field(default=None, alias="maxContextUnlocked")
    continue_prefill: bool | None = Field(default=None, alias="continuePrefill")
    squash_system_messages: bool | None = Field(default=None, alias="squashSystemMessages")
    show_thoughts: bool | None = Field(default=None, alias="showThoughts")

    model_config = {"populate_by_name": True}


class PromptEnableBody(BaseModel):
    identifier: str
    enabled: bool


class PromptSaveBody(BaseModel):
    identifier: str
    name: str | None = None
    role: str | None = None
    content: str | None = None
    enabled: bool | None = None
    injection_position: int | None = None
    injection_depth: int | None = None
    injection_order: int | None = None
    forbid_overrides: bool | None = None


class PromptAddBody(BaseModel):
    name: str | None = None
    role: str | None = None
    content: str | None = None


@router.get("", response_model=Envelope)
def list_chat_presets(
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Envelope:
    return Envelope(
        data={
            "presets": store.list_presets(),
            "activeId": store.get_active_preset_id(),
        },
        message="ok",
    )


@router.post("/import", response_model=Envelope)
def import_chat_preset(
    body: ImportBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    try:
        stored = store.import_preset(body.data, body.name or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Envelope(
        data={
            "id": stored["id"],
            "name": stored["name"],
            "promptCount": len(store.list_prompts(stored["id"])),
            "updatedAt": stored["updatedAt"],
        },
        message="imported",
    )


@router.post("/activate", response_model=Envelope)
def activate_chat_preset(
    body: ActivateBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    try:
        current = store.get_active_preset_id()
        next_id = (body.id or "").strip() or None
        if next_id and current == next_id:
            next_id = None
        store.set_active_preset_id(next_id)
        if next_id:
            store.apply_active_sampling_to_llm()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return Envelope(
        data={
            "activeId": store.get_active_preset_id(),
            "presets": store.list_presets(),
        },
        message="ok",
    )


@router.get("/{preset_id}", response_model=Envelope)
def get_chat_preset(
    preset_id: str,
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Envelope:
    detail = store.detail_payload(preset_id)
    if not detail:
        raise HTTPException(status_code=404, detail="预设不存在")
    return Envelope(data=detail, message="ok")


@router.get("/{preset_id}/export")
def export_chat_preset(
    preset_id: str,
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> Response:
    exported = store.export_preset_json(preset_id)
    if not exported:
        raise HTTPException(status_code=404, detail="预设不存在")
    body = json.dumps(exported["body"], ensure_ascii=False, indent=2) + "\n"
    return Response(
        content=body.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{exported["filename"]}"',
        },
    )


@router.delete("/{preset_id}", response_model=Envelope)
def delete_chat_preset(
    preset_id: str,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    if not store.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="预设不存在")
    return Envelope(
        data={"presets": store.list_presets(), "activeId": store.get_active_preset_id()},
        message="deleted",
    )


@router.put("/{preset_id}/params", response_model=Envelope)
def save_chat_preset_params(
    preset_id: str,
    body: SaveParamsBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    patch = body.model_dump(by_alias=True, exclude_none=True)
    saved = store.apply_params_patch(preset_id, patch)
    if not saved:
        raise HTTPException(status_code=404, detail="预设不存在")
    if store.get_active_preset_id() == preset_id:
        store.apply_active_sampling_to_llm()
    return Envelope(data=store.detail_payload(preset_id), message="saved")


@router.post("/{preset_id}/prompts/enable", response_model=Envelope)
def enable_chat_preset_prompt(
    preset_id: str,
    body: PromptEnableBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    saved = store.set_prompt_enabled(preset_id, body.identifier, body.enabled)
    if not saved:
        raise HTTPException(status_code=404, detail="预设或提示词不存在")
    return Envelope(data={"prompts": store.list_prompts(preset_id)}, message="ok")


@router.put("/{preset_id}/prompts", response_model=Envelope)
def save_chat_preset_prompt(
    preset_id: str,
    body: PromptSaveBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    patch = body.model_dump(exclude_none=True)
    ident = patch.pop("identifier", "")
    saved = store.update_prompt(preset_id, ident, patch)
    if not saved:
        raise HTTPException(status_code=404, detail="预设不存在")
    return Envelope(data={"prompts": store.list_prompts(preset_id)}, message="saved")


@router.post("/{preset_id}/prompts", response_model=Envelope)
def add_chat_preset_prompt(
    preset_id: str,
    body: PromptAddBody,
    _user: dict[str, Any] = Depends(require_user),
) -> Envelope:
    saved = store.add_prompt(
        preset_id,
        name=body.name or "",
        role=body.role or "system",
        content=body.content or "",
    )
    if not saved:
        raise HTTPException(status_code=404, detail="预设不存在")
    return Envelope(data={"prompts": store.list_prompts(preset_id)}, message="added")
