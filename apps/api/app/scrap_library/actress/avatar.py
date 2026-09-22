# -*- coding: utf-8 -*-
"""向量库女优 → GFriends 头像刮削与本地落盘。

目录：media/scrap-library/_actress/<女优名>.jpg
索引：media/scrap-library/_actress/_index.json（别名 → 文件名）
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.core.db import media_dir, get_meta_pool

from .aliases import CN_TO_JP_KANJI, alias_names as _alias_names
from .bio import fold_key

log = logging.getLogger(__name__)

_AVATAR_REL_DIR = "scrap-library/_actress"
_INDEX_NAME = "_index.json"
_FILETREE_URLS = (
    "https://cdn.jsdelivr.net/gh/gfriends/gfriends@master/Filetree.json",
    "https://cdn.jsdelivr.net/gh/xinxin8816/gfriends@master/Filetree.json",
    "https://raw.githubusercontent.com/gfriends/gfriends/master/Filetree.json",
)
_CONTENT_BASES = (
    "https://cdn.jsdelivr.net/gh/gfriends/gfriends@master/Content",
    "https://cdn.jsdelivr.net/gh/xinxin8816/gfriends@master/Content",
    "https://raw.githubusercontent.com/gfriends/gfriends/master/Content",
    "https://raw.githubusercontent.com/xinxin8816/gfriends/master/Content",
)
_FILETREE_TTL_S = 24 * 3600
_NOISE_NAMES = frozenset(
    {
        "挿入",
        "插入",
        "不明",
        "未知",
        "various",
        "unknown",
        "女優",
        "女优",
        "引退",
        "クリムゾン",
        "克里姆森",
        "克裏姆森",
        "克裡姆森",
        "恋愛禁止ル",
        "戀愛禁止ル",
        "恋爱禁止ル",
    }
)

_job_lock = threading.Lock()
_job: dict[str, Any] = {
    "running": False,
    "phase": "",
    "progress": None,
    "log": [],
    "result": None,
    "error": None,
}
_job_hydrated = False
_job_hydrate_lock = threading.Lock()

_tree_lock = threading.Lock()
_tree_cache: dict[str, Any] = {"at": 0.0, "index": None}

# 头像直链种子来自 actors.zh-CN.json（1.8 MB），按 mtime+size 缓存避免逐人重读
_avatar_seed_lock = threading.Lock()
_avatar_seed_cache: dict[str, Any] = {"key": None, "map": {}}


def avatar_dir() -> Path:
    d = (media_dir() / "scrap-library" / "_actress").resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _index_path() -> Path:
    return avatar_dir() / _INDEX_NAME


def _load_index() -> dict[str, str]:
    path = _index_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_index(index: dict[str, str]) -> None:
    path = _index_path()
    path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _safe_filename(name: str) -> str:
    s = unicodedata.normalize("NFKC", str(name or "").strip())
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if not s:
        s = "unknown"
    return f"{s[:96]}.jpg"






def _jp_fold_key(name: str) -> str:
    """NFKC + 简繁→日新字后再 casefold；GFriends 索引/查询共用。"""
    s = unicodedata.normalize("NFKC", str(name or "").strip())
    if not s:
        return ""
    return s.translate(CN_TO_JP_KANJI).casefold()




def _persist_avatar_job(**extra: Any) -> None:
    try:
        from app.core import job_persist

        with _job_lock:
            payload = {
                "status": (
                    "running"
                    if _job.get("running")
                    else str(extra.get("status") or _job.get("phase") or "idle")
                ),
                "phase": str(_job.get("phase") or ""),
                "progress": dict(_job.get("progress") or {}) or None,
                "log": list(_job.get("log") or [])[-40:],
                "result": _job.get("result"),
                "error": _job.get("error"),
                "running": bool(_job.get("running")),
            }
        for k, v in extra.items():
            payload[k] = v
        if payload.get("running"):
            payload["status"] = "running"
        job_persist.save_job(job_persist.ACTRESS_AVATAR_JOB_KEY, payload)
    except Exception as e:  # noqa: BLE001
        log.warning("persist actress avatar job failed: %s", e)


def _hydrate_avatar_job(*, force: bool = False) -> dict[str, Any]:
    global _job_hydrated
    with _job_hydrate_lock:
        if _job_hydrated and not force:
            return {}
        _job_hydrated = True
    try:
        from app.core import job_persist

        raw = job_persist.load_job(job_persist.ACTRESS_AVATAR_JOB_KEY)
        if not raw:
            return {}
        with _job_lock:
            if _job.get("running"):
                return raw
            if not _job.get("phase") and raw.get("phase"):
                _job["phase"] = str(raw.get("phase") or "")
            if not _job.get("progress") and raw.get("progress"):
                _job["progress"] = dict(raw.get("progress") or {})
            if not _job.get("log") and raw.get("log"):
                _job["log"] = list(raw.get("log") or [])[-40:]
            if _job.get("result") is None and raw.get("result") is not None:
                _job["result"] = raw.get("result")
            if not _job.get("error") and raw.get("error"):
                _job["error"] = raw.get("error")
            if str(raw.get("status") or "") == "running":
                _job["phase"] = "interrupted"
                prog = dict(_job.get("progress") or {})
                prog["label"] = "进程中断 · 可继续"
                _job["progress"] = prog
                raw = dict(raw)
                raw["status"] = "interrupted"
                raw["running"] = False
                job_persist.save_job(job_persist.ACTRESS_AVATAR_JOB_KEY, raw)
        return raw
    except Exception as e:  # noqa: BLE001
        log.warning("hydrate actress avatar job failed: %s", e)
        return {}


def get_job_status() -> dict[str, Any]:
    _hydrate_avatar_job()
    with _job_lock:
        return {
            "running": bool(_job["running"]),
            "phase": _job.get("phase") or "",
            "progress": _job.get("progress"),
            "log": list(_job.get("log") or [])[-40:],
            "result": _job.get("result"),
            "error": _job.get("error"),
        }


def _log(msg: str) -> None:
    with _job_lock:
        rows = list(_job.get("log") or [])
        rows.append(str(msg))
        _job["log"] = rows[-40:]
    log.info("actress-avatar: %s", msg)


def _progress(**kw: Any) -> None:
    with _job_lock:
        cur = dict(_job.get("progress") or {})
        cur.update(kw)
        _job["progress"] = cur
        if kw.get("label"):
            _job["phase"] = str(kw["label"])


def resolve_avatar_rel(name: str) -> str:
    """返回 media 相对路径（scrap-library/_actress/xxx.jpg），无则空串。

    会走演员映射别名：松本芽衣 → 松本芽依.jpg。
    """
    key = str(name or "").strip()
    if not key:
        return ""
    index = _load_index()
    # 查询名 + 映射别名（标准名优先）
    try:
        aliases = _alias_names(key)
    except Exception:  # noqa: BLE001
        aliases = [key]
    seen: set[str] = set()
    candidates: list[str] = []
    for n in [key, *aliases]:
        s = str(n or "").strip()
        if not s:
            continue
        fk = fold_key(s)
        if fk in seen:
            continue
        seen.add(fk)
        candidates.append(s)

    for s in candidates:
        fname = index.get(fold_key(s)) or index.get(s)
        if fname:
            path = avatar_dir() / str(fname)
            if _avatar_file_ok(path):
                return f"{_AVATAR_REL_DIR}/{path.name}".replace("\\", "/")
        cand = avatar_dir() / _safe_filename(s)
        if _avatar_file_ok(cand):
            return f"{_AVATAR_REL_DIR}/{cand.name}".replace("\\", "/")
    return ""


def resolve_avatar_api(name: str) -> str:
    from app.scrap_library.embed import local_file_api

    rel = resolve_avatar_rel(name)
    return local_file_api(rel) if rel else ""


def ensure_actress_avatar(name: str, *, force: bool = False) -> dict[str, Any]:
    """单人女优头像：已有则复用，否则按全别名 seed→GFriends→JavBus 下载落盘。"""
    from .bio import expand_actress_query_names

    raw = str(name or "").strip()
    if not raw:
        return {"ok": False, "name": "", "error": "empty name"}

    # 刮削查询：映射别名 + Actress.db 连通名全试一遍
    aliases = expand_actress_query_names([raw], limit=48)
    if not aliases:
        aliases = _alias_names(raw) or [raw]
    display = aliases[0]
    fname = _safe_filename(display)
    dest = avatar_dir() / fname
    existed = _avatar_file_ok(dest) and not force
    source = "local" if existed else ""
    if not existed:
        if dest.is_file():
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        data, source = _fetch_avatar_for_names(aliases)
        if not data or _is_placeholder_image(data):
            return {
                "ok": False,
                "name": display,
                "aliases": aliases,
                "source": source or "",
                "path": "",
                "bytes": 0,
                "error": "avatar miss",
            }
        try:
            from app.scrap_library.enrich_extras import compress_avatar_bytes

            data = compress_avatar_bytes(data, max_edge=512, jpeg_q=80)
        except Exception:  # noqa: BLE001
            pass
        tmp = dest.with_suffix(".jpg.part")
        try:
            tmp.write_bytes(data)
            tmp.replace(dest)
        except OSError as e:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return {
                "ok": False,
                "name": display,
                "aliases": aliases,
                "source": source,
                "path": "",
                "bytes": 0,
                "error": f"write fail: {e}",
            }
        index = _load_index()
        for a in aliases:
            index[fold_key(a)] = fname
        index[fold_key(display)] = fname
        _save_index(index)
    else:
        # 本地已有：仍把别名写入索引，墙/详情异写名能命中
        try:
            index = _load_index()
            changed = False
            for a in aliases:
                fk = fold_key(a)
                if fk and index.get(fk) != fname:
                    index[fk] = fname
                    changed = True
            if changed:
                _save_index(index)
        except Exception:  # noqa: BLE001
            pass

    size = dest.stat().st_size if dest.is_file() else 0
    return {
        "ok": _avatar_file_ok(dest),
        "name": display,
        "aliases": aliases,
        "source": source or ("local" if existed else ""),
        "path": str(dest),
        "rel": f"{_AVATAR_REL_DIR}/{fname}".replace("\\", "/"),
        "bytes": size,
        "posterApi": resolve_avatar_api(display),
        "error": "",
    }


def get_actress_profile(
    name: str, *, region: str = "", refresh: bool = False, persist: bool = True
) -> dict[str, Any]:
    """女优详情头：标准名 / 别名 / 作品数 / 头像 / 外链 / 详细资料。

    persist=True（默认）时写入 Meta Postgres `scrap_library_actress`。
    """
    from .bio import resolve_actress_bio
    from app.scrap_library.embed import list_items
    from app.scrape.metadata_optimize import (
        _actor_maps,
        _lookup_actor_hit,
        _map_actor_entry,
        mapping_language_from_settings,
        polish_actress_names,
    )

    raw = str(name or "").strip()
    if not raw:
        raise ValueError("name required")

    polished = polish_actress_names([raw])
    display = polished[0] if polished else raw

    aliases: list[str] = []
    url = ""
    javdb = ""
    try:
        table = _actor_maps(mapping_language_from_settings())
        canon, _ = _map_actor_entry(display, table)
        if canon:
            display = str(canon).strip() or display
        hit = _lookup_actor_hit(display, table)
        if isinstance(hit, dict):
            url = str(hit.get("url") or "").strip()
            javdb = str(hit.get("javdb") or "").strip()
            for f in ("name", "zh"):
                v = str(hit.get(f) or "").strip()
                if v:
                    display = v
                    break
        # 别名：映射表键 + 变体，去掉展示名本身
        disp_fold = fold_key(display)
        for a in _alias_names(display):
            if fold_key(a) == disp_fold:
                continue
            if a not in aliases:
                aliases.append(a)
            if len(aliases) >= 16:
                break
    except Exception as e:  # noqa: BLE001
        log.debug("actress profile map failed %s: %s", display, e)

    count = 0
    try:
        # 与分面入口同名查询（库内女优行常是映射前/后两种写法）
        for qname in (raw, display):
            if not qname:
                continue
            page = list_items(
                region=str(region or "").strip(),
                actress=qname,
                limit=1,
                offset=0,
            )
            count = int(page.get("total") or 0)
            if count > 0:
                break
    except Exception as e:  # noqa: BLE001
        log.debug("actress profile count failed %s: %s", display, e)

    poster_api = resolve_avatar_api(display) or resolve_avatar_api(raw)

    bio: dict[str, Any] = {}
    try:
        bio = resolve_actress_bio(
            display=display,
            query_name=raw,
            aliases=aliases,
            map_url=url,
            refresh=bool(refresh),
            allow_online=False,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("actress bio failed %s: %s", display, e)
        bio = {}

    if bio.get("sourceUrl") and not url:
        url = str(bio.get("sourceUrl") or "").strip()

    out = {
        "name": display,
        "queryName": raw,
        "aliases": aliases,
        "count": count,
        "posterApi": poster_api,
        "url": url,
        "javdb": javdb,
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
    if persist:
        try:
            from .store import upsert_actress_profile

            stored = upsert_actress_profile(out)
            if stored.get("avatarRel"):
                out["avatarRel"] = stored.get("avatarRel")
                out["db"] = True
        except Exception as e:  # noqa: BLE001
            log.debug("actress profile persist failed %s: %s", display, e)
    return out


def apply_actress_avatars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """女优分面：有本地头像时覆盖海报字段（绝不用作品 poster）。"""
    from app.scrap_library.embed import local_file_api

    out: list[dict[str, Any]] = []
    for raw in rows or []:
        row = dict(raw or {})
        name = str(row.get("name") or "").strip()
        if not name:
            out.append(row)
            continue
        if name in {"未标注女优", "未标注", "(unknown)"}:
            row["posterApi"] = ""
            row["posterApis"] = []
            row["coverUrl"] = ""
            row.pop("avatar", None)
            out.append(row)
            continue
        rel = resolve_avatar_rel(name)
        if not rel:
            try:
                from .store import get_actress_row

                db = get_actress_row(name)
                db_rel = str((db or {}).get("avatarRel") or "").strip()
                if db_rel:
                    from app.core.db import media_dir

                    p = media_dir() / db_rel.replace("\\", "/")
                    if _avatar_file_ok(p):
                        rel = db_rel.replace("\\", "/")
            except Exception:  # noqa: BLE001
                pass
        if rel:
            api = local_file_api(rel)
            row["posterApi"] = api
            row["posterApis"] = [api]
            row["posterPath"] = rel
            row["coverUrl"] = ""
            row["avatar"] = True
            # 回写索引：异写名也能命中同一文件
            try:
                index = _load_index()
                fname = Path(rel).name
                changed = False
                for a in _alias_names(name):
                    fk = fold_key(a)
                    if index.get(fk) != fname:
                        index[fk] = fname
                        changed = True
                if index.get(fold_key(name)) != fname:
                    index[fold_key(name)] = fname
                    changed = True
                if changed:
                    _save_index(index)
            except Exception:  # noqa: BLE001
                pass
        else:
            # 无头像时清空作品封面，避免女优墙显示片名 poster
            row["posterApi"] = ""
            row["posterApis"] = []
            row["coverUrl"] = ""
            row.pop("avatar", None)
        out.append(row)
    return out




def _load_gfriends_index() -> dict[str, tuple[str, str]]:
    """name.casefold() → (folder, filename) 取质量最高（目录靠后）。"""
    now = time.time()
    with _tree_lock:
        cached = _tree_cache.get("index")
        at = float(_tree_cache.get("at") or 0)
        if cached is not None and now - at < _FILETREE_TTL_S:
            return cached  # type: ignore[return-value]

    tree: dict[str, Any] | None = None
    last_err: Exception | None = None
    for url in _FILETREE_URLS:
        try:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                r = client.get(url)
                r.raise_for_status()
                data = r.json()
            if isinstance(data, dict) and isinstance(data.get("Content"), dict):
                tree = data
                break
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    if tree is None:
        raise RuntimeError(f"GFriends Filetree 拉取失败: {last_err}")

    content = tree.get("Content") or {}
    # Content 按质量升序；同名取更靠后的目录
    index: dict[str, tuple[str, str]] = {}
    folders = list(content.keys())
    for folder in folders:
        bucket = content.get(folder) or {}
        if not isinstance(bucket, dict):
            continue
        for key, val in bucket.items():
            # key 可能是「妃月るい.jpg」，val 为实际文件「妃月るい.jpg?t=…」
            name = str(key or "")
            if not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            stem = name.rsplit(".", 1)[0]
            raw_file = str(val or name).split("?", 1)[0]
            if not raw_file:
                continue

            def _register(stem_name: str) -> None:
                # 原始 fold + 日文新字体 fold（简体「吉良薰」可命中「吉良薫」）
                index[fold_key(stem_name)] = (str(folder), raw_file)
                jk = _jp_fold_key(stem_name)
                if jk:
                    index[jk] = (str(folder), raw_file)

            _register(stem)
            # 也用完整文件名 stem；AI-Fix- 去前缀后也可查
            file_stem = raw_file.rsplit(".", 1)[0]
            _register(file_stem)
            if file_stem.lower().startswith("ai-fix-"):
                _register(file_stem[7:])
            if stem.lower().startswith("ai-fix-"):
                _register(stem[7:])

    with _tree_lock:
        _tree_cache["at"] = now
        _tree_cache["index"] = index
    return index


def _is_placeholder_image(data: bytes) -> bool:
    """拒绝 Now Printing / 空白占位图（GFriends/JavBus/DMM 都可能返回）。"""
    if not data or len(data) < 1500:
        return True
    low = data[:4096].lower()
    if b"nowprinting" in low or b"now printing" in low:
        return True
    # DMM/JavBus 常见 GIF 占位
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) < 8000:
        return True
    try:
        import io

        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = im.size
        if w < 96 or h < 96:
            return True
        step = max(1, min(w, h) // 25)
        samples = [
            im.getpixel((x, y))
            for x in range(0, w, step)
            for y in range(0, h, step)
        ]
        if not samples:
            return True
        avg = [sum(c[i] for c in samples) / len(samples) for i in range(3)]
        lum = 0.299 * avg[0] + 0.587 * avg[1] + 0.114 * avg[2]
        white = sum(1 for c in samples if min(c) > 220) / len(samples)
        # 「Now Printing」白底灰字：高亮 + 高白占比
        if white >= 0.72 and lum >= 210:
            return True
        if white >= 0.65 and lum >= 200 and len(data) < 14_000:
            return True
    except Exception:  # noqa: BLE001
        # 无法解码的当无效
        return True
    return False


def _avatar_file_ok(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        if path.stat().st_size < 1500:
            return False
        return not _is_placeholder_image(path.read_bytes())
    except OSError:
        return False


def _download_bytes(
    url: str, *, retries: int = 2, referer: str | None = None
) -> bytes | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    last_err: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(25.0, connect=8.0),
                follow_redirects=True,
                headers=headers,
            ) as client:
                r = client.get(url)
                if r.status_code >= 400 or not r.content or len(r.content) < 1500:
                    last_err = RuntimeError(
                        f"status={r.status_code} len={len(r.content or b'')}"
                    )
                    time.sleep(0.25 * (attempt + 1))
                    continue
                ctype = (r.headers.get("content-type") or "").lower()
                if "html" in ctype:
                    return None
                low = url.lower()
                if "nowprinting" in low or "placeholder" in low or "blank." in low:
                    return None
                if _is_placeholder_image(r.content):
                    return None
                return r.content
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.25 * (attempt + 1))
    if last_err:
        log.debug("avatar download fail %s: %s", url, last_err)
    return None


def _fetch_gfriends_avatar(aliases: list[str]) -> bytes | None:
    """按别名逐个尝试；跳过 Now Printing 占位，继续下一条。"""
    index = _load_gfriends_index()
    tried: set[tuple[str, str]] = set()
    best: bytes | None = None
    best_area = 0
    for alias in aliases:
        keys = (
            _jp_fold_key(alias),
            fold_key(alias),
            _jp_fold_key(f"AI-Fix-{alias}"),
            fold_key(f"AI-Fix-{alias}"),
        )
        for key in keys:
            if not key:
                continue
            hit = index.get(key)
            if not hit or hit in tried:
                continue
            tried.add(hit)
            folder, filename = hit
            folder_q = quote(folder, safe="")
            candidates = [filename]
            if filename.lower().startswith("ai-fix-"):
                candidates.append(filename[7:])
            for fname in candidates:
                file_q = quote(fname, safe="")
                for base in _CONTENT_BASES:
                    data = _download_bytes(f"{base}/{folder_q}/{file_q}")
                    if not data:
                        continue
                    # 多别名时优先更大图
                    try:
                        import io

                        from PIL import Image

                        im = Image.open(io.BytesIO(data))
                        area = int(im.size[0]) * int(im.size[1])
                    except Exception:  # noqa: BLE001
                        area = len(data)
                    if area > best_area:
                        best = data
                        best_area = area
                    break
                if best and best_area >= 200 * 200:
                    return best
    return best


def _name_close(a: str, b: str) -> bool:
    aa = fold_key(a)
    bb = fold_key(b)
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    if aa in bb or bb in aa:
        return True
    return False


def _fetch_javbus_avatar(aliases: list[str]) -> bytes | None:
    """GFriends 未命中时：JavBus /searchstar/{name} 头像瀑布兜底。"""
    try:
        from bs4 import BeautifulSoup

        from app.core.outbound_http import fetch_page
        from app.makers import settings as makers_settings
        from app.makers.catalog_routes import _abs, _javbus_bases
    except Exception as e:  # noqa: BLE001
        log.debug("javbus avatar import skip: %s", e)
        return None

    bases = tuple(_javbus_bases() or ())
    if not bases:
        return None
    cookie = makers_settings.javbus_cookie() or None
    for alias in aliases[:6]:
        if len(alias) < 2:
            continue
        enc = quote(alias)
        for base in bases[:2]:
            try:
                page = fetch_page(
                    f"{base}/searchstar/{enc}",
                    referer=f"{base}/",
                    cookie=cookie,
                    access=makers_settings.provider_access("javbus"),
                    timeout=12.0,
                    source_id="javbus",
                )
                html = (page.html or "") if page else ""
                if len(html) < 200:
                    continue
            except Exception as e:  # noqa: BLE001
                log.debug("javbus searchstar fail %s @ %s: %s", alias, base, e)
                continue
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:  # noqa: BLE001
                continue
            for box in soup.select(
                "#waterfall a.avatar-box, #waterfall .avatar-box, a.avatar-box"
            ):
                name_el = box.select_one(".star-name, span")
                label = (
                    (name_el.get_text(" ", strip=True) if name_el else "")
                    or str(box.get("title") or "")
                    or ""
                )
                img = box.select_one("img")
                if img is not None:
                    title = str(img.get("title") or img.get("alt") or "").strip()
                    if title and (not label or label.endswith(("（", "("))):
                        label = title
                if label and not any(_name_close(label, a) for a in aliases):
                    # 宽松：无标签时仍取首图；有标签但不匹配则跳过
                    if label.strip():
                        continue
                src = ""
                if img is not None:
                    src = str(img.get("src") or img.get("data-src") or "")
                url = _abs(base, src) if src else None
                if not url:
                    continue
                data = _download_bytes(url, referer=f"{base}/")
                if data:
                    return data
    return None


def _load_avatar_url_seed() -> dict[str, str]:
    """演员直链头像种子，取自 ``apps/maps/scrape/actors.zh-CN.json`` 的 ``avatar`` 字段。

    条目形如 ``{"一二三ゆぅり": {"name": "一二三优里", "avatar": "https://…"}}``；
    别名键与标准名都注册（GFriends/JavBus 覆盖不到的伪娘/素人等靠它防再 miss）。
    """
    try:
        from app.core.maps_paths import actors_seed

        path = actors_seed("zh-CN")
        if not path.is_file():
            return {}
        st = path.stat()
        stamp = (str(path), int(st.st_mtime_ns), int(st.st_size))
    except Exception as e:  # noqa: BLE001
        log.debug("avatar url seed stat fail: %s", e)
        return {}

    with _avatar_seed_lock:
        if _avatar_seed_cache.get("key") == stamp:
            return _avatar_seed_cache["map"]  # type: ignore[return-value]

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.debug("avatar url seed load fail: %s", e)
        return {}

    out: dict[str, str] = {}
    # 先按标准名收集头像，再把所有指向该标准名的别名键一并注册，
    # 这样「别名 → 直链」在不解别名链的情况下也能直接命中。
    by_name: dict[str, str] = {}
    if isinstance(raw, dict):
        for entry in raw.values():
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("avatar") or "").strip()
            name = str(entry.get("name") or "").strip()
            if url.startswith(("http://", "https://")) and name:
                by_name.setdefault(name, url)
    if by_name:
        for key, entry in raw.items():
            name = ""
            if isinstance(entry, dict):
                avatar = str(entry.get("avatar") or "").strip()
                if avatar.startswith(("http://", "https://")):
                    name = str(entry.get("name") or "").strip()
                else:
                    name = str(entry.get("name") or entry.get("zh") or "").strip()
            if name not in by_name:
                continue
            url = by_name[name]
            for alias in (str(key or "").strip(), name):
                if not alias:
                    continue
                out[alias] = url
                out[fold_key(alias)] = url

    with _avatar_seed_lock:
        _avatar_seed_cache["key"] = stamp
        _avatar_seed_cache["map"] = out
    return out


def _fetch_seed_avatar(aliases: list[str]) -> bytes | None:
    seed = _load_avatar_url_seed()
    if not seed:
        return None
    seen: set[str] = set()
    for alias in aliases:
        for key in (alias, fold_key(alias)):
            url = seed.get(key) or ""
            if not url or url in seen:
                continue
            seen.add(url)
            data = _download_bytes(url, referer=url.rsplit("/", 1)[0] + "/")
            if data and not _is_placeholder_image(data):
                return data
    return None


def _fetch_avatar_for_names(aliases: list[str]) -> tuple[bytes | None, str]:
    """返回 (bytes, source)；source=seed|gfriends|javbus|''。"""
    data = _fetch_seed_avatar(aliases)
    if data:
        return data, "seed"
    data = _fetch_gfriends_avatar(aliases)
    if data:
        return data, "gfriends"
    data = _fetch_javbus_avatar(aliases)
    if data:
        return data, "javbus"
    return None, ""


def list_vector_actress_names(*, region: str = "", limit: int | None = None) -> list[str]:
    """从向量库汇总女优名（已映射展示名优先）。"""
    from app.scrape.metadata_optimize import polish_actress_names
    from app.scrap_library.embed import TABLE, ensure_schema, _region_match_values

    ensure_schema()
    pool = get_meta_pool()
    clauses = ["source_text ~ %s"]
    params: list[Any] = ["女优："]
    if region:
        match = _region_match_values(region)
        if match:
            clauses.append("region = ANY(%s)")
            params.append(match)
    where = " AND ".join(clauses)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT NULLIF(substring(source_text from '女优：(.+?)(?:\\n|$)'), '') AS line
            FROM {TABLE}
            WHERE {where}
            """,
            params,
        )
        raw_rows = cur.fetchall() or []
    raw: list[str] = []
    for r in raw_rows:
        line = str((r.get("line") if isinstance(r, dict) else r[0]) or "").strip()
        if not line:
            continue
        for tok in re.split(r"[\s　、,/|]+", line):
            t = tok.strip()
            if t:
                raw.append(t)
    polished = polish_actress_names(raw)
    out: list[str] = []
    seen: set[str] = set()
    for n in polished:
        k = fold_key(n)
        if not n or k in seen:
            continue
        if k in {fold_key(x) for x in _NOISE_NAMES}:
            continue
        if len(n) <= 1:
            continue
        seen.add(k)
        out.append(n)
    if limit is not None and int(limit) > 0:
        out = out[: int(limit)]
    return out


