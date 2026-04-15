# Feishu Multi-Bot Feature: Git Workflow Guide

This document outlines the strict, isolated Git workflow for developing the Feishu multi-bot and agent-specific binding feature in DeerFlow. Following this guide ensures a pristine baseline, prevents merge conflicts, and maintains a clean commit history for the final Pull Request.

## Step 1: Remote Setup Verification
Ensure your local repository is correctly tracking both your personal fork (`origin`) and the official repository (`upstream`).

```bash
# Verify your remotes
git remote -v

# Expected output should include:
# origin    git@github.com:<your-username>/deer-flow.git (fetch)
# origin    git@github.com:<your-username>/deer-flow.git (push)
# upstream  https://github.com/bytedance/deer-flow.git (fetch)
# upstream  https://github.com/bytedance/deer-flow.git (push)
```

## Step 2: Implement a Clean Working Environment
Before starting or rebasing, guarantee a pristine baseline by clearing out any uncommitted experimental or unrelated changes. This ensures your feature branch remains strictly isolated.

```bash
# Navigate to the project root
cd /Users/luole/deer-flow

# Safely stash all current unstaged and untracked unrelated changes
git stash push -u -m "WIP: unrelated changes before starting feishu feature"

# Verify your working directory is clean (should say "nothing to commit, working tree clean")
git status
```

*Note: If you ever need to retrieve these unrelated changes later, you can switch to a different branch and run `git stash pop`.*

## Step 3: Baseline Commit Identification & Branch Creation
Always branch directly from the absolute latest official codebase, not your local `main`.

```bash
# 1. Fetch the latest state from the official repository
git fetch upstream

# 2. Create and checkout a dedicated feature branch from the upstream baseline
git checkout -b feature/feishu-multi-bot-binding upstream/main

# 3. Verify your baseline commit matches the latest upstream commit
git log -1
```

## Step 4: Push Configuration & Remote Tracking
Configure your branch to push exclusively to your fork (`origin`) while tracking it for a future Pull Request.

```bash
# Push the new branch to your fork and set up the upstream tracking link
git push -u origin feature/feishu-multi-bot-binding

# For all subsequent commits on this branch, you only need to run:
# git push
```

## Step 5: Commit Message Standards
DeerFlow strictly follows **Conventional Commits**. Use `feishu` or `multi-bot` as your commit scopes. Ensure code is formatted using `ruff` (Python) and `Prettier` (Frontend/Docs) before committing.

**Valid Examples:**
* `feat(feishu): implement agent-specific binding for multiple bots`
* `refactor(gateway): update routing logic to support dynamic Feishu tokens`
* `fix(feishu): resolve event duplication in multi-channel webhook`
* `docs(feishu): add configuration guide for multi-bot setup`

## Step 6: Keeping the Feature Branch Updated (Rebasing)
If the official `upstream/main` updates while you are developing, **DO NOT use `git merge`**. Use `git rebase` to maintain a clean, linear history.

```bash
# 1. Fetch latest official changes
git fetch upstream

# 2. Rebase your feature branch on top of the latest main
git rebase upstream/main

# 3. If conflicts occur, resolve them in your IDE, then run:
# git add <resolved-files>
# git rebase --continue

# 4. Force push safely to your fork after rebasing
git push --force-with-lease origin feature/feishu-multi-bot-binding
```

## Step 7: Switching Contexts (Returning to Dev)
If you need to pause work on the Feishu feature and return to your default development environment without losing any progress:

```bash
# 1. Ensure your current Feishu changes are committed or stashed
git status

# 2. Switch back to your default dev branch
git checkout dev

# 3. (Optional) If you stashed unrelated changes in Step 2, you can restore them now
git stash pop
```

*Note: To resume work on the Feishu feature later, simply run `git checkout feature/feishu-multi-bot-binding`.*

## 💡 Best Practices for Isolation
To ensure a seamless Pull Request approval process:
1. **Strict Scope**: Only modify files directly related to the Feishu multi-bot routing (e.g., `gateway` routes, `feishu` channel adapters).
2. **Avoid Core File Pollution**: Do not modify core `Dockerfile`s, global middleware, or unrelated backend services unless absolutely necessary.
3. **Self-Review**: Before pushing, run `git diff upstream/main...HEAD` to verify that your branch *only* contains Feishu-related changes.