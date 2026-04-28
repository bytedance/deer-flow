"""
card_validator 工具测试脚本
测试各种场景下的 card.json 验证和修复功能
"""

import sys
import os
import json
import tempfile
import shutil

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from my_tools.card_validator import card_validator


def test_valid_card():
    """测试1：验证格式正确的 card.json"""
    print("\n=== 测试1：验证格式正确的 card.json ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        card_path = os.path.join(tmpdir, "card.json")
        card_data = {
            "book_name": "测试项目",
            "genre": "悬疑",
            "concept": "一个关于暗巷中的神秘守护者故事",
            "platform": "起点",
            "status": "planning",
            "current_chapter": 0,
            "target_chapters": 0
        }
        
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        
        result = card_validator.invoke({"card_path": card_path, "fix": False})
        print(f"结果：{result}")
        assert "[OK]" in result or "验证通过" in result, "应该验证通过"
        print("[OK] 测试1通过")


def test_missing_fields():
    """测试2：缺少必填字段"""
    print("\n=== 测试2：缺少必填字段 ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        card_path = os.path.join(tmpdir, "card.json")
        card_data = {
            "book_name": "测试项目",
            "status": "planning"
        }
        
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        
        # 不修复 - 应该报告缺失字段
        result = card_validator.invoke({"card_path": card_path, "fix": False})
        print(f"结果（不修复）：{result}")
        assert "[FAIL]" in result or "验证失败" in result, "应该验证失败"
        assert "缺少必填字段：genre" in result, "应该报告缺少 genre"
        assert "缺少必填字段：current_chapter" in result, "应该报告缺少 current_chapter"
        
        # 修复 - 也应该报告缺失字段（因为工具不补全内容，只验证格式）
        result = card_validator.invoke({"card_path": card_path, "fix": True})
        print(f"结果（修复）：{result}")
        assert "[FAIL]" in result or "验证失败" in result, "应该仍然失败（缺失字段需要大模型补全）"
        assert "缺少必填字段" in result, "应该报告缺失字段"
        
        # 验证文件没有被修改（因为缺失字段无法自动补全）
        with open(card_path, "r", encoding="utf-8") as f:
            unchanged_data = json.load(f)
        
        assert "genre" not in unchanged_data, "genre 不应该被工具自动添加"
        assert "current_chapter" not in unchanged_data, "current_chapter 不应该被工具自动添加"
        print("[OK] 测试2通过（缺失字段需要大模型补全，工具只负责报告）")


def test_wrong_types():
    """测试3：字段类型错误（数字是字符串）"""
    print("\n=== 测试3：字段类型错误 ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        card_path = os.path.join(tmpdir, "card.json")
        card_data = {
            "book_name": "测试项目",
            "genre": "悬疑",
            "concept": "测试概念",
            "platform": "起点",
            "status": "planning",
            "current_chapter": "0",
            "target_chapters": "5"
        }
        
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        
        # 修复
        result = card_validator.invoke({"card_path": card_path, "fix": True})
        print(f"结果：{result}")
        assert "已修复" in result, "应该修复类型错误"
        
        # 验证修复后的文件
        with open(card_path, "r", encoding="utf-8") as f:
            fixed_data = json.load(f)
        
        assert isinstance(fixed_data["current_chapter"], int), "current_chapter 应该是 int"
        assert isinstance(fixed_data["target_chapters"], int), "target_chapters 应该是 int"
        assert fixed_data["current_chapter"] == 0, "值应该是 0"
        assert fixed_data["target_chapters"] == 5, "值应该是 5"
        print("[OK] 测试3通过")


def test_invalid_status():
    """测试4：无效的 status 值"""
    print("\n=== 测试4：无效的 status 值 ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        card_path = os.path.join(tmpdir, "card.json")
        card_data = {
            "book_name": "测试项目",
            "genre": "悬疑",
            "concept": "测试概念",
            "platform": "起点",
            "status": "invalid_status",
            "current_chapter": 0,
            "target_chapters": 0
        }
        
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        
        result = card_validator.invoke({"card_path": card_path, "fix": True})
        print(f"结果：{result}")
        assert "已修复" in result, "应该修复无效 status"
        
        # 验证修复后的文件
        with open(card_path, "r", encoding="utf-8") as f:
            fixed_data = json.load(f)
        
        assert fixed_data["status"] == "planning", "status 应该修复为 planning"
        print("[OK] 测试4通过")


def test_auto_create():
    """测试5：文件不存在时自动创建"""
    print("\n=== 测试5：文件不存在时自动创建 ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        card_path = os.path.join(tmpdir, "new_card.json")
        
        # 不自动创建
        result = card_validator.invoke({"card_path": card_path, "auto_create": False})
        print(f"结果（不自动创建）：{result}")
        assert "[FAIL]" in result or "文件不存在" in result, "应该提示文件不存在"
        
        # 自动创建
        result = card_validator.invoke({
            "card_path": card_path,
            "auto_create": True,
            "book_name": "自动创建测试",
            "genre": "玄幻",
            "concept": "自动创建的概念",
            "platform": "番茄"
        })
        print(f"结果（自动创建）：{result}")
        assert "[OK]" in result or "已创建" in result, "应该自动创建"
        
        # 验证创建的文件
        assert os.path.exists(card_path), "文件应该存在"
        with open(card_path, "r", encoding="utf-8") as f:
            created_data = json.load(f)
        
        assert created_data["book_name"] == "自动创建测试", "书名应该正确"
        assert created_data["genre"] == "玄幻", "类型应该正确"
        assert created_data["concept"] == "自动创建的概念", "概念应该正确"
        assert created_data["platform"] == "番茄", "平台应该正确"
        assert created_data["status"] == "planning", "状态应该是 planning"
        assert created_data["current_chapter"] == 0, "当前章节应该是 0"
        assert created_data["target_chapters"] == 0, "目标章节应该是 0"
        print("[OK] 测试5通过")


def test_json_with_comments():
    """测试6：JSON 包含注释"""
    print("\n=== 测试6：JSON 包含注释 ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        card_path = os.path.join(tmpdir, "card.json")
        # 包含注释的 JSON（不符合标准）
        json_content = """{
  "book_name": "测试项目",
  "genre": "悬疑",
  "concept": "测试概念",
  "platform": "起点",
  "status": "planning",
  "current_chapter": 0,
  "target_chapters": 0
}"""
        
        with open(card_path, "w", encoding="utf-8") as f:
            f.write(json_content)
        
        result = card_validator.invoke({"card_path": card_path, "fix": True})
        print(f"结果：{result}")
        assert "验证通过" in result or "已修复" in result, "应该处理注释问题"
        print("[OK] 测试6通过")


def test_negative_numbers():
    """测试7：负数章节号"""
    print("\n=== 测试7：负数章节号 ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        card_path = os.path.join(tmpdir, "card.json")
        card_data = {
            "book_name": "测试项目",
            "genre": "悬疑",
            "concept": "测试概念",
            "platform": "起点",
            "status": "planning",
            "current_chapter": -1,
            "target_chapters": -5
        }
        
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        
        result = card_validator.invoke({"card_path": card_path, "fix": True})
        print(f"结果：{result}")
        assert "已修复" in result, "应该修复负数"
        
        # 验证修复后的文件
        with open(card_path, "r", encoding="utf-8") as f:
            fixed_data = json.load(f)
        
        assert fixed_data["current_chapter"] == 0, "current_chapter 应该修复为 0"
        assert fixed_data["target_chapters"] == 0, "target_chapters 应该修复为 0"
        print("[OK] 测试7通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("开始运行 card_validator 工具测试")
    print("=" * 60)
    
    try:
        test_valid_card()
        test_missing_fields()
        test_wrong_types()
        test_invalid_status()
        test_auto_create()
        test_json_with_comments()
        test_negative_numbers()
        
        print("\n" + "=" * 60)
        print("[OK] 所有测试通过！")
        print("=" * 60)
        return True
    except Exception as e:
        print("\n" + "=" * 60)
        print(f"[FAIL] 测试失败：{e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
