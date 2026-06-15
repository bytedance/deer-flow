# DeerFlow 分支与上游同步工作流

> 当前生效版本。取代 `docx/deer-flow-branch-strategy.md`（用 m1，无 PR 约束）和 `docx/deer-flow-upstream-sync-guide.md`（用 m2，无 PR 约束）。

## 1. 仓库结构

### Remote

| 名称 | 地址 | 说明 |
|---|---|---|
| `origin` | `git@github.com:raidery/deer-flow.git` | 个人 fork，所有 push 目标 |
| `upstream` | `git@github.com:bytedance/deer-flow.git` | 官方源，只 fetch，不 push |

### 分支拓扑

```
upstream/main (bytedance)
        │ fetch
        ▼
   upstream-sync ──merge via PR──▶ main ◀──merge via PR── m3 (当前开发分支)
                                    ▲
                                  PR #1
                                    │
                                   m2 (tag v0.1-20260612, 已合并归档)
```

### 分支职责

| 分支 | 用途 | 修改权限 |
|---|---|---|
| `upstream/main` | 上游官方分支 | ❌ 只读 |
| `upstream-sync` | 上游中转分支，只接受 `upstream/main` 的 merge | ❌ 不写业务代码 |
| `main` | 集成发布分支，接受来自 `upstream-sync` 和 feature 分支的 PR | ❌ 禁止直 push，必须 PR |
| `m3` | 当前 sprint 开发分支 | ✅ 自由开发，push 到 origin |
| `feature/*` | 单点功能短命分支（可选） | ✅ 完成后 PR 回 main 或合到 m3 |

## 2. 核心规则

1. **任何变更进入 main 必须走 PR**，禁止 `git push origin main`。
2. **上游同步走 `upstream-sync` 中转**，不要把 `upstream/main` 直接合到 `main`。
3. **m3 是 sprint 量级整合分支**；如果有独立小特性，从 main 开 `feature/xxx` → PR 回 main，不要全塞 m3。
4. **发布点打 tag**：m3 合并到 main 后打 `v0.2-YYYYMMDD`，作为下一个发布快照。

## 3. 新功能开发流程（m3）

### 创建 m3 分支（已完成）

```bash
git checkout main
git pull origin main
git checkout -b m3
git push -u origin m3
```

### 日常提交

```bash
# 在 m3 上直接提交
git add <files>
git commit -m "feat(scope): subject"
git push origin m3
```

### 完成阶段性工作后开 PR

```bash
gh pr create --base main --head m3 \
  --title "feat(m3): <主题>" \
  --body "$(cat <<'EOF'
## Summary
- 变更要点 1
- 变更要点 2

## Test plan
- [ ] 测试项 1
- [ ] 测试项 2
EOF
)"
```

合并后：

```bash
# 打 tag 作为发布快照
git checkout main
git pull origin main
git tag v0.2-$(date +%Y%m%d)
git push origin v0.2-$(date +%Y%m%d)

# 准备下一轮：保留 m3 直到 m4 开起来,或本地删除
git branch -d m3            # 可选
git push origin --delete m3 # 可选,通常等 7 天再删
```

## 4. 上游同步流程

### 手动同步（推荐先用这个）

```bash
# 1) 拉上游
git fetch upstream

# 2) 把 upstream/main 推进到 upstream-sync
git checkout upstream-sync
git merge --ff-only upstream/main || {
  echo "upstream-sync 不是 fast-forward,需手动 rebase 或解决冲突"
  exit 1
}
git push origin upstream-sync

# 3) 开 sync PR 把 upstream-sync 合到 main
git checkout main
git pull origin main
git checkout -b sync/upstream-$(date +%Y%m%d)
git merge upstream-sync   # 这里大概率有冲突,手动解决自有改动
git push origin HEAD
gh pr create --base main --head "sync/upstream-$(date +%Y%m%d)" \
  --title "chore(sync): upstream $(date +%Y-%m-%d)" \
  --body "Merge upstream/main into main via upstream-sync"
```

合并 PR 后,回到 m3 拉最新 main:

```bash
git checkout m3
git pull origin main           # 把 main 的最新合到 m3
git push origin m3
```

> 也可用 `git rebase main`,但只在 m3 还没 push 出去或团队约定允许时用,否则用 merge 更安全。

### 脚本化

把上面前两步存为 `scripts/sync-upstream.sh`(已在项目根 `scripts/` 目录的话),把交互部分(`gh pr create`)留给人手动跑。

## 5. 定时同步

### 方案 A:GitHub Action(推荐)

在 fork 的 `.github/workflows/upstream-sync.yml` 加:

```yaml
name: Upstream Sync

on:
  schedule:
    - cron: "0 1 * * 1"   # 每周一 UTC 01:00 = 北京时间周一 09:00
  workflow_dispatch:       # 允许手动触发

permissions:
  contents: write
  pull-requests: write

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: upstream-sync
          fetch-depth: 0
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Add upstream remote
        run: git remote add upstream https://github.com/bytedance/deer-flow.git

      - name: Fetch upstream
        run: git fetch upstream main

      - name: Fast-forward upstream-sync
        run: |
          git merge --ff-only upstream/main || {
            echo "::error::upstream-sync 不是 fast-forward,需人工介入"
            exit 1
          }

      - name: Push upstream-sync
        run: git push origin upstream-sync

      - name: Create sync PR to main
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          DATE=$(date +%Y%m%d)
          BRANCH="sync/upstream-$DATE"
          git checkout -b "$BRANCH"
          git push origin "$BRANCH"
          gh pr create --base main --head "$BRANCH" \
            --title "chore(sync): upstream $(date +%Y-%m-%d)" \
            --body "Automated upstream/main merge via upstream-sync." \
            || echo "PR 已存在或无变更"
```

**特点**:不自动合并 PR,只生成 PR 让 CI 跑测试 + 你审。

### 方案 B:本地 cron

```bash
# crontab -e
0 9 * * 1 cd /Users/raidery/bench/harness/raidery/deer-flow && ./scripts/sync-upstream.sh >> /tmp/deerflow-sync.log 2>&1
```

要求机器开机 + git 凭证常驻,稳定性不如 GitHub Action。

## 6. 速查

```bash
# 看分支状态
git branch -vv
git remote -v

# 看 m3 落后 main 多少
git log m3..main --oneline

# 看 main 落后 upstream/main 多少
git fetch upstream
git log main..upstream/main --oneline

# 紧急回滚某个合并
git revert -m 1 <merge_commit_sha>
```

## 7. 历史与清理

- **m2** (tag `v0.1-20260612`):已通过 PR #1 (m2-integration → main) 合入 main。本地分支可删,tag 永久保留。
- **origin/m2-integration**:计划 2026-06-19 删除(PR merge 后 7 天)。
- **upstream/feat/auth-on-2.0-rc**:与 upstream/main 已分叉,不再同步。

## 8. 相关文档

- `docx/deer-flow-branch-strategy.md` — 旧版策略(用 m1,无 PR),保留作历史参考
- `docx/deer-flow-upstream-sync-guide.md` — 旧版同步指南(用 m2,无 PR),保留作历史参考
- 本文档为当前生效版本
