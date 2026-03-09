"""统一 CLI 入口，对应 Go MCP 工具的 13 个子命令。

全局选项: --host, --port, --account
输出: JSON（ensure_ascii=False）
退出码: 0=成功, 1=未登录, 2=错误
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sys
import tempfile

def _session_tab_file(port: int) -> str:
    """返回指定端口的 session tab 文件路径（每账号独立隔离）。"""
    return os.path.join(tempfile.gettempdir(), "xhs", f"session_tab_{port}.txt")


def _login_tab_file(port: int) -> str:
    """返回指定端口的 login tab 文件路径（每账号独立隔离）。"""
    return os.path.join(tempfile.gettempdir(), "xhs", f"login_tab_{port}.txt")


def _save_login_tab(target_id: str, port: int) -> None:
    path = _login_tab_file(port)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(target_id)


def _load_login_tab(port: int) -> str | None:
    with contextlib.suppress(FileNotFoundError):
        data = open(_login_tab_file(port)).read().strip()
        return data or None
    return None


def _clear_login_tab(port: int) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(_login_tab_file(port))


def _save_session_tab(target_id: str, port: int) -> None:
    path = _session_tab_file(port)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(target_id)


def _load_session_tab(port: int) -> str | None:
    with contextlib.suppress(FileNotFoundError):
        data = open(_session_tab_file(port)).read().strip()
        return data or None
    return None


def _clear_session_tab(port: int) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(_session_tab_file(port))

# Windows 控制台默认编码（如 cp1252）不支持中文，强制 UTF-8
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("xhs-cli")


def _output(data: dict, exit_code: int = 0) -> None:
    """输出 JSON 并退出。"""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def _open_file_if_display(path: str) -> None:
    """有桌面环境时用系统默认程序打开文件，无界面环境静默跳过。"""
    from chrome_launcher import has_display

    if not has_display():
        return

    import platform
    import subprocess

    try:
        system = platform.system()
        if system == "Windows":
            os.startfile(path)
        elif system == "Darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        logger.debug("无法自动打开文件: %s", path)


def _update_account_nickname(args: argparse.Namespace, page) -> None:
    """登录成功后，将平台昵称写入账号描述（best-effort，失败不影响登录结果）。"""
    if not getattr(args, "account", ""):
        return
    import sys as _sys

    _sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    import account_manager
    from xhs.login import get_current_user_nickname

    try:
        nickname = get_current_user_nickname(page)
        if nickname:
            account_manager.update_account_description(args.account, nickname)
            logger.info("账号 %s 昵称已更新: %s", args.account, nickname)
    except Exception as e:
        logger.warning("更新账号昵称失败: %s", e)


def _resolve_account(args: argparse.Namespace) -> str | None:
    """解析 --account 参数，更新 args.port，返回 user_data_dir（无账号时返回 None）。"""
    if not getattr(args, "account", ""):
        return None
    import sys as _sys

    _sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    import account_manager

    name = args.account
    args.port = account_manager.get_account_port(name)
    return account_manager.get_profile_dir(name)


def _connect(args: argparse.Namespace):
    """连接到 Chrome 并返回 (browser, page)。

    优先复用上次命令留下的 tab（通过端口隔离的 session tab 文件记录），
    避免每次命令都新建 tab 导致 Chrome 中 tab 堆积。
    """
    from chrome_launcher import ensure_chrome, has_display
    from xhs.cdp import Browser

    user_data_dir = _resolve_account(args)

    if not ensure_chrome(port=args.port, headless=not has_display(), user_data_dir=user_data_dir):
        _output(
            {"success": False, "error": "无法启动 Chrome，请检查 Chrome 是否已安装"},
            exit_code=2,
        )

    browser = Browser(host=args.host, port=args.port)
    browser.connect()

    # 优先复用上次命令留下的 tab
    saved_id = _load_session_tab(args.port)
    if saved_id:
        page = browser.get_page_by_target_id(saved_id)
        if page:
            logger.debug("复用会话 tab: %s", saved_id)
            _save_session_tab(page.target_id, args.port)
            return browser, page
        logger.warning("会话 tab (target_id=%s) 已失效，重新获取", saved_id)

    page = browser.get_or_create_page()
    _save_session_tab(page.target_id, args.port)
    return browser, page


def _connect_saved_tab(args: argparse.Namespace):
    """连接到登录流程中记录的精确 tab，回退到第一个非空白 tab。"""
    from chrome_launcher import ensure_chrome, has_display
    from xhs.cdp import Browser

    user_data_dir = _resolve_account(args)

    if not ensure_chrome(port=args.port, headless=not has_display(), user_data_dir=user_data_dir):
        _output({"success": False, "error": "无法连接到 Chrome"}, exit_code=2)

    browser = Browser(host=args.host, port=args.port)
    browser.connect()

    target_id = _load_login_tab(args.port)
    if target_id:
        page = browser.get_page_by_target_id(target_id)
        if page:
            return browser, page
        logger.warning("保存的 tab (target_id=%s) 已失效，回退到第一个可用 tab", target_id)

    page = browser.get_existing_page()
    if not page:
        _output(
            {"success": False, "error": "未找到已打开的登录页面，请重新执行登录前置步骤"},
            exit_code=2,
        )
    return browser, page


def _connect_existing(args: argparse.Namespace):
    """连接到 Chrome 并复用已有页面（用于分步发布的后续步骤）。"""
    from chrome_launcher import ensure_chrome, has_display
    from xhs.cdp import Browser

    user_data_dir = _resolve_account(args)

    if not ensure_chrome(port=args.port, headless=not has_display(), user_data_dir=user_data_dir):
        _output(
            {"success": False, "error": "无法连接到 Chrome"},
            exit_code=2,
        )

    browser = Browser(host=args.host, port=args.port)
    browser.connect()
    page = browser.get_existing_page()
    if not page:
        _output(
            {"success": False, "error": "未找到已打开的页面，请先执行前置步骤"},
            exit_code=2,
        )
    return browser, page


def _headless_fallback(port: int) -> None:
    """Headless 模式未登录时的处理：有桌面降级到有窗口模式，无桌面直接报错提示。"""
    from chrome_launcher import has_display, restart_chrome

    if has_display():
        logger.info("Headless 模式未登录，切换到有窗口模式...")
        restart_chrome(port=port, headless=False)
        _output(
            {
                "success": False,
                "error": "未登录",
                "action": "switched_to_headed",
                "message": "已切换到有窗口模式，请在浏览器中扫码登录",
            },
            exit_code=1,
        )
    else:
        _output(
            {
                "success": False,
                "error": "未登录",
                "action": "login_required",
                "message": "无界面环境下请先运行 send-code --phone <手机号> 完成登录",
            },
            exit_code=1,
        )

def _qrcode_fallback(browser, page, args: argparse.Namespace) -> None:
    """频率限制时刷新页面返回二维码，让 AI 直接展示给用户扫码。"""
    from xhs.login import (
        fetch_qrcode,
        make_qrcode_url,
        save_qrcode_to_file,
    )
    from xhs.urls import EXPLORE_URL

    # 刷新页面使登录弹窗回到默认的二维码 tab
    page.navigate(EXPLORE_URL)
    page.wait_for_load()

    png_bytes, _b64_orig, already = fetch_qrcode(page)
    if already:
        browser.close()
        _output({"logged_in": True, "message": "已登录"})
        return

    qrcode_path = save_qrcode_to_file(png_bytes)
    image_url, login_url = make_qrcode_url(png_bytes)

    _open_file_if_display(qrcode_path)

    _save_login_tab(page.target_id, args.port)
    _clear_session_tab(args.port)
    browser.close()
    result: dict = {
        "logged_in": False,
        "login_method": "qrcode",
        "qrcode_path": qrcode_path,
        "qrcode_image_url": image_url,
        "message": (
            "验证码发送受限，已切换为二维码登录，请扫码。"
            "扫码后运行 wait-login 等待登录结果。"
        ),
    }
    if login_url:
        result["qr_login_url"] = login_url
    _output(result, exit_code=1)


# ========== 子命令实现 ==========


def cmd_check_login(args: argparse.Namespace) -> None:
    """检查登录状态。未登录时自动获取二维码，省去单独调 get-qrcode 的一轮通信。

    直接调 fetch_qrcode 一步完成：导航 + 登录检查 + 二维码获取，
    不再经过 check_login_status 避免重复导航和等待。
    """
    from xhs.login import (
        fetch_qrcode,
        make_qrcode_url,
        save_qrcode_to_file,
    )

    browser, page = _connect(args)
    try:
        png_bytes, _b64_orig, already = fetch_qrcode(page)
        if already:
            _output({"logged_in": True}, exit_code=0)
            return

        qrcode_path = save_qrcode_to_file(png_bytes)
        image_url, login_url = make_qrcode_url(png_bytes)

        # 记录 login tab + 清除 session tab
        _save_login_tab(page.target_id, args.port)
        _clear_session_tab(args.port)

        _open_file_if_display(qrcode_path)

        from chrome_launcher import has_display

        result: dict = {
            "logged_in": False,
            "qrcode_path": qrcode_path,
            "qrcode_image_url": image_url,
        }
        if login_url:
            result["qr_login_url"] = login_url
        if has_display():
            result["login_method"] = "qrcode"
            result["hint"] = (
                "未登录，二维码已自动生成。"
                "扫码后运行 wait-login 等待登录结果"
            )
        else:
            result["login_method"] = "both"
            result["hint"] = (
                "未登录，二维码已自动生成。"
                "方式A: 直接扫码 + wait-login；"
                "方式B: send-code --phone <手机号>"
                " + verify-code（手机验证码）"
            )
        _output(result, exit_code=1)
    finally:
        # 只断开 CDP 连接，不关闭 tab——保留登录页面
        browser.close()


def cmd_login(args: argparse.Namespace) -> None:
    """获取登录二维码并阻塞等待扫码（最多 120 秒）。"""
    from xhs.login import fetch_qrcode, save_qrcode_to_file, wait_for_login

    browser, page = _connect(args)
    try:
        png_bytes, _b64, already = fetch_qrcode(page)
        if already:
            _output({"logged_in": True, "message": "已登录"})
            return

        qrcode_path = save_qrcode_to_file(png_bytes)
        _open_file_if_display(qrcode_path)
        print(
            json.dumps(
                {"qrcode_path": qrcode_path, "message": "请扫码登录"},
                ensure_ascii=False,
            )
        )
        success = wait_for_login(page, timeout=120)
        if success:
            _update_account_nickname(args, page)
        _output(
            {"logged_in": success, "message": "登录成功" if success else "登录超时"},
            exit_code=0 if success else 2,
        )
    finally:
        browser.close_page(page)
        browser.close()


def cmd_phone_login(args: argparse.Namespace) -> None:
    """手机号+验证码登录（适用于无界面服务器）。"""
    from xhs.errors import RateLimitError
    from xhs.login import send_phone_code, submit_phone_code

    browser, page = _connect(args)
    try:
        sent = send_phone_code(page, args.phone)
    except RateLimitError:
        # 频率限制——直接切换二维码登录
        logger.info("验证码发送受限，切换为二维码登录")
        _qrcode_fallback(browser, page, args)
        return

    try:
        if not sent:
            _output({"logged_in": True, "message": "已登录，无需重新登录"})
            return

        # 输出提示，等待用户在终端输入验证码
        print(
            json.dumps(
                {
                    "status": "code_sent",
                    "message": (
                        f"验证码已发送至 "
                        f"{args.phone[:3]}****{args.phone[-4:]}"
                    ),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

        # 从 --code 参数或交互式 stdin 读取验证码
        if args.code:
            code = args.code.strip()
        else:
            try:
                code = input("请输入验证码: ").strip()
            except EOFError:
                _output(
                    {"success": False, "error": "未收到验证码输入"},
                    exit_code=2,
                )
                return

        if not code:
            _output(
                {"success": False, "error": "验证码不能为空"},
                exit_code=2,
            )
            return

        success = submit_phone_code(page, code)
        _output(
            {
                "logged_in": success,
                "message": "登录成功" if success else "验证码错误或超时",
            },
            exit_code=0 if success else 2,
        )
    finally:
        # 不关闭 tab——与 verify-code 一致，保留页面供重试
        browser.close()


def cmd_get_qrcode(args: argparse.Namespace) -> None:
    """获取登录二维码并立即返回（非阻塞）。

    从登录弹窗的二维码 img 元素读取图片（data URL 或网络 URL），
    保存为本地 PNG 文件后立即退出。Chrome tab 保持打开，QR 会话继续有效。
    调用方收到 qrcode_data_url 后直接内嵌到对话窗口显示；同时浏览器窗口（GUI 环境）
    也会显示二维码，用户可选择扫任意一个。
    """
    from xhs.login import (
        fetch_qrcode,
        make_qrcode_url,
        save_qrcode_to_file,
    )

    browser, page = _connect(args)

    png_bytes, _b64_orig, already = fetch_qrcode(page)
    if already:
        browser.close_page(page)
        browser.close()
        _output({"logged_in": True, "message": "已登录"})
        return

    qrcode_path = save_qrcode_to_file(png_bytes)
    image_url, login_url = make_qrcode_url(png_bytes)

    _open_file_if_display(qrcode_path)

    # 记录 login tab，供 wait-login 精确 reconnect
    _save_login_tab(page.target_id, args.port)
    # 清除 session tab 引用——隔离登录表单，防止其他命令复用
    _clear_session_tab(args.port)

    # 只断开 CDP 连接，不关闭 tab——QR 会话保持
    browser.close()
    result: dict = {
        "qrcode_path": qrcode_path,
        "qrcode_image_url": image_url,
        "message": "二维码已生成，请扫码登录。"
        "扫码后运行 wait-login 等待登录结果。",
    }
    if login_url:
        result["qr_login_url"] = login_url
    _output(result)


def cmd_wait_login(args: argparse.Namespace) -> None:
    """等待扫码登录完成（配合 get-qrcode 使用）。

    连接已有 Chrome tab，内部轮询直到登录成功或超时，替代 Skill 层的多次 check-login 轮询。
    """
    from xhs.login import wait_for_login

    browser, page = _connect_saved_tab(args)
    try:
        success = wait_for_login(page, timeout=args.timeout)
        if success:
            _clear_login_tab(args.port)
            _update_account_nickname(args, page)
        _output(
            {
                "logged_in": success,
                "message": "登录成功" if success else "等待超时，请重新运行 get-qrcode 获取新二维码",
            },
            exit_code=0 if success else 2,
        )
    finally:
        browser.close()


def cmd_send_code(args: argparse.Namespace) -> None:
    """分步登录第一步：填写手机号并发送验证码，保持页面不关闭。

    频率限制时返回错误信息和建议，由 AI 告知用户选择。
    """
    from xhs.errors import RateLimitError
    from xhs.login import send_phone_code

    browser, page = _connect(args)
    try:
        sent = send_phone_code(page, args.phone)
        if not sent:
            _output({"logged_in": True, "message": "已登录，无需重新登录"})
            return

        # 记录 login tab，供 verify-code 精确 reconnect
        _save_login_tab(page.target_id, args.port)
        # 清除 session tab 引用——隔离登录表单，防止其他命令复用并关闭/导航该 tab
        _clear_session_tab(args.port)
        _output({
            "status": "code_sent",
            "message": (
                f"验证码已发送至 {args.phone[:3]}****{args.phone[-4:]}，"
                "请运行 verify-code --code <验证码>"
            ),
        })
    except RateLimitError:
        # 频率限制——直接切换二维码登录
        logger.info("验证码发送受限，切换为二维码登录")
        _qrcode_fallback(browser, page, args)
    else:
        # 只断开控制连接，不关闭页面——tab 保持打开，verify-code 继续复用
        browser.close()


def cmd_verify_code(args: argparse.Namespace) -> None:
    """分步登录第二步：在已有页面上填写验证码并提交。"""
    from xhs.login import submit_phone_code

    browser, page = _connect_saved_tab(args)
    try:
        success = submit_phone_code(page, args.code)
        if success:
            _clear_login_tab(args.port)
            _update_account_nickname(args, page)
        _output(
            {"logged_in": success, "message": "登录成功" if success else "验证码错误或超时"},
            exit_code=0 if success else 2,
        )
    finally:
        # 不关闭 tab——成功后供后续命令复用，失败后用户可再次运行 verify-code 重试
        browser.close()


def cmd_delete_cookies(args: argparse.Namespace) -> None:
    """退出登录（页面 UI 点击退出）并删除 cookies 文件。"""
    from xhs.cookies import delete_cookies, get_cookies_file_path
    from xhs.login import logout

    # 先通过浏览器 UI 退出登录
    browser, page = _connect(args)
    try:
        logged_out = logout(page)
    finally:
        browser.close_page(page)
        browser.close()

    # 再删除本地 cookies 文件
    path = get_cookies_file_path(args.account)
    delete_cookies(path)

    _clear_session_tab(args.port)  # 退出登录后清除会话 tab 记录
    msg = "已退出登录并删除 cookies" if logged_out else "未登录，已删除 cookies 文件"
    _output({"success": True, "message": msg, "cookies_path": path})


def cmd_list_feeds(args: argparse.Namespace) -> None:
    """获取首页 Feed 列表。"""
    from xhs.feeds import list_feeds

    browser, page = _connect(args)
    try:
        feeds = list_feeds(page)
        _output({"feeds": [f.to_dict() for f in feeds], "count": len(feeds)})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_search_feeds(args: argparse.Namespace) -> None:
    """搜索 Feeds。"""
    from xhs.search import search_feeds
    from xhs.types import FilterOption

    filter_opt = FilterOption(
        sort_by=args.sort_by or "",
        note_type=args.note_type or "",
        publish_time=args.publish_time or "",
        search_scope=args.search_scope or "",
        location=args.location or "",
    )

    browser, page = _connect(args)
    try:
        feeds = search_feeds(page, args.keyword, filter_opt)
        _output({"feeds": [f.to_dict() for f in feeds], "count": len(feeds)})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_get_feed_detail(args: argparse.Namespace) -> None:
    """获取 Feed 详情。"""
    from xhs.feed_detail import get_feed_detail
    from xhs.types import CommentLoadConfig

    config = CommentLoadConfig(
        click_more_replies=args.click_more_replies,
        max_replies_threshold=args.max_replies_threshold,
        max_comment_items=args.max_comment_items,
        scroll_speed=args.scroll_speed,
    )

    browser, page = _connect(args)
    try:
        detail = get_feed_detail(
            page,
            args.feed_id,
            args.xsec_token,
            load_all_comments=args.load_all_comments,
            config=config,
        )
        _output(detail.to_dict())
    finally:
        browser.close_page(page)
        browser.close()


def cmd_user_profile(args: argparse.Namespace) -> None:
    """获取用户主页。"""
    from xhs.user_profile import get_user_profile

    browser, page = _connect(args)
    try:
        profile = get_user_profile(page, args.user_id, args.xsec_token)
        _output(profile.to_dict())
    finally:
        browser.close_page(page)
        browser.close()


def cmd_post_comment(args: argparse.Namespace) -> None:
    """发表评论。"""
    from xhs.comment import post_comment

    browser, page = _connect(args)
    try:
        post_comment(page, args.feed_id, args.xsec_token, args.content)
        _output({"success": True, "message": "评论发送成功"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_reply_comment(args: argparse.Namespace) -> None:
    """回复评论。"""
    from xhs.comment import reply_comment

    browser, page = _connect(args)
    try:
        reply_comment(
            page,
            args.feed_id,
            args.xsec_token,
            args.content,
            comment_id=args.comment_id or "",
            user_id=args.user_id or "",
        )
        _output({"success": True, "message": "回复成功"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_like_feed(args: argparse.Namespace) -> None:
    """点赞/取消点赞。"""
    from xhs.like_favorite import like_feed, unlike_feed

    browser, page = _connect(args)
    try:
        if args.unlike:
            result = unlike_feed(page, args.feed_id, args.xsec_token)
        else:
            result = like_feed(page, args.feed_id, args.xsec_token)
        _output(result.to_dict())
    finally:
        browser.close_page(page)
        browser.close()


def cmd_favorite_feed(args: argparse.Namespace) -> None:
    """收藏/取消收藏。"""
    from xhs.like_favorite import favorite_feed, unfavorite_feed

    browser, page = _connect(args)
    try:
        if args.unfavorite:
            result = unfavorite_feed(page, args.feed_id, args.xsec_token)
        else:
            result = favorite_feed(page, args.feed_id, args.xsec_token)
        _output(result.to_dict())
    finally:
        browser.close_page(page)
        browser.close()


def cmd_publish(args: argparse.Namespace) -> None:
    """发布图文内容。"""
    from image_downloader import process_images
    from xhs.login import check_login_status
    from xhs.publish import publish_image_content
    from xhs.types import PublishImageContent

    # 读取标题和正文
    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    # 处理图片
    image_paths = process_images(args.images) if args.images else []
    if not image_paths:
        _output({"success": False, "error": "没有有效的图片"}, exit_code=2)

    browser, page = _connect(args)
    try:
        # headless 模式登录检查 + 自动降级
        headless = getattr(args, "headless", False)
        if headless and not check_login_status(page):
            browser.close_page(page)
            browser.close()
            _headless_fallback(args.port)
            return

        publish_image_content(
            page,
            PublishImageContent(
                title=title,
                content=content,
                tags=args.tags or [],
                image_paths=image_paths,
                schedule_time=args.schedule_at,
                is_original=args.original,
                visibility=args.visibility or "",
            ),
        )
        _output({"success": True, "title": title, "images": len(image_paths), "status": "发布完成"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_fill_publish(args: argparse.Namespace) -> None:
    """只填写图文表单，不发布。"""
    from image_downloader import process_images
    from xhs.publish import fill_publish_form
    from xhs.types import PublishImageContent

    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    image_paths = process_images(args.images) if args.images else []
    if not image_paths:
        _output({"success": False, "error": "没有有效的图片"}, exit_code=2)

    browser, page = _connect(args)
    try:
        fill_publish_form(
            page,
            PublishImageContent(
                title=title,
                content=content,
                tags=args.tags or [],
                image_paths=image_paths,
                schedule_time=args.schedule_at,
                is_original=args.original,
                visibility=args.visibility or "",
            ),
        )
        _output(
            {
                "success": True,
                "title": title,
                "images": len(image_paths),
                "status": "表单已填写，等待确认发布",
            }
        )
    finally:
        # 不关闭页面，让用户在浏览器中预览
        browser.close()


def cmd_fill_publish_video(args: argparse.Namespace) -> None:
    """只填写视频表单，不发布。"""
    from xhs.publish_video import fill_publish_video_form
    from xhs.types import PublishVideoContent

    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    browser, page = _connect(args)
    try:
        fill_publish_video_form(
            page,
            PublishVideoContent(
                title=title,
                content=content,
                tags=args.tags or [],
                video_path=args.video,
                schedule_time=args.schedule_at,
                visibility=args.visibility or "",
            ),
        )
        _output(
            {
                "success": True,
                "title": title,
                "video": args.video,
                "status": "视频表单已填写，等待确认发布",
            }
        )
    finally:
        # 不关闭页面，让用户在浏览器中预览
        browser.close()


def cmd_click_publish(args: argparse.Namespace) -> None:
    """点击发布按钮（在用户确认后调用）。复用已有的发布页 tab。"""
    from xhs.publish import click_publish_button

    browser, page = _connect_existing(args)
    try:
        click_publish_button(page)
        _output({"success": True, "status": "发布完成"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_save_draft(args: argparse.Namespace) -> None:
    """保存为草稿（取消发布时调用）。"""
    from xhs.publish import save_as_draft

    browser, page = _connect_existing(args)
    try:
        save_as_draft(page)
        _output({"success": True, "status": "内容已保存到草稿箱"})
    finally:
        browser.close_page(page)
        browser.close()


def cmd_long_article(args: argparse.Namespace) -> None:
    """长文模式：填写内容 + 一键排版，返回模板列表。"""
    from xhs.publish_long_article import publish_long_article

    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    browser, page = _connect(args)
    try:
        template_names = publish_long_article(
            page,
            title=title,
            content=content,
            image_paths=args.images,
        )
        _output(
            {
                "success": True,
                "templates": template_names,
                "status": "长文已填写，请选择模板",
            }
        )
    finally:
        # 不关闭页面，后续 select-template / next-step 需要复用
        browser.close()


def cmd_select_template(args: argparse.Namespace) -> None:
    """选择排版模板。复用已有的长文编辑页 tab。"""
    from xhs.publish_long_article import select_template

    browser, page = _connect_existing(args)
    try:
        selected = select_template(page, args.name)
        if selected:
            _output({"success": True, "template": args.name, "status": "模板已选择"})
        else:
            _output(
                {"success": False, "error": f"未找到模板: {args.name}"},
                exit_code=2,
            )
    finally:
        # 不关闭页面，后续 next-step 需要复用
        browser.close()


def cmd_next_step(args: argparse.Namespace) -> None:
    """点击下一步 + 填写发布页描述。复用已有的长文编辑页 tab。"""
    from xhs.publish_long_article import click_next_and_fill_description

    with open(args.content_file, encoding="utf-8") as f:
        description = f.read().strip()

    browser, page = _connect_existing(args)
    try:
        click_next_and_fill_description(page, description)
        _output({"success": True, "status": "已进入发布页，等待确认发布"})
    finally:
        # 不关闭页面，等待 click-publish
        browser.close()


def cmd_publish_video(args: argparse.Namespace) -> None:
    """发布视频内容。"""
    from xhs.login import check_login_status
    from xhs.publish_video import publish_video_content
    from xhs.types import PublishVideoContent

    with open(args.title_file, encoding="utf-8") as f:
        title = f.read().strip()
    with open(args.content_file, encoding="utf-8") as f:
        content = f.read().strip()

    browser, page = _connect(args)
    try:
        # headless 模式登录检查 + 自动降级
        headless = getattr(args, "headless", False)
        if headless and not check_login_status(page):
            browser.close_page(page)
            browser.close()
            _headless_fallback(args.port)
            return

        publish_video_content(
            page,
            PublishVideoContent(
                title=title,
                content=content,
                tags=args.tags or [],
                video_path=args.video,
                schedule_time=args.schedule_at,
                visibility=args.visibility or "",
            ),
        )
        _output({"success": True, "title": title, "video": args.video, "status": "发布完成"})
    finally:
        browser.close_page(page)
        browser.close()


# ========== 账号管理子命令 ==========


def cmd_add_account(args: argparse.Namespace) -> None:
    """添加命名账号，自动分配独立端口和 Chrome Profile。"""
    import sys as _sys

    _sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    import account_manager

    account_manager.add_account(args.name, description=args.description or "")
    port = account_manager.get_account_port(args.name)
    profile = account_manager.get_profile_dir(args.name)
    _output({"success": True, "name": args.name, "port": port, "profile_dir": profile})


def cmd_list_accounts(args: argparse.Namespace) -> None:
    """列出所有命名账号。"""
    import sys as _sys

    _sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    import account_manager

    accounts = account_manager.list_accounts()
    _output({"accounts": accounts, "count": len(accounts)})


def cmd_remove_account(args: argparse.Namespace) -> None:
    """删除命名账号。"""
    import sys as _sys

    _sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    import account_manager

    account_manager.remove_account(args.name)
    _output({"success": True, "name": args.name})


def cmd_set_default_account(args: argparse.Namespace) -> None:
    """设置默认账号。"""
    import sys as _sys

    _sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    import account_manager

    account_manager.set_default_account(args.name)
    _output({"success": True, "default": args.name})


# ========== 参数解析 ==========


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="xhs-cli",
        description="小红书自动化 CLI",
    )

    # 全局选项
    parser.add_argument("--host", default="127.0.0.1", help="Chrome 调试主机 (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9222, help="Chrome 调试端口 (default: 9222)")
    parser.add_argument("--account", default="", help="账号名称")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # check-login
    sub = subparsers.add_parser("check-login", help="检查登录状态")
    sub.set_defaults(func=cmd_check_login)

    # login
    sub = subparsers.add_parser("login", help="登录（扫码，阻塞等待）")
    sub.set_defaults(func=cmd_login)

    # get-qrcode（非阻塞，截图后立即返回）
    sub = subparsers.add_parser("get-qrcode", help="获取登录二维码截图并立即返回（非阻塞）")
    sub.set_defaults(func=cmd_get_qrcode)

    # wait-login（配合 get-qrcode，阻塞等待登录完成）
    sub = subparsers.add_parser("wait-login", help="等待扫码登录完成（配合 get-qrcode 使用）")
    sub.add_argument("--timeout", type=float, default=120.0, help="等待超时秒数 (default: 120)")
    sub.set_defaults(func=cmd_wait_login)

    # phone-login（单命令交互式）
    sub = subparsers.add_parser("phone-login", help="手机号+验证码登录（交互式，适合本地终端）")
    sub.add_argument("--phone", required=True, help="手机号（不含国家码，如 13800138000）")
    sub.add_argument("--code", default="", help="短信验证码（省略则交互式输入）")
    sub.set_defaults(func=cmd_phone_login)

    # send-code（分步登录第一步）
    sub = subparsers.add_parser("send-code", help="分步登录第一步：发送手机验证码，保持页面不关闭")
    sub.add_argument("--phone", required=True, help="手机号（不含国家码）")
    sub.set_defaults(func=cmd_send_code)

    # verify-code（分步登录第二步）
    sub = subparsers.add_parser("verify-code", help="分步登录第二步：填写验证码并完成登录")
    sub.add_argument("--code", required=True, help="收到的短信验证码")
    sub.set_defaults(func=cmd_verify_code)

    # delete-cookies
    sub = subparsers.add_parser("delete-cookies", help="删除 cookies")
    sub.set_defaults(func=cmd_delete_cookies)

    # list-feeds
    sub = subparsers.add_parser("list-feeds", help="获取首页 Feed 列表")
    sub.set_defaults(func=cmd_list_feeds)

    # search-feeds
    sub = subparsers.add_parser("search-feeds", help="搜索 Feeds")
    sub.add_argument("--keyword", required=True, help="搜索关键词")
    sub.add_argument("--sort-by", help="排序: 综合|最新|最多点赞|最多评论|最多收藏")
    sub.add_argument("--note-type", help="类型: 不限|视频|图文")
    sub.add_argument("--publish-time", help="时间: 不限|一天内|一周内|半年内")
    sub.add_argument("--search-scope", help="范围: 不限|已看过|未看过|已关注")
    sub.add_argument("--location", help="位置: 不限|同城|附近")
    sub.set_defaults(func=cmd_search_feeds)

    # get-feed-detail
    sub = subparsers.add_parser("get-feed-detail", help="获取 Feed 详情")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--load-all-comments", action="store_true", help="加载全部评论")
    sub.add_argument("--click-more-replies", action="store_true", help="点击展开更多回复")
    sub.add_argument("--max-replies-threshold", type=int, default=10, help="展开回复数阈值")
    sub.add_argument("--max-comment-items", type=int, default=0, help="最大评论数 (0=不限)")
    sub.add_argument("--scroll-speed", default="normal", help="滚动速度: slow|normal|fast")
    sub.set_defaults(func=cmd_get_feed_detail)

    # user-profile
    sub = subparsers.add_parser("user-profile", help="获取用户主页")
    sub.add_argument("--user-id", required=True, help="用户 ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.set_defaults(func=cmd_user_profile)

    # post-comment
    sub = subparsers.add_parser("post-comment", help="发表评论")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--content", required=True, help="评论内容")
    sub.set_defaults(func=cmd_post_comment)

    # reply-comment
    sub = subparsers.add_parser("reply-comment", help="回复评论")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--content", required=True, help="回复内容")
    sub.add_argument("--comment-id", help="目标评论 ID")
    sub.add_argument("--user-id", help="目标用户 ID")
    sub.set_defaults(func=cmd_reply_comment)

    # like-feed
    sub = subparsers.add_parser("like-feed", help="点赞")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--unlike", action="store_true", help="取消点赞")
    sub.set_defaults(func=cmd_like_feed)

    # favorite-feed
    sub = subparsers.add_parser("favorite-feed", help="收藏")
    sub.add_argument("--feed-id", required=True, help="Feed ID")
    sub.add_argument("--xsec-token", required=True, help="xsec_token")
    sub.add_argument("--unfavorite", action="store_true", help="取消收藏")
    sub.set_defaults(func=cmd_favorite_feed)

    # publish
    sub = subparsers.add_parser("publish", help="发布图文")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--images", nargs="+", required=True, help="图片路径/URL")
    sub.add_argument("--tags", nargs="*", help="标签")
    sub.add_argument("--schedule-at", help="定时发布 (ISO8601)")
    sub.add_argument("--original", action="store_true", help="声明原创")
    sub.add_argument("--visibility", help="可见范围")
    sub.add_argument("--headless", action="store_true", help="无头模式（未登录自动降级）")
    sub.set_defaults(func=cmd_publish)

    # publish-video
    sub = subparsers.add_parser("publish-video", help="发布视频")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--video", required=True, help="视频文件路径")
    sub.add_argument("--tags", nargs="*", help="标签")
    sub.add_argument("--schedule-at", help="定时发布 (ISO8601)")
    sub.add_argument("--visibility", help="可见范围")
    sub.add_argument("--headless", action="store_true", help="无头模式（未登录自动降级）")
    sub.set_defaults(func=cmd_publish_video)

    # fill-publish（只填写图文表单，不发布）
    sub = subparsers.add_parser("fill-publish", help="填写图文表单（不发布）")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--images", nargs="+", required=True, help="图片路径/URL")
    sub.add_argument("--tags", nargs="*", help="标签")
    sub.add_argument("--schedule-at", help="定时发布 (ISO8601)")
    sub.add_argument("--original", action="store_true", help="声明原创")
    sub.add_argument("--visibility", help="可见范围")
    sub.set_defaults(func=cmd_fill_publish)

    # fill-publish-video（只填写视频表单，不发布）
    sub = subparsers.add_parser("fill-publish-video", help="填写视频表单（不发布）")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--video", required=True, help="视频文件路径")
    sub.add_argument("--tags", nargs="*", help="标签")
    sub.add_argument("--schedule-at", help="定时发布 (ISO8601)")
    sub.add_argument("--visibility", help="可见范围")
    sub.set_defaults(func=cmd_fill_publish_video)

    # click-publish（点击发布按钮）
    sub = subparsers.add_parser("click-publish", help="点击发布按钮")
    sub.set_defaults(func=cmd_click_publish)

    # long-article（长文模式）
    sub = subparsers.add_parser("long-article", help="长文模式：填写 + 一键排版")
    sub.add_argument("--title-file", required=True, help="标题文件路径")
    sub.add_argument("--content-file", required=True, help="正文文件路径")
    sub.add_argument("--images", nargs="*", help="可选图片路径")
    sub.set_defaults(func=cmd_long_article)

    # select-template（选择模板）
    sub = subparsers.add_parser("select-template", help="选择排版模板")
    sub.add_argument("--name", required=True, help="模板名称")
    sub.set_defaults(func=cmd_select_template)

    # next-step（下一步 + 填写描述）
    sub = subparsers.add_parser("next-step", help="点击下一步 + 填写描述")
    sub.add_argument("--content-file", required=True, help="描述内容文件路径")
    sub.set_defaults(func=cmd_next_step)

    # save-draft（保存草稿）
    sub = subparsers.add_parser("save-draft", help="保存为草稿（取消发布时使用）")
    sub.set_defaults(func=cmd_save_draft)

    # add-account（添加命名账号）
    sub = subparsers.add_parser("add-account", help="添加命名账号，自动分配独立端口")
    sub.add_argument("--name", required=True, help="账号名称")
    sub.add_argument("--description", default="", help="账号描述（可选）")
    sub.set_defaults(func=cmd_add_account)

    # list-accounts（列出所有账号）
    sub = subparsers.add_parser("list-accounts", help="列出所有命名账号")
    sub.set_defaults(func=cmd_list_accounts)

    # remove-account（删除账号）
    sub = subparsers.add_parser("remove-account", help="删除命名账号")
    sub.add_argument("--name", required=True, help="账号名称")
    sub.set_defaults(func=cmd_remove_account)

    # set-default-account（设置默认账号）
    sub = subparsers.add_parser("set-default-account", help="设置默认账号")
    sub.add_argument("--name", required=True, help="账号名称")
    sub.set_defaults(func=cmd_set_default_account)

    return parser


def main() -> None:
    """CLI 入口。"""
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except Exception as e:
        logger.error("执行失败: %s", e, exc_info=True)
        _output({"success": False, "error": str(e)}, exit_code=2)


if __name__ == "__main__":
    main()
