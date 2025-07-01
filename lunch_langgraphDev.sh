source /mnt/afs/yaotiankuo/agents/deer-main-dev/.venv/bin/activate
# 安装依赖
uv pip install -e .
# uv pip install -U "langgraph-cli[inmem]"

# 启动LangGraph服务器
langgraph dev