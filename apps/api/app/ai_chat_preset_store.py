"""BrewStory / SillyTavern 风格对话预设：文件存储于 data/presets/openai/。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import settings_store
from .db import data_dir

ACTIVE_PRESET_KEY = "ai.activeChatPresetId"
PRESET_DIR_NAME = "presets"
OPENAI_SUBDIR = "openai"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_\u4e00-\u9fff\-]+")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _preset_root() -> Path:
    d = data_dir() / PRESET_DIR_NAME / OPENAI_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _legacy_root() -> Path:
    d = data_dir() / PRESET_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def slug_id(name: str, *, unique: bool = False) -> str:
    raw = (name or "preset").strip() or "preset"
    s = _SLUG_RE.sub("_", raw).strip("_")[:48] or "preset"
    if not unique:
        return s
    base = s
    n = 0
    while (_preset_root() / f"{s}.json").exists() or (_legacy_root() / f"{s}.json").exists():
        n += 1
        s = f"{base}_{n}"
        if n > 200:
            s = f"{base}_{uuid.uuid4().hex[:8]}"
            break
    return s


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _path_for(preset_id: str) -> Path | None:
    pid = str(preset_id or "").strip()
    if not pid:
        return None
    p = _preset_root() / f"{pid}.json"
    if p.exists():
        return p
    legacy = _legacy_root() / f"{pid}.json"
    if legacy.exists():
        return legacy
    return None


def get_active_preset_id() -> str | None:
    raw = settings_store.get_setting(ACTIVE_PRESET_KEY)
    if isinstance(raw, dict):
        v = str(raw.get("id") or "").strip()
        return v or None
    if isinstance(raw, str):
        return raw.strip() or None
    return None


def set_active_preset_id(preset_id: str | None) -> str | None:
    pid = str(preset_id or "").strip() or None
    if pid and not get_preset(pid):
        raise ValueError("预设不存在")
    settings_store.put_setting(ACTIVE_PRESET_KEY, {"id": pid} if pid else {"id": None})
    return pid


def list_presets() -> list[dict[str, Any]]:
    files: list[Path] = []
    root = _preset_root()
    files.extend(sorted(root.glob("*.json")))
    legacy = _legacy_root()
    for f in sorted(legacy.glob("*.json")):
        # skip if same name already in openai/
        if not (root / f.name).exists():
            # only include if looks like StoredPreset
            raw = _read_json(f)
            if raw and isinstance(raw.get("data"), dict):
                files.append(f)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in files:
        stored = _normalize_stored(_read_json(f), fallback_id=f.stem)
        if not stored:
            continue
        pid = stored["id"]
        if pid in seen:
            continue
        seen.add(pid)
        data = stored["data"]
        prompts = data.get("prompts") if isinstance(data.get("prompts"), list) else []
        out.append(
            {
                "id": pid,
                "name": stored["name"],
                "updatedAt": stored["updatedAt"],
                "promptCount": len(prompts),
                "kind": "openai",
            }
        )
    out.sort(key=lambda x: str(x.get("updatedAt") or ""), reverse=True)
    return out


def _normalize_stored(
    raw: dict[str, Any] | None,
    *,
    fallback_id: str = "",
) -> dict[str, Any] | None:
    if not raw:
        return None
    # Already StoredPreset
    if isinstance(raw.get("data"), dict):
        pid = str(raw.get("id") or fallback_id).strip() or fallback_id
        name = str(raw.get("name") or pid).strip() or pid
        return {
            "id": pid,
            "name": name,
            "updatedAt": str(raw.get("updatedAt") or raw.get("updated_at") or _now()),
            "data": raw["data"],
        }
    # Raw OpenAIPreset blob on disk (unusual)
    if isinstance(raw.get("prompts"), list) or "temperature" in raw or "openai_max_tokens" in raw:
        pid = fallback_id or slug_id(str(raw.get("name") or "preset"))
        return {
            "id": pid,
            "name": str(raw.get("name") or pid),
            "updatedAt": _now(),
            "data": raw,
        }
    return None


def get_preset(preset_id: str) -> dict[str, Any] | None:
    path = _path_for(preset_id)
    if not path:
        return None
    return _normalize_stored(_read_json(path), fallback_id=path.stem)


def save_preset(stored: dict[str, Any]) -> dict[str, Any]:
    pid = str(stored.get("id") or "").strip()
    if not pid:
        raise ValueError("缺少预设 id")
    name = str(stored.get("name") or pid).strip() or pid
    data = stored.get("data")
    if not isinstance(data, dict):
        raise ValueError("无效预设 data")
    payload = {
        "id": pid,
        "name": name,
        "updatedAt": _now(),
        "data": data,
    }
    _write_json(_preset_root() / f"{pid}.json", payload)
    # remove legacy duplicate if any
    legacy = _legacy_root() / f"{pid}.json"
    if legacy.exists() and legacy.resolve() != (_preset_root() / f"{pid}.json").resolve():
        try:
            legacy.unlink()
        except OSError:
            pass
    return payload


def delete_preset(preset_id: str) -> bool:
    path = _path_for(preset_id)
    if not path:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    if get_active_preset_id() == preset_id:
        set_active_preset_id(None)
    return True


def import_preset(raw: Any, name_hint: str = "") -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("无效预设 JSON")

    # Unwrap BrewStory StoredPreset wrapper { id, name, data }
    if isinstance(raw.get("data"), dict) and not (
        isinstance(raw.get("prompts"), list) or isinstance(raw.get("prompt_order"), list)
    ):
        name_hint = name_hint or str(raw.get("name") or "")
        raw = raw["data"]

    name = (
        re.sub(r"\.json$", "", name_hint or "", flags=re.I).strip()
        or str(raw.get("name") or "").strip()
        or "preset"
    )
    pid = slug_id(name, unique=False)
    data = dict(raw)
    stored = {
        "id": pid,
        "name": name,
        "updatedAt": _now(),
        "data": data,
    }
    return save_preset(stored)


def export_preset_json(preset_id: str) -> dict[str, Any] | None:
    preset = get_preset(preset_id)
    if not preset:
        return None
    safe = re.sub(r'[\\/:*?"<>|]+', "_", preset.get("name") or preset_id) or "preset"
    return {"filename": f"{safe}.json", "body": preset["data"]}


def sampling_from_data(data: dict[str, Any]) -> dict[str, Any]:
    """Map ST OpenAIPreset fields → ai.llm.sampling camelCase."""

    def num(key: str, *alts: str) -> float | int | None:
        for k in (key, *alts):
            if k in data and isinstance(data[k], (int, float)) and not isinstance(data[k], bool):
                return data[k]
        return None

    def flag(key: str, *alts: str, default: bool | None = None) -> bool | None:
        for k in (key, *alts):
            if k in data:
                return bool(data[k])
        return default

    seed = num("seed")
    n = num("n")
    return {
        "temperature": num("temperature"),
        "topP": num("top_p", "topP"),
        "maxTokens": num("openai_max_tokens", "max_tokens", "maxTokens"),
        "maxContext": num("openai_max_context", "max_context", "maxContext"),
        "frequencyPenalty": num("frequency_penalty", "frequencyPenalty"),
        "presencePenalty": num("presence_penalty", "presencePenalty"),
        "topK": num("top_k", "topK"),
        "minP": num("min_p", "minP"),
        "repetitionPenalty": num("repetition_penalty", "rep_pen", "repetitionPenalty"),
        "seed": int(seed) if seed is not None else None,
        "n": int(n) if n is not None else None,
        "streamOpenai": flag("stream_openai", "streamOpenai", default=True),
        "maxContextUnlocked": flag("max_context_unlocked", "maxContextUnlocked", default=False),
        "continuePrefill": flag("continue_prefill", "continuePrefill", default=False),
        "squashSystemMessages": flag(
            "squash_system_messages", "squashSystemMessages", default=False
        ),
        "showThoughts": flag("show_thoughts", "showThoughts", default=False),
    }


def apply_params_patch(preset_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    preset = get_preset(preset_id)
    if not preset:
        return None
    data = dict(preset["data"])
    # Accept camelCase from frontend and ST snake_case
    mapping = {
        "temperature": "temperature",
        "topP": "top_p",
        "top_p": "top_p",
        "topK": "top_k",
        "top_k": "top_k",
        "minP": "min_p",
        "min_p": "min_p",
        "frequencyPenalty": "frequency_penalty",
        "frequency_penalty": "frequency_penalty",
        "presencePenalty": "presence_penalty",
        "presence_penalty": "presence_penalty",
        "repetitionPenalty": "repetition_penalty",
        "repetition_penalty": "repetition_penalty",
        "maxTokens": "openai_max_tokens",
        "openai_max_tokens": "openai_max_tokens",
        "maxContext": "openai_max_context",
        "openai_max_context": "openai_max_context",
        "seed": "seed",
        "n": "n",
        "streamOpenai": "stream_openai",
        "stream_openai": "stream_openai",
        "maxContextUnlocked": "max_context_unlocked",
        "max_context_unlocked": "max_context_unlocked",
        "continuePrefill": "continue_prefill",
        "continue_prefill": "continue_prefill",
        "squashSystemMessages": "squash_system_messages",
        "squash_system_messages": "squash_system_messages",
        "showThoughts": "show_thoughts",
        "show_thoughts": "show_thoughts",
    }
    bool_keys = {
        "stream_openai",
        "max_context_unlocked",
        "continue_prefill",
        "squash_system_messages",
        "show_thoughts",
    }
    for src, dst in mapping.items():
        if src not in patch:
            continue
        v = patch[src]
        if dst in bool_keys:
            if isinstance(v, bool):
                data[dst] = v
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            data[dst] = v
    return save_preset({**preset, "data": data})


def list_prompts(preset_id: str) -> list[dict[str, Any]]:
    preset = get_preset(preset_id)
    if not preset:
        return []
    prompts = preset["data"].get("prompts")
    if not isinstance(prompts, list):
        return []
    out: list[dict[str, Any]] = []
    for p in prompts:
        if not isinstance(p, dict):
            continue
        out.append(
            {
                "identifier": str(p.get("identifier") or ""),
                "name": str(p.get("name") or p.get("identifier") or ""),
                "role": str(p.get("role") or "system"),
                "enabled": p.get("enabled") is not False,
                "marker": bool(p.get("marker")),
                "content": str(p.get("content") or ""),
                "injection_position": p.get("injection_position"),
                "injection_depth": p.get("injection_depth"),
                "injection_order": p.get("injection_order"),
                "forbid_overrides": bool(p.get("forbid_overrides")),
            }
        )
    return out


def set_prompt_enabled(preset_id: str, identifier: str, enabled: bool) -> dict[str, Any] | None:
    return update_prompt(preset_id, identifier, {"enabled": bool(enabled)})


def update_prompt(
    preset_id: str,
    identifier: str,
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    preset = get_preset(preset_id)
    if not preset or not identifier:
        return None
    data = dict(preset["data"])
    prompts = [dict(p) for p in (data.get("prompts") or []) if isinstance(p, dict)]
    idx = next((i for i, p in enumerate(prompts) if p.get("identifier") == identifier), -1)
    if idx < 0:
        prompts.append(
            {
                "identifier": identifier,
                "name": patch.get("name") or identifier,
                "role": patch.get("role") or "system",
                "content": patch.get("content") or "",
                "enabled": patch.get("enabled") is not False,
            }
        )
        idx = len(prompts) - 1
    else:
        cur = prompts[idx]
        for k in (
            "name",
            "role",
            "content",
            "enabled",
            "injection_position",
            "injection_depth",
            "injection_order",
            "forbid_overrides",
        ):
            if k in patch:
                cur[k] = patch[k]
        prompts[idx] = cur

    data["prompts"] = prompts
    # sync prompt_order enabled flags
    if isinstance(patch.get("enabled"), bool) and isinstance(data.get("prompt_order"), list):
        for block in data["prompt_order"]:
            if not isinstance(block, dict):
                continue
            order = block.get("order")
            if not isinstance(order, list):
                continue
            for row in order:
                if isinstance(row, dict) and row.get("identifier") == identifier:
                    row["enabled"] = bool(patch["enabled"])
    return save_preset({**preset, "data": data})


def add_prompt(
    preset_id: str,
    *,
    name: str = "",
    role: str = "system",
    content: str = "",
) -> dict[str, Any] | None:
    preset = get_preset(preset_id)
    if not preset:
        return None
    identifier = f"custom_{uuid.uuid4().hex[:10]}"
    return update_prompt(
        preset_id,
        identifier,
        {
            "name": name or "自定义提示",
            "role": role or "system",
            "content": content or "",
            "enabled": True,
        },
    )


def apply_active_sampling_to_llm() -> dict[str, Any] | None:
    """Copy active preset sampling into ai.llm.sampling so chat/小花共用。"""
    from .ai_config import AI_LLM_KEY

    pid = get_active_preset_id()
    if not pid:
        return None
    preset = get_preset(pid)
    if not preset:
        return None
    sampling = sampling_from_data(preset["data"])
    # drop Nones
    sampling = {k: v for k, v in sampling.items() if v is not None}
    prev = settings_store.get_setting(AI_LLM_KEY) or {}
    if not isinstance(prev, dict):
        prev = {}
    next_cfg = {**prev, "sampling": {**(prev.get("sampling") or {}), **sampling}}
    return settings_store.put_setting(AI_LLM_KEY, next_cfg)


def active_system_prompt(*, max_chars: int = 12000) -> str:
    """拼接当前启用预设里、已开启且非空的提示词（按 prompt_order）。"""
    pid = get_active_preset_id()
    if not pid:
        return ""
    preset = get_preset(pid)
    if not preset:
        return ""
    data = preset.get("data") if isinstance(preset.get("data"), dict) else {}
    prompts_raw = data.get("prompts") if isinstance(data.get("prompts"), list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for p in prompts_raw:
        if isinstance(p, dict) and p.get("identifier"):
            by_id[str(p["identifier"])] = p

    order_ids: list[str] = []
    for block in data.get("prompt_order") or []:
        if not isinstance(block, dict):
            continue
        for row in block.get("order") or []:
            if not isinstance(row, dict):
                continue
            if row.get("enabled") is False:
                continue
            ident = str(row.get("identifier") or "").strip()
            if ident:
                order_ids.append(ident)
    if not order_ids:
        order_ids = [str(p.get("identifier") or "") for p in prompts_raw if isinstance(p, dict)]

    parts: list[str] = []
    seen: set[str] = set()
    for ident in order_ids:
        if not ident or ident in seen:
            continue
        seen.add(ident)
        p = by_id.get(ident)
        if not p:
            continue
        if p.get("enabled") is False:
            continue
        if p.get("marker"):
            continue
        content = str(p.get("content") or "").strip()
        if content:
            parts.append(content)
    text = "\n\n".join(parts).strip()
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def merge_active_sampling(llm_cfg: dict[str, Any]) -> dict[str, Any]:
    """请求时用启用预设的采样覆盖 LLM 配置（预设优先）。"""
    pid = get_active_preset_id()
    if not pid:
        return llm_cfg
    preset = get_preset(pid)
    if not preset:
        return llm_cfg
    sampling = {k: v for k, v in sampling_from_data(preset["data"]).items() if v is not None}
    if not sampling:
        return llm_cfg
    merged = {**(llm_cfg.get("sampling") or {}), **sampling}
    return {**llm_cfg, "sampling": merged}


def detail_payload(preset_id: str) -> dict[str, Any] | None:
    preset = get_preset(preset_id)
    if not preset:
        return None
    data = preset["data"]
    regexes = []
    ext = data.get("extensions") if isinstance(data.get("extensions"), dict) else {}
    scripts = ext.get("regex_scripts") if isinstance(ext, dict) else None
    if isinstance(scripts, list):
        for s in scripts:
            if not isinstance(s, dict):
                continue
            regexes.append(
                {
                    "id": str(s.get("id") or ""),
                    "scriptName": str(s.get("scriptName") or s.get("name") or ""),
                    "disabled": bool(s.get("disabled")),
                    "findRegex": str(s.get("findRegex") or "")[:120],
                }
            )
    return {
        "id": preset["id"],
        "name": preset["name"],
        "updatedAt": preset["updatedAt"],
        "sampling": sampling_from_data(data),
        "prompts": list_prompts(preset_id),
        "regexScripts": regexes,
        "active": get_active_preset_id() == preset["id"],
    }
