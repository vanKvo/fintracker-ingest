"""IN-FMT: format profiles — key, proposal, inference, validation, direction and type.

Bank layouts below are synthetic copies of real export headers; no real statement data.

__author__ = "Van Vo"
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from decimal import Decimal

import pytest

from src.core.exceptions import UnsupportedAccountTypeError
from src.profiles.schemas import (
    AccountClass, AmountMode, Baseline, Columns, DateFormat, HouseholdAccount, ImportContext, Profile, SignConvention,
)
from src.profiles.service import account_class_for, apply_profile, choose_proposal, infer_profile, profile_key, validate_profile
from src.readers.service import read_file

TODAY = dt.date(2026, 11, 16)

CHASE_CARD = (
    "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
    "01/03/2026,01/04/2026,STARBUCKS #12345,Food & Drink,Sale,-5.75,\n"
    "01/05/2026,01/05/2026,WHOLEFDS MKT,Groceries,Sale,-82.10,\n"
    "01/09/2026,01/09/2026,Payment Thank You-Mobile,,Payment,500.00,\n"
    "01/10/2026,01/11/2026,AMAZON RETURN,Shopping,Return,25.00,\n"
)
CHASE_CHECKING = (
    "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
    "DEBIT,01/15/2026,LOAN PAYMENT,-500.00,LOAN_PMT,1000.00,\n"
    "CREDIT,01/16/2026,ACME PAYROLL,1500.00,ACH_CREDIT,2500.00,\n"
    "DEBIT,01/17/2026,BANK FEE,-3.00,Interest Charged Weird,2497.00,\n"
)
CAPITAL_ONE = (
    "Account Number,Transaction Description,Transaction Date,Transaction Type,Transaction Amount,Balance\n"
    "8483,Deposit from 360 Performance Savings XXXXXXX1234,11/16/26,Credit,200.00,700.00\n"
    "8483,Monthly Interest Paid,11/15/26,Credit,0.42,500.00\n"
    "8483,Withdrawal from REMITLY INC REMITTANCE,11/14/26,Debit,100.00,499.58\n"
    "8483,Withdrawal from CHASE CREDIT CRD EPAY,11/13/26,Debit,300.00,599.58\n"
    "8483,Withdrawal from FID BKG SVC LLC MONEYLINE,11/12/26,Debit,50.00,899.58\n"
    "8483,Zelle money received from Alex Doe,11/11/26,Credit,60.00,949.58\n"
    "8483,Deposit from ACME PAYROLL,11/10/26,Credit,1500.00,889.58\n"
)

CHASE_CARD_PROFILE = Profile(
    columns=Columns(date="Transaction Date", description="Description", amount="Amount", type="Type", category="Category"),
    amount_mode=AmountMode.SIGNED, sign_convention=SignConvention.EXPENSE_NEGATIVE, date_format=DateFormat.MDY,
)
CHASE_CHECKING_PROFILE = Profile(
    columns=Columns(date="Posting Date", description="Description", amount="Amount", type="Type"),
    amount_mode=AmountMode.SIGNED, sign_convention=SignConvention.EXPENSE_NEGATIVE, date_format=DateFormat.MDY,
)


def ctx(account_class: AccountClass, *household: HouseholdAccount, bank: str = "chase", available: bool = True) -> ImportContext:
    return ImportContext(bank_id=bank, account_class=account_class, account_id="own", household=tuple(household) if available else None, today=TODAY)


def table(text: str):  # type: ignore[no-untyped-def]
    return read_file("x.csv", text.encode())


def rows_by_description(text: str, profile: Profile, context: ImportContext):  # type: ignore[no-untyped-def]
    return {r.description: r for r in apply_profile(table(text), profile, context).rows}


def capital_one(context: ImportContext):  # type: ignore[no-untyped-def]
    t = table(CAPITAL_ONE)
    return {r.description: r for r in apply_profile(t, infer_profile(t).profile, context).rows}


# --- IN-FMT-01: profile key ---

def test_in_fmt_01_checking_and_card_layouts_have_different_keys() -> None:
    """IN-FMT-01 profile key: bank + account class + header signature."""
    card = profile_key("chase", AccountClass.CREDIT, table(CHASE_CARD).headers)
    checking = profile_key("chase", AccountClass.DEPOSIT, table(CHASE_CHECKING).headers)
    assert card != checking


def test_in_fmt_01_signature_ignores_order_and_case_but_not_columns() -> None:
    """IN-FMT-01 profile key: column order and case don't change the signature; a new column does."""
    a = profile_key("chase", AccountClass.CREDIT, ["Transaction Date", "Description", "Amount"])
    b = profile_key("chase", AccountClass.CREDIT, ["amount", "transaction date", "DESCRIPTION"])
    c = profile_key("chase", AccountClass.CREDIT, ["Transaction Date", "Description", "Amount", "Memo"])
    assert a == b and a != c


