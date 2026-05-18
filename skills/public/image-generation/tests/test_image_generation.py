# Copyright 2025 ApeCloud, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
集成测试：third_party/deerflow/skills/public/image-generation/scripts/generate.py

参考 logs/test_generate_manual.md 中的手动测试流程，使用真实 GEMINI_API_KEY
调用 Gemini API 验证图片生成功能。

GEMINI_API_KEY 必须通过 tests/unit_test/.env.test 或环境变量提供，
否则测试以 ERROR 状态终止（不跳过）。
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "generate.py"
)

# ---------------------------------------------------------------------------
# 在模块加载时立即检查 KEY，缺失则 ERROR（而非 skip）
# ---------------------------------------------------------------------------
if not os.environ.get("GEMINI_API_KEY"):
    pytest.fail(
        "GEMINI_API_KEY is not set. Set it in .env or export GEMINI_API_KEY=...",
        pytrace=False,
    )


def _load_generate_module():
    spec = importlib.util.spec_from_file_location("generate", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_module = _load_generate_module()
generate_image = generate_module.generate_image


# ---------------------------------------------------------------------------
# 集成测试
# ---------------------------------------------------------------------------

PROMPT = (
    "A cute cartoon cat sitting on a wooden desk, "
    "soft lighting, digital art style"
)


class TestGenerateImageIntegration:
    """
    使用真实 GEMINI_API_KEY 验证 generate.py 的完整生成流程。

    对应 logs/test_generate_manual.md：
      Step 1 — 创建 prompt 文件
      Step 2 — 执行生成脚本
      结论验证：返回值格式、输出文件存在且为有效图片
    """

    def test_generate_image_via_function(self):
        """
        直接调用 generate_image()，验证：
        - 返回值格式为 "Successfully generated image to <path>"（结论第 4 条）
        - 输出文件存在且非空（结论第 3 条）
        - 输出文件是有效图片
        """
        prompt_file = Path("/tmp/test_prompt.txt")
        prompt_file.write_text(PROMPT, encoding="utf-8")
        output_file = Path("/tmp/test_output_function.jpg")

        result = generate_image(
            str(prompt_file),
            [],
            str(output_file),
            aspect_ratio="1:1",
        )

        assert result == f"Successfully generated image to {output_file}"
        assert output_file.exists()
        assert output_file.stat().st_size > 0
        with Image.open(output_file) as img:
            img.verify()

    def test_generate_image_via_cli(self):
        """
        通过子进程调用 CLI（对应手动测试 Step 2 的命令行方式），验证：
        - stdout 包含成功消息
        - 输出文件被写出
        """
        prompt_file = Path("/tmp/test_prompt.txt")
        prompt_file.write_text(PROMPT, encoding="utf-8")
        output_file = Path("/tmp/test_output_cli.jpg")

        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--prompt-file", str(prompt_file),
                "--output-file", str(output_file),
                "--aspect-ratio", "1:1",
            ],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )

        assert f"Successfully generated image to {output_file}" in proc.stdout
        assert output_file.exists()
        assert output_file.stat().st_size > 0
