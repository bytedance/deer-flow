# DeerFlow 定制开发分支管理策略

## 目标

保持社区上游（upstream）和本地定制修改并行，清晰分离、不相互污染。

## 分支命名约定

| 分支 | 用途 | 追踪 |
|------|------|------|
| `main` | 社区代码镜像，只做同步和合并 | `upstream/main` |
| `m1` | 你的主开发分支，所有功能汇聚点 | `origin/m1` |
| `feature-xxx` | 短命功能分支，开发完合并删除 | 无 |

## 仓库远程约定

| 远程名 | 地址 | 说明 |
|--------|------|------|
| `origin` | `git@github.com:raidery/deer-flow.git` | 你的 fork |
| `upstream` | `git@github.com:bytedance/deer-flow.git` | 社区原版 |

## 初始化流程

### 1. 首次设置（克隆后一次性执行）

```bash
# 添加上游仓库
git remote add upstream git@github.com:bytedance/deer-flow.git

# 创建开发分支并推送
git checkout -b m1
git push -u origin m1
```

### 2. 已有仓库，后续新增上游

```bash
# 检查远程
git remote -v
# 如果没有 upstream，手动添加
git remote add upstream git@github.com:bytedance/deer-flow.git

# 确保在 main 并创建开发分支
git checkout main
git checkout -b m1
git push -u origin m1
```

## 日常开发流程

### 同步上游社区（建议每周至少一次）

```bash
# 1. 切换到 main
git checkout main

# 2. 获取上游最新代码
git fetch upstream

# 3. 合并上游更新到本地 main
git merge upstream/main

# 4. 推送到你的 origin（保持你的 fork 和上游同步）
git push

# 5. 切换回开发分支
git checkout m1

# 6. 把刚才 main 更新的上游代码也合并进来
git merge main
```

> 如果合并有冲突，在 `main` 上解决冲突后 push；然后在 `m1` 上再做一次 merge 或 rebase。

### 开发新功能

```bash
# 1. 从 m1 创建短命分支
git checkout m1
git checkout -b feature-xxx

# 2. 开发、提交
git add .
git commit -m "feat: add xxx feature"

# 3. 多次提交可以继续在 feature-xxx 上
git commit -m "fix: handle edge case"

# 4. 功能完成后，合并回主开发分支
git checkout m1
git merge feature-xxx

# 5. 删除短命分支（保持分支列表干净）
git branch -d feature-xxx

# 6. 推送更新
git push
```

### 发布：合并到 main

```bash
# 1. 确保所有功能已合并到 m1
git checkout main

# 2. 同步上游（可选，建议）
git fetch upstream
git merge upstream/main

# 3. 合并你的开发分支
git merge m1

# 4. 推送（发布完成）
git push
```

## 分支结构图

```
upstream/bytedance/deer-flow
         │
         │ 定期 fetch + merge
         ▼
┌─────────────────────────────────┐
│          origin/main            │  ← 社区代码镜像
│   (只接受 upstream 合并)        │
└───────┬─────────────────────────┘
        │ merge m1
        ▼
┌─────────────────────────────────┐
│     m1          │  ← 主开发分支
│  (所有功能最终汇聚点)            │
└───────┬─────────────────────────┘
        │ merge feature-xxx
        ▼
   feature-xxx  (短命，用完删除)
```

## 常用命令速查

```bash
# 查看分支状态
git branch -vv
git remote -v

# 同步上游
git checkout main && git fetch upstream && git merge upstream/main && git push

# 查看还未合并到 main 的提交
git log main..m1

# 删除已合并的短命分支
git branch -d feature-xxx

# 强制删除未合并的分支
git branch -D feature-xxx

# 查看远程分支
git branch -r
```

```
把m1 branch的文件合并到当前branch
❯ git checkout m1 -- .env.example backend/Dockerfile docker/provisioner/Dockerfile
❯ git checkout m1 -- .env.example frontend/Dockerfile docker/docker-compose-dev.yaml
❯ git checkout m1 -- docker/docker-compose.yaml
❯ git checkout m1 -- docx
```
## 注意事项

1. **永远不要在 `main` 上直接开发**。`main` 的唯一职责是保持和上游同步。
2. **功能开发用短命分支**，完成后合并回 `m1`，避免分支列表混乱。
3. **定期同步上游**，避免积累太多冲突。建议每周至少一次。
4. **解决冲突时优先保留社区代码**（因为社区是上游，你的定制是下游）。
5. 如果 rebase 更符合你的习惯，可以用 `git rebase main` 代替 `git merge main`。