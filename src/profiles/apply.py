"""Applying a profile to a table: one typed row per data row (IN-FMT-04, IN-FMT-05, IN-IMP-07).

A row that can't be read is kept as UNREADABLE and counted; one bad row never fails the file.

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from ..core.observability import logger
from ..readers.schemas import Table
from .columns import index_of
from .parsing import parse_amount, parse_date
from .schemas import UNCLEAR_TYPE, AmountMode, AppliedFile, Direction, ImportContext, Profile, SignConvention, TypedRow
from .type_rules import classify

_FUTURE_TOLERANCE = dt.timedelta(days=1)


def _cell(row: list[str], index: int | None) -> str:
    return row[index].strip() if index is not None else ""


def _signed(amount: Decimal, convention: SignConvention | None) -> Direction:
    if convention == SignConvention.EXPENSE_POSITIVE:
        return Direction.DEBIT if amount > 0 else Direction.CREDIT
    return Direction.DEBIT if amount < 0 else Direction.CREDIT


def _amount_and_direction(row: list[str], profile: Profile, idx: dict[str, int | None]) -> tuple[Decimal, Direction] | None:
    mode = profile.amount_mode
    if mode == AmountMode.SPLIT:
        debit, credit = parse_amount(_cell(row, idx["debit"])), parse_amount(_cell(row, idx["credit"]))
        present = [(v, d) for v, d in ((debit, Direction.DEBIT), (credit, Direction.CREDIT)) if v is not None and v != 0]
        if len(present) != 1:
            return None
        return abs(present[0][0]), present[0][1]

    amount = parse_amount(_cell(row, idx["amount"]))
    if amount is None or amount == 0:
        return None
    if mode == AmountMode.INDICATOR:
        word = _cell(row, idx["direction"]).lower()
        if word in {v.lower() for v in profile.debit_values}:
            return abs(amount), Direction.DEBIT
        if word in {v.lower() for v in profile.credit_values}:
            return abs(amount), Direction.CREDIT
        return None
    return abs(amount), _signed(amount, profile.sign_convention)


def apply_profile(table: Table, profile: Profile, ctx: ImportContext) -> AppliedFile:
    cols = profile.columns
    idx = {name: index_of(table.headers, getattr(cols, name)) for name in
           ("date", "description", "amount", "debit", "credit", "direction", "type", "category", "status")}
    pending = {v.strip().lower() for v in profile.pending_values}
    latest = ctx.today + _FUTURE_TOLERANCE
    logged_labels: set[str] = set()

    rows: list[TypedRow] = []
    for number, row in zip(table.source_row_numbers, table.rows):
        description = _cell(row, idx["description"])
        if pending and _cell(row, idx["status"]).lower() in pending:
            rows.append(TypedRow(number, "PENDING", description))
            continue

        tx_date = parse_date(_cell(row, idx["date"]), profile.date_format)
        money = _amount_and_direction(row, profile, idx)
        if tx_date is None or tx_date > latest or money is None:
            rows.append(TypedRow(number, "UNREADABLE", description))
            continue

        amount, direction = money
        decision = classify(description, _cell(row, idx["type"]) or None, direction, ctx)
        if decision.unknown_label and decision.unknown_label not in logged_labels:
            logged_labels.add(decision.unknown_label)
            # Labels are bank vocabulary, not user data; the description is never logged.
            logger.warning("UNKNOWN_TYPE_LABEL", extra={
                "event": "UNKNOWN_TYPE_LABEL", "bank_id": ctx.bank_id,
                "account_class": str(ctx.account_class), "label": decision.unknown_label,
            })
        rows.append(TypedRow(
            number, "OK", description, tx_date, amount, direction, decision.tx_type,
            UNCLEAR_TYPE if decision.flagged else None, _cell(row, idx["category"]) or None,
        ))

    counts = {
        "read": sum(r.outcome == "OK" for r in rows),
        "pending": sum(r.outcome == "PENDING" for r in rows),
        "unreadable": sum(r.outcome == "UNREADABLE" for r in rows),
    }
    return AppliedFile(rows, counts)