@pytest.mark.parametrize("account_type,expected", [("CHECKING", AccountClass.DEPOSIT), ("SAVINGS", AccountClass.DEPOSIT), ("CREDIT", AccountClass.CREDIT)])
def test_in_fmt_01_account_class(account_type: str, expected: AccountClass) -> None:
    """IN-FMT-01 profile key: checking and savings are DEPOSIT, credit cards CREDIT."""
    assert account_class_for(account_type) == expected


def test_in_fmt_01_cash_account_is_refused() -> None:
    """IN-FMT-01 profile key: a cash account has no bank export (UNSUPPORTED_ACCOUNT_TYPE)."""
    with pytest.raises(UnsupportedAccountTypeError):
        account_class_for("CASH")


# --- IN-FMT-02: proposal order ---

def test_in_fmt_02_user_profile_first_with_baseline_differences() -> None:
    """IN-FMT-02 proposal order: the user's own profile wins, and differences from the baseline are named."""
    t = table(CHASE_CARD)
    sig = profile_key("chase", AccountClass.CREDIT, t.headers)[2]
    mine = dataclasses.replace(CHASE_CARD_PROFILE, columns=dataclasses.replace(CHASE_CARD_PROFILE.columns, date="Post Date"))
    proposal = choose_proposal(t, mine, [Baseline(sig, CHASE_CARD_PROFILE)])
    assert proposal.source == "USER" and proposal.profile == mine
    assert proposal.baseline_differences == {"columns.date": "Transaction Date"}


def test_in_fmt_02_baseline_when_user_has_none() -> None:
    """IN-FMT-02 proposal order: with no profile of their own, the user gets the baseline."""
    t = table(CHASE_CARD)
    sig = profile_key("chase", AccountClass.CREDIT, t.headers)[2]
    proposal = choose_proposal(t, None, [Baseline(sig, CHASE_CARD_PROFILE)])
    assert proposal.source == "BASELINE" and proposal.profile == CHASE_CARD_PROFILE


def test_in_fmt_02_nearest_baseline_needs_its_columns_in_the_file() -> None:
    """IN-FMT-02 proposal order: a baseline of another signature is used only when its columns exist in the file."""
    t = table(CHASE_CARD.replace(",Memo\n", ",Notes\n", 1))
    proposal = choose_proposal(t, None, [Baseline("other-signature", CHASE_CARD_PROFILE)])
    assert proposal.source == "NEAREST_BASELINE"
    unrelated = Profile(columns=Columns(date="Booking Day", description="Text", amount="Sum"),
                        amount_mode=AmountMode.SIGNED, sign_convention=SignConvention.EXPENSE_NEGATIVE, date_format=DateFormat.MDY)
    assert choose_proposal(t, None, [Baseline("other", unrelated)]).source == "INFERRED"


# --- IN-FMT-03: inference ---

def test_in_fmt_03_split_columns() -> None:
    """IN-FMT-03 inference: separate debit and credit columns are inferred SPLIT."""
    t = table("Date,Memo,Amount Debit,Amount Credit\n01/15/2026,COFFEE,4.50,\n01/16/2026,PAY,,1500.00\n")
    p = infer_profile(t).profile
    assert p.amount_mode == AmountMode.SPLIT
    assert p.columns == Columns(date="Date", description="Memo", debit="Amount Debit", credit="Amount Credit")


