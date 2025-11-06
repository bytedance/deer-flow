# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

from pydantic import BaseModel, Field
from typing import Optional


class DocumentInfo(BaseModel):
    """文档信息模型"""

    id: str = Field(..., description="文档ID")
    name: str = Field(..., description="文档名称")
    size: int = Field(..., description="文档大小（字节）")
    hash: str = Field(..., description="文档哈希值")
    path: str = Field(..., description="文档路径")
    uploaded_at: str = Field(..., description="上传时间")
    metadata: dict = Field(default_factory=dict, description="元数据")


class DocumentUploadResponse(BaseModel):
    """文档上传响应模型"""

    success: bool = Field(..., description="是否成功")
    document: Optional[DocumentInfo] = Field(None, description="文档信息")
    message: Optional[str] = Field(None, description="消息")


class DocumentListResponse(BaseModel):
    """文档列表响应模型"""

    documents: list[DocumentInfo] = Field(..., description="文档列表")
    total: int = Field(..., description="总文档数")







