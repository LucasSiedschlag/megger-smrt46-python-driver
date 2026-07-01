
PYTHON ?= python3
SRC := smrt46_client tests tools
DIST_DIR := dist

.PHONY: help install-dev test lint format typecheck check build clean clean-build \
	probe bench-current bench-voltage bench-curve

help:
	@echo "Targets:"
	@echo "  install-dev       Install package with dev dependencies"
	@echo "  test              Run unit tests"
	@echo "  lint              Run ruff checks"
	@echo "  format            Run ruff formatter"
	@echo "  typecheck         Run mypy"
	@echo "  check             Run test, lint, and typecheck"
	@echo "  build             Build a wheel into dist/"
	@echo "  clean             Remove generated artifacts"
	@echo "  probe             Run SMRT46 connection probe"
	@echo "  bench-current     Run a compact C1 3A current smoke test"
	@echo "  bench-voltage     Run the V2 50V voltage bench shape"
	@echo "  bench-curve       Run a compact phase A curve bench shape"

install-dev:
	$(PYTHON) -m pip install -e .[dev]

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m ruff check $(SRC)

format:
	$(PYTHON) -m ruff format $(SRC)
	$(PYTHON) -m ruff check --fix $(SRC)

typecheck:
	$(PYTHON) -m mypy

check: test lint typecheck

clean-build:
	rm -rf build $(DIST_DIR) *.egg-info

build: clean-build
	$(PYTHON) -m pip wheel --no-deps --no-build-isolation -w $(DIST_DIR) .

clean: clean-build
	rm -rf .mypy_cache .ruff_cache .pytest_cache .code-review-graph
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

probe:
	$(PYTHON) -m tools.smrt46_connection_probe --target default --verbose

bench-current:
	$(PYTHON) -m tools.smrt46_run_current_injection --target default --current 1:3.0:0 --frequency 60 --poll-count 1 --only-current-time

bench-voltage:
	$(PYTHON) -m tools.smrt46_run_voltage_test --target default --voltage 2:50.0:120 --stop-mode binary_input --target-bin 1

bench-curve:
	$(PYTHON) -m tools.smrt46_run_curve_test --target default --phase A --start 4.0 --stop 4.2 --step 0.1 --only-current-time
