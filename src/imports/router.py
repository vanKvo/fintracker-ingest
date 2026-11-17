"""Import routes (IN-IMP Appendix A). The user comes only from the identity authorizer (invariant 2).

__author__ = "Van Vo"
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ..core.identity import get_user_id
from . import service
from .schemas import ConfirmRequest, ImportResponse, PreviewRequest, StartImportRequest

router = APIRouter(prefix="/api/v1/ingest/imports", tags=["imports"])


@router.post("", response_model=ImportResponse)
async def start_import(body: StartImportRequest, user_id: str = Depends(get_user_id)) -> ImportResponse:
    return await service.start_import(user_id, str(body.statementId))


@router.get("/{import_id}", response_model=ImportResponse)
async def get_import(import_id: str, user_id: str = Depends(get_user_id)) -> ImportResponse:
    return await service.get_import(user_id, import_id)


@router.post("/{import_id}/preview", response_model=ImportResponse)
async def preview(import_id: str, body: PreviewRequest, user_id: str = Depends(get_user_id)) -> ImportResponse:
    return await service.preview(user_id, import_id, body.profile, body.sheet)


@router.post("/{import_id}/confirm", response_model=ImportResponse)
async def confirm(import_id: str, body: ConfirmRequest, user_id: str = Depends(get_user_id)) -> ImportResponse:
    return await service.confirm(user_id, import_id, body.profile, body.excludedRows, body.includedRows, body.importAnyway)


@router.post("/{import_id}/cancel", status_code=204)
async def cancel(import_id: str, user_id: str = Depends(get_user_id)) -> Response:
    await service.cancel(user_id, import_id)
    return Response(status_code=204)
