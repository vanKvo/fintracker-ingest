"""A row's type (IN-FMT-05, -11, -12). The first step that answers wins: the household's own
account by last four, the bank's type label, a description pattern, then the direction.

__author__ = "Van Vo"
"""

from __future__ import annotations

from dataclasses import dataclass

from .labels import lookup_label
from .own_accounts import match_own_account
from .patterns import issuer_of, patterns_for
from .schemas import AccountClass, Direction, ImportContext, TxType

_ALLOWED: dict[TxType, frozenset[Direction]] = {  # LG-TXT-01
    TxType.EXPENSE: frozenset({Direction.DEBIT}),
    TxType.INCOME: frozenset({Direction.CREDIT}),
    TxType.REFUND: frozenset({Direction.CREDIT}),
    TxType.TRANSFER: frozenset({Direction.DEBIT, Direction.CREDIT}),
    TxType.ADJUSTMENT: frozenset({Direction.DEBIT, Direction.CREDIT}),
}


@dataclass(frozen=True)
class TypeDecision:
    tx_type: TxType
    flagged: bool
    unknown_label: str | None = None  # for the UNKNOWN_TYPE_LABEL log


def fits(tx_type: TxType, direction: Direction) -> bool:
    return direction in _ALLOWED[tx_type]


def from_direction(direction: Direction, account_class: AccountClass) -> TypeDecision:
    """Money into a card is a payment or a refund, never income. TRANSFER is the safer guess: a
    payment read as a refund would cancel real spending in the budget."""
    if direction == Direction.DEBIT:
        return TypeDecision(TxType.EXPENSE, False)
    if account_class == AccountClass.CREDIT:
        return TypeDecision(TxType.TRANSFER, True)
    return TypeDecision(TxType.INCOME, False)


def _card_payment(ctx: ImportContext, description: str) -> TypeDecision:
    issuer = issuer_of(description)
    tracked = issuer is not None and ctx.household is not None and any(
        a.account_class == AccountClass.CREDIT and a.bank_id == issuer and a.account_id != ctx.account_id
        for a in ctx.household
    )
    return TypeDecision(TxType.TRANSFER, False) if tracked else TypeDecision(TxType.EXPENSE, True)


def classify(description: str, label: str | None, direction: Direction, ctx: ImportContext) -> TypeDecision:
    own = match_own_account(description, ctx)
    if own != "NONE":
        return TypeDecision(TxType.TRANSFER, own == "UNCLEAR")

    unknown_label: str | None = None
    if label and label.strip():
        entry = lookup_label(ctx.bank_id, ctx.account_class, label)
        if entry is None:
            unknown_label = label.strip()  # flagged; patterns and the direction still decide the type
        else:
            tx_type, flag = entry
            if fits(tx_type, direction):
                return TypeDecision(tx_type, flag)
            fallback = from_direction(direction, ctx.account_class)
            return TypeDecision(fallback.tx_type, True)

    for pattern in patterns_for(ctx.bank_id, ctx.account_class):
        if pattern.direction not in (None, direction) or not pattern.regex.search(description):
            continue
        if isinstance(pattern.result, TxType):
            if not fits(pattern.result, direction):
                continue
            decision = TypeDecision(pattern.result, pattern.flag)
        else:  # CARD_PAYMENT
            decision = _card_payment(ctx, description)
        return TypeDecision(decision.tx_type, decision.flagged or unknown_label is not None, unknown_label)

    fallback = from_direction(direction, ctx.account_class)
    return TypeDecision(fallback.tx_type, fallback.flagged or unknown_label is not None, unknown_label)
