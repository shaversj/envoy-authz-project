import logging

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

logger = logging.getLogger("uvicorn.error")

SUPPORTED_HTTP_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
    "HEAD",
]


app = FastAPI(
    title="Example Envoy Backend",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.api_route("/", methods=SUPPORTED_HTTP_METHODS)
@app.api_route("/{path:path}", methods=SUPPORTED_HTTP_METHODS)
async def handle_request(request: Request) -> PlainTextResponse:
    logger.info(
        "Backend request received: method=%s path=%s headers=%s",
        request.method,
        request.url.path,
        ",".join(sorted(request.headers)),
    )
    return PlainTextResponse(
        "ok",
        headers={"x-custom-header-from-backend": "from backend"},
    )
