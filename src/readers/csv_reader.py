"""CSV reader (IN-RDR-02).

Decodes UTF-8 (byte order mark removed), then Windows-1252, and never inserts replacement
characters. No encoding-detection library: the common one, chardet, is LGPL (IN-RDR principle 4).

__author__ = "Van Vo"
"""

from __future__ import annotations

import csv
import io

from ..core.exceptions import InvalidFileError
from .schemas import Table
from .table_builder import build_table, find_header_row

_DELIMITERS = (",", ";", "\t", "|")
_SNIFF_RECORDS = 50


def decode(data: bytes) -> str | None:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _records(text: str, delimiter: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)]


def _score(records: list[list[str]]) -> int:
    """How many records after the header have the header's width; 0 if no header is found."""
    sample = records[:_SNIFF_RECORDS]
    index = find_header_row(sample)
    if index is None:
        return 0
    width = len(sample[index])
    return 1 + sum(1 for row in sample[index + 1:] if len(row) == width)


def looks_like_csv(head: bytes) -> bool:
    """IN-RDR-01: decodable text where a delimiter splits a line into at least 2 columns."""
    text = decode(head)
    if text is None or "\x00" in text:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    return any(len(line.split(d)) >= 2 for line in lines for d in _DELIMITERS)


class CsvReader:
    file_type = "CSV"

    def detect(self, file_name: str, head: bytes) -> bool:
        return looks_like_csv(head)

    def read(self, data: bytes, *, header_row: int | None, sheet: str | None, known_signatures: frozenset[str], max_rows: int) -> Table:
        text = decode(data)
        if text is None:
            raise InvalidFileError("Undecodable text")
        best = max(_DELIMITERS, key=lambda d: _score(_records(text[:65536], d)))
        return build_table("CSV", _records(text, best), header_row=header_row, max_rows=max_rows)
