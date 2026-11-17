"""IN-IMP-08: the cleanup job ends imports nobody finished.

__author__ = "Van Vo"
"""

from __future__ import annotations

import logging

import boto3
import pytest

from tests.service.conftest import IMPORTS_TABLE, STATEMENT, Clock, FakeLedger, call, start


def run_sweep() -> dict[str, int]:
    from src.sweep.handler import handler

    return handler({}, None)


def set_status(status: str) -> None:
    boto3.resource("dynamodb").Table(IMPORTS_TABLE).update_item(
        Key={"importId": STATEMENT}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status})


def test_in_imp_08_unconfirmed_preview_expires_after_30_minutes(ledger: FakeLedger, clock: Clock) -> None:
    """IN-IMP-08 cancel and expiry: a preview nobody confirmed for 30 minutes is ended as expired."""
    start()
    clock.advance(minutes=29)
    run_sweep()
    assert call("GET", f"/api/v1/ingest/imports/{STATEMENT}")[1]["status"] == "PREVIEW_READY"
    clock.advance(minutes=2)
    assert run_sweep() == {"expired": 1, "scanTimedOut": 0, "stuck": 0}
    body = call("GET", f"/api/v1/ingest/imports/{STATEMENT}")[1]
    assert (body["status"], body["reason"]) == ("EXPIRED", "IMPORT_EXPIRED")
    assert ledger.calls("failure") == [{"reasonCode": "IMPORT_EXPIRED"}]


def test_in_imp_08_scan_never_finishing_fails_after_15_minutes(ledger: FakeLedger, clock: Clock, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """IN-IMP-08 cancel and expiry: a file still waiting for its scan after 15 minutes fails the security check."""
    monkeypatch.setenv("MALWARE_SCAN_REQUIRED", "true")
    start()
    clock.advance(minutes=16)
    with caplog.at_level(logging.WARNING):
        assert run_sweep()["scanTimedOut"] == 1
    assert ledger.calls("failure") == [{"reasonCode": "MALWARE_SCAN_FAILED"}]
    assert any("SCAN_TIMEOUT" in r.getMessage() for r in caplog.records)


def test_in_imp_08_import_stuck_while_importing_fails_after_5_minutes(ledger: FakeLedger, clock: Clock) -> None:
    """IN-IMP-08 cancel and expiry: an import stuck while importing for 5 minutes fails on our side."""
    start()
    set_status("IMPORTING")
    clock.advance(minutes=6)
    assert run_sweep()["stuck"] == 1
    assert ledger.calls("failure") == [{"reasonCode": "LEDGER_PUSH_FAILED"}]


def test_in_imp_08_first_run_after_switching_on_catches_up(ledger: FakeLedger, clock: Clock) -> None:
    """IN-IMP-08 cancel and expiry: imports are picked by age, so a run after hours off ends every overdue one."""
    start()
    clock.advance(hours=3)
    assert run_sweep()["expired"] == 1


def test_in_imp_08_sweep_failure_is_logged_for_the_alarm(ledger: FakeLedger, clock: Clock, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """IN-IMP-08 cancel and expiry: a failed run logs SWEEP_FAILED, and the next run picks up the same imports."""
    start()
    clock.advance(minutes=40)
    monkeypatch.setenv("IMPORTS_TABLE", "missing-table")
    with caplog.at_level(logging.ERROR), pytest.raises(Exception):
        run_sweep()
    assert any("SWEEP_FAILED" in r.getMessage() for r in caplog.records)
    monkeypatch.setenv("IMPORTS_TABLE", IMPORTS_TABLE)
    assert run_sweep()["expired"] == 1
