"""IN-IMP: the import flow through the deployed entry point — start, preview, confirm, cancel, failures.

__author__ = "Van Vo"
"""

from __future__ import annotations

import io
import logging

import boto3
import pytest
from openpyxl import Workbook

from tests.service.conftest import (
    ACCOUNT, BUCKET, CHASE_CARD_CSV, IMPORTS_TABLE, OTHER_USER, STATEMENT, USER, FakeLedger, call, put_file, start, statement,
)

BASE = "/api/v1/ingest/imports"


def path(suffix: str = "") -> str:
    return f"{BASE}/{STATEMENT}{suffix}"


def rows_by_description(body: dict) -> dict[str, dict]:  # type: ignore[type-arg]
    return {r["description"]: r for r in body["rows"]}


# --- IN-IMP-01: start an import ---

def test_in_imp_01_start_returns_the_preview(ledger: FakeLedger) -> None:
    """IN-IMP-01 start an import: right after the upload, the user gets the preview."""
    status, body, _ = start()
    assert status == 200
    assert body["importId"] == STATEMENT and body["status"] == "PREVIEW_READY"
    assert body["fileType"] == "CSV" and body["counts"]["read"] == 5


def test_in_imp_01_starting_again_returns_the_same_import(ledger: FakeLedger) -> None:
    """IN-IMP-01 start an import: asking again returns the import already under way, not a new one."""
    _, first, _ = start()
    table = boto3.resource("dynamodb").Table(IMPORTS_TABLE)
    created = table.get_item(Key={"importId": STATEMENT})["Item"]["createdAt"]
    status, second, _ = call("POST", BASE, {"statementId": STATEMENT})
    assert status == 200 and second["status"] == first["status"] and second["profile"] == first["profile"]
    assert table.get_item(Key={"importId": STATEMENT})["Item"]["createdAt"] == created


def test_in_imp_01_reopening_shows_the_preview(ledger: FakeLedger) -> None:
    """IN-IMP-01 start an import: an unfinished import can be reopened with its preview."""
    start()
    status, body, _ = call("GET", path())
    assert status == 200 and body["status"] == "PREVIEW_READY" and len(body["rows"]) == 5


@pytest.mark.parametrize("statement_id,user", [(STATEMENT, OTHER_USER), ("22222222-2222-2222-2222-222222222222", USER)])
def test_in_imp_01_other_users_or_unknown_statement_is_not_found(ledger: FakeLedger, statement_id: str, user: str) -> None:
    """IN-IMP-01 start an import: another user's statement, or an unknown one, is not found (invariant 5)."""
    put_file(CHASE_CARD_CSV)
    status, body, _ = call("POST", BASE, {"statementId": statement_id}, user=user)
    assert status == 404 and body["code"] == "NOT_FOUND"
    assert call("GET", f"{BASE}/{STATEMENT}", user=OTHER_USER)[0] == 404


def test_in_imp_01_finished_statement_is_answered_as_ended(ledger: FakeLedger) -> None:
    """IN-IMP-01 start an import: a statement that already finished or failed is answered as ended, with its reason."""
    ledger.statements[STATEMENT] = statement(status="FAILED")
    status, body, _ = start()
    assert status == 409 and body["code"] == "IMPORT_ENDED"


def test_in_imp_01_file_not_uploaded_yet_is_retryable_and_records_nothing(ledger: FakeLedger) -> None:
    """IN-IMP-01 start an import: a file not in storage yet is answered 'try again', and nothing is recorded."""
    status, body, _ = call("POST", BASE, {"statementId": STATEMENT})
    assert status == 409 and body["code"] == "FILE_NOT_UPLOADED" and body["retryable"] is True
    assert "Item" not in boto3.resource("dynamodb").Table(IMPORTS_TABLE).get_item(Key={"importId": STATEMENT})


def test_in_imp_01_ledger_unreachable_is_our_side_and_records_nothing(ledger: FakeLedger) -> None:
    """IN-IMP-01 start an import: the Ledger unreachable after 3 tries is 'our side', with nothing recorded."""
    ledger.fail("owner", 503, 503, 503, 503)
    status, body, _ = start()
    assert status == 503 and body["code"] == "PIPELINE_ERROR"
    assert "Item" not in boto3.resource("dynamodb").Table(IMPORTS_TABLE).get_item(Key={"importId": STATEMENT})