def test_in_fmt_03_sign_convention_from_the_majority() -> None:
    """IN-FMT-03 inference: mostly negative amounts are inferred EXPENSE_NEGATIVE."""
    body = "".join(f"01/{d:02d}/2026,SHOP,-{d}.00\n" for d in range(1, 18)) + "01/20/2026,PAY,100.00\n"
    assert infer_profile(table("Date,Description,Amount\n" + body)).profile.sign_convention == SignConvention.EXPENSE_NEGATIVE
    assert infer_profile(table(CAPITAL_ONE.replace("Credit,", "Debit,"))).profile.amount_mode == AmountMode.INDICATOR


def test_in_fmt_03_date_format() -> None:
    """IN-FMT-03 inference: a day over 12 decides DMY; otherwise US month-first, marked unconfirmed."""
    dmy = infer_profile(table("Date,Description,Amount\n13/02/2026,A,-1.00\n03/04/2026,B,-2.00\n"))
    mdy = infer_profile(table("Date,Description,Amount\n03/04/2026,A,-1.00\n"))
    assert dmy.profile.date_format == DateFormat.DMY
    assert mdy.profile.date_format == DateFormat.MDY and "dateFormat" in mdy.unconfirmed


def test_in_fmt_03_capital_one_indicator_column() -> None:
    """IN-FMT-03 inference: a Debit/Credit column is a direction indicator, never a type column."""
    p = infer_profile(table(CAPITAL_ONE)).profile
    assert p.amount_mode == AmountMode.INDICATOR
    assert p.columns.direction == "Transaction Type" and p.columns.amount == "Transaction Amount"
    assert p.columns.type is None and p.columns.date == "Transaction Date" and p.columns.description == "Transaction Description"


def test_in_fmt_03_missing_columns_leave_an_incomplete_profile() -> None:
    """IN-FMT-03 inference: no date or amount column leaves fields to map, and confirming is blocked."""
    t = table("Posted,Text,Value\n01/15/2026,A,-1.00\n")
    inferred = infer_profile(t)
    assert validate_profile(inferred.profile, t.headers)


# --- IN-FMT-04: fields and validation ---

def test_in_fmt_04_seeded_chase_card_profile_validates() -> None:
    """IN-FMT-04 validation: the Chase credit-card profile is valid for Chase's layout."""
    assert validate_profile(CHASE_CARD_PROFILE, table(CHASE_CARD).headers) == []


def test_in_fmt_04_invalid_profile_lists_the_fields_to_fix() -> None:
    """IN-FMT-04 validation: an invalid profile is refused with the fields to fix."""
    bad = Profile(columns=Columns(date="Nope", description="Description", amount="Description"),
                  amount_mode=AmountMode.SIGNED, sign_convention=None, date_format=DateFormat.MDY)
    problems = validate_profile(bad, table(CHASE_CARD).headers)
    assert {"columns.date", "signConvention", "columns.amount"} <= set(problems)


def test_in_fmt_04_split_and_indicator_rows_that_cant_be_read() -> None:
    """IN-FMT-04 validation: a SPLIT row with both or neither value, or an unknown indicator, is unreadable."""
    split = Profile(columns=Columns(date="Date", description="Memo", debit="Debit", credit="Credit"),
                    amount_mode=AmountMode.SPLIT, date_format=DateFormat.MDY)
    applied = apply_profile(table("Date,Memo,Debit,Credit\n01/15/2026,A,1.00,2.00\n01/16/2026,B,,\n01/17/2026,C,3.00,\n"), split, ctx(AccountClass.DEPOSIT))
    assert [r.outcome for r in applied.rows] == ["UNREADABLE", "UNREADABLE", "OK"]
    indicator = infer_profile(table(CAPITAL_ONE)).profile
    odd = apply_profile(table(CAPITAL_ONE.replace("11/14/26,Debit", "11/14/26,Hold")), indicator, ctx(AccountClass.DEPOSIT))
    assert sum(r.outcome == "UNREADABLE" for r in odd.rows) == 1


def test_in_fmt_04_pending_rows_are_skipped_and_counted() -> None:
    """IN-FMT-04 validation: rows whose status is pending are counted as pending, not unreadable."""
    text = "Date,Description,Amount,Status\n01/15/2026,A,-1.00,Pending\n01/16/2026,B,-2.00,Posted\n01/17/2026,C,-3.00,pending\n"
    p = Profile(columns=Columns(date="Date", description="Description", amount="Amount", status="Status"),
                amount_mode=AmountMode.SIGNED, sign_convention=SignConvention.EXPENSE_NEGATIVE, date_format=DateFormat.MDY,
                pending_values=("Pending",))
    applied = apply_profile(table(text), p, ctx(AccountClass.CREDIT))
    assert applied.counts == {"read": 1, "pending": 2, "unreadable": 0}


