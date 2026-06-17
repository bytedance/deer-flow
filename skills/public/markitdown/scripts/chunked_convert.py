#!/usr/bin/env python3
"""Split large markitdown output into LLM-sized chunks for map-reduce processing.

修复自 review 的问题：
  1. 单行/单段 > max_tokens → 按 token 强制切
  2. code block 边界 → 不在 fenced code 内部切
  3. code block 内的 # 不算 heading → 状态机隔离
  4. setext heading (===/---) → 兼容
  5. CONTEXT_HEADER_TOKENS 实际生效 → 上一 chunk 末尾 heading 作为下一 chunk 的 context 头
  6. 结构化输出 → .index.json 而非 .index 文本
  7. 结构化错误返回 → 失败时返回 {"error": ..., "chunks": []}
  8. 基础错误处理
  9. 整张 markdown 表格不切（策略 A1），单表过大时 stderr warning
"""
import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import tiktoken
from markitdown import MarkItDown

# ============================================================================
# 可调常量（手动改这里就行）
# ============================================================================
CHUNK_SIZE = 1600        # 每块最大 tokens
CONTEXT_HEADER_TOKENS = 50     # 上一 chunk 末尾 heading 作为下一 chunk context 头的 token 上限
TOKEN_ENCODING = "cl100k_base"
# ============================================================================


@dataclass
class ChunkMeta:
    path: str
    index: int
    tokens: int
    section: str


def _enc():
    return tiktoken.get_encoding(TOKEN_ENCODING)


def count_tokens(text: str) -> int:
    return len(_enc().encode(text))


def _is_atx_heading(line: str) -> bool:
    return bool(re.match(r"^#{1,6}\s", line))


def _is_setext_underline(line: str) -> int:
    """返回 setext 级别 (1/2)，不是下划线返回 0。
    CommonMark: 下划线允许 0-3 个前导空格缩进。"""
    if re.match(r"^[ ]{0,3}=+\s*$", line):
        return 1
    if re.match(r"^[ ]{0,3}-+\s*$", line):
        return 2
    return 0


def _is_code_fence(line: str) -> bool:
    """是否 fenced code block 的开/闭 fence。
    CommonMark: 0-3 个前导空格。4+ 空格或 tab 开头是 indented code block，不是 fence。"""
    i = 0
    while i < len(line) and line[i] == " ":
        i += 1
    if i >= 4:
        return False
    if i < len(line) and line[i] == "\t":
        return False
    s = line.lstrip()
    return s.startswith("```") or s.startswith("~~~")


def _detect_setext_heading(lines: list[str], i: int) -> str:
    """检查 lines[i] 是否是 setext heading 的标题行。
    返回完整 heading 文本（含下划线），不是返回空串。
    排除 list item 后的 ---（那是水平线不是 setext 下划线）。"""
    if i + 1 >= len(lines):
        return ""
    level = _is_setext_underline(lines[i + 1])
    if not level:
        return ""
    prev = lines[i]
    if not prev.strip():
        return ""
    if re.match(r"^\s*([-*+]|\d+\.)\s", prev):
        return ""
    return prev + lines[i + 1]


def is_table_line(line: str) -> bool:
    """一行是不是 markdown 表格行（以 | 开头，≥ 2 个 |）。"""
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def is_table_separator(line: str) -> bool:
    """是不是 | --- | --- | 这种分隔行（兼容 :---: 对齐语法）。"""
    s = line.strip()
    if "|" not in s or "-" not in s:
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    return len(cells) >= 1 and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def extract_table_block(lines: list[str], i: int) -> tuple[list[str], int]:
    """从 lines[i] 起收集连续的表格行。返回 (table_lines, 消费的 line 数)。"""
    block = []
    j = i
    while j < len(lines) and is_table_line(lines[j]):
        block.append(lines[j])
        j += 1
    return block, j - i


