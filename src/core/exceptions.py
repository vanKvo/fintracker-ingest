"""Errors (XS-IMP-04, app doc 4.8).

- `IngestError`: ends an import with a reason code from XS-IMP Appendix A. The import is marked and
  the Ledger is told; the client sees the import with its reason.
- `AppError`: answers the request with an RFC 9457 problem whose `code` the UI branches on. The
  `detail` is safe to show; `log_message` is for logs only. Neither is ever built from another
  exception's text.

__author__ = "Van Vo"
"""

from __future__ import annotations

from collections.abc import Sequence

OUR_SIDE = "Something went wrong on our side. Try again in a few minutes."


class IngestError(Exception):
    """Base of the errors that end an import. `reason` is a code from XS-IMP Appendix A."""

    reason = "PIPELINE_ERROR"


class UnsupportedFormatError(IngestError):
    reason = "UNSUPPORTED_FORMAT"


class InvalidFileError(IngestError):
    """No header row, duplicate headers, or no data rows."""

    reason = "INVALID_CSV_FORMAT"


class FileTooLargeError(IngestError):
    reason = "FILE_TOO_LARGE"


class TooManyRowsError(IngestError):
    reason = "TOO_MANY_ROWS"


class UnsupportedAccountTypeError(IngestError):
    reason = "UNSUPPORTED_ACCOUNT_TYPE"


class AppError(Exception):
    status = 500
    code = "PIPELINE_ERROR"
    title = "Internal error"
    detail = OUR_SIDE
    retryable = False
    retry_after: int | None = None

    def __init__(self, detail: str | None = None, *, log_message: str | None = None, fields: Sequence[str] = (), reason: str | None = None) -> None:
        self.detail = detail or type(self).detail
        self.log_message = log_message
        self.fields = list(fields)
        self.reason = reason
        super().__init__(log_message or self.code)


class InvalidRequestError(AppError):
    status, code, title = 400, "INVALID_ARGUMENT", "Invalid request"
    detail = "Some of the request values aren't valid."


class UnauthorizedError(AppError):
    status, code, title = 401, "UNAUTHORIZED", "Authentication required"
    detail = "Your session has ended. Sign in again to continue."


class NotFoundError(AppError):
    status, code, title = 404, "NOT_FOUND", "Not found"
    detail = "We couldn't find that import."


class FileNotUploadedError(AppError):
    status, code, title, retryable = 409, "FILE_NOT_UPLOADED", "File not uploaded yet", True
    detail = "Your file is still uploading. Try again in a moment."


class ScanPendingError(AppError):
    status, code, title, retryable, retry_after = 409, "SCAN_PENDING", "Checking your file", True, 2
    detail = "Checking your file…"


class ImportEndedError(AppError):
    status, code, title = 409, "IMPORT_ENDED", "Import already ended"
    detail = "This upload has already been processed. Open it from the Statements tab."


class ImportNotOpenError(AppError):
    status, code, title = 409, "IMPORT_NOT_OPEN", "Import not open"
    detail = "This upload can't be changed any more. Open it from the Statements tab."


class ImportImportingError(AppError):
    status, code, title = 409, "IMPORT_IMPORTING", "Import in progress"
    detail = "Your transactions are being imported and can't be cancelled now."


class OverlapNotCheckedError(AppError):
    status, code, title = 409, "OVERLAP_NOT_CHECKED", "Couldn't check for transactions you already have"
    detail = "We couldn't check for transactions you already have. Tick 'Import anyway' to continue."


class InvalidProfileError(AppError):
    status, code, title = 422, "INVALID_PROFILE", "Settings need fixing"
    detail = "Some settings need fixing before these transactions can be imported."


class NoRowsSelectedError(AppError):
    status, code, title = 422, "NO_ROWS_SELECTED", "No transactions selected"
    detail = "Choose at least one transaction to import."


class UnsupportedFileForImportError(AppError):
    status, code, title = 422, "UNSUPPORTED_FORMAT", "Unsupported file"
    detail = "Upload a CSV or Excel file downloaded from your bank."


class UnsupportedAccountError(AppError):
    status, code, title = 422, "UNSUPPORTED_ACCOUNT_TYPE", "Unsupported account"
    detail = "Cash accounts don't have bank exports. Add cash transactions by hand."


class DependencyUnavailableError(AppError):
    status, code, title, retryable = 503, "PIPELINE_ERROR", "Temporarily unavailable", True
