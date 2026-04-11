#!/bin/bash
# DeerFlow Upstream 同步自动化脚本

set -e

DATE=$(date +%Y%m%d-%H%M)
BACKUP_BRANCH="backup/pre-sync-$DATE"
SYNC_BRANCH="sync/upstream-$(date +%Y%m%d)"

echo "=== DeerFlow Upstream Sync ==="
echo "Date: $DATE"
echo ""

# Step 1: 备份
echo "[1/6] Creating backup..."
git checkout -b "$BACKUP_BRANCH"
git tag -a "pre-sync-$DATE" -m "Full backup before upstream sync"
git checkout main
echo "✓ Backup created: $BACKUP_BRANCH, pre-sync-$DATE"
echo ""

# Step 2: Fetch upstream
echo "[2/6] Fetching upstream changes..."
git fetch upstream
echo "✓ Upstream fetched"
echo ""

# Step 3: Sync
echo "[3/6] Syncing with upstream..."
git checkout -b "$SYNC_BRANCH"
git merge upstream/main -X ours
echo "✓ Sync completed"
echo ""

# Step 4: Verify
echo "[4/6] Verifying protected files..."
if grep -q "OPENCLI_" docker/docker-compose.yaml; then
    echo "✓ OpenCLI config intact"
else
    echo "⚠ Warning: OpenCLI config may have changed!"
fi
echo ""

# Step 5: Merge back to main
echo "[5/6] Merging to main..."
git checkout main
git merge "$SYNC_BRANCH" --no-ff -m "sync: merge upstream changes $(date +%Y-%m-%d)"
git branch -D "$SYNC_BRANCH"
echo "✓ Merged to main"
echo ""

# Step 6: Complete
echo "[6/6] Sync complete!"
echo ""
echo "To push to origin:"
echo "  git push origin main"
echo ""
echo "To update dev branch:"
echo "  git checkout dev && git merge main"
echo ""
