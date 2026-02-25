install:
	uv sync

dev:
	uv run langgraph dev --no-browser --allow-blocking --no-reload

gateway:
	uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001

test:
	PYTHONPATH=. uv run pytest tests/ -v

lint:
	uvx ruff check .

format:
	uvx ruff check . --fix && uvx ruff format .
