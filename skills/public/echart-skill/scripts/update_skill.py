#!/usr/bin/env python3
"""
echart-skill 更新脚本

功能：
1. 首次安装：git clone 从 GitHub 克隆代码
2. 后续更新：git pull 拉取最新代码
3. 更新前自动备份旧文件到 backup 目录
"""

import os
import sys
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path


REPO_URL = "https://github.com/lgwanai/echart-skill.git"
BACKUP_DIR = "backup"
EXCLUDE_DIRS = {".git", "backup", "dist", "tmp", "outputs", "__pycache__", "node_modules"}
EXCLUDE_FILES = {"workspace.duckdb", "echart_config.txt", ".DS_Store", "*.pyc", "*.log", "*.duckdb"}


def should_exclude(path: Path) -> bool:
    """检查路径是否应排除"""
    name = path.name
    if name in EXCLUDE_DIRS:
        return True
    for pattern in EXCLUDE_FILES:
        if pattern.startswith("*"):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True
    return False


def create_backup(skill_root: Path) -> str:
    """创建备份压缩包"""
    backup_dir = skill_root / BACKUP_DIR
    backup_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"echart-skill_backup_{timestamp}.zip"
    backup_path = backup_dir / backup_name
    
    print(f"📦 创建备份: {backup_path}")
    
    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(skill_root):
            root_path = Path(root)
            dirs[:] = [d for d in dirs if not should_exclude(root_path / d)]
            
            for file in files:
                file_path = root_path / file
                if not should_exclude(file_path):
                    arcname = str(file_path.relative_to(skill_root))
                    zf.write(file_path, arcname)
    
    size_mb = backup_path.stat().st_size / (1024 * 1024)
    print(f"✅ 备份完成: {backup_name} ({size_mb:.2f} MB)")
    
    return str(backup_path)


def is_git_repo(path: Path) -> bool:
    """检查是否是 git 仓库"""
    return (path / ".git").exists()


def git_clone(target_dir: Path) -> bool:
    """执行 git clone"""
    print(f"\n📥 克隆仓库: {REPO_URL}")
    
    parent_dir = target_dir.parent
    repo_name = target_dir.name
    
    try:
        result = subprocess.run(
            ["git", "clone", REPO_URL, repo_name],
            cwd=parent_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            print(f"✅ 克隆成功")
            return True
        else:
            print(f"❌ 克隆失败: {result.stderr.strip()}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ 克隆超时")
        return False
    except Exception as e:
        print(f"❌ 克隆异常: {e}")
        return False


def git_pull(skill_root: Path) -> bool:
    """执行 git pull"""
    print("\n📥 拉取最新代码...")
    
    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=skill_root,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            print(f"✅ 更新成功")
            if result.stdout and result.stdout.strip() != "Already up to date.":
                print(result.stdout.strip())
            return True
        else:
            print(f"❌ 更新失败: {result.stderr.strip()}")
            return False
            
    except subprocess.TimeoutExpired:
        print("❌ 更新超时")
        return False
    except Exception as e:
        print(f"❌ 更新异常: {e}")
        return False


def update_skill(skill_root: Path) -> bool:
    """更新 skill（自动判断 clone 或 pull）"""
    if is_git_repo(skill_root):
        return git_pull(skill_root)
    else:
        print("\n⚠️ 当前目录不是 git 仓库")
        print("💡 请先执行以下命令安装:")
        print(f"   cd {skill_root.parent}")
        print(f"   git clone {REPO_URL}")
        return False


def main():
    """主函数"""
    skill_root = Path(__file__).parent.resolve().parent
    print(f"📁 Skill 目录: {skill_root}")
    
    backup_path = None
    if skill_root.exists() and list(skill_root.iterdir()):
        if is_git_repo(skill_root):
            backup_path = create_backup(skill_root)
        else:
            print("\n⚠️ 首次安装，跳过备份")
    
    success = update_skill(skill_root)
    
    print("\n" + "="*50)
    if success:
        print("🎉 echart-skill 更新完成!")
    else:
        print("⚠️ 更新失败")
    if backup_path:
        print(f"📦 备份文件: {backup_path}")
    print("="*50)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
