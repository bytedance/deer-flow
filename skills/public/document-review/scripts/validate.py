#!/usr/bin/env python3
"""Prepare map-reduce prompts for reviewing large markdown documents.

Wraps chunked_convert (from markitdown skill) for token-aware chunking,
then emits ready-to-use map prompts per chunk plus a reduce prompt template
the agent fills in with map results.

CLI:  python validate.py <input.md> <output_dir/> [--chunk-size N]
Module:
    from validate import prepare_chunks
    result = prepare_chunks("/path/to/big.md", "/tmp/chunks/")
    for c in result["chunks"]:
        llm(system=c["map_prompt"]["system"], user=c["map_prompt"]["user"])
    reduce_user = result["reduce_prompt"]["user_template"].format(
        map_results_json=json.dumps(all_map_results),
        chunk_summaries=result["chunk_summaries"],
    )
    final = llm(system=result["reduce_prompt"]["system"], user=reduce_user)
"""
import argparse
import json
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_MARKITDOWN_SCRIPTS = (_THIS_DIR.parent.parent / "markitdown" / "scripts")
sys.path.insert(0, str(_MARKITDOWN_SCRIPTS))

from chunked_convert import chunked_convert

DEFAULT_CHUNK_SIZE = 1800


MAP_SYSTEM_PROMPT = """你是中文文档审校专家。当前任务审校文档的第 {chunk_index}/{total_chunks} 片段。

审校范围：
- 错别字、漏字、多字、语病、重复表达
- 标点误用、中英文标点混用
- 日期、金额、数字、单位格式不统一
- 标题层级、编号、表格、条款引用问题
- 主体名称、术语、引用前后一致性
- 敏感词、绝对化表达、广告法风险表达
- 合同条款中的合规风险（金额、日期、付款、交付、违约责任等）

重要约束（你只看到片段，看不到全文）：
- 只报本片段内能 100% 确认的问题
- 疑似需要前后文核实的，标 needs_global_check=true
- 不要报"全文格式不统一"这类需要全局视图的问题
- 合同类不判断"合法/违法"，只提示"存在风险/建议明确/建议法务确认"

严格按以下 JSON 格式输出，不要有任何 JSON 之外的文字：
{{
  "chunk_index": {chunk_index},
  "issues": [
    {{
      "line": <int>,
      "type": "<typo|grammar|punctuation|format|consistency|sensitive|compliance>",
      "severity": "<low|medium|high>",
      "description": "问题描述",
      "needs_global_check": <bool>
    }}
  ]
}}
"""

MAP_USER_PROMPT = """以下是文档片段（第 {chunk_index}/{total_chunks} 块）：

{chunk_content}

每行前缀是行号（"1: 文本" 表示这是第 1 行）。请用这些行号填入 JSON 的 line 字段。

请审校并返回 JSON。"""

REDUCE_SYSTEM_PROMPT = """你是中文文档审校汇总专家。负责把分段审校结果合并为**最终 markdown 报告**（不是 JSON，是直接给用户看的报告）。

任务：
1. 跨块去重（同一错别字在 chunk 边界被报两次）
2. 处理 needs_global_check=true 的问题（基于 chunk 章节覆盖信息做全局判断）
3. 检查跨块一致性：章节编号连续性、主体名称统一、术语一致、引用关系
4. 按风险等级排序（high → medium → low）

**严格按以下 markdown 格式输出**，不要有任何 JSON 或额外说明文字：

# 一、校验结论

[2-4 句：整体质量、主要问题、风险等级、优先修改事项]

# 二、问题清单

| 序号 | 位置 | 问题类型 | 原文 | 问题说明 | 风险等级 | 修改建议 |
|---|---|---|---|---|---|---|
| 1 | 第 X 块 第 Y 行 | typo | "原文片段" | 问题说明 | 高 | 修改建议 |
| 2 | ... | ... | ... | ... | ... | ... |

问题类型只使用：typo / grammar / punctuation / format / consistency / sensitive / compliance
风险等级只使用：高 / 中 / 低

# 三、跨块一致性发现

[基于 chunk 章节覆盖信息，列出跨块发现的章节编号问题、术语不一致、引用错误等]

# 四、关键修订稿

[只输出重点修改段落或条款；文档较短可输出完整修订稿，较长只输出关键修订]
"""

