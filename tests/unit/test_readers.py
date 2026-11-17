"""IN-RDR: file readers turn CSV and XLSX bank exports into a table of text cells.

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt
import io
import re
import zipfile

import openpyxl
import pytest

from src.core.exceptions import FileTooLargeError, InvalidFileError, TooManyRowsError, UnsupportedFormatError
from src.readers.service import read_file
from tests.unit.xlsx_fixtures import rewrite_entries, workbook_bytes

CHASE_CHECKING = (
    "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
    "DEBIT,01/15/2026,STARBUCKS #12345,-5.75,DEBIT_CARD,994.25,\n"
    "CREDIT,01/16/2026,ACME PAYROLL,1500.00,ACH_CREDIT,2494.25,\n"
)


def _all_text(table) -> bool:  # type: ignore[no-untyped-def]
    return all(isinstance(c, str) for c in table.headers) and all(
        isinstance(c, str) for row in table.rows for c in row
    )


# --- IN-RDR-01: reader contract and detection ---

def test_in_rdr_01_csv_and_xlsx_are_read_by_their_own_reader() -> None:
    """IN-RDR-01 reader contract and detection: each file type is read by its reader."""
    csv_table = read_file("chase.csv", CHASE_CHECKING.encode())
    xlsx_table = read_file("discover.xlsx", workbook_bytes([("Sheet1", [["Date", "Description", "Amount"], ["2026-01-15", "A", 1]])]))
    assert csv_table.file_type == "CSV"
    assert xlsx_table.file_type == "XLSX"
    assert _all_text(csv_table) and _all_text(xlsx_table)


def test_in_rdr_01_content_wins_over_extension() -> None:
    """IN-RDR-01 reader contract and detection: a workbook named .csv is read as a workbook."""
    data = workbook_bytes([("Sheet1", [["Date", "Description", "Amount"], ["2026-01-15", "A", 1]])])
    assert read_file("export.csv", data).file_type == "XLSX"


@pytest.mark.parametrize("data", [
    b"%PDF-1.7\n...",
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 20,
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 50,
])
def test_in_rdr_01_unreadable_types_are_unsupported(data: bytes) -> None:
    """IN-RDR-01 reader contract and detection: PDF, images and legacy .xls end with UNSUPPORTED_FORMAT."""
    with pytest.raises(UnsupportedFormatError):
        read_file("statement.csv", data)


# --- IN-RDR-02: CSV reader ---

def test_in_rdr_02_reads_headers_and_rows() -> None:
    """IN-RDR-02 CSV reader: a Chase checking export gives 7 headers and one row per transaction."""
    table = read_file("chase.csv", CHASE_CHECKING.encode())
    assert table.headers == ["Details", "Posting Date", "Description", "Amount", "Type", "Balance", "Check or Slip #"]
    assert len(table.rows) == 2
    assert table.rows[0][2] == "STARBUCKS #12345"
    assert table.source_row_numbers == [2, 3]


def test_in_rdr_02_skips_preamble_lines() -> None:
    """IN-RDR-02 CSV reader: preamble lines above the header are skipped."""
    preamble = "Account: ...4321\nExported on 2026-02-01\n\nCurrent balance: 994.25\n"
    plain = read_file("a.csv", CHASE_CHECKING.encode())
    with_preamble = read_file("a.csv", (preamble + CHASE_CHECKING).encode())
    assert with_preamble.headers == plain.headers
    assert with_preamble.rows == plain.rows
    assert with_preamble.header_row_index == 4


def test_in_rdr_02_windows_1252_is_decoded_without_replacement_characters() -> None:
    """IN-RDR-02 CSV reader: a Windows-1252 file reads CAFÉ, not a replacement character."""
    data = "Date,Description,Amount\n01/15/2026,CAFÉ LUNA,-12.00\n".encode("cp1252")
    assert read_file("a.csv", data).rows[0][1] == "CAFÉ LUNA"


def test_in_rdr_02_utf8_byte_order_mark_is_removed() -> None:
    """IN-RDR-02 CSV reader: a UTF-8 byte order mark doesn't stick to the first header."""
    data = "﻿Date,Description,Amount\n01/15/2026,A,-1.00\n".encode("utf-8")
    assert read_file("a.csv", data).headers[0] == "Date"


