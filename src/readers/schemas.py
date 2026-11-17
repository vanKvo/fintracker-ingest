"""The table every reader produces (IN-RDR Appendix A).

__author__ = "Van Vo"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

FileType = Literal["CSV", "XLSX"]


@dataclass(frozen=True)
class Table:
    """Headers plus rows of text cells. Each row has exactly len(headers) cells."""

    file_type: FileType
    headers: list[str]
    rows: list[list[str]]
    header_row_index: int  # 0-based record (CSV) or row (XLSX) of the header
    source_row_numbers: list[int]  # 1-based record/row number in the file, one per data row
    sheet_name: str | None = None
    sheet_names: list[str] = field(default_factory=list)
