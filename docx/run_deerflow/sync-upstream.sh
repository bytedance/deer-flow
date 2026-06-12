#!/bin/bash
#
# sync-upstream.sh - 从上游同步 DeerFlow 到本地分支
#
# 用法:
#   ./sync-upstream.sh          # 交互式确认后执行
#   ./sync-upstream.sh --dry-run  # 仅显示将执行的操作
#
# 流程:
#   1. upstream/main → upstream-sync (fetch + merge)
#   2. upstream-sync → main (merge)
#   3. main → m2（仅显示命令，各分支自行决定）
#

set -e

# 禁用分页器，避免交互卡住
export GIT_PAGER=cat

DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
  DRY_RUN=true
fi

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_step() { echo -e "${GREEN}[STEP]${NC} $1"; }

confirm() {
  local prompt="$1"
  local response
  echo -ne "${YELLOW}${prompt} [y/N]: ${NC}"
  read response
  case "$response" in
    [yY][eE][sS]|[yY]) return 0 ;;
    *) return 1 ;;
  esac
}

echo ""
log_info "=========================================="
log_info "   DeerFlow Upstream Sync Workflow"
log_info "=========================================="
echo ""

# 检查当前分支
CURRENT_BRANCH=$(git branch --show-current)
log_info "当前分支: ${CURRENT_BRANCH}"
echo ""

# Step 1: 显示上游更新情况
log_step "Step 1: 检查上游更新"
echo "--------------------------------------------------"
UPSTREAM_MAIN="upstream/main"
LOCAL_SYNC="upstream-sync"

# 获取上游最新 commit
UPSTREAM_SHA=$(git rev-parse $UPSTREAM_MAIN 2>/dev/null)
LOCAL_SYNC_SHA=$(git rev-parse $LOCAL_SYNC 2>/dev/null)

if [[ -z "$UPSTREAM_SHA" ]]; then
  log_warn "无法获取 upstream/main，跳过检查"
else
  log_info "upstream/main: $(git log -1 --oneline $UPSTREAM_MAIN 2>/dev/null || echo 'N/A')"
fi

if [[ -z "$LOCAL_SYNC_SHA" ]]; then
  log_warn "upstream-sync 分支不存在，将从 upstream/main 创建"
else
  log_info "upstream-sync: $(git log -1 --oneline $LOCAL_SYNC 2>/dev/null || echo 'N/A')"
  if [[ "$UPSTREAM_SHA" == "$LOCAL_SYNC_SHA" ]]; then
    log_warn "upstream-sync 已与 upstream/main 同步，无需更新"
  else
    BEHIND=$(git rev-list --count $LOCAL_SYNC..$UPSTREAM_MAIN 2>/dev/null || echo "?")
    log_info "upstream-sync 落后上游约 ${BEHIND} 个提交"
  fi
fi
echo ""

# Step 2: 显示完整操作计划
log_step "Step 2: 操作计划"
echo "--------------------------------------------------"
echo ""
echo "  ① upstream/main → upstream-sync"
echo "     git fetch upstream"
echo "     git checkout upstream-sync"
echo "     git merge upstream/main"
echo "     git push"
echo ""
echo "  ② upstream-sync → main"
echo "     git checkout main"
echo "     git merge upstream-sync"
echo "     git push origin main"
echo ""
echo "  ③ main → m2（仅显示命令，各分支自行决定）"
echo ""
echo ""

# Step 3: 检查工作区状态
log_step "Step 3: 检查工作区"
echo "--------------------------------------------------"
if [[ -n "$(git status --porcelain)" ]]; then
  log_warn "工作区有未提交的更改!"
  git status --short
  echo ""
  log_warn "=============================="
  log_warn "请先执行以下命令："
  log_warn "  git stash -u"
  log_warn "  ./sync-upstream.sh"
  log_warn "  git stash pop"
  log_warn "=============================="
  echo ""
  exit 1
else
  log_info "工作区干净"
fi
echo ""

# 检查 main 和 m2 状态
log_info "main 分支状态:"
git log -1 --oneline main 2>/dev/null || log_warn "main 分支不存在"
echo ""

log_info "m2 分支状态:"
git log -1 --oneline m2 2>/dev/null || log_warn "m2 分支不存在"
echo ""

if $DRY_RUN; then
  log_warn "=========================================="
  log_warn "   DRY RUN - 未执行任何操作"
  log_warn "=========================================="
  exit 0
fi

# 确认执行
if ! confirm "确认执行上述同步操作？"; then
  log_warn "已取消"
  exit 0
fi

echo ""
log_info "=========================================="
log_info "          开始执行同步"
log_info "=========================================="
echo ""

# Phase 1: 同步 upstream-sync
log_step "Phase 1: 同步 upstream-sync"
echo "用途: 将上游最新代码拉取到 upstream-sync 分支"
echo "--------------------------------------------------"
rtk git checkout upstream-sync
rtk git fetch upstream
if ! rtk git merge upstream/main; then
  log_warn "检测到合并冲突！"
  echo ""
  echo "冲突文件:"
  git --no-pager diff --name-only --diff-filter=U
  echo ""
  log_warn "正在中止合并操作..."
  rtk git merge --abort
  exit 1
fi
rtk git push
echo ""

# Phase 2: 合入 main
log_step "Phase 2: 合入 main"
echo "用途: 将 upstream-sync 合并到本地 main，作为集成分支"
echo "--------------------------------------------------"
rtk git checkout main
if ! rtk git merge upstream-sync; then
  log_warn "检测到合并冲突！"
  echo ""
  echo "冲突文件:"
  git --no-pager diff --name-only --diff-filter=U
  echo ""
  log_warn "正在中止合并操作..."
  rtk git merge --abort
  exit 1
fi
rtk git push origin main
echo ""

# Phase 3: 显示 m2 合并命令（不执行）
log_step "Phase 3: m2 合并信息"
echo "用途: 各开发分支自行决定何时合并"
echo "--------------------------------------------------"
if git rev-parse --quiet --verify m2 >/dev/null; then
  MAIN_SHA=$(git rev-parse main)
  M2_BASE=$(git merge-base main m2)
  if [[ "$MAIN_SHA" == "$M2_BASE" ]]; then
    log_info "m2 已基于最新 main，无需合并"
  else
    COMMITS_BEHIND=$(git rev-list --count m2..main 2>/dev/null || echo "?")
    log_info "m2 落后 main 约 ${COMMITS_BEHIND} 个提交"
    echo ""
    echo "如需合并到 m2，执行:"
    echo "  git checkout m2"
    echo "  git rebase main"
  fi
else
  log_warn "m2 分支不存在"
fi
echo ""

echo ""
log_info "=========================================="
log_info "          同步完成"
log_info "=========================================="
echo ""

log_info "提交历史 (upstream-sync):"
rtk git log --oneline -5 upstream-sync
echo ""

log_info "提交历史 (main):"
rtk git log --oneline -5 main
echo ""

log_info "提交历史 (m2):"
rtk git log --oneline -5 m2
echo ""