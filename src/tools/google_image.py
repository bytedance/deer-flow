import os
from langchain_core.tools import BaseTool, ToolException
from google import genai
import base64
from google.genai import types

class GoogleImageTool(BaseTool):
    name: str = "google_image"
    description: str = (
        "Generate an image with Imagen-3.\n"
        "Input: prompt string → Output: base-64 PNG string."
    )

    def _run(self, prompt: str) -> str:
        try:
            client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))   
            resp = client.models.generate_images(
                model="models/imagen-3.0-generate-002",
                prompt=prompt,
                config={"number_of_images": 1, "output_mime_type": "image/png"},
            )

            img_bytes = resp.generated_images[0].image.image_bytes
            return base64.b64encode(img_bytes).decode()
        except Exception as e:
            raise ToolException(f"Image generation failed: {e}") from e

google_image_tool = GoogleImageTool()
