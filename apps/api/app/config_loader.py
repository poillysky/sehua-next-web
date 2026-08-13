"""Load bootstrap config from config/app.json (+ optional app.local.json)."""



from __future__ import annotations



import json

import os

from copy import deepcopy

from pathlib import Path

from typing import Any



ROOT = Path(__file__).resolve().parents[3]

DEFAULT_CONFIG = ROOT / "config" / "app.json"

LOCAL_CONFIG = ROOT / "config" / "app.local.json"





def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:

    out = deepcopy(base)

    for k, v in overlay.items():

        if isinstance(v, dict) and isinstance(out.get(k), dict):

            out[k] = _deep_merge(out[k], v)

        else:

            out[k] = v

    return out





def config_paths() -> list[Path]:

    raw = os.environ.get("SNS_CONFIG")

    if raw:

        return [Path(raw)]

    paths = [DEFAULT_CONFIG]

    if LOCAL_CONFIG.is_file():

        paths.append(LOCAL_CONFIG)

    return paths





def load_config() -> dict[str, Any]:

    cfg: dict[str, Any] = {

        "admin": {

            "username": "admin",

            "password": "admin123456",

            "reset_password_on_boot": False,

        }

    }

    for path in config_paths():

        if not path.is_file():

            continue

        with path.open("r", encoding="utf-8") as f:

            data = json.load(f)

        if isinstance(data, dict):

            cfg = _deep_merge(cfg, data)

    return cfg





def admin_bootstrap() -> dict[str, Any]:

    admin = load_config().get("admin") or {}

    return {

        "username": str(admin.get("username") or "admin").strip(),

        "password": str(admin.get("password") or ""),

        "reset_password_on_boot": bool(admin.get("reset_password_on_boot")),

    }