def test_in_imp_01_xlsx_statement_is_accepted(ledger: FakeLedger) -> None:
    """IN-IMP-01 start an import: Excel statements are imported like CSV ones."""
    ledger.statements[STATEMENT] = statement(sourceFormat="XLSX", s3Key=f"statements/{STATEMENT}.xlsx")
    wb = Workbook()
    ws = wb.active
    for line in CHASE_CARD_CSV.strip().split("\n"):
        ws.append(line.split(","))
    out = io.BytesIO()
    wb.save(out)
    status, body, _ = start(out.getvalue(), key=f"statements/{STATEMENT}.xlsx")
    assert status == 200 and body["fileType"] == "XLSX" and body["counts"]["read"] == 5


# --- IN-IMP-02: file and row limits ---

def test_in_imp_02_file_over_5_mb_fails_and_the_ledger_is_told(ledger: FakeLedger) -> None:
    """IN-IMP-02 file and row limits: a file over 25 MB ends the import as too large; the Ledger is told."""
    status, body, _ = start(b"x" * (25 * 1024 * 1024 + 1))
    assert status == 200 and (body["status"], body["reason"]) == ("FAILED", "FILE_TOO_LARGE")
    assert ledger.calls("failure") == [{"reasonCode": "FILE_TOO_LARGE"}]


def test_in_imp_02_more_than_5000_rows_fails(ledger: FakeLedger) -> None:
    """IN-IMP-02 file and row limits: more than 5,000 transactions ends the import with TOO_MANY_ROWS."""
    rows = "".join(f"01/15/2026,SHOP {i},-1.00\n" for i in range(5001))
    _, body, _ = start("Date,Description,Amount\n" + rows)
    assert (body["status"], body["reason"]) == ("FAILED", "TOO_MANY_ROWS")


# --- IN-IMP-03: malware scan check behind a switch ---

def test_in_imp_03_switch_off_reads_without_a_scan(ledger: FakeLedger) -> None:
    """IN-IMP-03 malware scan switch: off, the file is read without waiting for a scan."""
    assert start()[1]["status"] == "PREVIEW_READY"


def test_in_imp_03_switch_on_waits_for_the_scan_then_previews(ledger: FakeLedger, monkeypatch: pytest.MonkeyPatch) -> None:
    """IN-IMP-03 malware scan switch: on, an unscanned file is 'still checking'; once clean, it previews."""
    monkeypatch.setenv("MALWARE_SCAN_REQUIRED", "true")
    status, body, headers = start()
    assert status == 409 and body["code"] == "SCAN_PENDING" and headers.get("retry-after") == "2"
    put_file(CHASE_CARD_CSV, scan="NO_THREATS_FOUND")
    status, body, _ = call("POST", BASE, {"statementId": STATEMENT})
    assert status == 200 and body["status"] == "PREVIEW_READY"


def test_in_imp_03_switch_on_threat_fails_without_reading(ledger: FakeLedger, monkeypatch: pytest.MonkeyPatch) -> None:
    """IN-IMP-03 malware scan switch: a file that fails the scan ends with MALWARE_SCAN_FAILED and is never read."""
    monkeypatch.setenv("MALWARE_SCAN_REQUIRED", "true")
    _, body, _ = start(b"\x00 not even a csv", scan="THREATS_FOUND")
    assert (body["status"], body["reason"]) == ("FAILED", "MALWARE_SCAN_FAILED")
    assert ledger.calls("failure") == [{"reasonCode": "MALWARE_SCAN_FAILED"}]


# --- IN-IMP-04: preview ---

def test_in_imp_04_preview_shows_rows_direction_type_period_and_layout(ledger: FakeLedger) -> None:
    """IN-IMP-04 preview: rows with direction and type, the period, the layout and its source."""
    _, body, _ = start()
    rows = rows_by_description(body)
    assert (rows["STARBUCKS #12345"]["direction"], rows["STARBUCKS #12345"]["type"]) == ("DEBIT", "EXPENSE")
    assert rows["Payment Thank You-Mobile"]["type"] == "TRANSFER"
    assert body["period"] == {"earliest": "2026-01-03", "latest": "2026-02-02"}
    assert body["profileSource"] == "INFERRED" and "signConvention" in body["unconfirmedFields"]
    assert {"name": "Memo", "field": None} in body["headers"]


def test_in_imp_04_flipping_the_sign_reverses_every_direction(ledger: FakeLedger) -> None:
    """IN-IMP-04 preview: a new layout gives a new preview from the same file."""
    _, body, _ = start()
    flipped = dict(body["profile"], signConvention="EXPENSE_POSITIVE")
    status, again, _ = call("POST", path("/preview"), {"profile": flipped})
    assert status == 200
    before = {r["rowNumber"]: r["direction"] for r in body["rows"]}
    assert all(before[r["rowNumber"]] != r["direction"] for r in again["rows"])


