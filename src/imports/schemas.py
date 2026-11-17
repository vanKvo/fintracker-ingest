"""API shapes (IN-IMP Appendix A).

__author__ = "Van Vo"
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class StartImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statementId: UUID


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: dict[str, Any] | None = None
    sheet: str | None = Field(default=None, max_length=200)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: dict[str, Any]
    excludedRows: list[int] = Field(default_factory=list, max_length=5000)
    includedRows: list[int] = Field(default_factory=list, max_length=5000)
    importAnyway: bool = False


class HeaderUse(BaseModel):
    name: str
    field: str | None


class PreviewRow(BaseModel):
    rowNumber: int
    date: str
    description: str
    amount: str
    direction: str
    type: str
    reviewReason: str | None
    alreadyImported: bool


class ImportResponse(BaseModel):
    importId: str
    status: str
    reason: str | None = None
    fileType: str | None = None
    sheet: str | None = None
    sheets: list[str] = []
    profile: dict[str, Any] | None = None
    profileSource: str | None = None
    unconfirmedFields: list[str] = []
    baselineDifferences: dict[str, str] = {}
    problems: list[str] = []
    headers: list[HeaderUse] = []
    period: dict[str, str] | None = None
    counts: dict[str, int] = {}
    overlapCheck: str | None = None
    rows: list[PreviewRow] = []
    unreadableRows: list[int] = []
    result: dict[str, int] | None = None
