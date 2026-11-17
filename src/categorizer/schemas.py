"""Categorizer feature schemas.

__author__ = "Van Vo"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

# Which step suggested the code (logged, never sent to the Ledger).
SuggestionSource = Literal["BANK_LABEL", "MERCHANT_MAP", "NONE"]


@dataclass(frozen=True)
class CodeSuggestion:
    """A SYSTEM category code the pipeline suggests for a row, or None for no suggestion. The
    Ledger turns it into a category and applies the user's own rules and categories first
    (XS-DPCAT-07)."""

    code: Optional[str]
    source: SuggestionSource
