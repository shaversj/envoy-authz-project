import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
import yaml
from cryptography.hazmat.primitives.asymmetric import rsa

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENVOY_CONFIG = PROJECT_ROOT / "envoy.yaml"
ENVOY_BINARY = shutil.which("envoy")


@dataclass(frozen=True)
class Runtime:
    envoy_url: str
    issuer_url: str


def load_config() -> dict[str, Any]:
    return yaml.safe_load(ENVOY_CONFIG.read_text())


def get_http_connection_manager(config: dict[str, Any]) -> dict[str, Any]:
    return config["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0][
        "typed_config"
    ]


def test_jwt_authn_runs_before_ext_authz() -> None:
    config = load_config()
    http_filters = get_http_connection_manager(config)["http_filters"]

    assert [item["name"] for item in http_filters[:3]] == [
        "envoy.filters.http.jwt_authn",
        "envoy.filters.http.ext_authz",
        "envoy.filters.http.router",
    ]


def test_only_verified_identity_headers_are_sent_to_ext_authz() -> None:
    config = load_config()
    http_filters = get_http_connection_manager(config)["http_filters"]
    filters = {item["name"]: item["typed_config"] for item in http_filters}

    jwt_provider = filters["envoy.filters.http.jwt_authn"]["providers"]["demo"]
    claim_headers = {
        item["header_name"]: item["claim_name"]
        for item in jwt_provider["claim_to_headers"]
    }
    assert claim_headers == {
        "x-authenticated-subject": "sub",
        "x-authenticated-scope": "scope",
    }
    assert jwt_provider["forward"] is False

    ext_authz = filters["envoy.filters.http.ext_authz"]
    allowed_headers = {
        item["exact"] for item in ext_authz["allowed_headers"]["patterns"]
    }
    disallowed_headers = {
        item["exact"] for item in ext_authz["disallowed_headers"]["patterns"]
    }
    assert allowed_headers == {
        "x-authenticated-subject",
        "x-authenticated-scope",
    }
    assert "authorization" in disallowed_headers


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_process(
    command: list[str],
    *,
    environment: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_url(
    url: str,
    process: subprocess.Popen[str],
    *,
    timeout: float = 10,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"Process exited before {url} was ready:\n{output}")
        try:
            httpx.get(url, timeout=0.25)
            return
        except httpx.HTTPError:
            time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {url}")


def render_test_config(
    path: Path,
    *,
    envoy_port: int,
    admin_port: int,
    authz_port: int,
    backend_port: int,
    issuer_port: int,
) -> None:
    config = load_config()
    config["admin"]["address"]["socket_address"]["port_value"] = admin_port

    listener = config["static_resources"]["listeners"][0]
    listener["address"]["socket_address"]["port_value"] = envoy_port
    http_connection_manager = get_http_connection_manager(config)
    filters = {
        item["name"]: item["typed_config"]
        for item in http_connection_manager["http_filters"]
    }

    issuer_url = f"http://127.0.0.1:{issuer_port}"
    jwt_provider = filters["envoy.filters.http.jwt_authn"]["providers"]["demo"]
    jwt_provider["issuer"] = issuer_url
    jwt_provider["remote_jwks"]["http_uri"]["uri"] = (
        f"{issuer_url}/.well-known/jwks.json"
    )

    ext_authz = filters["envoy.filters.http.ext_authz"]
    ext_authz["http_service"]["server_uri"]["uri"] = f"http://127.0.0.1:{authz_port}"

    cluster_ports = {
        "backend": backend_port,
        "ext-authz": authz_port,
        "jwt-issuer": issuer_port,
    }
    for cluster in config["static_resources"]["clusters"]:
        port = cluster_ports[cluster["name"]]
        cluster["load_assignment"]["endpoints"][0]["lb_endpoints"][0]["endpoint"][
            "address"
        ]["socket_address"]["port_value"] = port

    path.write_text(yaml.safe_dump(config, sort_keys=False))


@pytest.fixture(scope="module")
def runtime(tmp_path_factory: pytest.TempPathFactory) -> Generator[Runtime]:
    if ENVOY_BINARY is None:
        pytest.skip("Envoy is not installed")

    issuer_port = free_port()
    authz_port = free_port()
    backend_port = free_port()
    envoy_port = free_port()
    admin_port = free_port()
    issuer_url = f"http://127.0.0.1:{issuer_port}"
    envoy_url = f"http://127.0.0.1:{envoy_port}"
    processes: list[subprocess.Popen[str]] = []

    try:
        issuer_environment = os.environ.copy()
        issuer_environment["JWT_ISSUER_URL"] = issuer_url
        processes.append(
            start_process(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "jwt_issuer.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(issuer_port),
                    "--log-level",
                    "warning",
                ],
                environment=issuer_environment,
            )
        )
        wait_for_url(f"{issuer_url}/healthz", processes[-1])

        for app, port in [
            ("envoy_authz.app:app", authz_port),
            ("backend_server.app:app", backend_port),
        ]:
            processes.append(
                start_process(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        app,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--log-level",
                        "warning",
                    ],
                    environment=os.environ.copy(),
                )
            )
            wait_for_url(f"http://127.0.0.1:{port}/healthz", processes[-1])

        config_path = tmp_path_factory.mktemp("envoy") / "envoy.yaml"
        render_test_config(
            config_path,
            envoy_port=envoy_port,
            admin_port=admin_port,
            authz_port=authz_port,
            backend_port=backend_port,
            issuer_port=issuer_port,
        )
        processes.append(
            start_process(
                [ENVOY_BINARY, "-c", str(config_path), "--log-level", "warning"],
                environment=os.environ.copy(),
            )
        )
        wait_for_url(envoy_url, processes[-1])

        yield Runtime(envoy_url=envoy_url, issuer_url=issuer_url)
    finally:
        for process in reversed(processes):
            stop_process(process)


