import base64
import hashlib
import urllib.parse

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def sign_request(params: dict, app_id: str) -> str:
    """领星 API 签名：MD5(排序参数)→大写 → AES/ECB/PKCS5(key=appId 补齐16字节) → Base64 → URL 编码。"""
    # 步骤2: 添加固定参数由调用方负责（access_token/app_key/timestamp 已在 params 里）
    # 步骤2.5: 移除 sign + api_code
    sign_params = {k: v for k, v in params.items() if k not in ("sign", "api_code")}
    # 步骤3: 参数排序
    sorted_keys = sorted(sign_params.keys())
    # 步骤4: 拼接参数字符串
    param_str = "&".join(f"{k}={sign_params[k]}" for k in sorted_keys)
    # 步骤5: MD5 转大写
    md5_hash = hashlib.md5(param_str.encode("utf-8")).hexdigest().upper()
    # 步骤6: AES/ECB/PKCS5Padding 加密 (key=appId 补齐到 16 字节)
    key_bytes = app_id.encode("utf-8")
    key_padded = key_bytes.ljust(16, b"\x00")  # 补齐到 16 字节
    cipher = AES.new(key_padded, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(md5_hash.encode("utf-8"), AES.block_size))
    sign_value = base64.b64encode(encrypted).decode("utf-8")
    # 步骤7: URL 编码
    return urllib.parse.quote(sign_value, safe="")
