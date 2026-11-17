"""Reading an uploaded file into a table (IN-RDR-01, IN-RDR-04).

Content decides the file type; the extension is only a hint. Adding a reader means adding it to
READERS in detection order.

__author__ = "Van Vo"
"""

from __future__ import annotations

from typing import Protocol

from ..core.exceptions import FileTooLargeError, UnsupportedFormatError
from .csv_reader import CsvReader
from .schemas import Table
from .xlsx_reader import XlsxReader, is_xlsx

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_DATA_ROWS = 5000
_HEAD_BYTES = 8192
_LEGACY_XLS = b"\xd0\xcf\x11\xe0"


class Reader(Protocol):
    file_type: str

    def detect(self, file_name: str, head: bytes) -> bool: ...

    def read(self, data: bytes, *, header_row: int | None, sheet: str | None, known_signatures: frozenset[str], max_rows: int) -> Table: ...


def _readers_for(data: bytes) -> tuple[Reader, ...]:
    return (XlsxReader(),) if is_xlsx(data) else (CsvReader(),)


def read_file(
    file_name: str,
    data: bytes,
    *,
    header_row: int | None = None,
    sheet: str | None = None,
    known_signatures: frozenset[str] = frozenset(),
    max_bytes: int = MAX_FILE_BYTES,
    max_rows: int = MAX_DATA_ROWS,
) -> Table:
    """The file's table.

    Raises:
        FileTooLargeError: over max_bytes, before anything is read; or a workbook too large uncompressed.
        UnsupportedFormatError: no reader accepts the file (PDF, image, legacy .xls, macros).
        InvalidFileError: no header row, duplicate headers, or no data rows.
        TooManyRowsError: more than max_rows data rows.
    """
    if len(data) > max_bytes:
        raise FileTooLargeError(f"File larger than {max_bytes} bytes")
    head = data[:_HEAD_BYTES]
    if head.startswith(_LEGACY_XLS):
        raise UnsupportedFormatError("Legacy .xls")
    for reader in _readers_for(data):
        if reader.detect(file_name, head):
            return reader.read(data, header_row=header_row, sheet=sheet, known_signatures=known_signatures, max_rows=max_rows)
    raise UnsupportedFormatError("No reader accepts this file")
