# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from typing import TypedDict, Optional
from src.config.report_style import ReportStyle


class PromptEnhancerState(TypedDict):
    """State for the prompt enhancer workflow."""

    prompt: str  # Original prompt to enhance
    context: Optional[str]  # Additional context
    report_style: Optional[ReportStyle]  # Report style preference
    output: Optional[str]  # Enhanced prompt result
