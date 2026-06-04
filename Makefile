.PHONY: help

# Check if 'uv' is installed
ifeq (, $(shell which uv))
$(error "uv is not installed. Please install it before running this Makefile.")
endif

# Default target - show available commands
help: # Show this help menu
	@echo "Available make commands:"
	@echo ""
	@awk 'BEGIN {FS = ":.*# "; printf "%-20s %s\n", "Target", "Description"} /^[a-zA-Z_-]+:.*# / {printf "%-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

dev: # Install development dependencies (editable install handled by uv sync)
	uv sync --all-groups

update:
	uv sync --upgrade --all-groups
	uv lock --upgrade

proto: # TODO: auto-generate proto files
	@echo "TODO"

clean: # Remove build artifacts and cache files
	rm -rf dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean dev # Build PyPI Package
	uv build

validate-wheel: build # Validate wheel packaging
	@./scripts/validate-wheel.sh

security-scans: # Run security scans (informational)
	uv pip install bandit[toml] --quiet
	uv run bandit -r src/ -ll -x "**/tests/**" || echo "Security scan completed with issues (informational)"

# Code intelligence targets
index: # Generate code intelligence index
	@echo "🔍 Indexing codebase..."
	@uv run python scripts/ast_to_sqlite.py

query: # Query symbols (usage: make query SYMBOL=name)
	@test -n "$(SYMBOL)" || (echo "Usage: make query SYMBOL=<name>" && exit 1)
	@uv run python scripts/code_intel.py find $(SYMBOL)

query-classes: # List all classes in codebase
	@uv run python scripts/code_intel.py list-all --kind class

query-all: # List all symbols in codebase
	@uv run python scripts/code_intel.py list-all

# Test commands
test: # Run all tests in parallel (auto-detect cores)
	uv run pytest tests/ -v -n auto

test-serial: # Run all tests serially (for debugging)
	uv run pytest tests/ -v

test-unit: # Run unit tests in parallel (auto-detect cores)
	uv run pytest tests/unit/ -v -n auto -m "not integration"

test-unit-serial: # Run unit tests serially (for debugging)
	uv run pytest tests/unit/ -v -m "not integration"

test-integration: # Run integration tests in parallel (auto-detect cores)
	uv run pytest tests/integration/ -v -n auto -m integration

test-integration-serial: # Run integration tests serially (for debugging)
	uv run pytest tests/integration/ -v -m integration

test-coverage: # Run tests with coverage report (parallel non-serial, then serial pass for state isolation)
	uv run pytest tests/ -v -n auto -m "not serial" --cov=runpod_flash --cov-report=xml
	uv run pytest tests/ -v -m "serial" --cov=runpod_flash --cov-append --cov-report=term-missing

test-coverage-serial: # Run tests with coverage report (serial execution)
	uv run pytest tests/ -v --cov=runpod_flash --cov-report=term-missing

test-fast: # Run tests with fast-fail mode and parallel execution
	uv run pytest tests/ -v -x --tb=short -n auto

test-workers: # Run tests with specific number of workers (e.g., WORKERS=4)
	uv run pytest tests/ -v -n $(WORKERS)

# Linting commands
lint: # Check code with ruff
	uv run ruff check .

lint-fix: # Fix code issues with ruff
	uv run ruff check . --fix

format: # Format code with ruff
	uv run ruff format .

format-check: # Check code formatting
	uv run ruff format --check .

# Type checking
typecheck: # Check types with mypy
	uv run mypy .

# Quality gates.
#
# - quality-check / quality-check-serial: aliases for ci-quality-github /
#   ci-quality-github-serial. These are the canonical CI gates. When invoked
#   locally you'll see GitHub Actions annotation markers (::group::,
#   --output-format=github) in the output -- inert outside Actions but
#   cosmetically noisy. The alias guarantees local and CI run the same recipe.
# - quality-check-strict: NOT an alias. Adds mypy typecheck on top of the
#   plain format/lint/test-coverage targets, with plain output (no annotation
#   markers, no JUnit XML). Use when you want stricter local feedback.
quality-check: ci-quality-github # Essential quality gate (parallel by default)
quality-check-strict: format-check lint typecheck test-coverage # Strict quality gate with type checking
quality-check-serial: ci-quality-github-serial # Serial quality gate for debugging

# GitHub Actions specific target -- canonical CI quality gate.
ci-quality-github: # Quality checks with GitHub Actions formatting (parallel by default)
	@echo "::group::Code formatting check"
	uv run ruff format --check .
	@echo "::endgroup::"
	@echo "::group::Linting"
	uv run ruff check . --output-format=github
	@echo "::endgroup::"
	@echo "::group::Test suite with coverage (parallel non-serial)"
	uv run pytest tests/ --junitxml=pytest-results-parallel.xml -v -n auto -m "not serial" --cov=runpod_flash --cov-report=xml --cov-fail-under=0
	@echo "::endgroup::"
	@echo "::group::Test suite with coverage (serial pass)"
	uv run pytest tests/ --junitxml=pytest-results-serial.xml -v -m "serial" --cov=runpod_flash --cov-append --cov-report=term-missing
	@echo "::endgroup::"

ci-quality-github-serial: # Serial quality checks for GitHub Actions (for debugging)
	@echo "::group::Code formatting check"
	uv run ruff format --check .
	@echo "::endgroup::"
	@echo "::group::Linting"
	uv run ruff check . --output-format=github
	@echo "::endgroup::"
	@echo "::group::Test suite with coverage (serial)"
	uv run pytest tests/ --junitxml=pytest-results.xml -v --cov=runpod_flash --cov-report=term-missing
	@echo "::endgroup::"
