"""IN-IMP-10: Ingest's permissions grant only what it needs.

__author__ = "Van Vo"
"""

from __future__ import annotations

import re
from pathlib import Path

TERRAFORM = Path(__file__).resolve().parents[2] / "infrastructure" / "terraform"


def _allow_statements() -> str:
    text = (TERRAFORM / "environments" / "dev" / "main.tf").read_text() + (TERRAFORM / "modules" / "lambda_function" / "main.tf").read_text()
    return text


def test_in_imp_10_no_wildcard_actions_or_resources() -> None:
    """IN-IMP-10 least privilege: no Ingest policy grants every action or every resource."""
    text = _allow_statements()
    assert not re.search(r'actions?\s*=\s*\[[^\]]*"\*"', text, re.IGNORECASE)
    assert not re.search(r'resources?\s*=\s*\[[^\]]*"\*"\s*[,\]]', text, re.IGNORECASE)
    assert not re.search(r'"[a-z0-9-]+:\*"', text)


def test_in_imp_10_no_document_or_language_ai_permissions() -> None:
    """IN-IMP-10 least privilege: no Textract or Comprehend permission."""
    text = _allow_statements().lower()
    assert "textract" not in text and "comprehend" not in text


def test_in_imp_08_sweep_schedule_has_a_switch() -> None:
    """IN-IMP-08 cancel and expiry: the cleanup job's schedule state follows expiry_sweep_enabled, every 15 minutes."""
    text = (TERRAFORM / "environments" / "dev" / "main.tf").read_text()
    assert 'state               = var.expiry_sweep_enabled ? "ENABLED" : "DISABLED"' in text
    assert 'rate(15 minutes)' in text


def test_in_fmt_06_proposal_changed_alarm_is_per_seeded_bank() -> None:
    """IN-FMT-06 format-change alarms: the proposal-changed share alarm is one per seeded bank, on the bank's own metrics."""
    text = (TERRAFORM / "environments" / "dev" / "main.tf").read_text()
    alarm = text[text.index('resource "aws_cloudwatch_metric_alarm" "proposal_changed_share"'):]
    alarm = alarm[:alarm.index("\n}\n")]
    assert re.search(r"for_each\s+= toset\(local.seed_banks\)", alarm)
    assert alarm.count("bank = each.key") == 2
    assert 'jsondecode(file("${path.module}/../../../../seed/format_profiles.json"))' in text
