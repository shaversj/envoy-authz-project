FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.10.12 /uv /uvx /bin/

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY envoy_authz ./envoy_authz

EXPOSE 8000

CMD ["uvicorn", "envoy_authz.app:app", "--host", "0.0.0.0", "--port", "8000"]

