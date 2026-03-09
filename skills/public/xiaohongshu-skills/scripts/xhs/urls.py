"""小红书 URL 常量和构建函数。"""

from urllib.parse import urlencode

# 基础页面
EXPLORE_URL = "https://www.xiaohongshu.com/explore"
HOME_URL = "https://www.xiaohongshu.com"
PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"


def make_feed_detail_url(feed_id: str, xsec_token: str) -> str:
    """构建 feed 详情页 URL。"""
    return (
        f"https://www.xiaohongshu.com/explore/{feed_id}?xsec_token={xsec_token}&xsec_source=pc_feed"
    )


def make_search_url(keyword: str) -> str:
    """构建搜索结果页 URL。"""
    params = urlencode({"keyword": keyword, "source": "web_explore_feed"})
    return f"https://www.xiaohongshu.com/search_result?{params}"


def make_user_profile_url(user_id: str, xsec_token: str) -> str:
    """构建用户主页 URL。"""
    return (
        f"https://www.xiaohongshu.com/user/profile/{user_id}"
        f"?xsec_token={xsec_token}&xsec_source=pc_note"
    )
