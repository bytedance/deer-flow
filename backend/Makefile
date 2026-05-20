install:
	uv sync

dev:
	PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload

gateway:
	PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001

test:
	PYTHONPATH=. uv run pytest tests/ -v --ignore=tests/recall_l2

# L2 召回评测 —— 真实 embedding + 标注集 + IR 指标。
# 不接 PR,只本地手动 / GitHub workflow_dispatch 跑。详见 tests/recall_l2/README.md
eval-recall:
	PYTHONPATH=. uv run python tests/recall_l2/eval_recall.py

eval-recall-update-baseline:
	PYTHONPATH=. uv run python tests/recall_l2/eval_recall.py --update-baseline

lint:
	uvx ruff check .
	uvx ruff format --check .

format:
	uvx ruff check . --fix && uvx ruff format .
