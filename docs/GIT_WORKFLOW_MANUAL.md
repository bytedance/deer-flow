
# DeerFlow Git 工作流程（手动终端版）

**版本**: 1.0.0  
**最后更新**: 2026-04-11

---

## 📋 目录

1. [前提条件检查](#前提条件检查)
2. [步骤 1：创建完整备份](#步骤-1创建完整备份)
3. [步骤 2：同步上游更新](#步骤-2同步上游更新)
4. [步骤 3：检查并解决冲突](#步骤-3检查并解决冲突)
5. [步骤 4：更新 main 分支](#步骤-4更新-main-分支)
6. [步骤 5：推送到远程仓库](#步骤-5推送到远程仓库)
7. [回滚方案](#回滚方案)
8. [快速完整命令](#快速完整命令)

---

## 前提条件检查

```bash
# 1. 查看当前状态
git status

# 2. 确认远程配置
git remote -v

# 3. 确认当前分支
git branch
```

---

## 步骤 1：创建完整备份（重要！）

```bash
# 1.1 创建备份分支
DATE=$(date +%Y%m%d-%H%M)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
BACKUP_BRANCH="backup/$CURRENT_BRANCH-$DATE"
git branch $BACKUP_BRANCH
echo "✅ 备份分支已创建: $BACKUP_BRANCH"

# 1.2 如果有未提交的更改，暂存它们
if [ -n "$(git status --porcelain)" ]; then
    git stash push -m "auto-sync-stash-$DATE"
    echo "✅ 未提交更改已暂存"
fi

# 1.3 创建 Git bundle（可选，用于完整备份）
git bundle create "repo-backup-$DATE.bundle" --all
echo "✅ Git bundle 已创建: repo-backup-$DATE.bundle"
```

---

## 步骤 2：同步上游更新

```bash
# 2.1 获取上游所有更新
git fetch upstream --tags
echo "✅ 上游更新已获取"

# 2.2 检查是否有新更新
if git log HEAD..upstream/main --oneline | grep -q .; then
    echo "📦 发现上游新更新:"
    git log HEAD..upstream/main --oneline
else
    echo "ℹ️  上游没有新更新"
fi

# 2.3 合并上游更新（优先保留本地修改）
git merge -X ours upstream/main -m "Merge upstream/main with local modifications (ours strategy)"
```

---

## 步骤 3：检查并解决冲突（如果有）

```bash
# 3.1 检查是否有冲突
CONFLICTS=$(git status --porcelain | grep -E "^UU|^AA|^DD" | cut -c4-)
if [ -n "$CONFLICTS" ]; then
    echo "❌ 发现冲突文件:"
    echo "$CONFLICTS"
    echo ""
    echo "请手动编辑冲突文件，然后执行："
    echo "  git add &lt;冲突文件&gt;"
    echo "  git commit"
    echo ""
    echo "或者中止合并："
    echo "  git merge --abort"
else
    echo "✅ 没有冲突，合并成功！"
fi
```

---

## 步骤 4：更新 main 分支

```bash
# 4.1 切换到 main 分支
git checkout main

# 4.2 将 dev 合并到 main（fast-forward）
git merge dev --ff-only

# 4.3 切回 dev 分支
git checkout dev
```

---

## 步骤 5：推送到远程仓库

```bash
# 5.1 推送到 origin（您的 main 仓库）
echo "📤 推送到 origin..."
git push origin main
git push origin dev

# 5.2 推送到 private（您的私人仓库）
echo "📤 推送到 private..."
git push private main
git push private dev

echo "✅ 所有推送完成！"
```

---

## 🔙 回滚方案（如果需要）

```bash
# 方案 1：切换回备份分支
echo "可用的备份分支："
git branch | grep backup
echo ""
echo "切换到备份："
echo "  git checkout $BACKUP_BRANCH"

# 方案 2：从 Git bundle 恢复
echo "从 bundle 恢复："
echo "  git clone repo-backup-$DATE.bundle recovery"
```

---

## 📝 快速完整命令（一键执行）

如果您想一键执行所有步骤，可以使用以下命令：

```bash
DATE=$(date +%Y%m%d-%H%M)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
BACKUP_BRANCH="backup/$CURRENT_BRANCH-$DATE"

echo "=========================================="
echo "DEERFLOW GIT WORKFLOW - MANUAL"
echo "=========================================="
echo ""

# Step 1: Backup
echo "[1/5] 创建备份..."
git branch $BACKUP_BRANCH
[ -n "$(git status --porcelain)" ] && git stash push -m "auto-sync-stash-$DATE"
echo "✅ 备份完成: $BACKUP_BRANCH"
echo ""

# Step 2: Sync upstream
echo "[2/5] 同步上游..."
git fetch upstream --tags
git merge -X ours upstream/main -m "Merge upstream/main with local modifications (ours strategy)"
echo "✅ 上游同步完成"
echo ""

# Step 3: Update main
echo "[3/5] 更新 main 分支..."
git checkout main
git merge dev --ff-only
git checkout dev
echo "✅ main 分支已更新"
echo ""

# Step 4: Push to origin
echo "[4/5] 推送到 origin..."
git push origin main
git push origin dev
echo "✅ origin 推送完成"
echo ""

# Step 5: Push to private
echo "[5/5] 推送到 private..."
git push private main
git push private dev
echo "✅ private 推送完成"
echo ""

echo "=========================================="
echo "✅ 工作流完成！"
echo "=========================================="
```

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `docs/GIT_WORKFLOW_MANUAL.md` | 本文档 - 手动终端操作指南 |
| `docs/GIT_ARCHITECTURE_ANALYSIS.md` | Git 架构分析 |

