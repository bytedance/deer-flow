# ── imports ─────────────────────────────────────────────────────────────
import base64, os, google.generativeai as genai
from langchain_core.tools import BaseTool, ToolException

_MODEL_ID = "models/gemini-2.0-flash-preview-image-generation"
_MODEL    = genai.GenerativeModel(_MODEL_ID)

class GoogleImageTool(BaseTool):
    name: str = "google_image_tool"
    description: str = (
        "Generate an image from a text prompt using the Gemini image-generation model. "
        "Return the image as a base-64-encoded PNG string."
    )

    def _run(self, prompt: str) -> str:
        try:
            resp = _MODEL.generate_content(
                prompt,
                generation_config = genai.GenerationConfig(
                    response_mime_type = "image/png"     
                )
            )
            img_part = resp.parts[0]
            return img_part.inline_data.data  # base-64 bytes
        except Exception as e:
            raise ToolException(f"Image generation failed: {e}") from e


google_image_tool = GoogleImageTool()




