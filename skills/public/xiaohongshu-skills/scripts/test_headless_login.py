"""测试无头环境下手机登录流程中 headless 参数传递是否正确。

模拟 Linux 无桌面环境（has_display() = False），验证修复后的代码路径。
"""
from __future__ import annotations

import argparse
import sys
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))


# ---------- 工具 ----------

def _make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(host="127.0.0.1", port=9222, account="")
    return argparse.Namespace(**{**defaults, **kwargs})


# ---------- Bug 2：_connect / _connect_existing ----------

class TestConnectHeadless:
    """_connect 和 _connect_existing 在无头环境下应传 headless=True。"""

    def test_connect_headless_when_no_display(self):
        mock_page = MagicMock()
        mock_browser_inst = MagicMock()
        mock_browser_inst.new_page.return_value = mock_page

        with (
            patch("chrome_launcher.has_display", return_value=False),
            patch("chrome_launcher.ensure_chrome", return_value=True) as mock_ensure,
            patch("xhs.cdp.Browser", return_value=mock_browser_inst),
        ):
            import cli
            cli._connect(_make_args())

        mock_ensure.assert_called_once_with(port=9222, headless=True)

    def test_connect_headed_when_has_display(self):
        mock_page = MagicMock()
        mock_browser_inst = MagicMock()
        mock_browser_inst.new_page.return_value = mock_page

        with (
            patch("chrome_launcher.has_display", return_value=True),
            patch("chrome_launcher.ensure_chrome", return_value=True) as mock_ensure,
            patch("xhs.cdp.Browser", return_value=mock_browser_inst),
        ):
            import cli
            cli._connect(_make_args())

        mock_ensure.assert_called_once_with(port=9222, headless=False)

    def test_connect_existing_headless_when_no_display(self):
        mock_page = MagicMock()
        mock_browser_inst = MagicMock()
        mock_browser_inst.get_existing_page.return_value = mock_page

        with (
            patch("chrome_launcher.has_display", return_value=False),
            patch("chrome_launcher.ensure_chrome", return_value=True) as mock_ensure,
            patch("xhs.cdp.Browser", return_value=mock_browser_inst),
        ):
            import cli
            cli._connect_existing(_make_args())

        mock_ensure.assert_called_once_with(port=9222, headless=True)


# ---------- Bug 1：send-code RateLimitError 重启 ----------

class TestSendCodeRateLimit:
    """触发频率限制时，重启 Chrome 应使用正确的 headless 参数。"""

    def _run_send_code(self, has_display_value: bool):
        """运行 cmd_send_code 并触发 RateLimitError，返回 restart_chrome 的调用记录。"""
        from xhs.errors import RateLimitError

        mock_page = MagicMock()
        mock_browser_inst = MagicMock()
        mock_browser_inst.new_page.return_value = mock_page

        with (
            patch("chrome_launcher.has_display", return_value=has_display_value),
            patch("chrome_launcher.ensure_chrome", return_value=True),
            patch("chrome_launcher.restart_chrome") as mock_restart,
            patch("xhs.cdp.Browser", return_value=mock_browser_inst),
            patch("xhs.login.send_phone_code", side_effect=[RateLimitError(), True]),
            pytest.raises(SystemExit),  # _output 会 sys.exit
        ):
            import cli
            cli.cmd_send_code(_make_args(phone="13800138000"))

        return mock_restart

    def test_rate_limit_restart_headless_when_no_display(self):
        mock_restart = self._run_send_code(has_display_value=False)
        mock_restart.assert_called_once_with(port=9222, headless=True)

    def test_rate_limit_restart_headed_when_has_display(self):
        mock_restart = self._run_send_code(has_display_value=True)
        mock_restart.assert_called_once_with(port=9222, headless=False)


# ---------- Bug 3：_headless_fallback ----------

class TestHeadlessFallback:
    """_headless_fallback 在有/无桌面时行为应不同。"""

    def test_no_display_returns_error_without_restart(self):
        with (
            patch("chrome_launcher.has_display", return_value=False),
            patch("chrome_launcher.restart_chrome") as mock_restart,
            pytest.raises(SystemExit) as exc_info,
        ):
            import io, json
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                import cli
                cli._headless_fallback(port=9222)

        mock_restart.assert_not_called()
        assert exc_info.value.code == 1
        output = json.loads(buf.getvalue())
        assert output["action"] == "login_required"
        assert "send-code" in output["message"]

    def test_has_display_restarts_headed(self):
        with (
            patch("chrome_launcher.has_display", return_value=True),
            patch("chrome_launcher.restart_chrome") as mock_restart,
            pytest.raises(SystemExit),
        ):
            import cli
            cli._headless_fallback(port=9222)

        mock_restart.assert_called_once_with(port=9222, headless=False)
