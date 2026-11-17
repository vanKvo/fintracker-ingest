"""Header signature (IN-FMT-01, carried from DP-MAP-01).

A bank has more than one export layout, so a profile is keyed by the file's header signature as
well as the bank. The signature ignores column order and letter case; adding, removing or renaming
a column changes it.

__author__ = "Van Vo"
"""

from __future__ import annotations

import hashlib
import re
from typing import Sequence

from ..core.exceptions import InvalidFileError

_WHITESPACE = re.compile(r"\s+")
_SIGNATURE_LENGTH = 16


def normalize_header(header: str) -> str:
    """Trim, lowercase and collapse whitespace."""
    return _WHITESPACE.sub(" ", header.strip()).lower()


def header_signature(headers: Sequence[str]) -> str:
    """First 16 hex characters of the SHA-256 of the sorted, normalized headers joined by `|`.

    Raises:
        InvalidFileError: two headers are the same once normalized; a profile couldn't say which
            one it means.
    """
    normalized = [normalize_header(h) for h in headers]
    if len(set(normalized)) != len(normalized):
        raise InvalidFileError("Duplicate header names")
    return hashlib.sha256("|".join(sorted(normalized)).encode("utf-8")).hexdigest()[:_SIGNATURE_LENGTH]
