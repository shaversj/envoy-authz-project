import logging
import os
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
    required_scope: str
    upstream_header_value: str

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            required_scope=os.getenv("AUTHZ_REQUIRED_SCOPE", "backend.read"),
            upstream_header_value=os.getenv(
                "AUTHZ_UPSTREAM_HEADER_VALUE",
                "some value",
            ),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
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
        subject = request.headers.get("x-authenticated-subject", "").strip()

        if not subject:
            logger.info(
                "Authorization denied: verified identity missing",
                extra={"method": request.method, "path": request.url.path},
            )
            return PlainTextResponse(
                "Verified identity is required",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        scopes = set(request.headers.get("x-authenticated-scope", "").split())
        if resolved_settings.required_scope not in scopes:
            logger.info(
                "Authorization denied: required scope missing",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "subject": subject,
                },
            )
            return PlainTextResponse(
                "PERMISSION_DENIED",
                status_code=403,
            )

        logger.info(
            "Authorization allowed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "subject": subject,
            },
        )
        return Response(
            status_code=200,
            headers={
                "x-custom-header-from-authz": resolved_settings.upstream_header_value
            },
        )

    return app


app = create_app()
