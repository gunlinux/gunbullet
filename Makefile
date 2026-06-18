.PHONY: dev
dev: ## Install dev dependencies
	uv sync --dev
	uv run uvicorn main:app_asgi

check: lint fix types test
	echo "check"

types:
	uv run pyright 


.PHONY: lint
lint:  ## Run linters
	uv run ruff check

.PHONY: fix
fix:  ## Fix lint errors
	uv run ruff check --fix
	uv run ruff format

.PHONY: test
test: ## Run tests with coverage
	uv run pytest

.PHONY: bench
bench: ## Run in-process performance microbenchmarks
	uv run pytest benchmarks/ --benchmark-columns=min,mean,median,ops


