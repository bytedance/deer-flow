import argparse
import asyncio
import json
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
    await ins_client.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch raw device tree for rotating diagnosis")
    parser.add_argument("device_id")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    try:
        result = await get_device_children(args.device_id)
        rendered = json.dumps(result, indent=2, ensure_ascii=False)
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
