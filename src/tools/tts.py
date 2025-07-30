# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Text-to-Speech module using volcengine TTS API.
"""

import json
import logging
import uuid
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)


class VolcengineTTS:
    """
    Client for volcengine Text-to-Speech API.
    """

    def __init__(
        self,
        appid: str,
        access_token: str,
        cluster: str = "volcano_tts",
        voice_type: str = "BV700_V2_streaming",
        host: str = "openspeech.bytedance.com",
    ):
        """
        Initialize the volcengine TTS client.

        Args:
            appid: Platform application ID
            access_token: Access token for authentication
            cluster: TTS cluster name
            voice_type: Voice type to use
            host: API host
        """
        self.appid = appid
        self.access_token = access_token
        self.cluster = cluster
        self.voice_type = voice_type
        self.host = host
        self.api_url = f"https://{host}/api/v1/tts"
        self.header = {"Authorization": f"Bearer;{access_token}"}

    def text_to_speech(
        self,
        text: str,
        encoding: str = "mp3",
        speed_ratio: float = 1.0,
        volume_ratio: float = 1.0,
        pitch_ratio: float = 1.0,
        text_type: str = "plain",
        with_frontend: int = 1,
        frontend_type: str = "unitTson",
        uid: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert text to speech using volcengine TTS API.

        Args:
            text: Text to convert to speech
            encoding: Audio encoding format
            speed_ratio: Speech speed ratio
            volume_ratio: Speech volume ratio
            pitch_ratio: Speech pitch ratio
            text_type: Text type (plain or ssml)
            with_frontend: Whether to use frontend processing
            frontend_type: Frontend type
            uid: User ID (generated if not provided)

        Returns:
            Dictionary containing the API response and base64-encoded audio data
        """
        if not uid:
            uid = str(uuid.uuid4())

        request_json = {
            "app": {
                "appid": self.appid,
                "token": self.access_token,
                "cluster": self.cluster,
            },
            "user": {"uid": uid},
            "audio": {
                "voice_type": self.voice_type,
                "encoding": encoding,
                "speed_ratio": speed_ratio,
                "volume_ratio": volume_ratio,
                "pitch_ratio": pitch_ratio,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": text_type,
                "operation": "query",
                "with_frontend": with_frontend,
                "frontend_type": frontend_type,
            },
        }

        try:
            sanitized_text = text.replace("\r\n", "").replace("\n", "")
            logger.debug(f"Sending TTS request for text: {sanitized_text[:50]}...")
            response = requests.post(
                self.api_url, json.dumps(request_json), headers=self.header
            )
            response_json = response.json()

            if response.status_code != 200:
                logger.error(f"TTS API error: {response_json}")
                return {"success": False, "error": response_json, "audio_data": None}

            if "data" not in response_json:
                logger.error(f"TTS API returned no data: {response_json}")
                return {
                    "success": False,
                    "error": "No audio data returned",
                    "audio_data": None,
                }

            return {
                "success": True,
                "response": response_json,
                "audio_data": response_json["data"],  # Base64 encoded audio data
            }

        except Exception as e:
            logger.exception(f"Error in TTS API call: {str(e)}")
            return {"success": False, "error": "TTS API call error", "audio_data": None}
