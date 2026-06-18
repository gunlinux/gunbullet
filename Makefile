.PHONY: dev
dev: ## Install dev dependencies
	uv sync --dev
	uv run uvicorn main:app_asgi --loop uvloop --workers 4

.PHONY: dev-rsgi
dev-rsgi: ## Run the app under Granian's RSGI interface (Rust HTTP core)
	uv run granian --interface rsgi main:app_asgi --workers 4 --no-ws

.PHONY: dev-asgi
dev-asgi: ## Run the app under Granian's RSGI interface (Rust HTTP core)
	uv run granian --interface asgi main:app_asgi --workers 4 --no-ws


.PHONY: build
build: ## Compile the Rust router and install it editable into the venv
	uv run maturin develop --release

.PHONY: rust-test
rust-test: ## Run the native Rust router unit tests
	cargo test --release

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

.PHONY: bench-servers
bench-servers: ## Load-compare uvicorn/ASGI vs granian/ASGI vs granian/RSGI (needs wrk)
	sh bench_servers.sh


