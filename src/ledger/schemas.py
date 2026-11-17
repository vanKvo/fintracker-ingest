"""What the Ledger answers (XS-IMP-05, XS-IMP-06, LG-STMT-02). Validated where it enters.

__author__ = "Van Vo"
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HouseholdAccountModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    accountId: str
    accountType: str
    lastFour: str | None = None
    bankId: str | None = None


class StatementOwnerModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    statementId: str
    accountId: str
    userId: str
    accountType: str
    bankId: str | None = None
    sourceFormat: str
    status: str
    s3Key: str
    householdAccounts: list[HouseholdAccountModel] = []


class OverlapMatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rowNumber: int
    transactionId: str


class OverlapAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    matches: list[OverlapMatch] = []


class FailedRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    reason: str | None = None


class BulkAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    insertedCount: int = 0
    skippedDuplicateCount: int = 0
    failedRows: list[FailedRow] = []
