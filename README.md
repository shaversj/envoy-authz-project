# Envoy JWT authentication and external authorization example

This project demonstrates an Envoy security chain with three small FastAPI
services:

- `jwt_issuer` is a development-only identity provider. It generates an RSA key
  in memory, publishes its public JWKS, and mints short-lived demo tokens.
- `envoy_authz` implements Envoy's HTTP `ext_authz` contract and requires the
  `backend.read` scope.
- `backend_server` is the protected upstream service.

Envoy handles authentication before authorization:

```text
client -> jwt_authn -> ext_authz -> backend
```

The `jwt_authn` filter verifies the signature, issuer, audience, and token
lifetime. It removes any client-supplied identity headers, then copies only the
verified `sub` and `scope` claims into `x-authenticated-subject` and
`x-authenticated-scope`. The HTTP `ext_authz` filter sends those two headers to
the authorization service and does not forward the bearer token.

## Run locally with Make

Start each component in a separate terminal:

```bash
# Terminal 1
make issuer

# Terminal 2
make authz

# Terminal 3
make backend

# Terminal 4
make envoy
```

Envoy listens on `127.0.0.1:8080`. Press `Ctrl+C` in each terminal to stop its
process. Start the issuer before Envoy so the first JWKS fetch succeeds.

Available targets:

| Command | Purpose |
| --- | --- |
| `make` or `make help` | Show the main commands |
| `make sync` | Install and synchronize Python dependencies with `uv` |
| `make issuer` | Run the development JWT issuer on port 8002 |
| `make authz` | Run the authorization service on port 8000 |
| `make backend` | Run the backend on port 8081 |
| `make envoy` | Run Envoy with `envoy.yaml` |
| `make test` | Run unit and Envoy integration tests |
| `make lint` | Run Ruff lint checks |
| `make format-check` | Check Python formatting |
| `make envoy-validate` | Validate the Envoy configuration |
| `make check` | Run all project validation checks |

Make variables can override the local defaults:

```bash
make issuer HOST=127.0.0.1 ISSUER_PORT=8002
make authz HOST=127.0.0.1 AUTHZ_PORT=8000
make backend HOST=127.0.0.1 BACKEND_PORT=8081
make envoy ENVOY_CONFIG=envoy.yaml
```

Configuration is read when each application starts:

| Variable | Default | Purpose |
| --- | --- | --- |
| `JWT_ISSUER_URL` | `http://127.0.0.1:8002` | Issuer claim and JWKS base URL |
| `JWT_AUDIENCE` | `envoy-demo` | Audience placed in demo tokens |
| `AUTHZ_REQUIRED_SCOPE` | `backend.read` | Scope required by the policy |
| `AUTHZ_UPSTREAM_HEADER_VALUE` | `some value` | Value added to allowed upstream requests |

The issuer creates a new in-memory signing key every time it starts. Previously
minted tokens stop working after an issuer restart and Envoy refreshes its JWKS.
The issuer is for local testing only; use a real OpenID Connect provider in
production.

## Call the protected backend

Mint a token with the required scope:

```bash
TOKEN="$(
  curl -s -X POST \
    'http://127.0.0.1:8002/token?subject=demo-user&scope=backend.read' \
  | uv run python -c \
    'import json, sys; print(json.load(sys.stdin)["access_token"])'
)"
```

Call Envoy:

```bash
curl -i \
  -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8080/
```

A valid token with `backend.read` returns `200 OK`. Authentication failures are
rejected before the authorization service runs:

```bash
# Missing token: 401
curl -i http://127.0.0.1:8080/

# Expired token: 401
EXPIRED_TOKEN="$(
  curl -s -X POST \
    'http://127.0.0.1:8002/token?expires_in=-300' \
  | uv run python -c \
    'import json, sys; print(json.load(sys.stdin)["access_token"])'
)"
curl -i -H "Authorization: Bearer $EXPIRED_TOKEN" http://127.0.0.1:8080/
```

A valid identity without the required permission is authenticated but forbidden:

```bash
UNPRIVILEGED_TOKEN="$(
  curl -s -X POST \
    'http://127.0.0.1:8002/token?subject=demo-user&scope=profile' \
  | uv run python -c \
    'import json, sys; print(json.load(sys.stdin)["access_token"])'
)"
curl -i \
  -H "Authorization: Bearer $UNPRIVILEGED_TOKEN" \
  http://127.0.0.1:8080/
```

That request returns `403 Forbidden`: authentication succeeded, but
`ext_authz` denied the policy check.

## Security properties demonstrated

- `jwt_authn` runs before `ext_authz`.
- JWTs must have a valid signature, issuer, audience, and lifetime.
- The bearer token is not forwarded to the authorization service.
- Client-supplied `x-authenticated-subject` and `x-authenticated-scope` values
  are stripped before verified claims are inserted.
- The authorization service returns `401` when verified identity is missing and
  `403` when identity is valid but `backend.read` is absent.
- `failure_mode_allow: false` fails closed when the authorization service is
  unavailable.

The authorization service must remain on an internal network. Calling it
directly bypasses the Envoy filter that creates the trusted identity headers.

## Validate changes

```bash
make check
```

The integration suite starts the issuer, authorization service, backend, and a
real Envoy process on temporary ports. It covers valid tokens, missing and
expired tokens, wrong issuer or audience, invalid signatures, and spoofed
identity headers. Integration tests are skipped only when the Envoy executable
is unavailable; `make envoy-validate` also requires Envoy.

See Envoy's
[JWT authentication filter documentation](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/jwt_authn_filter),
[external authorization filter documentation](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter),
and
[v3 HTTP authorization API](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/ext_authz/v3/ext_authz.proto.html#extensions-filters-http-ext-authz-v3-httpservice).

## Container image

The existing images run the authorization and backend services. The development
issuer is intended to run locally with `make issuer`.

```bash
docker build -t envoy-fastapi-authz .
docker run --rm -p 8000:8000 \
  -e AUTHZ_REQUIRED_SCOPE=backend.read \
  envoy-fastapi-authz

docker build -f Dockerfile.backend -t envoy-fastapi-backend .
docker run --rm -p 8081:8081 envoy-fastapi-backend
```
