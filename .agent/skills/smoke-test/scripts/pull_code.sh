#!/usr/bin/env bash
set -e

echo "=========================================="
echo "  Pulling the Latest Code"
echo "=========================================="
echo ""

# Check whether the current directory is a Git repository
if [ ! -d ".git" ]; then
    echo "✗ The current directory is not a Git repository"
    exit 1
fi

# Check Git status
echo "Checking Git status..."
if git status --porcelain | grep -q .; then
    echo "⚠  Uncommitted changes detected:"
    git status --short
    echo ""
    echo "Please commit or stash your changes before continuing"
    echo "Options:"
    echo "  1. git add . && git commit -m 'Save changes'"
    echo "  2. git stash (stash changes and restore them later)"
    echo "  3. git reset --hard HEAD (discard local changes - use with caution)"
    exit 1
else
    echo "✓ Working tree is clean"
fi
echo ""

# Fetch remote updates
echo "Fetching remote updates..."
git fetch origin main
echo ""

# Pull the latest code
echo "Pulling the latest code..."
git pull origin main
echo ""

# Show the latest commit
echo "Latest commit:"
git log -1 --oneline
echo ""

echo "=========================================="
echo "  Code Update Complete"
echo "=========================================="
