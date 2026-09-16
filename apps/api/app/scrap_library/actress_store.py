# -*- coding: utf-8 -*-
"""女优档案落 Meta Postgres（与 scrap_library_embed 同库）。

标题向量行只存 `女优：姓名`；生日/身高/罩杯/头像路径等结构化资料
写入 `scrap_library_actress`，刮削/E2E/详情 API 统一 upsert。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.db import get_meta_pool, init_db

log = logging.getLogger(__name__)

ACTRESS_TABLE = "scrap_library_actress"


def _fold_key(name: str) -> str:
    from app.scrap_library.actress_bio import fold_key

    return fold_key(name)


def ensure_actress_schema() -> dict[str, Any]:
    """创建/补齐女优档案表（幂等）。"""
    init_db()
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ACTRESS_TABLE} (
              name_key        text PRIMARY KEY,
              name            text NOT NULL DEFAULT '',
              aliases_json    text NOT NULL DEFAULT '[]',
              birthday        text NOT NULL DEFAULT '',
              age             integer,
              height          integer,
              bust            integer,
              waist           integer,
              hip             integer,
              cup             text NOT NULL DEFAULT '',
              birthplace      text NOT NULL DEFAULT '',
              career_period   text NOT NULL DEFAULT '',
              debut_work      text NOT NULL DEFAULT '',
              bio_source      text NOT NULL DEFAULT '',
              bio_source_url  text NOT NULL DEFAULT '',
              map_url         text NOT NULL DEFAULT '',
              javdb           text NOT NULL DEFAULT '',
              avatar_rel      text NOT NULL DEFAULT '',
              avatar_bytes    integer NOT NULL DEFAULT 0,
              work_count      integer NOT NULL DEFAULT 0,
              profile_json    text NOT NULL DEFAULT '{{}}',
              updated_at      timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {ACTRESS_TABLE}_name
              ON {ACTRESS_TABLE} (name)
            """
        )
        cur.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {ACTRESS_TABLE}_birthday
              ON {ACTRESS_TABLE} (birthday)
              WHERE birthday <> ''
            """
        )
        conn.commit()
    return {"table": ACTRESS_TABLE}


def upsert_actress_profile(
    profile: dict[str, Any],
    *,
    avatar_rel: str = "",
    avatar_bytes: int = 0,
) -> dict[str, Any]:
    """把 get_actress_profile / 头像结果写入向量库女优表。"""
    ensure_actress_schema()
    raw_name = str(profile.get("name") or profile.get("queryName") or "").strip()
    if not raw_name:
        return {"ok": False, "error": "empty name"}

    # 主键用映射后主名，避免「いろはめる / 伊留波梦月」双行
    try:
        from app.scrape.metadata_optimize import polish_actress_names

        polished = polish_actress_names([raw_name])
        name = (polished[0] if polished else raw_name).strip() or raw_name
    except Exception:  # noqa: BLE001
        name = raw_name

    key = _fold_key(name)
    aliases = [
        str(a).strip()
        for a in (profile.get("aliases") or [])
        if str(a or "").strip()
    ]
    # 查询名若与主名不同，并入别名
    qn = str(profile.get("queryName") or "").strip()
    if qn and qn.casefold() != name.casefold() and qn not in aliases:
        aliases.insert(0, qn)
    if raw_name and raw_name.casefold() != name.casefold() and raw_name not in aliases:
        aliases.insert(0, raw_name)
    # 去重保序
    seen_a: set[str] = set()
    aliases_u: list[str] = []
    for a in aliases:
        if a.casefold() == name.casefold() or a.casefold() in seen_a:
            continue
        seen_a.add(a.casefold())
        aliases_u.append(a)
    aliases = aliases_u[:24]
    rel = str(avatar_rel or "").strip()
    if not rel:
        # profile 常带 posterApi；尽量还原相对路径
        poster = str(profile.get("posterApi") or "")
        if "scrap-library%2F_actress%2F" in poster or "scrap-library/_actress/" in poster:
            from urllib.parse import unquote, parse_qs, urlparse

            q = parse_qs(urlparse(poster).query)
            path = unquote((q.get("path") or [""])[0])
            if path.startswith("scrap-library/_actress/"):
                rel = path

    if not rel:
        try:
            from app.scrap_library.actress_avatar import resolve_avatar_rel

            rel = resolve_avatar_rel(name) or ""
        except Exception:  # noqa: BLE001
            rel = ""

    bytes_n = int(avatar_bytes or 0)
    if rel and bytes_n <= 0:
        try:
            from app.core.db import media_dir

            p = media_dir() / rel.replace("\\", "/")
            if p.is_file():
                bytes_n = p.stat().st_size
        except OSError:
            pass

    age = profile.get("age")
    try:
        age_i = int(age) if age is not None and str(age).strip() != "" else None
    except (TypeError, ValueError):
        age_i = None

    def _int(v: Any) -> int | None:
        try:
            if v is None or str(v).strip() == "":
                return None
            return int(v)
        except (TypeError, ValueError):
            return None

    row = {
        "name_key": key,
        "name": name,
        "aliases_json": json.dumps(aliases, ensure_ascii=False),
        "birthday": str(profile.get("birthday") or "").strip(),
        "age": age_i,
        "height": _int(profile.get("height")),
        "bust": _int(profile.get("bust")),
        "waist": _int(profile.get("waist")),
        "hip": _int(profile.get("hip")),
        "cup": str(profile.get("cup") or "").strip(),
        "birthplace": str(profile.get("birthplace") or "").strip(),
        "career_period": str(profile.get("careerPeriod") or "").strip(),
        "debut_work": str(profile.get("debutWork") or "").strip(),
        "bio_source": str(profile.get("bioSource") or "").strip(),
        "bio_source_url": str(profile.get("bioSourceUrl") or "").strip(),
        "map_url": str(profile.get("url") or "").strip(),
        "javdb": str(profile.get("javdb") or "").strip(),
        "avatar_rel": rel,
        "avatar_bytes": bytes_n,
        "work_count": int(profile.get("count") or 0),
        "profile_json": json.dumps(profile, ensure_ascii=False, default=str),
    }

    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {ACTRESS_TABLE} (
              name_key, name, aliases_json, birthday, age,
              height, bust, waist, hip, cup, birthplace,
              career_period, debut_work, bio_source, bio_source_url,
              map_url, javdb, avatar_rel, avatar_bytes, work_count,
              profile_json, updated_at
            ) VALUES (
              %(name_key)s, %(name)s, %(aliases_json)s, %(birthday)s, %(age)s,
              %(height)s, %(bust)s, %(waist)s, %(hip)s, %(cup)s, %(birthplace)s,
              %(career_period)s, %(debut_work)s, %(bio_source)s, %(bio_source_url)s,
              %(map_url)s, %(javdb)s, %(avatar_rel)s, %(avatar_bytes)s, %(work_count)s,
              %(profile_json)s, now()
            )
            ON CONFLICT (name_key) DO UPDATE SET
              name = EXCLUDED.name,
              aliases_json = EXCLUDED.aliases_json,
              birthday = CASE
                WHEN EXCLUDED.birthday <> '' THEN EXCLUDED.birthday
                ELSE {ACTRESS_TABLE}.birthday END,
              age = COALESCE(EXCLUDED.age, {ACTRESS_TABLE}.age),
              height = COALESCE(EXCLUDED.height, {ACTRESS_TABLE}.height),
              bust = COALESCE(EXCLUDED.bust, {ACTRESS_TABLE}.bust),
              waist = COALESCE(EXCLUDED.waist, {ACTRESS_TABLE}.waist),
              hip = COALESCE(EXCLUDED.hip, {ACTRESS_TABLE}.hip),
              cup = CASE
                WHEN EXCLUDED.cup <> '' THEN EXCLUDED.cup
                ELSE {ACTRESS_TABLE}.cup END,
              birthplace = CASE
                WHEN EXCLUDED.birthplace <> '' THEN EXCLUDED.birthplace
                ELSE {ACTRESS_TABLE}.birthplace END,
              career_period = CASE
                WHEN EXCLUDED.career_period <> '' THEN EXCLUDED.career_period
                ELSE {ACTRESS_TABLE}.career_period END,
              debut_work = CASE
                WHEN EXCLUDED.debut_work <> '' THEN EXCLUDED.debut_work
                ELSE {ACTRESS_TABLE}.debut_work END,
              bio_source = CASE
                WHEN EXCLUDED.bio_source <> '' THEN EXCLUDED.bio_source
                ELSE {ACTRESS_TABLE}.bio_source END,
              bio_source_url = CASE
                WHEN EXCLUDED.bio_source_url <> '' THEN EXCLUDED.bio_source_url
                ELSE {ACTRESS_TABLE}.bio_source_url END,
              map_url = CASE
                WHEN EXCLUDED.map_url <> '' THEN EXCLUDED.map_url
                ELSE {ACTRESS_TABLE}.map_url END,
              javdb = CASE
                WHEN EXCLUDED.javdb <> '' THEN EXCLUDED.javdb
                ELSE {ACTRESS_TABLE}.javdb END,
              avatar_rel = CASE
                WHEN EXCLUDED.avatar_rel <> '' THEN EXCLUDED.avatar_rel
                ELSE {ACTRESS_TABLE}.avatar_rel END,
              avatar_bytes = CASE
                WHEN EXCLUDED.avatar_bytes > 0 THEN EXCLUDED.avatar_bytes
                ELSE {ACTRESS_TABLE}.avatar_bytes END,
              work_count = GREATEST(EXCLUDED.work_count, {ACTRESS_TABLE}.work_count),
              profile_json = EXCLUDED.profile_json,
              updated_at = now()
            """,
            row,
        )
        conn.commit()

    stored = get_actress_row(name) or {**row, "ok": True}
    stored["ok"] = True
    return stored


