"""Fallback middleware that enforces PPT artifact output for PPT requests.

If a user asks for a PPT/PPTX deck and the current turn does not produce
an actual .pptx artifact, this middleware generates a minimal fallback deck.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from deerflow.config.paths import Paths, get_paths
from deerflow.models import create_chat_model
from deerflow.skills.loader import get_skills_root_path


class PptEnforcementMiddlewareState(AgentState):
    """State extension compatible with ThreadState schema."""

    artifacts: NotRequired[list[str]]


class PptEnforcementMiddleware(AgentMiddleware[PptEnforcementMiddlewareState]):
    """Ensure a PPTX artifact exists when the user asks for a presentation."""

    state_schema = PptEnforcementMiddlewareState

    _PPT_KEYWORDS = (
        "ppt",
        "pptx",
        "\u5e7b\u706f\u7247",  # 幻灯片
        "\u6f14\u793a\u6587\u7a3f",  # 演示文稿
        "\u6f14\u793a",  # 演示
        "slide deck",
        "slides",
    )

    _SINGLE_SLIDE_TOKENS = (
        "\u53ea\u8981\u4e00\u9762",  # 只要一面
        "\u53ea\u8981\u4e00\u9875",  # 只要一页
        "\u4e00\u9762",  # 一面
        "\u4e00\u9875",  # 一页
        "\u5355\u9875",  # 单页
        "\u5355\u5f20",  # 单张
    )

    _CN_CLEANUP_PREFIX = (
        "\u8bf7",
        "\u5e2e\u6211",
        "\u5e2e\u5fd9",
        "\u9ebb\u70e6",
        "\u751f\u6210",
        "\u521b\u5efa",
        "\u505a",
        "\u5236\u4f5c",
    )

    def __init__(self, base_dir: str | None = None):
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()

    @staticmethod
    def _message_text(content: object) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "\n".join(parts)
        return str(content)

    def _is_ppt_request(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in lowered for keyword in self._PPT_KEYWORDS)

    def _assistant_intends_ppt_generation(self, text: str) -> bool:
        """Detect explicit assistant intent to generate a PPT in this turn."""
        if not text:
            return False
        lowered = text.lower()
        if not self._is_ppt_request(lowered):
            return False

        # Positive intent cues: "will create/generate/make PPT".
        positive = (
            "create",
            "generate",
            "make",
            "build",
            "\u521b\u5efa",  # 创建
            "\u751f\u6210",  # 生成
            "\u5236\u4f5c",  # 制作
            "\u505a",  # 做
        )
        has_positive = any(token in lowered for token in positive)
        if not has_positive:
            return False

        # Negative cues: "cannot/failed to generate PPT".
        negative = (
            "can't",
            "cannot",
            "unable",
            "failed",
            "error",
            "\u4e0d\u80fd",  # 不能
            "\u65e0\u6cd5",  # 无法
            "\u5931\u8d25",  # 失败
            "\u9519\u8bef",  # 错误
        )
        return not any(token in lowered for token in negative)

    @staticmethod
    def _find_last_user_index(messages: list) -> int | None:
        for idx in range(len(messages) - 1, -1, -1):
            if getattr(messages[idx], "type", None) == "human":
                return idx
        return None

    def _recent_user_requested_ppt(self, messages: list, last_user_index: int, lookback_humans: int = 3) -> bool:
        """Check a few prior user turns for PPT intent (for option-like replies such as '1')."""
        checked = 0
        for idx in range(last_user_index - 1, -1, -1):
            if getattr(messages[idx], "type", None) != "human":
                continue
            checked += 1
            text = self._message_text(getattr(messages[idx], "content", ""))
            if self._is_ppt_request(text):
                return True
            if checked >= lookback_humans:
                break
        return False

    def _last_ai_text(self, messages: list) -> str:
        for idx in range(len(messages) - 1, -1, -1):
            if getattr(messages[idx], "type", None) == "ai":
                return self._message_text(getattr(messages[idx], "content", ""))
        return ""

    def _has_ppt_generated_in_current_turn(self, messages: list, last_user_index: int) -> bool:
        """Detect whether this turn already produced a PPT via tool execution."""
        for msg in messages[last_user_index + 1 :]:
            if getattr(msg, "type", None) != "tool":
                continue
            tool_name = (getattr(msg, "name", "") or "").lower()
            content = self._message_text(getattr(msg, "content", "")).lower()
            if tool_name == "generate_ppt" and ".pptx" in content:
                return True
            if "presentation generated:" in content and ".pptx" in content:
                return True
        return False

    def _infer_slide_count(self, text: str) -> int:
        if any(token in text for token in self._SINGLE_SLIDE_TOKENS):
            return 1

        match = re.search(r"(\d+)\s*(?:\u9875|\u5f20|\u9762)", text)
        if match:
            try:
                count = int(match.group(1))
                if count > 0:
                    return min(count, 20)
            except ValueError:
                pass

        return 5

    def _extract_topic(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"[Pp][Pp][Tt][Xx]?", "", cleaned)
        cleaned = (
            cleaned.replace("\u5e7b\u706f\u7247", "")
            .replace("\u6f14\u793a\u6587\u7a3f", "")
            .replace("\u6f14\u793a", "")
            .strip()
        )

        cn_prefix_pattern = "|".join(re.escape(token) for token in self._CN_CLEANUP_PREFIX)
        cleaned = re.sub(rf"^(?:{cn_prefix_pattern})+", "", cleaned).strip()
        cleaned = re.sub(r"\u7684+$", "", cleaned).strip()
        return cleaned or "Presentation"

    @staticmethod
    def _safe_filename(name: str) -> str:
        filename = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
        if not filename:
            filename = "presentation"
        return filename[:80]

    @staticmethod
    def _build_fallback_plan(title: str, slide_count: int) -> dict:
        if slide_count <= 1:
            return {
                "title": title,
                "slides": [
                    {
                        "type": "content",
                        "title": title,
                        "key_points": [
                            "\u8bf7\u8865\u5145\u5173\u952e\u8981\u70b9",
                            "\u53ef\u63d0\u4f9b\u80cc\u666f/\u91cd\u70b9/\u7ed3\u8bba",
                            "\u6211\u5c06\u4e3a\u4f60\u5b8c\u5584\u5185\u5bb9",
                        ],
                    }
                ],
            }

        slides = [{"type": "title", "title": title, "subtitle": "\u81ea\u52a8\u751f\u6210"}]
        for i in range(2, slide_count + 1):
            slides.append(
                {
                    "type": "content",
                    "title": f"\u8981\u70b9 {i - 1}",
                    "key_points": ["\u8981\u70b9 1", "\u8981\u70b9 2", "\u8981\u70b9 3"],
                }
            )
        return {"title": title, "slides": slides}

    @staticmethod
    def _generate_plan_with_model(topic: str, slide_count: int) -> dict | None:
        try:
            model = create_chat_model(thinking_enabled=False)
            lang = "Chinese" if re.search(r"[\u4e00-\u9fff]", topic) else "English"
            prompt = (
                "You are generating a PPT slide plan in JSON.\n"
                "Return ONLY valid JSON with keys: title, slides.\n"
                "Rules:\n"
                f"- Language: {lang}\n"
                f"- Slide count: {slide_count}\n"
                '- Each slide must include type and title.\n'
                '- Title slide (type: "title") may include subtitle.\n'
                '- Content slides (type: "content") must include key_points (3-6 bullets).\n'
                "- If slide count is 1, return a single content slide.\n"
                f"Topic: {topic}\n"
            )

            response = model.invoke(prompt)
            content = str(getattr(response, "content", "") or "").strip()
            if not content:
                return None

            # Extract JSON if the model wrapped it with extra text.
            match = re.search(r"\{.*\}", content, re.S)
            json_text = match.group(0) if match else content
            data = json.loads(json_text)
            if not isinstance(data, dict) or "slides" not in data:
                return None
            return data
        except Exception:
            return None

    @staticmethod
    def _run_generate_text(plan_file: str, output_file: str) -> tuple[bool, str]:
        script = get_skills_root_path() / "public" / "ppt-generation" / "scripts" / "generate_text.py"
        if not script.is_file():
            return False, f"generate_text.py not found at {script}"

        result = subprocess.run(
            [sys.executable, str(script), "--plan-file", plan_file, "--output-file", output_file],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode != 0:
            return False, result.stderr or result.stdout or "unknown error"
        if (not os.path.isfile(output_file)) or os.path.getsize(output_file) <= 0:
            return False, f"output file missing or empty: {output_file}"
        return True, ""

    @override
    def after_agent(self, state: PptEnforcementMiddlewareState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_user_index = self._find_last_user_index(messages)
        if last_user_index is None:
            return None

        last_user = messages[last_user_index]
        user_text = self._message_text(getattr(last_user, "content", ""))
        ai_text = self._last_ai_text(messages)

        should_enforce = (
            self._is_ppt_request(user_text)
            or self._recent_user_requested_ppt(messages, last_user_index)
            or self._assistant_intends_ppt_generation(ai_text)
        )
        if not should_enforce:
            return None

        # Only skip fallback when the current turn has already generated a PPT.
        if self._has_ppt_generated_in_current_turn(messages, last_user_index):
            return None

        thread_id = runtime.context.get("thread_id")
        if thread_id is None:
            return None

        self._paths.ensure_thread_dirs(thread_id)
        workspace_dir = self._paths.sandbox_work_dir(thread_id)
        outputs_dir = self._paths.sandbox_outputs_dir(thread_id)
        os.makedirs(workspace_dir, exist_ok=True)
        os.makedirs(outputs_dir, exist_ok=True)

        slide_count = self._infer_slide_count(user_text)
        topic = self._extract_topic(user_text)
        plan = self._generate_plan_with_model(topic, slide_count)
        if plan is None:
            plan = self._build_fallback_plan(topic, slide_count)

        plan_file = os.path.join(str(workspace_dir), "presentation-plan.json")
        with open(plan_file, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)

        filename = self._safe_filename(plan.get("title") or topic)
        output_filename = f"{filename}.pptx"
        output_file = os.path.join(str(outputs_dir), output_filename)
        if os.path.exists(output_file):
            output_filename = f"{filename}-{int(time.time())}.pptx"
            output_file = os.path.join(str(outputs_dir), output_filename)

        ok, err = self._run_generate_text(plan_file, output_file)
        if not ok:
            print(f"[PptEnforcementMiddleware] Failed to generate PPT: {err}")
            return None

        virtual_path = f"/mnt/user-data/outputs/{output_filename}"
        return {"artifacts": [virtual_path]}
