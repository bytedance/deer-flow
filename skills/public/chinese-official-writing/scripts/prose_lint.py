#!/usr/bin/env python3
"""Warn about AI-flavor, side-commentary, and casual phrasing in Chinese official drafts.

The script reports risks only. It does not rewrite text.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree


@dataclass
class Finding:
    path: str
    line: int
    severity: str
    label: str
    match: str
    excerpt: str


class InputReadError(Exception):
    """Raised when a CLI input file cannot be read as usable text."""


PATTERNS: list[tuple[str, str, str, str]] = [
    ("high", "paired-summary", r"不是[^。；;\n]{0,80}而是", "改为直接肯定结论；必要否定对比可保留。"),
    ("high", "paired-summary", r"不仅[^。；;\n]{0,80}还", "拆成具体事实或只保留关键判断。"),
    ("high", "paired-summary", r"不但[^。；;\n]{0,80}而且", "拆成具体事实或只保留关键判断。"),
    ("high", "paired-summary", r"既[^。；;\n]{0,80}又", "改为具体并列事项，避免套话。"),
    ("high", "paired-summary", r"一方面[^。；;\n]{0,100}另一方面", "改为按业务或数据自然分段。"),
    ("high", "side-commentary", r"本方案重点说明", "删除写作说明，改成方案正文判断。"),
    ("high", "side-commentary", r"重点说明\s*Token\s*用在哪里", "改为年度调用需求来源描述。"),
    ("medium", "side-commentary", r"以下(直接)?列出", "改为正文承接，不写提示语。"),
    ("medium", "side-commentary", r"本文将从", "改为直接进入结论或事实。"),
    ("medium", "side-commentary", r"本节主要(介绍|说明)", "改为正文判断。"),
    ("medium", "side-commentary", r"根据有关资料显示", "核实来源后直接写事实，避免模糊背书。"),
    ("medium", "side-commentary", r"相关情况如下", "可删除套话，直接进入事项。"),
    ("medium", "side-commentary", r"需要指出的是", "保留实质内容，删除提示语。"),
    ("medium", "side-commentary", r"值得注意的是", "保留实质内容，删除提示语。"),
    ("medium", "side-commentary", r"为了便于理解", "正式文稿中通常不需要解释腔。"),
    ("medium", "side-commentary", r"简单来说", "正式文稿中通常不需要解释腔。"),
    ("medium", "side-commentary", r"通俗地说", "正式文稿中通常不需要解释腔。"),
    ("medium", "side-commentary", r"可以理解为", "正式文稿中通常不需要解释腔。"),
    ("medium", "project-card-summary", r"^\s*(?:项目名称|建设单位|实施单位|建设周期|总投资|预算金额|采购内容|服务内容)\s*[：:]", "检查摘要或概况是否写成项目卡片；必要时改为连续正文。"),
    ("medium", "cost-explainer", r"测算口径|测算公式|计算公式|单价\s*[×xX*]\s*数量|计算如下", "检查需求与成本章节是否写成测算说明；必要时改为说明需求来源、费用对应事项和成本边界。"),
    ("medium", "unfinished-placeholder", r"\[[^\]\n]{0,30}(?:具体|待|填写|补充|确认|项目名称|单位名称|金额|日期)[^\]\n]{0,30}\]", "交付正文不应保留方括号占位；缺项改为正文外提示。"),
    ("medium", "unfinished-placeholder", r"(?<![A-Za-z])(?:X{2,}(?![A-Za-z\u4e00-\u9fff])|X+(?:万元|亿元|亿|项|%|％|卡|套|人|次|个))", "交付正文不应保留 X/XXXX 类占位；缺项改为正文外提示。"),
    ("medium", "unfinished-placeholder", r"Y{4}年M{1,2}月D{1,2}日?", "交付正文不应保留 YYYY年MM月DD日 类占位；缺项改为正文外提示。"),
    ("medium", "unfinished-placeholder", r"[（(][^）)\n]{0,30}(?:待|签发日期|会议时间|成文日期|填写|补充|确认)[^）)\n]{0,30}[）)]", "交付正文不应保留括号占位；缺项改为正文外提示。"),
    ("medium", "unfinished-placeholder", r"〔(?:签发日期|会议时间|待补充|[^〕\n]{0,20}(?:待|补充|填写|确认)[^〕\n]{0,20})〕", "交付正文不应保留未完成占位；缺项改为正文外提示。"),
    ("high", "thought-leak", r"作为(?:一个)?\s*AI|我是(?:一个)?\s*AI|由\s*AI\s*(?:起草|生成|辅助生成)|AI\s*(?:辅助)?生成|我的(?:思路|推理|分析)|(?:思考|推理)过程(?:如下|是|：|:)|内部推理", "删除模型身份、思考过程或内部推理表述。"),
    ("medium", "thought-leak", r"我将根据|接下来我会|按你的要求", "改为文稿正文或办理安排，不暴露生成过程。"),
    ("medium", "viewpoint-risk", r"(?:按|按照|根据)(?:录音|用户)要求|(?:录音|用户)要求(?:如下|为)|你让我|这版文章|这段文字", "检查是否把外部修改过程写进正文。"),
    ("medium", "casual", r"租赁方式更稳[，,、]?\s*也更省", "改为成本和服务保障更具确定性。"),
    ("medium", "casual", r"用不完", "改为阶段性资源余量或资源利用率。"),
    ("medium", "casual", r"AI味", "改为表述偏泛或判断不够具体。"),
    ("medium", "casual", r"这个钱花得值", "改为投入产出关系较为清晰。"),
    ("medium", "casual", r"老板关心", "改为决策层重点关注。"),
    ("low", "empty-filler", r"全面赋能", "确认是否有具体机制支撑。"),
    ("low", "empty-filler", r"充分发挥", "确认后文是否说明发挥方式。"),
    ("low", "empty-filler", r"不断提升", "确认是否有具体对象或目标。"),
    ("low", "template-phrase", r"形成一批", "确认是否有明确对象、数量或结果形态。"),
    ("low", "template-phrase", r"重点任务包括", "避免用一个总括句承接长清单，改为分项任务条款。"),
    ("low", "template-phrase", r"保障措施包括", "避免泛化清单，改为组织、资金、督导、责任等具体措施。"),
    ("low", "template-phrase", r"总体看", "确认是否只是过渡填充；可直接写判断。"),
    ("medium", "ai-compute-vague", r"先进算力", "算力文件中应补充GPU/服务器/Token/并发/SLA等可验收指标。"),
    ("medium", "ai-compute-vague", r"强大平台", "补充调度、监控、隔离、计量、运维等具体平台能力。"),
    ("medium", "ai-compute-vague", r"成本更低", "补充比较周期、需求假设和成本项目。"),
    ("medium", "ai-compute-vague", r"满足未来发展需要", "补充用户、Token、并发、模型升级或智能体工作流依据。"),
]

FORMAT_PATTERNS: list[tuple[str, str, str, str]] = [
    ("medium", "halfwidth-punctuation", r"[\u4e00-\u9fff][,;:!?][\u4e00-\u9fff]", "中文正文中通常改用全角标点。"),
    ("low", "number-grouping-comma", r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", "确认正式中文材料中是否应取消千位分隔符。"),
    ("low", "cn-number-space", r"[\u4e00-\u9fff]\s+\d|\d\s+[\u4e00-\u9fff]", "检查中文和数字之间是否误加空格。"),
    ("medium", "emoji-marker", r"[\U0001F300-\U0001FAFF]", "正式公文正文避免使用 Emoji。"),
    ("low", "markdown-bold", r"\*\*[^*\n]{1,80}\*\*", "正式公文正文不要用 Markdown 加粗标记；改为普通小标题或正文。"),
    ("low", "western-bullet", r"^\s*(?:[-*•●◆◇★✅☑]|[0-9]+[.)])\s+", "中文正式正文避免频繁使用西式项目符号或 1. 2. 编号；必要清单可保留。"),
]

# 面向约 2k-5k 字正式材料的低风险经验线，只提示术语过度集中，不作为硬失败或自动改写依据。
REPEAT_TERMS: dict[str, int] = {
    "口径": 4,  # 数据、政策和办理事项常用词，4 次起提示是否复述同一依据。
    "边界": 4,  # 合规、职责和测算说明常用词，4 次起提示是否重复限定。
    "底座": 6,  # 技术材料可合理多次出现，阈值高于一般空泛词。
    "闭环": 4,  # 管理类材料常用词，4 次起提示是否以概念替代措施。
    "赋能": 3,  # 容易空泛化，3 次起提示是否需要改成具体作用。
    "生态": 4,  # 产业和平台材料常用词，4 次起提示是否泛化。
    "抓手": 3,  # 容易变成套话，3 次起提示是否需要改成事项或机制。
    "矩阵": 3,  # 组织和传播材料常用词，3 次起提示是否堆概念。
}

# 重复段落检测用的通用低信息词。不要放入“数据、系统、平台、服务、管理、实施、保障”等实义领域词。
DUPLICATE_GENERIC_TOKENS = {
    "项目",
    "工作",
    "建设",
    "方案",
    "情况",
    "相关",
    "进行",
    "通过",
    "形成",
    "推进",
    "落实",
    "有效",
    "积极",
    "全面",
    "持续",
    "推动",
    "完善",
    "确保",
}


def read_docx(path: Path) -> str:
    pieces: list[str] = []
    xml_names = (
        "word/document.xml",
        "word/header1.xml",
        "word/header2.xml",
        "word/header3.xml",
        "word/footer1.xml",
        "word/footer2.xml",
        "word/footer3.xml",
        "word/footnotes.xml",
        "word/endnotes.xml",
        "word/comments.xml",
    )
    try:
        with zipfile.ZipFile(path) as zf:
            for name in xml_names:
                if name not in zf.namelist():
                    continue
                root = ElementTree.fromstring(zf.read(name))
                for elem in root.iter():
                    tag = elem.tag.rsplit("}", 1)[-1]
                    if tag == "t" and elem.text:
                        pieces.append(elem.text)
                    elif tag in {"p", "br"}:
                        pieces.append("\n")
                    elif tag == "tab":
                        pieces.append("\t")
    except zipfile.BadZipFile as exc:
        raise InputReadError(f"文件损坏或不是有效 DOCX: {path}") from exc
    except ElementTree.ParseError as exc:
        raise InputReadError(f"DOCX 内部 XML 无法解析: {path}") from exc
    return "".join(pieces)


def read_text(path_arg: str, encoding: str | None) -> tuple[str, str]:
    if path_arg == "-":
        return "<stdin>", sys.stdin.read()

    path = Path(path_arg)
    try:
        if path.suffix.lower() == ".docx":
            return str(path), read_docx(path)
        raw = path.read_bytes()
    except InputReadError:
        raise
    except FileNotFoundError as exc:
        raise InputReadError(f"文件不存在: {path}") from exc
    except PermissionError as exc:
        raise InputReadError(f"无权限读取文件: {path}") from exc
    except OSError as exc:
        raise InputReadError(f"无法读取文件: {path}: {exc}") from exc

    encodings = [encoding] if encoding else ["utf-8-sig", "utf-8", "gb18030"]
    for enc in encodings:
        if not enc:
            continue
        try:
            return str(path), raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return str(path), raw.decode(encodings[-1], errors="replace")


def excerpt(line: str, start: int, end: int) -> str:
    left = max(0, start - 28)
    right = min(len(line), end + 28)
    value = line[left:right].strip()
    return re.sub(r"\s+", " ", value)


def inside_inline_code(line: str, start: int, end: int) -> bool:
    """Return True when a match is entirely inside a Markdown inline-code span."""
    spans: list[tuple[int, int]] = []
    idx = 0
    while True:
        left = line.find("`", idx)
        if left == -1:
            break
        right = line.find("`", left + 1)
        if right == -1:
            break
        spans.append((left, right + 1))
        idx = right + 1
    return any(left <= start and end <= right for left, right in spans)


def paragraph_blocks(lines: list[str]) -> list[tuple[int, str, int]]:
    blocks: list[tuple[int, str, int]] = []
    current: list[str] = []
    start_line = 1
    section_id = 0
    in_fence = False

    def flush_current() -> None:
        nonlocal current
        if current:
            blocks.append((start_line, "\n".join(current), section_id))
            current = []

    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_current()
            in_fence = not in_fence
            section_id += 1
            continue
        if in_fence:
            continue
        if not stripped:
            flush_current()
            continue
        if stripped.startswith(("#", "|")):
            flush_current()
            section_id += 1
            continue
        if re.match(r"^\s*(?:[-*]|\d+[.)、])\s+", stripped):
            flush_current()
            continue
        if not current:
            start_line = idx
        current.append(stripped)
    flush_current()
    return blocks


def content_tokens(text: str) -> set[str]:
    compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)
    if len(compact) < 12:
        return set()
    tokens = {compact[i : i + 2] for i in range(len(compact) - 1)}
    tokens |= {compact[i : i + 3] for i in range(len(compact) - 2)}
    return {token for token in tokens if token not in DUPLICATE_GENERIC_TOKENS}


def duplicate_findings(path_label: str, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    blocks = paragraph_blocks(lines)
    for index in range(1, len(blocks)):
        prev_line, prev_text, prev_section = blocks[index - 1]
        line_no, text, section = blocks[index]
        if section != prev_section:
            continue
        if len(prev_text) < 60 or len(text) < 60:
            continue
        prev_tokens = content_tokens(prev_text)
        tokens = content_tokens(text)
        if not prev_tokens or not tokens:
            continue
        shared = prev_tokens & tokens
        union = prev_tokens | tokens
        ratio = len(shared) / len(union)
        if len(shared) >= 18 and ratio >= 0.42:
            findings.append(
                Finding(
                    path=path_label,
                    line=line_no,
                    severity="medium",
                    label="adjacent-duplicate-matter",
                    match=";".join(sorted(shared)[:6]),
                    excerpt=f"与上一段（约第 {prev_line} 行）事项重叠较高；检查是否为胶水式重复连接。",
                )
            )
    return findings


def structured_smell_findings(path_label: str, text: str, lines: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    card_pattern = re.compile(r"^\s*(?:[-*]\s*)?(?:项目名称|项目单位|建设单位|实施单位|采购单位|建设周期|实施周期|服务期限|建设内容|采购内容|服务内容|总投资|预算金额|经费预算|资金来源|项目地点)\s*[：:]")
    streak = 0
    streak_start = 1
    total = 0
    first_line = 1
    for line_no, line in enumerate(lines, start=1):
        if card_pattern.search(line):
            if streak == 0:
                streak_start = line_no
            streak += 1
            total += 1
            if total == 1:
                first_line = line_no
            if streak == 3:
                findings.append(
                    Finding(
                        path=path_label,
                        line=streak_start,
                        severity="medium",
                        label="project-card-summary",
                        match="card-fields",
                        excerpt="连续字段行使摘要或项目概况像项目卡片；必要时改为连续正式正文。",
                    )
                )
        elif line.strip():
            streak = 0
    if total >= 4 and not any(item.label == "project-card-summary" for item in findings):
        findings.append(
            Finding(
                path=path_label,
                line=first_line,
                severity="medium",
                label="project-card-summary",
                match="card-fields",
                excerpt="字段行较多，检查摘要或项目概况是否像项目卡片。",
            )
        )

    match = re.search(r"(?:^|\n)\s*(?:[一二三四五六七八九十]+、)?[^。\n]{0,18}必要性[^。\n]*(?:\n|$)[\s\S]{0,700}一是[\s\S]{0,220}二是[\s\S]{0,220}三是", text)
    if match:
        line = text[: match.start()].count("\n") + 1
        findings.append(
            Finding(
                path=path_label,
                line=line,
                severity="medium",
                label="necessity-listing",
                match="一是/二是/三是",
                excerpt="必要性章节像论点罗列；必要时补足事实依据、工作影响和事项落点。",
            )
        )
    return findings


def scan(path_label: str, text: str, include_format: bool = False, include_structure: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines() or [text]

    patterns = PATTERNS + (FORMAT_PATTERNS if include_format else [])
    compiled = [(severity, label, re.compile(pattern), advice) for severity, label, pattern, advice in patterns]
    in_fence = False
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            if include_format:
                findings.append(
                    Finding(
                        path=path_label,
                        line=line_no,
                        severity="low",
                        label="markdown-code-fence",
                        match=stripped[:20],
                        excerpt="正式公文正文不要用 Markdown 代码块包裹；交付正文应直接呈现。",
                    )
                )
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for severity, label, regex, advice in compiled:
            for match in regex.finditer(line):
                if inside_inline_code(line, match.start(), match.end()):
                    continue
                findings.append(
                    Finding(
                        path=path_label,
                        line=line_no,
                        severity=severity,
                        label=label,
                        match=match.group(0),
                        excerpt=f"{excerpt(line, match.start(), match.end())} | {advice}",
                    )
                )

    if include_format:
        western_list_count = sum(1 for line in lines if re.match(r"^\s*(?:[-*•●◆◇★✅☑]|[0-9]+[.)])\s+", line))
        if western_list_count >= 8:
            findings.append(
                Finding(
                    path=path_label,
                    line=1,
                    severity="low",
                    label="frequent-list-markers",
                    match=str(western_list_count),
                    excerpt="正文中西式项目符号或 1. 2. 编号较多；确认是否可改为中文条款或自然段。",
                )
            )

    if include_structure:
        findings.extend(duplicate_findings(path_label, lines))
        findings.extend(structured_smell_findings(path_label, text, lines))

    for term, threshold in REPEAT_TERMS.items():
        count = text.count(term)
        if count >= threshold:
            findings.append(
                Finding(
                    path=path_label,
                    line=1,
                    severity="low",
                    label="term-overuse",
                    match=term,
                    excerpt=f"`{term}` 出现 {count} 次；建议将部分表述替换为更具体的事项、主体或办理要素。",
                )
            )

    return findings


def print_text(findings: Iterable[Finding]) -> None:
    for item in findings:
        print(f"{item.path}:{item.line}: {item.severity}: {item.label}: {item.match}")
        print(f"  {item.excerpt}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Warn about Chinese official-writing prose risks.")
    parser.add_argument("files", nargs="+", help="Text/Markdown/DOCX files to scan, or '-' for stdin.")
    parser.add_argument("--encoding", help="Encoding for plain-text files.")
    parser.add_argument("--json", action="store_true", help="Emit JSON findings.")
    parser.add_argument("--format", action="store_true", help="Also scan punctuation, number, list-marker, and emoji format risks.")
    parser.add_argument("--structure", action="store_true", help="Also scan adjacent paragraphs for repeated matters.")
    parser.add_argument("--strict", action="store_true", help="Return exit code 1 when findings exist.")
    args = parser.parse_args(argv)

    all_findings: list[Finding] = []
    had_read_error = False
    for file_arg in args.files:
        try:
            path_label, text = read_text(file_arg, args.encoding)
        except InputReadError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            had_read_error = True
            continue
        all_findings.extend(scan(path_label, text, include_format=args.format, include_structure=args.structure))

    if args.json:
        print(json.dumps([asdict(item) for item in all_findings], ensure_ascii=False, indent=2))
    else:
        if all_findings:
            print_text(all_findings)
        elif not had_read_error:
            print("No prose risks found.")

    if had_read_error:
        return 2
    return 1 if args.strict and all_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
