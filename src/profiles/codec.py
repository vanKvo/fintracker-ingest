"""Profile ↔ JSON (IN-FMT Appendix A, camelCase), as stored and as the API sends it.

A malformed profile from the browser is refused with the fields to fix (IN-FMT-04).

__author__ = "Van Vo"
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields as dc_fields
from typing import Any

from ..core.exceptions import InvalidProfileError
from .schemas import (
    DEFAULT_CREDIT_VALUES, DEFAULT_DEBIT_VALUES, AmountMode, Columns, DateFormat, Profile, SignConvention,
)

_COLUMN_NAMES = tuple(f.name for f in dc_fields(Columns))


def to_dict(profile: Profile) -> dict[str, Any]:
    out: dict[str, Any] = {
        "columns": {name: getattr(profile.columns, name) for name in _COLUMN_NAMES},
        "amountMode": str(profile.amount_mode),
        "signConvention": str(profile.sign_convention) if profile.sign_convention else None,
        "dateFormat": str(profile.date_format),
        "headerRow": profile.header_row,
        "debitValues": list(profile.debit_values),
        "creditValues": list(profile.credit_values),
        "pendingValues": list(profile.pending_values),
    }
    return out


def _strings(value: object, field: str, problems: list[str]) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return tuple(value)
    problems.append(field)
    return None


def from_dict(data: object) -> Profile:
    """Raises InvalidProfileError naming each malformed field."""
    problems: list[str] = []
    if not isinstance(data, dict):
        raise InvalidProfileError(fields=["profile"], log_message="profile is not an object")
    raw_columns = data.get("columns") or {}
    if not isinstance(raw_columns, dict):
        raw_columns, problems = {}, problems + ["columns"]
    columns: dict[str, str | None] = {}
    for name in _COLUMN_NAMES:
        value = raw_columns.get(name)
        if value is not None and not isinstance(value, str):
            problems.append(f"columns.{name}")
            value = None
        columns[name] = value or None

    def enum(cls: type, key: str, required: bool) -> Any:
        value = data.get(key)
        if value is None:
            if required:
                problems.append(key)
            return None
        try:
            return cls(value)
        except ValueError:
            problems.append(key)
            return None

    mode = enum(AmountMode, "amountMode", True)
    date_format = enum(DateFormat, "dateFormat", True)
    sign = enum(SignConvention, "signConvention", False)
    header_row = data.get("headerRow")
    if header_row is not None and (not isinstance(header_row, int) or header_row < 0):
        problems.append("headerRow")
        header_row = None
    debit = _strings(data.get("debitValues"), "debitValues", problems)
    credit = _strings(data.get("creditValues"), "creditValues", problems)
    pending = _strings(data.get("pendingValues"), "pendingValues", problems)
    if problems or mode is None or date_format is None:
        raise InvalidProfileError(fields=problems, log_message="malformed profile")
    return Profile(
        columns=Columns(**columns), amount_mode=mode, date_format=date_format, sign_convention=sign,
        header_row=header_row, debit_values=debit or DEFAULT_DEBIT_VALUES,
        credit_values=credit or DEFAULT_CREDIT_VALUES, pending_values=pending or (),
    )


def profile_hash(profile: Profile) -> str:
    """IN-FMT-07: the same settings give the same hash whatever their order."""
    return hashlib.sha256(json.dumps(to_dict(profile), sort_keys=True).encode()).hexdigest()[:32]
