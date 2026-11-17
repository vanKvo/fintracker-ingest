"""IN-FMT-10: load the shared default profiles from seed/format_profiles.json (deploy step).

    python -m scripts.load_seed_profiles [seed/format_profiles.json]

Stops with a non-zero exit, loading nothing, when any seed isn't usable for its own columns.

__author__ = "Van Vo"
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from src.profiles import codec, store
from src.profiles.signature import header_signature
from src.profiles.validation import validate_profile

DEFAULT_SEED = Path(__file__).resolve().parents[1] / "seed" / "format_profiles.json"


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    seeds = json.loads(Path(args[0] if args else DEFAULT_SEED).read_text(encoding="utf-8"))
    checked = []
    for seed in seeds:
        try:
            profile = codec.from_dict(seed["profile"])
        except Exception:
            print(f"Seed {seed.get('bankId')}/{seed.get('accountClass')} is malformed.")
            raise SystemExit(1) from None
        problems = validate_profile(profile, seed["headers"])
        if problems:
            print(f"Seed {seed['bankId']}/{seed['accountClass']} isn't usable: {', '.join(problems)}")
            raise SystemExit(1)
        checked.append((seed, profile))
    for seed, profile in checked:
        store.put_baseline(seed["bankId"], seed["accountClass"], header_signature(seed["headers"]), profile, seed["headers"],
                           source="SEED", by="seed", verified=bool(seed.get("verified")))
    print(f"Loaded {len(checked)} seed profiles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
