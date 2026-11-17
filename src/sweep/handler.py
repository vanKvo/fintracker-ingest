"""The cleanup job (IN-IMP-08): every 15 minutes, end imports nobody finished.

Imports are picked by age, not by what changed since the last run, so the first run after the
schedule is switched back on ends everything that became overdue while it was off.

__author__ = "Van Vo"
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from ..core import clock, config
from ..core.observability import logger
from ..imports.repository import older_than
from ..imports.service import end_import


async def sweep() -> dict[str, int]:
    now = clock.now()
    rules = (
        ("expired", "PREVIEW_READY", config.preview_expiry_minutes(), "EXPIRED", "IMPORT_EXPIRED"),
        ("scanTimedOut", "SCAN_PENDING", config.scan_timeout_minutes(), "FAILED", "MALWARE_SCAN_FAILED"),
        ("stuck", "IMPORTING", config.importing_timeout_minutes(), "FAILED", "LEDGER_PUSH_FAILED"),
    )
    counts: dict[str, int] = {}
    for name, status, minutes, end_status, reason in rules:
        overdue = older_than(status, clock.iso(now - dt.timedelta(minutes=minutes)))
        for record in overdue:
            if name == "scanTimedOut":
                logger.warning("SCAN_TIMEOUT", import_id=record["importId"])
            await end_import(record, end_status, reason)
        counts[name] = len(overdue)
    logger.info("SWEEP_DONE", extra=dict(counts))
    return counts


def handler(event: Any, context: Any) -> dict[str, int]:
    loop = asyncio.new_event_loop()  # not asyncio.run: it would leave no current loop for the next handler in this process
    try:
        return loop.run_until_complete(sweep())
    except Exception as exc:
        logger.error("SWEEP_FAILED", error_type=type(exc).__name__)
        raise
    finally:
        loop.close()
