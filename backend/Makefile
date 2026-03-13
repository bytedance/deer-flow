install:
	uv sync

dev:
	bash -c 'source ../scripts/langgraph-dev-state.sh && reset_langgraph_dev_state "$$(cd .. && pwd)" && prepare_langgraph_dev_env && uv run langgraph dev --no-browser --allow-blocking --no-reload'

gateway:
	uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001

test:
	PYTHONPATH=. uv run pytest tests/ -v

lint:
	uvx ruff check .

format:
	uvx ruff check . --fix && uvx ruff format .
