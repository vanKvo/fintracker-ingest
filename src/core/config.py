"""Settings, read from the environment on every use so a change needs no code (IN-IMP Appendix A,
IN-FMT Appendix F).

__author__ = "Van Vo"
"""

from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def imports_table() -> str:
    return os.environ.get("IMPORTS_TABLE", "FinTracker_Imports")


def profiles_table() -> str:
    return os.environ.get("PROFILES_TABLE", "FinTracker_FormatProfiles")


def statement_bucket() -> str:
    return os.environ["STATEMENT_BUCKET"]


def malware_scan_required() -> bool:
    """IN-IMP-03: off until anyone other than the owner uploads."""
    return os.environ.get("MALWARE_SCAN_REQUIRED", "false").strip().lower() == "true"


def max_file_bytes() -> int:
    return _int("MAX_FILE_BYTES", 25 * 1024 * 1024)


def max_data_rows() -> int:
    return _int("MAX_DATA_ROWS", 5000)


def preview_expiry_minutes() -> int:
    return _int("PREVIEW_EXPIRY_MINUTES", 30)


def scan_timeout_minutes() -> int:
    return _int("SCAN_TIMEOUT_MINUTES", 15)


def importing_timeout_minutes() -> int:
    return _int("IMPORTING_TIMEOUT_MINUTES", 5)


def promotion_min_users() -> int:
    return _int("PROMOTION_MIN_USERS", 3)


def promotion_min_agreement() -> float:
    return float(os.environ.get("PROMOTION_MIN_AGREEMENT") or 0.8)


def promotion_window_days() -> int:
    return _int("PROMOTION_WINDOW_DAYS", 30)


def promotion_topic_arn() -> str | None:
    return os.environ.get("PROMOTION_TOPIC_ARN") or None
