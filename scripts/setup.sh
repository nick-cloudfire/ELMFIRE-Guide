#!/usr/bin/env bash
# One-time toolchain setup. Creates .venv/ with Sphinx and a bundled pandoc,
# so no root access is needed -- except on Debian/Ubuntu, which ships venv
# support in a separate package (checked for below).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }
PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

# Debian/Ubuntu omit ensurepip from the base python3 package, and `python3 -m
# venv` fails partway through, leaving an unusable .venv behind.
if ! python3 -c "import ensurepip" 2>/dev/null; then
    cat >&2 <<MSG
python3-venv is not installed, so a virtual environment cannot be created.

    sudo apt-get install -y python${PYVER}-venv

Then re-run this script.
MSG
    exit 1
fi

# A previous failed run leaves a broken .venv that would shadow a good one.
[[ -e "$ROOT/.venv" ]] && { echo "Removing existing $ROOT/.venv"; rm -rf "$ROOT/.venv"; }

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install --upgrade pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/sphinx/requirements.txt" pypandoc_binary

# pypandoc ships a pandoc binary; expose it on PATH for build.sh.
PANDOC="$("$ROOT/.venv/bin/python" -c 'import pypandoc; print(pypandoc.get_pandoc_path())')"
ln -sf "$PANDOC" "$ROOT/.venv/bin/pandoc"
"$ROOT/.venv/bin/pandoc" --version | head -1

echo
echo "Toolchain ready. Next: ./scripts/build.sh --serve"

# Optional extras. Neither blocks a build; both change what the site contains.
command -v pdftoppm >/dev/null || \
    echo "  optional: sudo apt-get install -y poppler-utils   (renders the one PDF figure)"
command -v latexmk  >/dev/null || \
    echo "  optional: sudo apt-get install -y latexmk         (builds the downloadable PDF)"
