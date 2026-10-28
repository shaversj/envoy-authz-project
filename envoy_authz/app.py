import logging
import os
import secrets
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

AUTHORIZATION_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "HEAD",
]


@dataclass(frozen=True)
class Settings:
    bearer_token: str
    upstream_header_value: str

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            bearer_token=os.getenv("AUTHZ_BEARER_TOKEN", "foo"),
            upstream_header_value=os.getenv(
                "AUTHZ_UPSTREAM_HEADER_VALUE",
                "some value",
            ),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    expected_bearer_token = resolved_settings.bearer_token.encode()
    app = FastAPI(
        title="Envoy HTTP External Authorization",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/authorize", methods=AUTHORIZATION_METHODS)
    async def authorize(request: Request) -> Response:
        authorization = request.headers.get("authorization")
        parts = authorization.split() if authorization else []

        if len(parts) != 2 or parts[0].lower() != "bearer":
            logger.info(
                "Authorization denied: malformed or missing header",
                extra={"method": request.method, "path": request.url.path},
            )
            return PlainTextResponse(
                "Authorization header malformed or not provided",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not secrets.compare_digest(parts[1].encode(), expected_bearer_token):
            logger.info(
                "Authorization denied: invalid bearer token",
                extra={"method": request.method, "path": request.url.path},
            )
            return PlainTextResponse(
                "PERMISSION_DENIED",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.info(
            "Authorization allowed",
            extra={"method": request.method, "path": request.url.path},
        )
        return Response(
            status_code=200,
            headers={
                "x-custom-header-from-authz": resolved_settings.upstream_header_value
            },
        )

    return app


app = create_app()
