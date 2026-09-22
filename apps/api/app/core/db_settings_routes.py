"""DB 连接设置路由。

`/settings/resource-db/*` 与 `/settings/bitmagnet-db/*` 两组端点此前在
``app.main`` 里各写了一遍（14 个近乎逐行的重复端点 + 两段重复的 PG 错误映射）。
这里收敛为**单一参数化实现**：``build_db_settings_router()`` 按参数生成一组端点，
``test_postgres_dsn()`` 是 PG 连接测试的唯一实现。

⚠️ 本模块**故意不写** ``from __future__ import annotations``：
工厂内部用变量作参数类型注解（``body: config_model``），需要注解在函数定义时求值为
真实的 Pydantic 模型类，FastAPI 才能正确生成请求体 schema。
"""

import importlib
import logging
from typing import Any, Callable

import psycopg
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

import app.core.pg_data_backup as pg_data_backup
import app.core.settings_store as settings_store
from app.auth.routes import require_admin, require_user

log = logging.getLogger(__name__)


class Envelope(BaseModel):
    data: Any = None
    message: str = "ok"
    status: int = 200


class ResourceDbConfig(BaseModel):
    enabled: bool = False
    dsn: str = Field(
        default="",
        description="Postgres DSN, e.g. postgresql://user:pass@host:5432/ed2k",
    )
    note: str = ""


class BitmagnetDbConfig(BaseModel):
    enabled: bool = False
    dsn: str = Field(
        default="",
        description="Bitmagnet Postgres DSN, e.g. postgresql://user:pass@host:5432/bitmagnet",
    )
    note: str = ""


class DbBackupImportBody(BaseModel):
    filename: str = Field(..., min_length=1)


class DbEmbedStartBody(BaseModel):
    force: bool = False


def test_postgres_dsn(dsn: str, *, refused_hint: str) -> Envelope:
    """PG 连接自检的唯一实现（对外返回 Envelope，不抛异常）。

    原 ``app.main.test_resource_db`` 与 ``app.main._test_postgres_dsn`` 是同一段
    错误映射写了两遍，此处合一；差异仅剩「连接被拒绝」的提示文案，用参数传入。
    """
    if not str(dsn).strip():
        raise HTTPException(status_code=400, detail="请填写连接信息")
    try:
        with psycopg.connect(str(dsn).strip(), connect_timeout=5) as conn:
            conn.execute("SELECT 1")
        return Envelope(data={"ok": True}, message="可以连接")
    except Exception as e:  # noqa: BLE001
        raw = str(e) or "连接失败"
        low = raw.lower()
        if "password authentication failed" in low:
            msg = "密码认证失败：密码不对，或该库实际需要密码"
        elif "no password supplied" in low:
            msg = (
                "服务器要求密码：本机 psql 可能免密，"
                "但从本机 API 连 192.168.x 等远程地址通常必须填密码"
            )
        elif "could not translate host" in low or "name or service not known" in low:
            msg = "主机无法解析：请检查主机地址"
        elif "connection refused" in low:
            msg = refused_hint
        elif "timeout" in low:
            msg = "连接超时：请确认主机/防火墙/端口可达"
        else:
            msg = raw
        return Envelope(data={"ok": False}, message=msg, status=200)


