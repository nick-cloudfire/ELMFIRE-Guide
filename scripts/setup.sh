#!/usr/bin/env bash
# One-time toolchain setup. Creates .venv/ with Sphinx and a bundled pandoc,
# so no root access or system package installs are required.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install --upgrade pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/sphinx/requirements.txt" pypandoc_binary

# pypandoc ships a pandoc binary; expose it on PATH for build.sh.
PANDOC="$("$ROOT/.venv/bin/python" -c 'import pypandoc,os;print(pypandoc.get_pandoc_path())')"
ln -sf "$PANDOC" "$ROOT/.venv/bin/pandoc"

echo "Toolchain ready. Next: ./scripts/build.sh --serve"
echo "Note: PDF figures also need poppler-utils (sudo apt-get install poppler-utils)"
