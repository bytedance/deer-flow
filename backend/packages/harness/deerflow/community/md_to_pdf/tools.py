"""
Markdown to Mobile-Friendly PDF Tool - Convert markdown files with charts and images to PDF.

Uses Playwright with Chromium for highest quality rendering.
"""

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from deerflow.agents.thread_state import ThreadState

logger = logging.getLogger(__name__)


def _convert_markdown_to_pdf(
    markdown_path: Path,
    output_path: Path,
    mobile_friendly: bool = True,
) -> tuple[bool, str]:
    """Convert markdown to PDF using Playwright for highest quality rendering.

    Args:
        markdown_path: Path to input markdown file
        output_path: Path to output PDF file
        mobile_friendly: Whether to use mobile-friendly layout

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        import markdown
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        return False, f"Required libraries not installed: {e}. Run: pip install markdown playwright && playwright install chromium"

    try:
        # Read markdown content
        with open(markdown_path, encoding="utf-8") as f:
            md_content = f.read()

        # Convert markdown to HTML with extensions for better rendering
        html_content = markdown.markdown(
            md_content,
            extensions=[
                "extra",  # Tables, fenced code blocks, etc.
                "codehilite",  # Syntax highlighting
                "toc",  # Table of contents
                "nl2br",  # Newline to <br>
                "sane_lists",  # Better list handling
            ],
        )

        # Simple clean CSS for PDF generation with dark theme
        mobile_css = """
        /* ── Page Setup ────────────────────────────────────────────── */
        @page {
          size: A4;
          margin: 0;
          background: #0f0f12;
        }

        /* ── Base ──────────────────────────────────────────────────── */
        *, *::before, *::after {
          box-sizing: border-box;
        }

        html {
          background: #0f0f12;
        }

        body {
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
          font-size: 11pt;
          font-weight: 400;
          line-height: 1.6;
          color: #eeeef2;
          background: #0f0f12;
          padding: 2cm 1.5cm;
          margin: 0;
          word-wrap: break-word;
          overflow-wrap: break-word;
          -webkit-print-color-adjust: exact;
          print-color-adjust: exact;
        }

        /* ── Headings ──────────────────────────────────────────────── */
        h1, h2, h3, h4, h5, h6 {
          font-family: inherit;
          page-break-after: avoid;
          font-weight: 700;
          color: #ffffff;
          margin-top: 1em;
          margin-bottom: 0.5em;
        }

        h1 {
          font-size: 24pt;
          margin-top: 0;
          margin-bottom: 0.8em;
          border-bottom: 2px solid #5b8dee;
          padding-bottom: 0.3em;
        }

        h2 {
          font-size: 18pt;
          border-bottom: 1px solid #5b8dee;
          padding-bottom: 0.2em;
        }

        h3 {
          font-size: 14pt;
          color: #5b8dee;
        }

        h4 {
          font-size: 12pt;
          color: #9d7fe8;
        }

        h5 {
          font-size: 11pt;
          color: #a0a0b8;
        }

        h6 {
          font-size: 10pt;
          color: #a0a0b8;
        }

        /* ── Paragraphs ────────────────────────────────────────────── */
        p {
          margin: 0.6em 0;
          text-align: left;
          orphans: 3;
          widows: 3;
        }

        /* ── Inline Emphasis ───────────────────────────────────────── */
        strong {
          color: #f5a623;
          font-weight: 700;
        }

        em {
          color: #9d7fe8;
          font-style: italic;
        }

        strong em, em strong {
          color: #f06292;
          font-style: italic;
        }

        /* ── Links ─────────────────────────────────────────────────── */
        a {
          color: #5b8dee;
          text-decoration: underline;
        }

        /* ── Horizontal Rule ───────────────────────────────────────── */
        hr {
          border: none;
          border-top: 1px solid #3a3a50;
          margin: 1.5em 0;
        }

        /* ── Blockquotes ───────────────────────────────────────────── */
        blockquote {
          border-left: 3px solid #5b8dee;
          margin: 1em 0;
          padding: 0.5em 1em;
          background: #16161d;
          color: #a0a0b8;
        }

        blockquote strong {
          color: #f5a623;
        }

        blockquote p {
          margin: 0.3em 0;
        }

        /* ── Code ──────────────────────────────────────────────────── */
        code {
          font-family: 'SF Mono', Monaco, 'Cascadia Code', Consolas, monospace;
          font-size: 10pt;
          background: #1e1e28;
          color: #4ecdc4;
          padding: 0.1em 0.3em;
          border: 1px solid #2a2a38;
        }

        pre {
          background: #16161d;
          border: 1px solid #3a3a50;
          padding: 1em;
          overflow-x: auto;
          font-size: 9pt;
          line-height: 1.5;
          page-break-inside: avoid;
          margin: 1em 0;
        }

        pre code {
          background: transparent;
          padding: 0;
          border: none;
          color: #eeeef2;
          font-size: inherit;
        }

        /* ── Tables ────────────────────────────────────────────────── */
        table {
          border-collapse: collapse;
          width: 100%;
          margin: 1em 0;
          font-size: 10pt;
          page-break-inside: avoid;
          border: 1px solid #3a3a50;
          background: #16161d;
        }

        th, td {
          padding: 8px 12px;
          text-align: left;
          border: 1px solid #2a2a38;
        }

        th {
          background: #1e1e28;
          font-weight: 700;
          color: #f5a623;
        }

        td {
          background: #16161d;
          color: #eeeef2;
        }

        tr:nth-child(even) td {
          background: #1e1e28;
        }

        /* ── Lists ─────────────────────────────────────────────────── */
        ul, ol {
          margin: 0.6em 0;
          padding-left: 2em;
        }

        ul {
          list-style: disc;
        }

        ul ul {
          list-style: circle;
        }

        ul ul ul {
          list-style: square;
        }

        ol {
          list-style: decimal;
        }

        li {
          margin: 0.3em 0;
        }

        li > p {
          margin: 0.2em 0;
        }

        /* ── Images ────────────────────────────────────────────────── */
        img {
          max-width: 100%;
          height: auto;
          display: block;
          margin: 1em auto;
          page-break-inside: avoid;
          border: 1px solid #2a2a38;
        }

        /* ── SVG ───────────────────────────────────────────────────── */
        svg {
          max-width: 100%;
          height: auto;
          page-break-inside: avoid;
        }

        /* ── Keyboard / Mark / Del ─────────────────────────────────── */
        kbd {
          font-family: monospace;
          font-size: 9pt;
          background: #1e1e28;
          color: #eeeef2;
          padding: 0.1em 0.4em;
          border: 1px solid #3a3a50;
        }

        mark {
          background: #f5a623;
          color: #000000;
          padding: 0.1em 0.2em;
        }

        del {
          color: #666680;
          text-decoration: line-through;
        }

        /* ── Print Optimizations ───────────────────────────────────── */
        @media print {
          h1, h2, h3, h4, h5, h6 {
            page-break-after: avoid;
          }

          p, li {
            orphans: 3;
            widows: 3;
          }

          pre, blockquote, table, img {
            page-break-inside: avoid;
          }

          a[href]::after {
            content: ' (' attr(href) ')';
            font-size: 9pt;
            color: #666680;
          }

          a[href^="#"]::after,
          a[href^="javascript:"]::after {
            content: '';
          }
        }
        """

        # Wrap HTML with proper structure
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>{mobile_css}</style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """

        # Ensure output directory exists
        # (called from async context via asyncio.to_thread — mkdir is safe here)

        # Convert HTML to PDF using Playwright (highest quality)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Set content with proper base URL for relative image paths
            page.set_content(full_html, wait_until="networkidle")

            # Generate PDF with mobile-friendly settings
            page.pdf(
                path=str(output_path),
                format="A4",
                print_background=True,
                margin={
                    "top": "1.5cm",
                    "right": "1cm",
                    "bottom": "1.5cm",
                    "left": "1cm",
                },
            )

            browser.close()

        return True, f"Successfully converted {markdown_path.name} to {output_path.name}"

    except Exception as e:
        logger.error(f"Failed to convert markdown to PDF: {e}")
        return False, f"Conversion failed: {str(e)}"


