# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def extract_text_from_document(file_path: Path, content_type: Optional[str] = None) -> str:
    """
    从文档中提取文本内容
    
    Args:
        file_path: 文档文件路径
        content_type: 文档的MIME类型
        
    Returns:
        提取的文本内容
    """
    file_extension = file_path.suffix.lower()
    
    try:
        # PDF文件
        if file_extension == ".pdf" or (content_type and "pdf" in content_type.lower()):
            return _extract_from_pdf(file_path)
        
        # Word文档
        elif file_extension in [".docx", ".doc"] or (content_type and "word" in content_type.lower()):
            return _extract_from_docx(file_path)
        
        # Excel文件
        elif file_extension in [".xlsx", ".xls"] or (content_type and "excel" in content_type.lower() or "spreadsheet" in content_type.lower()):
            return _extract_from_excel(file_path)
        
        # 文本文件
        elif file_extension in [".txt", ".md", ".markdown"]:
            return file_path.read_text(encoding="utf-8", errors="ignore")
        
        # CSV文件
        elif file_extension == ".csv":
            return _extract_from_csv(file_path)
        
        else:
            logger.warning(f"Unsupported file type: {file_extension}")
            return f"[无法解析此文件类型: {file_extension}]"
    
    except Exception as e:
        logger.error(f"Error extracting text from {file_path}: {e}")
        return f"[提取文档内容时出错: {str(e)}]"


def _extract_from_pdf(file_path: Path) -> str:
    """从PDF文件提取文本"""
    try:
        import PyPDF2
        text = []
        with open(file_path, "rb") as file:
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text.append(page.extract_text())
        return "\n".join(text)
    except ImportError:
        logger.warning("PyPDF2 not installed, cannot extract PDF text")
        return "[需要安装 PyPDF2 库来解析PDF文件]"
    except Exception as e:
        logger.error(f"Error extracting PDF: {e}")
        return f"[PDF解析错误: {str(e)}]"


def _extract_from_docx(file_path: Path) -> str:
    """从Word文档提取文本"""
    try:
        from docx import Document
        doc = Document(file_path)
        text = []
        for paragraph in doc.paragraphs:
            text.append(paragraph.text)
        return "\n".join(text)
    except ImportError:
        logger.warning("python-docx not installed, cannot extract Word text")
        return "[需要安装 python-docx 库来解析Word文档]"
    except Exception as e:
        logger.error(f"Error extracting Word: {e}")
        return f"[Word解析错误: {str(e)}]"


def _extract_from_excel(file_path: Path) -> str:
    """从Excel文件提取文本"""
    try:
        import pandas as pd
        text_parts = []
        excel_file = pd.ExcelFile(file_path)
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            text_parts.append(f"工作表: {sheet_name}\n{df.to_string()}\n")
        return "\n".join(text_parts)
    except ImportError:
        logger.warning("pandas not installed, cannot extract Excel text")
        return "[需要安装 pandas 库来解析Excel文件]"
    except Exception as e:
        logger.error(f"Error extracting Excel: {e}")
        return f"[Excel解析错误: {str(e)}]"


def _extract_from_csv(file_path: Path) -> str:
    """从CSV文件提取文本"""
    try:
        import pandas as pd
        df = pd.read_csv(file_path)
        return df.to_string()
    except ImportError:
        # 如果没有pandas，尝试用csv模块
        import csv
        text_parts = []
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for row in reader:
                text_parts.append(",".join(row))
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"Error extracting CSV: {e}")
        return f"[CSV解析错误: {str(e)}]"







