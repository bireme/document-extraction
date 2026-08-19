.PHONY: test lint check

PY := PYTHONPATH=src python3

test:
	$(PY) -m unittest discover -s tests -p 'test_*.py' -v

lint:
	ruff check src tests

check: lint test
