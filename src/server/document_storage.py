# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# 文档存储目录
DOCUMENTS_DIR = Path(os.getenv("DOCUMENTS_DIR", "documents"))
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)


class DocumentStorage:
    """通用文档存储管理器"""

    def __init__(self, base_dir: Path = DOCUMENTS_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_document(
        self, file_content: bytes, file_name: str, metadata: Optional[dict] = None
    ) -> dict:
        """
        保存文档到本地存储

        Args:
            file_content: 文件内容（字节）
            file_name: 文件名
            metadata: 可选的元数据

        Returns:
            包含文档信息的字典
        """
        # 生成唯一ID
        doc_id = str(uuid4())
        
        # 计算文件哈希
        file_hash = hashlib.sha256(file_content).hexdigest()
        
        # 创建文档目录
        doc_dir = self.base_dir / doc_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存文件
        file_path = doc_dir / file_name
        file_path.write_bytes(file_content)
        
        # 保存元数据
        doc_info = {
            "id": doc_id,
            "name": file_name,
            "size": len(file_content),
            "hash": file_hash,
            "path": str(file_path),
            "uploaded_at": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        
        # 保存文档信息到JSON文件
        import json
        info_path = doc_dir / "info.json"
        info_path.write_text(json.dumps(doc_info, ensure_ascii=False, indent=2))
        
        logger.info(f"Document saved: {file_name} (ID: {doc_id})")
        return doc_info

    def get_document(self, doc_id: str) -> Optional[dict]:
        """
        获取文档信息

        Args:
            doc_id: 文档ID

        Returns:
            文档信息字典，如果不存在则返回None
        """
        doc_dir = self.base_dir / doc_id
        info_path = doc_dir / "info.json"
        
        if not info_path.exists():
            return None
        
        import json
        return json.loads(info_path.read_text(encoding="utf-8"))

    def get_document_content(self, doc_id: str) -> Optional[bytes]:
        """
        获取文档内容

        Args:
            doc_id: 文档ID

        Returns:
            文档内容（字节），如果不存在则返回None
        """
        doc_info = self.get_document(doc_id)
        if not doc_info:
            return None
        
        file_path = Path(doc_info["path"])
        if not file_path.exists():
            return None
        
        return file_path.read_bytes()

    def list_documents(self, limit: int = 100, offset: int = 0) -> list[dict]:
        """
        列出所有文档

        Args:
            limit: 返回的最大文档数
            offset: 偏移量

        Returns:
            文档信息列表
        """
        documents = []
        
        for doc_dir in self.base_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            
            info_path = doc_dir / "info.json"
            if not info_path.exists():
                continue
            
            try:
                import json
                doc_info = json.loads(info_path.read_text(encoding="utf-8"))
                documents.append(doc_info)
            except Exception as e:
                logger.warning(f"Error reading document info from {doc_dir}: {e}")
                continue
        
        # 按上传时间倒序排序
        documents.sort(key=lambda x: x.get("uploaded_at", ""), reverse=True)
        
        return documents[offset : offset + limit]

    def delete_document(self, doc_id: str) -> bool:
        """
        删除文档

        Args:
            doc_id: 文档ID

        Returns:
            是否成功删除
        """
        doc_dir = self.base_dir / doc_id
        if not doc_dir.exists():
            return False
        
        try:
            import shutil
            shutil.rmtree(doc_dir)
            logger.info(f"Document deleted: {doc_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting document {doc_id}: {e}")
            return False


# 全局文档存储实例
document_storage = DocumentStorage()



