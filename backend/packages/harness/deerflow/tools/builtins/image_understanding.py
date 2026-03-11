"""Advanced image understanding using multimodal LLMs with SiliconFlow support."""
 
import base64
import io
import json
import logging
import requests
from pathlib import Path
from typing import Any, Union
 
from langchain_core.messages import HumanMessage

from logging.handlers import RotatingFileHandler
import asyncio
 
# Type alias for image input
ImagePathOrImage = Union[Path, 'PIL.Image.Image']
 
def setup_image_logger():
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "image_understanding.log"
    
    handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.propagate = True  # 同时也输出到其他地方
    
    return logger

logger = setup_image_logger()
 
 
async def understand_image(
    image: ImagePathOrImage,
    context: str = "",
    detail_level: str = "high"
) -> str:
    """
    Understand an image with multimodal LLM, extracting both text and meaning.
    
    Args:
        image: Path to image file OR PIL.Image object
        context: Optional context about where this image appears
        detail_level: 'low', 'medium', or 'high' - controls detail level of analysis
    
    Returns:
        Detailed description of image in Markdown format
    """
    from PIL import Image
    
    # Handle both Path and PIL.Image
    if isinstance(image, Path):
        # From file path
        image_name = image.name
        with open(image, 'rb') as f:
            image_data = f.read()
        
        # Determine MIME type from extension
        mime_type = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.bmp': 'image/bmp',
            '.webp': 'image/webp',
            '.tiff': 'image/tiff',
            '.tif': 'image/tiff',
        }.get(image.suffix.lower(), 'image/jpeg')
    else:
        # From PIL.Image object
        image_name = "image.png"
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        image_data = img_byte_arr.getvalue()
        mime_type = 'image/png'
    
    # Encode to base64
    img_base64 = base64.b64encode(image_data).decode('utf-8')
    
    # Get vision model
    model_config = get_vision_model_config()
    result = await asyncio.to_thread(test_siliconflow_api_config)
    logger.info(f"SiliconFlow API test result: {result}")
    if not model_config:
        return "Error: No vision-capable model configured"
    
    # Build prompt
    prompt = build_analysis_prompt(detail_level, context)
    
    try:
        logger.info(f"Analyzing image: {image_name} (model: {model_config.name})")
        
        # Use direct HTTP request for SiliconFlow models
        if 'siliconflow' in model_config.base_url.lower():
            content = await call_siliconflow_vision_api(
                model_config, img_base64, mime_type, prompt
            )
        else:
            # Use LangChain for other models (GPT-4o, Claude, etc.)
            content = await call_standard_vision_model(
                model_config, img_base64, mime_type, prompt
            )
        
        logger.info(f"Image analysis complete: {len(content)} characters")
        return content
        
    except Exception as e:
        logger.error(f"Failed to understand image {image_name}: {e}")
        return f"Error analyzing image: {e}"
 
 
async def call_siliconflow_vision_api(
    model_config,
    base64_image: str,
    mime_type: str,
    prompt: str
) -> str:
    """Call SiliconFlow vision API directly using requests."""
    import asyncio
    import json
    
    # Build API URL
    base_url = model_config.base_url.rstrip('/')
    api_url = f"{base_url}/chat/completions"
    
    # ========== 确定模型名称 ==========
    model_name = None
    if hasattr(model_config, 'model'):
        model_name = model_config.model
    elif hasattr(model_config, 'name'):
        model_name = model_config.name
    
    # DeepSeek OCR 的完整名称
    if not model_name or 'DeepSeek-OCR' not in model_name:
        model_name = "deepseek-ai/DeepSeek-OCR"
        logger.warning(f"Using default model name: {model_name}")
    # =================================
    
    # ========== 构建 payload ==========
    # 使用传入的 mime_type（image/png 或 image/jpeg）
    image_url = f"data:{mime_type};base64,{base64_image}"
    
    payload = {
        "model": model_name,  # 使用正确的模型名称
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",  # 必须包含text类型
                        "text": prompt   # 使用构建的prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url
                        }  # 直接使用传入的image_url
                    }
                ]
            }
        ],
        "max_tokens": 2048,      # 必须包含max_tokens
        "stream": False
    }
    # ==============================
    
    headers = {
        "Authorization": f"Bearer {model_config.api_key}",
        "Content-Type": "application/json"
    }
    
    # ========== 调试日志 ==========
    logger.info(f"SiliconFlow API URL: {api_url}")
    logger.info(f"Model: {model_name}")
    logger.info(f"Image URL prefix: {image_url[:50]}...")
    logger.info(f"Full payload: {json.dumps(payload, indent=2, ensure_ascii=False)[:1000]}...")
    # ========================
    
    loop = asyncio.get_event_loop()
    
    def make_request():
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        
        # 添加这行：立即打印原始响应
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response body: {response.text[:1000]}")

        response.raise_for_status()
        return response.json()
    
    try:
        result = await loop.run_in_executor(None, make_request)
        
        
        if "choices" in result and result["choices"]:
            content = result["choices"][0]["message"]["content"]

            # ========== 添加日志看原始内容 ==========
            logger.info(f"Raw response from DeepSeek OCR: {content}")
            # =====================================
            
            # Clean DeepSeek OCR tags
            import re
            content = re.sub(r'<\|ref\|>(.*?)<\|/ref\|>', r'\1', content)
            
            return content
        else:
            logger.error(f"Unexpected response: {json.dumps(result, indent=2)}")
            return "Error: Unexpected API response"
            
    except requests.exceptions.HTTPError as e:
        error_details = ""
        if e.response:
            logger.error(f"HTTP Error Status: {e.response.status_code}")
            logger.error(f"HTTP Error Body: {e.response.text[:1000]}")
            
            try:
                error_json = e.response.json()
                logger.error(f"硅基流动API详细错误: {json.dumps(error_json, indent=2, ensure_ascii=False)}")
                
                # 提取所有可能的错误信息字段
                error_parts = []
                if "error" in error_json:
                    if isinstance(error_json["error"], dict):
                        error_parts.append(f"错误: {error_json['error'].get('message', str(error_json['error']))}")
                    else:
                        error_parts.append(f"错误: {error_json['error']}")
                
                if "message" in error_json:
                    error_parts.append(f"消息: {error_json['message']}")
                
                if "detail" in error_json:
                    error_parts.append(f"详情: {error_json['detail']}")
                
                error_details = " | ".join(error_parts) if error_parts else str(e)
                
            except json.JSONDecodeError:
                error_text = e.response.text[:500]
                logger.error(f"API非JSON错误响应: {error_text}")
                error_details = f"HTTP {e.response.status_code}: {error_text}"
        else:
            error_details = str(e)
        
        return f"Error analyzing image: {error_details}"
 
 
