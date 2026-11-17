# Ingest Service

Turns CSV and Excel bank exports into pending Ledger transactions, with a preview the user confirms.
Replaces the legacy Data pipeline (never deployed; reference code in `services/fintracker-data-pipeline`).

Specs: `docs/fintracker-ingest/specs/` — IN-IMP (import flow), IN-FMT (format profiles), IN-RDR (file readers).
Contracts with the Ledger: XS-IMP-05 to -07 (`docs/fintracker-cross-services/specs/`).

## Layout

| Folder | Holds |
|---|---|
| `src/imports/` | The API (FastAPI on Lambda via Mangum), the import record and the workflow: start, preview, confirm, cancel |
| `src/readers/` | IN-RDR: CSV and XLSX into a table, with the safety limits |
| `src/profiles/` | IN-FMT: bank layouts, inference, direction and type, the profile store, votes and promotion |
| `src/categorizer/` | Category code suggestions (copied from the legacy pipeline; patterns packaged as JSON) |
| `src/ledger/` | Calls to the Ledger's internal API |
| `src/files/` | Reading uploaded files and their malware scan tag |
| `src/sweep/` | IN-IMP-08: the 15-minute cleanup job |
| `scripts/` | `load_seed_profiles` (deploy step), `promote_profile` (owner), `build_lambda_package.sh` |
| `seed/format_profiles.json` | Shared default profiles (IN-FMT-10) |
| `infrastructure/terraform/` | Lambdas, HTTP API, tables, bucket, scheduler (with its switch), malware scan (with its switch), alarms |

## Run the tests

```bash
poetry install
poetry run pytest          # unit and service tests: moto for AWS, a fake Ledger at the HTTP edge
poetry run mypy src scripts
```

## Run locally

```bash
APP_ENV=local LOCAL_DEV_USER_ID=<your internal user id> INTERNAL_AUTH_MODE=local \
INTERNAL_BASE_URL_LEDGER=http://localhost:8080 STATEMENT_BUCKET=<bucket> \
poetry run uvicorn src.main:app --reload --port 8086
```

## Deploy (dev)

```bash
scripts/build_lambda_package.sh
cd infrastructure/terraform/environments/dev && terraform init && terraform apply
cd ../../../.. && poetry run python -m scripts.load_seed_profiles      # IN-FMT-10
```

Then add `api_role_arn` and `sweep_role_arn` (Terraform outputs) to the Ledger's `INTERNAL_ALLOWED_CALLER_ARNS`.

**Switches:** `malware_scan` (IN-IMP-03; off in phase 1, on before anyone but the owner uploads) and
`expiry_sweep_enabled` (IN-IMP-08). Both are Terraform variables.
