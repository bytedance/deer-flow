import asyncio
import io
import json
import zipfile
from types import SimpleNamespace

import pytest
from deerflow_extension_trajectory.exporting import (
    ExportLimit,
    build_download,
    collect_export,
)


def test_export_caps_checkpoint_reads_and_reports_incomplete_history():
    def cfg(cid):
        return {"configurable": {"thread_id": "t", "checkpoint_id": cid}}

    states = {
        str(index): SimpleNamespace(
            config=cfg(str(index)),
            parent_config=cfg(str(index - 1)) if index else None,
            values={"messages": []},
            next=(),
            created_at="now",
        )
        for index in range(3)
    }

    class Accessor:
        async def aget_tuple(self, config):
            return states.get(config["configurable"]["checkpoint_id"])

        aget = aget_tuple

    with pytest.raises(ExportLimit):
        asyncio.run(collect_export(Accessor(), cfg("2"), max_checkpoints=2))
    del states["1"]
    incomplete = asyncio.run(collect_export(Accessor(), cfg("2")))
    assert not incomplete["history_complete"] and incomplete["warnings"]


def test_zip_embeds_images_once_and_preserves_missing_image_warnings():
    image = {
        "name": "photo.png",
        "path": "/mnt/user-data/uploads/photo.png",
        "size": "1 KB",
    }
    missing = {
        "name": "gone.png",
        "path": "/mnt/user-data/uploads/gone.png",
        "size": "1 KB",
    }
    rows = [
        {
            "kind": "user",
            "text": "hello",
            "images": [image, image, missing],
            "created_at": "now",
            "tool_calls": [],
        },
        {
            "kind": "assistant",
            "text": "```\ntext",
            "tool_calls": [{"id": "call1", "name": "read_file", "args": "完整参数"}],
        },
        {"kind": "tool", "text": "完整结果", "tool_call_id": "call1"},
    ]
    data = {
        "thread_id": "t",
        "head_checkpoint_id": "c",
        "source": "checkpoint",
        "history_complete": True,
        "warnings": [],
        "rows": rows,
    }
    reads = []

    def image_reader(path):
        reads.append(path)
        if "gone" in path:
            raise FileNotFoundError()
        return b"\x89PNG\r\n\x1a\nimage"

    content, warnings = build_download(data, "markdown", image_reader)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert len([p for p in archive.namelist() if p.startswith("images/")]) == 1
        markdown = archive.read("trajectory.md").decode()
        assert "images/" in markdown and "图片未打包" in markdown
        assert (
            "完整参数" in markdown
            and "完整结果" in markdown
            and "read_file" in markdown
        )
        assert archive.read("EXPORT_NOTES.txt")
    assert len(reads) == 2 and warnings
    content, _ = build_download(
        data, "json", lambda p: pytest.fail("JSON must not read image files")
    )
    assert json.loads(content)["rows"][0]["images"][0]["path"] == image["path"]


def test_child_markdown_nesting_preserves_tool_text_that_looks_like_headings():
    from deerflow_extension_trajectory.exporting import render_markdown

    child = {
        "thread_id": "thread",
        "head_checkpoint_id": "child",
        "name": "bash",
        "execution_id": "execution",
        "warnings": [],
        "rows": [
            {
                "kind": "tool",
                "text": "# literal shell comment\n## literal output",
                "tool_name": "bash",
            }
        ],
    }
    data = {
        "thread_id": "thread",
        "head_checkpoint_id": "root",
        "rows": [
            {
                "kind": "assistant",
                "text": "",
                "tool_calls": [{"name": "task", "args": "{}", "subagents": [child]}],
            }
        ],
    }
    markdown = render_markdown(data, {}, [])
    assert "# literal shell comment\n## literal output" in markdown
    assert "#### 子 agent 轨迹" in markdown
