from __future__ import annotations

import base64
import os
from typing import Union
from google import genai
from google.genai import types
from langchain_core.tools import BaseTool, ToolException

_TTS_MODEL = "models/gemini-2.5-flash-preview-tts"


class GoogleSpeechTool(BaseTool):
    name: str = "generate_speech"
    description: str = (
        "Generate speech (mp3/wav) from text using Google Gemini TTS preview.\n"
        "Input can be str or {'text': str, 'voice': str}.\n"
        "Returns base-64 encoded audio bytes (PCM)."
    )

    def _run(self, text: str, voice: str = "Kore") -> str:
        try:
            client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
            resp = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=text,
                config={
                    "response_modalities": ["AUDIO"],
                    "speech_config": {
                        "voice_config": {
                            "prebuilt_voice_config": {"voice_name": voice}
                        }
                    },
                },
            )
            audio_bytes = resp.candidates[0].content.parts[0].inline_data.data
            return base64.b64encode(audio_bytes).decode("utf-8")
        except Exception as e:
            raise ToolException(f"TTS generation failed: {e}") from e




google_speech_tool = GoogleSpeechTool()
