"""When agreed votes qualify a profile for promotion (IN-FMT-08). Pure: the store reads the votes.

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Vote:
    profile_hash: str
    confirmed_at: dt.datetime


def qualifying_hash(votes: Sequence[Vote], *, now: dt.datetime, min_users: int, min_agreement: float, window_days: int) -> str | None:
    """The profile hash that at least `min_users` distinct users chose within the window, with at least
    `min_agreement` of the window's votes; None otherwise. Votes are already one per user."""
    recent = [v for v in votes if v.confirmed_at >= now - dt.timedelta(days=window_days)]
    if not recent:
        return None
    best, count = Counter(v.profile_hash for v in recent).most_common(1)[0]
    return best if count >= min_users and count / len(recent) >= min_agreement else None
