"""Service-test harness: the real Lambda entry point (Mangum + FastAPI), DynamoDB and S3 through moto,
and a fake Ledger at the HTTP edge. Nothing between our own classes is faked.

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterator

import boto3
import httpx
import pytest
from moto import mock_aws
import uuid


def U(name: str) -> str:
    """A stable user ID for a readable test name."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))

USER = "aaaaaaaa-0000-4000-8000-000000000001"
OTHER_USER = "aaaaaaaa-0000-4000-8000-000000000002"
ACCOUNT = "bbbbbbbb-0000-4000-8000-000000000001"
STATEMENT = "11111111-1111-1111-1111-111111111111"
BUCKET = "statements-test"
IMPORTS_TABLE = "FinTracker_Imports"
PROFILES_TABLE = "FinTracker_FormatProfiles"
START = dt.datetime(2026, 11, 16, 15, 0, tzinfo=dt.timezone.utc)

CHASE_CARD_CSV = (
    "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
    "01/03/2026,01/04/2026,STARBUCKS #12345,Food & Drink,Sale,-5.75,\n"
    "01/05/2026,01/05/2026,WHOLEFDS MKT,Groceries,Sale,-82.10,\n"
    "01/09/2026,01/09/2026,Payment Thank You-Mobile,,Payment,500.00,\n"
    "01/10/2026,01/11/2026,AMAZON RETURN,Shopping,Return,25.00,\n"
    "02/02/2026,02/03/2026,NETFLIX.COM,Entertainment,Sale,-15.49,\n"
)


@dataclass
class FakeLedger(httpx.AsyncBaseTransport):
    """The Ledger's internal API as Ingest sees it (XS-IMP-05/06/07, LG-STMT-02, XS-IMP-02)."""

    statements: dict[str, dict[str, Any]] = field(default_factory=dict)
    existing: list[dict[str, Any]] = field(default_factory=list)  # account's transactions for the overlap check
    requests: list[tuple[str, str, dict[str, str], Any]] = field(default_factory=list)
    failures: dict[str, list[int]] = field(default_factory=dict)  # route -> statuses to answer first
    bulk_failed_rows: int = 0

    def fail(self, route: str, *statuses: int) -> None:
        self.failures.setdefault(route, []).extend(statuses)

    def calls(self, route: str) -> list[Any]:
        return [body for r, _, _, body in self.requests if r == route]

    def headers_of(self, route: str) -> list[dict[str, str]]:
        return [h for r, _, h, _ in self.requests if r == route]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        headers = {k.lower(): v for k, v in request.headers.items()}
        route = self._route(request.method, path)
        self.requests.append((route, path, headers, body))
        pending = self.failures.get(route)
        if pending:
            return httpx.Response(pending.pop(0), json={"code": "failure"})
        return self._answer(route, path, body, headers)

    @staticmethod
    def _route(method: str, path: str) -> str:
        if path.endswith("/owner"):
            return "owner"
        if path.endswith("/overlap-check"):
            return "overlap"
        if path.endswith("/period"):
            return "period"
        if path.endswith("/transactions/internal/bulk"):
            return "bulk"
        if path.endswith("/import-failure"):
            return "failure"
        return f"{method} {path}"

    def _answer(self, route: str, path: str, body: Any, headers: dict[str, str]) -> httpx.Response:
        if route == "owner":
            statement = self.statements.get(path.split("/")[-2])
            if statement is None:
                return httpx.Response(404, json={"code": "not_found"})
            answer = dict(statement)
            if headers.get("x-internal-user-id") != statement["userId"]:
                answer["householdAccounts"] = []
            return httpx.Response(200, json=answer)
        if route == "overlap":
            remaining = list(self.existing)
            matches = []
            for row in sorted(body["rows"], key=lambda r: r["rowNumber"]):
                for tx in remaining:
                    if (tx["date"], Decimal(tx["amount"]), tx["direction"]) == (row["date"], Decimal(row["amount"]), row["direction"]) and (
                        tx.get("merchantKey") in (None, row["merchantKey"])
                    ):
                        matches.append({"rowNumber": row["rowNumber"], "transactionId": tx["id"], "status": "POSTED"})
                        remaining.remove(tx)
                        break
            return httpx.Response(200, json={"matches": matches})
        if route == "bulk":
            n = len(body["transactions"])
            failed = [{"index": i, "reason": "INVALID_ROW"} for i in range(self.bulk_failed_rows)]
            return httpx.Response(200, json={"packageId": body["packageId"], "insertedCount": n - len(failed),
                                             "skippedDuplicateCount": 0, "failedRows": failed, "results": []})
        if route in ("period", "failure"):
            return httpx.Response(204)
        return httpx.Response(404)


