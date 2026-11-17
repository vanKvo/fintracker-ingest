"""The import workflow (IN-IMP-01 to IN-IMP-09): start, preview, confirm, cancel, expire.

Each user action is one request; the import record holds the state between them. The browser never
sends rows: every preview and the confirmation rebuild them from the stored file (principle 4).

__author__ = "Van Vo"
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..categorizer.merchant_key import merchant_key
from ..categorizer.patterns_data import suggester
from ..core import clock, config
from ..core.exceptions import (
    DependencyUnavailableError, FileNotUploadedError, ImportEndedError, ImportImportingError, ImportNotOpenError,
    IngestError, InvalidProfileError, NoRowsSelectedError, NotFoundError, OverlapNotCheckedError, ScanPendingError,
    UnsupportedAccountError, UnsupportedAccountTypeError, UnsupportedFileForImportError,
)
from ..core.observability import MetricUnit, logger, metric
from ..files import storage
from ..ledger import client as ledger
from ..profiles import codec, store
from ..profiles.columns import index_of
from ..profiles.schemas import AccountClass, AppliedFile, AmountMode, HouseholdAccount, ImportContext, Profile
from ..profiles.service import account_class_for, apply_profile, choose_proposal, validate_profile
from ..profiles.signature import header_signature
from ..readers.schemas import Table
from ..readers.service import read_file
from .models import ENDED_STATUSES, OPEN_STATUSES, ImportItem
from .normalize import ledger_lines
from .repository import create, get, update
from .schemas import HeaderUse, ImportResponse, PreviewRow

PREVIEW_ROWS = 20
UNREADABLE_ROWS = 50
_TTL_SECONDS = 7 * 24 * 3600
_IMPORT_FORMATS = ("CSV", "XLSX")


@dataclass
class Built:
    """The file read with a profile."""

    table: Table
    profile: Profile
    source: str
    unconfirmed: list[str]
    differences: dict[str, str]
    problems: list[str]
    applied: AppliedFile | None = None
    matches: dict[int, str] = field(default_factory=dict)
    overlap_ok: bool = True


@contextmanager
def _import_logging(import_id: str) -> Iterator[None]:
    logger.append_keys(import_id=import_id)
    try:
        yield
    finally:
        logger.remove_keys(["import_id"])


def _step(step: str, **counts: Any) -> None:
    logger.info("IMPORT_STEP", step=step, **counts)


# --- helpers ---

def _owned(user_id: str, import_id: str) -> ImportItem:
    record = get(import_id)
    if record is None or record.get("userId") != user_id:
        raise NotFoundError(log_message="no import for this user")
    return record


def _context(record: ImportItem) -> ImportContext:
    household = tuple(
        HouseholdAccount(a["accountId"], _class_or_none(a.get("accountType")), a.get("lastFour"), a.get("bankId"))
        for a in record.get("household", [])
    ) if "household" in record else None
    return ImportContext(bank_id=record["bankId"], account_class=AccountClass(record["accountClass"]),
                         account_id=record["accountId"], household=household, today=clock.now().date())


def _class_or_none(account_type: str | None) -> AccountClass | None:
    try:
        return account_class_for(account_type or "")
    except UnsupportedAccountTypeError:
        return None


def _stored_baselines(bank_id: str, account_class: AccountClass) -> list[store.StoredBaseline]:
    try:
        return store.list_baselines(bank_id, account_class)
    except Exception:  # IN-FMT-02: the proposal falls back to a guess; the preview still opens
        logger.warning("PROFILE_READ_FAILED")
        return []


def _user_profile(user_id: str, bank_id: str, account_class: AccountClass, signature: str) -> Profile | None:
    try:
        return store.get_user_profile(user_id, bank_id, account_class, signature)
    except Exception:
        logger.warning("PROFILE_READ_FAILED")
        return None


async def _overlap(record: ImportItem, applied: AppliedFile) -> tuple[dict[int, str], bool]:
    rows = [{"rowNumber": r.row_number, "date": r.tx_date.isoformat(), "amount": f"{r.amount:.2f}",
             "direction": str(r.direction), "merchantKey": merchant_key(r.description)}
            for r in applied.rows if r.outcome == "OK" and r.tx_date and r.amount is not None]
    if not rows:
        return {}, True
    try:
        return await ledger.overlap_check(record["userId"], record["accountId"], rows), True
    except (ledger.InternalCallError, ValidationError):
        logger.warning("OVERLAP_CHECK_FAILED")
        return {}, False


async def _build(record: ImportItem, data: bytes, profile: Profile | None, sheet: str | None) -> Built:
    """Raises IngestError when the file itself can't be read (the import ends)."""
    account_class = AccountClass(record["accountClass"])
    stored = _stored_baselines(record["bankId"], account_class)
    table = read_file(record["s3Key"], data, header_row=profile.header_row if profile else None, sheet=sheet,
                      known_signatures=frozenset(b.signature for b in stored),
                      max_bytes=config.max_file_bytes(), max_rows=config.max_data_rows())
    signature = header_signature(table.headers)

    if profile is None:
        try:
            store.note_layout(record["bankId"], account_class, signature, stored)
        except Exception:
            logger.warning("FORMAT_ALARM_FAILED")
        proposal = choose_proposal(table, _user_profile(record["userId"], record["bankId"], account_class, signature),
                                   store.baselines_for_proposal(stored))
        unconfirmed = set(proposal.unconfirmed)
        if proposal.source in ("BASELINE", "NEAREST_BASELINE"):
            verified = next((b.verified for b in stored if b.profile.columns == proposal.profile.columns
                             or b.signature == signature), False)
            if not verified:
                unconfirmed = {"dateFormat"} | ({"signConvention"} if proposal.profile.amount_mode == AmountMode.SIGNED else set())
        built = Built(table, proposal.profile, proposal.source, sorted(unconfirmed), dict(proposal.baseline_differences), [])
    else:
        built = Built(table, profile, record.get("profileSource", "INFERRED"),
                      list(record.get("unconfirmed", [])) if profile == _stored_profile(record) else [],
                      dict(record.get("differences", {})) if profile == _stored_profile(record) else {}, [])

    built.problems = validate_profile(built.profile, table.headers)
    if not built.problems:
        built.applied = apply_profile(table, built.profile, _context(record))
        built.matches, built.overlap_ok = await _overlap(record, built.applied)
    return built


