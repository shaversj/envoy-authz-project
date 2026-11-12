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
    **kwargs: Any,
) -> Response:
    settings = Settings(
        required_scope="backend.read",
        upstream_header_value="some value",
    )
    transport = ASGITransport(app=create_app(settings))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.anyio
async def test_health_check_does_not_require_identity() -> None:
    response = await request("GET", "/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_verified_identity_with_required_scope_is_allowed() -> None:
    response = await request(
        "GET",
        "/authorize",
        headers={
            "x-authenticated-subject": "test-user",
            "x-authenticated-scope": "profile backend.read",
        },
    )

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["x-custom-header-from-authz"] == "some value"


@pytest.mark.anyio
async def test_authorization_endpoint_accepts_non_get_methods() -> None:
    response = await request(
        "POST",
        "/authorize",
        headers={
            "x-authenticated-subject": "test-user",
            "x-authenticated-scope": "backend.read",
        },
    )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_missing_verified_identity_is_unauthorized() -> None:
    response = await request(
        "GET",
        "/authorize",
        headers={"x-authenticated-scope": "backend.read"},
    )

    assert response.status_code == 401
    assert response.text == "Verified identity is required"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_verified_identity_without_required_scope_is_forbidden() -> None:
    response = await request(
        "GET",
        "/authorize",
        headers={
            "x-authenticated-subject": "test-user",
            "x-authenticated-scope": "profile",
        },
    )

    assert response.status_code == 403
    assert response.text == "PERMISSION_DENIED"
