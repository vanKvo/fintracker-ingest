"""Header lookup shared by inference, validation and apply.

__author__ = "Van Vo"
"""

from __future__ import annotations

from dataclasses import fields
from typing import Sequence

from .schemas import Columns
from .signature import normalize_header


def index_of(headers: Sequence[str], name: str | None) -> int | None:
    if name is None:
        return None
    wanted = normalize_header(name)
    return next((i for i, h in enumerate(headers) if normalize_header(h) == wanted), None)


def mapped(columns: Columns) -> dict[str, str]:
    return {f.name: getattr(columns, f.name) for f in fields(columns) if getattr(columns, f.name) is not None}
