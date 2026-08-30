"""统一、可追踪且不会向客户端泄露内部细节的 API 错误。"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("bonfire.errors")


@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400
    diagnostic: str | None = None
    context: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


def _response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = _request_id(request)
    # detail 保持前端兼容；error 提供稳定的机器可读结构。
    return JSONResponse(
        status_code=status,
        content={
            "detail": message,
            "error": {"code": code, "message": message, "request_id": request_id},
        },
        headers={"X-Request-ID": request_id},
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    log.warning(
        "request_id=%s code=%s diagnostic=%s context=%s",
        _request_id(request), exc.code, exc.diagnostic, exc.context,
    )
    return _response(request, exc.status_code, exc.code, exc.message)


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    message = exc.detail if isinstance(exc.detail, str) else "请求无法完成"
    code = {
        400: "BAD_REQUEST", 401: "AUTHENTICATION_REQUIRED", 403: "ACCESS_DENIED",
        404: "RESOURCE_NOT_FOUND", 409: "RESOURCE_CONFLICT", 422: "VALIDATION_ERROR",
        502: "UPSTREAM_ERROR", 503: "DEPENDENCY_UNAVAILABLE",
    }.get(exc.status_code, "REQUEST_FAILED")
    return _response(request, exc.status_code, code, message)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic 的 input 可能包含密码、令牌或大段业务数据，不能原样返回。
    fields = [".".join(str(x) for x in item.get("loc", ())) for item in exc.errors()]
    message = "请求参数格式不正确" + (f"：{', '.join(fields[:5])}" if fields else "")
    log.info("request_id=%s validation_fields=%s", _request_id(request), fields)
    return _response(request, 422, "VALIDATION_ERROR", message)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _request_id(request)
    log.exception("request_id=%s unhandled error", request_id, exc_info=exc)
    return _response(request, 500, "INTERNAL_ERROR", f"系统内部错误，请联系管理员并提供请求编号 {request_id}")
