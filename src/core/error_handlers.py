"""The one place errors become HTTP responses: RFC 9457 problem+json (app doc 4.8, XS-IMP-04).

Exception text never reaches the client; unexpected errors are logged with their type only.

__author__ = "Van Vo"
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .exceptions import AppError, InvalidRequestError, NotFoundError
from .observability import logger

TYPE_BASE = "https://fintracker.app/errors/"
PROBLEM_JSON = "application/problem+json"


def problem(error: AppError) -> JSONResponse:
    trace_id = uuid.uuid4().hex
    body: dict[str, object] = {
        "type": TYPE_BASE + error.code.lower().replace("_", "-"),
        "title": error.title, "status": error.status, "detail": error.detail,
        "code": error.code, "retryable": error.retryable, "trace_id": trace_id,
    }
    if error.fields:
        body["fields"] = error.fields
    if error.reason:
        body["reason"] = error.reason
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    log = logger.error if error.status >= 500 else logger.warning
    log("REQUEST_FAILED", code=error.code, status=error.status, trace_id=trace_id, detail=error.log_message)
    return JSONResponse(status_code=error.status, content=body, media_type=PROBLEM_JSON, headers=headers)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return problem(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e.get("loc", ())[1:]) for e in exc.errors()]
        return problem(InvalidRequestError(fields=fields, log_message="request validation failed"))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            return problem(NotFoundError(log_message="no such route"))
        error = AppError(log_message=f"http {exc.status_code}")
        error.status = exc.status_code
        return problem(error)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.error("UNEXPECTED_ERROR", error_type=type(exc).__name__)
        return problem(AppError(log_message=type(exc).__name__))
