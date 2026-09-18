"""One error shape for every route (docs/api_contract.md, Conventions):

    {"error": {"code": "<snake_case>", "message": "<for a person>", "details": {...}}}

`detail` is kept beside it until the Streamlit UI goes at S5, because that UI reads it."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict",
         422: "validation_failed", 503: "unavailable"}


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
