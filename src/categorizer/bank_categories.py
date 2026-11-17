"""Bank-provided category label -> Ledger SYSTEM category code.

XS-DPCAT-03 (v3): some exports (Chase, Discover credit card CSVs) carry the bank's own category.
Keys are labels normalized like codes (XS-DPCAT Appendix A); values are SYSTEM codes, never UUIDs,
so the table works in every environment. The pipeline holds no list of the Ledger's categories, so
the table has an entry for every active SYSTEM code's own label ("Groceries" -> groceries); the
deploy check (code_check.py) warns when one is missing. `uncategorized` has none: no suggestion
is how the pipeline says it. Labels with no clear equivalent are left out on purpose and fall
through to the merchant table.

__author__ = "Van Vo"
"""

from __future__ import annotations

BANK_LABEL_TO_CODE: dict[str, str] = {
    # A SYSTEM code's own label
    "groceries": "groceries",
    "food-and-drink": "food-and-drink",
    "transportation": "transportation",
    "shopping": "shopping",
    "entertainment": "entertainment",
    "utilities": "utilities",
    "housing": "housing",
    "healthcare": "healthcare",
    "insurance": "insurance",
    "subscriptions": "subscriptions",
    "travel": "travel",
    "education": "education",
    "personal-care": "personal-care",
    "income": "income",
    "transfer": "transfer",
    "fees": "fees",
    # Chase
    "bills-and-utilities": "utilities",
    "gas": "transportation",
    "automotive": "transportation",
    "health-and-wellness": "healthcare",
    "personal": "personal-care",
    "home": "housing",
    "fees-and-adjustments": "fees",
    # Discover
    "merchandise": "shopping",
    "department-stores": "shopping",
    "restaurants": "food-and-drink",
    "supermarkets": "groceries",
    "gasoline": "transportation",
    "travel-entertainment": "travel",
    "home-improvement": "housing",
    "medical-services": "healthcare",
}