def build_db_settings_router(
    *,
    prefix: str,
    tag: str,
    setting_key: str,
    config_model: type[BaseModel],
    backup_kind: str,
    dsn_required_detail: str,
    refused_hint: str,
    backup_filename_desc: str,
    close_pool: Callable[[], None],
    embed_module: str,
    operation_prefix: str,
) -> APIRouter:
    """按参数生成一组 DB 设置端点（GET / PUT / test / backups×3 / embed×5）。"""
    router = APIRouter(prefix=prefix, tags=[tag])

    def _dsn_or_400() -> str:
        raw = settings_store.get_setting(setting_key) or {}
        dsn = str(raw.get("dsn") or "").strip()
        if not bool(raw.get("enabled")) or not dsn:
            raise HTTPException(status_code=400, detail=dsn_required_detail)
        return dsn

    def _embed_svc():
        # 惰性导入：避免启动期就加载向量服务（体积大、连接池重）。
        return importlib.import_module(embed_module)

    @router.get("", response_model=Envelope, operation_id=f"{operation_prefix}_get")
    def get_db(_user: dict[str, Any] = Depends(require_user)) -> Envelope:
        raw = settings_store.get_setting(setting_key)
        cfg = config_model.model_validate(raw or {})
        public = cfg.model_dump()
        configured = bool(cfg.enabled and cfg.dsn.strip())
        return Envelope(
            data={**public, "configured": configured},
            message="configured" if configured else "not_configured",
        )

    @router.put("", response_model=Envelope, operation_id=f"{operation_prefix}_put")
    def put_db(
        body: config_model,  # type: ignore[valid-type]
        _user: dict[str, Any] = Depends(require_admin),
    ) -> Envelope:
        saved = settings_store.put_setting(setting_key, body.model_dump())
        close_pool()  # DSN 变更后重建连接池
        configured = bool(body.enabled and body.dsn.strip())
        return Envelope(
            data={
                **saved["value"],
                "configured": configured,
                "updated_at": saved["updated_at"],
            },
            message="saved",
        )

    @router.post("/test", response_model=Envelope, operation_id=f"{operation_prefix}_test")
    def test_db(
        body: config_model,  # type: ignore[valid-type]
        _user: dict[str, Any] = Depends(require_admin),
    ) -> Envelope:
        return test_postgres_dsn(body.dsn, refused_hint=refused_hint)

    @router.get("/backups", response_model=Envelope, operation_id=f"{operation_prefix}_backups_list")
    def list_backups(_user: dict[str, Any] = Depends(require_admin)) -> Envelope:
        return Envelope(data={"items": pg_data_backup.list_backups(backup_kind)})

    @router.post("/backups/export", response_model=Envelope, operation_id=f"{operation_prefix}_backups_export")
    def export_backup(_user: dict[str, Any] = Depends(require_admin)) -> Envelope:
        try:
            result = pg_data_backup.export_resource_zip(
                _dsn_or_400(),
                kind=backup_kind,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"导出失败：{e}") from e
        return Envelope(data=result, message="已导出到 backups")

    @router.post("/backups/import", response_model=Envelope, operation_id=f"{operation_prefix}_backups_import")
    def import_backup(
        body: DbBackupImportBody,
        _user: dict[str, Any] = Depends(require_admin),
    ) -> Envelope:
        try:
            result = pg_data_backup.import_resource_zip(
                _dsn_or_400(),
                body.filename.strip(),
                kind=backup_kind,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"导入失败：{e}") from e
        return Envelope(data=result, message="已从备份恢复资源数据")

    @router.post(
        "/backups/upload-import",
        response_model=Envelope,
        operation_id=f"{operation_prefix}_backups_upload_import",
    )
    async def upload_import_backup(
        file: UploadFile = File(..., description=backup_filename_desc),
        _user: dict[str, Any] = Depends(require_admin),
    ) -> Envelope:
        dsn = _dsn_or_400()
        saved: dict[str, Any] = {}
        restored: dict[str, Any] = {}
        try:
            saved = pg_data_backup.save_uploaded_zip(
                backup_kind,
                source=file.file,
                original_name=file.filename or "",
            )
            restored = pg_data_backup.import_resource_zip(
                dsn,
                str(saved["filename"]),
                kind=backup_kind,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"导入失败：{e}") from e
        finally:
            await file.close()
        return Envelope(data={**saved, **restored}, message="已上传并恢复资源数据")

    @router.get("/embed/stats", response_model=Envelope, operation_id=f"{operation_prefix}_embed_stats")
    def embed_stats(_user: dict[str, Any] = Depends(require_admin)) -> Envelope:
        try:
            return Envelope(data=_embed_svc().stats())
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e)) from e

    @router.get("/embed/status", response_model=Envelope, operation_id=f"{operation_prefix}_embed_status")
    def embed_status(_user: dict[str, Any] = Depends(require_admin)) -> Envelope:
        return Envelope(data=_embed_svc().get_job_status())

    @router.post("/embed/start", response_model=Envelope, operation_id=f"{operation_prefix}_embed_start")
    def embed_start(
        body: DbEmbedStartBody,
        _user: dict[str, Any] = Depends(require_admin),
    ) -> Envelope:
        svc = _embed_svc()
        _dsn_or_400()
        try:
            result = svc.start_ingest_job(force=bool(body.force))
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
        return Envelope(data=result, message="已开始同步向量")

    @router.post("/embed/stop", response_model=Envelope, operation_id=f"{operation_prefix}_embed_stop")
    def embed_stop(_user: dict[str, Any] = Depends(require_admin)) -> Envelope:
        return Envelope(data=_embed_svc().request_stop(), message="正在暂停")

    @router.post(
        "/embed/create-index",
        response_model=Envelope,
        operation_id=f"{operation_prefix}_embed_create_index",
    )
    def embed_create_index(_user: dict[str, Any] = Depends(require_admin)) -> Envelope:
        _dsn_or_400()
        try:
            return Envelope(data=_embed_svc().create_hnsw_index(), message="索引已创建")
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(e)) from e

    return router
