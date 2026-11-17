"""Format profile types (IN-FMT Appendix A) and the typed rows a profile produces.

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Literal


class AmountMode(StrEnum):
    SIGNED = "SIGNED"        # one signed amount column
    SPLIT = "SPLIT"          # separate money-out and money-in columns
    INDICATOR = "INDICATOR"  # an unsigned amount plus a column saying debit or credit


class SignConvention(StrEnum):
    EXPENSE_NEGATIVE = "EXPENSE_NEGATIVE"
    EXPENSE_POSITIVE = "EXPENSE_POSITIVE"


class DateFormat(StrEnum):
    ISO = "ISO"
    MDY = "MDY"
    DMY = "DMY"
    YMD = "YMD"


class AccountClass(StrEnum):
    DEPOSIT = "DEPOSIT"  # checking and savings
    CREDIT = "CREDIT"    # credit cards


class Direction(StrEnum):
    DEBIT = "DEBIT"    # money out
    CREDIT = "CREDIT"  # money in


class TxType(StrEnum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    REFUND = "REFUND"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"


DEFAULT_DEBIT_VALUES = ("debit", "dr", "withdrawal")
DEFAULT_CREDIT_VALUES = ("credit", "cr", "deposit")
UNCLEAR_TYPE = "UNCLEAR_TYPE"


@dataclass(frozen=True)
class Columns:
    """Header names in the file. None = not mapped."""

    date: str | None = None
    description: str | None = None
    amount: str | None = None
    debit: str | None = None
    credit: str | None = None
    direction: str | None = None
    type: str | None = None
    category: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class Profile:
    columns: Columns
    amount_mode: AmountMode
    date_format: DateFormat
    sign_convention: SignConvention | None = None
    header_row: int | None = None
    debit_values: tuple[str, ...] = DEFAULT_DEBIT_VALUES
    credit_values: tuple[str, ...] = DEFAULT_CREDIT_VALUES
    pending_values: tuple[str, ...] = ()
    verified: bool = False


@dataclass(frozen=True)
class Baseline:
    signature: str
    profile: Profile


ProposalSource = Literal["USER", "BASELINE", "NEAREST_BASELINE", "INFERRED"]


@dataclass(frozen=True)
class InferredProfile:
    profile: Profile
    unconfirmed: frozenset[str]


@dataclass(frozen=True)
class Proposal:
    profile: Profile
    source: ProposalSource
    baseline_differences: dict[str, str] = field(default_factory=dict)  # field -> the baseline's value
    unconfirmed: frozenset[str] = frozenset()


@dataclass(frozen=True)
class HouseholdAccount:
    """Another account of the statement's owner (XS-IMP-05). last_four and bank_id may be unknown."""

    account_id: str
    account_class: AccountClass | None  # None for a CASH account
    last_four: str | None
    bank_id: str | None


@dataclass(frozen=True)
class ImportContext:
    bank_id: str
    account_class: AccountClass
    account_id: str
    household: tuple[HouseholdAccount, ...] | None  # None = the Ledger couldn't return them
    today: dt.date


RowOutcome = Literal["OK", "PENDING", "UNREADABLE"]


@dataclass(frozen=True)
class TypedRow:
    row_number: int
    outcome: RowOutcome
    description: str
    tx_date: dt.date | None = None
    amount: Decimal | None = None  # always positive; direction gives the sign (LG-TXT-03)
    direction: Direction | None = None
    tx_type: TxType | None = None
    review_reason: str | None = None
    bank_category: str | None = None


@dataclass(frozen=True)
class AppliedFile:
    rows: list[TypedRow]
    counts: dict[str, int]  # read, pending, unreadable
