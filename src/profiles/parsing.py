"""Reading amounts and dates from text cells (IN-FMT-03, IN-FMT-05, IN-IMP-07).

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation

from .schemas import DateFormat

_DATE_PARTS = re.compile(r"^(\d{1,4})[/.-](\d{1,2})[/.-](\d{1,4})(?:[T ].*)?$")


def parse_amount(text: str) -> Decimal | None:
    """`$1,234.56` → 1234.56; `(42.00)`, `-42.00` and `42.00-` → -42.00. None if not a number."""
    raw = re.sub(r"[\s$,]", "", text or "")
    if not raw:
        return None
    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        raw, negative = raw[1:-1], True
    if raw.endswith("-"):
        raw, negative = raw[:-1], not negative
    if raw.startswith(("-", "+")):
        negative = negative != (raw[0] == "-")
        raw = raw[1:]
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", raw):
        return None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return -value if negative else value


def _year(text: str) -> int | None:
    if len(text) == 2:
        return 2000 + int(text)  # IN-IMP-07: a two-digit year is 20YY
    return int(text) if len(text) == 4 else None


def parse_date(text: str, fmt: DateFormat) -> dt.date | None:
    """The date in the profile's format; separators `/`, `-` and `.`. None if unreadable."""
    match = _DATE_PARTS.match((text or "").strip())
    if not match:
        return None
    a, b, c = match.groups()
    try:
        if fmt in (DateFormat.ISO, DateFormat.YMD):
            if len(a) != 4:
                return None
            if fmt == DateFormat.ISO and (len(b) != 2 or len(c) != 2):
                return None
            return dt.date(int(a), int(b), int(c))
        year = _year(c)
        if year is None or len(a) > 2:
            return None
        month, day = (int(a), int(b)) if fmt == DateFormat.MDY else (int(b), int(a))
        return dt.date(year, month, day)
    except ValueError:
        return None
