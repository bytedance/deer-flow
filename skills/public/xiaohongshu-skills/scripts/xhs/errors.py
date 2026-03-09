"""小红书自动化异常体系。"""


class XHSError(Exception):
    """小红书自动化基础异常。"""


class NoFeedsError(XHSError):
    """没有捕获到 feeds 数据。"""

    def __init__(self) -> None:
        super().__init__("没有捕获到 feeds 数据")


class NoFeedDetailError(XHSError):
    """没有捕获到 feed 详情数据。"""

    def __init__(self) -> None:
        super().__init__("没有捕获到 feed 详情数据")


class NotLoggedInError(XHSError):
    """未登录。"""

    def __init__(self) -> None:
        super().__init__("未登录，请先扫码登录")


class PageNotAccessibleError(XHSError):
    """页面不可访问。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"笔记不可访问: {reason}")


class UploadTimeoutError(XHSError):
    """上传超时。"""


class PublishError(XHSError):
    """发布失败。"""


class TitleTooLongError(PublishError):
    """标题超过长度限制。"""

    def __init__(self, current: str, maximum: str) -> None:
        self.current = current
        self.maximum = maximum
        super().__init__(f"当前输入长度为{current}，最大长度为{maximum}")


class ContentTooLongError(PublishError):
    """正文超过长度限制。"""

    def __init__(self, current: str, maximum: str) -> None:
        self.current = current
        self.maximum = maximum
        super().__init__(f"当前输入长度为{current}，最大长度为{maximum}")


class RateLimitError(XHSError):
    """请求频率过高，验证码获取失败。"""

    def __init__(self) -> None:
        super().__init__("请求太频繁，验证码获取失败，请重启浏览器后重试")


class CDPError(XHSError):
    """CDP 通信异常。"""


class ElementNotFoundError(XHSError):
    """页面元素未找到。"""

    def __init__(self, selector: str) -> None:
        self.selector = selector
        super().__init__(f"未找到元素: {selector}")