REDUCE_USER_PROMPT = """以下是文档分 {total_chunks} 块的审校结果：

## 分段审校结果（JSON 数组）
{map_results_json}

## 各 chunk 章节覆盖
{chunk_summaries}

请合并去重并生成最终汇总报告。"""


def _format_chunk_summaries(chunks: list[dict]) -> str:
    """Generate a human-readable summary of chunk coverage for the reduce stage.

    Each line: 第 N 块（M tokens）: <heading/section>
    Gives the reduce LLM enough context to do cross-chunk consistency checks
    (chapter numbering, terminology) and to verify needs_global_check issues
    without needing the full chunk text.
    """
    lines = []
    for c in chunks:
        section = c["section"].strip() or "(无标题)"
        lines.append(f"- 第 {c['index'] + 1} 块（{c['tokens']} tokens）：{section}")
    return "\n".join(lines)


def _number_lines(text: str) -> str:
    """Prefix each line with its 1-based line number, so LLM can reference positions."""
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(text.splitlines()))


def prepare_chunks(
    md_path: str,
    output_dir: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict:
    """切分 markdown 并准备 map-reduce prompts。

    Returns:
        {
            "_error": str or None,
            "chunks": [
                {
                    "index": int,
                    "path": str,        # chunk 文件路径
                    "tokens": int,
                    "section": str,
                    "map_prompt": {"system": str, "user": str}
                }, ...
            ],
            "reduce_prompt": {
                "system": str,
                "user_template": str   # 含 {map_results_json} 和 {chunk_summaries} 占位符
            },
            "total_chunks": int,
            "source_tokens": int
        }
    """
    md_p = Path(md_path)
    out_p = Path(output_dir)

    index = chunked_convert(str(md_p), str(out_p), max_tokens=chunk_size)

    if err := index.get("_error"):
        return {
            "_error": err,
            "chunks": [],
            "reduce_prompt": None,
            "total_chunks": 0,
            "source_tokens": 0,
        }

    total_chunks = index["total_chunks"]
    map_chunks = []
    for c in index["chunks"]:
        chunk_path = Path(c["path"])
        chunk_content = chunk_path.read_text(encoding="utf-8")

        map_chunks.append({
            "index": c["index"],
            "path": str(chunk_path),
            "tokens": c["tokens"],
            "section": c["section"],
            "map_prompt": {
                "system": MAP_SYSTEM_PROMPT.format(
                    chunk_index=c["index"] + 1,
                    total_chunks=total_chunks,
                ),
                "user": MAP_USER_PROMPT.format(
                    chunk_index=c["index"] + 1,
                    total_chunks=total_chunks,
                    chunk_content=_number_lines(chunk_content),
                ),
            },
        })

    reduce_prompt = {
        "system": REDUCE_SYSTEM_PROMPT,
        "user_template": REDUCE_USER_PROMPT.format(
            total_chunks=total_chunks,
            map_results_json="{map_results_json}",
            chunk_summaries="{chunk_summaries}",
        ),
    }

    return {
        "_error": None,
        "chunks": map_chunks,
        "reduce_prompt": reduce_prompt,
        "chunk_summaries": _format_chunk_summaries(map_chunks),
        "total_chunks": total_chunks,
        "source_tokens": index["source_tokens"],
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Prepare map-reduce prompts for document review (wraps chunked_convert)"
    )
    p.add_argument("source", help="Input markdown file path")
    p.add_argument("output_dir", help="Directory to write chunk files")
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    args = p.parse_args()

    result = prepare_chunks(args.source, args.output_dir, args.chunk_size)

    if err := result.get("_error"):
        print(f"[validate] ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
