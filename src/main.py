"""FastAPI application and Lambda entry point (Mangum) for the Ingest service.

__author__ = "Van Vo"
"""

from __future__ import annotations

from fastapi import FastAPI
from fintracker_internal_http import load_settings as load_internal_http_settings
from mangum import Mangum

from .core.error_handlers import register_error_handlers
from .core.identity import assert_local_identity_safe
from .imports.router import router as imports_router

assert_local_identity_safe()  # invariant 2: no dev identity outside local development
load_internal_http_settings()  # LB-IHTTP-02: refuse an invalid INTERNAL_AUTH_MODE at the cold start

app = FastAPI(title="FinTracker Ingest Service", version="0.1.0",
              description="CSV and Excel bank exports to pending Ledger transactions, with a preview the user confirms.")
app.include_router(imports_router)
register_error_handlers(app)

handler = Mangum(app, lifespan="off", text_mime_types=["text/", "application/json", "application/problem+json"])
