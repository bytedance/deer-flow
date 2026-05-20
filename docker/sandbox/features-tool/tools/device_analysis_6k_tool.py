"""6K series device analysis tool (静设备腐蚀监测 PIPELINE, positionType 61..64).

Filters slim component tree to keep only points whose endpoint_series == "6k".
"""
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ins import InsApiClient, load_dotenv_file, load_ins_settings
from tools.device_analysis_2k_tool import _filter_node_by_series

ENDPOINT_SERIES = "6k"

load_dotenv_file()
INS_SETTINGS = load_ins_settings()
ins_client = InsApiClient(INS_SETTINGS)


async def get_device_children_6k(device_id: str) -> dict:
    if not INS_SETTINGS.username or not INS_SETTINGS.password:
        raise RuntimeError("缺少 INS_USERNAME 或 INS_PASSWORD 环境变量，无法登录 InS 接口")

    components = await ins_client.get_slim_components(device_id)
    filtered = [
        node
        for raw in components
        for node in [_filter_node_by_series(raw, ENDPOINT_SERIES)]
        if node is not None
    ]
    return {
        "device_id": device_id,
        "endpoint_series": ENDPOINT_SERIES,
        "child_device_list": filtered,
    }


async def close_clients() -> None:
    await ins_client.close()


async def main() -> None:
    if len(sys.argv) <= 1:
        raise SystemExit("用法: python device_analysis_6k_tool.py <设备ID>")
    try:
        result = await get_device_children_6k(sys.argv[1])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
