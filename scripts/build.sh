#!/usr/bin/env bash
# Build the ELMFIRE documentation site from the LaTeX sources.
#
#   ./scripts/build.sh            build HTML into build/html
#   ./scripts/build.sh --serve    build, then preview on http://localhost:8000
#   ./scripts/build.sh --strict   fail the build on any Sphinx warning
#
# Requires the venv created by scripts/setup.sh (or a system sphinx + pandoc).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build"
DOCS="$BUILD/docs"
HTML="$BUILD/html"

# Prefer the project venv, fall back to whatever is on PATH.
if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PY="$ROOT/.venv/bin/python"
    export PATH="$ROOT/.venv/bin:$PATH"
else
    PY="$(command -v python3)"
fi
command -v pandoc >/dev/null || { echo "pandoc not found - run scripts/setup.sh" >&2; exit 1; }

# -a -E: the RST tree is regenerated from scratch on every run, so a cached
# environment can leave stale pages and stale search-index terms behind.
SPHINX_ARGS=(-b html -a -E -d "$BUILD/doctrees")
SERVE=0
for arg in "$@"; do
    case "$arg" in
        --strict) SPHINX_ARGS+=(-W --keep-going -n) ;;
        --serve)  SERVE=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

echo "==> Converting LaTeX to reStructuredText"
"$PY" "$ROOT/scripts/tex2rst.py"
"$PY" "$ROOT/scripts/tables2csv.py"
"$PY" "$ROOT/scripts/bibcheck.py"

echo "==> Staging figures"
mkdir -p "$DOCS/images"
cp "$ROOT"/figs/*.png "$ROOT"/figs/*.jpg "$DOCS/images/" 2>/dev/null || true
# Site furniture that lives outside figs/ (e.g. the index hero image).
cp -r "$ROOT"/sphinx/images/. "$DOCS/images/" 2>/dev/null || true
# HTML cannot display PDF figures; rasterise any that exist.
shopt -s nullglob
for pdf in "$ROOT"/figs/*.pdf; do
    base="$(basename "${pdf%.pdf}")"
    if command -v pdftoppm >/dev/null; then
        pdftoppm -png -r 150 -singlefile "$pdf" "$DOCS/images/$base"
    else
        echo "    WARNING: pdftoppm missing, $base.pdf not converted (poppler-utils)" >&2
    fi
done
shopt -u nullglob

echo "==> Staging Sphinx project"
cp "$ROOT"/sphinx/*.py "$ROOT"/sphinx/*.rst "$ROOT"/sphinx/requirements.txt "$DOCS/"
cp "$ROOT/references.bib" "$DOCS/"
mkdir -p "$DOCS/_static" "$DOCS/_templates" "$DOCS/_extra"
cp -r "$ROOT"/sphinx/_static/. "$DOCS/_static/" 2>/dev/null || true
# Ship the PDF alongside the site so index.rst can link to it.
# Ship the compiled guide alongside the site when one is available. Build it
# here if latexmk is installed, otherwise reuse a pre-built copy.
if command -v latexmk >/dev/null; then
    latexmk -pdf -quiet -outdir="$BUILD" "$ROOT/main.tex" >/dev/null 2>&1 \
        && cp "$BUILD/main.pdf" "$DOCS/_extra/ELMFIRE_Guide.pdf" \
        || echo "    WARNING: latexmk failed; skipping PDF" >&2
fi
if [[ ! -f "$DOCS/_extra/ELMFIRE_Guide.pdf" ]]; then
    for pdf in "$ROOT/ELMFIRE_Guide.pdf" "${ELMFIRE_BASE_DIR:-/nonexistent}/docs/ELMFIRE_Guide.pdf"; do
        [[ -f "$pdf" ]] && cp "$pdf" "$DOCS/_extra/ELMFIRE_Guide.pdf" && break
    done
fi
# No PDF anywhere: strip the download link so the build stays warning-clean.
if [[ ! -f "$DOCS/_extra/ELMFIRE_Guide.pdf" ]]; then
    echo "    note: no ELMFIRE_Guide.pdf found; removing the download link"
    sed -i '/ELMFIRE_Guide.pdf/d; /also available as a single/d' "$DOCS/index.rst"
fi

# Hand-written overrides win over anything generated above.
if compgen -G "$ROOT/sphinx/overlay/*" >/dev/null; then
    echo "==> Applying overlay/"
    cp -r "$ROOT"/sphinx/overlay/. "$DOCS/"
fi

# sphinx-build only writes files, it never removes ones it no longer emits.
# Without this, output from a previous build (stale pages, an old doctree
# cache, a PDF that has since moved) accumulates and gets deployed.
echo "==> Clearing previous output"
rm -rf "$HTML"

echo "==> Running sphinx-build"
sphinx-build "${SPHINX_ARGS[@]}" "$DOCS" "$HTML"

# A clean sphinx-build does not mean the maths renders; check it explicitly.
echo "==> Validating rendered maths"
if ! "$PY" "$ROOT/scripts/mathcheck.py"; then
    echo "Maths validation failed - the equations above will not render." >&2
    exit 1
fi

echo
echo "Site built: $HTML"
echo "Report:     $BUILD/conversion_report.json"

if [[ "$SERVE" == 1 ]]; then
    echo "Serving on http://localhost:8000 (Ctrl-C to stop)"
    "$PY" -m http.server 8000 --directory "$HTML"
fi
