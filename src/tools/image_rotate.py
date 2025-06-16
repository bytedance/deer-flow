from PIL import Image

def parse_rotation(rotate_request):
   """
   解析旋转请求，返回PIL旋转角度和描述
   
   Args:
       rotate_request (str): 旋转请求字符串
       
   Returns:
       tuple: (pil_rotation_angle, description)
   """
   import re
   
   # 清理输入
   text = str(rotate_request).lower().strip()
   
   # 提取数字
   angle_match = re.search(r'(-?\d+)', text)
   angle = int(angle_match.group(1)) if angle_match else None
   
   # 判断方向
   is_counter = any(word in text for word in ['逆时针', '反时针', '左转', 'counter', 'left'])
   is_clock = any(word in text for word in ['顺时针', '右转', 'clock', 'right'])
   
   # 处理特殊角度
   if '180' in text or '半圈' in text:
       return (180, "旋转180度")
   
   if angle == 180:
       return (180, "旋转180度")
   
   # 处理90度（最常见情况）
   if angle == 90 or '90' in text or '九十' in text or not angle:
       if is_counter or angle == -90:
           return (90, "逆时针旋转90度")  # PIL中正数是逆时针
       else:
           return (-90, "顺时针旋转90度")  # PIL中负数是顺时针
   
   # 处理其他角度
   if angle:
       pil_angle = angle if is_counter else -angle
       direction = "逆时针" if is_counter else "顺时针"
       return (pil_angle, f"{direction}旋转{abs(angle)}度")
   
   # 默认情况
   raise ValueError(f"无法识别旋转请求: '{rotate_request}'")


# 使用示例
def rotate_image(img_path, new_file_path, rotate_request):
    """旋转图片"""
    try:
        pil_angle, description = parse_rotation(rotate_request)

        img = Image.open(img_path)
        # 旋转图片
        rotated_img = img.rotate(pil_angle, expand=True)
        rotated_img.save(new_file_path, quality=95)
        return description
    except ValueError as e: 
        raise e