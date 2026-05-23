"""Thin MCP stdio server wrapping the Google Workspace CLI (``gws``).

Exposes Google Drive + Docs operations as MCP tools by shelling out to
``gws`` from https://github.com/googleworkspace/cli. The underlying CLI
reads a plaintext ``authorized_user`` credentials JSON from
``GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE`` and handles OAuth refresh
internally, so this wrapper does not need to manage tokens.

Spawned by deer-flow's MCP client when the ``gdrive`` preset is enabled.
The wrapper is intentionally small — no Google SDK dependency, no
authentication logic, just a JSON-in/JSON-out bridge for MCP clients.

Tools exposed:
- ``gdrive_search`` — list / search Drive files (defaults to most-recent
  sort order when no query is supplied).
- ``gdrive_read_file`` — read a single file by ID. Google Docs → markdown,
  Sheets → CSV, Slides → plain text; regular text files are returned as
  UTF-8 text; binary files come back as a size summary.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

logger = logging.getLogger("deerflow.mcp_servers.gdrive_gws")

server: Server = Server("gdrive-gws")

GWS_BIN = os.environ.get("GWS_BIN", "gws")

# Google Workspace mime types that need export rather than direct download.
EXPORT_MIMES: dict[str, str] = {
    "application/vnd.google-apps.document": "text/markdown",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
    "application/vnd.google-apps.drawing": "image/png",
}

TEXT_MIMES_PREFIX = ("text/",)
TEXT_MIMES_EXACT = {"application/json", "application/xml", "application/x-yaml"}

# Default ceiling for text payloads returned to the agent. 80 000 characters
# works out to ~25k tokens for English and ~40k for CJK — large enough for
# typical docs but small enough to stay well under a 128k context window
# when combined with chat history and tool schemas. Callers can raise or
# lower this per-invocation via the ``max_chars`` argument on
# ``gdrive_read_file``.
DEFAULT_MAX_CHARS = 80_000


class GwsError(RuntimeError):
    pass


async def _run_gws(args: list[str], cwd: str | None = None) -> tuple[dict, str]:
    """Run ``gws`` and return (parsed JSON payload, raw stdout)."""
    proc = await asyncio.create_subprocess_exec(
        GWS_BIN,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    stderr_text = stderr.decode(errors="replace")
    stdout_text = stdout.decode(errors="replace")
    if proc.returncode != 0:
        raise GwsError(f"gws {' '.join(args[:3])} failed (exit {proc.returncode}): {stderr_text.strip() or stdout_text.strip()}")
    # ``gws`` occasionally prints progress lines before the JSON payload.
    # Parse the last non-empty line, falling back to the whole output.
    text = stdout_text.strip()
    if not text:
        return {}, stdout_text
    try:
        return json.loads(text), stdout_text
    except json.JSONDecodeError:
        # Sometimes the JSON is preceded by status lines; try the last { ... } block.
        start = text.rfind("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1]), stdout_text
            except json.JSONDecodeError:
                pass
        return {"raw": text}, stdout_text


@server.list_tools()
async def _list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="gdrive_search",
            description=("Search Google Drive files. If no query is provided, returns the most-recently modified files. Results include id, name, mimeType, modifiedTime, and webViewLink."),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional Google Drive search query (e.g. \"name contains 'report'\", \"mimeType='application/pdf'\").",
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Maximum number of files to return (1-100).",
                    },
                },
            },
        ),
        types.Tool(
            name="gdrive_read_file",
            description=(
                "Read a Google Drive file by ID. Google Docs are exported as markdown, Sheets as "
                "CSV, Slides as plain text, drawings as PNG (base64). Plain text files are returned "
                "directly. Binary files return a size summary. Large text payloads are truncated "
                f"to ~{DEFAULT_MAX_CHARS:,} characters by default to keep the response within the "
                "model context window — pass max_chars to override and offset to read from a "
                "specific position."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {
                        "type": "string",
                        "description": "Google Drive file ID.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 400_000,
                        "default": DEFAULT_MAX_CHARS,
                        "description": "Maximum characters of text to return. Files larger than this are truncated with a clear marker at the end.",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "default": 0,
                        "description": "Character offset to start reading from. Use with max_chars to page through very large files.",
                    },
                },
                "required": ["file_id"],
            },
        ),
        types.Tool(
            name="gdrive_get_metadata",
            description="Return metadata (id, name, mimeType, size, modifiedTime, webViewLink) for a Drive file by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                },
                "required": ["file_id"],
            },
        ),
    ]


async def _search(query: str, max_results: int) -> list[types.TextContent]:
    params: dict = {
        "pageSize": max_results,
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink,owners(displayName))",
        "orderBy": "modifiedTime desc",
    }
    if query:
        params["q"] = query
    payload, _ = await _run_gws(["drive", "files", "list", "--params", json.dumps(params)])
    files = payload.get("files", [])
    return [
        types.TextContent(
            type="text",
            text=json.dumps({"count": len(files), "files": files}, indent=2, ensure_ascii=False),
        )
    ]


async def _get_metadata(file_id: str) -> dict:
    payload, _ = await _run_gws(
        [
            "drive",
            "files",
            "get",
            "--params",
            json.dumps(
                {
                    "fileId": file_id,
                    "fields": "id,name,mimeType,size,modifiedTime,webViewLink,owners(displayName)",
                }
            ),
        ]
    )
    return payload


def _slice_text(text: str, offset: int, max_chars: int, name: str, mime: str) -> str:
    """Slice a text payload to ``[offset, offset+max_chars)`` with a clear header."""
    total = len(text)
    start = max(0, min(offset, total))
    end = min(total, start + max_chars)
    chunk = text[start:end]

    header_lines = [f"# {name}", "", f"> mimeType: `{mime}`"]
    if start > 0 or end < total:
        header_lines.append(f"> Showing characters {start:,}–{end:,} of {total:,} total ({(end - start):,} returned; pass offset={end} to continue).")
    header = "\n".join(header_lines) + "\n\n"
    return header + chunk


async def _read_file(
    file_id: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    offset: int = 0,
) -> list[types.TextContent]:
    meta = await _get_metadata(file_id)
    mime = str(meta.get("mimeType", ""))
    name = str(meta.get("name", file_id))

    export_mime = EXPORT_MIMES.get(mime)

    with tempfile.TemporaryDirectory(prefix="gdrive-gws-") as workdir:
        if export_mime is not None:
            await _run_gws(
                [
                    "drive",
                    "files",
                    "export",
                    "--params",
                    json.dumps({"fileId": file_id, "mimeType": export_mime}),
                    "--output",
                    "export.out",
                ],
                cwd=workdir,
            )
            out_path = Path(workdir) / "export.out"
            if export_mime.startswith("text/") or export_mime == "application/json":
                content = out_path.read_text(encoding="utf-8", errors="replace")
                return [
                    types.TextContent(
                        type="text",
                        text=_slice_text(content, offset, max_chars, name, f"{mime} → {export_mime}"),
                    )
                ]
            # Binary export (e.g. PNG for drawings)
            data = out_path.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            return [
                types.TextContent(
                    type="text",
                    text=(f"# {name}\n\nmimeType: {mime}\nexport: {export_mime}\nbytes: {len(data):,}\nbase64 (truncated to 512 chars):\n{b64[:512]}"),
                )
            ]

        # Regular (non-Workspace) file — download.
        await _run_gws(
            [
                "drive",
                "files",
                "get",
                "--params",
                json.dumps({"fileId": file_id}),
                "--output",
                "download.bin",
            ],
            cwd=workdir,
        )
        out_path = Path(workdir) / "download.bin"
        data = out_path.read_bytes()

        if mime.startswith(TEXT_MIMES_PREFIX) or mime in TEXT_MIMES_EXACT:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("utf-8", errors="replace")
            return [
                types.TextContent(
                    type="text",
                    text=_slice_text(text, offset, max_chars, name, mime),
                )
            ]

        b64 = base64.b64encode(data).decode("ascii")
        return [
            types.TextContent(
                type="text",
                text=(f"# {name}\n\nmimeType: {mime}\nbytes: {len(data):,}\n(binary file; base64 truncated to 512 chars)\n{b64[:512]}"),
            )
        ]


@server.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "gdrive_search":
            query = str(arguments.get("query", "") or "").strip()
            max_results = int(arguments.get("max_results", 10) or 10)
            return await _search(query, max_results)

        if name == "gdrive_read_file":
            file_id = arguments["file_id"]
            max_chars = int(arguments.get("max_chars") or DEFAULT_MAX_CHARS)
            offset = int(arguments.get("offset") or 0)
            return await _read_file(file_id, max_chars=max_chars, offset=offset)

        if name == "gdrive_get_metadata":
            file_id = arguments["file_id"]
            meta = await _get_metadata(file_id)
            return [types.TextContent(type="text", text=json.dumps(meta, indent=2, ensure_ascii=False))]

        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    except GwsError as e:
        logger.error("gws command failed: %s", e)
        return [types.TextContent(type="text", text=f"gws error: {e}")]
    except Exception as e:
        logger.exception("gdrive_gws tool %s failed", name)
        return [types.TextContent(type="text", text=f"Unexpected error: {e}")]


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("GDRIVE_GWS_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
