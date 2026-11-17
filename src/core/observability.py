"""Logger and metrics for the Ingest service (IN-IMP-11).

Every line goes through fintracker-log-masking. Log only codes, ids, steps and counts — never
statement content (IN-IMP principle 6).

__author__ = "Van Vo"
"""

from __future__ import annotations

from aws_lambda_powertools.metrics import MetricUnit, single_metric
from fintracker_log_masking import setup_logging

SERVICE = "ingest-service"
NAMESPACE = "FinTracker"

logger = setup_logging(SERVICE)  # LB-LOGM-10: masks every line and every standard-library record


def metric(name: str, value: float = 1, unit: MetricUnit = MetricUnit.Count, **dimensions: str) -> None:
    """One EMF metric, flushed at once. Metrics must never fail a request."""
    try:
        with single_metric(name=name, unit=unit, value=value, namespace=NAMESPACE) as m:
            m.add_dimension(name="service", value=SERVICE)
            for key, val in dimensions.items():
                m.add_dimension(name=key, value=val)
    except Exception:  # pragma: no cover - metrics are best effort
        logger.warning("METRIC_FAILED", metric=name)


__all__ = ["logger", "metric", "MetricUnit"]
