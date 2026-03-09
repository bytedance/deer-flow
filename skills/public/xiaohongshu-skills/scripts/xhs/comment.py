"""评论操作，对应 Go xiaohongshu/comment_feed.go。"""

from __future__ import annotations

import logging

from .cdp import Page
from .feed_detail import _check_end_container, _check_page_accessible, _get_comment_count
from .human import sleep_random
from .selectors import (
    COMMENT_INPUT_FIELD,
    COMMENT_INPUT_TRIGGER,
    COMMENT_SUBMIT_BUTTON,
    PARENT_COMMENT,
    REPLY_BUTTON,
)
from .urls import make_feed_detail_url

logger = logging.getLogger(__name__)


def post_comment(page: Page, feed_id: str, xsec_token: str, content: str) -> None:
    """发表评论到 Feed。

    Args:
        page: CDP 页面对象。
        feed_id: Feed ID。
        xsec_token: xsec_token。
        content: 评论内容。

    Raises:
        RuntimeError: 评论失败。
    """
    url = make_feed_detail_url(feed_id, xsec_token)
    logger.info("打开 feed 详情页: %s", url)

    page.navigate(url)
    page.wait_for_load()
    page.wait_dom_stable()
    sleep_random(800, 1500)

    _check_page_accessible(page)

    # 点击评论输入触发区域
    if not page.has_element(COMMENT_INPUT_TRIGGER):
        raise RuntimeError("未找到评论输入框，该帖子可能不支持评论或网页端不可访问")

    page.click_element(COMMENT_INPUT_TRIGGER)
    sleep_random(400, 800)

    # 输入评论内容（CDP 逐字输入）
    page.wait_for_element(COMMENT_INPUT_FIELD, timeout=5)
    page.input_content_editable(COMMENT_INPUT_FIELD, content)
    sleep_random(600, 1200)

    # 点击提交
    page.click_element(COMMENT_SUBMIT_BUTTON)
    sleep_random(800, 1500)

    logger.info("评论发送成功: feed=%s", feed_id)


def reply_comment(
    page: Page,
    feed_id: str,
    xsec_token: str,
    content: str,
    comment_id: str = "",
    user_id: str = "",
) -> None:
    """回复指定评论。

    通过 comment_id 或 user_id 定位评论，然后回复。

    Args:
        page: CDP 页面对象。
        feed_id: Feed ID。
        xsec_token: xsec_token。
        content: 回复内容。
        comment_id: 评论 ID（优先使用）。
        user_id: 用户 ID（备选）。

    Raises:
        RuntimeError: 回复失败。
    """
    if not comment_id and not user_id:
        raise ValueError("comment_id 和 user_id 至少提供一个")

    url = make_feed_detail_url(feed_id, xsec_token)
    logger.info("打开 feed 详情页进行回复: %s", url)

    page.navigate(url)
    page.wait_for_load()
    page.wait_dom_stable()
    sleep_random(800, 1500)

    _check_page_accessible(page)
    sleep_random(1500, 2500)

    # 查找目标评论
    comment_found = _find_and_scroll_to_comment(page, comment_id, user_id)
    if not comment_found:
        raise RuntimeError(f"未找到评论 (commentID: {comment_id}, userID: {user_id})")

    sleep_random(800, 1500)

    # 点击回复按钮
    reply_selector = f"#comment-{comment_id} {REPLY_BUTTON}" if comment_id else REPLY_BUTTON
    page.click_element(reply_selector)
    sleep_random(800, 1500)

    # 输入回复内容（CDP 逐字输入）
    page.wait_for_element(COMMENT_INPUT_FIELD, timeout=5)
    page.input_content_editable(COMMENT_INPUT_FIELD, content)
    sleep_random(600, 1200)

    # 点击提交
    page.click_element(COMMENT_SUBMIT_BUTTON)
    sleep_random(1500, 2500)

    logger.info("回复评论成功")


def _find_and_scroll_to_comment(
    page: Page,
    comment_id: str,
    user_id: str,
    max_attempts: int = 100,
) -> bool:
    """查找并滚动到目标评论。"""
    logger.info("开始查找评论 - commentID: %s, userID: %s", comment_id, user_id)

    # 先滚动到评论区
    page.scroll_element_into_view(".comments-container")
    sleep_random(800, 1500)

    last_count = 0
    stagnant = 0

    for attempt in range(max_attempts):
        # 检查是否到底
        if _check_end_container(page):
            logger.info("已到达评论底部，未找到目标评论")
            break

        # 停滞检测
        current_count = _get_comment_count(page)
        if current_count != last_count:
            last_count = current_count
            stagnant = 0
        else:
            stagnant += 1
        if stagnant >= 10:
            logger.info("评论数量停滞超过10次")
            break

        # 滚动到最后一条评论
        if current_count > 0:
            page.scroll_nth_element_into_view(PARENT_COMMENT, current_count - 1)
            sleep_random(200, 500)

        # 继续滚动
        page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
        sleep_random(400, 800)

        # 通过 commentID 查找
        if comment_id:
            selector = f"#comment-{comment_id}"
            if page.has_element(selector):
                logger.info("通过 commentID 找到评论 (尝试 %d 次)", attempt + 1)
                page.scroll_element_into_view(selector)
                return True

        # 通过 userID 查找
        if user_id:
            found = page.evaluate(
                f"""
                (() => {{
                    const els = document.querySelectorAll(
                        '.parent-comment, .comment-item, .comment'
                    );
                    for (const el of els) {{
                        if (el.querySelector('[data-user-id="{user_id}"]')) {{
                            el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
                            return true;
                        }}
                    }}
                    return false;
                }})()
                """
            )
            if found:
                logger.info("通过 userID 找到评论 (尝试 %d 次)", attempt + 1)
                return True

        sleep_random(600, 1200)

    return False


def _js_str(s: str) -> str:
    """将 Python 字符串转为 JS 字面量（含引号）。"""
    import json

    return json.dumps(s)
