"""Calls to the Ledger's internal API (XS-IMP-02, XS-IMP-05, -06, -07, LG-STMT-02).

Every call is signed by the library (SigV4 deployed, a caller header locally) and carries the
verified user as X-Internal-User-Id only (invariant 3). Bodies carry no user or account ID beyond the
account the overlap check names, which the Ledger checks against that user.

__author__ = "Van Vo"
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fintracker_internal_http import InternalCallError, InternalClient, InternalResponse, UserContext

from ..core.observability import logger
from .schemas import BulkAnswer, OverlapAnswer, StatementOwnerModel

_transport: httpx.AsyncBaseTransport | None = None
_RETRY_STATUSES = {429, 502, 503, 504}
_BACKOFF = (0.05, 0.1, 0.2)

STATEMENTS = "/api/v1/ledger/statements/internal"
TRANSACTIONS = "/api/v1/ledger/transactions/internal"


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Tests only: send every Ledger call through `transport`."""
    global _transport
    _transport = transport


async def _request(method: str, path: str, user_id: str, *, json: Any = None, attempts: int = 1,
                   accept: tuple[int, ...] = (), deadline: float | None = None) -> InternalResponse:
    options: dict[str, Any] = {} if deadline is None else {"deadline": deadline, "read_timeout": deadline}
    for attempt in range(attempts):
        try:
            async with InternalClient.from_env("LEDGER", transport=_transport) as client:
                return await client.request(method, path, user=UserContext(user_id=user_id), require=("user",),
                                            json=json, accept=accept, **options)
        except InternalCallError as error:
            if attempt + 1 == attempts or error.status not in _RETRY_STATUSES:
                raise
            await asyncio.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
    raise AssertionError("unreachable")  # pragma: no cover


async def get_owner(statement_id: str, user_id: str) -> StatementOwnerModel | None:
    """XS-IMP-05. None when the Ledger has no such statement. GETs are retried by the library (3 tries)."""
    response = await _request("GET", f"{STATEMENTS}/{statement_id}/owner", user_id, accept=(404,))
    if response.status == 404:
        return None
    return StatementOwnerModel.model_validate(response.body)


async def overlap_check(user_id: str, account_id: str, rows: list[dict[str, Any]]) -> dict[int, str]:
    """XS-IMP-06: row number → the existing transaction it matches. Raises InternalCallError; gives up after 5 s."""
    response = await _request("POST", f"{TRANSACTIONS}/overlap-check", user_id,
                              json={"accountId": account_id, "rows": rows}, deadline=5.0)
    answer = OverlapAnswer.model_validate(response.body or {})
    return {m.rowNumber: m.transactionId for m in answer.matches}


async def set_period(statement_id: str, user_id: str, opening: str, closing: str) -> None:
    """XS-IMP-07."""
    await _request("PATCH", f"{STATEMENTS}/{statement_id}/period", user_id,
                   json={"openingDate": opening, "closingDate": closing}, attempts=4)


async def push_bulk(user_id: str, package: dict[str, Any]) -> BulkAnswer:
    """LG-STMT-02: one package per import; safe to retry (row fingerprints)."""
    response = await _request("POST", f"{TRANSACTIONS}/bulk", user_id, json=package, attempts=4,
                              deadline=25.0)
    return BulkAnswer.model_validate(response.body or {})


async def report_failure(statement_id: str, user_id: str, reason: str) -> bool:
    """XS-IMP-02. False (and logged for the alarm) when the Ledger couldn't be told after 4 tries."""
    try:
        await _request("POST", f"{STATEMENTS}/{statement_id}/import-failure", user_id,
                       json={"reasonCode": reason}, attempts=4, accept=(409,))
        return True
    except InternalCallError as error:
        logger.error("LEDGER_FAILURE_NOTICE_FAILED", import_id=statement_id, status=error.status, code=error.code)
        return False


__all__ = ["InternalCallError", "get_owner", "overlap_check", "set_period", "push_bulk", "report_failure", "use_transport"]