def purge_placeholder_avatars() -> int:
    """删除已落盘的 Now Printing / 空白占位，并清理索引。返回删除数。"""
    index = _load_index()
    removed = 0
    bad_names: set[str] = set()
    for path in avatar_dir().glob("*.jpg"):
        if path.name.startswith("_"):
            continue
        if _avatar_file_ok(path):
            continue
        try:
            path.unlink(missing_ok=True)
            removed += 1
            bad_names.add(path.name)
        except OSError:
            pass
    if bad_names:
        index = {k: v for k, v in index.items() if str(v) not in bad_names}
        _save_index(index)
        try:
            import app.scrap_library.embed as emb

            emb._FACETS_CACHE.clear()  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass
    return removed


def scrape_actress_avatars(
    *,
    force: bool = False,
    limit: int | None = None,
    region: str = "",
    resume_done_names: set[str] | None = None,
) -> dict[str, Any]:
    from pathlib import Path as _Path

    from .bio import expand_actress_query_names
    from .store import collect_library_actress_names

    done_names = set(resume_done_names or ())
    purged = purge_placeholder_avatars()
    if purged:
        _log(f"已清除占位空图 {purged} 张，将重试下载")

    # 向量库名 + 分面名并集，避免漏人
    names: list[str] = []
    seen: set[str] = set()
    for n in list_vector_actress_names(region=region, limit=None) + collect_library_actress_names(
        region=region
    ):
        s = str(n or "").strip()
        if not s:
            continue
        fk = fold_key(s)
        if not fk or fk in seen:
            continue
        seen.add(fk)
        names.append(s)
        if limit is not None and int(limit) > 0 and len(names) >= int(limit):
            break

    catalog_n = len(names)
    _log(f"女优队列 {catalog_n:,} 人（向量库∪分面）")
    if done_names:
        _log(f"续跑 · 已处理跳过 {len(done_names):,}")
    _progress(
        stage="scan",
        percent=2,
        label="对照本地头像…",
        done=0,
        total=catalog_n or None,
    )

    index = _load_index()
    pending: list[str] = []
    skip = 0
    if force:
        pending = [n for n in names if n not in done_names]
        skip = len(names) - len(pending)
    else:
        for name in names:
            if name in done_names:
                skip += 1
                continue
            # 以别名索引/落盘为准，不单看标准名文件名
            rel = resolve_avatar_rel(name)
            if rel:
                skip += 1
                fname = _Path(rel.replace("\\", "/")).name
                for alias in expand_actress_query_names([name], limit=32):
                    index.setdefault(fold_key(alias), fname)
                index.setdefault(fold_key(name), fname)
            else:
                fname = _safe_filename(name)
                dest = avatar_dir() / fname
                if dest.is_file() and not _avatar_file_ok(dest):
                    try:
                        dest.unlink(missing_ok=True)
                    except OSError:
                        pass
                pending.append(name)
        if skip:
            _save_index(index)

    total = len(pending)
    _log(
        f"{'覆盖' if force else '增量'} · 待下载 {total:,}"
        + (f" · 已有跳过 {skip:,}" if not force else "")
    )
    if total <= 0:
        _progress(stage="done", percent=100, label="无需下载", done=0, total=0)
        _log(f"完成 · 无需下载 · 已有跳过 {skip}")
        return {
            "ok": True,
            "catalogTotal": catalog_n,
            "total": 0,
            "downloaded": 0,
            "downloadedGfriends": 0,
            "downloadedJavbus": 0,
            "downloadedSeed": 0,
            "skipped": skip,
            "missed": 0,
            "failed": 0,
            "missSamples": [],
        }

    _progress(
        stage="scan",
        percent=4,
        label="拉取 GFriends 索引…",
        done=0,
        total=total,
    )
    try:
        _load_gfriends_index()
        _log("GFriends 索引已就绪 · 未命中将尝试 JavBus")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e

    ok = 0
    ok_gf = 0
    ok_jb = 0
    ok_seed = 0
    miss = 0
    fail = 0
    miss_samples: list[str] = []
    from app.core.container_budget import cap_parallel

    workers = cap_parallel(6, tight=2, small=4, hard=6)

    def one(name: str) -> tuple[str, str, str]:
        if resolve_avatar_rel(name) and not force:
            return "skip", name, ""
        fname = _safe_filename(name)
        dest = avatar_dir() / fname
        if dest.is_file() and not _avatar_file_ok(dest):
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        aliases = expand_actress_query_names([name], limit=48)
        if not aliases:
            aliases = _alias_names(name) or [name]
        data, source = _fetch_avatar_for_names(aliases)
        if not data or _is_placeholder_image(data):
            return "miss", name, ""
        try:
            from app.scrap_library.enrich_extras import compress_avatar_bytes

            data = compress_avatar_bytes(data, max_edge=512, jpeg_q=80)
        except Exception:  # noqa: BLE001
            pass
        tmp = dest.with_suffix(".jpg.part")
        try:
            tmp.write_bytes(data)
            tmp.replace(dest)
            return "ok", name, source
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return "fail", name, ""

    _progress(stage="download", percent=5, label="下载头像…", done=0, total=total)
    done = 0
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="actress-avatar") as pool:
        futs = {pool.submit(one, n): n for n in pending}
        for fut in as_completed(futs):
            status, name, source = fut.result()
            done += 1
            if status == "ok":
                ok += 1
                if source == "javbus":
                    ok_jb += 1
                elif source == "seed":
                    ok_seed += 1
                else:
                    ok_gf += 1
                fname = _safe_filename(name)
                for alias in expand_actress_query_names([name], limit=48):
                    index[fold_key(alias)] = fname
                index[fold_key(name)] = fname
                done_names.add(name)
            elif status == "skip":
                skip += 1
                fname = _safe_filename(name)
                for alias in expand_actress_query_names([name], limit=32):
                    index.setdefault(fold_key(alias), fname)
                done_names.add(name)
            elif status == "miss":
                miss += 1
                done_names.add(name)
                if len(miss_samples) < 40:
                    miss_samples.append(name)
            else:
                fail += 1
                done_names.add(name)
            if done % 25 == 0 or done == total:
                pct = 5 + int(90 * done / max(1, total))
                _progress(
                    stage="download",
                    percent=pct,
                    label=f"下载头像 {done}/{total}",
                    done=done,
                    total=total,
                )
                if done % 100 == 0:
                    _save_index(index)
                    _persist_avatar_job(
                        status="running",
                        params={
                            "force": bool(force),
                            "limit": limit,
                            "region": region,
                        },
                        doneNames=sorted(done_names)[-8000:],
                    )
                    _log(
                        f"进度 {done}/{total} · 成功 {ok}"
                        f"（GF {ok_gf}/JB {ok_jb}）· 未命中 {miss}"
                    )

    _save_index(index)
    try:
        import app.scrap_library.embed as emb

        emb._FACETS_CACHE.clear()  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass

    if miss_samples:
        _log("未命中样例: " + "、".join(miss_samples[:20]))

    result = {
        "ok": True,
        "catalogTotal": catalog_n,
        "total": total,
        "downloaded": ok,
        "downloadedGfriends": ok_gf,
        "downloadedJavbus": ok_jb,
        "downloadedSeed": ok_seed,
        "skipped": skip,
        "missed": miss,
        "failed": fail,
        "missSamples": miss_samples,
    }
    _progress(
        stage="done",
        percent=100,
        label="完成",
        done=total,
        total=total,
    )
    _log(
        f"完成 · 新下 {ok}（GFriends {ok_gf} · JavBus {ok_jb} · seed {ok_seed}）"
        f" · 已有跳过 {skip} · 未命中 {miss} · 失败 {fail}"
        f" · 队列 {total}/{catalog_n}"
    )
    _persist_avatar_job(
        status="done",
        params={"force": bool(force), "limit": limit, "region": region},
        doneNames=[],
    )
    return result



