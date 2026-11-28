PY ?= python3
export PYTHONPATH := src
export DEERFLOW_GOVERNANCE_CONFIG ?= governance.yaml

.PHONY: help install test demo validate simulate audit pending gate clean

help:
	@echo "make test      47 个核心层用例（不需要 DeerFlow / langchain / API key）"
	@echo "make demo      端到端演示：三态审批 + 指纹复用 + 授权隔离 + 预算熔断"
	@echo "make validate  校验 governance.yaml（可进 CI）"
	@echo "make gate      test + validate + demo，一条命令跑完全部离线验收"
	@echo "make pending   查看待审批队列"

install:
	$(PY) -m pip install -e .

test:
	$(PY) -m unittest discover -s tests -v

demo:
	$(PY) scripts/demo_flow.py

validate:
	$(PY) -m deerflow_governance.cli validate

pending:
	$(PY) -m deerflow_governance.cli pending

audit:
	$(PY) -m deerflow_governance.cli audit -n 40

gate: test validate demo
	@echo "\n离线验收全部通过"

clean:
	rm -rf data/*.db data/*.jsonl
	find . -name __pycache__ -type d -exec rm -rf {} +