def mint_token(runtime: Runtime, **overrides: Any) -> str:
    response = httpx.post(
        f"{runtime.issuer_url}/token",
        params={
            "subject": "test-user",
            "scope": "backend.read",
            **overrides,
        },
        timeout=2,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def request_backend(runtime: Runtime, token: str, **headers: str) -> httpx.Response:
    return httpx.get(
        runtime.envoy_url,
        headers={"Authorization": f"Bearer {token}", **headers},
        timeout=2,
    )


def test_valid_token_reaches_backend(runtime: Runtime) -> None:
    response = request_backend(runtime, mint_token(runtime))

    assert response.status_code == 200
    assert response.text == "ok"
    assert response.headers["x-custom-header-from-backend"] == "from backend"


def test_missing_and_expired_tokens_are_unauthorized(runtime: Runtime) -> None:
    missing = httpx.get(runtime.envoy_url, timeout=2)
    expired = request_backend(runtime, mint_token(runtime, expires_in=-300))

    assert missing.status_code == 401
    assert expired.status_code == 401


@pytest.mark.parametrize(
    ("overrides", "expected_status"),
    [
        ({"token_issuer": "https://wrong-issuer.example"}, 401),
        ({"audience": "wrong-audience"}, 403),
    ],
)
def test_wrong_issuer_or_audience_is_unauthorized(
    runtime: Runtime,
    overrides: dict[str, str],
    expected_status: int,
) -> None:
    response = request_backend(runtime, mint_token(runtime, **overrides))

    assert response.status_code == expected_status


def test_invalid_signature_is_unauthorized(runtime: Runtime) -> None:
    trusted_token = mint_token(runtime)
    trusted_header = jwt.get_unverified_header(trusted_token)
    now = datetime.now(UTC)
    untrusted_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged_token = jwt.encode(
        {
            "iss": runtime.issuer_url,
            "aud": "envoy-demo",
            "sub": "test-user",
            "scope": "backend.read",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        untrusted_key,
        algorithm="RS256",
        headers={"kid": trusted_header["kid"]},
    )

    response = request_backend(runtime, forged_token)

    assert response.status_code == 401


def test_spoofed_scope_cannot_bypass_authorization(runtime: Runtime) -> None:
    token_without_permission = mint_token(runtime, scope="profile")

    response = request_backend(
        runtime,
        token_without_permission,
        **{"x-authenticated-scope": "backend.read"},
    )

    assert response.status_code == 403
