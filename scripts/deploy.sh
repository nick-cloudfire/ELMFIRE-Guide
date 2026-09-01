#!/usr/bin/env bash
# Publish the built site to the elmfire.io docroot.
#
#   ./scripts/deploy.sh                  dry run - show what would change
#   ./scripts/deploy.sh --apply          back up the docroot, then publish
#   ./scripts/deploy.sh --apply --host user@elmfire.io   publish over ssh
#
# Replaces the old docs/archive/build.sh, which ran `sphinx-build -a` straight
# into /var/www/html: that left no backup and no way to preview before going
# live. Here the build is verified first, the docroot is snapshotted, and the
# default mode changes nothing.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HTML="$ROOT/build/html"
DOCROOT="${DOCROOT:-/var/www/html}"
# Backups default to beside the docroot, but that usually needs root. Point
# them at a directory the deploying user owns and no escalation is required,
# which is what makes unattended deploys work.
BACKUP_DIR="${BACKUP_DIR:-}"
KEEP_BACKUPS="${KEEP_BACKUPS:-5}"
HOST=""
APPLY=0
STAMP="$(date +%Y%m%d-%H%M%S)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)   APPLY=1; shift ;;
        --host)    HOST="$2"; shift 2 ;;
        --docroot) DOCROOT="$2"; shift 2 ;;
        --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
        --keep)    KEEP_BACKUPS="$2"; shift 2 ;;
        *) echo "usage: $0 [--apply] [--host user@server] [--docroot DIR]" \
                "[--backup-dir DIR] [--keep N]" >&2; exit 2 ;;
    esac
done

[[ -f "$HTML/index.html" ]] || { echo "No build found. Run ./scripts/build.sh first." >&2; exit 1; }

# Check before any output that suggests work is under way. With --host, rsync
# must be present on the server too -- it is invoked at both ends.
command -v rsync >/dev/null || {
    echo "rsync not found.  sudo apt-get install -y rsync" >&2
    exit 1
}

# A build that lost its stylesheets or search index is worse than no deploy.
for required in index.html searchindex.js objects.inv _static; do
    [[ -e "$HTML/$required" ]] || { echo "Build looks incomplete: missing $required" >&2; exit 1; }
done
# Belt and braces: build.sh clears its output dir, but if anything ever leaves
# internal artefacts behind we must not publish them.
for junk in .doctrees .buildinfo/../.doctrees; do
    [[ -e "$HTML/$junk" ]] && {
        echo "Refusing to deploy: $junk is present in the build output." >&2
        echo "Re-run ./scripts/build.sh (it clears build/html first)." >&2
        exit 1
    }
done
if [[ "$(find "$HTML" -name 'ELMFIRE_Guide.pdf' | wc -l)" -gt 1 ]]; then
    echo "Refusing to deploy: the guide PDF appears more than once." >&2
    echo "Stale output -- re-run ./scripts/build.sh." >&2
    exit 1
fi

echo "Build OK: $(find "$HTML" -name '*.html' | wc -l) pages, $(du -sh "$HTML" | cut -f1)"

STAMP="$(date +%Y%m%d-%H%M%S)"
# --delete replaces the whole docroot, which is the point: the site structure
# is the file layout. But the docroot may also hold things the web server owns
# rather than Sphinx -- certbot's ACME challenge dir above all, whose removal
# breaks TLS renewal silently, weeks later. Keep those.
KEEP=(/.well-known/ /.htaccess /robots.txt /favicon.ico /.git/)
RSYNC=(rsync -a --delete --human-readable --itemize-changes)
for path in "${KEEP[@]}"; do RSYNC+=(--exclude="$path"); done
echo "Preserving in docroot: ${KEEP[*]}"
[[ "$APPLY" == 1 ]] || RSYNC+=(--dry-run)

# Only escalate when actually writing, and only if it is actually needed.
# The backup is created *beside* the docroot, so the parent directory must be
# writable too -- /var/www/html is often writable when /var/www is not.
: "${BACKUP_DIR:=$(dirname "$DOCROOT")}"
BACKUP="$BACKUP_DIR/$(basename "$DOCROOT").bak-$STAMP"

SUDO=()
if [[ "$APPLY" == 1 && -z "$HOST" ]] \
   && { [[ ! -w "$DOCROOT" ]] || [[ ! -w "$BACKUP_DIR" ]]; }; then
    SUDO=(sudo)
fi

if [[ -n "$HOST" ]]; then
    if [[ "$APPLY" == 1 ]]; then
        echo "==> Backing up $HOST:$DOCROOT to $BACKUP"
        ssh "$HOST" "sudo cp -a '$DOCROOT' '$BACKUP'"
    fi
    echo "==> Syncing to $HOST:$DOCROOT"
    "${RSYNC[@]}" --rsync-path="sudo rsync" "$HTML/" "$HOST:$DOCROOT/"
else
    if [[ "$APPLY" == 1 ]]; then
        echo "==> Backing up $DOCROOT to $BACKUP"
        "${SUDO[@]}" mkdir -p "$BACKUP_DIR"
        "${SUDO[@]}" cp -a "$DOCROOT" "$BACKUP"
    fi
    echo "==> Syncing to $DOCROOT"
    mkdir -p "$DOCROOT" 2>/dev/null || true
    "${SUDO[@]}" "${RSYNC[@]}" "$HTML/" "$DOCROOT/"
fi

if [[ "$APPLY" == 1 ]]; then
    echo
    echo "Published. Rollback:  rsync -a --delete $BACKUP/ $DOCROOT/"
    # Each deploy leaves a full copy behind; keep the most recent $KEEP_BACKUPS.
    if [[ -z "$HOST" && "$KEEP_BACKUPS" -gt 0 ]]; then
        mapfile -t old < <(find "$BACKUP_DIR" -maxdepth 1 -name "$(basename "$DOCROOT").bak-*" \
                           2>/dev/null | sort -r | tail -n "+$((KEEP_BACKUPS + 1))")
        for dir in "${old[@]:-}"; do
            [[ -n "$dir" ]] && { echo "Pruning old backup: $dir"; "${SUDO[@]}" rm -rf "$dir"; }
        done
    fi
    echo "Verify:               curl -sSI https://elmfire.io/ | head -1"
else
    echo
    echo "Dry run only - nothing changed. Re-run with --apply to publish."
fi
