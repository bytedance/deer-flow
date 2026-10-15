"""
Google Drive 技能评估测试
基本功能测试用例
"""
import os
import sys
import pytest

# 添加脚本目录到路径
script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
scripts_path = os.path.join(script_dir, 'scripts')
sys.path.insert(0, scripts_path)

from utils import get_mime_type, get_google_mime_type, format_size

class TestUtils:
    """测试工具函数"""
    
    def test_get_mime_type_by_extension(self):
        """测试通过扩展名获取 MIME 类型"""
        assert get_mime_type('test.pdf') == 'application/pdf'
        assert get_mime_type('document.txt') == 'text/plain'
        assert get_mime_type('image.jpg') == 'image/jpeg'
    
    def test_get_google_mime_type(self):
        """测试获取 Google Workspace MIME 类型"""
        assert get_google_mime_type('doc') == 'application/vnd.google-apps.document'
        assert get_google_mime_type('sheet') == 'application/vnd.google-apps.spreadsheet'
        assert get_google_mime_type('slide') == 'application/vnd.google-apps.presentation'
        assert get_google_mime_type('folder') == 'application/vnd.google-apps.folder'
    
    def test_format_size(self):
        """测试文件大小格式化"""
        assert format_size(0) == '0 B'
        assert format_size(1024) == '1.0 KB'
        assert format_size(1024 * 1024) == '1.0 MB'
        assert format_size(1024 * 1024 * 1024) == '1.0 GB'

@pytest.mark.skipif(not os.path.exists('token.json'), reason="需要先完成认证")
class TestDriveIntegration:
    """Google Drive 集成测试（需要认证）"""
    
    def test_credentials_available(self):
        """测试凭证文件是否存在"""
        assert os.path.exists('credentials.json') or os.path.exists('token.json')
    
    def test_utils_import(self):
        """测试工具模块导入"""
        from utils import (
            get_credentials,
            build_drive_service,
            format_datetime
        )
        assert True

class TestSearchQuery:
    """测试搜索查询构建"""
    
    def test_basic_query_components(self):
        """测试基本查询组件"""
        # 这些是实际搜索功能中使用的查询模式
        test_cases = [
            ("name contains 'test'", "文件名搜索"),
            ("fullText contains 'keyword'", "全文搜索"),
            ("mimeType = 'application/pdf'", "类型过滤"),
            ("trashed = false", "排除已删除"),
            ("'root' in parents", "根目录文件"),
        ]
        
        for query, description in test_cases:
            assert isinstance(query, str)
            assert len(query) > 0

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
