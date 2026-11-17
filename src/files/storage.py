"""Uploaded statement files and their malware scan result (IN-IMP-01, IN-IMP-03).

The Ledger issues the upload URL and names the key; this service only reads.

__author__ = "Van Vo"
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from ..core import config
from ..core.exceptions import DependencyUnavailableError

SCAN_TAG = "GuardDutyMalwareScanStatus"
CLEAN = "NO_THREATS_FOUND"
_MISSING = {"NoSuchKey", "404", "NotFound"}


def _s3() -> Any:  # boto3 client (untyped library)
    return boto3.client("s3")


def get_file(key: str) -> bytes | None:
    """The file's bytes, or None when it isn't in the bucket yet."""
    try:
        return _s3().get_object(Bucket=config.statement_bucket(), Key=key)["Body"].read()  # type: ignore[no-any-return]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _MISSING:
            return None
        raise DependencyUnavailableError(log_message="s3 get_object failed") from None
    except BotoCoreError:
        raise DependencyUnavailableError(log_message="s3 unreachable") from None


def scan_status(key: str) -> str | None:
    """GuardDuty's tag value, or None when the scan hasn't finished."""
    try:
        tags = _s3().get_object_tagging(Bucket=config.statement_bucket(), Key=key)["TagSet"]
    except (ClientError, BotoCoreError):
        raise DependencyUnavailableError(log_message="s3 get_object_tagging failed") from None
    return next((t["Value"] for t in tags if t["Key"] == SCAN_TAG), None)
