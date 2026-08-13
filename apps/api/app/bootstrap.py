"""Startup: seed admin from config → SQLite; runtime config stays in SQLite."""



from __future__ import annotations



import logging

from typing import Any



from . import auth_store, settings_store

from .config_loader import admin_bootstrap, config_paths



log = logging.getLogger("sns.bootstrap")



BOOTSTRAP_META_KEY = "bootstrap_admin"





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



    settings_store.put_setting(

        BOOTSTRAP_META_KEY,

        {

            "username": username,

            "source": [str(p) for p in config_paths()],

            "seeded": result.get("seeded"),

            "password_reset": result.get("password_reset"),

            "note": "密码仅首次（或 reset_password_on_boot）从 config 写入 SQLite",

        },

    )



    if result.get("seeded"):

        log.info("admin seeded from config → sqlite: %s", username)

    elif result.get("password_reset"):

        log.warning("admin password reset from config: %s", username)

    else:

        log.info("admin already in sqlite: %s", username)



    return result


