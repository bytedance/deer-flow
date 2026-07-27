"""lark-cli 官方 skill 包与 deer-flow 技能系统的格式兼容性回归测试。

锁住四件事：
1. 我们依赖的 lark skill（lark-shared/lark-im/lark-base）的 SKILL.md 都能被
   deerflow.skills.parser.parse_skill_file 成功解析。
2. 解析出的 name/description 符合 deer-flow 技能系统的非空要求。
3. lark-cli 特有的 frontmatter 字段（metadata.requires.bins、version 等）被 parser
   安全忽略，不会导致解析失败。同时覆盖“有 metadata”（lark-im/lark-base）和
   “无 metadata”（lark-shared）两种情况。
4. lark-cli 的 version 字段不被误解析为 deer-flow 认识的字段。

upstream lark-cli 升级（git submodule bump）时，CI 会发现任何打破兼容的
frontmatter 变更。
"""

import re
from pathlib import Path

import yaml

from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import SkillCategory

REPO_ROOT = Path(__file__).resolve().parents[2]
LARK_SKILLS_DIR = REPO_ROOT / "skills" / "public" / "lark" / "skills"

# 我们 A 阶段启用的 3 个 skill + 它们依赖的 lark-shared
REQUIRED_LARK_SKILLS = ["lark-shared", "lark-im", "lark-base"]


def _skill_dir(name: str) -> Path:
    return LARK_SKILLS_DIR / name


def _skill_md(name: str) -> Path:
    return _skill_dir(name) / "SKILL.md"


# 与 parse_skill_file 同款 frontmatter 切割，但跳过 deer-flow 的字段提取，
# 直接 yaml.safe_load 原始 dict，用于断言 upstream 字段确实存在/缺席。
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _raw_frontmatter(name: str) -> dict:
    content = _skill_md(name).read_text(encoding="utf-8")
    match = _FRONT_MATTER_RE.match(content)
    assert match is not None, f"{name}: 缺 frontmatter"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), f"{name}: frontmatter 不是 dict"
    return data


def test_lark_skills_dir_exists():
    """submodule 必须已 add，skills/public/lark/skills 目录存在。"""
    assert LARK_SKILLS_DIR.exists(), f"lark-cli skills 目录不存在：{LARK_SKILLS_DIR}\n先跑：git submodule add https://github.com/larksuite/cli.git skills/public/lark"


def test_required_lark_skills_present():
    """我们依赖的 3 个 skill 的 SKILL.md 都在。"""
    missing = [n for n in REQUIRED_LARK_SKILLS if not _skill_md(n).exists()]
    assert not missing, f"缺 lark skill：{missing}"


def test_lark_skills_parse_with_deerflow_parser():
    """每个 lark SKILL.md 都能被 deer-flow parser 解析成 Skill 对象。"""
    for name in REQUIRED_LARK_SKILLS:
        skill = parse_skill_file(
            _skill_md(name),
            category=SkillCategory.PUBLIC,
        )
        assert skill is not None, f"解析 {name}/SKILL.md 返回 None（frontmatter 不合规）"
        assert skill.name == name, f"{name}: name 字段不符，得到 {skill.name!r}"
        assert skill.description and skill.description.strip(), f"{name}: description 为空"


def test_lark_metadata_fields_ignored():
    """lark-cli 的 metadata.requires.bins 等字段被 parser 安全忽略，不报错。

    这是兼容性的关键：deer-flow parser 只提取自己认识的字段，其余通过
    metadata.get(...) 忽略。如果 upstream lark-cli 加了 deer-flow 认识的
    字段名（如 allowed-tools）但语义不同，这个测试会暴露。

    同时覆盖两种情况：
    - lark-im：有 metadata 字段（metadata.requires.bins: ["lark-cli"]）
    - lark-shared：无 metadata 字段
    """
    for name in REQUIRED_LARK_SKILLS:
        skill = parse_skill_file(
            _skill_md(name),
            category=SkillCategory.PUBLIC,
        )
        assert skill is not None
        # lark-im/lark-base 的 frontmatter 有 metadata.requires.bins
        # deer-flow 不应该把这个误解析成 allowed_tools 或 required_secrets
        assert skill.allowed_tools is None, f"{name}: lark-cli 的 metadata 字段不该被 deer-flow 误识别成 allowed-tools"
        assert skill.required_secrets == (), f"{name}: lark-cli 的 metadata 字段不该被 deer-flow 误识别成 required-secrets"

    # 锁住"被忽略的字段确实存在"这一前提：upstream 若移除 metadata 字段，
    # 上面的 allowed_tools/required_secrets 断言会空过（vacuously pass），
    # 这里强制 lark-im 的 frontmatter 确实含 metadata 键、lark-shared 确实不含。
    lark_im_fm = _raw_frontmatter("lark-im")
    assert "metadata" in lark_im_fm, "lark-im frontmatter 不再含 metadata 字段（upstream 变更？）"
    lark_shared_fm = _raw_frontmatter("lark-shared")
    assert "metadata" not in lark_shared_fm, "lark-shared frontmatter 不该含 metadata 字段"


def test_lark_version_field_ignored():
    """lark-cli 的 version 字段被 parser 安全忽略。

    lark-cli 的 SKILL.md 都有 version 字段（如 version: 1.0.0）。
    deer-flow 不提取这个字段，但需确认它不会导致解析失败或被误解析。
    """
    skill = parse_skill_file(
        _skill_md("lark-im"),
        category=SkillCategory.PUBLIC,
    )
    assert skill is not None
    # version 不在 deer-flow Skill dataclass 的字段中，parser 不会提取它
    # 这里主要确认解析成功且不报错
    assert skill.name == "lark-im"
