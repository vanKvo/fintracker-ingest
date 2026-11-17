"""Inferring a profile for an unknown layout (IN-FMT-03, Appendix B).

__author__ = "Van Vo"
"""

from __future__ import annotations

from .parsing import parse_amount, parse_date
from .schemas import (
    DEFAULT_CREDIT_VALUES, DEFAULT_DEBIT_VALUES, AmountMode, Columns, DateFormat, InferredProfile, Profile, SignConvention,
)
from .signature import normalize_header
from ..readers.schemas import Table

SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": ("transaction date", "trans date", "date", "posting date", "post date", "posted date"),
    "description": ("description", "merchant", "payee", "name", "memo", "transaction description"),
    "amount": ("amount", "transaction amount", "amt"),
    "debit": ("debit", "debits", "withdrawal", "withdrawals", "amount debit", "money out"),
    "credit": ("credit", "credits", "deposit", "deposits", "amount credit", "money in"),
    "type": ("type", "transaction type"),
    "category": ("category",),
    "status": ("status",),
}
_LAST_RESORT_DESCRIPTION = "details"
_DATE_FORMATS = (DateFormat.ISO, DateFormat.MDY, DateFormat.DMY, DateFormat.YMD)


def _column_values(table: Table, index: int) -> list[str]:
    return [row[index] for row in table.rows if row[index].strip()]


def _is_indicator(values: list[str]) -> bool:
    allowed = {v.lower() for v in DEFAULT_DEBIT_VALUES + DEFAULT_CREDIT_VALUES}
    return bool(values) and all(v.strip().lower() in allowed for v in values)


def _date_format(values: list[str]) -> DateFormat:
    for fmt in _DATE_FORMATS:  # MDY before DMY: US banks
        if values and all(parse_date(v, fmt) is not None for v in values):
            return fmt
    return DateFormat.MDY


def infer_profile(table: Table) -> InferredProfile:
    normalized = [normalize_header(h) for h in table.headers]
    used: set[int] = set()

    def take(field: str) -> str | None:
        for synonym in SYNONYMS[field]:
            for i, header in enumerate(normalized):
                if header == synonym and i not in used:
                    used.add(i)
                    return table.headers[i]
        return None

    found: dict[str, str | None] = {"date": take("date"), "description": take("description")}
    if found["description"] is None and _LAST_RESORT_DESCRIPTION in normalized:
        i = normalized.index(_LAST_RESORT_DESCRIPTION)
        if i not in used:
            used.add(i)
            found["description"] = table.headers[i]

    # A column holding only debit/credit words is the direction, whatever its header says.
    direction = None
    for i in range(len(table.headers)):
        if i not in used and _is_indicator(_column_values(table, i)):
            used.add(i)
            direction = table.headers[i]
            break

    for field in ("amount", "debit", "credit", "type", "category", "status"):
        found[field] = take(field)

    amount_index = table.headers.index(found["amount"]) if found["amount"] else None
    amounts = [a for a in (parse_amount(v) for v in _column_values(table, amount_index))] if amount_index is not None else []
    readable = [a for a in amounts if a is not None]

    sign: SignConvention | None = None
    if direction and found["amount"] and all(a >= 0 for a in readable):
        mode = AmountMode.INDICATOR
    elif found["debit"] and found["credit"] and not found["amount"]:
        mode = AmountMode.SPLIT
    else:
        mode = AmountMode.SIGNED
        negatives = sum(1 for a in readable if a < 0)
        sign = SignConvention.EXPENSE_NEGATIVE if negatives * 2 > len(readable) else SignConvention.EXPENSE_POSITIVE

    date_values = _column_values(table, table.headers.index(found["date"])) if found["date"] else []
    columns = Columns(
        date=found["date"], description=found["description"],
        amount=found["amount"] if mode != AmountMode.SPLIT else None,
        debit=found["debit"] if mode == AmountMode.SPLIT else None,
        credit=found["credit"] if mode == AmountMode.SPLIT else None,
        direction=direction if mode == AmountMode.INDICATOR else None,
        type=found["type"], category=found["category"], status=found["status"],
    )
    profile = Profile(columns=columns, amount_mode=mode, date_format=_date_format(date_values), sign_convention=sign)
    unconfirmed = {"columns", "amountMode", "dateFormat"} | ({"signConvention"} if sign else set())
    return InferredProfile(profile, frozenset(unconfirmed))
