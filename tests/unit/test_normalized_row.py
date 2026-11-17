"""IN-IMP-07: the row sent to the Ledger.

__author__ = "Van Vo"
"""

from __future__ import annotations

import datetime as dt

from src.categorizer.merchant_map import MerchantPattern
from src.categorizer.service import CodeSuggester
from src.imports.normalize import ledger_lines
from src.profiles.schemas import AccountClass, AmountMode, Columns, DateFormat, ImportContext, Profile, SignConvention
from src.profiles.service import apply_profile
from src.readers.service import read_file

TODAY = dt.date(2026, 11, 16)
CTX = ImportContext(bank_id="chase", account_class=AccountClass.CREDIT, account_id="own", household=(), today=TODAY)
PROFILE = Profile(
    columns=Columns(date="Date", description="Description", amount="Amount", category="Category"),
    amount_mode=AmountMode.SIGNED, sign_convention=SignConvention.EXPENSE_NEGATIVE, date_format=DateFormat.MDY,
)
SUGGESTER = CodeSuggester([
    MerchantPattern(pattern="STARBUCKS", match_type="contains", code="food-and-drink", priority=10, active=True),
])


def lines(text: str, statement_id: str = "stmt-1") -> list[dict[str, object]]:
    table = read_file("x.csv", ("Date,Description,Amount,Category\n" + text).encode())
    return ledger_lines(apply_profile(table, PROFILE, CTX), statement_id, SUGGESTER)


def test_in_imp_07_row_has_iso_date_clean_merchant_positive_amount_type_and_category() -> None:
    """IN-IMP-07 normalized row: date, merchant, amount, direction, type and category code for the Ledger."""
    [line] = lines("01/15/26,STARBUCKS #12345,-5.75,\n")
    assert line["date"] == "2026-01-15"
    assert line["merchant"] == "starbucks"
    assert line["amount"] == "5.75"
    assert (line["direction"], line["type"]) == ("DEBIT", "EXPENSE")
    assert line["categoryCode"] == "food-and-drink"
    assert line["merchantKey"] == "STARBUCKS"
    assert line["reviewReason"] is None


def test_in_imp_07_bank_category_label_is_used_and_kept() -> None:
    """IN-IMP-07 normalized row: the bank's category label gives the code and travels as sourceCategory."""
    [line] = lines("01/15/2026,CORNER MARKET,-20.00,Groceries\n")
    assert (line["categoryCode"], line["sourceCategory"]) == ("groceries", "Groceries")


def test_in_imp_07_amount_formats() -> None:
    """IN-IMP-07 normalized row: currency symbols and thousands separators are ignored; parentheses are negative."""
    big, paren = lines('01/15/2026,SHOP,"$1,234.56",\n01/16/2026,REFUND,(42.00),\n')
    assert (big["amount"], big["direction"]) == ("1234.56", "CREDIT")
    assert (paren["amount"], paren["direction"]) == ("42.00", "DEBIT")


def test_in_imp_07_identical_rows_get_different_fingerprints_and_retries_the_same() -> None:
    """IN-IMP-07 normalized row: two identical $5 rows differ by row number; a retry gives the same fingerprints."""
    text = "01/15/2026,COFFEE,-5.00,\n01/15/2026,COFFEE,-5.00,\n"
    first, second = lines(text)
    assert first["rowFingerprint"] != second["rowFingerprint"]
    assert [l["rowFingerprint"] for l in lines(text)] == [first["rowFingerprint"], second["rowFingerprint"]]
    assert lines(text, "stmt-2")[0]["rowFingerprint"] != first["rowFingerprint"]


def test_in_imp_07_future_zero_and_unreadable_rows_are_never_sent() -> None:
    """IN-IMP-07 normalized row: a date over a day ahead, a zero amount or a bad date is unreadable, never guessed."""
    table = read_file("x.csv", b"Date,Description,Amount,Category\n03/01/2027,A,-1.00,\n11/17/2026,B,-1.00,\n01/15/2026,C,0.00,\n13/45/2026,D,-1.00,\n")
    applied = apply_profile(table, PROFILE, CTX)
    assert applied.counts == {"read": 1, "pending": 0, "unreadable": 3}
    assert [l["merchant"] for l in ledger_lines(applied, "s", SUGGESTER)] == ["b"]


def test_in_imp_07_excluded_rows_are_left_out() -> None:
    """IN-IMP-07 normalized row: rows the user excluded (by file row number) are not sent."""
    table = read_file("x.csv", b"Date,Description,Amount,Category\n01/15/2026,A,-1.00,\n01/16/2026,B,-2.00,\n")
    applied = apply_profile(table, PROFILE, CTX)
    assert [l["merchant"] for l in ledger_lines(applied, "s", SUGGESTER, excluded_rows=frozenset({2}))] == ["b"]


def test_in_imp_07_unclear_type_travels_as_review_reason() -> None:
    """IN-IMP-07 normalized row: a row flagged UNCLEAR_TYPE carries it as reviewReason (XS-IMP-01)."""
    [line] = lines("01/15/2026,THANKS,300.00,\n")
    assert (line["type"], line["reviewReason"]) == ("TRANSFER", "UNCLEAR_TYPE")
