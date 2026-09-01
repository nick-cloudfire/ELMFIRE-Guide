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
HOST=""
APPLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --apply)   APPLY=1; shift ;;
        --host)    HOST="$2"; shift 2 ;;
        --docroot) DOCROOT="$2"; shift 2 ;;
        *) echo "usage: $0 [--apply] [--host user@server] [--docroot /var/www/html]" >&2; exit 2 ;;
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

# Only escalate when actually writing, and only if the docroot needs it.
SUDO=()
if [[ "$APPLY" == 1 && -z "$HOST" && ! -w "$DOCROOT" ]]; then
    SUDO=(sudo)
fi

if [[ -n "$HOST" ]]; then
    if [[ "$APPLY" == 1 ]]; then
        echo "==> Backing up $HOST:$DOCROOT to $DOCROOT.bak-$STAMP"
        ssh "$HOST" "sudo cp -a '$DOCROOT' '$DOCROOT.bak-$STAMP'"
    fi
    echo "==> Syncing to $HOST:$DOCROOT"
    "${RSYNC[@]}" --rsync-path="sudo rsync" "$HTML/" "$HOST:$DOCROOT/"
else
    if [[ "$APPLY" == 1 ]]; then
        echo "==> Backing up $DOCROOT to $DOCROOT.bak-$STAMP"
        "${SUDO[@]}" cp -a "$DOCROOT" "$DOCROOT.bak-$STAMP"
    fi
    echo "==> Syncing to $DOCROOT"
    mkdir -p "$DOCROOT" 2>/dev/null || true
    "${SUDO[@]}" "${RSYNC[@]}" "$HTML/" "$DOCROOT/"
fi

if [[ "$APPLY" == 1 ]]; then
    echo
    echo "Published. Rollback:  sudo rsync -a --delete $DOCROOT.bak-$STAMP/ $DOCROOT/"
    echo "Verify:               curl -sSI https://elmfire.io/ | head -1"
else
    echo
    echo "Dry run only - nothing changed. Re-run with --apply to publish."
fi
