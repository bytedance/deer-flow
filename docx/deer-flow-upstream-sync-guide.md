# DeerFlow Upstream 同步策略指南

## 分支结构

```
byteDance/deer-flow (upstream)
    └── main
          ↑
          │ 定期合并
          │
upstream-sync  ← 专门同步上游
m1             ← 你的开发分支
main           ← 最终集成分支（本地，不跟踪 upstream）
```

## 完整命令清单

### 阶段一：初始化（只需执行一次）

```bash
# 1. 添加上游仓库
git remote add upstream https://github.com/byteDance/deer-flow.git

# 2. 验证 remote 配置
git remote -v
```

### 阶段二：创建同步分支

```bash
# 3. 创建 upstream-sync 分支
git checkout -b upstream-sync

# 4. 设置 upstream-sync 跟踪上游 main
git branch --set-upstream-to=upstream/main upstream-sync

# 5. 推送 upstream-sync 到 origin
git push -u origin upstream-sync
```

### 阶段三：日常同步（定期执行）

```bash
# 切换到 upstream-sync
git checkout upstream-sync

# 拉取上游最新代码
git fetch upstream

# 合并上游 main 到当前分支
git merge upstream/main

# 推送合并结果
git push
```

'''
本地有修改，需要先暂存：

  git stash

  然后再执行合并：

  git merge upstream/main
'''

### 阶段四：开发与合并

```bash
# 在 m1 开发
git checkout m1

# ... 开发完成后，切换到 main ...
git checkout main

# 合入上游同步分支
git merge upstream-sync

# 合入你的开发分支
git merge m1

# 推送到 origin
git push origin main
```

## 分支跟踪关系

| 分支 | 跟踪 | 说明 |
|------|------|------|
| `upstream-sync` | `upstream/main` | 同步上游代码 |
| `m1` | `origin/m1`（已有） | 开发分支 |
| `main` | 无 | 本地集成分支，完成后推送到 origin |

## 工作流程图

```
┌─────────────────────────────────────────────────────┐
│  定期同步（每周/每两周）                               │
│  ┌─────────────────┐    ┌──────────────────────┐  │
│  │ upstream/main   │───→│ upstream-sync        │  │
│  │ (byteDance)     │    │ (git merge)          │  │
│  └─────────────────┘    └──────────┬───────────┘  │
│                                     │ push         │
│                                     ↓              │
│  ┌─────────────────┐    ┌──────────────────────┐  │
│  │ origin/main    │←───│ main (本地集成分支)   │  │
│  │ (远程)          │ push│ git merge upstream-sync│ │
│  └─────────────────┘    │ git merge m1         │  │
│                         └──────────────────────┘  │
│                                     ↑              │
│  ┌─────────────────┐    ┌──────────────────────┐  │
│  │ origin/m1       │←───│ m1 (开发分支)         │  │
│  └─────────────────┘    └──────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

## 为什么这种结构更好

| 优势 | 说明 |
|------|------|
| 职责分离 | upstream-sync 专注同步，m1 专注开发 |
| 减少冲突 | 上游冲突在 upstream-sync 处理，m1 保持干净 |
| 历史清晰 | main 作为集成分支，可以看到完整的合入记录 |
| 可追溯 | 问题出现时容易定位是上游代码还是自己引入的 |
