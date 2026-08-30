.PHONY: test test-unit test-integration test-contract test-architecture test-e2e test-performance coverage mutation lint format-check check

PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PY := PYTHONPATH=src $(PYTHON)
RUN := $(PY) tests/run_suite.py

test:
	$(RUN) all

test-unit:
	$(RUN) unit

test-integration:
	$(RUN) integration

test-contract:
	$(RUN) contract

test-architecture:
	$(RUN) architecture

test-e2e:
	$(RUN) e2e

test-performance:
	$(RUN) performance

coverage:
	$(PY) -m coverage run --branch -m unittest discover tests -v
	$(PYTHON) -m coverage report -m

mutation:
	$(PYTHON) -m mutmut run

lint:
	$(PYTHON) -m ruff check src tests

format-check:
	$(PYTHON) -m ruff format --check src tests

check: lint format-check test