@tool("markdown_to_pdf", parse_docstring=True)
async def markdown_to_pdf_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    markdown_file: str,
    output_filename: str | None = None,
    tool_call_id: Annotated[str, InjectedToolCallId] = "",
) -> Command:
    """Convert a markdown file to a mobile-friendly PDF with charts and images.

    This tool takes a markdown file and converts it to a well-formatted PDF optimized
    for mobile viewing. It properly handles:
    - Images (embedded or linked)
    - Code blocks with syntax highlighting
    - Tables and charts
    - Lists, blockquotes, and formatting
    - Mobile-friendly layout (readable font sizes, proper margins)

    The output PDF will be saved to `/mnt/user-data/outputs` and automatically presented
    to the user.

    Args:
        markdown_file: Path to the markdown file to convert. Can be absolute or relative to workspace.
        output_filename: Optional custom name for the output PDF file (without extension).
                        If not provided, uses the markdown filename with .pdf extension.

    Returns:
        Command with the result message and artifact path.

    Example:
        markdown_to_pdf(
            markdown_file="/mnt/user-data/workspace/report.md",
            output_filename="mobile_report"
        )
    """
    if runtime.state is None:
        return Command(update={"messages": [ToolMessage("Error: Thread runtime state not available", tool_call_id=tool_call_id)]})

    thread_id = runtime.context.get("thread_id") if runtime.context else None
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: Thread ID not available", tool_call_id=tool_call_id)]})

    thread_data = runtime.state.get("thread_data") or {}
    workspace_path = thread_data.get("workspace_path")
    outputs_path = thread_data.get("outputs_path")

    if not workspace_path or not outputs_path:
        return Command(update={"messages": [ToolMessage("Error: Thread paths not available", tool_call_id=tool_call_id)]})

    # Resolve input markdown file path
    md_path_str = markdown_file.lstrip("/")
    if md_path_str.startswith("mnt/user-data/workspace/"):
        # Virtual path - resolve to actual path
        relative = md_path_str.replace("mnt/user-data/workspace/", "")
        md_path = Path(workspace_path) / relative
    elif md_path_str.startswith("mnt/user-data/outputs/"):
        # Virtual path - resolve to actual path
        relative = md_path_str.replace("mnt/user-data/outputs/", "")
        md_path = Path(outputs_path) / relative
    else:
        # Assume relative to workspace
        md_path = Path(workspace_path) / md_path_str

    md_path = md_path.resolve()

    # Validate input file exists
    if not md_path.exists():
        return Command(update={"messages": [ToolMessage(f"Error: Markdown file not found: {markdown_file}", tool_call_id=tool_call_id)]})

    if not md_path.is_file():
        return Command(update={"messages": [ToolMessage(f"Error: Path is not a file: {markdown_file}", tool_call_id=tool_call_id)]})

    # Determine output filename
    if output_filename:
        pdf_filename = output_filename if output_filename.endswith(".pdf") else f"{output_filename}.pdf"
    else:
        pdf_filename = md_path.stem + ".pdf"

    output_path = Path(outputs_path) / pdf_filename

    # Create output directory before entering the thread to avoid blocking calls inside to_thread
    await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)

    # Run blocking Playwright conversion in a thread pool to avoid blocking the async event loop
    success, message = await asyncio.to_thread(_convert_markdown_to_pdf, md_path, output_path, True)

    if not success:
        return Command(update={"messages": [ToolMessage(f"Error: {message}", tool_call_id=tool_call_id)]})

    # Add artifact for user viewing
    virtual_path = f"/mnt/user-data/outputs/{pdf_filename}"
    return Command(
        update={
            "artifacts": [virtual_path],
            "messages": [ToolMessage(f"✓ {message}\n\nOutput: {virtual_path}", tool_call_id=tool_call_id)],
        }
    )
