#!/bin/bash
set -e

DATE=$(date +%Y%m%d-%H%M)
BACKUP_BRANCH="backup/pre-sync-$DATE"
BACKUP_TAG="pre-sync-$DATE"

echo "=== DeerFlow Full Sync Workflow ==="
echo "Date: $DATE"
echo ""

# Step 1: Backup
echo "[1/8] Creating backup..."
git checkout dev
git checkout -b "$BACKUP_BRANCH"
git tag -a "$BACKUP_TAG" -m "Full backup before upstream sync"
git checkout dev
git stash push -m "Pre-sync stash" || true
echo "✓ Backup created: $BACKUP_BRANCH, $BACKUP_TAG"
echo ""

# Step 2: Update main from upstream
echo "[2/8] Updating main branch..."
git checkout main
git fetch upstream
git reset --hard upstream/main
echo "✓ Main branch updated"
echo ""

# Step 3: Merge into dev
echo "[3/8] Merging into dev branch..."
git checkout dev
git merge main --no-ff -X ours -m "sync: merge upstream changes $(date +%Y-%m-%d)"
echo "✓ Merged into dev"
echo ""

# Step 4: Verify
echo "[4/8] Verifying local configs..."
if grep -q "OPENCLI_" docker/docker-compose.yaml; then
    echo "✓ OpenCLI config intact"
else
    echo "⚠ Warning: OpenCLI config may have changed!"
fi
echo ""

# Step 5: Restore stash
echo "[5/8] Restoring stashed changes..."
git stash pop || true
echo "✓ Stash restored"
echo ""

# Step 6: Build test
echo "[6/8] Running build test..."
docker compose build --quiet
echo "✓ Build test passed"
echo ""

# Step 7: Push to origin
echo "[7/8] Pushing to origin..."
git push origin main --force-with-lease
git push origin dev --force-with-lease
git push origin --tags
echo "✓ Pushed to origin"
echo ""

# Step 8: Complete
echo "[8/8] Sync complete!"
echo ""
echo "Next steps:"
echo "  1. Run: docker compose up -d"
echo "  2. Verify services are working"
echo "  3. Cleanup old backups (optional):"
echo "     git branch -D $BACKUP_BRANCH"
echo "     git tag -d $BACKUP_TAG"
echo ""
