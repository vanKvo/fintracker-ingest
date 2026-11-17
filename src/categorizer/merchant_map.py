"""MerchantCategoryMap — merchant text patterns to SYSTEM category codes.

Copied from the legacy Data pipeline (src/categorizer/merchant_map.py), matching logic unchanged.
The DynamoDB loader is not copied yet: it comes with the import API, which owns the table.

DP-LEDGER-CATEGORIES-06: PDF rows have no bank label, so the merchant text is matched against
patterns kept in a DynamoDB table (seeded by Terraform from infrastructure/seed/) instead of a
hard-coded regex list. Patterns name category codes, never UUIDs, so one seed works in every
environment. Ambiguous merchants (e.g. Target) are left out on purpose and stay uncategorized.

__author__ = "Van Vo"
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional


@dataclass(frozen=True)
class MerchantPattern:
    pattern: str
    match_type: str  # "regex" | "contains" | "exact"
    code: str
    priority: int  # lower number wins when several patterns match
    active: bool


def normalize_merchant_text(raw: str) -> str:
    """The seed's normalization: uppercase, collapse whitespace, keep punctuation."""
    return re.sub(r"\s+", " ", raw).strip().upper()


@lru_cache(maxsize=512)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _matches(pattern: MerchantPattern, text: str) -> bool:
    if pattern.match_type == "contains":
        return pattern.pattern in text
    if pattern.match_type == "exact":
        return pattern.pattern == text
    if pattern.match_type == "regex":
        return _compiled(pattern.pattern).search(text) is not None
    return False


def match_merchant_code(
    raw_merchant: str,
    patterns: Iterable[MerchantPattern],
    usable_codes: Optional[set[str]] = None,
) -> Optional[str]:
    """The code of the matching pattern with the lowest priority number, or None.

    Args:
        raw_merchant: Merchant text as it appears on the statement.
        patterns: The MerchantCategoryMap rows.
        usable_codes: Active SYSTEM category codes. A pattern whose code isn't one of them is
            treated as no match, so a retired code can never be sent to the Ledger.
    """
    text = normalize_merchant_text(raw_merchant)
    candidates = [
        p for p in patterns
        if p.active and (usable_codes is None or p.code in usable_codes) and _matches(p, text)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda p: (p.priority, p.pattern)).code
