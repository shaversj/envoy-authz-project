# Envoy HTTP external authorization example

Two small FastAPI services demonstrate Envoy external authorization end to end:

- `envoy_authz` implements Envoy's HTTP `ext_authz` contract.
- `backend_server` is the protected upstream service.

The authorization service mirrors the behavior of the referenced Go example
while using Envoy's native HTTP authorization transport:

- `Authorization: Bearer foo` returns `200 OK` and adds
  `x-custom-header-from-authz: some value` to the upstream request.
- A wrong token returns `401 Unauthorized` with `PERMISSION_DENIED`.
- A missing or malformed authorization header returns `401 Unauthorized`.

This is a deliberately simple example. Replace the static token check with your
real policy before using it in production.

## Run the service

```bash
uv sync
uv run uvicorn envoy_authz.app:app --host 0.0.0.0 --port 8000
```

Configuration is read when the application starts:

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTHZ_BEARER_TOKEN` | `foo` | Token accepted by the demo policy |
| `AUTHZ_UPSTREAM_HEADER_VALUE` | `some value` | Value forwarded to the upstream service |

The service exposes:

- `GET /healthz` for health checks
- `/authorize` for Envoy authorization checks; all common HTTP methods are
  accepted because Envoy preserves the original request method

## Run the backend

```bash
uv run uvicorn backend_server.app:app --host 0.0.0.0 --port 8081
```

The backend accepts requests on any path, returns `ok`, and adds
`x-custom-header-from-backend: from backend` to its response. It logs request
methods, paths, and header names without logging authorization header values.

## Try it directly

```bash
curl -i http://127.0.0.1:8000/authorize
curl -i -H 'Authorization: Bearer bar' http://127.0.0.1:8000/authorize
curl -i -H 'Authorization: Bearer foo' http://127.0.0.1:8000/authorize
```

## Run with Envoy

The included [`envoy.yaml`](envoy.yaml) expects:

- this service at `127.0.0.1:8000`
- an HTTP backend at `127.0.0.1:8081`
- Envoy ingress at `127.0.0.1:8080`

For a local demonstration, use three terminals:

```bash
# Terminal 1: authorization service
uv run uvicorn envoy_authz.app:app --host 127.0.0.1 --port 8000

# Terminal 2: protected backend
uv run uvicorn backend_server.app:app --host 127.0.0.1 --port 8081

# Terminal 3: Envoy
envoy -c envoy.yaml
```

Then call Envoy:

```bash
curl -i http://127.0.0.1:8080/
curl -i -H 'Authorization: Bearer foo' http://127.0.0.1:8080/
```

Envoy treats a `200` response from the authorization service as allow and any
other status as deny. The `allowed_upstream_headers` matcher in `envoy.yaml`
copies `x-custom-header-from-authz` from the authorization response into the
request sent to the backend. See Envoy's
[external authorization filter documentation](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter)
and
[v3 HTTP service API](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/ext_authz/v3/ext_authz.proto.html#extensions-filters-http-ext-authz-v3-httpservice).

## Validate changes

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Container image

```bash
docker build -t envoy-fastapi-authz .
docker run --rm -p 8000:8000 \
  -e AUTHZ_BEARER_TOKEN=foo \
  envoy-fastapi-authz

docker build -f Dockerfile.backend -t envoy-fastapi-backend .
docker run --rm -p 8081:8081 envoy-fastapi-backend
```

