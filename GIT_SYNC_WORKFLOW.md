# Git Sync Workflow: Synchronize Upstream Changes While Preserving Local Modifications
This workflow ensures you can safely pull the latest updates from the official upstream repository without losing your local customizations, with built-in backup and rollback mechanisms.

---

## Prerequisites
First verify you have the upstream remote configured:
```bash
# List existing remotes
git remote -v

# If upstream is missing, add it (replace with official repo URL)
git remote add upstream https://github.com/official-owner/deer-flow.git
```

---

## 1. Pre-Sync Backup Procedures
Always backup local changes before syncing to avoid data loss:

### Option A: For uncommitted local modifications (use `git stash`)
```bash
# Stash all uncommitted changes with a descriptive message
git stash push -m "Pre-sync backup: $(date +%Y-%m-%d) - local customizations"

# Verify stash was created
git stash list
```

### Option B: For committed local changes (create a backup branch)
```bash
# Create a timestamped backup branch of your current state
git checkout -b backup/pre-sync-$(date +%Y%m%d-%H%M)

# Switch back to your working branch (e.g. main/dev)
git checkout main
```

### Full Safety Backup (optional but recommended)
```bash
# Create a tagged snapshot of your current state for emergency rollback
git tag -a pre-sync-$(date +%Y%m%d-%H%M) -m "Full backup before upstream sync"
```

---

## 2. Fetch and Sync Operations
Choose one of the following sync strategies based on your use case:

### Step 1: Fetch latest upstream changes
```bash
# Fetch all latest changes from upstream without modifying local files
git fetch upstream

# Verify fetched branches
git branch -r
```

### Option A: Merge Upstream (preserves commit history, recommended for shared branches)
Best for team-shared branches where commit history integrity is important:
```bash
# Merge latest upstream changes into your current branch
git merge upstream/main  # Replace main with your target branch (e.g. dev)
```

### Option B: Rebase Upstream (clean linear history, recommended for personal feature branches)
Best for private feature branches to keep commit history clean:
```bash
# Rebase your local changes on top of latest upstream
git rebase upstream/main  # Replace main with your target branch
```

---

## 3. Conflict Resolution Protocols
If Git reports merge/rebase conflicts, follow this process:

### Step 1: Identify conflicted files
```bash
# List all files with conflicts
git status
```
Conflicted files will be marked as `both modified`.

### Step 2: Resolve conflicts
1. Open each conflicted file in your IDE
2. Look for conflict markers:
   ```
   <<<<<<< HEAD
   Your local changes
   =======
   Upstream changes
   >>>>>>> upstream/main
   ```
3. Edit the file to keep the correct combination of changes
4. Remove all conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`)

### Step 3: Complete the sync operation
For merge conflicts:
```bash
# Mark resolved files
git add <conflicted-file-path>

# Finish merge
git merge --continue
```

For rebase conflicts:
```bash
# Mark resolved files
git add <conflicted-file-path>

# Continue rebase
git rebase --continue

# Repeat until all conflicts are resolved
```

### Conflict Resolution Best Practices
- If unsure about a change, contact the author of the upstream commit
- Prioritize critical local customizations (e.g. Docker configs, opencli integration)
- Test each conflict resolution immediately after applying

---

## 4. Post-Sync Verification Steps
Confirm your local modifications are intact and upstream changes are applied correctly:

### Step 1: Restore stashed changes (if you used Option A backup)
```bash
# Reapply your stashed local changes
git stash pop stash@{0}  # Or use git stash apply to keep the stash
```

### Step 2: Verify local changes exist
```bash
# Check your modified files are still present
git status

# Diff specific critical files to confirm no changes were lost
git diff path/to/your/custom/file
```

### Step 3: Verify upstream changes are applied
```bash
# Check commit history to confirm latest upstream commits are present
git log --oneline -n 20

# Compare with upstream to ensure you are up to date
git diff upstream/main
```

---

## 5. Testing Requirements
Validate both upstream updates and local changes work together:

### 1. Build Validation
```bash
# Run project build to ensure no compilation errors
npm run build  # Or equivalent command for your project
```

### 2. Critical Function Testing
- Verify DeerFlow core services start correctly: `docker compose up`
- Verify your local customizations work (e.g. opencli integration, custom skills)
- Test upstream new features/ bug fixes as per their release notes

### 3. Regression Testing
- Run existing test suite: `npm test`
- Verify no regression in previously working functionality

---

## 6. Rollback Procedures (If Sync Fails)
If you encounter unsolvable conflicts or broken functionality, roll back to your pre-sync state:

### Rollback from stash backup
```bash
# Abort in-progress merge/rebase
git merge --abort  # For merge failures
git rebase --abort # For rebase failures

# Reapply your stashed changes
git stash pop stash@{0}
```

### Rollback from backup branch
```bash
# Reset your current branch to the backup state
git reset --hard backup/pre-sync-YYYYMMDD-HHMM

# Delete the failed sync state
git branch -D backup/pre-sync-YYYYMMDD-HHMM # Optional cleanup
```

### Rollback from tag backup
```bash
# Reset to your pre-sync tagged snapshot
git reset --hard pre-sync-YYYYMMDD-HHMM
```

---

## 7. Branch Management Best Practices
1. Never work directly on the `main`/`master` branch - always use feature branches for local customizations
2. Sync with upstream at least once per week to avoid large divergences that cause complex conflicts
3. Keep local commits small and atomic to simplify conflict resolution
4. Delete old backup branches/tags after successful sync to keep repository clean
5. Use `git pull --ff-only` for regular pulls to avoid accidental merge commits

---

## Complete End-to-End Workflow Example
```bash
# 1. Backup
git stash push -m "Pre-sync: opencli config changes"
git tag pre-sync-20240501-1430

# 2. Fetch upstream
git fetch upstream

# 3. Merge
git merge upstream/main

# 4. Resolve conflicts (if any)
git add docker-compose.yaml
git merge --continue

# 5. Restore local changes
git stash pop

# 6. Verify and test
git status
docker compose up --build
```

5. Use `git pull --ff-only` for regular pulls to avoid accidental merge commits

---

## 8. Post-Sync Push to Personal Fork
After successful synchronization and testing, push the complete updated codebase to your personal GitHub fork:

### Step 1: Commit outstanding local changes
```bash
# Check for any uncommitted working changes
git status

# Add all modified files
git add .

# Commit with a clear descriptive message
git commit -m "Sync upstream changes $(date +%Y-%m-%d) + preserve local customizations: [list key changes e.g. opencli Docker config, custom skills]"
```

### Step 2: Push to your personal fork
```bash
# Push to your origin remote (your personal fork)
git push origin main  # Replace main with your working branch name
```

### Step 3: Verify on GitHub
1. Open your personal fork repository in a browser
2. Navigate to the Commits page
3. Confirm both the latest upstream commits and your local custom commits appear correctly in the history
4. Verify no missing changes or unexpected conflicts in the pushed code

---

## Complete End-to-End Workflow Example
```
# 6. Verify and test
git status
docker compose up --build

# 7. Commit and push to personal fork
git add .
git commit -m "Sync upstream 2024-05-01 + preserve opencli integration customizations"
git push origin main

# 8. Verify on GitHub: check commits page in your personal fork
```