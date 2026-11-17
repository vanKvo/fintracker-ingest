"""Choosing the profile to propose (IN-FMT-02): the user's own, then the baseline for this layout,
then the nearest baseline whose columns exist in the file, then an inferred profile.

__author__ = "Van Vo"
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

from ..readers.schemas import Table
from .columns import index_of, mapped
from .inference import infer_profile
from .schemas import Baseline, Profile, Proposal
from .signature import header_signature
from .validation import validate_profile

_OPTIONAL = ("type", "category", "status")


def _flatten(profile: Profile) -> dict[str, str]:
    flat = {f"columns.{k}": v for k, v in mapped(profile.columns).items()}
    flat.update({
        "amountMode": str(profile.amount_mode), "dateFormat": str(profile.date_format),
        "signConvention": str(profile.sign_convention) if profile.sign_convention else "",
    })
    return flat


def _differences(user: Profile, baseline: Profile) -> dict[str, str]:
    mine, theirs = _flatten(user), _flatten(baseline)
    return {k: theirs.get(k, "") for k in sorted(set(mine) | set(theirs)) if mine.get(k) != theirs.get(k)}


def _adapted(profile: Profile, headers: Sequence[str]) -> Profile | None:
    """The baseline with optional columns the file lacks dropped; None if a required one is missing."""
    columns = profile.columns
    for name in _OPTIONAL:
        if getattr(columns, name) is not None and index_of(headers, getattr(columns, name)) is None:
            columns = dataclasses.replace(columns, **{name: None})
    candidate = dataclasses.replace(profile, columns=columns)
    return candidate if not validate_profile(candidate, headers) else None


def choose_proposal(table: Table, user_profile: Profile | None, baselines: Sequence[Baseline]) -> Proposal:
    headers = table.headers
    signature = header_signature(headers)
    same = next((b.profile for b in baselines if b.signature == signature), None)
    same_ok = same is not None and not validate_profile(same, headers)

    if user_profile is not None and not validate_profile(user_profile, headers):
        differences = _differences(user_profile, same) if same_ok and same is not None else {}
        return Proposal(user_profile, "USER", differences)
    if same_ok and same is not None:
        return Proposal(same, "BASELINE")

    nearest: tuple[int, str, Profile] | None = None
    for baseline in baselines:
        adapted = _adapted(baseline.profile, headers)
        if adapted is not None:
            key = (len(mapped(adapted.columns)), baseline.signature, adapted)
            if nearest is None or (key[0], key[1]) > (nearest[0], nearest[1]):
                nearest = key
    if nearest is not None:
        return Proposal(nearest[2], "NEAREST_BASELINE")

    inferred = infer_profile(table)
    return Proposal(inferred.profile, "INFERRED", unconfirmed=inferred.unconfirmed)
