import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from diagnosis.device_context_artifact import build_device_context_artifact
from ins import InsApiClient, load_dotenv_file, load_ins_settings
from diagnosis_rule.config import load_config

load_dotenv_file()
INS_SETTINGS = load_ins_settings()

ins_client = InsApiClient(INS_SETTINGS)

DEVICE_ANALYSIS_EXAMPLE_JSON = """
{
  "device_id": "设备ID",
  "child_device_summary": ["概括1", "概括2"],
  "device_type": {
    "value": "设备类型",
    "confidence": "high|medium|low",
    "reason": "依据"
  },
  "process_type": {
    "value": "工艺类型",
    "confidence": "high|medium|low",
    "reason": "依据"
  },
  "device_structure": {
    "value": "设备结构",
    "confidence": "high|medium|low",
    "reason": "依据"
  },
  "child_device_list": [
    {
      "id": "...",
      "name": "...",
      "system":"type_num为1时无此项。设备所属系统，可选项：动力部分|传动部分|工作部分",
      "type":"type_num为1时无此项。设备类型，可选项：汽轮机|离心式压缩机|多轴式压缩机|螺杆式压缩机|齿轮箱|烟气轮机|发电机|未知",
      "unit_type": 2,
      "type_num": 80,
      "children":[
        {
          "id": "...",
          "name": "...",
          "unit_type": 2,
          "type_num": 70,
          "direction":"方向，可选项：联端|非联端",
          "bearing_type":["轴承类型，多选，可选项：支撑轴承|推力轴承|无法推断"],
          "children":[
            {
              "id": "...",
              "name": "...",
              "unit_type": 3,
              "type_num": "",
              "h_alarm": "",
              "hh_alarm": "",
              "belongShaftId":"",
              "type":"type_num=83，名称不包含波形为轴振，名称包含波形为轴位移波形。type_num=81为键相，type_num=82需根据名称推断，可选项：润滑油温度|防喘振阀开度|压缩机进气参数|出口温度|入口流量|轴承温度|轴位移|其他工艺参数"
            }
          ]
        }
      ]
    }
  ]
}
""".strip()


class DeviceInferenceItem(BaseModel):
    value: str = Field(description="模型给出的结论")
    confidence: str = Field(description="置信度，如 high/medium/low")
    reason: str = Field(description="给出该结论的主要依据")


class DeviceAnalysisResult(BaseModel):
    device_id: str = Field(description="输入的设备ID")
    child_device_summary: list[str] = Field(description="对子设备树的简要概括")
    device_type: DeviceInferenceItem = Field(description="设备类型判断")
    process_type: DeviceInferenceItem = Field(
        default_factory=lambda: DeviceInferenceItem(value="", confidence="low", reason=""),
        description="工艺类型判断",
    )
    device_structure: DeviceInferenceItem = Field(
        default_factory=lambda: DeviceInferenceItem(value="", confidence="low", reason=""),
        description="设备结构判断",
    )
    child_device_list: list[dict[str, Any]] = Field(description="从 InS 系统获取并由模型整理后的子设备树")


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def _api_key() -> str:
    value = _env_first("OPENAI_API_KEY", "AI_API_KEY")
    if not value:
        raise RuntimeError("缺少 OPENAI_API_KEY 或 AI_API_KEY，无法执行 device_analysis LLM 推理")
    return value


def _base_url() -> str:
    value = _env_first("OPENAI_BASE_URL", "AI_BASE_URL", default="https://api.openai.com/v1")
    if value.endswith("/chat/completions"):
        return value
    return f"{value.rstrip('/')}/chat/completions"


def _model_name() -> str:
    return _env_first("DEVICE_ANALYSIS_MODEL", "OPENAI_MODEL", default="deepseek-v4-pro")


def _extract_content(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"LLM 返回中缺少 choices: {response_payload}")
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text") or ""))
        if text_parts:
            return "".join(text_parts)
    raise RuntimeError(f"无法解析 LLM 返回 content: {message}")


def _raw_tree_prompt(device_id: str, raw_payload: dict[str, Any]) -> str:
    return (
        f"请分析设备ID `{device_id}` 的原始子设备树，并严格输出一个合法 JSON 对象。\n"
        "要求：\n"
        "1. 必须输出字段：device_id, child_device_summary, device_type, process_type, device_structure, child_device_list。\n"
        "2. device_type/process_type/device_structure 必须是对象，字段为 value/confidence/reason。\n"
        "3. child_device_list 必须保留所有测点，不允许丢点。\n"
        "4. 当 type_num=82 时，原始列表可能不会挂在相应的 80/70 下，需要根据名称推理并挂到合适的已有位置；"
        "推力轴承一般在联端；如推理不出来或该测点属于整个机组，才放到机组下面。\n"
        "5. 当 type_num 为 82 且名称包含轴振/转速时，忽略该测点。\n"
        "6. 不要输出 markdown、解释文字或代码块，只输出 JSON。\n"
        "7. 允许根据树结构补充 system/type/direction/bearing_type/type 等标准字段。\n\n"
        f"输出模板：\n{DEVICE_ANALYSIS_EXAMPLE_JSON}\n\n"
        f"原始输入 JSON：\n{json.dumps(raw_payload, ensure_ascii=False)}"
    )


async def _chat_completion_content(system_prompt: str, user_prompt: str) -> str:
    request_payload = {
        "model": _model_name(),
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(_base_url(), headers=headers, json=request_payload)
        if response.status_code >= 400:
            retry_payload = dict(request_payload)
            retry_payload.pop("response_format", None)
            response = await client.post(_base_url(), headers=headers, json=retry_payload)
        response.raise_for_status()
        return _extract_content(response.json())


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
    raw_payload = await get_device_children(device_id)
    system_prompt = (
        "你是工业设备结构分析助手。"
        "你需要基于子设备名称、层级关系、unit_type、type_num 和点位分布，自主推理设备类型、工艺类型、设备结构。"
        "不要机械套固定规则，不要声称已知未提供的信息。"
        "先概括子设备树，再输出标准 JSON。"
    )
    content = await _chat_completion_content(system_prompt, _raw_tree_prompt(device_id, raw_payload))
    parsed = DeviceAnalysisResult.model_validate(json.loads(content))
    return parsed.model_dump(mode="python")


async def build_device_context(device_id: str, sub_device_id: str | None = None) -> dict[str, object]:
    analysis = await analyze_device(device_id)
    return build_device_context_artifact(analysis, load_config(), sub_device_id=sub_device_id)


async def close_clients() -> None:
    await ins_client.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Build rotating device context artifact with LLM inference")
    parser.add_argument("device_id")
    parser.add_argument("sub_device_id", nargs="?")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    try:
        result = await build_device_context(args.device_id, sub_device_id=args.sub_device_id)
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
