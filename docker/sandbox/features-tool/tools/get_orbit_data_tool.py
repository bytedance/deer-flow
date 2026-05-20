import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ins import InsApiClient, load_dotenv_file, load_ins_settings
from ins.client import datetime_input_to_ms

load_dotenv_file()
INS_SETTINGS = load_ins_settings()

ins_client = InsApiClient(INS_SETTINGS)


async def _get_orbit_data_impl(
    machine_id: str,
    bearing_id: str,
    time: str,
    probe_ids: list[str] | None = None,
) -> dict[str, object]:
    time_ms = datetime_input_to_ms(time)
    data = await ins_client.get_orbit_data(machine_id, bearing_id, time_ms, probe_ids=probe_ids)
    return {
        "machine_id": machine_id,
        "bearing_id": bearing_id,
        "time_ms": time_ms,
        "probe_ids": data.get("probe_ids") or [],
        "data": data,
    }


async def get_orbit_data_tool(machine_id: str, bearing_id: str, time: str) -> dict[str, object]:
    """
    获取指定机组下轴承在某个时间点的轴心轨迹数据。
    """
    return await _get_orbit_data_impl(machine_id, bearing_id, time)


async def close_clients() -> None:
    await ins_client.close()


async def main() -> None:
    if len(sys.argv) < 4:
        raise SystemExit("用法: python get_orbit_data_tool.py <machine_id> <bearing_id> <time>")

    try:
        result = await _get_orbit_data_impl(sys.argv[1], sys.argv[2], sys.argv[3])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
