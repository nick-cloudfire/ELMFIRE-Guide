#!/usr/bin/env bash
# Unattended: pull, and if anything changed, rebuild and publish.
#
# Intended to run from a systemd timer or cron. Does nothing when the remote
# has not moved, so it is safe to run often.
#
#   ./scripts/autodeploy.sh              pull, build and deploy if changed
#   ./scripts/autodeploy.sh --force      rebuild and deploy even if unchanged
#   ./scripts/autodeploy.sh --dry-run    report what would happen, change nothing
#
# The site is only replaced if the build succeeds under --strict, so a broken
# commit on main leaves the previous site serving.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${LOG:-$ROOT/build/autodeploy.log}"
BRANCH="${BRANCH:-main}"
FORCE=0
DRY=0

for arg in "$@"; do
    case "$arg" in
        --force)   FORCE=1 ;;
        --dry-run) DRY=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { log "FAILED: $*"; exit 1; }

# One run at a time: a build plus rsync can outlast a short timer interval.
exec 9>"$ROOT/build/.autodeploy.lock"
flock -n 9 || { log "another run is in progress; skipping"; exit 0; }

cd "$ROOT"

git fetch --quiet origin "$BRANCH" || fail "git fetch"
local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse "origin/$BRANCH")"

if [[ "$local_rev" == "$remote_rev" && "$FORCE" == 0 ]]; then
    exit 0                              # nothing to do, and nothing to log
fi

if [[ "$local_rev" != "$remote_rev" ]]; then
    log "changes on origin/$BRANCH: ${local_rev:0:8} -> ${remote_rev:0:8}"
    git --no-pager log --oneline "$local_rev..$remote_rev" | sed 's/^/    /'
else
    log "no changes, but --force given"
fi

if [[ "$DRY" == 1 ]]; then
    log "dry run: stopping before pull"
    exit 0
fi

# --ff-only: never create a merge commit unattended. If the working tree has
# drifted, stop and let a human look rather than guessing.
git diff --quiet || fail "working tree has uncommitted changes"
git merge --ff-only "origin/$BRANCH" --quiet || fail "cannot fast-forward $BRANCH"

log "building"
if ! ./scripts/build.sh --strict; then
    fail "build failed - site left unchanged at the previous version"
fi

log "deploying"
if ! ./scripts/deploy.sh --apply; then
    fail "deploy failed"
fi

log "published $(git rev-parse --short HEAD)"
