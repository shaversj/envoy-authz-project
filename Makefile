SHELL := /bin/sh
.DEFAULT_GOAL := help

UV ?= uv
HOST ?= 0.0.0.0
AUTHZ_PORT ?= 8000
BACKEND_PORT ?= 8081
ENVOY_CONFIG ?= envoy.yaml

.PHONY: help sync authz backend envoy test lint format-check envoy-validate check

help:
	@printf '%s\n' \
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
