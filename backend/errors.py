"""One error shape for every route (docs/api_contract.md, Conventions):

    {"error": {"code": "<snake_case>", "message": "<for a person>", "details": {...}}}

`detail` is kept beside it until the Streamlit UI goes at S5, because that UI reads it."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.schemas_api import ErrorBody

CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict",
         413: "too_large", 422: "validation_failed", 503: "unavailable"}


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str, details: dict | list | None = None):
        super().__init__(status, message)
        self.code, self.message, self.details = code, message, details or {}


def _body(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": jsonable_encoder(details or {})},
                         "detail": message}, status_code=status)


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, err: ApiError):
        return _body(err.status_code, err.code, err.message, err.details)

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, err: HTTPException):
        message = err.detail if isinstance(err.detail, str) else str(err.detail)
        return _body(err.status_code, CODES.get(err.status_code, "error"), message)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, err: RequestValidationError):
        return _body(422, "validation_failed", "the request did not validate", {"errors": jsonable_encoder(err.errors())})


def document(app: FastAPI) -> None:
    """In the OpenAPI document a 422 body is `ErrorBody`, the envelope the handler above
    really sends, not FastAPI's default `HTTPValidationError` (checklist I1.9)."""
    base = app.openapi

    def openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = base()
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        for name in ("HTTPValidationError", "ValidationError"):
            schemas.pop(name, None)
        body = ErrorBody.model_json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(body.pop("$defs", {}))
        schemas["ErrorBody"] = body
        _swap_refs(schema, "#/components/schemas/HTTPValidationError", "#/components/schemas/ErrorBody")
        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi


def _swap_refs(node, old: str, new: str) -> None:
    """Rewrite `$ref` values only, never prose that happens to mention the old name."""
    if isinstance(node, dict):
        if node.get("$ref") == old:
            node["$ref"] = new
        for value in node.values():
            _swap_refs(value, old, new)
    elif isinstance(node, list):
        for value in node:
            _swap_refs(value, old, new)
