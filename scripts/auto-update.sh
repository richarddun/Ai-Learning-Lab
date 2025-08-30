#!/usr/bin/env bash
set -euo pipefail

# Prevent overlapping runs
exec 9>/tmp/ai-lab-auto-update.lock
flock -n 9 || exit 0

# Resolve repo directory (defaults to this script's repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
BRANCH="${BRANCH:-main}"
SERVICE="${SERVICE:-ai-learning-lab.service}" # only used if you choose to restart

cd "$REPO_DIR"

# Skip if working tree has local changes
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "$(date -Is) Repo has local changes; skipping update."
  exit 0
fi

# Ensure correct branch is checked out
current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$BRANCH" ]; then
  git checkout "$BRANCH"
fi

# Fetch and compare
git fetch --prune origin
local="$(git rev-parse HEAD)"
remote="$(git rev-parse "origin/$BRANCH" || echo "")"
if [ -z "$remote" ]; then
  echo "$(date -Is) Could not resolve origin/$BRANCH; aborting."
  exit 1
fi

if [ "$local" = "$remote" ]; then
  echo "$(date -Is) Up to date ($BRANCH @ $local)."
  exit 0
fi

# Brief summary of incoming commits
git --no-pager log --oneline --decorate --graph --max-count=5 "$local..$remote" || true

# Fast-forward pull only
git pull --ff-only origin "$BRANCH"

# Optional: if requirements changed, try to install deps (best-effort)
if git diff --name-only "$local..HEAD" | grep -qE '(^|/)requirements\.txt$'; then
  if [ -f ./venv/bin/pip ]; then
    ./venv/bin/pip install -r requirements.txt || true
  elif command -v pip3 >/dev/null 2>&1; then
    pip3 install -r requirements.txt || true
  fi
fi

# Optional: restart if ever needed (commented out by default)
# systemctl --user restart "$SERVICE"
# or: sudo systemctl restart "$SERVICE"

echo "$(date -Is) Updated to $(git rev-parse --short HEAD) on $BRANCH."

