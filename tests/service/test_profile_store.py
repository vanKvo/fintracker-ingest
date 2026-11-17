"""IN-FMT-02 (failure), IN-FMT-06 to IN-FMT-10: stored profiles, votes, promotion, deletion and seeds.

__author__ = "Van Vo"
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import boto3
import pytest

from tests.service.conftest import U, CHASE_CARD_CSV, PROFILES_TABLE, STATEMENT, USER, Clock, FakeLedger, call, put_file, start, statement

BASE = "/api/v1/ingest/imports"
SEED = Path(__file__).resolve().parents[2] / "seed" / "format_profiles.json"


def confirm_as(ledger: FakeLedger, user: str, statement_id: str, profile_change: dict | None = None) -> dict:  # type: ignore[type-arg]
    ledger.statements[statement_id] = statement(statementId=statement_id, userId=user, s3Key=f"statements/{statement_id}.csv")
    put_file(CHASE_CARD_CSV, key=f"statements/{statement_id}.csv")
    _, body, _ = call("POST", BASE, {"statementId": statement_id}, user=user)
    profile = dict(body["profile"], **(profile_change or {}))
    _, done, _ = call("POST", f"{BASE}/{statement_id}/confirm", {"profile": profile}, user=user)
    return done


def items() -> list[dict]:  # type: ignore[type-arg]
    return boto3.resource("dynamodb").Table(PROFILES_TABLE).scan()["Items"]


def sid(n: int) -> str:
    return f"{n:08d}-0000-0000-0000-000000000000"


def load_seed() -> None:
    from scripts.load_seed_profiles import main

    main([str(SEED)])


# --- IN-FMT-02 (failure) and IN-FMT-07 ---

def test_in_fmt_07_confirmation_saves_the_users_profile_for_them_only(ledger: FakeLedger) -> None:
    """IN-FMT-07 confirmation saves the user's profile: user A's correction is proposed to A, not to B."""
    confirm_as(ledger, U("user-a"), sid(1), {"signConvention": "EXPENSE_POSITIVE"})
    put_file(CHASE_CARD_CSV, key=f"statements/{sid(2)}.csv")
    ledger.statements[sid(2)] = statement(statementId=sid(2), userId=U("user-a"), s3Key=f"statements/{sid(2)}.csv")
    _, mine, _ = call("POST", BASE, {"statementId": sid(2)}, user=U("user-a"))
    assert mine["profileSource"] == "USER" and mine["profile"]["signConvention"] == "EXPENSE_POSITIVE"
    ledger.statements[sid(3)] = statement(statementId=sid(3), userId=U("user-b"), s3Key=f"statements/{sid(2)}.csv")
    _, theirs, _ = call("POST", BASE, {"statementId": sid(3)}, user=U("user-b"))
    assert theirs["profileSource"] == "INFERRED" and theirs["profile"]["signConvention"] == "EXPENSE_NEGATIVE"


def test_in_fmt_07_one_vote_per_user_per_layout(ledger: FakeLedger) -> None:
    """IN-FMT-07 confirmation saves a vote: an unchanged proposal still votes; a later vote replaces the earlier one."""
    confirm_as(ledger, U("user-a"), sid(1))
    confirm_as(ledger, U("user-a"), sid(2), {"signConvention": "EXPENSE_POSITIVE"})
    votes = [i for i in items() if i["PK"].startswith("VOTE#")]
    assert len(votes) == 1


def test_in_fmt_02_and_07_profile_store_down_never_blocks_an_import(ledger: FakeLedger, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """IN-FMT-02 proposal fails over to a guess and IN-FMT-07 a lost vote is logged; the import completes."""
    monkeypatch.setenv("PROFILES_TABLE", "missing-table")
    put_file(CHASE_CARD_CSV)
    with caplog.at_level(logging.WARNING):
        _, body, _ = call("POST", BASE, {"statementId": STATEMENT})
        assert body["profileSource"] == "INFERRED"
        _, done, _ = call("POST", f"{BASE}/{STATEMENT}/confirm", {"profile": body["profile"]})
    assert done["status"] == "COMPLETED"
    assert any("PROFILE_SAVE_FAILED" in r.getMessage() for r in caplog.records)


# --- IN-FMT-06: format change ---

def test_in_fmt_06_new_layout_of_a_known_bank_raises_the_alarm_once_a_day(ledger: FakeLedger, caplog: pytest.LogCaptureFixture) -> None:
    """IN-FMT-06 format change: a known bank's unknown layout logs BANK_FORMAT_CHANGED once a day, without headers."""
    load_seed()
    changed = CHASE_CARD_CSV.replace(",Memo\n", ",Notes\n", 1)
    with caplog.at_level(logging.WARNING):
        start(changed)
        ledger.statements[sid(9)] = statement(statementId=sid(9), s3Key=f"statements/{STATEMENT}.csv")
        call("POST", BASE, {"statementId": sid(9)})
    alarms = [r for r in caplog.records if r.getMessage() == "BANK_FORMAT_CHANGED"]
    assert len(alarms) == 1 and "Notes" not in str(alarms[0].__dict__)


