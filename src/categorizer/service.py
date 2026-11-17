"""Categorizer Service — suggests a SYSTEM category code for every row.

XS-DPCAT-03 (v3) / REQ-DP-09: the pipeline names a SYSTEM category by its code and nothing else. It
holds no copy of the Ledger's categories, never sends an id, and knows nothing of the user's own
categories or merchant rules — the Ledger applies those, then turns a suggested code into a
category (XS-DPCAT-07). Order, with no paid classifier and no shared cache:
  1. The bank's label, looked up in the bank-label table (CSV rows that carry one).
  2. MerchantCategoryMap patterns on the merchant text (XS-DPCAT-06).
  3. No code. The Ledger stores the row as uncategorized.

__author__ = "Van Vo"
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from .bank_categories import BANK_LABEL_TO_CODE
from .merchant_map import MerchantPattern, match_merchant_code
from .schemas import CodeSuggestion

UNCATEGORIZED_CODE = "uncategorized"  # the Ledger's fallback; the pipeline never sends it (XS-DPCAT-01)


def normalize_label(label: str) -> str:
    """XS-DPCAT Appendix A, shared with the Ledger: trim and lowercase, `&` -> ` and `, any other
    character outside a-z, 0-9, space and dash -> space, runs of spaces and dashes -> one dash,
    leading and trailing dashes stripped. An empty result means no label."""
    text = label.strip().lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    return re.sub(r"[\s-]+", "-", text).strip("-")


class CodeSuggester:
    """Built once per upload from the merchant patterns."""

    def __init__(self, merchant_patterns: Iterable[MerchantPattern]) -> None:
        self._patterns = tuple(merchant_patterns)

    def suggest(self, raw_merchant: str, source_category: Optional[str]) -> CodeSuggestion:
        label = normalize_label(source_category) if source_category else ""
        if label and (code := BANK_LABEL_TO_CODE.get(label)):
            return CodeSuggestion(code, "BANK_LABEL")

        if code := match_merchant_code(raw_merchant, self._patterns):
            return CodeSuggestion(code, "MERCHANT_MAP")

        return CodeSuggestion(None, "NONE")