def test_in_imp_04_choosing_another_sheet(ledger: FakeLedger) -> None:
    """IN-IMP-04 preview: choosing another sheet previews that sheet."""
    ledger.statements[STATEMENT] = statement(sourceFormat="XLSX", s3Key=f"statements/{STATEMENT}.xlsx")
    wb = Workbook()
    wb.active.title = "Summary"
    wb.active.append(["Account", "Balance"])
    wb.active.append(["Card", 100])
    ws = wb.create_sheet("Transactions")
    for line in CHASE_CARD_CSV.strip().split("\n"):
        ws.append(line.split(","))
    out = io.BytesIO()
    wb.save(out)
    _, body, _ = start(out.getvalue(), key=f"statements/{STATEMENT}.xlsx")
    assert body["sheet"] == "Summary" and body["sheets"] == ["Summary", "Transactions"]
    _, again, _ = call("POST", path("/preview"), {"sheet": "Transactions"})
    assert again["sheet"] == "Transactions" and again["counts"]["read"] == 5


def test_in_imp_04_incomplete_layout_shows_problems_and_no_rows(ledger: FakeLedger) -> None:
    """IN-IMP-04 preview: a layout missing the date or amount previews with those fields and no rows."""
    _, body, _ = start("Posted,Text,Value\n01/15/2026,A,-1.00\n")
    assert body["status"] == "PREVIEW_READY" and body["rows"] == []
    assert "columns.date" in body["problems"]


def test_in_imp_04_nothing_readable_keeps_the_import_open(ledger: FakeLedger) -> None:
    """IN-IMP-04 preview: no readable row with the chosen layout keeps the import open with 0 rows read."""
    _, body, _ = start()
    broken = dict(body["profile"], dateFormat="YMD")
    _, again, _ = call("POST", path("/preview"), {"profile": broken})
    assert again["status"] == "PREVIEW_READY" and again["counts"]["read"] == 0 and again["counts"]["unreadable"] == 5


def test_in_imp_04_no_header_row_ends_the_import(ledger: FakeLedger) -> None:
    """IN-IMP-04 preview: a file with no header row or no transactions ends with INVALID_CSV_FORMAT."""
    _, body, _ = start("Date,Description,Amount\n")
    assert (body["status"], body["reason"]) == ("FAILED", "INVALID_CSV_FORMAT")


# --- IN-IMP-05: rows already in the Ledger ---

def test_in_imp_05_rows_the_ledger_has_are_marked_and_counted(ledger: FakeLedger) -> None:
    """IN-IMP-05 already in the Ledger: matched rows are marked and counted."""
    ledger.existing = [{"id": "t1", "date": "2026-01-03", "amount": "5.75", "direction": "DEBIT", "merchantKey": "STARBUCKS"}]
    _, body, _ = start()
    assert body["counts"]["alreadyImported"] == 1 and body["overlapCheck"] == "OK"
    assert rows_by_description(body)["STARBUCKS #12345"]["alreadyImported"] is True
    sent = ledger.calls("overlap")[0]
    assert sent["accountId"] == ACCOUNT and len(sent["rows"]) == 5


def test_in_imp_05_overlap_check_failure_needs_import_anyway(ledger: FakeLedger) -> None:
    """IN-IMP-05 already in the Ledger: when the check fails, confirming needs 'Import anyway'."""
    ledger.fail("overlap", 500)
    _, body, _ = start()
    assert body["overlapCheck"] == "FAILED" and body["counts"]["alreadyImported"] == 0
    status, refused, _ = call("POST", path("/confirm"), {"profile": body["profile"]})
    assert status == 409 and refused["code"] == "OVERLAP_NOT_CHECKED"
    status, done, _ = call("POST", path("/confirm"), {"profile": body["profile"], "importAnyway": True})
    assert status == 200 and done["status"] == "COMPLETED"


# --- IN-IMP-06: confirm and deliver ---

def test_in_imp_06_confirm_sets_the_period_and_sends_one_package(ledger: FakeLedger) -> None:
    """IN-IMP-06 confirm and deliver: the period is set and every row goes to the Ledger in one package."""
    _, body, _ = start()
    status, done, _ = call("POST", path("/confirm"), {"profile": body["profile"]})
    assert status == 200 and done["status"] == "COMPLETED"
    assert done["result"] == {"inserted": 5, "skippedAlreadyImported": 0, "skippedPending": 0, "skippedUnreadable": 0, "failedRows": 0}
    assert ledger.calls("period") == [{"openingDate": "2026-01-03", "closingDate": "2026-02-02"}]
    [package] = ledger.calls("bulk")
    assert package["statementId"] == STATEMENT and package["packageId"] == STATEMENT and len(package["transactions"]) == 5


