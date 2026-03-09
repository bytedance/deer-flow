"""点赞/收藏操作，对应 Go xiaohongshu/like_favorite.go。"""

from __future__ import annotations

import json
import logging
import time

from .cdp import Page
from .errors import NoFeedDetailError
from .selectors import COLLECT_BUTTON, LIKE_BUTTON
from .types import ActionResult
from .urls import make_feed_detail_url

logger = logging.getLogger(__name__)

# 从 __INITIAL_STATE__ 读取互动状态的 JS
_GET_INTERACT_STATE_JS = """
(() => {
    if (window.__INITIAL_STATE__ &&
        window.__INITIAL_STATE__.note &&
        window.__INITIAL_STATE__.note.noteDetailMap) {
        return JSON.stringify(window.__INITIAL_STATE__.note.noteDetailMap);
    }
    return "";
})()
"""


def _get_interact_state(page: Page, feed_id: str) -> tuple[bool, bool]:
    """读取笔记的点赞/收藏状态。

    Returns:
        (liked, collected)

    Raises:
        NoFeedDetailError: 无法获取状态。
    """
    result = page.evaluate(_GET_INTERACT_STATE_JS)
    if not result:
        raise NoFeedDetailError()

    note_detail_map = json.loads(result)
    detail = note_detail_map.get(feed_id)
    if not detail:
        raise NoFeedDetailError()

    interact = detail.get("note", {}).get("interactInfo", {})
    return interact.get("liked", False), interact.get("collected", False)


def _prepare_page(page: Page, feed_id: str, xsec_token: str) -> None:
    """导航到 feed 详情页。"""
    url = make_feed_detail_url(feed_id, xsec_token)
    page.navigate(url)
    page.wait_for_load()
    page.wait_dom_stable()
    time.sleep(1)


# ========== 点赞 ==========


def like_feed(page: Page, feed_id: str, xsec_token: str) -> ActionResult:
    """点赞笔记（幂等：已点赞则跳过）。"""
    _prepare_page(page, feed_id, xsec_token)
    return _toggle_like(page, feed_id, target_liked=True)


def unlike_feed(page: Page, feed_id: str, xsec_token: str) -> ActionResult:
    """取消点赞（幂等：未点赞则跳过）。"""
    _prepare_page(page, feed_id, xsec_token)
    return _toggle_like(page, feed_id, target_liked=False)


def _toggle_like(page: Page, feed_id: str, target_liked: bool) -> ActionResult:
    """执行点赞/取消点赞操作。"""
    action_name = "点赞" if target_liked else "取消点赞"

    try:
        liked, _ = _get_interact_state(page, feed_id)
    except NoFeedDetailError:
        logger.warning("无法读取互动状态，直接点击")
        liked = not target_liked  # 强制执行点击

    # 幂等检查
    if liked == target_liked:
        logger.info("feed %s 已%s，跳过", feed_id, action_name)
        return ActionResult(feed_id=feed_id, success=True, message=f"已{action_name}")

    # 点击
    page.click_element(LIKE_BUTTON)
    time.sleep(3)

    # 验证
    try:
        liked, _ = _get_interact_state(page, feed_id)
        if liked == target_liked:
            logger.info("feed %s %s成功", feed_id, action_name)
            return ActionResult(feed_id=feed_id, success=True, message=f"{action_name}成功")
    except NoFeedDetailError:
        pass

    # 重试一次
    logger.warning("feed %s %s可能未成功，重试", feed_id, action_name)
    page.click_element(LIKE_BUTTON)
    time.sleep(2)

    return ActionResult(feed_id=feed_id, success=True, message=f"{action_name}已执行")


# ========== 收藏 ==========


def favorite_feed(page: Page, feed_id: str, xsec_token: str) -> ActionResult:
    """收藏笔记（幂等：已收藏则跳过）。"""
    _prepare_page(page, feed_id, xsec_token)
    return _toggle_favorite(page, feed_id, target_collected=True)


def unfavorite_feed(page: Page, feed_id: str, xsec_token: str) -> ActionResult:
    """取消收藏（幂等：未收藏则跳过）。"""
    _prepare_page(page, feed_id, xsec_token)
    return _toggle_favorite(page, feed_id, target_collected=False)


def _toggle_favorite(page: Page, feed_id: str, target_collected: bool) -> ActionResult:
    """执行收藏/取消收藏操作。"""
    action_name = "收藏" if target_collected else "取消收藏"

    try:
        _, collected = _get_interact_state(page, feed_id)
    except NoFeedDetailError:
        logger.warning("无法读取互动状态，直接点击")
        collected = not target_collected

    # 幂等检查
    if collected == target_collected:
        logger.info("feed %s 已%s，跳过", feed_id, action_name)
        return ActionResult(feed_id=feed_id, success=True, message=f"已{action_name}")

    # 点击
    page.click_element(COLLECT_BUTTON)
    time.sleep(3)

    # 验证
    try:
        _, collected = _get_interact_state(page, feed_id)
        if collected == target_collected:
            logger.info("feed %s %s成功", feed_id, action_name)
            return ActionResult(feed_id=feed_id, success=True, message=f"{action_name}成功")
    except NoFeedDetailError:
        pass

    # 重试
    logger.warning("feed %s %s可能未成功，重试", feed_id, action_name)
    page.click_element(COLLECT_BUTTON)
    time.sleep(2)

    return ActionResult(feed_id=feed_id, success=True, message=f"{action_name}已执行")
