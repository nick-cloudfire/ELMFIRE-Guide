#!/usr/bin/env python3
"""Validate the rendered maths in build/html.

Sphinx and docutils happily emit LaTeX that MathJax then refuses in the
browser, so a clean sphinx-build says nothing about whether the equations
render. Two such failures have already shipped from this pipeline:

  * blank lines inside `.. math::` split one equation into fragments, so
    \\begin{cases} closed with \\end{split}
  * \\begin{align} nested inside the \\begin{split} Sphinx adds is illegal,
    giving "Erroneous nesting of equation structures"

Both are structural and cheap to detect, which is what this does.
"""

import collections
import glob
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "build" / "html"

# Environments that are only legal at the top level of display maths. Sphinx
# wraps every equation in \begin{split}, so these must never appear.
TOPLEVEL = {"align", "gather", "eqnarray", "flalign", "alignat", "multline",
            "equation"}


def equations():
    """Yield (page, kind, tex) for every equation MathJax will be handed."""
    for path in sorted(glob.glob(str(HTML / "*.html"))):
        page, text = Path(path).name, Path(path).read_text(errors="replace")
        for kind, pattern in (("display", r"\\\[(.+?)\\\]"),
                              ("inline", r"\\\((.+?)\\\)")):
            for m in re.finditer(pattern, text, re.S):
                yield page, kind, html.unescape(m.group(1))


def check(tex):
    """Return a list of problem descriptions for one equation."""
    found, stack = [], []
    for begin_end, name in re.findall(r"\\(begin|end)\{(\w+)\*?\}", tex):
        if begin_end == "begin":
            if stack and name in TOPLEVEL:
                found.append(f"{name} nested inside {stack[-1]} (top-level only)")
            stack.append(name)
        elif not stack or stack[-1] != name:
            found.append(f"\\end{{{name}}} does not match \\begin{{{stack[-1]}}}"
                         if stack else f"stray \\end{{{name}}}")
        else:
            stack.pop()
    if stack:
        found.append(f"unclosed \\begin{{{stack[-1]}}}")
    if len(re.findall(r"\\left(?![a-zA-Z])", tex)) != len(re.findall(r"\\right(?![a-zA-Z])", tex)):
        found.append("unbalanced \\left / \\right")
    if tex.count("{") != tex.count("}"):
        found.append("unbalanced braces")
    return found


def main():
    if not HTML.exists():
        sys.exit("no build/html - run scripts/build.sh first")

    counts, problems = collections.Counter(), []
    for page, kind, tex in equations():
        counts[kind] += 1
        for problem in check(tex):
            problems.append((page, problem, re.sub(r"\s+", " ", tex)[:100]))

    print(f"  {counts['display']} display + {counts['inline']} inline equations checked"
          + (f", {len(problems)} PROBLEMS" if problems else ", all valid"))
    for page, problem, snippet in problems:
        print(f"    [{page}] {problem}\n        {snippet}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