def split_into_chunks(
    text: str, max_tokens: int, context_header_tokens: int
) -> list[tuple[str, str]]:
    """核心切分。

    返回 [(section_header, body), ...]:
    - section_header: 当前 chunk 最近一次 heading 文本（用于 context 串接）
    - body: 实际 markdown 内容

    不变量：
    - 不在 fenced code block 内部切
    - code block 内的 # 不被识别为 heading
    - 单行/单段 > max_tokens 时按 token 强制切
    - 切点优先选在 heading 边界
    - 整张 markdown 表格不切（策略 A1），单表过大时 stderr warning
    """
    lines = text.splitlines(keepends=True)
    chunks: list[tuple[str, str]] = []
    cur_lines: list[str] = []
    cur_tokens = 0
    cur_section = ""
    in_code = False

    def commit() -> None:
        nonlocal cur_lines, cur_tokens, cur_section
        if cur_lines:
            chunks.append((cur_section, "".join(cur_lines)))
            cur_lines = []
            cur_tokens = 0
            cur_section = ""

    def emit_oversized(line: str) -> None:
        ids = _enc().encode(line)
        for start in range(0, len(ids), max_tokens):
            sub = _enc().decode(ids[start:start + max_tokens])
            chunks.append((cur_section, sub))

    i = 0
    while i < len(lines):
        line = lines[i]

        # 1. code fence（toggle 状态机）
        if _is_code_fence(line):
            in_code = not in_code
            cur_lines.append(line)
            cur_tokens += count_tokens(line)
            i += 1
            continue

        # 2. code block 内部：只追加，永不切
        if in_code:
            cur_lines.append(line)
            cur_tokens += count_tokens(line)
            i += 1
            continue

        # 2.5 表格块：整表不切（策略 A1）
        if is_table_line(line):
            block, consumed = extract_table_block(lines, i)
            block_text = "".join(block)
            block_tokens = count_tokens(block_text)

            if cur_lines and cur_tokens + block_tokens > max_tokens:
                commit()

            if block_tokens > max_tokens * 2:
                print(
                    f"[chunked_convert] WARNING: oversized table at line {i + 1}, "
                    f"{block_tokens} tokens (> {max_tokens * 2}), "
                    f"produced oversized chunk",
                    file=sys.stderr,
                )

            cur_lines.extend(block)
            cur_tokens += block_tokens
            i += consumed
            continue

        # 3. heading 检测（仅在 code 外）
        is_atx = _is_atx_heading(line)
        setext_text = _detect_setext_heading(lines, i)
        is_setext = bool(setext_text)
        is_heading = is_atx or is_setext

        if is_heading:
            heading_text = line if is_atx else setext_text
            heading_tokens = count_tokens(heading_text)
            if cur_lines and cur_tokens + heading_tokens > max_tokens:
                commit()
            if is_setext:
                cur_section = lines[i]
                cur_lines.append(setext_text)
                cur_tokens += count_tokens(setext_text)
                i += 2
            else:
                cur_section = line
                cur_lines.append(line)
                cur_tokens += heading_tokens
                i += 1
            continue

        # 4. 单行超大 → 按 token 强制切
        line_tokens = count_tokens(line)
        if line_tokens > max_tokens:
            commit()
            emit_oversized(line)
            i += 1
            continue

        # 5. 普通行：超 limit 就切，否则追加
        if cur_lines and cur_tokens + line_tokens > max_tokens:
            commit()
        cur_lines.append(line)
        cur_tokens += line_tokens
        i += 1

    commit()

    # 6. context header：把上一 chunk 的 section 作为下一 chunk 的 context 头
    if context_header_tokens > 0 and len(chunks) > 1:
        out: list[tuple[str, str]] = [chunks[0]]
        for j in range(1, len(chunks)):
            section, body = chunks[j]
            ctx = out[-1][0].strip()
            if not ctx and out[-1][1]:
                ctx = out[-1][1].splitlines()[0].strip()
            if ctx and count_tokens(ctx) > context_header_tokens:
                ids = _enc().encode(ctx)
                ctx = _enc().decode(ids[-context_header_tokens:])
            if ctx:
                body = f"<!-- context: previous section was '{ctx}' -->\n\n" + body
            out.append((section, body))
        return out

    return chunks


def chunked_convert(
    src: str,
    dst_dir: str,
    max_tokens: int = CHUNK_SIZE,
    context_header_tokens: int = CONTEXT_HEADER_TOKENS,
) -> dict:
    """主入口。返回结构化 dict（含所有 chunk 的 metadata）。"""
    src_path = Path(src)
    dst = Path(dst_dir)
    stem = src_path.stem

    def fail(msg: str) -> dict:
        result = {"_error": msg, "chunks": []}
        try:
            (dst / f"{stem}.index.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
        return result

    try:
        dst.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return fail(f"cannot create output dir {dst}: {e}")

    try:
        md = MarkItDown()
        full = md.convert(str(src_path)).text_content or ""
    except Exception as e:
        return fail(f"markitdown failed: {e}")

    if not full.strip():
        return fail("markitdown returned empty content")

    total_tokens = count_tokens(full)

    raw_chunks = split_into_chunks(full, max_tokens, context_header_tokens)

    chunk_metas: list[ChunkMeta] = []
    for idx, (section, body) in enumerate(raw_chunks):
        chunk_path = dst / f"{stem}.chunk{idx:03d}.md"
        chunk_path.write_text(body, encoding="utf-8")
        chunk_metas.append(
            ChunkMeta(
                path=str(chunk_path),
                index=idx,
                tokens=count_tokens(body),
                section=section.strip()[:200] or "(no heading)",
            )
        )

    index = {
        "source": str(src_path),
        "source_tokens": total_tokens,
        "chunk_size": max_tokens,
        "context_header_tokens": context_header_tokens,
        "total_chunks": len(chunk_metas),
        "chunks": [asdict(m) for m in chunk_metas],
    }
    (dst / f"{stem}.index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return index


def main() -> None:
    p = argparse.ArgumentParser(
        description="Split large markitdown output into LLM-sized chunks."
    )
    p.add_argument("source", help="Path to source file (PDF/DOCX/...)")
    p.add_argument("output_dir", help="Directory to write chunk files")
    p.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    p.add_argument("--context-header", type=int, default=CONTEXT_HEADER_TOKENS)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    index = chunked_convert(args.source, args.output_dir, args.chunk_size, args.context_header)

    # J: 用 get() 显式 None 检查,不用 "in" 字典键判断
    if err := index.get("_error"):
        print(f"[chunked_convert] ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(
            f"[chunked_convert] {index['source_tokens']} tokens → "
            f"{index['total_chunks']} chunks (size≤{index['chunk_size']}, "
            f"context_header={index['context_header_tokens']})"
        )
        for c in index["chunks"]:
            print(
                f"  - {Path(c['path']).name}: {c['tokens']} tokens, "
                f"section={c['section']!r}"
            )
    else:
        print(json.dumps(index, ensure_ascii=False))


if __name__ == "__main__":
    main()
