"""The caller's internal user ID (invariant 2).

Deployed: read only from the identity authorizer's context on the HTTP API event
(requestContext.authorizer.lambda.internal_user_id). Headers, query strings and bodies are never
read for identity. Local: LOCAL_DEV_USER_ID, only when APP_ENV=local; startup fails if it is set
anywhere else.

__author__ = "Van Vo"
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from fastapi import Request

from .exceptions import UnauthorizedError


def _child(node: object, key: str) -> object:
    return node.get(key) if isinstance(node, Mapping) else None


def user_id_from_event(event: object) -> str | None:
    value = _child(_child(_child(_child(event, "requestContext"), "authorizer"), "lambda"), "internal_user_id")
    return value if isinstance(value, str) and value.strip() else None


def assert_local_identity_safe() -> None:
    if os.environ.get("LOCAL_DEV_USER_ID") and os.environ.get("APP_ENV") != "local":
        raise RuntimeError("LOCAL_DEV_USER_ID is only allowed when APP_ENV=local.")


async def get_user_id(request: Request) -> str:
    user_id = user_id_from_event(request.scope.get("aws.event"))
    if user_id is None and os.environ.get("APP_ENV") == "local":
        user_id = os.environ.get("LOCAL_DEV_USER_ID") or None
    if user_id is None:
        raise UnauthorizedError(log_message="no authorizer user")
    return user_id