def test_in_rdr_02_semicolon_file_reads_like_comma_file() -> None:
    """IN-RDR-02 CSV reader: the delimiter is detected."""
    comma = read_file("a.csv", CHASE_CHECKING.encode())
    semi = read_file("a.csv", CHASE_CHECKING.replace(",", ";").encode())
    assert semi.headers == comma.headers and semi.rows == comma.rows


def test_in_rdr_02_quoted_commas_and_line_breaks_stay_in_one_cell() -> None:
    """IN-RDR-02 CSV reader: quoted fields keep their commas and line breaks."""
    data = 'Date,Description,Amount\n01/15/2026,"SHOP, INC\nSTORE 2",-3.00\n01/16/2026,B,-1.00\n'
    table = read_file("a.csv", data.encode())
    assert table.rows[0][1] == "SHOP, INC\nSTORE 2"
    assert len(table.rows) == 2


def test_in_rdr_02_empty_rows_are_dropped_and_others_kept() -> None:
    """IN-RDR-02 CSV reader: empty rows are dropped; summary lines are kept for later counting."""
    data = "Date,Description,Amount\n01/15/2026,A,-1.00\n,,\nTotal,,-1.00\n"
    assert read_file("a.csv", data.encode()).rows == [["01/15/2026", "A", "-1.00"], ["Total", "", "-1.00"]]


@pytest.mark.parametrize("data", [
    "\n".join(["note"] * 25) + "\nDate,Description,Amount\n01/15/2026,A,1\n",
    "Date,Description,date\n01/15/2026,A,1\n",
    "Date,Description,Amount\n",
])
def test_in_rdr_02_invalid_csv(data: str) -> None:
    """IN-RDR-02 CSV reader: no header in 20 lines, duplicate headers, or no data rows end with INVALID_CSV_FORMAT."""
    with pytest.raises(InvalidFileError):
        read_file("a.csv", data.encode())


def test_in_rdr_02_profile_header_row_is_used() -> None:
    """IN-RDR-02 CSV reader: a profile may fix the header row."""
    data = "Bank export,x\nDate,Description,Amount\n01/15/2026,A,1\n"
    assert read_file("a.csv", data.encode(), header_row=1).headers == ["Date", "Description", "Amount"]


# --- IN-RDR-03: XLSX reader ---

def test_in_rdr_03_typed_cells_render_as_text() -> None:
    """IN-RDR-03 XLSX reader: dates render as ISO dates and numbers in plain decimal form."""
    data = workbook_bytes([("Sheet1", [
        ["Date", "Description", "Amount"],
        [dt.datetime(2026, 1, 15), "STARBUCKS", -12.5],
        [dt.date(2026, 1, 16), "PAYROLL", 1500],
    ])])
    table = read_file("a.xlsx", data)
    assert table.rows == [["2026-01-15", "STARBUCKS", "-12.5"], ["2026-01-16", "PAYROLL", "1500"]]


def test_in_rdr_03_picks_the_sheet_with_a_known_layout_and_lists_all_sheets() -> None:
    """IN-RDR-03 XLSX reader: the sheet matching a known profile is read, and every sheet is listed."""
    from src.profiles.signature import header_signature
    data = workbook_bytes([
        ("Summary", [["Account", "Balance"], ["Checking", 100]]),
        ("Transactions", [["Date", "Description", "Amount"], ["2026-01-15", "A", 1]]),
    ])
    known = frozenset({header_signature(["Date", "Description", "Amount"])})
    table = read_file("a.xlsx", data, known_signatures=known)
    assert table.sheet_name == "Transactions"
    assert table.sheet_names == ["Summary", "Transactions"]
    assert read_file("a.xlsx", data).sheet_name == "Summary"


def test_in_rdr_03_user_picked_sheet_is_read() -> None:
    """IN-RDR-03 XLSX reader: a sheet the user picks in the preview is read."""
    data = workbook_bytes([
        ("Summary", [["Account", "Balance"], ["Checking", 100]]),
        ("Transactions", [["Date", "Description", "Amount"], ["2026-01-15", "A", 1]]),
    ])
    assert read_file("a.xlsx", data, sheet="Transactions").headers == ["Date", "Description", "Amount"]


