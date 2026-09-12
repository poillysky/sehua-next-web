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

from .db import media_dir, get_meta_pool

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

_tree_lock = threading.Lock()
_tree_cache: dict[str, Any] = {"at": 0.0, "index": None}


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


def _fold_key(name: str) -> str:
    return unicodedata.normalize("NFKC", str(name or "").strip()).casefold()


def get_job_status() -> dict[str, Any]:
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
    """返回 media 相对路径（scrap-library/_actress/xxx.jpg），无则空串。"""
    key = str(name or "").strip()
    if not key:
        return ""
    index = _load_index()
    fname = index.get(_fold_key(key)) or index.get(key)
    if not fname:
        # 直接文件名兜底
        cand = avatar_dir() / _safe_filename(key)
        if _avatar_file_ok(cand):
            return f"{_AVATAR_REL_DIR}/{cand.name}".replace("\\", "/")
        return ""
    path = avatar_dir() / str(fname)
    if _avatar_file_ok(path):
        return f"{_AVATAR_REL_DIR}/{path.name}".replace("\\", "/")
    return ""


def resolve_avatar_api(name: str) -> str:
    from .scrap_library_embed import local_file_api

    rel = resolve_avatar_rel(name)
    return local_file_api(rel) if rel else ""


def apply_actress_avatars(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """女优分面：有本地头像时覆盖海报字段。"""
    from .scrap_library_embed import local_file_api

    index = _load_index()
    out: list[dict[str, Any]] = []
    for raw in rows or []:
        row = dict(raw or {})
        name = str(row.get("name") or "").strip()
        if not name:
            out.append(row)
            continue
        fname = index.get(_fold_key(name)) or index.get(name)
        rel = ""
        if fname:
            path = avatar_dir() / str(fname)
            if _avatar_file_ok(path):
                rel = f"{_AVATAR_REL_DIR}/{path.name}".replace("\\", "/")
        if not rel:
            cand = avatar_dir() / _safe_filename(name)
            if _avatar_file_ok(cand):
                rel = f"{_AVATAR_REL_DIR}/{cand.name}".replace("\\", "/")
        if rel:
            api = local_file_api(rel)
            row["posterApi"] = api
            row["posterApis"] = [api]
            row["posterPath"] = rel
            row["coverUrl"] = ""
            row["avatar"] = True
        out.append(row)
    return out


def _alias_names(display: str) -> list[str]:
    """显示名 + 刮削演员映射表别名（日文键/jp 字段，供 GFriends 检索）。

    与刮削共用 data/scrape_maps/actors.*.json：正向取 name/zh/jp，
    反向收集所有指向同一标准名的键（多为日文）。
    """
    from .scrape_metadata_optimize import (
        _actor_maps,
        _lookup_actor_hit,
        _map_actor_entry,
        mapping_language_from_settings,
    )

    names: list[str] = []
    seen: set[str] = set()

    def add(n: str) -> None:
        s = unicodedata.normalize("NFKC", str(n or "").strip())
        if not s:
            return
        # 去掉括注：本名（别名）
        s = re.sub(r"\s*[\(（][^)）]*[\)）]\s*$", "", s).strip()
        if not s:
            return
        k = _fold_key(s)
        if k in seen:
            return
        seen.add(k)
        names.append(s)

    def add_variants(n: str) -> None:
        add(n)
        s = unicodedata.normalize("NFKC", str(n or "").strip())
        if not s:
            return
        # 々 ↔ 叠字（佐々波 ↔ 佐佐波）
        if "々" in s:
            chars = list(s)
            for i, c in enumerate(chars):
                if c == "々" and i > 0:
                    chars[i] = chars[i - 1]
            add("".join(chars))
        else:
            buf: list[str] = []
            i = 0
            while i < len(s):
                if (
                    i + 1 < len(s)
                    and s[i] == s[i + 1]
                    and "\u4e00" <= s[i] <= "\u9fff"
                ):
                    buf.append(s[i])
                    buf.append("々")
                    i += 2
                else:
                    buf.append(s[i])
                    i += 1
            add("".join(buf))
        try:
            import zhconv

            add(zhconv.convert(s, "zh-hant"))
            add(zhconv.convert(s, "zh-cn"))
            add(zhconv.convert(s, "zh-tw"))
        except Exception:  # noqa: BLE001
            pass

    add_variants(display)
    try:
        table = _actor_maps(mapping_language_from_settings())
        canon, _ = _map_actor_entry(display, table)
        add_variants(canon)
        hit = _lookup_actor_hit(display, table)
        if isinstance(hit, dict):
            add_variants(str(hit.get("name") or ""))
            add_variants(str(hit.get("zh") or ""))
            add_variants(str(hit.get("jp") or ""))
            add_variants(str(hit.get("ja") or ""))
        # 反向：所有指向同一标准名的 key（日文检索名多在键上）
        target_folds = {_fold_key(x) for x in (canon, display) if x}
        if isinstance(hit, dict):
            for f in ("name", "zh"):
                v = str(hit.get(f) or "").strip()
                if v:
                    target_folds.add(_fold_key(v))
        for k, v in table.items():
            if isinstance(v, dict):
                n = str(v.get("name") or v.get("zh") or "").strip()
                kn = str(k)
                if _fold_key(n) in target_folds or _fold_key(kn) in target_folds:
                    add_variants(kn)
                    add_variants(n)
                    add_variants(str(v.get("name") or ""))
                    add_variants(str(v.get("zh") or ""))
                    add_variants(str(v.get("jp") or ""))
                    add_variants(str(v.get("ja") or ""))
            elif isinstance(v, str):
                if _fold_key(v) in target_folds or _fold_key(str(k)) in target_folds:
                    add_variants(str(k))
                    add_variants(v)
    except Exception as e:  # noqa: BLE001
        log.debug("alias resolve failed %s: %s", display, e)
    return names


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
            index[_fold_key(stem)] = (str(folder), raw_file)
            # 也用完整文件名 stem；AI-Fix- 去前缀后也可查
            file_stem = raw_file.rsplit(".", 1)[0]
            index[_fold_key(file_stem)] = (str(folder), raw_file)
            if file_stem.lower().startswith("ai-fix-"):
                index[_fold_key(file_stem[7:])] = (str(folder), raw_file)
            if stem.lower().startswith("ai-fix-"):
                index[_fold_key(stem[7:])] = (str(folder), raw_file)

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
        for key in (_fold_key(alias), _fold_key(f"AI-Fix-{alias}")):
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
    aa = _fold_key(a)
    bb = _fold_key(b)
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

        from .makers_catalog_routes import _abs, _fetch_html, _javbus_bases
    except Exception as e:  # noqa: BLE001
        log.debug("javbus avatar import skip: %s", e)
        return None

    bases = tuple(_javbus_bases() or ())
    if not bases:
        return None
    for alias in aliases[:8]:
        if len(alias) < 2:
            continue
        enc = quote(alias)
        for base in bases:
            try:
                html = _fetch_html(
                    f"{base}/searchstar/{enc}", referer=f"{base}/", fast=True
                )
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


def _fetch_avatar_for_names(aliases: list[str]) -> tuple[bytes | None, str]:
    """返回 (bytes, source)；source=gfriends|javbus|''。"""
    data = _fetch_gfriends_avatar(aliases)
    if data:
        return data, "gfriends"
    data = _fetch_javbus_avatar(aliases)
    if data:
        return data, "javbus"
    return None, ""


def list_vector_actress_names(*, region: str = "", limit: int | None = None) -> list[str]:
    """从向量库汇总女优名（已映射展示名优先）。"""
    from .scrape_metadata_optimize import polish_actress_names
    from .scrap_library_embed import TABLE, ensure_schema, _region_match_values

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
        k = _fold_key(n)
        if not n or k in seen:
            continue
        if k in {_fold_key(x) for x in _NOISE_NAMES}:
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
            from . import scrap_library_embed as emb

            emb._FACETS_CACHE.clear()  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass
    return removed


def scrape_actress_avatars(
    *,
    force: bool = False,
    limit: int | None = None,
    region: str = "",
) -> dict[str, Any]:
    purged = purge_placeholder_avatars()
    if purged:
        _log(f"已清除占位空图 {purged} 张，将重试下载")
    names = list_vector_actress_names(region=region, limit=limit)
    total = len(names)
    _log(f"向量库女优 {total:,} 人")
    _progress(
        stage="scan",
        percent=2,
        label="拉取 GFriends 索引…",
        done=0,
        total=total,
    )
    try:
        _load_gfriends_index()
        _log("GFriends 索引已就绪 · 未命中将尝试 JavBus")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(str(e)) from e

    index = _load_index()
    ok = 0
    ok_gf = 0
    ok_jb = 0
    skip = 0
    miss = 0
    fail = 0
    miss_samples: list[str] = []
    workers = 6

    def one(name: str) -> tuple[str, str, str]:
        fname = _safe_filename(name)
        dest = avatar_dir() / fname
        if _avatar_file_ok(dest) and not force:
            return "skip", name, ""
        if dest.is_file() and not _avatar_file_ok(dest):
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        aliases = _alias_names(name)
        data, source = _fetch_avatar_for_names(aliases)
        if not data or _is_placeholder_image(data):
            return "miss", name, ""
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
        futs = {pool.submit(one, n): n for n in names}
        for fut in as_completed(futs):
            status, name, source = fut.result()
            done += 1
            if status == "ok":
                ok += 1
                if source == "javbus":
                    ok_jb += 1
                else:
                    ok_gf += 1
                fname = _safe_filename(name)
                for alias in _alias_names(name):
                    index[_fold_key(alias)] = fname
                index[_fold_key(name)] = fname
            elif status == "skip":
                skip += 1
                fname = _safe_filename(name)
                for alias in _alias_names(name):
                    index.setdefault(_fold_key(alias), fname)
            elif status == "miss":
                miss += 1
                if len(miss_samples) < 40:
                    miss_samples.append(name)
            else:
                fail += 1
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
                    _log(
                        f"进度 {done}/{total} · 成功 {ok}"
                        f"（GF {ok_gf}/JB {ok_jb}）· 跳过 {skip} · 未命中 {miss}"
                    )

    _save_index(index)
    # 清女优分面内存缓存，下次列表优先读头像
    try:
        from . import scrap_library_embed as emb

        emb._FACETS_CACHE.clear()  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass

    if miss_samples:
        _log("未命中样例: " + "、".join(miss_samples[:20]))

    result = {
        "ok": True,
        "total": total,
        "downloaded": ok,
        "downloadedGfriends": ok_gf,
        "downloadedJavbus": ok_jb,
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
        f"完成 · 新下 {ok}（GFriends {ok_gf} · JavBus {ok_jb}）"
        f" · 已有跳过 {skip} · 未命中 {miss} · 失败 {fail}"
    )
    return result


def start_actress_avatar_job(
    *, force: bool = False, limit: int | None = None, region: str = ""
) -> dict[str, Any]:
    from .scrap_library_embed import get_job_status as get_embed_job

    with _job_lock:
        if _job["running"]:
            raise RuntimeError("女优头像刮削已在运行")
        if get_embed_job().get("running"):
            raise RuntimeError("刮削库向量同步进行中，请稍后再试")
        _job.update(
            {
                "running": True,
                "phase": "starting",
                "progress": {
                    "stage": "prepare",
                    "percent": 0,
                    "label": "starting",
                    "done": 0,
                    "total": None,
                },
                "log": [],
                "result": None,
                "error": None,
            }
        )

    def run() -> None:
        try:
            result = scrape_actress_avatars(
                force=force, limit=limit, region=region
            )
            with _job_lock:
                _job["result"] = result
                _job["phase"] = "done"
        except Exception as e:  # noqa: BLE001
            log.exception("actress avatar scrape failed")
            with _job_lock:
                _job["error"] = str(e)
                _job["phase"] = "error"
                rows = list(_job.get("log") or [])
                rows.append(f"失败: {e}")
                _job["log"] = rows[-40:]
        finally:
            with _job_lock:
                _job["running"] = False

    threading.Thread(
        target=run, name="scrap-actress-avatar", daemon=True
    ).start()
    return {"started": True}