def _stored_profile(record: ImportItem) -> Profile | None:
    return codec.from_dict(record["profile"]) if record.get("profile") else None


def _response(record: ImportItem, built: Built | None = None) -> ImportResponse:
    base = ImportResponse(
        importId=record["importId"], status=record["status"], reason=record.get("reason"), fileType=record.get("fileType"),
        sheet=record.get("sheet"), profile=record.get("profile"), profileSource=record.get("profileSource"),
        unconfirmedFields=list(record.get("unconfirmed", [])), baselineDifferences=dict(record.get("differences", {})),
        result=record.get("result"),
    )
    if built is None:
        return base
    fields_by_header = {header: name for name, header in vars(built.profile.columns).items() if header}
    base.sheet, base.sheets = built.table.sheet_name, built.table.sheet_names
    base.profile, base.profileSource = codec.to_dict(built.profile), built.source
    base.unconfirmedFields, base.baselineDifferences, base.problems = built.unconfirmed, built.differences, built.problems
    base.headers = [HeaderUse(name=h, field=next((f for hh, f in fields_by_header.items()
                                                  if index_of([h], hh) is not None), None)) for h in built.table.headers]
    base.overlapCheck = "OK" if built.overlap_ok else "FAILED"
    if built.applied is None:
        base.counts = {"read": 0, "unreadable": 0, "pending": 0, "alreadyImported": 0}
        return base
    ok = [r for r in built.applied.rows if r.outcome == "OK"]
    dates = sorted(r.tx_date.isoformat() for r in ok if r.tx_date)
    base.period = {"earliest": dates[0], "latest": dates[-1]} if dates else None
    base.counts = {**built.applied.counts, "alreadyImported": sum(1 for r in ok if r.row_number in built.matches)}
    base.rows = [PreviewRow(rowNumber=r.row_number, date=r.tx_date.isoformat() if r.tx_date else "", description=r.description,
                            amount=f"{r.amount:.2f}", direction=str(r.direction), type=str(r.tx_type),
                            reviewReason=r.review_reason, alreadyImported=r.row_number in built.matches)
                 for r in ok[:PREVIEW_ROWS]]
    base.unreadableRows = [r.row_number for r in built.applied.rows if r.outcome == "UNREADABLE"][:UNREADABLE_ROWS]
    return base


async def end_import(record: ImportItem, status: str, reason: str) -> ImportResponse:
    """Ends an open or stuck import and tells the Ledger (IN-IMP-09). A second ending changes nothing."""
    now = clock.now()
    changes = {"status": status, "reason": reason, "endedAt": clock.iso(now), "updatedAt": clock.iso(now),
               "ttl": int(now.timestamp()) + _TTL_SECONDS}
    if update(record["importId"], changes, only_if_status=(*OPEN_STATUSES, "IMPORTING")):
        record = {**record, **changes}  # type: ignore[typeddict-item]
        await ledger.report_failure(record["importId"], record["userId"], reason)
        metric("ImportsFailed", reason=reason)
        _step("end", status=status, reason=reason)
    else:
        record = get(record["importId"]) or record
    return _response(record)