# def build_siliconflow_image_url(
#     base64_image: str,
#     mime_type: str,
#     model_name: str
# ) -> str | dict:
#     """
#     Build image_url for SiliconFlow models.
    
#     DeepSeek OCR expects plain string, others expect nested object.
#     """
#     model_name_lower = model_name.lower()
    
#     if 'deepseek' in model_name_lower and 'ocr' in model_name_lower:
#         # DeepSeek OCR: plain string format
#         return f"data:{mime_type};base64,{base64_image}"
#     else:
#         # Other SiliconFlow models: nested object
#         return {
#             "url": f"data:{mime_type};base64,{base64_image}",
#             "detail": "low"  # SiliconFlow uses 'low' for better performance
#         }
 
def build_siliconflow_image_url(
    base64_image: str,
    mime_type: str,
    model_name: str
) -> str | dict:
    """
    Build image_url for SiliconFlow models.
    
    DeepSeek OCR: 使用 image/png 或 image/jpeg
    """
    # 直接使用传入的 mime_type
    return f"data:{mime_type};base64,{base64_image}"
 
async def call_standard_vision_model(
    model_config,
    base64_image: str,
    mime_type: str,
    prompt: str
) -> str:
    """
    Call standard vision models (GPT-4o, Claude, etc.) via LangChain.
    """
    from src.models.factory import create_chat_model
    
    try:
        model = create_chat_model(name=model_config.name)
        
        # Build message
        content = [
            {
                "type": "text",
                "text": prompt
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{base64_image}",
                    "detail": "high"
                }
            }
        ]
        
        message = HumanMessage(content=content)
        response = await model.ainvoke([message])
        
        # Extract content
        if isinstance(response.content, list):
            content = '\n\n'.join(
                item.text if hasattr(item, 'text') else str(item)
                for item in response.content
            )
        else:
            content = str(response.content)
        
        return content
        
    except Exception as e:
        logger.error(f"Standard vision model failed: {e}")
        return f"Error: {e}"
 
 
def build_analysis_prompt(detail_level: str, context: str) -> str:
    """Build analysis prompt based on detail level."""
    if detail_level == "high":
        return f"""Analyze this image in detail and provide:
 
1. **Type of Image**: (photo, chart, graph, diagram, screenshot, document scan, etc.)
 
2. **Content Summary**: Brief overview of what the image shows
 
3. **Text Content**: Extract ALL visible text, word-for-word. Preserve formatting and structure as much as possible.
 
4. **Key Elements**: 
   - For charts/graphs: List axes, labels, data points, trends
   - For diagrams: Explain components and relationships
   - For documents: Describe layout, sections, formatting
   - For photos: Describe main subjects, actions, setting
 
5. **Data Extraction** (if applicable):
   - Tables: Convert to Markdown table format
   - Charts: Describe data and insights
   - Forms: List all fields and their values
 
6. **Context & Meaning**: Explain the significance of this image in the document.
 
{f"Additional Context: {context}" if context else ""}
 
Provide the response in Markdown format with proper formatting. Be thorough and precise."""
    
    elif detail_level == "medium":
        return f"""Analyze this image and provide:
 
1. **Image Type**: What kind of image is this?
 
2. **Text Content**: Extract all visible text accurately.
 
3. **Main Content**: Brief description of what the image shows.
 
4. **Key Information**: Highlight important data, insights, or elements.
 
{f"Context: {context}" if context else ""}
 
Provide in Markdown format."""
    
    else:  # low
        return f"""Describe this image in detail. Extract any text content. Provide a clear, concise description."""
 
 
