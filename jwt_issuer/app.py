import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from jwt.algorithms import RSAAlgorithm


@dataclass(frozen=True)
class Settings:
    issuer: str
    audience: str

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            issuer=os.getenv("JWT_ISSUER_URL", "http://127.0.0.1:8002"),
            audience=os.getenv("JWT_AUDIENCE", "envoy-demo"),
        )


class JwtIssuer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        public_key = self._private_key.public_key()
        public_der = public_key.public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self.key_id = hashlib.sha256(public_der).hexdigest()[:16]

        jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
        jwk.update({"kid": self.key_id, "use": "sig", "alg": "RS256"})
        self.jwks = {"keys": [jwk]}

    def mint_token(
        self,
        *,
        subject: str,
        scope: str,
        expires_in: int,
        issuer: str | None = None,
        audience: str | None = None,
    ) -> str:
        now = datetime.now(UTC)
        claims = {
            "iss": issuer or self.settings.issuer,
            "aud": audience or self.settings.audience,
            "sub": subject,
            "scope": scope,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        }
        return jwt.encode(
            claims,
            self._private_key,
            algorithm="RS256",
            headers={"kid": self.key_id},
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    issuer = JwtIssuer(resolved_settings)
    app = FastAPI(
        title="Development JWT Issuer",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/jwks.json")
    async def jwks() -> dict[str, list[dict[str, Any]]]:
        return issuer.jwks

    @app.post("/token")
    async def token(
        subject: str = "demo-user",
        scope: str = "backend.read",
        expires_in: int = 300,
        token_issuer: str | None = None,
        audience: str | None = None,
    ) -> dict[str, str | int]:
        return {
            "access_token": issuer.mint_token(
                subject=subject,
                scope=scope,
                expires_in=expires_in,
                issuer=token_issuer,
                audience=audience,
            ),
            "token_type": "Bearer",
            "expires_in": expires_in,
        }

    return app


app = create_app()
