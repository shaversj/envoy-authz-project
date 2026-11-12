import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from jwt.algorithms import RSAAlgorithm

from jwt_issuer.app import Settings, create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_issuer_publishes_jwks_and_mints_verifiable_token() -> None:
    settings = Settings(
        issuer="http://issuer.test",
        audience="envoy-demo",
    )
    transport = ASGITransport(app=create_app(settings))

    async with AsyncClient(transport=transport, base_url=settings.issuer) as client:
        jwks_response = await client.get("/.well-known/jwks.json")
        token_response = await client.post(
            "/token",
            params={
                "subject": "test-user",
                "scope": "profile backend.read",
            },
        )

    assert jwks_response.status_code == 200
    jwks = jwks_response.json()
    assert len(jwks["keys"]) == 1
    assert jwks["keys"][0]["use"] == "sig"
    assert jwks["keys"][0]["alg"] == "RS256"

    assert token_response.status_code == 200
    token_body = token_response.json()
    public_key = RSAAlgorithm.from_jwk(jwks["keys"][0])
    claims = jwt.decode(
        token_body["access_token"],
        public_key,
        algorithms=["RS256"],
        issuer=settings.issuer,
        audience=settings.audience,
    )

    assert token_body["token_type"] == "Bearer"
    assert claims["sub"] == "test-user"
    assert claims["scope"] == "profile backend.read"


@pytest.mark.anyio
async def test_issuer_can_mint_expired_token_for_failure_testing() -> None:
    settings = Settings(
        issuer="http://issuer.test",
        audience="envoy-demo",
    )
    transport = ASGITransport(app=create_app(settings))

    async with AsyncClient(transport=transport, base_url=settings.issuer) as client:
        response = await client.post("/token", params={"expires_in": -60})

    claims = jwt.decode(
        response.json()["access_token"],
        options={"verify_signature": False},
    )

    assert claims["exp"] < claims["iat"]
