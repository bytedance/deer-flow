"""媒体下载（SHA256 缓存），对应 Go pkg/downloader/images.go。"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 已知图片扩展名
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}


def is_image_url(path: str) -> bool:
    """判断字符串是否为图片/媒体 URL。"""
    return path.lower().startswith(("http://", "https://"))


class ImageDownloader:
    """图片下载器（带 SHA256 缓存）。"""

    def __init__(self, save_path: str) -> None:
        self.save_path = save_path
        os.makedirs(save_path, exist_ok=True)
        self._session = requests.Session()
        self._session.timeout = 30

    def download_image(self, image_url: str) -> str:
        """下载单张图片，返回本地文件路径。

        如果文件已存在（通过 URL hash 判断），直接返回路径。

        Raises:
            ValueError: URL 格式无效。
            RuntimeError: 下载失败。
        """
        if not is_image_url(image_url):
            raise ValueError(f"无效的图片 URL: {image_url}")

        # 生成文件名
        url_hash = hashlib.sha256(image_url.encode()).hexdigest()[:16]
        ext = self._detect_extension(image_url)
        filename = f"img_{url_hash}_{int(time.time())}{ext}"
        filepath = os.path.join(self.save_path, filename)

        # 检查是否已有同 hash 的文件
        existing = self._find_existing(url_hash)
        if existing:
            return existing

        # 下载
        parsed = urlparse(image_url)
        headers = {
            "User-Agent": _USER_AGENT,
            "Referer": f"{parsed.scheme}://{parsed.hostname}/",
        }

        resp = self._session.get(image_url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"下载失败 (status={resp.status_code}): {image_url}")

        # 保存
        with open(filepath, "wb") as f:
            f.write(resp.content)

        logger.info("下载完成: %s -> %s", image_url, filepath)
        return filepath

    def download_images(self, image_urls: list[str]) -> list[str]:
        """批量下载图片。"""
        paths = []
        for url in image_urls:
            try:
                path = self.download_image(url)
                paths.append(path)
            except Exception as e:
                logger.error("下载失败 %s: %s", url, e)
        return paths

    def _detect_extension(self, url: str) -> str:
        """从 URL 推断文件扩展名。"""
        parsed = urlparse(url)
        path = parsed.path.lower()
        for ext in _IMAGE_EXTENSIONS:
            if path.endswith(ext):
                return ext
        return ".jpg"  # 默认

    def _find_existing(self, url_hash: str) -> str | None:
        """查找已有同 hash 的文件。"""
        prefix = f"img_{url_hash}_"
        for filename in os.listdir(self.save_path):
            if filename.startswith(prefix):
                return os.path.join(self.save_path, filename)
        return None


def process_images(images: list[str], save_dir: str | None = None) -> list[str]:
    """处理图片列表（URL 下载，本地路径直接返回）。"""
    if not save_dir:
        save_dir = os.path.join(os.path.expanduser("~"), ".xhs", "images")

    downloader = ImageDownloader(save_dir)
    result = []

    for img in images:
        if is_image_url(img):
            path = downloader.download_image(img)
            result.append(path)
        else:
            # 本地路径
            if os.path.exists(img):
                result.append(os.path.abspath(img))
            else:
                logger.warning("文件不存在: %s", img)

    return result
