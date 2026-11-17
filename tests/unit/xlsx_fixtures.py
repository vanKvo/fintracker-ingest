"""Builds small XLSX files for reader tests. Synthetic data only: real bank exports never go in
the repository.

__author__ = "Van Vo"
"""

from __future__ import annotations

import io
import zipfile
from typing import Callable, Sequence

from openpyxl import Workbook


def workbook_bytes(sheets: Sequence[tuple[str, Sequence[Sequence[object]]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets:
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(list(row))
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def rewrite_entries(data: bytes, change: Callable[[str, bytes], bytes], extra: dict[str, bytes] | None = None) -> bytes:
    """Copy a ZIP, passing each entry through `change`, and add `extra` entries."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            dst.writestr(info.filename, change(info.filename, src.read(info.filename)))
        for name, body in (extra or {}).items():
            dst.writestr(name, body)
    return out.getvalue()