# --- IN-FMT-05: direction and type ---

def test_in_fmt_05_chase_card_sales_payments_and_returns() -> None:
    """IN-FMT-05 direction and type: card sales are EXPENSE, payments TRANSFER, returns REFUND, none flagged."""
    rows = rows_by_description(CHASE_CARD, CHASE_CARD_PROFILE, ctx(AccountClass.CREDIT))
    assert (rows["STARBUCKS #12345"].direction, rows["STARBUCKS #12345"].tx_type) == ("DEBIT", "EXPENSE")
    assert (rows["Payment Thank You-Mobile"].direction, rows["Payment Thank You-Mobile"].tx_type) == ("CREDIT", "TRANSFER")
    assert (rows["AMAZON RETURN"].direction, rows["AMAZON RETURN"].tx_type) == ("CREDIT", "REFUND")
    assert all(r.review_reason is None for r in rows.values())
    assert rows["STARBUCKS #12345"].amount == Decimal("5.75")


def test_in_fmt_05_checking_loan_payment_is_flagged_expense() -> None:
    """IN-FMT-05 direction and type: a checking payment label is EXPENSE flagged UNCLEAR_TYPE."""
    rows = rows_by_description(CHASE_CHECKING, CHASE_CHECKING_PROFILE, ctx(AccountClass.DEPOSIT))
    assert (rows["LOAN PAYMENT"].tx_type, rows["LOAN PAYMENT"].review_reason) == ("EXPENSE", "UNCLEAR_TYPE")
    assert (rows["ACME PAYROLL"].tx_type, rows["ACME PAYROLL"].review_reason) == ("INCOME", None)


def test_in_fmt_05_split_checking_file() -> None:
    """IN-FMT-05 direction and type: SPLIT debit is EXPENSE and credit INCOME, unflagged."""
    p = Profile(columns=Columns(date="Date", description="Memo", debit="Debit", credit="Credit"),
                amount_mode=AmountMode.SPLIT, date_format=DateFormat.MDY)
    rows = rows_by_description("Date,Memo,Debit,Credit\n01/15/2026,SHOP,42.10,\n01/16/2026,ACME PAYROLL,,\"1,500.00\"\n", p, ctx(AccountClass.DEPOSIT))
    assert (rows["SHOP"].direction, rows["SHOP"].tx_type, rows["SHOP"].review_reason) == ("DEBIT", "EXPENSE", None)
    assert (rows["ACME PAYROLL"].direction, rows["ACME PAYROLL"].tx_type, rows["ACME PAYROLL"].amount) == ("CREDIT", "INCOME", Decimal("1500.00"))


def test_in_fmt_05_card_credit_without_label_is_flagged_transfer() -> None:
    """IN-FMT-05 direction and type: money into a card with no label is TRANSFER flagged, never income."""
    p = Profile(columns=Columns(date="Date", description="Description", amount="Amount"),
                amount_mode=AmountMode.SIGNED, sign_convention=SignConvention.EXPENSE_NEGATIVE, date_format=DateFormat.MDY)
    rows = rows_by_description("Date,Description,Amount\n01/15/2026,SHOP,-10.00\n01/16/2026,THANKS,300.00\n", p, ctx(AccountClass.CREDIT))
    assert (rows["THANKS"].tx_type, rows["THANKS"].review_reason) == ("TRANSFER", "UNCLEAR_TYPE")


def test_in_fmt_05_parentheses_with_expense_positive() -> None:
    """IN-FMT-05 direction and type: (19.99) is negative, so with EXPENSE_POSITIVE it is money in."""
    p = Profile(columns=Columns(date="Date", description="Description", amount="Amount"),
                amount_mode=AmountMode.SIGNED, sign_convention=SignConvention.EXPENSE_POSITIVE, date_format=DateFormat.MDY)
    rows = rows_by_description("Date,Description,Amount\n01/15/2026,REFUND X,(19.99)\n", p, ctx(AccountClass.DEPOSIT))
    assert rows["REFUND X"].direction == "CREDIT" and rows["REFUND X"].amount == Decimal("19.99")


