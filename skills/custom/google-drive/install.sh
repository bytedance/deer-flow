#!/bin/bash
# DeerFlow Google Drive 集成技能 - 一键安装脚本

set -e

echo "=========================================="
echo "  DeerFlow Google Drive 集成技能安装器"
echo "=========================================="
echo ""

# 检查 DeerFlow 项目目录
DEFAULT_DEERFLOW_DIR="$HOME/deer-flow"
read -p "请输入 DeerFlow 项目目录 [默认: $DEFAULT_DEERFLOW_DIR]: " DEERFLOW_DIR
DEERFLOW_DIR=${DEERFLOW_DIR:-$DEFAULT_DEERFLOW_DIR}

# 验证目录存在
if [ ! -d "$DEERFLOW_DIR" ]; then
    echo "❌ 目录不存在: $DEERFLOW_DIR"
    echo "请确认 DeerFlow 项目路径后重试"
    exit 1
fi

echo "✅ DeerFlow 目录: $DEERFLOW_DIR"
echo ""

# 目标技能目录
SKILLS_DIR="$DEERFLOW_DIR/skills/custom/google-drive"

# 创建目录
echo "📁 创建技能目录..."
mkdir -p "$SKILLS_DIR"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 复制文件
echo "📦 复制技能文件..."
cp -r "$SCRIPT_DIR"/* "$SKILLS_DIR"/

# 清理可能重复的 install.sh（避免递归复制
rm -f "$SKILLS_DIR"/install.sh

echo ""
echo "✅ 安装完成！"
echo ""
echo "=========================================="
echo "📋 下一步操作："
echo "=========================================="
echo ""
echo "1. 检查 Docker 卷挂载配置："
echo "   编辑 $DEERFLOW_DIR/docker-compose.yml"
echo "   确认 backend 服务有类似配置："
echo "   volumes:"
echo "     - ./skills:/app/backend/skills"
echo ""
echo "2. 获取 Google Cloud 凭证："
echo "   - 访问 https://console.cloud.google.com/"
echo "   - 创建 OAuth 凭证并保存为 credentials.json"
echo "   - 放到: $SKILLS_DIR/credentials.json"
echo ""
echo "3. 完成认证："
echo "   cd $SKILLS_DIR"
echo "   pip install -r requirements.txt"
echo "   python scripts/auth_setup.py"
echo ""
echo "4. 重启 DeerFlow："
echo "   cd $DEERFLOW_DIR"
echo "   make down && make up"
echo ""
echo "=========================================="
echo "🚀 安装位置: $SKILLS_DIR"
echo "=========================================="