def get_actress_row(name: str) -> dict[str, Any] | None:
    ensure_actress_schema()
    key = _fold_key(name)
    if not key:
        return None
    pool = get_meta_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT name_key, name, aliases_json, birthday, age,
                   height, bust, waist, hip, cup, birthplace,
                   career_period, debut_work, bio_source, bio_source_url,
                   map_url, javdb, avatar_rel, avatar_bytes, work_count,
                   profile_json, updated_at
            FROM {ACTRESS_TABLE}
            WHERE name_key = %s
            LIMIT 1
            """,
            (key,),
        )
        raw = cur.fetchone()
    if not raw:
        return None
    d = dict(raw)
    try:
        d["aliases"] = json.loads(d.pop("aliases_json") or "[]")
    except json.JSONDecodeError:
        d["aliases"] = []
        d.pop("aliases_json", None)
    else:
        d.pop("aliases_json", None)
    d["careerPeriod"] = d.pop("career_period", "") or ""
    d["debutWork"] = d.pop("debut_work", "") or ""
    d["bioSource"] = d.pop("bio_source", "") or ""
    d["bioSourceUrl"] = d.pop("bio_source_url", "") or ""
    d["url"] = d.pop("map_url", "") or ""
    d["avatarRel"] = d.pop("avatar_rel", "") or ""
    d["avatarBytes"] = int(d.pop("avatar_bytes") or 0)
    d["count"] = int(d.pop("work_count") or 0)
    try:
        d["profile"] = json.loads(d.pop("profile_json") or "{}")
    except json.JSONDecodeError:
        d["profile"] = {}
        d.pop("profile_json", None)
    else:
        d.pop("profile_json", None)
    ua = d.get("updated_at")
    if ua is not None:
        d["updatedAt"] = ua.isoformat() if hasattr(ua, "isoformat") else str(ua)
        d.pop("updated_at", None)
    return d


def actress_ages_for_names(names: list[str]) -> dict[str, int]:
    """批量查年龄：name_key → 当前岁数（优先 age 列，否则按 birthday 算）。

    PG 缺失时从 Actress.db（含映射别名链）自愈回填，避免女优墙大量无年龄。
    """
    from app.scrap_library.actress_bio import age_from_birthday, lookup_actress_db

    keys: list[str] = []
    key_to_name: dict[str, str] = {}
    seen: set[str] = set()
    for raw in names or []:
        name = str(raw or "").strip()
        fk = _fold_key(name)
        if not fk or fk in seen:
            continue
        seen.add(fk)
        keys.append(fk)
        key_to_name[fk] = name
    if not keys:
        return {}

    ensure_actress_schema()
    pool = get_meta_pool()
    out: dict[str, int] = {}
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT name_key, age, birthday
            FROM {ACTRESS_TABLE}
            WHERE name_key = ANY(%s)
            """,
            (keys,),
        )
        for row in cur.fetchall() or []:
            d = dict(row)
            fk = str(d.get("name_key") or "")
            if not fk:
                continue
            age_i: int | None = None
            raw_age = d.get("age")
            try:
                if raw_age is not None and str(raw_age).strip() != "":
                    age_i = int(raw_age)
            except (TypeError, ValueError):
                age_i = None
            if age_i is None or age_i <= 0:
                age_i = age_from_birthday(str(d.get("birthday") or ""))
            if age_i is not None and age_i > 0:
                out[fk] = int(age_i)

    missing = [key_to_name[k] for k in keys if k not in out]
    if not missing:
        return out

    try:
        from app.scrap_library.actress_avatar import _alias_names
    except Exception:  # noqa: BLE001
        _alias_names = None  # type: ignore[assignment]

    for name in missing:
        try:
            cands = [name]
            if _alias_names is not None:
                for a in _alias_names(name):
                    if a not in cands:
                        cands.append(a)
                    if len(cands) >= 48:
                        break
            bio = lookup_actress_db(cands)
            if not bio:
                continue
            age_i = bio.get("age")
            try:
                age_n = int(age_i) if age_i is not None else 0
            except (TypeError, ValueError):
                age_n = 0
            if age_n <= 0:
                age_n = int(age_from_birthday(str(bio.get("birthday") or "")) or 0)
            if age_n <= 0:
                # 仍把有身高/罩杯的资料写入，供详情页用
                if not (
                    bio.get("birthday")
                    or bio.get("height")
                    or bio.get("cup")
                    or bio.get("careerPeriod")
                ):
                    continue
            profile = {
                "name": name,
                "queryName": name,
                "birthday": bio.get("birthday") or "",
                "age": age_n if age_n > 0 else None,
                "height": bio.get("height"),
                "bust": bio.get("bust"),
                "waist": bio.get("waist"),
                "hip": bio.get("hip"),
                "cup": bio.get("cup") or "",
                "birthplace": bio.get("birthplace") or "",
                "careerPeriod": bio.get("careerPeriod") or "",
                "debutWork": bio.get("debutWork") or "",
                "bioSource": bio.get("source") or "actress_db",
                "bioSourceUrl": bio.get("sourceUrl") or "",
            }
            upsert_actress_profile(profile)
            if age_n > 0:
                out[_fold_key(name)] = age_n
        except Exception as e:  # noqa: BLE001
            log.debug("actress age self-heal failed %s: %s", name, e)

    return out


