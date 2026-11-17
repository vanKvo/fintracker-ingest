"""The current time, in one place so the expiry rules can be tested (IN-IMP-08).

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now() -> dt.datetime:
    return _now()


def iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
