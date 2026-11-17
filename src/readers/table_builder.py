"""Finding the header and building the table, shared by the CSV and XLSX readers (IN-RDR-02, -03).

__author__ = "Van Vo"
"""

from __future__ import annotations

from typing import Sequence

from ..core.exceptions import InvalidFileError, TooManyRowsError
from ..profiles.signature import header_signature
from .schemas import FileType, Table

HEADER_SEARCH_LINES = 20


def _non_empty(row: Sequence[str]) -> int:
    return sum(1 for cell in row if cell.strip())


def _trimmed_len(row: Sequence[str]) -> int:
    """Length without trailing empty cells (spreadsheets pad every row to the widest column)."""
    n = len(row)
    while n and not row[n - 1].strip():
        n -= 1
    return n


def find_header_row(records: Sequence[Sequence[str]]) -> int | None:
    """IN-RDR-02: the first of the first 20 records with at least 2 non-empty cells, followed by a
    record of the same width, so preamble lines like "Account: ...4321" are skipped."""
    for i, row in enumerate(records[:HEADER_SEARCH_LINES]):
        if _non_empty(row) < 2 or i + 1 >= len(records):
            continue
        nxt = records[i + 1]
        if len(nxt) == len(row) or _trimmed_len(nxt) == _trimmed_len(row):
            return i
    return None


def build_table(
    file_type: FileType,
    records: Sequence[Sequence[str]],
    *,
    header_row: int | None,
    max_rows: int,
    sheet_name: str | None = None,
    sheet_names: Sequence[str] = (),
) -> Table:
    """Headers from the header row, then every non-empty record after it, padded or cut to the
    header's width.

    Raises:
        InvalidFileError: no header row, duplicate headers, or no data rows.
        TooManyRowsError: more than max_rows data rows (IN-IMP-02).
    """
    index = header_row if header_row is not None else find_header_row(records)
    if index is None or index >= len(records):
        raise InvalidFileError("No header row")
    width = _trimmed_len(records[index])
    headers = [cell.strip() for cell in records[index][:width]]
    if width < 2:
        raise InvalidFileError("No header row")
    header_signature(headers)  # raises on duplicate names

    rows: list[list[str]] = []
    numbers: list[int] = []
    for number, record in enumerate(records[index + 1:], start=index + 2):
        if not _non_empty(record):
            continue
        if len(rows) == max_rows:
            raise TooManyRowsError(f"More than {max_rows} data rows")
        cells = [cell.strip() for cell in record[:width]]
        rows.append(cells + [""] * (width - len(cells)))
        numbers.append(number)
    if not rows:
        raise InvalidFileError("No data rows")
    return Table(file_type, headers, rows, index, numbers, sheet_name, list(sheet_names))
