SHELL := /bin/sh
.DEFAULT_GOAL := help

UV ?= uv
HOST ?= 0.0.0.0
AUTHZ_PORT ?= 8000
BACKEND_PORT ?= 8081
ENVOY_CONFIG ?= envoy.yaml

.PHONY: help sync authz backend services envoy test lint format-check envoy-validate check

help:
	@printf '%s\n' \
		'make services        Run the authorization and backend services together' \
		'make authz           Run only the authorization service' \
		'make backend         Run only the backend service' \
		'make envoy           Run Envoy with the project configuration' \
		'make check           Run all validation checks'

sync:
	$(UV) sync

authz: sync
	$(UV) run uvicorn envoy_authz.app:app --host $(HOST) --port $(AUTHZ_PORT)

backend: sync
	$(UV) run uvicorn backend_server.app:app --host $(HOST) --port $(BACKEND_PORT)

services: sync
	@set -e; \
	authz_pid=''; \
	backend_pid=''; \
	cleanup() { \
		test -z "$$authz_pid" || kill "$$authz_pid" 2>/dev/null || true; \
		test -z "$$backend_pid" || kill "$$backend_pid" 2>/dev/null || true; \
		wait 2>/dev/null || true; \
	}; \
	stop() { cleanup; trap - EXIT; exit 0; }; \
	trap stop INT TERM; \
	trap cleanup EXIT; \
	$(UV) run uvicorn envoy_authz.app:app --host $(HOST) --port $(AUTHZ_PORT) & authz_pid=$$!; \
	$(UV) run uvicorn backend_server.app:app --host $(HOST) --port $(BACKEND_PORT) & backend_pid=$$!; \
	wait "$$authz_pid" "$$backend_pid"

envoy:
	envoy -c $(ENVOY_CONFIG)

test:
	$(UV) run pytest

lint:
	$(UV) run ruff check .

format-check:
	$(UV) run ruff format --check .

envoy-validate:
	envoy --mode validate -c $(ENVOY_CONFIG)

check:
	$(UV) lock --check
	$(MAKE) test
	$(MAKE) lint
	$(MAKE) format-check
	$(MAKE) envoy-validate
