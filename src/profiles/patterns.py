"""Description patterns for exports with no type label (IN-FMT-11, Appendix D).

A card payment is a transfer only when the household tracks a card at the bank the description
names; otherwise it may be the only record of spending on an untracked card, so it is an expense
flagged for review.

__author__ = "Van Vo"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .schemas import AccountClass, Direction, TxType

CARD_PAYMENT: Literal["CARD_PAYMENT"] = "CARD_PAYMENT"


@dataclass(frozen=True)
class DescriptionPattern:
    regex: re.Pattern[str]
    direction: Direction | None  # None = either
    result: TxType | Literal["CARD_PAYMENT"]
    flag: bool = False


def _p(pattern: str, direction: Direction | None, result: TxType | Literal["CARD_PAYMENT"], flag: bool = False) -> DescriptionPattern:
    return DescriptionPattern(re.compile(pattern, re.IGNORECASE), direction, result, flag)


_PEER = r"\bZELLE\b|\bVENMO\b|\bCASH APP\b"

_DEFAULTS: dict[AccountClass, tuple[DescriptionPattern, ...]] = {
    AccountClass.DEPOSIT: (
        _p(r"\bINTEREST (PAID|EARNED|PAYMENT)\b", Direction.CREDIT, TxType.INCOME),
        _p(r"\b(CRD|CARD) ?(EPAY|PMT|PAYMENT)\b|\bCREDIT CARD PAYMENT\b|\bAUTOPAY\b", Direction.DEBIT, CARD_PAYMENT),
        _p(r"\bMONEYLINE\b|\bBROKERAGE\b|\bFID BKG\b|\bSCHWAB\b|\bVANGUARD\b|\bROBINHOOD\b", None, TxType.TRANSFER, True),
        _p(_PEER, Direction.CREDIT, TxType.INCOME, True),
        _p(_PEER, Direction.DEBIT, TxType.EXPENSE, True),
        _p(r"\bTRANSFER\b|\bXFER\b", None, TxType.TRANSFER, True),
    ),
    AccountClass.CREDIT: (
        _p(r"\bPAYMENT\b.*\bTHANK YOU\b|\bAUTOPAY\b|\bONLINE PAYMENT\b", Direction.CREDIT, TxType.TRANSFER),
        _p(r"\bINTEREST CHARGE", Direction.DEBIT, TxType.EXPENSE),
    ),
}

_BANKS: dict[tuple[str, AccountClass], tuple[DescriptionPattern, ...]] = {}

ISSUER_WORDS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), bank) for p, bank in (
        (r"\bCHASE\b", "chase"),
        (r"\bCAPITAL ?ONE\b", "capital_one"),
        (r"\bDISCOVER\b", "discover"),
        (r"\bBANK OF AMERICA\b|\bBK OF AMER\b", "bank_of_america"),
        (r"\bWELLS FARGO\b", "wells_fargo"),
        (r"\bU\.?S\.? BANK\b", "us_bank"),
    )
)


def patterns_for(bank_id: str, account_class: AccountClass) -> tuple[DescriptionPattern, ...]:
    return _BANKS.get((bank_id, account_class), ()) + _DEFAULTS[account_class]


def issuer_of(description: str) -> str | None:
    return next((bank for regex, bank in ISSUER_WORDS if regex.search(description)), None)
