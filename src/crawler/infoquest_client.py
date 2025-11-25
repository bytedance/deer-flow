# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Util that calls InfoQuest Crawler API.

In order to set this up, follow instructions at:
https://docs.byteplus.com/en/docs/InfoQuest/What_is_Info_Quest
"""

import logging
import os
from typing import Dict, Any

import requests

logger = logging.getLogger(__name__)

class InfoQuestClient:
    """Client for interacting with the InfoQuest web crawling API."""
    
    def __init__(self, fetch_time: int = -1, timeout: int = -1, navi_timeout: int = -1):
        logger.info(
            "\n============================================\n"
            "🚀 BytePlus InfoQuest Crawler Initialization 🚀\n"
            "============================================"
        )
        
        self.fetch_time = fetch_time
        self.timeout = timeout
        self.navi_timeout = navi_timeout
        self.api_key_set = bool(os.getenv("INFOQUEST_API_KEY"))
        
        config_details = (
            f"📋 Configuration Details:\n"
            f"├── Fetch Timeout: {fetch_time} {'(Default: No timeout)' if fetch_time == -1 else '(Custom)'}\n"
            f"├── Timeout: {timeout} {'(Default: No timeout)' if timeout == -1 else '(Custom)'}\n"
            f"├── Navigation Timeout: {navi_timeout} {'(Default: No timeout)' if navi_timeout == -1 else '(Custom)'}\n"
            f"└── API Key: {'✅ Configured' if self.api_key_set else '❌ Not set'}"
        )
        
        logger.info(config_details)
        logger.info("\n" + "*" * 70 + "\n")

    def crawl(self, url: str, return_format: str = "html") -> str:
        logger.debug("Preparing request for URL: %s", url)
        
        # Prepare headers
        headers = self._prepare_headers()
        
        # Prepare request data
        data = self._prepare_request_data(url, return_format)
        
        # Log request details
        logger.debug(
            "InfoQuest Crawler request prepared: endpoint=https://reader.infoquest.bytepluses.com, "
            "format=%s, has_api_key=%s",
            data.get("format"), self.api_key_set
        )

        logger.debug("Sending crawl request to InfoQuest API")
        response = requests.post(
            "https://reader.infoquest.bytepluses.com",
            headers=headers,
            json=data
        )

        # Validate response
        response.raise_for_status()

        # Check for empty response
        if not response.text or not response.text.strip():
            logger.error("BytePlus InfoQuest Crawler returned empty response for URL: %s", url)
            raise ValueError("InfoQuest Crawler API returned empty response")

        # Print partial response for debugging
        if logger.isEnabledFor(logging.DEBUG):
            response_sample = response.text[:200] + ("..." if len(response.text) > 200 else "")
            logger.debug(
                "Successfully received response, content length: %d bytes, first 200 chars: %s",
                len(response.text), response_sample
            )
        return response.text
    
    def _prepare_headers(self) -> Dict[str, str]:
        """Prepare request headers."""
        headers = {
            "Content-Type": "application/json",
        }
        
        # Add API key if available
        if os.getenv("INFOQUEST_API_KEY"):
            headers["Authorization"] = f"Bearer {os.getenv('INFOQUEST_API_KEY')}"
            logger.debug("API key added to request headers")
        else:
            logger.warning(
                "InfoQuest API key is not set. Provide your own key for authentication."
            )
            
        return headers
    
    def _prepare_request_data(self, url: str, return_format: str) -> Dict[str, Any]:
        """Prepare request data with formatted parameters."""
        # Normalize return_format
        if return_format and return_format.lower() == "html":
            normalized_format = "HTML"
        else:
            normalized_format = return_format
        
        data = {"url": url, "format": normalized_format}
        
        # Add timeout parameters if set to positive values
        timeout_params = {}
        if self.fetch_time > 0:
            timeout_params["fetch_time"] = self.fetch_time
        if self.timeout > 0:
            timeout_params["timeout"] = self.timeout
        if self.navi_timeout > 0:
            timeout_params["navi_timeout"] = self.navi_timeout
        
        # Log applied timeout parameters
        if timeout_params:
            logger.debug("Applying timeout parameters: %s", timeout_params)
            data.update(timeout_params)
        
        return data