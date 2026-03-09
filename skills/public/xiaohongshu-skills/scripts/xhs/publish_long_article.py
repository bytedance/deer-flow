"""长文发布模式，参考 cdp_publish.py 的长文工作流。"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .cdp import Page
from .errors import PublishError
from .publish import _click_publish_tab, _find_content_element, _navigate_to_publish_page
from .selectors import (
    AUTO_FORMAT_BUTTON_TEXT,
    CONTENT_EDITOR,
    LONG_ARTICLE_TITLE,
    NEW_CREATION_BUTTON_TEXT,
    NEXT_STEP_BUTTON_TEXT,
    TEMPLATE_CARD,
    TEMPLATE_TITLE,
)

logger = logging.getLogger(__name__)

# 等待常量
_AUTO_FORMAT_WAIT = 3.0
_TEMPLATE_WAIT_ROUNDS = 15
_PAGE_LOAD_WAIT = 3.0


def publish_long_article(
    page: Page,
    title: str,
    content: str,
    image_paths: list[str] | None = None,
) -> list[str]:
    """长文发布：导航 → 点击写长文 → 新的创作 → 填写标题正文 → 一键排版。

    返回可用模板名称列表。

    Args:
        page: CDP 页面对象。
        title: 长文标题。
        content: 长文正文（段落用换行分隔）。
        image_paths: 可选的图片路径列表（插入编辑器）。

    Returns:
        可用模板名称列表。

    Raises:
        PublishError: 操作失败。
    """
    # 1. 导航到发布页
    _navigate_to_publish_page(page)

    # 2. 点击"写长文"TAB
    _click_publish_tab(page, "写长文")
    time.sleep(1)

    # 3. 点击"新的创作"
    _click_new_creation(page)

    # 4. 填写标题（textarea）
    _fill_long_title(page, title)

    # 5. 填写正文（TipTap 编辑器）
    _fill_long_content(page, content)

    # 6. 可选：插入图片到编辑器
    if image_paths:
        _insert_images_to_editor(page, image_paths)

    # 7. 点击"一键排版"
    _click_auto_format(page)

    # 8. 等待模板加载并返回名称列表
    _wait_for_templates(page)
    template_names = get_template_names(page)
    logger.info("模板加载完成: %s", template_names)
    return template_names


def get_template_names(page: Page) -> list[str]:
    """获取当前可用的排版模板名称列表。

    Args:
        page: CDP 页面对象。

    Returns:
        模板名称列表。
    """
    names = page.evaluate(
        f"""
        (() => {{
            const cards = document.querySelectorAll({json.dumps(TEMPLATE_CARD)});
            const names = [];
            for (const card of cards) {{
                const title = card.querySelector({json.dumps(TEMPLATE_TITLE)});
                names.push(title ? title.textContent.trim() : 'Template ' + names.length);
            }}
            return names;
        }})()
        """
    )
    return names or []


def select_template(page: Page, template_name: str) -> bool:
    """选择指定名称的排版模板。

    Args:
        page: CDP 页面对象。
        template_name: 模板名称。

    Returns:
        是否成功选择。
    """
    clicked = page.evaluate(
        f"""
        (() => {{
            const cards = document.querySelectorAll({json.dumps(TEMPLATE_CARD)});
            for (const card of cards) {{
                const title = card.querySelector({json.dumps(TEMPLATE_TITLE)});
                if (title && title.textContent.trim() === {json.dumps(template_name)}) {{
                    card.click();
                    return true;
                }}
            }}
            return false;
        }})()
        """
    )

    if clicked:
        logger.info("已选择模板: %s", template_name)
        time.sleep(1)
    else:
        logger.warning("未找到模板: %s", template_name)

    return bool(clicked)


def click_next_and_fill_description(page: Page, description: str) -> None:
    """点击下一步，进入发布页并填写正文描述。

    注意：发布页有独立的正文编辑器，需单独填入。
    如果 description 超过 1000 字，应压缩到 800 字左右。

    Args:
        page: CDP 页面对象。
        description: 发布页正文描述。

    Raises:
        PublishError: 操作失败。
    """
    # 点击"下一步"
    _click_button_by_text(page, NEXT_STEP_BUTTON_TEXT)
    time.sleep(_PAGE_LOAD_WAIT)

    # 填写发布页描述
    if description:
        # 截断描述到 1000 字以内
        if len(description) > 1000:
            description = description[:800]
            logger.warning("描述超过1000字，已截断到800字")

        content_selector = _find_content_element(page)
        page.input_content_editable(content_selector, description)
        logger.info("已填写发布页描述")


# ========== 内部辅助函数 ==========


def _click_new_creation(page: Page) -> None:
    """点击"新的创作"按钮。"""
    _click_button_by_text(page, NEW_CREATION_BUTTON_TEXT)
    time.sleep(2)
    page.wait_dom_stable()
    logger.info("已点击'新的创作'")


def _fill_long_title(page: Page, title: str) -> None:
    """填写长文标题（textarea，需使用 native setter）。"""
    page.wait_for_element(LONG_ARTICLE_TITLE, timeout=10)

    page.evaluate(
        f"""
        (() => {{
            const el = document.querySelector({json.dumps(LONG_ARTICLE_TITLE)});
            if (!el) return false;
            const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLTextAreaElement.prototype, 'value'
            ).set;
            el.focus();
            nativeSetter.call(el, {json.dumps(title)});
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return true;
        }})()
        """
    )
    logger.info("已填写长文标题: %s", title[:20])
    time.sleep(0.5)


def _fill_long_content(page: Page, content: str) -> None:
    """填写长文正文（TipTap/ProseMirror 编辑器）。"""
    content_selector = CONTENT_EDITOR
    if not page.has_element(CONTENT_EDITOR):
        content_selector = _find_content_element(page)

    page.input_content_editable(content_selector, content)
    logger.info("已填写长文正文 (%d 字)", len(content))
    time.sleep(1)


def _insert_images_to_editor(page: Page, image_paths: list[str]) -> None:
    """将图片插入到编辑器中。"""
    for img_path in image_paths:
        file_uri = Path(img_path).resolve().as_uri()
        page.evaluate(
            f"""
            (() => {{
                const editor = document.querySelector({json.dumps(CONTENT_EDITOR)});
                if (!editor) return false;
                const img = document.createElement('img');
                img.src = {json.dumps(file_uri)};
                editor.appendChild(img);
                editor.dispatchEvent(new Event('input', {{ bubbles: true }}));
                return true;
            }})()
            """
        )
    logger.info("已插入 %d 张图片到编辑器", len(image_paths))
    time.sleep(1)


def _click_auto_format(page: Page) -> None:
    """点击"一键排版"按钮。"""
    _click_button_by_text(page, AUTO_FORMAT_BUTTON_TEXT)
    logger.info("已点击'一键排版'，等待模板加载...")
    time.sleep(_AUTO_FORMAT_WAIT)


def _wait_for_templates(page: Page) -> bool:
    """等待模板卡片出现。"""
    for _ in range(_TEMPLATE_WAIT_ROUNDS):
        count = page.get_elements_count(TEMPLATE_CARD)
        if count and count > 0:
            logger.info("发现 %d 个模板卡片", count)
            return True
        time.sleep(1)

    logger.warning("等待模板卡片超时")
    return False


def _click_button_by_text(page: Page, text: str) -> None:
    """通过文本内容查找并点击按钮（通用方法）。"""
    clicked = page.evaluate(
        f"""
        (() => {{
            const elems = document.querySelectorAll(
                'button, [role="button"], span, div, a, [class*="btn"]'
            );
            for (const el of elems) {{
                if (el.textContent.trim() === {json.dumps(text)}) {{
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;
                    el.click();
                    return true;
                }}
            }}
            return false;
        }})()
        """
    )

    if not clicked:
        raise PublishError(f"未找到'{text}'按钮，页面结构可能已变化")
