"""IN-FMT-08: promote a profile the owner was notified about to the shared default for its layout.

    python -m scripts.promote_profile --bank chase --account-class CREDIT --signature <sig> --profile-hash <hash> --by <name> [--verified]

Check the profile against a sample export first when there is one. The script refuses a profile that
isn't usable for the layout's columns. Old defaults stay.

__author__ = "Van Vo"
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any

from src.profiles import codec, store
from src.profiles.validation import validate_profile


def promote_profile_dict(bank_id: str, account_class: str, signature: str, profile_data: dict[str, Any], headers: Sequence[str],
                         *, by: str, verified: bool = False, vote_count: int = 0) -> None:
    profile = codec.from_dict(profile_data)
    problems = validate_profile(profile, headers)
    if problems:
        raise ValueError(f"profile is not usable: {', '.join(problems)}")
    store.put_baseline(bank_id, account_class, signature, profile, headers, source="PROMOTED", by=by,
                       verified=verified, vote_count=vote_count)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank", required=True)
    parser.add_argument("--account-class", required=True, choices=("DEPOSIT", "CREDIT"))
    parser.add_argument("--signature", required=True)
    parser.add_argument("--profile-hash", required=True)
    parser.add_argument("--by", required=True)
    parser.add_argument("--verified", action="store_true")
    args = parser.parse_args(argv)
    notice = store.get_promotion_notice(args.bank, args.account_class, args.signature, args.profile_hash)
    if notice is None:
        print("No promotion notice for that layout and profile.")
        return 1
    promote_profile_dict(args.bank, args.account_class, args.signature, json.loads(notice["profile"]), notice["headers"],
                         by=args.by, verified=args.verified, vote_count=int(notice.get("voteCount", 0)))
    print("Promoted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