def collect_library_actress_names(*, region: str = "") -> list[str]:
    """汇总刮削库各区女优分面名（去重）。"""
    from app.scrap_library.embed import list_facets

    regs: list[str]
    if str(region or "").strip():
        regs = [str(region).strip()]
    else:
        regs = [
            "japan_censored",
            "japan_uncensored",
            "amateur",
            "photo",
            "fc2",
            "china",
            "western",
            "",
        ]
    out: list[str] = []
    seen: set[str] = set()
    for reg in regs:
        try:
            page = list_facets(
                region=reg, kind="actress", sort="name", order="asc", limit=20_000
            )
        except Exception as e:  # noqa: BLE001
            log.debug("collect actress facets failed %s: %s", reg, e)
            continue
        for f in page.get("facets") or []:
            name = str((f or {}).get("name") or "").strip()
            if not name or name.startswith("未标注") or name in {"(unknown)"}:
                continue
            fk = _fold_key(name)
            if not fk or fk in seen:
                continue
            seen.add(fk)
            out.append(name)
    return out


def backfill_library_actress_profiles(
    *,
    region: str = "",
    ensure_avatar: bool = False,
    force_avatar: bool = False,
    refresh_bio: bool = True,
) -> dict[str, Any]:
    """批量回填库内女优：本地 Actress.db 资料（默认不联网刮头像）。"""
    names = collect_library_actress_names(region=region)
    return sync_actresses_to_vector_db(
        names,
        region=region,
        ensure_avatar=ensure_avatar,
        force_avatar=force_avatar,
        refresh_bio=refresh_bio,
    )


