import pytest
from httpx import ASGITransport, AsyncClient

from backend_server.app import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_root_returns_backend_response_header() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/",
            headers={"x-custom-header-from-authz": "some value"},
        )

    assert response.status_code == 200
    assert response.text == "ok"
    assert response.headers["x-custom-header-from-backend"] == "from backend"


@pytest.mark.anyio
async def test_backend_accepts_non_get_requests_on_nested_paths() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/orders/123", content=b"request body")

    assert response.status_code == 200
    assert response.text == "ok"
