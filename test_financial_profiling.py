#!/usr/bin/env python3
"""
Test script for financial profiling functionality.
Reads query from query.txt (English) or query_zh_CN.txt (Chinese) and runs it through the multi-agent system.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from src.workflow import run_agent_workflow_async

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def test_financial_profiling(locale="en", report_style=None):
    """Test financial profiling workflow with query from query.txt or query_zh_CN.txt.
    
    Args:
        locale: Language locale ("en" or "zh-CN")
        report_style: Report style to use. Options: "academic", "popular_science", 
                     "news", "social_media", "strategic_investment". 
                     Default: "academic"
    """
    # Select query file based on locale
    if locale == "zh-CN":
        query_file = Path("query_zh_CN.txt")
        logger.info("Testing Chinese financial profiling query")
    else:
        query_file = Path("query.txt")
        logger.info("Testing English financial profiling query")
    
    if not query_file.exists():
        logger.error(f"Query file not found: {query_file}")
        sys.exit(1)

    with open(query_file, "r", encoding="utf-8") as f:
        query = f.read().strip()

    if not query:
        logger.error("Query file is empty")
        sys.exit(1)

    logger.info(f"Loaded query from {query_file}")
    logger.info(f"Query preview: {query[:100]}...")
    
    # Set report_style via environment variable if provided
    original_report_style = None
    if report_style:
        logger.info(f"Setting report style via environment variable: {report_style}")
        original_report_style = os.environ.get("REPORT_STYLE")
        os.environ["REPORT_STYLE"] = report_style
    else:
        logger.info("Using default report style: academic")

    # Run the agent workflow
    try:
        await run_agent_workflow_async(
            user_input=query,
            debug=True,
            max_plan_iterations=1,
            max_step_num=3,
            enable_background_investigation=True,
            enable_clarification=False,
        )
        logger.info(f"Financial profiling test ({locale}) completed successfully")
    except Exception as e:
        logger.error(f"Error running financial profiling test ({locale}): {e}")
        raise
    finally:
        # Restore original environment variable
        if original_report_style is not None:
            os.environ["REPORT_STYLE"] = original_report_style
        elif "REPORT_STYLE" in os.environ:
            del os.environ["REPORT_STYLE"]


async def test_all(report_style=None):
    """Run both English and Chinese tests."""
    logger.info("=" * 60)
    logger.info("Running English financial profiling test")
    logger.info("=" * 60)
    await test_financial_profiling(locale="en", report_style=report_style)
    
    logger.info("\n" + "=" * 60)
    logger.info("Running Chinese financial profiling test")
    logger.info("=" * 60)
    await test_financial_profiling(locale="zh-CN", report_style=report_style)


if __name__ == "__main__":
    # Check if locale or report_style arguments are provided
    locale_arg = None
    report_style_arg = None
    
    if len(sys.argv) > 1:
        locale_arg = sys.argv[1].lower()
    
    if len(sys.argv) > 2:
        report_style_arg = sys.argv[2].lower()
    
    # Valid report styles
    valid_styles = ["academic", "popular_science", "news", "social_media", "strategic_investment"]
    
    if locale_arg == "zh-cn" or locale_arg == "zh":
        style = report_style_arg if report_style_arg in valid_styles else None
        asyncio.run(test_financial_profiling(locale="zh-CN", report_style=style))
    elif locale_arg == "all":
        style = report_style_arg if report_style_arg in valid_styles else None
        asyncio.run(test_all(report_style=style))
    elif locale_arg in valid_styles:
        # If first arg is a report_style, treat it as such
        asyncio.run(test_financial_profiling(locale="en", report_style=locale_arg))
    else:
        # Default to English
        style = report_style_arg if report_style_arg in valid_styles else None
        asyncio.run(test_financial_profiling(locale="en", report_style=style))