async def _preview(record: ImportItem, data: bytes, profile: Profile | None, sheet: str | None) -> ImportResponse:
    started = time.monotonic()
    try:
        built = await _build(record, data, profile, sheet)
    except IngestError as error:
        return await end_import(record, "FAILED", error.reason)
    now = clock.iso(clock.now())
    changes: dict[str, Any] = {
        "status": "PREVIEW_READY", "profile": codec.to_dict(built.profile), "profileSource": built.source,
        "unconfirmed": built.unconfirmed, "differences": built.differences, "signature": header_signature(built.table.headers),
        "headers": built.table.headers, "overlapCheck": "OK" if built.overlap_ok else "FAILED",
        "previewedAt": now, "updatedAt": now,
    }
    if built.table.sheet_name:
        changes["sheet"] = built.table.sheet_name
    if profile is None:
        changes["proposedProfile"] = codec.to_dict(built.profile)
    if not update(record["importId"], changes, only_if_status=OPEN_STATUSES):
        raise ImportNotOpenError(log_message="import ended during preview")
    record = {**record, **changes}  # type: ignore[typeddict-item]
    counts = built.applied.counts if built.applied else {}
    _step("preview", **counts)
    metric("PreviewMs", (time.monotonic() - started) * 1000, MetricUnit.Milliseconds)
    return _response(record, built)


def _file(record: ImportItem) -> bytes:
    data = storage.get_file(record["s3Key"])
    if data is None:
        raise DependencyUnavailableError(log_message="stored file missing")
    return data


# --- IN-IMP-01, IN-IMP-03: start ---

async def start_import(user_id: str, statement_id: str) -> ImportResponse:
    with _import_logging(statement_id):
        try:
            owner = await ledger.get_owner(statement_id, user_id)
        except (ledger.InternalCallError, ValidationError):
            raise DependencyUnavailableError(log_message="owner lookup failed") from None
        if owner is None or owner.userId != user_id:
            raise NotFoundError(log_message="statement not owned by caller")

        record = get(statement_id)
        if record is not None:
            if record.get("userId") != user_id:
                raise NotFoundError(log_message="import of another user")
            if record["status"] in ENDED_STATUSES:
                raise ImportEndedError(reason=record.get("reason"), log_message="import already ended")
            if record["status"] == "IMPORTING":
                raise ImportImportingError(log_message="import in progress")
            if record["status"] == "SCAN_PENDING":
                return await _after_scan(record)
            return _response(record, await _build(record, _file(record), _stored_profile(record), record.get("sheet")))

        if owner.status != "PROCESSING":
            raise ImportEndedError(log_message="statement not waiting")
        if owner.sourceFormat not in _IMPORT_FORMATS:
            raise UnsupportedFileForImportError(log_message="not a CSV or Excel statement")
        try:
            account_class = account_class_for(owner.accountType)
        except UnsupportedAccountTypeError:
            raise UnsupportedAccountError(log_message="cash account") from None
        data = storage.get_file(owner.s3Key)
        if data is None:
            raise FileNotUploadedError(log_message="file not in the bucket yet")

        now = clock.iso(clock.now())
        new: ImportItem = {
            "importId": statement_id, "userId": user_id, "accountId": owner.accountId, "accountClass": str(account_class),
            "bankId": owner.bankId or "other", "s3Key": owner.s3Key, "fileType": owner.sourceFormat,
            "household": [a.model_dump() for a in owner.householdAccounts],
            "status": "SCAN_PENDING" if config.malware_scan_required() else "PREVIEW_READY",
            "createdAt": now, "updatedAt": now,
        }
        if not create(new):
            return await start_import(user_id, statement_id)
        metric("ImportsStarted")
        _step("start", file_type=owner.sourceFormat)
        return await _after_scan(new, data)


async def _after_scan(record: ImportItem, data: bytes | None = None) -> ImportResponse:
    if config.malware_scan_required():
        scan = storage.scan_status(record["s3Key"])
        if scan is None:
            raise ScanPendingError(log_message="scan pending")
        if scan != storage.CLEAN:
            return await end_import(record, "FAILED", "MALWARE_SCAN_FAILED")
    return await _preview(record, data if data is not None else _file(record), None, None)


# --- IN-IMP-01 (reopen), IN-IMP-04: preview ---

async def get_import(user_id: str, import_id: str) -> ImportResponse:
    with _import_logging(import_id):
        record = _owned(user_id, import_id)
        if record["status"] != "PREVIEW_READY":
            return _response(record)
        try:
            built = await _build(record, _file(record), _stored_profile(record), record.get("sheet"))
        except IngestError as error:
            return await end_import(record, "FAILED", error.reason)
        return _response(record, built)


