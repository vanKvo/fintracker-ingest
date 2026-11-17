"""The merchant patterns, packaged with the code (IN-IMP Appendix C).

Copied from the legacy seed (infrastructure/seed/merchant_category_map.json). Packaging them keeps the
service to two tables; a change ships with a deploy, which a review should see anyway.

__author__ = "Van Vo"
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .merchant_map import MerchantPattern
from .service import CodeSuggester

_DATA = Path(__file__).with_name("merchant_category_map.json")


@lru_cache(maxsize=1)
def suggester() -> CodeSuggester:
    rows = json.loads(_DATA.read_text(encoding="utf-8"))
    return CodeSuggester(MerchantPattern(r["pattern"], r["match_type"], r["code"], int(r["priority"]), bool(r["active"])) for r in rows)