def test_in_fmt_06_unknown_bank_raises_nothing(ledger: FakeLedger, caplog: pytest.LogCaptureFixture) -> None:
    """IN-FMT-06 format change: a bank with no shared default at all raises nothing."""
    ledger.statements[STATEMENT] = statement(bankId="other")
    with caplog.at_level(logging.WARNING):
        start()
    assert not [r for r in caplog.records if r.getMessage() == "BANK_FORMAT_CHANGED"]


def test_in_fmt_06_changed_proposals_are_counted(ledger: FakeLedger) -> None:
    """IN-FMT-06 format change: confirmations and changed proposals are counted per bank and day."""
    confirm_as(ledger, U("user-a"), sid(1))
    confirm_as(ledger, U("user-b"), sid(2), {"signConvention": "EXPENSE_POSITIVE"})
    [stats] = [i for i in items() if i["PK"] == "STATS#chase"]
    assert (stats["confirmations"], stats["changed"]) == (2, 1)


# --- IN-FMT-08: promotion ---

def promotion_notices() -> list[dict]:  # type: ignore[type-arg]
    return [i for i in items() if i["SK"].startswith("PROMOTION_NOTICE#")]


def test_in_fmt_08_three_users_agreeing_notify_the_owner_once(ledger: FakeLedger) -> None:
    """IN-FMT-08 promotion: 3 different users agreeing notify the owner once."""
    for n, user in enumerate((U("user-a"), U("user-b"), U("user-c"), U("user-d")), start=1):
        confirm_as(ledger, user, sid(n), {"signConvention": "EXPENSE_POSITIVE"})
    assert len(promotion_notices()) == 1


def test_in_fmt_08_one_user_ten_times_never_qualifies(ledger: FakeLedger) -> None:
    """IN-FMT-08 promotion: one user confirming 10 times is one vote."""
    for n in range(1, 11):
        confirm_as(ledger, U("user-a"), sid(n))
    assert promotion_notices() == []


def test_in_fmt_08_split_votes_do_not_qualify(ledger: FakeLedger) -> None:
    """IN-FMT-08 promotion: 3 votes for one profile and 2 for another (60%) don't qualify."""
    for n, user in enumerate((U("user-d"), U("user-e")), start=4):
        confirm_as(ledger, user, sid(n), {"signConvention": "EXPENSE_POSITIVE"})
    for n, user in enumerate((U("user-a"), U("user-b"), U("user-c")), start=1):
        confirm_as(ledger, user, sid(n))
    assert promotion_notices() == []


def test_in_fmt_08_votes_outside_the_window_do_not_count(ledger: FakeLedger, clock: Clock) -> None:
    """IN-FMT-08 promotion: a vote older than 30 days doesn't count."""
    confirm_as(ledger, U("user-a"), sid(1))
    clock.advance(days=35)
    confirm_as(ledger, U("user-b"), sid(2))
    confirm_as(ledger, U("user-c"), sid(3))
    assert promotion_notices() == []


def test_in_fmt_08_thresholds_are_settings(ledger: FakeLedger, monkeypatch: pytest.MonkeyPatch) -> None:
    """IN-FMT-08 promotion: changing a threshold is a setting, not code."""
    monkeypatch.setenv("PROMOTION_MIN_USERS", "2")
    confirm_as(ledger, U("user-a"), sid(1))
    confirm_as(ledger, U("user-b"), sid(2))
    assert len(promotion_notices()) == 1