def _local_actress_profile_dict(name: str) -> dict[str, Any]:
    """仅本地：全别名试查 Actress.db → 档案 dict（不联网、不查作品数）。"""
    from app.scrap_library.actress_bio import (
        expand_actress_query_names,
        lookup_actress_db,
        _cache_put,
    )
    from app.scrape.metadata_optimize import polish_actress_names

    raw = str(name or "").strip()
    polished = polish_actress_names([raw]) if raw else []
    display = polished[0] if polished else raw
    cands = expand_actress_query_names([raw, display], limit=64)
    if not cands:
        cands = [display or raw]
    bio = lookup_actress_db(cands) or {}
    if bio:
        try:
            _cache_put(cands, bio)
        except Exception:  # noqa: BLE001
            pass
    return {
        "name": display or raw,
        "queryName": raw,
        "aliases": [x for x in cands if x and x != (display or raw)][:24],
        "birthday": bio.get("birthday") or "",
        "age": bio.get("age"),
        "height": bio.get("height"),
        "bust": bio.get("bust"),
        "waist": bio.get("waist"),
        "hip": bio.get("hip"),
        "cup": bio.get("cup") or "",
        "birthplace": bio.get("birthplace") or "",
        "careerPeriod": bio.get("careerPeriod") or "",
        "debutWork": bio.get("debutWork") or "",
        "bioSource": bio.get("source") or "",
        "bioSourceUrl": bio.get("sourceUrl") or "",
    }