async def understand_multiple_images(
    images: list[ImagePathOrImage],
    context: str = ""
) -> str:
    """
    Understand multiple images with context awareness.
    
    Args:
        images: List of image paths OR PIL.Image objects
        context: Context about where these images appear
    
    Returns:
        Combined analysis in Markdown format
    """
    analyses = []
    
    for i, img in enumerate(images, 1):
        # Get image name
        if isinstance(img, Path):
            img_name = img.name
        else:
            img_name = f"image_{i}.png"
        
        logger.info(f"Processing image {i}/{len(images)}: {img_name}")
        
        analysis = await understand_image(
            img,
            context=f"{context} (Image {i} of {len(images)})",
            detail_level="medium"
        )
        
        analyses.append(f"### Image {i}: {img_name}\n\n{analysis}")
        
        # Small delay to avoid rate limiting
        import asyncio
        await asyncio.sleep(0.5)
    
    return '\n\n---\n\n'.join(analyses)
 
 
def get_vision_model_config():
    """
    Get vision model configuration.
    
    Returns:
        ModelConfig object or None
    """
    try:
        from src.config.app_config import get_app_config
        
        config = get_app_config()
        
        # Priority order: SiliconFlow models first
        preferred_models = [
            'siliconflow-deepseek-ocr',
            'paddleocr',
            'qwen-vl',
            'gpt-4o',
            'gpt-4-turbo',
            'claude-3.5-sonnet',
            'claude-3-opus',
        ]
        
        for model_name in preferred_models:
            for model_config in config.models:
                if model_name.lower() in model_config.name.lower():
                    logger.info(f"Using vision model: {model_config.name}")
                    return model_config
        
        logger.error(
            "No vision-capable model found. "
            "Please configure: siliconflow-deepseek-ocr, PaddleOCR, GPT-4o, etc."
        )
        return None
        
    except Exception as e:
        logger.error(f"Failed to get vision model config: {e}")
        return None
 
 
def sanitize_analysis_output(content: str, max_length: int = 200000) -> str:
    """Sanitize LLM analysis output to prevent encoding and size issues."""
    if not content:
        return ""
    
    import re
    
    # Remove control characters
    content = re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F\x7F]', '', content)
    
    # Fix Unicode issues
    content = content.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
    
    # Normalize whitespace
    content = re.sub(r'\n{3,}', '\n\n', content)
    
    # Truncate if needed
    if len(content) > max_length:
        content = content[:max_length] + (
            f"\n\n[Content truncated from {len(content)} to {max_length} characters]"
        )
    
    return content.strip()

# def test_siliconflow_api_config():
#     """测试硅基流动API配置和连通性"""
#     import requests
    
#     # 获取配置
#     model_config = get_vision_model_config()
#     if not model_config:
#         return "❌ 未找到模型配置"
    
#     # 构建最小测试请求
#     test_payload = {
#         "model": "deepseek-ocr",
#         "messages": [
#             {
#                 "role": "user",
#                 "content": [
#                     {"type": "text", "text": "Hello, can you read this?"}
#                 ]
#             }
#         ],
#         "max_tokens": 100
#     }
    
#     headers = {
#         "Authorization": f"Bearer {model_config.api_key}",
#         "Content-Type": "application/json"
#     }
    
#     api_url = f"{model_config.base_url.rstrip('/')}/chat/completions"
    
#     try:
#         response = requests.post(api_url, json=test_payload, headers=headers, timeout=10)
        
#         if response.status_code == 200:
#             return "✅ API连通性测试成功"
#         else:
#             return f"❌ API测试失败: {response.status_code}\n{response.text[:200]}"
            
#     except Exception as e:
#         return f"❌ API测试异常: {e}"

def test_siliconflow_api_config():
    """测试硅基流动API配置和连通性"""
    import requests
    
    model_config = get_vision_model_config()
    if not model_config:
        return "❌ 未找到模型配置"
    
    # 测试1：纯文本请求（验证API密钥和连通性）
    test_payload = {
        "model": "deepseek-ai/DeepSeek-OCR",
        "messages": [
            {
                "role": "user",
                "content": "Hello, are you working?"
            }
        ],
        "max_tokens": 100,
        "temperature": 0.1
    }
    
    headers = {
        "Authorization": f"Bearer {model_config.api_key}",
        "Content-Type": "application/json"
    }
    
    api_url = f"{model_config.base_url.rstrip('/')}/chat/completions"
    
    try:
        response = requests.post(api_url, json=test_payload, headers=headers, timeout=10)
        print(f"Test response: {response.status_code}")
        print(f"Test body: {response.text[:500]}")
        
        if response.status_code == 200:
            return "✅ API连通性测试成功"
        else:
            return f"❌ API测试失败: {response.status_code}\n{response.text[:500]}"
    except Exception as e:
        return f"❌ API测试异常: {e}"