def test_in_fmt_08_script_promotes_and_the_next_user_gets_the_default(ledger: FakeLedger) -> None:
    """IN-FMT-08 promotion: the owner's script promotes the profile; the next user is proposed it."""
    from scripts.promote_profile import main

    for n, user in enumerate((U("user-a"), U("user-b"), U("user-c")), start=1):
        confirm_as(ledger, user, sid(n), {"signConvention": "EXPENSE_POSITIVE"})
    [notice] = promotion_notices()
    signature, profile_hash = notice["SK"].split("#")[1:3]
    assert main(["--bank", "chase", "--account-class", "CREDIT", "--signature", signature, "--profile-hash", profile_hash, "--by", "owner"]) == 0
    ledger.statements[sid(7)] = statement(statementId=sid(7), userId=U("user-z"), s3Key=f"statements/{sid(1)}.csv")
    _, body, _ = call("POST", BASE, {"statementId": sid(7)}, user=U("user-z"))
    assert body["profileSource"] == "BASELINE" and body["profile"]["signConvention"] == "EXPENSE_POSITIVE"


def test_in_fmt_08_script_refuses_an_unusable_profile(aws: None) -> None:
    """IN-FMT-08 promotion: a profile with no date column is refused by the script."""
    from scripts.promote_profile import promote_profile_dict

    with pytest.raises(ValueError):
        promote_profile_dict("chase", "CREDIT", "sig", {"columns": {"description": "Description", "amount": "Amount"},
                                                        "amountMode": "SIGNED", "signConvention": "EXPENSE_NEGATIVE", "dateFormat": "MDY"},
                             ["Description", "Amount"], by="owner")


# --- IN-FMT-09: deletion ---

def test_in_fmt_09_deleting_a_user_removes_their_profiles_and_votes_only(ledger: FakeLedger) -> None:
    """IN-FMT-09 deletion: a deleted user's profiles and votes are gone; shared defaults stay."""
    from src.profiles.deletion_handler import handler

    load_seed()
    confirm_as(ledger, USER, sid(1), {"signConvention": "EXPENSE_POSITIVE"})
    confirm_as(ledger, U("user-b"), sid(2))
    handler({"detail-type": "UserAccountDeleted", "detail": {"userId": USER}}, None)
    assert not [i for i in items() if USER in json.dumps(i, default=str)]
    assert [i for i in items() if i["SK"].startswith("BASELINE#")]
    assert [i for i in items() if U("user-b") in json.dumps(i, default=str)]


# --- IN-FMT-10: seeds ---

def test_in_fmt_10_seeds_load_and_chase_card_is_proposed_as_verified_default(ledger: FakeLedger) -> None:
    """IN-FMT-10 seed baselines: seeds load, and Chase's card layout is proposed as a verified default."""
    load_seed()
    _, body, _ = start()
    assert body["profileSource"] == "BASELINE" and body["unconfirmedFields"] == []


def test_in_fmt_10_capital_one_seed_reads_debit_and_credit(ledger: FakeLedger) -> None:
    """IN-FMT-10 seed baselines: the Capital One 360 Checking default reads every Debit as money out and Credit as money in."""
    load_seed()
    ledger.statements[STATEMENT] = statement(accountType="CHECKING", bankId="capital_one")
    text = ("Account Number,Transaction Description,Transaction Date,Transaction Type,Transaction Amount,Balance\n"
            "8483,Monthly Interest Paid,11/15/26,Credit,0.42,500.00\n8483,Withdrawal from REMITLY,11/14/26,Debit,100.00,499.58\n")
    _, body, _ = start(text)
    assert body["profileSource"] == "BASELINE"
    assert {r["description"]: r["direction"] for r in body["rows"]} == {"Monthly Interest Paid": "CREDIT", "Withdrawal from REMITLY": "DEBIT"}


def test_in_fmt_10_unverified_seed_marks_sign_and_date_for_checking(ledger: FakeLedger) -> None:
    """IN-FMT-10 seed baselines: an unverified default marks its sign and date format for the user to check."""
    load_seed()
    ledger.statements[STATEMENT] = statement(accountType="CHECKING", bankId="bank_of_america")
    _, body, _ = start("Date,Description,Amount,Running Bal.\n01/15/2026,SHOP,-5.00,100.00\n")
    assert body["profileSource"] == "BASELINE" and set(body["unconfirmedFields"]) == {"signConvention", "dateFormat"}


def test_in_fmt_10_invalid_seed_stops_the_loader(aws: None, tmp_path: Path) -> None:
    """IN-FMT-10 seed baselines: a default that isn't usable stops the loader."""
    from scripts.load_seed_profiles import main

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"bankId": "x", "accountClass": "CREDIT", "headers": ["A", "B"], "verified": False,
                                "profile": {"columns": {"date": "A"}, "amountMode": "SIGNED", "dateFormat": "MDY"}}]))
    with pytest.raises(SystemExit):
        main([str(bad)])