def test_in_imp_06_confirming_twice_sends_one_package(ledger: FakeLedger) -> None:
    """IN-IMP-06 confirm and deliver: confirming twice answers the same and sends one package."""
    _, body, _ = start()
    first = call("POST", path("/confirm"), {"profile": body["profile"]})[1]
    second = call("POST", path("/confirm"), {"profile": body["profile"]})[1]
    assert second["result"] == first["result"] and len(ledger.calls("bulk")) == 1


def test_in_imp_06_already_imported_rows_are_skipped_unless_put_back(ledger: FakeLedger) -> None:
    """IN-IMP-06 confirm and deliver: rows already in the Ledger are skipped unless the user puts them back."""
    ledger.existing = [{"id": "t1", "date": "2026-01-03", "amount": "5.75", "direction": "DEBIT", "merchantKey": "STARBUCKS"}]
    _, body, _ = start()
    _, done, _ = call("POST", path("/confirm"), {"profile": body["profile"]})
    assert done["result"]["inserted"] == 4 and done["result"]["skippedAlreadyImported"] == 1


def test_in_imp_06_put_back_and_excluded_rows(ledger: FakeLedger) -> None:
    """IN-IMP-06 confirm and deliver: included rows go back in; excluded rows stay out."""
    ledger.existing = [{"id": "t1", "date": "2026-01-03", "amount": "5.75", "direction": "DEBIT", "merchantKey": "STARBUCKS"}]
    _, body, _ = start()
    rows = rows_by_description(body)
    _, done, _ = call("POST", path("/confirm"), {"profile": body["profile"],
                                                "includedRows": [rows["STARBUCKS #12345"]["rowNumber"]],
                                                "excludedRows": [rows["NETFLIX.COM"]["rowNumber"]]})
    assert done["result"]["inserted"] == 4
    merchants = [t["merchant"] for t in ledger.calls("bulk")[0]["transactions"]]
    assert "starbucks" in merchants and "netflix.com" not in merchants


def test_in_imp_06_ledger_rejected_rows_are_reported(ledger: FakeLedger) -> None:
    """IN-IMP-06 confirm and deliver: rows the Ledger rejects are reported; the import still completes."""
    ledger.bulk_failed_rows = 3
    _, body, _ = start()
    _, done, _ = call("POST", path("/confirm"), {"profile": body["profile"]})
    assert done["status"] == "COMPLETED" and done["result"]["failedRows"] == 3 and done["result"]["inserted"] == 2


def test_in_imp_06_invalid_profile_lists_fields_and_keeps_the_import_open(ledger: FakeLedger) -> None:
    """IN-IMP-06 confirm and deliver: an invalid layout is refused with the fields to fix."""
    _, body, _ = start()
    bad = dict(body["profile"], columns=dict(body["profile"]["columns"], amount=None))
    status, refused, _ = call("POST", path("/confirm"), {"profile": bad})
    assert status == 422 and refused["code"] == "INVALID_PROFILE" and "columns.amount" in refused["fields"]
    assert call("GET", path())[1]["status"] == "PREVIEW_READY" and not ledger.calls("bulk")


def test_in_imp_06_no_rows_left_is_refused(ledger: FakeLedger) -> None:
    """IN-IMP-06 confirm and deliver: nothing left after exclusions is refused; the import stays open."""
    _, body, _ = start()
    status, refused, _ = call("POST", path("/confirm"), {"profile": body["profile"], "excludedRows": [r["rowNumber"] for r in body["rows"]]})
    assert status == 422 and refused["code"] == "NO_ROWS_SELECTED"
    assert call("GET", path())[1]["status"] == "PREVIEW_READY"


def test_in_imp_06_ledger_down_fails_the_import_and_tells_the_ledger(ledger: FakeLedger) -> None:
    """IN-IMP-06 confirm and deliver: the Ledger refusing the package after 4 tries fails the import."""
    _, body, _ = start()
    ledger.fail("bulk", 503, 503, 503, 503)
    _, done, _ = call("POST", path("/confirm"), {"profile": body["profile"]})
    assert (done["status"], done["reason"]) == ("FAILED", "LEDGER_PUSH_FAILED")
    assert ledger.calls("failure") == [{"reasonCode": "LEDGER_PUSH_FAILED"}]


# --- IN-IMP-08: cancel ---

