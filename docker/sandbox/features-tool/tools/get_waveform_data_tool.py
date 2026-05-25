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


async def _get_waveform_data_impl(component_id: str, time: str, endpoint_series: str = "8k") -> dict[str, object]:
    time_ms = datetime_input_to_ms(time)
    data = await ins_client.get_waveform_data(component_id, time_ms, endpoint_series=endpoint_series)
    return {
        "component_id": component_id,
        "time_ms": time_ms,
        "data": data,
    }


async def get_waveform_data_tool(component_id: str, time: str) -> dict[str, object]:
    """
    获取指定测点某个时间点的波形图和频谱图数据。
    """
    return await _get_waveform_data_impl(component_id, time)


async def close_clients() -> None:
    await ins_client.close()


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit("用法: python get_waveform_data_tool.py <component_id> <time>")

    try:
        result = await _get_waveform_data_impl(sys.argv[1], sys.argv[2])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    finally:
        await close_clients()


if __name__ == "__main__":
    asyncio.run(main())
