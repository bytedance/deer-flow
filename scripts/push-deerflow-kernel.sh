#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
EXPORT_SCRIPT="$SCRIPT_DIR/export-deerflow-kernel.sh"
REMOTE_URL="${DEERFLOW_KERNEL_REMOTE_URL:-http://code.tiancloud.com:9002/xiaosi/deerflow-kernel}"
OUTPUT_DIR="${TMPDIR:-/tmp}/deerflow-kernel"
BRANCH="main"
COMMIT_MESSAGE="chore: export deerflow kernel"
SKIP_EXPORT=0
FORCE_EXPORT=0
MERGE_REMOTE_HISTORY=0

normalize_remote_url() {
    local url="$1"

    if [[ "$url" =~ ^https?:// ]] && [[ ! "$url" =~ \.git$ ]]; then
        url="${url}.git"
    fi

    printf '%s\n' "$url"
}

is_ssh_remote_url() {
    local url="$1"
    [[ "$url" =~ ^git@ ]] || [[ "$url" =~ ^ssh:// ]]
}

build_authenticated_remote_url() {
    local url="$1"
    local username="${DEERFLOW_KERNEL_GIT_USERNAME:-}"
    local password="${DEERFLOW_KERNEL_GIT_PASSWORD:-${DEERFLOW_KERNEL_GIT_TOKEN:-}}"

    if [[ -z "$username" || -z "$password" ]]; then
        printf '%s\n' "$url"
        return 0
    fi

    if [[ ! "$url" =~ ^https?:// ]]; then
        printf '%s\n' "$url"
        return 0
    fi

    local encoded_username encoded_password
    encoded_username="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$username")"
    encoded_password="$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$password")"
    printf '%s\n' "${url/\/\//\/\/$encoded_username:$encoded_password@}"
}

usage() {
    cat <<'EOF'
Usage: push-deerflow-kernel.sh [options]

Export the standalone deerflow-kernel repository and push it to a remote Git
repository in non-interactive mode.

Options:
  --output DIR         Export destination. Default: ${TMPDIR:-/tmp}/deerflow-kernel
  --remote-url URL     Git remote URL. Default: http://code.tiancloud.com:9002/xiaosi/deerflow-kernel
  --branch NAME        Branch to push. Default: main
  --message TEXT       Commit message. Default: chore: export deerflow kernel
  --skip-export        Do not re-run the export step
  --force-export       Recreate the export directory before push
    --merge-remote-history
                                            If push is rejected (non-fast-forward), fetch and merge
                                            remote branch history, then retry push.
  -h, --help           Show this help message

Environment:
  GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL can be set to control the commit identity.
  DEERFLOW_KERNEL_REMOTE_URL can override the default remote URL.
    DEERFLOW_KERNEL_GIT_USERNAME and DEERFLOW_KERNEL_GIT_PASSWORD (or
    DEERFLOW_KERNEL_GIT_TOKEN) can be set for non-interactive HTTP Basic Auth.
    DEERFLOW_KERNEL_SSH_ALLOW_INTERACTIVE=1 can be set to allow interactive
    SSH auth (for passphrase-protected private keys).
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --remote-url)
            REMOTE_URL="$2"
            shift 2
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        --message)
            COMMIT_MESSAGE="$2"
            shift 2
            ;;
        --skip-export)
            SKIP_EXPORT=1
            shift
            ;;
        --force-export)
            FORCE_EXPORT=1
            shift
            ;;
        --merge-remote-history)
            MERGE_REMOTE_HISTORY=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ "$SKIP_EXPORT" != "1" ]]; then
    export_args=(--output "$OUTPUT_DIR")
    if [[ "$FORCE_EXPORT" == "1" ]]; then
        export_args+=(--force)
    fi
    "$EXPORT_SCRIPT" "${export_args[@]}"
fi

if [[ ! -d "$OUTPUT_DIR" ]]; then
    echo "Export directory not found: $OUTPUT_DIR" >&2
    exit 1
fi

if [[ ! -f "$OUTPUT_DIR/pyproject.toml" ]]; then
    echo "Export directory is missing pyproject.toml: $OUTPUT_DIR" >&2
    exit 1
fi

REMOTE_URL="$(normalize_remote_url "$REMOTE_URL")"
AUTH_REMOTE_URL="$(build_authenticated_remote_url "$REMOTE_URL")"

GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-$(git -C "$REPO_ROOT" config user.name || true)}"
GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-$(git -C "$REPO_ROOT" config user.email || true)}"

if [[ -z "$GIT_AUTHOR_NAME" || -z "$GIT_AUTHOR_EMAIL" ]]; then
    echo "Git author identity is not configured." >&2
    echo "Set GIT_AUTHOR_NAME and GIT_AUTHOR_EMAIL before running this script." >&2
    exit 1
