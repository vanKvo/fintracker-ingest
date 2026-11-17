"""DynamoDB access for format profiles (IN-FMT-02, IN-FMT-06 to IN-FMT-10, Appendix F).

One user's confirmation changes only that user's profile; shared defaults change only by promotion
or the seed. Reading or saving here never blocks an import: callers fall back and log.

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from ..core import clock, config
from ..core.observability import logger, metric
from . import codec
from .promotion import Vote, qualifying_hash
from .schemas import AccountClass, Baseline, Profile

VOTES_INDEX = "user-votes"
_DAY_TTL = 10 * 24 * 3600


@dataclass(frozen=True)
class StoredBaseline:
    signature: str
    profile: Profile
    verified: bool


def _table() -> Any:  # boto3 Table (untyped library)
    return boto3.resource("dynamodb").Table(config.profiles_table())


def create_table() -> None:
    boto3.client("dynamodb").create_table(
        TableName=config.profiles_table(), BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": n, "AttributeType": "S"} for n in ("PK", "SK", "voterUserId")],
        KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}, {"AttributeName": "SK", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[{
            "IndexName": VOTES_INDEX, "KeySchema": [{"AttributeName": "voterUserId", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "KEYS_ONLY"},
        }],
    )


def _bank_pk(bank_id: str, account_class: AccountClass | str) -> str:
    return f"BANK#{bank_id}#{account_class}"


def _key(bank_id: str, account_class: AccountClass | str, signature: str) -> str:
    return f"{bank_id}#{account_class}#{signature}"


def _query_all(**kwargs: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while True:
        page = _table().query(**kwargs)
        items.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


# --- reading (IN-FMT-02) ---

def list_baselines(bank_id: str, account_class: AccountClass) -> list[StoredBaseline]:
    items = _query_all(KeyConditionExpression=Key("PK").eq(_bank_pk(bank_id, account_class)) & Key("SK").begins_with("BASELINE#"))
    return [StoredBaseline(i["SK"].split("#", 1)[1], codec.from_dict(json.loads(i["profile"])), bool(i.get("verified")))
            for i in items]


def get_user_profile(user_id: str, bank_id: str, account_class: AccountClass, signature: str) -> Profile | None:
    item = _table().get_item(Key={"PK": f"USER#{user_id}", "SK": f"PROFILE#{_key(bank_id, account_class, signature)}"}).get("Item")
    return codec.from_dict(json.loads(item["profile"])) if item else None


def baselines_for_proposal(stored: Sequence[StoredBaseline]) -> list[Baseline]:
    return [Baseline(b.signature, b.profile) for b in stored]


# --- format change (IN-FMT-06) ---

def note_layout(bank_id: str, account_class: AccountClass, signature: str, stored: Sequence[StoredBaseline]) -> None:
    """BANK_FORMAT_CHANGED once a day per layout, when the bank has defaults and none matches."""
    if not stored or any(b.signature == signature for b in stored):
        return
    day = clock.now().date().isoformat()
    try:
        _table().put_item(
            Item={"PK": f"FORMAT_ALARM#{_key(bank_id, account_class, signature)}", "SK": f"DAY#{day}",
                  "ttl": int(clock.now().timestamp()) + 2 * 24 * 3600},
            ConditionExpression="attribute_not_exists(PK)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return
        raise
    logger.warning("BANK_FORMAT_CHANGED", bank_id=bank_id, account_class=str(account_class), signature=signature)


# --- confirmation, votes and promotion (IN-FMT-06, -07, -08) ---

def save_confirmation(user_id: str, bank_id: str, account_class: AccountClass, signature: str, headers: Sequence[str],
                      confirmed: Profile, proposed: Profile | None) -> None:
    now = clock.now()
    profile_json = json.dumps(codec.to_dict(confirmed), sort_keys=True)
    profile_hash = codec.profile_hash(confirmed)
    key = _key(bank_id, account_class, signature)
    table = _table()
    table.put_item(Item={"PK": f"USER#{user_id}", "SK": f"PROFILE#{key}", "profile": profile_json, "confirmedAt": clock.iso(now)})
    table.put_item(Item={"PK": f"VOTE#{key}", "SK": f"USER#{user_id}", "profileHash": profile_hash,
                         "confirmedAt": clock.iso(now), "voterUserId": user_id})

    changed = proposed is not None and codec.to_dict(proposed) != codec.to_dict(confirmed)
    table.update_item(
        Key={"PK": f"STATS#{bank_id}", "SK": f"DAY#{now.date().isoformat()}"},
        UpdateExpression="ADD confirmations :one, changed :changed SET #ttl = :ttl",
        ExpressionAttributeNames={"#ttl": "ttl"},
        ExpressionAttributeValues={":one": 1, ":changed": 1 if changed else 0, ":ttl": int(now.timestamp()) + _DAY_TTL})
    # Per bank for dashboards; service-wide totals feed the IN-FMT-06 alarm (an alarm can't enumerate banks).
    metric("ProposalConfirmations", bank=bank_id)
    metric("ProposalConfirmations")
    if changed:
        metric("ProposalChanged", bank=bank_id)
        metric("ProposalChanged")

    _check_promotion(bank_id, account_class, signature, headers, now)


def _check_promotion(bank_id: str, account_class: AccountClass, signature: str, headers: Sequence[str], now: dt.datetime) -> None:
    key = _key(bank_id, account_class, signature)
    votes = [Vote(i["profileHash"], dt.datetime.fromisoformat(i["confirmedAt"]))
             for i in _query_all(KeyConditionExpression=Key("PK").eq(f"VOTE#{key}"))]
    winner = qualifying_hash(votes, now=now, min_users=config.promotion_min_users(),
                             min_agreement=config.promotion_min_agreement(), window_days=config.promotion_window_days())
    if winner is None:
        return
    sample = next(i for i in _query_all(KeyConditionExpression=Key("PK").eq(f"VOTE#{key}")) if i["profileHash"] == winner)
    voter_profile = _table().get_item(Key={"PK": f"USER#{sample['SK'].split('#', 1)[1]}", "SK": f"PROFILE#{key}"}).get("Item")
    try:
        _table().put_item(
            Item={"PK": _bank_pk(bank_id, account_class), "SK": f"PROMOTION_NOTICE#{signature}#{winner}",
                  "notifiedAt": clock.iso(now), "profile": voter_profile["profile"] if voter_profile else "{}",
                  "headers": list(headers), "voteCount": sum(1 for v in votes if v.profile_hash == winner)},
            ConditionExpression="attribute_not_exists(SK)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return
        raise
    logger.info("PROMOTION_QUALIFIED", bank_id=bank_id, account_class=str(account_class), signature=signature, profile_hash=winner)
    topic = config.promotion_topic_arn()
    if topic:
        boto3.client("sns").publish(TopicArn=topic, Subject="FinTracker: a bank layout qualifies for promotion",
                                    Message=json.dumps({"bankId": bank_id, "accountClass": str(account_class),
                                                        "signature": signature, "profileHash": winner}))


def get_promotion_notice(bank_id: str, account_class: str, signature: str, profile_hash: str) -> dict[str, Any] | None:
    item = _table().get_item(Key={"PK": _bank_pk(bank_id, account_class), "SK": f"PROMOTION_NOTICE#{signature}#{profile_hash}"}).get("Item")
    return dict(item) if item else None


def put_baseline(bank_id: str, account_class: str, signature: str, profile: Profile, headers: Sequence[str], *,
                 source: str, by: str, verified: bool, vote_count: int = 0) -> None:
    _table().put_item(Item={
        "PK": _bank_pk(bank_id, account_class), "SK": f"BASELINE#{signature}",
        "profile": json.dumps(codec.to_dict(profile), sort_keys=True), "headers": list(headers),
        "source": source, "promotedAt": clock.iso(clock.now()), "promotedBy": by, "voteCount": vote_count,
        "verified": verified,
    })


# --- deletion (IN-FMT-09) ---

def delete_user_data(user_id: str) -> int:
    """Removes the user's own profiles and votes; shared defaults keep no user IDs."""
    table = _table()
    keys = [{"PK": i["PK"], "SK": i["SK"]} for i in _query_all(KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"))]
    keys += [{"PK": i["PK"], "SK": i["SK"]} for i in _query_all(IndexName=VOTES_INDEX, KeyConditionExpression=Key("voterUserId").eq(user_id))]
    with table.batch_writer() as batch:
        for key in keys:
            batch.delete_item(Key=key)
    return len(keys)