def test_in_fmt_05_unknown_label_falls_back_flagged_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    """IN-FMT-05 direction and type: an unknown label falls back to the direction, flagged and logged by bank and label."""
    with caplog.at_level(logging.WARNING):
        rows = rows_by_description(CHASE_CHECKING, CHASE_CHECKING_PROFILE, ctx(AccountClass.DEPOSIT))
    assert (rows["BANK FEE"].tx_type, rows["BANK FEE"].review_reason) == ("EXPENSE", "UNCLEAR_TYPE")
    assert any(getattr(r, "event", "") == "UNKNOWN_TYPE_LABEL" and getattr(r, "label", "") == "Interest Charged Weird" for r in caplog.records)
    assert not any("BANK FEE" in r.getMessage() for r in caplog.records)


def test_in_fmt_05_label_disagreeing_with_direction_is_flagged() -> None:
    """IN-FMT-05 direction and type: a Return that reads as money out keeps the direction's type, flagged."""
    rows = rows_by_description(CHASE_CARD.replace("Return,25.00", "Return,-25.00"), CHASE_CARD_PROFILE, ctx(AccountClass.CREDIT))
    assert (rows["AMAZON RETURN"].tx_type, rows["AMAZON RETURN"].review_reason) == ("EXPENSE", "UNCLEAR_TYPE")


# --- IN-FMT-12: own accounts by last four ---

SAVINGS_1234 = HouseholdAccount(account_id="sav", account_class=AccountClass.DEPOSIT, last_four="1234", bank_id="capital_one")
CHASE_CARD_8760 = HouseholdAccount(account_id="card", account_class=AccountClass.CREDIT, last_four="8760", bank_id="chase")


def test_in_fmt_12_masked_number_of_a_tracked_account_is_a_transfer() -> None:
    """IN-FMT-12 own accounts by last four: a tracked account's masked number makes the row a TRANSFER, unflagged."""
    rows = capital_one(ctx(AccountClass.DEPOSIT, SAVINGS_1234, bank="capital_one"))
    r = rows["Deposit from 360 Performance Savings XXXXXXX1234"]
    assert (r.direction, r.tx_type, r.review_reason) == ("CREDIT", "TRANSFER", None)


def test_in_fmt_12_ending_in_form_matches_a_card() -> None:
    """IN-FMT-12 own accounts by last four: "ending in 8760" matches the tracked Chase card."""
    p = Profile(columns=Columns(date="Date", description="Description", amount="Amount"),
                amount_mode=AmountMode.SIGNED, sign_convention=SignConvention.EXPENSE_NEGATIVE, date_format=DateFormat.MDY)
    rows = rows_by_description("Date,Description,Amount\n01/15/2026,Payment to Chase card ending in 8760,-500.00\n", p, ctx(AccountClass.DEPOSIT, CHASE_CARD_8760))
    assert (rows["Payment to Chase card ending in 8760"].tx_type, rows["Payment to Chase card ending in 8760"].review_reason) == ("TRANSFER", None)


def test_in_fmt_12_unmatched_or_ambiguous_masked_number_is_a_flagged_transfer() -> None:
    """IN-FMT-12 own accounts by last four: no match, two matches, or no last four stored give a flagged TRANSFER."""
    desc = "Deposit from 360 Performance Savings XXXXXXX1234"
    twin = HouseholdAccount(account_id="sav2", account_class=AccountClass.DEPOSIT, last_four="1234", bank_id=None)
    no_digits = HouseholdAccount(account_id="sav3", account_class=AccountClass.DEPOSIT, last_four=None, bank_id=None)
    for household in ((), (SAVINGS_1234, twin), (no_digits,)):
        r = capital_one(ctx(AccountClass.DEPOSIT, *household, bank="capital_one"))[desc]
        assert (r.tx_type, r.review_reason) == ("TRANSFER", "UNCLEAR_TYPE")


