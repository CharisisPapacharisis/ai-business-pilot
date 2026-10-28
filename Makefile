PYTHON := uv run python
RUFF := uv run ruff

.PHONY: help sync seed ui test mcp-dev lint fix check

help:
	@echo make sync     - Install or update the locked environment
	@echo make seed     - Recreate the fictional DuckDB database
	@echo make ui       - Start the Streamlit application
	@echo make test     - Run the automated pytest suite
	@echo make mcp-dev  - Inspect the DuckDB MCP server interactively
	@echo make lint     - Check Ruff linting and formatting
	@echo make fix      - Apply safe Ruff fixes and formatting
	@echo make check    - Run linting, formatting checks, and tests

sync:
	uv sync

seed:
	$(PYTHON) scripts/seed_database.py

ui:
	uv run streamlit run streamlit_app.py

test:
	uv run pytest -q

mcp-dev:
	uv run mcp dev mcp_servers/duckdb_server.py

lint:
	$(RUFF) check .
	$(RUFF) format --check .

fix:
	$(RUFF) check --fix .
	$(RUFF) format .

check: lint test
