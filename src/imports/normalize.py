"""The row sent to the Ledger (IN-IMP-07, IN-IMP Appendix C).

Only readable rows are sent, and only those the user didn't exclude. The fingerprint includes the
statement id and the file row number, so a retried push never inserts a row twice (LG-STMT-02) and
two identical purchases on the same day stay two rows.

__author__ = "Van Vo"
"""

from __future__ import annotations

import hashlib
import re

from ..categorizer.merchant_key import merchant_key
from ..categorizer.service import CodeSuggester
from ..profiles.schemas import AppliedFile, TypedRow

LedgerLine = dict[str, object]


def clean_merchant(raw: str) -> str:
    """Lowercase, reference numbers removed: "STARBUCKS #12345" → "starbucks" (carried from the legacy normalizer)."""
    cleaned = re.sub(r"[#\*]\d+", "", raw)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def row_fingerprint(statement_id: str, row_number: int, tx_date: str, merchant: str, amount: str, tx_type: str) -> str:
    return hashlib.sha256(f"{statement_id}|{row_number}|{tx_date}|{merchant}|{amount}|{tx_type}".encode()).hexdigest()


def _line(row: TypedRow, statement_id: str, suggester: CodeSuggester) -> LedgerLine:
    assert row.tx_date and row.amount is not None and row.direction and row.tx_type  # an OK row has all four
    merchant = clean_merchant(row.description)
    amount = f"{row.amount:.2f}"
    date = row.tx_date.isoformat()
    suggestion = suggester.suggest(row.description, row.bank_category)
    return {
        "date": date,
        "merchant": merchant,
        "amount": amount,
        "direction": str(row.direction),
        "type": str(row.tx_type),
        "categoryCode": suggestion.code,
        "sourceCategory": row.bank_category,
        "merchantKey": merchant_key(row.description),
        "reviewReason": row.review_reason,
        "rowFingerprint": row_fingerprint(statement_id, row.row_number, date, merchant, amount, str(row.tx_type)),
    }


def ledger_lines(applied: AppliedFile, statement_id: str, suggester: CodeSuggester, excluded_rows: frozenset[int] = frozenset()) -> list[LedgerLine]:
    return [
        _line(row, statement_id, suggester)
        for row in applied.rows
        if row.outcome == "OK" and row.row_number not in excluded_rows
    ]