async def preview(user_id: str, import_id: str, profile_data: dict[str, Any] | None, sheet: str | None) -> ImportResponse:
    with _import_logging(import_id):
        record = _owned(user_id, import_id)
        if record["status"] != "PREVIEW_READY":
            raise ImportNotOpenError(log_message="preview of a closed import")
        profile = codec.from_dict(profile_data) if profile_data is not None else None
        if profile is None and sheet is None:
            profile = _stored_profile(record)
        return await _preview(record, _file(record), profile, sheet or (record.get("sheet") if profile is not None else None))


# --- IN-IMP-05, IN-IMP-06: confirm ---

async def confirm(user_id: str, import_id: str, profile_data: dict[str, Any], excluded_rows: list[int],
                  included_rows: list[int], import_anyway: bool) -> ImportResponse:
    with _import_logging(import_id):
        started = time.monotonic()
        record = _owned(user_id, import_id)
        if record["status"] == "COMPLETED":
            return _response(record)
        if record["status"] != "PREVIEW_READY":
            raise ImportNotOpenError(log_message="confirm of a closed import")
        profile = codec.from_dict(profile_data)
        try:
            built = await _build(record, _file(record), profile, record.get("sheet"))
        except IngestError as error:
            return await end_import(record, "FAILED", error.reason)
        if built.problems or built.applied is None:
            raise InvalidProfileError(fields=built.problems, log_message="confirm with an invalid profile")
        if (record.get("overlapCheck") == "FAILED" or not built.overlap_ok) and not import_anyway:
            raise OverlapNotCheckedError(log_message="overlap not checked")

        ok_numbers = {r.row_number for r in built.applied.rows if r.outcome == "OK"}
        already = (set(built.matches) & ok_numbers) - set(included_rows)
        lines = ledger_lines(built.applied, import_id, suggester(), excluded_rows=frozenset(set(excluded_rows) | already))
        if not lines:
            raise NoRowsSelectedError(log_message="nothing left to import")

        if not update(import_id, {"status": "IMPORTING", "updatedAt": clock.iso(clock.now())}, only_if_status=("PREVIEW_READY",)):
            current = get(import_id)
            if current and current["status"] == "COMPLETED":
                return _response(current)
            raise ImportNotOpenError(log_message="confirm raced another request")
        _step("confirm", rows=len(lines))

        try:
            proposed = codec.from_dict(record["proposedProfile"]) if record.get("proposedProfile") else None
            store.save_confirmation(user_id, record["bankId"], AccountClass(record["accountClass"]),
                                    header_signature(built.table.headers), built.table.headers, built.profile, proposed)
        except Exception:  # IN-FMT-07: a lost vote never blocks an import
            logger.warning("PROFILE_SAVE_FAILED")

        dates = sorted(str(line["date"]) for line in lines)
        try:
            await ledger.set_period(import_id, user_id, dates[0], dates[-1])
        except ledger.InternalCallError:
            return await end_import(record, "FAILED", "PIPELINE_ERROR")
        try:
            answer = await ledger.push_bulk(user_id, {"packageId": import_id, "statementId": import_id, "transactions": lines})
        except ledger.InternalCallError:
            return await end_import(record, "FAILED", "LEDGER_PUSH_FAILED")

        counts = built.applied.counts
        result = {"inserted": answer.insertedCount + answer.skippedDuplicateCount, "skippedAlreadyImported": len(already),
                  "skippedPending": counts["pending"], "skippedUnreadable": counts["unreadable"], "failedRows": len(answer.failedRows)}
        now = clock.now()
        changes = {"status": "COMPLETED", "result": result, "profile": codec.to_dict(built.profile), "endedAt": clock.iso(now),
                   "updatedAt": clock.iso(now), "ttl": int(now.timestamp()) + _TTL_SECONDS}
        update(import_id, changes)
        _step("push", inserted=result["inserted"], failed=result["failedRows"])
        metric("ImportsCompleted")
        metric("RowsImported", result["inserted"])
        metric("RowsSkippedAlreadyImported", result["skippedAlreadyImported"])
        metric("ConfirmMs", (time.monotonic() - started) * 1000, MetricUnit.Milliseconds)
        return _response({**record, **changes})  # type: ignore[typeddict-item]


# --- IN-IMP-08: cancel ---

async def cancel(user_id: str, import_id: str) -> None:
    with _import_logging(import_id):
        record = _owned(user_id, import_id)
        if record["status"] == "IMPORTING":
            raise ImportImportingError(log_message="cancel while importing")
        if record["status"] in OPEN_STATUSES:
            await end_import(record, "CANCELLED", "IMPORT_CANCELLED")