def test_in_fmt_12_statement_own_account_never_matches() -> None:
    """IN-FMT-12 own accounts by last four: the statement's own account isn't a match."""
    own = HouseholdAccount(account_id="own", account_class=AccountClass.DEPOSIT, last_four="1234", bank_id=None)
    r = capital_one(ctx(AccountClass.DEPOSIT, own, bank="capital_one"))["Deposit from 360 Performance Savings XXXXXXX1234"]
    assert r.review_reason == "UNCLEAR_TYPE"


def test_in_fmt_12_payroll_deposit_is_not_a_transfer() -> None:
    """IN-FMT-12 own accounts by last four: "Deposit from" without a masked number stays INCOME."""
    r = capital_one(ctx(AccountClass.DEPOSIT, SAVINGS_1234, bank="capital_one"))["Deposit from ACME PAYROLL"]
    assert (r.tx_type, r.review_reason) == ("INCOME", None)


def test_in_fmt_12_household_unavailable_flags_masked_rows() -> None:
    """IN-FMT-12 own accounts by last four: without the household's accounts, masked rows are flagged transfers."""
    r = capital_one(ctx(AccountClass.DEPOSIT, bank="capital_one", available=False))["Deposit from 360 Performance Savings XXXXXXX1234"]
    assert (r.tx_type, r.review_reason) == ("TRANSFER", "UNCLEAR_TYPE")


# --- IN-FMT-11: description patterns ---

def test_in_fmt_11_capital_one_interest_and_unmatched_debit() -> None:
    """IN-FMT-11 description patterns: interest is INCOME; a debit matching no pattern is EXPENSE, both unflagged."""
    rows = capital_one(ctx(AccountClass.DEPOSIT, bank="capital_one"))
    assert (rows["Monthly Interest Paid"].tx_type, rows["Monthly Interest Paid"].review_reason) == ("INCOME", None)
    remitly = rows["Withdrawal from REMITLY INC REMITTANCE"]
    assert (remitly.direction, remitly.tx_type, remitly.review_reason) == ("DEBIT", "EXPENSE", None)


def test_in_fmt_11_card_payment_depends_on_a_tracked_card_at_that_bank() -> None:
    """IN-FMT-11 description patterns: a card payment is TRANSFER when that bank's card is tracked, else flagged EXPENSE."""
    desc = "Withdrawal from CHASE CREDIT CRD EPAY"
    tracked = capital_one(ctx(AccountClass.DEPOSIT, CHASE_CARD_8760, bank="capital_one"))[desc]
    untracked = capital_one(ctx(AccountClass.DEPOSIT, SAVINGS_1234, bank="capital_one"))[desc]
    assert (tracked.tx_type, tracked.review_reason) == ("TRANSFER", None)
    assert (untracked.tx_type, untracked.review_reason) == ("EXPENSE", "UNCLEAR_TYPE")


def test_in_fmt_11_brokerage_and_zelle_are_flagged() -> None:
    """IN-FMT-11 description patterns: a brokerage move is a flagged TRANSFER; Zelle received is flagged INCOME."""
    rows = capital_one(ctx(AccountClass.DEPOSIT, bank="capital_one"))
    fid = rows["Withdrawal from FID BKG SVC LLC MONEYLINE"]
    zelle = rows["Zelle money received from Alex Doe"]
    assert (fid.tx_type, fid.review_reason) == ("TRANSFER", "UNCLEAR_TYPE")
    assert (zelle.tx_type, zelle.review_reason) == ("INCOME", "UNCLEAR_TYPE")


def test_in_fmt_11_pattern_not_fitting_the_direction_is_skipped() -> None:
    """IN-FMT-11 description patterns: interest paid as money out matches no pattern and follows the direction."""
    rows = capital_one(ctx(AccountClass.DEPOSIT, bank="capital_one"))
    assert rows["Monthly Interest Paid"].tx_type == "INCOME"
    flipped = table(CAPITAL_ONE.replace("Monthly Interest Paid,11/15/26,Credit", "Monthly Interest Paid,11/15/26,Debit"))
    r = {x.description: x for x in apply_profile(flipped, infer_profile(flipped).profile, ctx(AccountClass.DEPOSIT, bank="capital_one")).rows}
    assert (r["Monthly Interest Paid"].tx_type, r["Monthly Interest Paid"].review_reason) == ("EXPENSE", None)
