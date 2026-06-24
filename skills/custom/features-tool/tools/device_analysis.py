import argparse
import asyncio
import json
import sys
from pathlib import Path

# 添加 features-tool 到 sys.path（ins 模块 + tools 包）
_FEATURES_TOOL_ROOT = Path(__file__).resolve().parent.parent
if str(_FEATURES_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_FEATURES_TOOL_ROOT))

from ins import InsApiClient, close_shared_http_client, load_dotenv_file, load_ins_settings

load_dotenv_file()
INS_SETTINGS = load_ins_settings()

ins_client = InsApiClient(INS_SETTINGS)


async def get_device_children(device_id: str) -> dict[str, object]:
    """
    根据设备 ID 获取 InS 系统中的原始子设备树。

    Args:
        device_id: 设备 ID，对应 InS 系统中的 machineIds 参数。
    """
    return {
        "device_id": device_id,
        "child_device_list": await ins_client.get_slim_components(device_id),
    }


async def analyze_device(device_id: str) -> dict[str, object]:
    return await get_device_children(device_id)


async def close_clients() -> None:
    await close_shared_http_client()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch raw device tree for rotating diagnosis")
    parser.add_argument("device_id")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    try:
        result = await get_device_children(args.device_id)
        child_device_list = result.get("child_device_list", [])

        # 构造一个完整的树根节点，符合 build_device_context.py 的期望格式
        # build_device_context.py 期望输入有 id/name/unit_type/type_num/children 字段
        # 如果 API 返回空列表，说明设备不存在或无权限
        if not child_device_list:
            root_node = {
                "id": "",
                "name": "",
                "unit_type": 1,
                "type_num": 1,
                "children": [],
                "_error": f"设备 {args.device_id} 在组织树中不存在或无访问权限",
            }
        else:
            # 构造虚拟根节点，把 child_device_list 作为 children
            root_node = {
                "id": args.device_id,
                "name": "",  # 设备名称需要 LLM 从其他来源获取
                "unit_type": 1,  # 1 = 设备（machine）
                "type_num": 1,   # 1 = 机器根节点
                "children": child_device_list,
            }

        rendered = json.dumps(root_node, indent=2, ensure_ascii=False)
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            print(json.dumps({"output": str(output_path), "device_id": args.device_id}, ensure_ascii=False))
        else:
            print(rendered)
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
