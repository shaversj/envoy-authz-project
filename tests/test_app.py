from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response

from envoy_authz.app import Settings, create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def request(
    method: str,
    path: str,
    *,
    token: str = "foo",
    **kwargs: Any,
) -> Response:
    settings = Settings(
        bearer_token=token,
        upstream_header_value="some value",
    )
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.anyio
async def test_health_check_does_not_require_authorization() -> None:
    response = await request("GET", "/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_valid_bearer_token_allows_request_and_sets_upstream_header() -> None:
    response = await request(
        "GET",
        "/authorize",
        headers={"Authorization": "Bearer foo"},
    )

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["x-custom-header-from-authz"] == "some value"


@pytest.mark.anyio
async def test_authorization_endpoint_accepts_non_get_methods() -> None:
    response = await request(
        "POST",
        "/authorize",
        headers={"Authorization": "Bearer foo"},
    )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_invalid_bearer_token_is_denied() -> None:
    response = await request(
        "GET",
        "/authorize",
        headers={"Authorization": "Bearer bar"},
    )

    assert response.status_code == 401
    assert response.text == "PERMISSION_DENIED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_missing_authorization_header_is_denied() -> None:
    response = await request("GET", "/authorize")

    assert response.status_code == 401
    assert response.text == "Authorization header malformed or not provided"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_malformed_authorization_header_is_denied() -> None:
    response = await request(
        "GET",
        "/authorize",
        headers={"Authorization": "Basic Zm9vOmJhcg=="},
    )

    assert response.status_code == 401
    assert response.text == "Authorization header malformed or not provided"


@pytest.mark.anyio
async def test_non_ascii_bearer_token_is_denied_without_server_error() -> None:
    response = await request(
        "GET",
        "/authorize",
        headers=[(b"authorization", b"Bearer caf\xe9")],
    )

    assert response.status_code == 401
    assert response.text == "PERMISSION_DENIED"
