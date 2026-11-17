"""Profile validation (IN-FMT-04).

__author__ = "Van Vo"
"""

from __future__ import annotations

from typing import Sequence

from .columns import index_of, mapped
from .schemas import AmountMode, Profile
from .signature import normalize_header

_REQUIRED_BY_MODE = {
    AmountMode.SIGNED: ("amount",),
    AmountMode.SPLIT: ("debit", "credit"),
    AmountMode.INDICATOR: ("amount", "direction"),
}


def validate_profile(profile: Profile, headers: Sequence[str]) -> list[str]:
    """The fields to fix, as `columns.<field>` or the profile field's name; empty when valid."""
    problems: list[str] = []
    columns = mapped(profile.columns)
    for field in ("date", "description", *_REQUIRED_BY_MODE[profile.amount_mode]):
        if field not in columns:
            problems.append(f"columns.{field}")
    if profile.amount_mode == AmountMode.SIGNED and profile.sign_convention is None:
        problems.append("signConvention")

    seen: set[str] = set()
    for field, header in columns.items():
        key = normalize_header(header)
        if index_of(headers, header) is None or key in seen:
            if f"columns.{field}" not in problems:
                problems.append(f"columns.{field}")
        seen.add(key)
    return problems
