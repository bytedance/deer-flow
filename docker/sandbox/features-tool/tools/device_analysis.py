import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ins import InsApiClient, load_dotenv_file, load_ins_settings

load_dotenv_file()
INS_SETTINGS = load_ins_settings()

ins_client = InsApiClient(INS_SETTINGS)


async def get_device_children(device_id: str) -> dict[str, object]:
    """
    根据设备 ID 获取 InS 系统中的子设备树。

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
    await ins_client.close()


async def main() -> None:
    if len(sys.argv) <= 1:
        raise SystemExit("用法: python device_analysis.py <设备ID>")

    try:
        result = await get_device_children(sys.argv[1])
        import json

        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
