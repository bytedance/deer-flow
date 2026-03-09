"""人类行为模拟参数（延迟、滚动、悬停），对应 Go feed_detail.go 中的常量。"""

import random
import time

# ========== 配置常量 ==========
DEFAULT_MAX_ATTEMPTS = 500
STAGNANT_LIMIT = 20
MIN_SCROLL_DELTA = 10
MAX_CLICK_PER_ROUND = 3
STAGNANT_CHECK_THRESHOLD = 2
LARGE_SCROLL_TRIGGER = 5
BUTTON_CLICK_INTERVAL = 3
FINAL_SPRINT_PUSH_COUNT = 15

# ========== 延迟范围（毫秒） ==========
HUMAN_DELAY = (300, 700)
REACTION_TIME = (300, 800)
HOVER_TIME = (100, 300)
READ_TIME = (500, 1200)
SHORT_READ = (600, 1200)
SCROLL_WAIT = (100, 200)
POST_SCROLL = (300, 500)


def sleep_random(min_ms: int, max_ms: int) -> None:
    """随机延迟。"""
    if max_ms <= min_ms:
        time.sleep(min_ms / 1000.0)
        return
    delay = random.randint(min_ms, max_ms) / 1000.0
    time.sleep(delay)


def navigation_delay() -> None:
    """页面导航后的随机等待，模拟人类阅读。"""
    sleep_random(1000, 2500)


def get_scroll_interval(speed: str) -> float:
    """根据速度获取滚动间隔（秒）。"""
    if speed == "slow":
        return (1200 + random.randint(0, 300)) / 1000.0
    if speed == "fast":
        return (300 + random.randint(0, 100)) / 1000.0
    # normal
    return (600 + random.randint(0, 200)) / 1000.0


def get_scroll_ratio(speed: str) -> float:
    """根据速度获取滚动比例。"""
    if speed == "slow":
        return 0.5
    if speed == "fast":
        return 0.9
    return 0.7


def calculate_scroll_delta(viewport_height: int, base_ratio: float) -> float:
    """计算滚动距离。"""
    scroll_delta = viewport_height * (base_ratio + random.random() * 0.2)
    if scroll_delta < 400:
        scroll_delta = 400.0
    return scroll_delta + random.randint(-50, 50)


# 页面不可访问关键词
INACCESSIBLE_KEYWORDS = [
    "当前笔记暂时无法浏览",
    "该内容因违规已被删除",
    "该笔记已被删除",
    "内容不存在",
    "笔记不存在",
    "已失效",
    "私密笔记",
    "仅作者可见",
    "因用户设置，你无法查看",
    "因违规无法查看",
]
