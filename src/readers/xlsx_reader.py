"""XLSX reader (IN-RDR-03, IN-RDR-04).

Read-only with cached values: formulas are never evaluated. The ZIP directory is checked before any
entry is opened, macros are refused, and openpyxl parses XML through defusedxml.

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from decimal import Decimal
from typing import Iterable

from defusedxml.common import DefusedXmlException
from openpyxl import load_workbook

from ..core.exceptions import FileTooLargeError, InvalidFileError, UnsupportedFormatError
from ..core.observability import logger
from ..profiles.signature import header_signature
from .schemas import Table
from .table_builder import build_table, find_header_row

MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ZIP_ENTRIES = 1000
_MACRO_ENTRY = "xl/vbaProject.bin"


def is_xlsx(data: bytes) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        return "xl/workbook.xml" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        return False


def _check_zip(data: bytes) -> None:
    infos = zipfile.ZipFile(io.BytesIO(data)).infolist()
    if len(infos) > MAX_ZIP_ENTRIES or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED_BYTES:
        raise FileTooLargeError("Workbook too large when uncompressed")
    names = {i.filename for i in infos}
    if _MACRO_ENTRY in names:
        raise UnsupportedFormatError("Macro-enabled workbook")
    if "[Content_Types].xml" in names:
        content_types = zipfile.ZipFile(io.BytesIO(data)).read("[Content_Types].xml")
        if b"macroEnabled" in content_types:
            raise UnsupportedFormatError("Macro-enabled workbook")


def render(value: object) -> str:
    """A cell as text: ISO date for dates, plain decimal for numbers, empty for no value."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (dt.datetime, dt.date)):
        return value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = format(Decimal(repr(value)), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    return str(value)


def _sheet_records(rows: Iterable[tuple[object, ...]]) -> list[list[str]]:
    return [[render(v) for v in row] for row in rows]


class XlsxReader:
    file_type = "XLSX"

    def detect(self, file_name: str, head: bytes) -> bool:
        return head.startswith(b"PK")  # confirmed by is_xlsx on the whole file

    def read(self, data: bytes, *, header_row: int | None, sheet: str | None, known_signatures: frozenset[str], max_rows: int) -> Table:
        _check_zip(data)
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            sheets = {ws.title: _sheet_records(ws.iter_rows(values_only=True)) for ws in wb.worksheets}
        except DefusedXmlException:
            logger.warning("XML_ENTITY_REFUSED")
            raise UnsupportedFormatError("XML entities refused") from None
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            raise UnsupportedFormatError("Workbook could not be read") from None

        names = list(sheets)
        chosen = sheet if sheet in sheets else self._pick(sheets, known_signatures)
        if chosen is None:
            raise InvalidFileError("No sheet has a header row")
        return build_table("XLSX", sheets[chosen], header_row=header_row, max_rows=max_rows, sheet_name=chosen, sheet_names=names)

    @staticmethod
    def _pick(sheets: dict[str, list[list[str]]], known: frozenset[str]) -> str | None:
        """IN-RDR-03: the first sheet with a known layout, else the first sheet with a header."""
        with_header: list[str] = []
        for name, records in sheets.items():
            index = find_header_row(records)
            if index is None:
                continue
            with_header.append(name)
            headers = [c.strip() for c in records[index] if c.strip()]
            try:
                if header_signature(headers) in known:
                    return name
            except InvalidFileError:
                continue
        return with_header[0] if with_header else None