def test_in_rdr_03_formula_reads_its_cached_value_or_empty() -> None:
    """IN-RDR-03 XLSX reader: formulas are never evaluated; the cached value is read, or empty without one."""
    data = workbook_bytes([("Sheet1", [["Date", "Description", "Amount"], ["2026-01-15", "A", "=B2*-1"], ["2026-01-16", "B", "=B3*-1"]])])

    def add_cached_value(name: str, body: bytes) -> bytes:
        if name == "xl/worksheets/sheet1.xml":
            return re.sub(rb"<f>B2\*-1</f><v\s*/>|<f>B2\*-1</f><v></v>", b"<f>B2*-1</f><v>-12.5</v>", body, count=1)
        return body

    table = read_file("a.xlsx", rewrite_entries(data, add_cached_value))
    assert table.rows[0][2] == "-12.5"
    assert table.rows[1][2] == ""


def test_in_rdr_03_macro_workbook_is_unsupported() -> None:
    """IN-RDR-03 XLSX reader: a workbook containing macros ends with UNSUPPORTED_FORMAT."""
    data = workbook_bytes([("Sheet1", [["Date", "Description", "Amount"], ["2026-01-15", "A", 1]])])
    with pytest.raises(UnsupportedFormatError):
        read_file("a.xlsx", rewrite_entries(data, lambda n, b: b, {"xl/vbaProject.bin": b"\x00" * 10}))


def test_in_rdr_03_no_sheet_with_a_header_is_invalid() -> None:
    """IN-RDR-03 XLSX reader: no sheet with a header row ends with INVALID_CSV_FORMAT."""
    data = workbook_bytes([("Sheet1", [["only one cell"], ["x"]])])
    with pytest.raises(InvalidFileError):
        read_file("a.xlsx", data)


# --- IN-RDR-04: safe parsing limits ---

def test_in_rdr_04_zip_bomb_is_refused_before_decompressing() -> None:
    """IN-RDR-04 safe parsing limits: uncompressed size over 50 MB ends with FILE_TOO_LARGE."""
    data = workbook_bytes([("Sheet1", [["Date", "Description", "Amount"], ["2026-01-15", "A", 1]])])
    bomb = rewrite_entries(data, lambda n, b: b, {"xl/media/padding.bin": b"\x00" * (51 * 1024 * 1024)})
    assert len(bomb) < 5 * 1024 * 1024
    with pytest.raises(FileTooLargeError):
        read_file("a.xlsx", bomb)


def test_in_rdr_04_xml_entities_are_refused() -> None:
    """IN-RDR-04 safe parsing limits: an XLSX whose XML declares an entity ends with UNSUPPORTED_FORMAT."""
    data = workbook_bytes([("Sheet1", [["Date", "Description", "Amount"], ["2026-01-15", "A", 1]])])

    def add_entity(name: str, body: bytes) -> bytes:
        if name == "xl/worksheets/sheet1.xml":
            return b'<!DOCTYPE x [<!ENTITY a "aaaa">]>' + body
        return body

    with pytest.raises(UnsupportedFormatError):
        read_file("a.xlsx", rewrite_entries(data, add_entity))


def test_in_rdr_04_defusedxml_is_active() -> None:
    """IN-RDR-04 safe parsing limits: openpyxl parses XML through defusedxml."""
    assert openpyxl.DEFUSEDXML is True


def test_in_rdr_04_file_over_5_mb_is_refused() -> None:
    """IN-RDR-04 safe parsing limits: a file over 25 MB ends with FILE_TOO_LARGE before it is read."""
    with pytest.raises(FileTooLargeError):
        read_file("a.csv", b"x" * (25 * 1024 * 1024 + 1))


def test_in_rdr_04_more_than_5000_rows_is_refused() -> None:
    """IN-RDR-04 safe parsing limits: reading stops after 5,000 data rows with TOO_MANY_ROWS."""
    rows = "".join(f"01/15/2026,A{i},-1.00\n" for i in range(5001))
    with pytest.raises(TooManyRowsError):
        read_file("a.csv", ("Date,Description,Amount\n" + rows).encode())
    exactly = "".join(f"01/15/2026,A{i},-1.00\n" for i in range(5000))
    assert len(read_file("a.csv", ("Date,Description,Amount\n" + exactly).encode()).rows) == 5000