def statement(**overrides: Any) -> dict[str, Any]:
    base = {
        "statementId": STATEMENT, "accountId": ACCOUNT, "userId": USER, "openingDate": None, "closingDate": None,
        "accountType": "CREDIT", "bankId": "chase", "sourceFormat": "CSV", "status": "PROCESSING",
        "s3Key": f"statements/{STATEMENT}.csv", "householdAccounts": [],
    }
    base.update(overrides)
    return base


class Clock:
    def __init__(self) -> None:
        self.now = START

    def advance(self, **kwargs: float) -> None:
        self.now = self.now + dt.timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    from src.core import clock as clock_module

    c = Clock()
    monkeypatch.setattr(clock_module, "_now", lambda: c.now)
    return c


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key, value in {
        "AWS_DEFAULT_REGION": "us-east-1", "AWS_REGION": "us-east-1", "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test", "IMPORTS_TABLE": IMPORTS_TABLE, "PROFILES_TABLE": PROFILES_TABLE,
        "STATEMENT_BUCKET": BUCKET, "INTERNAL_AUTH_MODE": "local", "INTERNAL_BASE_URL_LEDGER": "http://ledger.test",
        "MALWARE_SCAN_REQUIRED": "false", "PROMOTION_TOPIC_ARN": "",
    }.items():
        monkeypatch.setenv(key, value)
    with mock_aws():
        from src.imports.repository import create_table as create_imports_table
        from src.profiles.store import create_table as create_profiles_table

        create_imports_table()
        create_profiles_table()
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield


@pytest.fixture
def ledger(aws: None) -> Iterator[FakeLedger]:
    from src.ledger import client

    fake = FakeLedger()
    fake.statements[STATEMENT] = statement()
    client.use_transport(fake)
    yield fake
    client.use_transport(None)


def put_file(text: str | bytes, key: str = f"statements/{STATEMENT}.csv", scan: str | None = None) -> None:
    body = text.encode() if isinstance(text, str) else text
    s3 = boto3.client("s3")
    s3.put_object(Bucket=BUCKET, Key=key, Body=body)
    if scan is not None:
        s3.put_object_tagging(Bucket=BUCKET, Key=key, Tagging={"TagSet": [{"Key": "GuardDutyMalwareScanStatus", "Value": scan}]})


class _Context:
    function_name = "ingest-api"
    aws_request_id = "req-1"
    invoked_function_arn = "arn:aws:lambda:us-east-1:111111111111:function:ingest-api"
    memory_limit_in_mb = 512

    @staticmethod
    def get_remaining_time_in_millis() -> int:
        return 30000


def call(method: str, path: str, body: Any = None, user: str | None = USER) -> tuple[int, Any, dict[str, str]]:
    """One request through the deployed entry point, as API Gateway (HTTP API, payload v2) sends it."""
    from src.main import handler

    request_context: dict[str, Any] = {
        "http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "203.0.113.1", "userAgent": "test"},
        "requestId": "req-1", "routeKey": "$default", "stage": "$default", "accountId": "111111111111",
        "apiId": "api", "domainName": "api.test", "time": "16/Nov/2026:15:00:00 +0000", "timeEpoch": 0,
    }
    if user is not None:
        request_context["authorizer"] = {"lambda": {"internal_user_id": user}}
    event = {
        "version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "",
        "headers": {"content-type": "application/json", "host": "api.test"},
        "requestContext": request_context,
        "body": json.dumps(body) if body is not None else None, "isBase64Encoded": False,
    }
    response = handler(event, _Context())
    payload = json.loads(response["body"]) if response.get("body") else None
    return response["statusCode"], payload, {k.lower(): v for k, v in (response.get("headers") or {}).items()}


def start(text: str | bytes = CHASE_CARD_CSV, **kwargs: Any) -> tuple[int, Any, dict[str, str]]:
    put_file(text, **kwargs)
    return call("POST", "/api/v1/ingest/imports", {"statementId": STATEMENT})
