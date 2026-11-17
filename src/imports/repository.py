"""DynamoDB access for import records (IN-IMP Appendix B).

Status changes are conditional, so an import can't be confirmed twice and a finished import can't
be reopened.

__author__ = "Van Vo"
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any, cast

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..core import config
from .models import ImportItem

STATUS_INDEX = "status-updatedAt"


def _table() -> Any:  # boto3 Table (untyped library)
    return boto3.resource("dynamodb").Table(config.imports_table())


def create_table() -> None:
    """Local and test setup; Terraform creates the deployed table with the same shape."""
    boto3.client("dynamodb").create_table(
        TableName=config.imports_table(), BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("importId", "status", "updatedAt")],
        KeySchema=[{"AttributeName": "importId", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[{
            "IndexName": STATUS_INDEX,
            "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}, {"AttributeName": "updatedAt", "KeyType": "RANGE"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
    )


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def get(import_id: str) -> ImportItem | None:
    item = _table().get_item(Key={"importId": import_id}, ConsistentRead=True).get("Item")
    return cast(ImportItem, _plain(item)) if item else None


def create(item: ImportItem) -> bool:
    """False when an import for this statement already exists."""
    try:
        _table().put_item(Item=dict(item), ConditionExpression="attribute_not_exists(importId)")
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def update(import_id: str, changes: dict[str, Any], *, only_if_status: Iterable[str] | None = None) -> bool:
    """Set `changes`. With `only_if_status`, only when the current status is one of them; False otherwise."""
    names = {f"#k{i}": k for i, k in enumerate(changes)}
    values: dict[str, Any] = {f":v{i}": v for i, v in enumerate(changes.values())}
    expression = "SET " + ", ".join(f"#k{i} = :v{i}" for i in range(len(changes)))
    kwargs: dict[str, Any] = {"Key": {"importId": import_id}, "UpdateExpression": expression,
                              "ExpressionAttributeNames": names, "ExpressionAttributeValues": values}
    if only_if_status is not None:
        allowed = list(only_if_status)
        names["#status"] = "status"
        values.update({f":s{i}": s for i, s in enumerate(allowed)})
        kwargs["ConditionExpression"] = "#status IN (" + ", ".join(f":s{i}" for i in range(len(allowed))) + ")"
    try:
        _table().update_item(**kwargs)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def older_than(status: str, cutoff_iso: str) -> list[ImportItem]:
    """Imports in `status` whose last change is before `cutoff_iso` (the cleanup job, IN-IMP-08)."""
    items: list[ImportItem] = []
    kwargs: dict[str, Any] = {"IndexName": STATUS_INDEX,
                              "KeyConditionExpression": Key("status").eq(status) & Key("updatedAt").lt(cutoff_iso)}
    while True:
        page = _table().query(**kwargs)
        items.extend(cast(ImportItem, _plain(i)) for i in page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