def test_in_imp_08_cancel_ends_the_import_and_tells_the_ledger(ledger: FakeLedger) -> None:
    """IN-IMP-08 cancel and expiry: cancelling ends the import as IMPORT_CANCELLED; the Ledger is told."""
    start()
    assert call("POST", path("/cancel"))[0] == 204
    _, body, _ = call("GET", path())
    assert (body["status"], body["reason"]) == ("CANCELLED", "IMPORT_CANCELLED")
    assert ledger.calls("failure") == [{"reasonCode": "IMPORT_CANCELLED"}]


def test_in_imp_08_cancelling_an_ended_import_changes_nothing(ledger: FakeLedger) -> None:
    """IN-IMP-08 cancel and expiry: cancelling an import that ended changes nothing."""
    _, body, _ = start()
    call("POST", path("/confirm"), {"profile": body["profile"]})
    assert call("POST", path("/cancel"))[0] == 204
    assert call("GET", path())[1]["status"] == "COMPLETED" and not ledger.calls("failure")


def test_in_imp_08_cancelling_while_importing_is_refused(ledger: FakeLedger) -> None:
    """IN-IMP-08 cancel and expiry: cancelling while rows are being sent is refused."""
    start()
    boto3.resource("dynamodb").Table(IMPORTS_TABLE).update_item(
        Key={"importId": STATEMENT}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "IMPORTING"})
    status, body, _ = call("POST", path("/cancel"))
    assert status == 409 and body["code"] == "IMPORT_IMPORTING"


# --- IN-IMP-09: failures as reason codes ---

def test_in_imp_09_unexpected_error_is_pipeline_error_without_its_text(ledger: FakeLedger) -> None:
    """IN-IMP-09 reason codes: an unexpected error ends with PIPELINE_ERROR, never its text (invariant: no exception text)."""
    ledger.statements[STATEMENT] = statement(s3Key="statements/missing-bucket-key.csv")
    boto3.client("s3").delete_bucket(Bucket=BUCKET)
    status, body, _ = call("POST", BASE, {"statementId": STATEMENT})
    assert body["code"] in ("PIPELINE_ERROR",) and status == 503
    assert "Bucket" not in body["detail"] and "NoSuchBucket" not in str(body)


def test_in_imp_09_ledger_failure_notice_failing_still_ends_the_import(ledger: FakeLedger, caplog: pytest.LogCaptureFixture) -> None:
    """IN-IMP-09 reason codes: when the Ledger can't be told after 4 tries, the import still ends and it is logged."""
    ledger.fail("failure", 503, 503, 503, 503)
    with caplog.at_level(logging.WARNING):
        _, body, _ = start(b"x" * (25 * 1024 * 1024 + 1))
    assert body["status"] == "FAILED"
    assert any("LEDGER_FAILURE_NOTICE_FAILED" in r.getMessage() for r in caplog.records)


# --- IN-IMP-10: identity ---

def test_in_imp_10_no_verified_user_is_401(ledger: FakeLedger) -> None:
    """IN-IMP-10 identity: without the authorizer's user, nothing runs (invariant 2)."""
    status, body, _ = call("POST", BASE, {"statementId": STATEMENT}, user=None)
    assert status == 401 and not ledger.requests


def test_in_imp_10_ledger_calls_carry_the_verified_user_and_no_ids_in_bodies(ledger: FakeLedger) -> None:
    """IN-IMP-10 identity: Ledger calls carry the verified user; the package carries no user or account (invariant 3)."""
    _, body, _ = start()
    call("POST", path("/confirm"), {"profile": body["profile"]})
    assert {h.get("x-internal-user-id") for h in ledger.headers_of("bulk") + ledger.headers_of("owner")} == {USER}
    package = ledger.calls("bulk")[0]
    assert "userId" not in package and "accountId" not in package
    assert all("userId" not in t and "accountId" not in t for t in package["transactions"])


# --- IN-IMP-11: logs ---

def test_in_imp_11_no_statement_content_in_logs(ledger: FakeLedger, caplog: pytest.LogCaptureFixture) -> None:
    """IN-IMP-11 logs: a full import logs each step and never a merchant name or an amount."""
    with caplog.at_level(logging.INFO):
        _, body, _ = start()
        call("POST", path("/confirm"), {"profile": body["profile"]})
    text = "\n".join(r.getMessage() + " " + str(r.__dict__) for r in caplog.records)
    for secret in ("STARBUCKS", "starbucks", "82.10", "WHOLEFDS", "NETFLIX"):
        assert secret not in text
    steps = {getattr(r, "step", None) for r in caplog.records}
    assert {"start", "preview", "confirm", "push"} <= steps