fi

export GIT_AUTHOR_NAME
export GIT_AUTHOR_EMAIL
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

if [[ ! -d "$OUTPUT_DIR/.git" ]]; then
    git -C "$OUTPUT_DIR" init -b "$BRANCH"
fi

git -C "$OUTPUT_DIR" remote remove origin >/dev/null 2>&1 || true
git -C "$OUTPUT_DIR" remote add origin "$AUTH_REMOTE_URL"

git -C "$OUTPUT_DIR" add .

if git -C "$OUTPUT_DIR" diff --cached --quiet; then
    echo "No changes to commit in $OUTPUT_DIR"
else
    git -C "$OUTPUT_DIR" commit -m "$COMMIT_MESSAGE"
fi

git_remote_probe_cmd=(git -C "$OUTPUT_DIR" ls-remote "$AUTH_REMOTE_URL")
git_push_cmd=(git -C "$OUTPUT_DIR" push --set-upstream origin "$BRANCH")

if is_ssh_remote_url "$AUTH_REMOTE_URL"; then
    ssh_allow_interactive="${DEERFLOW_KERNEL_SSH_ALLOW_INTERACTIVE:-0}"
    if [[ "$ssh_allow_interactive" == "1" ]]; then
        ssh_opts='ssh -o StrictHostKeyChecking=accept-new'
        git_remote_probe_cmd=(env GIT_SSH_COMMAND="$ssh_opts" "${git_remote_probe_cmd[@]}")
        git_push_cmd=(env GIT_SSH_COMMAND="$ssh_opts" "${git_push_cmd[@]}")
    else
        ssh_non_interactive_opts='ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new'
        git_remote_probe_cmd=(env GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="$ssh_non_interactive_opts" "${git_remote_probe_cmd[@]}")
        git_push_cmd=(env GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="$ssh_non_interactive_opts" "${git_push_cmd[@]}")
    fi
else
    git_remote_probe_cmd=(env GIT_TERMINAL_PROMPT=0 "${git_remote_probe_cmd[@]}")
    git_push_cmd=(env GIT_TERMINAL_PROMPT=0 "${git_push_cmd[@]}")
fi

resolve_merge_conflicts_if_safe() {
    local conflict_files
    conflict_files="$(git -C "$OUTPUT_DIR" diff --name-only --diff-filter=U)"

    if [[ "$conflict_files" == "README.md" ]]; then
        git -C "$OUTPUT_DIR" checkout --ours README.md
        git -C "$OUTPUT_DIR" add README.md
        git -C "$OUTPUT_DIR" commit -m "chore: merge remote $BRANCH before kernel export push"
        return 0
    fi

    if [[ -n "$conflict_files" ]]; then
        echo "Merge conflicts require manual resolution:" >&2
        echo "$conflict_files" >&2
    else
        echo "Merge failed without tracked conflict files. Resolve manually in $OUTPUT_DIR." >&2
    fi
    return 1
}

merge_remote_history_and_retry_push() {
    echo "Push was rejected. Attempting to merge remote history from origin/$BRANCH..."
    git -C "$OUTPUT_DIR" fetch origin "$BRANCH"

    if ! git -C "$OUTPUT_DIR" merge --allow-unrelated-histories --no-edit "origin/$BRANCH"; then
        if ! resolve_merge_conflicts_if_safe; then
            return 1
        fi
    fi

    "${git_push_cmd[@]}"
}

if ! "${git_remote_probe_cmd[@]}" >/dev/null 2>&1; then
    echo "Remote is not reachable in non-interactive mode: $REMOTE_URL" >&2
    if is_ssh_remote_url "$AUTH_REMOTE_URL"; then
        echo "Check SSH key auth: ssh -T git@code.tiancloud.com" >&2
        echo "If your key is passphrase-protected, re-run with DEERFLOW_KERNEL_SSH_ALLOW_INTERACTIVE=1." >&2
    else
        echo "Check network connectivity or provide DEERFLOW_KERNEL_GIT_USERNAME plus DEERFLOW_KERNEL_GIT_PASSWORD/DEERFLOW_KERNEL_GIT_TOKEN." >&2
    fi
    exit 1
fi

if ! "${git_push_cmd[@]}"; then
    if [[ "$MERGE_REMOTE_HISTORY" == "1" ]]; then
        merge_remote_history_and_retry_push
    else
        echo "Push failed. Re-run with --merge-remote-history to auto-merge remote history and retry." >&2
        exit 1
    fi
fi

echo "Push completed: $REMOTE_URL ($BRANCH)"