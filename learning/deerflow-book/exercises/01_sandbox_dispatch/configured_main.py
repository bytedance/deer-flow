"""实作 01 进阶：根据配置创建实例，再交给同一个工具函数。

先实现 create_sandbox，再运行本文件。
这里使用教学类和 JSON 配置，不会启动真实容器。
"""

import json
from pathlib import Path

from main import read_with_tool
from sandbox_examples import ContainerSandboxDemo, LocalSandboxDemo


def create_sandbox(provider_name: str):
    """根据配置名称返回一个教学实例。"""
    # TODO：local 返回 LocalSandboxDemo 的实例。
    if (provider_name == "local"):
        sandbox = LocalSandboxDemo()
        return sandbox
    # TODO：container 返回 ContainerSandboxDemo 的实例。
    elif (provider_name == "container"):
        sandbox = ContainerSandboxDemo()
        return sandbox
    # TODO：其他名称抛出 ValueError，错误信息包含传入的名称。
    else:
        raise ValueError(f"不支持的执行环境：{provider_name}")


def main():
    config_path = Path(__file__).with_name("sandbox_config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))

    sandbox = create_sandbox(config["sandbox"]["provider"])
    result = read_with_tool(sandbox=sandbox, path=config["path"])

    print(f"实际实例类型：{type(sandbox).__name__}")
    print(result)


if __name__ == "__main__":
    main()
