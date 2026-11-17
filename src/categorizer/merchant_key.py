"""The normalized merchant a per-user merchant rule is keyed on.

REQ-DP-09: "Always use this for <merchant>" must match the same merchant on the next statement,
so the key drops what changes between visits — order ids (AMZN MKTP US*2K4AB1), store and
reference numbers (#123, 00012345) and point-of-sale prefixes (TST*, SQ *). An id after "*" is
only dropped when it contains a digit, so UBER *TRIP and UBER *EATS stay different merchants.

__author__ = "Van Vo"
"""

from __future__ import annotations

import re

_POS_PREFIX = re.compile(r"^(TST\*|SQ \*|SP \*|PY \*|PAYPAL \*)\s*")
_ORDER_ID = re.compile(r"\*[A-Z0-9]*\d[A-Z0-9]*")
_REFERENCE = re.compile(r"#\s*\d+|\b\d{3,}\b")


def merchant_key(raw_merchant: str) -> str:
    key = re.sub(r"\s+", " ", raw_merchant).strip().upper()
    key = _POS_PREFIX.sub("", key)
    key = _ORDER_ID.sub("", key)
    key = _REFERENCE.sub("", key)
    return re.sub(r"\s+", " ", key).strip()