def sync_actresses_to_vector_db(
    names: list[str],
    *,
    region: str = "",
    ensure_avatar: bool = True,
    force_avatar: bool = False,
    refresh_bio: bool = False,
    extra_aliases: list[str] | None = None,
) -> dict[str, Any]:
    """E2E/刮削：头像落盘（可选）+ 本地 Actress.db 资料 → scrap_library_actress。

    资料不联网；头像仅在本地缺失时下载到 media/_actress。
    多人时头像并行拉取（先预热 GFriends 索引一次），避免串行卡死感。
    extra_aliases：合并阶段收拢的跨源异写，写入主名档案的 aliases。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from app.scrap_library.actress_avatar import ensure_actress_avatar
    from app.scrape.metadata_optimize import polish_actress_names

    _ = region, refresh_bio  # 保留签名兼容调用方
    ensure_actress_schema()
    items: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()
    ordered: list[str] = []

    for raw in names or []:
        name = str(raw or "").strip()
        if not name:
            continue
        try:
            polished = polish_actress_names([name])
            display = (polished[0] if polished else name).strip() or name
        except Exception:  # noqa: BLE001
            display = name
        fk = _fold_key(display)
        if not fk or fk in seen:
            continue
        seen.add(fk)
        ordered.append(display)

    extra_al = [
        str(a).strip()
        for a in (extra_aliases or [])
        if str(a or "").strip()
    ]

    if not ordered:
        return {
            "ok": True,
            "items": [],
            "issues": ["无女优可写入"],
            "table": ACTRESS_TABLE,
        }

    # 预热 GFriends Filetree（只打一次 CDN；串行每人各打一次会极慢）
    if ensure_avatar:
        try:
            from app.scrap_library.actress_avatar import _load_gfriends_index

            _load_gfriends_index()
        except Exception:  # noqa: BLE001
            pass

    av_by_name: dict[str, dict[str, Any]] = {}
    if ensure_avatar:
        workers = max(1, min(6, len(ordered)))

        def _one_avatar(nm: str) -> tuple[str, dict[str, Any]]:
            try:
                return nm, ensure_actress_avatar(nm, force=force_avatar)
            except Exception as e:  # noqa: BLE001
                return nm, {
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "bytes": 0,
                    "rel": "",
                    "source": "",
                }

        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="actress-sync-av"
        ) as pool:
            futs = [pool.submit(_one_avatar, nm) for nm in ordered]
            for fut in as_completed(futs):
                nm, av = fut.result()
                av_by_name[nm] = av
                if not av.get("ok") and av.get("error"):
                    issues.append(f"头像失败: {nm} ({av.get('error')})")

    for name in ordered:
        av = av_by_name.get(name) or {
            "ok": False,
            "bytes": 0,
            "rel": "",
            "source": "",
        }

        try:
            profile = _local_actress_profile_dict(name)
        except Exception as e:  # noqa: BLE001
            profile = {"name": name, "queryName": name}
            issues.append(f"资料失败: {name} ({type(e).__name__}: {e})")

        # 单人收拢时：把跨源异写并入档案别名
        if extra_al and len(ordered) == 1:
            merged_al = list(profile.get("aliases") or [])
            for a in extra_al:
                if a.casefold() == name.casefold():
                    continue
                if a not in merged_al:
                    merged_al.append(a)
            profile["aliases"] = merged_al[:24]

        stored = upsert_actress_profile(
            profile,
            avatar_rel=str(av.get("rel") or ""),
            avatar_bytes=int(av.get("bytes") or 0),
        )
        bio_ok = bool(
            stored.get("birthday")
            or stored.get("height")
            or stored.get("cup")
            or stored.get("careerPeriod")
        )
        avatar_ok = bool(str(stored.get("avatarRel") or "").strip()) and (
            int(stored.get("avatarBytes") or 0) > 0 or bool(av.get("ok"))
        )
        db_ok = bool(stored.get("ok"))
        if not db_ok:
            issues.append(f"女优写入失败: {name}")
        if ensure_avatar and not avatar_ok:
            issues.append(f"女优头像未入库: {name}")
        if not bio_ok:
            issues.append(f"女优资料空: {name}")

        items.append(
            {
                "name": stored.get("name") or name,
                "ok": db_ok and (bio_ok or avatar_ok),
                "db": db_ok,
                "avatar_ok": avatar_ok,
                "avatar_source": av.get("source") or ("local" if avatar_ok else ""),
                "avatar_bytes": int(stored.get("avatarBytes") or 0),
                "avatarRel": stored.get("avatarRel") or "",
                "birthday": stored.get("birthday") or "",
                "age": stored.get("age"),
                "height": stored.get("height"),
                "cup": stored.get("cup") or "",
                "careerPeriod": stored.get("careerPeriod") or "",
                "bioSource": stored.get("bioSource") or "",
                "bioSourceUrl": stored.get("bioSourceUrl") or "",
            }
        )

    ok = all(bool(x.get("ok")) for x in items)
    return {
        "ok": ok,
        "items": items,
        "issues": issues,
        "table": ACTRESS_TABLE,
        "n": len(items),
        "localBioOnly": True,
    }
