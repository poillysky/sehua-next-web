"""Startup: seed admin + default settings from config → Postgres meta."""

from __future__ import annotations

import logging
from typing import Any

import app.auth.store as auth_store
import app.core.settings_store as settings_store
from app.core.config_loader import admin_bootstrap, config_paths, load_config

log = logging.getLogger("sns.bootstrap")

BOOTSTRAP_META_KEY = "bootstrap_admin"
SETTINGS_SEED_META_KEY = "bootstrap_settings"


def seed_admin_from_config() -> dict[str, Any]:
    admin = admin_bootstrap()
    username = admin["username"]
    password = admin["password"]
    reset = admin["reset_password_on_boot"]

    result = auth_store.ensure_admin_user(
        username,
        password,
        reset_password=reset,
    )

    # 安全告警：默认弱口令仅适用于本地开发。生产请用 SNS_ADMIN_PASSWORD 或 app.local.json 覆盖。
    if password in ("admin123456", "admin", "123456", "password") and (
        result.get("seeded") or result.get("password_reset")
    ):
        log.warning(
            "管理员口令命中已知弱口令并已写入(seed/reset)。强烈建议通过环境变量 "
            "SNS_ADMIN_PASSWORD 或 config/app.local.json 覆盖后再部署到公网/不可信网络"
        )

    settings_store.put_setting(
        BOOTSTRAP_META_KEY,
        {
            "username": username,
            "source": [str(p) for p in config_paths()],
            "seeded": result.get("seeded"),
            "password_reset": result.get("password_reset"),
            "note": "密码仅首次（或 reset_password_on_boot）从 config 写入 Postgres",
        },
    )

    if result.get("seeded"):
        log.info("admin seeded from config → postgres: %s", username)
    elif result.get("password_reset"):
        log.warning("admin password reset from config: %s", username)
    else:
        log.info("admin already in postgres: %s", username)

    return result


def seed_settings_from_config(*, force: bool | None = None) -> dict[str, Any]:
    """把 config.app.json / app.local.json 的 settings 写入 Postgres meta。

    默认：仅当 key 不存在时填入（不覆盖用户已改配置）。
    force=True 或 config.seed_settings_on_boot=true：强制覆盖写入。
    """
    cfg = load_config()
    raw = cfg.get("settings")
    if not isinstance(raw, dict) or not raw:
        return {"seeded": [], "skipped": [], "forced": False}

    if force is None:
        force = bool(cfg.get("seed_settings_on_boot"))

    seeded: list[str] = []
    skipped: list[str] = []
    for key, value in raw.items():
        k = str(key or "").strip()
        if not k or value is None:
            continue
        existing = settings_store.get_setting(k)
        if existing is not None and not force:
            skipped.append(k)
            continue
        settings_store.put_setting(k, value)
        seeded.append(k)
        log.info("settings seeded from config → postgres: %s", k)

    meta = {
        "seeded": seeded,
        "skipped": skipped,
        "forced": force,
        "source": [str(p) for p in config_paths()],
    }
    settings_store.put_setting(SETTINGS_SEED_META_KEY, meta)
    if seeded:
        log.info(
            "settings seed done: wrote %s, skipped %s (force=%s)",
            ",".join(seeded) or "-",
            len(skipped),
            force,
        )
    else:
        log.info(
            "settings seed: nothing to write (skipped %s existing keys, force=%s)",
            len(skipped),
            force,
        )
    return meta
