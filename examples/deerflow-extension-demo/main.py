#!/usr/bin/env python3
"""DeerFlow MySQL 工具 POC。

演示如何将自定义工具和自定义 Prompt 集成到 DeerFlow Agent 中。
"""

import os
import sys
import warnings
from pathlib import Path

# 忽略 Pydantic 序列化警告
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

# 设置 API Key
os.environ["DEEPSEEK_API_KEY"] = "sk-fb8ee523da134a109264669d05536b78"

# 设置配置文件路径
BASE_DIR = Path(__file__).parent
os.environ["DEER_FLOW_CONFIG_PATH"] = str(BASE_DIR / "config.yaml")
os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = str(BASE_DIR / "extensions_config.json")

# 设置 DEER_FLOW_HOME，让 DeerFlow 能找到自定义 agent
os.environ["DEER_FLOW_HOME"] = str(BASE_DIR)

# 添加当前目录到 Python 路径（确保能找到 mysql_tools）
sys.path.insert(0, str(Path(__file__).parent))


def main():
    """运行 FastAPI 服务。"""
    print("=" * 60)
    print("DeerFlow MySQL 助手 - FastAPI 服务")
    print("=" * 60)
    print()
    print("API 文档: http://localhost:8100/docs")
    print("健康检查: http://localhost:8100/health")
    print()
    print("API 端点:")
    print("  POST /chat    - 发送消息获取完整响应")
    print("  POST /stream  - 流式返回对话事件")
    print("  GET  /models  - 列出可用模型")
    print("  GET  /skills  - 列出可用技能")
    print()
    print("按 Ctrl+C 停止服务")
    print("=" * 60)

    import uvicorn

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8100,
        reload=True,
    )


if __name__ == "__main__":
    main()
