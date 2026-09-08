# -*- coding: utf-8 -*-
"""115 小文件直传（sampleinitupload → OSS multipart）。

用于字幕等小文件；大文件应走秒传/分片接口（此处不做）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from . import p115_client

log = logging.getLogger(__name__)

SAMPLE_INIT = "https://uplb.115.com/3.0/sampleinitupload.php"
MAX_SAMPLE_BYTES = 20 * 1024 * 1024


def upload_local_file(
    cookie: str,
    path: Path | str,
    *,
    folder_cid: str = "0",
    filename: str | None = None,
) -> dict[str, Any]:
    """上传本地文件到指定目录 cid。"""
    err = p115_client.require_cookie_parts(cookie)
    if err:
        raise RuntimeError(err)
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    size = p.stat().st_size
    if size <= 0:
        raise RuntimeError("空文件无法上传")
    if size > MAX_SAMPLE_BYTES:
        raise RuntimeError(f"文件过大（>{MAX_SAMPLE_BYTES // (1024 * 1024)}MB），请改用客户端上传")
    name = (filename or p.name).strip() or p.name
    uid = p115_client.extract_uid(cookie)
    cid = str(folder_cid or "0").strip() or "0"
    target = f"U_1_{cid}"

    with httpx.Client(timeout=60.0, trust_env=False, follow_redirects=True) as client:
        init = client.post(
            SAMPLE_INIT,
            headers=p115_client.form_headers(cookie, "https://115.com/?cid=" + cid),
            content=p115_client.encode_form(
                [
                    ("userid", uid),
                    ("filename", name),
                    ("filesize", str(size)),
                    ("target", target),
                ]
            ),
        )
        init.raise_for_status()
        meta = init.json()
        if not isinstance(meta, dict):
            raise RuntimeError("115 上传初始化失败")
        # 部分失败用 errno / error
        if meta.get("error") or meta.get("errno"):
            raise RuntimeError(
                str(meta.get("error") or meta.get("message") or meta.get("errno") or "初始化失败")
            )
        host = str(meta.get("host") or "").strip()
        if not host:
            raise RuntimeError(f"115 上传初始化无 host: {meta}")

        data = p.read_bytes()
        files = {
            "name": (None, name),
            "key": (None, str(meta.get("object") or "")),
            "policy": (None, str(meta.get("policy") or "")),
            "OSSAccessKeyId": (None, str(meta.get("accessid") or "")),
            "success_action_status": (None, "200"),
            "callback": (None, str(meta.get("callback") or "")),
            "signature": (None, str(meta.get("signature") or "")),
            "file": (name, data, "application/octet-stream"),
        }
        up = client.post(host, files=files, timeout=120.0)
        # OSS 常返回 200 + JSON callback
        try:
            body = up.json()
        except Exception:
            body = {"raw": up.text[:300], "status_code": up.status_code}
        if up.status_code >= 400:
            raise RuntimeError(f"OSS 上传失败 HTTP {up.status_code}: {body}")
        if isinstance(body, dict) and body.get("state") is False:
            raise RuntimeError(str(body.get("message") or body.get("error") or body))
        return {
            "ok": True,
            "filename": name,
            "size": size,
            "folderCid": cid,
            "result": body if isinstance(body, dict) else {"raw": body},
        }


def upload_many(
    cookie: str,
    paths: list[Path | str],
    *,
    folder_cid: str = "0",
    filenames: list[str] | None = None,
) -> dict[str, Any]:
    uploaded: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    for idx, raw in enumerate(paths):
        p = Path(raw)
        name = None
        if filenames and idx < len(filenames) and filenames[idx]:
            name = str(filenames[idx]).strip() or None
        try:
            uploaded.append(
                upload_local_file(
                    cookie, p, folder_cid=folder_cid, filename=name or p.name
                )
            )
        except Exception as e:  # noqa: BLE001
            log.warning("115 upload %s failed: %s", p, e)
            failed.append({"file": name or p.name, "message": str(e)})
    return {
        "ok": len(failed) == 0 and len(uploaded) > 0,
        "uploaded": uploaded,
        "failed": failed,
        "count": len(uploaded),
    }
