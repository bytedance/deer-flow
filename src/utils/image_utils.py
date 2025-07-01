    
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import base64
import io
from PIL import Image

def create_message_with_base64_image(text: str, image_paths: str) -> HumanMessage:
    """使用base64编码传递图像, 都转为jpg再转为base64传输"""
    
    # image_paths: path1,path2,path3
    image_paths_list = image_paths.split(",")
    base64_image_list = []
    
    for image_path in image_paths_list:

        with Image.open(image_path) as img:
            # 转换为RGB模式（去除透明通道）
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # 保存为JPEG格式到内存
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)
            
            # 编码为base64
            base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
            base64_image_list.append(base64_image)

    
    image_messages = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{i}"
            }
        }
        for i in base64_image_list
    ]
    
    # 创建多模态content
    content = [
        {
            "type": "text",
            "text": text
        }
    ]
    content.extend(image_messages)
    
    return HumanMessage(content=content)
