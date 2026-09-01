# Sphinx configuration for the ELMFIRE guide.
#
# Content is generated from the LaTeX sources by scripts/tex2rst.py; this file
# and everything else in sphinx/ is hand-maintained. Carried over from the
# original docs/archive/conf.py, with additions for math and bibliography.

project = "ELMFIRE"
copyright = "2026, Cloudfire Inc."
author = "Cloudfire Inc."
release = "1.1"

extensions = [
    "sphinx_copybutton",
    "sphinx.ext.mathjax",      # the guide is math-heavy; RTD theme needs this
    "sphinxcontrib.bibtex",    # references.bib, via :cite: roles
]

bibtex_bibfiles = ["references.bib"]
bibtex_default_style = "plain"

templates_path = ["_templates"]
# _assets holds the downloadable PDF; :download: copies it into _downloads,
# so it must not also be picked up as source or static content.
exclude_patterns = ["_build", "_extra"]

# Publishes the guide at a stable https://elmfire.io/ELMFIRE_Guide.pdf, which
# is what the elmfire README links to. :download: would content-hash the path.
html_extra_path = ["_extra"]

numfig = True                  # "Fig. 3" style captions, as in the PDF
math_number_all = False

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_title = "ELMFIRE User Guide"
html_theme_options = {
    "navigation_depth": 3,
    "collapse_navigation": False,
}

# ~50 references.bib entries lack a required field (journal, institution, ...).
# They still render; the warnings only drown out real problems and would make
# build.sh --strict useless. scripts/bibcheck.py lists them instead, into
# build/bib_incomplete.txt.
suppress_warnings = ["bibtex.missing_field"]

# Surface broken :ref: targets as warnings so build.sh --strict can fail on them.
nitpicky = False
