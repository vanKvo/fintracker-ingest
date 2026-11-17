"""The import record as stored (IN-IMP Appendix B). Holds no statement content.

__author__ = "Van Vo"
"""

from __future__ import annotations

from typing import Any, TypedDict

OPEN_STATUSES = ("SCAN_PENDING", "PREVIEW_READY")
ENDED_STATUSES = ("COMPLETED", "FAILED", "CANCELLED", "EXPIRED")


class ImportItem(TypedDict, total=False):
    importId: str
    userId: str
    accountId: str
    accountClass: str
    bankId: str
    s3Key: str
    fileType: str
    household: list[dict[str, Any]]
    status: str
    reason: str
    profile: dict[str, Any]
    proposedProfile: dict[str, Any]
    profileSource: str
    signature: str
    headers: list[str]
    sheet: str
    overlapCheck: str
    unconfirmed: list[str]
    differences: dict[str, str]
    createdAt: str
    previewedAt: str
    updatedAt: str
    endedAt: str
    result: dict[str, int]
    ttl: int