def start_actress_avatar_job(
    *,
    force: bool = False,
    limit: int | None = None,
    region: str = "",
    polish_meta: bool = True,
) -> dict[str, Any]:
    """女优刮削：可选先映射写回向量库，再刮头像落盘。"""
    from app.scrap_library.embed import (
        get_actress_optimize_status,
        get_job_status as get_embed_job,
        optimize_actress_metadata,
    )

    prev = _hydrate_avatar_job()
    resume_done: set[str] = set()
    resumed = False
    prev_params = prev.get("params") if isinstance(prev.get("params"), dict) else {}
    prev_status = str(prev.get("status") or "")
    same = (
        bool(prev_params.get("force")) == bool(force)
        and str(prev_params.get("region") or "") == str(region or "")
        and (prev_params.get("limit") in (None, limit) or limit is None)
    )
    if (
        prev_status in {"interrupted", "running", "paused"}
        and same
        and isinstance(prev.get("doneNames"), list)
    ):
        resume_done = {str(x) for x in prev["doneNames"] if str(x).strip()}
        resumed = bool(resume_done)

    with _job_lock:
        if _job["running"]:
            raise RuntimeError("女优刮削已在运行")
        if get_embed_job().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        if get_actress_optimize_status().get("running"):
            raise RuntimeError("女优元数据优化进行中，请稍后再试")
        try:
            from app.scrap_library import nfo_optimize as nfo_opt

            if nfo_opt.get_job_status().get("running"):
                raise RuntimeError("NFO 优化进行中，请稍后再试")
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            pass
        _job.update(
            {
                "running": True,
                "phase": "继续" if resumed else "starting",
                "progress": {
                    "stage": "prepare",
                    "percent": 0,
                    "label": "继续" if resumed else "starting",
                    "done": len(resume_done) if resumed else 0,
                    "total": None,
                },
                "log": list(_job.get("log") or [])[-20:] if resumed else [],
                "result": None,
                "error": None,
            }
        )
    _persist_avatar_job(
        status="running",
        params={
            "force": bool(force),
            "limit": limit,
            "region": region,
            "polishMeta": bool(polish_meta),
        },
        doneNames=sorted(resume_done)[-8000:],
    )

    def run() -> None:
        try:
            polish_result: dict[str, Any] | None = None
            if polish_meta and not resumed:
                _log("① 映射女优标准名并写回向量库…")
                with _job_lock:
                    _job["phase"] = "写入女优元数据…"
                    _job["progress"] = {
                        "stage": "embed",
                        "percent": 3,
                        "label": "polish_meta",
                        "done": 0,
                        "total": None,
                    }
                polish_result = optimize_actress_metadata(reembed=True)
                updated = int(polish_result.get("updated") or 0)
                total = int(polish_result.get("total") or 0)
                reemb = int(polish_result.get("reembedded") or 0)
                _log(
                    f"元数据完成 · 更新 {updated}/{total} · 重嵌 {reemb}"
                )
                with _job_lock:
                    _job["phase"] = "刮削头像…"
                    _job["progress"] = {
                        "stage": "scan",
                        "percent": 8,
                        "label": "avatars",
                        "done": 0,
                        "total": None,
                    }
            _log("② 刮削女优头像…" + (" · 续跑" if resumed else ""))
            result = scrape_actress_avatars(
                force=force,
                limit=limit,
                region=region,
                resume_done_names=resume_done or None,
            )
            _log("③ 回填资料 + 补缺头像（本地 Actress.db 别名穷举）…")
            with _job_lock:
                _job["phase"] = "补全女优资料/头像…"
                _job["progress"] = {
                    "stage": "bio",
                    "percent": 92,
                    "label": "bio_backfill",
                    "done": 0,
                    "total": None,
                }
            from .store import (
                backfill_library_actress_profiles,
                collect_library_actress_names,
            )

            bio_result = backfill_library_actress_profiles(
                region=str(region or "").strip(),
                ensure_avatar=False,
                refresh_bio=True,
            )
            # 仍缺头像的再 ensure 一次（全别名）
            still_miss_av: list[str] = []
            filled_av = 0
            for name in collect_library_actress_names(
                region=str(region or "").strip()
            ):
                if resolve_avatar_rel(name) and not force:
                    continue
                av = ensure_actress_avatar(name, force=bool(force))
                if av.get("ok"):
                    filled_av += 1
                else:
                    still_miss_av.append(name)

            still_miss_bio: list[str] = []
            bio_ok_n = 0
            for it in bio_result.get("items") or []:
                if it.get("birthday") or it.get("height") or it.get("cup") or it.get(
                    "careerPeriod"
                ):
                    bio_ok_n += 1
                else:
                    n = str(it.get("name") or "").strip()
                    if n:
                        still_miss_bio.append(n)

            gaps = {
                "missingAvatar": still_miss_av[:40],
                "missingBio": still_miss_bio[:40],
                "missingAvatarN": len(still_miss_av),
                "missingBioN": len(still_miss_bio),
                "bioOk": bio_ok_n,
                "avatarFilledExtra": filled_av,
            }
            result = {
                **result,
                "bio": {
                    "n": bio_result.get("n"),
                    "ok": bio_result.get("ok"),
                    "bioOk": bio_ok_n,
                    "issues": (bio_result.get("issues") or [])[:40],
                },
                "gaps": gaps,
            }
            _log(
                f"资料回填 · {int(bio_result.get('n') or 0)} 人 · 有资料 {bio_ok_n}"
                f" · 补头像 +{filled_av}"
            )
            if still_miss_av or still_miss_bio:
                _log(
                    f"仍缺 · 头像 {len(still_miss_av)} · 资料 {len(still_miss_bio)}"
                    + (
                        f" · 头像样例 {'、'.join(still_miss_av[:8])}"
                        if still_miss_av
                        else ""
                    )
                    + (
                        f" · 资料样例 {'、'.join(still_miss_bio[:8])}"
                        if still_miss_bio
                        else ""
                    )
                )
            else:
                _log("缺口已清：头像与资料均已本地齐备")
            if polish_result is not None:
                result = {**result, "polish": polish_result}
            with _job_lock:
                _job["result"] = result
                _job["phase"] = "done"
            _persist_avatar_job(status="done", doneNames=[])
        except Exception as e:  # noqa: BLE001
            log.exception("actress scrape failed")
            with _job_lock:
                _job["error"] = str(e)
                _job["phase"] = "error"
                rows = list(_job.get("log") or [])
                rows.append(f"失败: {e}")
                _job["log"] = rows[-40:]
            _persist_avatar_job(
                status="error",
                doneNames=sorted(resume_done)[-8000:],
            )
        finally:
            with _job_lock:
                _job["running"] = False
            _persist_avatar_job()

    threading.Thread(
        target=run, name="scrap-actress-scrape", daemon=True
    ).start()
    return {"started": True, "resumed": resumed}
