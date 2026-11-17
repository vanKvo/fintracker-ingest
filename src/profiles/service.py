"""Format profiles: the feature's public functions (IN-FMT).

__author__ = "Van Vo"
"""

from __future__ import annotations

from typing import Sequence

from ..core.exceptions import UnsupportedAccountTypeError
from .apply import apply_profile
from .inference import infer_profile
from .proposal import choose_proposal
from .schemas import AccountClass
from .signature import header_signature
from .validation import validate_profile

__all__ = ["account_class_for", "apply_profile", "choose_proposal", "infer_profile", "profile_key", "validate_profile"]

_CLASSES = {"CHECKING": AccountClass.DEPOSIT, "SAVINGS": AccountClass.DEPOSIT, "CREDIT": AccountClass.CREDIT}


def account_class_for(account_type: str) -> AccountClass:
    """IN-FMT-01: checking and savings are DEPOSIT, credit cards CREDIT. Cash has no bank export."""
    try:
        return _CLASSES[account_type]
    except KeyError:
        raise UnsupportedAccountTypeError("No bank export for this account type") from None


def profile_key(bank_id: str, account_class: AccountClass, headers: Sequence[str]) -> tuple[str, AccountClass, str]:
    """IN-FMT-01: a profile is keyed by bank, account class and header signature."""
    return bank_id, account_class, header_signature(headers)
