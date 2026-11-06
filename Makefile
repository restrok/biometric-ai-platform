.DEFAULT_GOAL := help
SHELL := /bin/bash
export PATH := $(HOME)/.local/bin:$(PATH)
API_DIR := api
UV ?= $(shell command -v uv 2>/dev/null || echo $$HOME/.local/bin/uv) --directory $(API_DIR)

.PHONY: help setup format lint test security check docker-build docker-up docker-down clean

help: ## Show this help message with available targets
	@echo "Usage: make [target] (or 'make -j check' for parallel checks)"
	@echo ""
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## Sync dependencies with uv and install pre-commit hooks
	$(UV) sync --all-groups
	$(UV) run pre-commit install
	$(UV) run pre-commit install --hook-type commit-msg

format: ## Run ruff format and ruff check --fix
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

lint: ## Run ruff check and mypy type checks
	$(UV) run ruff check .
	$(UV) run mypy .

test: ## Run test suite with parallel pytest-xdist and coverage
	$(UV) run pytest

security: ## Run pip-audit, gitleaks, and ruff SAST check
	$(UV) run ruff check --select S --extend-ignore S608,S104 .
	$(UV) run pip-audit --ignore-vuln PYSEC-2026-3467 --ignore-vuln PYSEC-2026-3046 --ignore-vuln PYSEC-2026-2447
	@if command -v gitleaks > /dev/null 2>&1; then \
		echo "Running gitleaks detect..."; \
		gitleaks detect --source . --verbose; \
	elif [ -f $(API_DIR)/.venv/bin/gitleaks ]; then \
		$(API_DIR)/.venv/bin/gitleaks detect --source . --verbose; \
	else \
		echo "Running pre-commit gitleaks hook..."; \
		$(UV) run pre-commit run gitleaks --all-files || true; \
	fi

check: lint security test ## Run lint, security, and test (supports 'make -j check')

docker-build: ## Build API container image locally
	docker compose -f docker-compose.example.yml build

docker-up: ## Start API service with docker compose
	docker compose -f docker-compose.example.yml up -d

docker-down: ## Stop API service with docker compose
	docker compose -f docker-compose.example.yml down

clean: ## Clean up caches, coverage, and build artifacts
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -f $(API_DIR)/.coverage $(API_DIR)/coverage.xml
