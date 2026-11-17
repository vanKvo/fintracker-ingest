"""IN-FMT-09: on UserAccountDeleted (XS-DEL), delete the user's own profiles and votes.

The event comes from the account-deletion flow on EventBridge; the user ID in it is the internal ID
the User profile service published, never one a client sent.

__author__ = "Van Vo"
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..core.observability import logger
from .store import delete_user_data


def handler(event: Any, context: Any) -> dict[str, int]:
    detail = event.get("detail") if isinstance(event, Mapping) else None
    user_id = detail.get("userId") if isinstance(detail, Mapping) else None
    if not isinstance(user_id, str) or not user_id.strip():
        logger.error("USER_DELETION_EVENT_INVALID")
        raise ValueError("UserAccountDeleted event without a userId")
    deleted = delete_user_data(user_id)
    logger.info("USER_PROFILES_DELETED", deleted=deleted)
    return {"deleted": deleted}
