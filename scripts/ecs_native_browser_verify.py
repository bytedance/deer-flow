"""One no-network distribution check; identical default launch options to native headless."""

import asyncio
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

from playwright.async_api import async_playwright


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def main():
    assert os.getuid() == 1000 and os.getgid() == 1000
    assert importlib.metadata.version("playwright") == "1.61.0"
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/deerflow-browsers"
    root = Path("/opt/deerflow-browsers")
    binaries = list(
        (root / "chromium_headless_shell-1228").rglob("chrome-headless-shell")
    )
    if len(binaries) != 1 or not binaries[0].is_file():
        print(json.dumps({"browser_distribution": "MISSING_HEADLESS_SHELL_1228"}))
        return 3
    assert {p.name for p in root.iterdir()} == {
        ".links",
        "chromium_headless_shell-1228",
        "ffmpeg-1011",
    }
    binary = binaries[0]
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            assert browser.version == "149.0.7827.55"
            page = await browser.new_page(viewport={"width": 640, "height": 480})
            await page.set_content(
                '<title>Native headless distribution</title><h1>Browser ready</h1><input aria-label="Acceptance input">'
            )
            await page.get_by_role("textbox", name="Acceptance input").fill(
                "native-headless-1228"
            )
            assert (
                await page.get_by_role("textbox", name="Acceptance input").input_value()
                == "native-headless-1228"
            )
            screenshot = await page.screenshot(type="png")
            assert screenshot[:8] == b"\x89PNG\r\n\x1a\n" and len(screenshot) > 1000
            print(
                json.dumps(
                    {
                        "browser_distribution": "PASS",
                        "uid": os.getuid(),
                        "gid": os.getgid(),
                        "playwright_version": "1.61.0",
                        "browser_version": browser.version,
                        "revision": "1228",
                        "binary_path": str(binary),
                        "binary_sha256": sha(binary),
                        "headless": True,
                        "channel": None,
                        "launch_options": {"headless": True},
                        "page_title": await page.title(),
                        "input_verified": True,
                        "screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
                        "screenshot_bytes": len(screenshot),
                        "screenshot_base64": base64.b64encode(screenshot).decode(),
                        "models_called": False,
                        "network": "none",
                        "scope": "headless_no_channel_distribution_only",
                    }
                )
            )
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
