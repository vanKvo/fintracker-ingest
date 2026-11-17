"""Transfers between the household's own accounts, by last four digits (IN-FMT-12, Appendix E).

A masked account number in the description, not a keyword, is the signal: Capital One starts every
incoming bank transfer with "Deposit from", paychecks included.

__author__ = "Van Vo"
"""

from __future__ import annotations

import re
from typing import Literal

from .schemas import ImportContext

_MASKED = re.compile(r"(?:[X*]{2,}|\.{3})(\d{4})(?!\d)|\bending in (\d{4})(?!\d)", re.IGNORECASE)

OwnAccountMatch = Literal["NONE", "ONE", "UNCLEAR"]


def masked_last_four(description: str) -> str | None:
    match = _MASKED.search(description)
    return (match.group(1) or match.group(2)) if match else None


def match_own_account(description: str, ctx: ImportContext) -> OwnAccountMatch:
    """ONE: exactly one other tracked account has these last four. UNCLEAR: a masked number that
    matches none, several, or the household couldn't be read. NONE: no masked number."""
    digits = masked_last_four(description)
    if digits is None:
        return "NONE"
    if ctx.household is None:
        return "UNCLEAR"
    matches = [a for a in ctx.household if a.account_id != ctx.account_id and a.last_four == digits]
    return "ONE" if len(matches) == 1 else "UNCLEAR"
