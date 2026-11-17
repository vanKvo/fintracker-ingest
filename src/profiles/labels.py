"""Bank type labels → Ledger type, per account class (IN-FMT-05, Appendix C).

A label means different things by account class: "Payment" on a card is the user paying the card
(TRANSFER); on checking it may be a card payment or a bill, so it is an EXPENSE flagged for review.

__author__ = "Van Vo"
"""

from __future__ import annotations

import re

from .schemas import AccountClass, TxType

LabelEntry = tuple[TxType, bool]  # type, flag for review

_DEFAULTS: dict[AccountClass, dict[str, LabelEntry]] = {
    AccountClass.CREDIT: {
        **{k: (TxType.EXPENSE, False) for k in ("sale", "purchase", "fee", "interest", "interest charged")},
        **{k: (TxType.REFUND, False) for k in ("return", "refund")},
        **{k: (TxType.TRANSFER, False) for k in ("payment", "payment thank you", "autopay")},
        "adjustment": (TxType.ADJUSTMENT, False),
        "cash advance": (TxType.TRANSFER, True),
    },
    AccountClass.DEPOSIT: {
        **{k: (TxType.EXPENSE, False) for k in ("debit", "withdrawal", "purchase", "fee", "check")},
        **{k: (TxType.INCOME, False) for k in ("deposit", "credit", "direct deposit", "interest")},
        **{k: (TxType.EXPENSE, True) for k in ("payment", "bill payment")},
        "transfer": (TxType.TRANSFER, True),
        "adjustment": (TxType.ADJUSTMENT, False),
    },
}

_BANKS: dict[tuple[str, AccountClass], dict[str, LabelEntry]] = {
    ("chase", AccountClass.DEPOSIT): {
        **{k: (TxType.EXPENSE, False) for k in ("debit_card", "ach_debit", "check_paid", "fee_transaction")},
        **{k: (TxType.INCOME, False) for k in ("ach_credit", "deposit", "quickpay_credit")},
        "acct_xfer": (TxType.TRANSFER, True),
        "loan_pmt": (TxType.EXPENSE, True),
    },
}


def normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip()).lower()


def lookup_label(bank_id: str, account_class: AccountClass, label: str) -> LabelEntry | None:
    """The bank's own entry first, then the default for the account class."""
    key = normalize_label(label)
    return _BANKS.get((bank_id, account_class), {}).get(key) or _DEFAULTS[account_class].get(key)
