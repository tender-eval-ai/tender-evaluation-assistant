"""Unit tests for two API helpers the Postgres-only route tests never reach in the default
run (review of #41): the version timestamps and the OpenAPI error-body rewrite."""
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI
from pydantic import BaseModel

from backend import errors
from backend.routes.rulesets import _when


def test_version_timestamps_accept_epoch_floats_decimals_and_datetimes():
    assert _when(None) is None
    assert _when(0.0) == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert _when(Decimal("1.5")) == datetime(1970, 1, 1, 0, 0, 1, 500000, tzinfo=timezone.utc)   # psycopg's extract(epoch)
    already = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    assert _when(already) is already
    assert _when(1.0).tzinfo is timezone.utc


def test_the_openapi_422_body_is_the_envelope_and_prose_is_left_alone():
    class Body(BaseModel):
        name: str

    app = FastAPI()

    @app.post("/things")
    def make(body: Body) -> dict:
        """Mentions HTTPValidationError in prose; only $ref values may be rewritten."""
        return {}

    errors.install(app)
    errors.document(app)
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    assert "ErrorBody" in schemas and "ErrorDetail" in schemas
    assert "HTTPValidationError" not in schemas and "ValidationError" not in schemas
    op = spec["paths"]["/things"]["post"]
    assert op["responses"]["422"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/ErrorBody"
    assert "HTTPValidationError" in op["description"]          # the docstring is prose, not a $ref
