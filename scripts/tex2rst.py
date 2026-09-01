#!/usr/bin/env python3
"""Convert the ELMFIRE LaTeX guide into Sphinx reStructuredText.

LaTeX is the single source of truth. This script regenerates the RST tree
under build/docs/ on every run, so never hand-edit its output -- put manual
overrides in sphinx/overlay/, which build.sh copies over the generated tree.

Approach: pandoc handles prose, lists, inline math and tables well, but
mangles `figure` and `equation` environments into `raw:: latex` blocks and
loses their labels. So those two environments -- plus \\ref, \\cite and the
guide's local \\code/cfTable macros -- are extracted to opaque sentinels
before pandoc runs and re-emitted as proper Sphinx directives afterwards.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "docs"

# tex stem -> (output rst, chapter title). Mirrors the \chapter order in main.tex.
CHAPTERS = [
    ("computationalGuide",     "user_guide",   "Computational Guide"),
    ("mathematicalBackground", "tech_ref",     "Mathematical Background"),
    ("verification",           "verification", "Verification"),
    ("validation",             "validation",   "Validation"),
]

SECTION_CMD = re.compile(r"^\s*\\(sub)*section\*?\{(?P<title>.+?)\}\s*$")
LABEL_LINE = re.compile(r"^\s*\\label\{(?P<name>[^}]*)\}\s*$")
GRAPHIC = re.compile(r"\\includegraphics(?:\[(?P<opts>[^]]*)\])?\{(?P<path>[^}]+)\}")
# "Fig.~\ref{}" style lead-ins; :numref: renders its own "Fig. N".
NUMREF_LEAD = re.compile(r"\b(?:Fig(?:ure)?\.?|Tab(?:le)?\.?|Eq(?:uation)?\.?)\s*$", re.I)


def anchor(label: str) -> str:
    """Sphinx anchors cannot contain ':' -- fig:theta becomes fig-theta."""
    return label.replace(":", "-").replace("_", "-").lower()


def role_for(label: str) -> str:
    """Figures, tables and equations get numbered references; sections plain."""
    if label.startswith(("fig:", "tab:")):
        return "numref"
    if label.startswith("eq:"):
        return "eq"
    return "ref"


def read_tex(stem: str) -> str:
    """Read a chapter and inline any \\input{} it pulls in."""
    text = (ROOT / f"{stem}.tex").read_text(encoding="utf-8")

    def inline(m):
        target = ROOT / f"{m.group(1)}.tex"
        return target.read_text(encoding="utf-8") if target.exists() else ""

    return re.sub(r"^\s*\\input\{([^}]+)\}\s*$", inline, text, flags=re.M)


def match_brace(text: str, open_idx: int) -> int:
    """Index of the '}' closing the '{' at open_idx, honouring nesting."""
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "{" and text[i - 1] != "\\":
            depth += 1
        elif text[i] == "}" and text[i - 1] != "\\":
            depth -= 1
            if depth == 0:
                return i
    raise ValueError(f"unbalanced brace at {open_idx}")


def expand_macro(text: str, name: str, wrap: str) -> str:
    """Rewrite \\name{...} to wrap.format(body), tolerating nested braces."""
    out, i = [], 0
    needle = "\\" + name + "{"
    while (j := text.find(needle, i)) != -1:
        k = match_brace(text, j + len(needle) - 1)
        out.append(text[i:j])
        out.append(wrap.format(text[j + len(needle):k]))
        i = k + 1
    out.append(text[i:])
    return "".join(out)


def find_env(text: str, env: str):
    """Yield (start, end) spans of \\begin{env}...\\end{env}, nesting-aware."""
    begin, end = f"\\begin{{{env}}}", f"\\end{{{env}}}"
    i = 0
    while (start := text.find(begin, i)) != -1:
        depth, j = 1, start + len(begin)
        while depth and j < len(text):
            nb, ne = text.find(begin, j), text.find(end, j)
            if ne == -1:
                break
            if nb != -1 and nb < ne:
                depth, j = depth + 1, nb + len(begin)
            else:
                depth, j = depth - 1, ne + len(end)
        yield start, j
        i = j


def parse_width(opts: str) -> str | None:
    """LaTeX includegraphics options -> a Sphinx :width: value."""
    if not opts:
        return None
    if m := re.search(r"width\s*=\s*([\d.]+)\s*\\(?:text|line|column)width", opts):
        return f"{float(m.group(1)) * 100:g}%"
    if m := re.search(r"width\s*=\s*([\d.]+)\s*(cm|mm|in|pt)", opts):
        return f"{m.group(1)}{m.group(2)}"
    if m := re.search(r"scale\s*=\s*([\d.]+)", opts):
        return f"{float(m.group(1)) * 100:g}%"
    return None


def unwrap(text: str, name: str, nargs: int) -> str:
    r"""Replace \name{..}..{body} with body. pandoc drops the wrapped content
    of \resizebox/\scalebox outright, which silently deletes whole tables."""
    needle = "\\" + name
    while (j := text.find(needle)) != -1:
        k = j + len(needle)
        for _ in range(nargs - 1):            # skip the sizing arguments
            k = match_brace(text, text.index("{", k)) + 1
        open_idx = text.index("{", k)
        close = match_brace(text, open_idx)
        body = text[open_idx + 1:close].strip().rstrip("%")
        text = text[:j] + body + text[close + 1:]
    return text


def preprocess(text: str):
    """Strip what pandoc mishandles. Returns tex plus extracted metadata."""
    text = unwrap(text, "resizebox", 3)
    text = unwrap(text, "scalebox", 2)
    text = re.sub(r"\\(begin|end)\{adjustbox\}(\{[^}]*\})?", "", text)
    # Presentation-only table commands with no HTML equivalent.
    text = re.sub(r"\\(row|cell)color\{[^}]*\}", "", text)
    text = re.sub(r"\\renewcommand\{[^}]*\}\{[^}]*\}", "", text)
    # \code{x} is a local macro (\path|x|); \texttt survives pandoc as literal.
    text = expand_macro(text, "code", r"\texttt{{{0}}}")
    text = re.sub(r"\\path\|([^|]*)\|", r"\\texttt{\1}", text)

    # Layout-only wrappers with no HTML meaning.
    text = re.sub(r"\\(begin|end)\{landscape\}", "", text)
    text = re.sub(r"^\s*\\chapter\*?\{.*?\}\s*$", "", text, flags=re.M)
    text = re.sub(r"\\specialrule\{[^}]*\}\{[^}]*\}\{[^}]*\}", r"\\hline", text)

    # cfTable{caption}{label}{width} is a local wrapper around table+minipage.
    text = re.sub(r"\\begin\{cfTable\}\{(.*?)\}\{(.*?)\}\{.*?\}",
                  lambda m: "\\begin{table}\n\\caption{%s}\n\\label{%s}\n" % (m.group(1), m.group(2)),
                  text, flags=re.S)
    text = text.replace(r"\end{cfTable}", r"\end{table}")

    # A \label may sit on the same line as its heading; split those onto their
    # own line so the label pass below sees them uniformly. Brace-aware, since
    # titles contain nested groups such as \text{} inside math.
    def split_inline_labels(src: str) -> str:
        out, i = [], 0
        for m in re.finditer(r"\\(?:sub){0,2}(?:section|paragraph)\*?\{", src):
            if m.start() < i:
                continue
            close = match_brace(src, m.end() - 1)
            rest = src[close + 1:]
            if (lbl := re.match(r"[ \t]*(\\label\{[^}]*\})", rest)):
                out.append(src[i:close + 1] + "\n" + lbl.group(1))
                i = close + 1 + lbl.end()
        out.append(src[i:])
        return "".join(out)

    text = split_inline_labels(text)

    # Sentinels are opaque to pandoc and restored as Sphinx roles afterwards.
    refs, cites, figures, equations = [], [], [], []

    def ref(m):
        refs.append(m.group(1))
        return f" XREF{len(refs) - 1:04d}XREF "

    def cite(m):
        cites.append(m.group(1))
        return f" XCIT{len(cites) - 1:04d}XCIT "

    text = re.sub(r"\\(?:auto|c|C)?ref\{([^}]*)\}", ref, text)
    text = re.sub(r"\\cite[tp]?\{([^}]*)\}", cite, text)

    # -- figures: pandoc turns these into raw-latex containers, so do it here.
    for start, end in reversed(list(find_env(text, "figure"))):
        block = text[start:end]
        images = [(m.group("path"), parse_width(m.group("opts") or ""))
                  for m in GRAPHIC.finditer(block)]
        if not images:
            continue
        label = next((m.group(1) for m in re.finditer(r"\\label\{([^}]*)\}", block)), None)
        caption = None
        if (c := block.rfind("\\caption")) != -1:
            brace = block.find("{", c)
            caption = block[brace + 1:match_brace(block, brace)]
        figures.append({"images": images, "label": label, "caption": caption})
        text = text[:start] + f"\n\nXFIG{len(figures) - 1:04d}XFIG\n\n" + text[end:]
    figures.reverse()
    # Indices were assigned in reverse; renumber the sentinels to match.
    text = re.sub(r"XFIG(\d{4})XFIG",
                  lambda m: f"XFIG{len(figures) - 1 - int(m.group(1)):04d}XFIG", text)

    # -- labelled equations: needed so :eq: references resolve.
    for env in ("equation", "align", "gather"):
        for start, end in reversed(list(find_env(text, env))):
            block = text[start:end]
            if not (m := re.search(r"\\label\{([^}]*)\}", block)):
                continue
            body = re.sub(r"\\label\{[^}]*\}", "", block)
            body = re.sub(r"\\(begin|end)\{%s\*?\}" % env, "", body).strip()
            equations.append({"label": m.group(1), "body": body,
                              "env": env if env != "equation" else None})
            text = text[:start] + f"\n\nXEQN{len(equations) - 1:04d}XEQN\n\n" + text[end:]
    equations.reverse()
    text = re.sub(r"XEQN(\d{4})XEQN",
                  lambda m: f"XEQN{len(equations) - 1 - int(m.group(1)):04d}XEQN", text)

    # The guide sometimes uses \textbf{...} as a heading and hangs a \label on
    # it. Promote those to real subsubsections so the anchor has a title to
    # point at and the heading shows up in the sidebar.
    text = re.sub(r"^[ \t]*\\textbf\{([^}]+)\}[ \t]*\n([ \t]*\\label\{[^}]*\})",
                  r"\\subsubsection{\1}\n\2", text, flags=re.M)

    # -- labels inside table/center envs: pandoc drops them, so hoist each one
    #    to a sentinel paragraph immediately before the environment.
    anchors = []
    for env in ("table", "center"):
        for start, end in reversed(list(find_env(text, env))):
            block = text[start:end]
            if not (m := re.search(r"\\label\{([^}]*)\}", block)):
                continue
            anchors.append(m.group(1))
            block = block.replace(m.group(0), "", 1)
            text = text[:start] + f"\n\nXANC{len(anchors) - 1:04d}XANC\n\n" + block + text[end:]
    anchors.reverse()
    text = re.sub(r"XANC(\d{4})XANC",
                  lambda m: f"XANC{len(anchors) - 1 - int(m.group(1)):04d}XANC", text)

    # -- remaining labels belong to sections; record the title, drop the line.
    labels, lines, out = {}, text.split("\n"), []
    for n, line in enumerate(lines):
        m = LABEL_LINE.match(line)
        if not m:
            out.append(line)
            continue
        name = m.group("name")
        if name == "#2":                      # artefact of the cfTable definition
            continue
        prev = next((lines[p] for p in range(n - 1, -1, -1) if lines[p].strip()), "")
        if sec := SECTION_CMD.match(prev):
            labels[name] = {"kind": "section", "key": sec.group("title").strip()}
        else:
            labels[name] = {"kind": "manual", "key": None}

    for fig in figures:
        if fig["label"]:
            labels[fig["label"]] = {"kind": "figure", "key": fig["images"][0][0]}
    for eq in equations:
        labels[eq["label"]] = {"kind": "equation", "key": None}
    for name in anchors:
        labels[name] = {"kind": "anchor", "key": None}

    return "\n".join(out), labels, refs, cites, figures, equations, anchors


def pandoc(tex: str, to="rst", extra=()) -> str:
    r = subprocess.run(
        ["pandoc", "-f", "latex", "-t", to, "--wrap=none", *extra],
        input=tex, capture_output=True, text=True,
    )
    if r.returncode:
        sys.exit(f"pandoc failed: {r.stderr[:800]}")
    return r.stdout


def indent(text: str, pad="   ") -> str:
    return "\n".join(pad + l if l.strip() else "" for l in text.split("\n"))


def render_figure(fig) -> str:
    """Emit a Sphinx figure directive (or several, for subfigures)."""
    caption = ""
    if fig["caption"]:
        caption = pandoc(fig["caption"]).strip().replace("\n", " ")

    out = []
    if fig["label"]:
        out += [f".. _{anchor(fig['label'])}:", ""]
    for n, (path, width) in enumerate(fig["images"]):
        name = Path(path).name
        if name.lower().endswith(".pdf"):
            name = name[:-4] + ".png"        # rasterised by build.sh
        out.append(f".. figure:: images/{name}")
        if width:
            out.append(f"   :width: {width}")
        out.append("   :align: center")
        # Only the first image carries the caption; the rest are continuations.
        if caption and n == 0:
            out += ["", indent(caption)]
        out.append("")
    return "\n".join(out)


def render_equation(eq) -> str:
    body = eq["body"]
    if eq["env"]:                            # keep the environment, nestably
        env = NESTABLE.get(eq["env"], eq["env"])
        body = f"\\begin{{{env}}}\n{body}\n\\end{{{env}}}"
    return "\n".join([".. math::", f"   :label: {anchor(eq['label'])}", "", indent(body), ""])


UNDERLINES = ["=", "-", "~", "^", '"', "'"]

# Sphinx wraps every `.. math::` body in \begin{split}...\end{split}. These
# environments are only legal at the top level of display math, so nested in
# split they make MathJax fail with "Erroneous nesting of equation structures".
# Each has a variant that is legal inside another environment.
NESTABLE = {"align": "aligned", "gather": "gathered", "eqnarray": "aligned",
            "flalign": "aligned", "alignat": "aligned"}
TOPLEVEL_ENV = re.compile(r"\\(begin|end)\{(%s)\*?\}" % "|".join(NESTABLE))


def nestable_math(line: str) -> str:
    return TOPLEVEL_ENV.sub(lambda m: "\\%s{%s}" % (m.group(1), NESTABLE[m.group(2)]), line)


def normalize_headings(rst: str) -> str:
    r"""Ensure heading depth never increases by more than one level.

    The guide uses \paragraph directly under \subsection in places, so pandoc
    emits a level-5 underline under a level-3 one. docutils rejects that as an
    inconsistent title style, so re-map each heading to at most one level
    deeper than its parent.
    """
    lines, out, stack = rst.split("\n"), [], []
    i = 0
    while i < len(lines):
        text, under = lines[i], lines[i + 1] if i + 1 < len(lines) else ""
        char = under.strip()[:1]
        is_heading = (
            # Headings always start at column 0; anything indented is literal
            # block or directive content that may happen to look like one.
            text.strip() and text[:1] not in " \t" and under[:1] not in " \t"
            and char in UNDERLINES
            and under.strip() == char * len(under.strip())
            and len(under.strip()) >= len(text.strip())
            and (not out or not out[-1].strip())
        )
        if not is_heading:
            out.append(text)
            i += 1
            continue

        level = UNDERLINES.index(char)
        while stack and stack[-1] >= level:
            stack.pop()
        level = min(level, len(stack))       # at most one deeper than parent
        stack.append(level)
        out += [text, UNDERLINES[level] * max(len(text.strip()), 3)]
        i += 2
    return "\n".join(out)


def collapse_math_blanks(rst: str) -> str:
    r"""Drop blank lines inside `.. math::` bodies.

    Sphinx treats a blank line in a math directive as a separator between
    independent equations. The LaTeX sources space out the rows of multi-line
    \begin{cases}/align blocks for readability, which would otherwise split one
    equation into several unterminated fragments -- MathJax then reports
    "\begin{cases} ended with \end{split}" and the equation fails to render.
    """
    lines, out, i = rst.split("\n"), [], 0
    while i < len(lines):
        out.append(lines[i])
        if not re.match(r"^\s*\.\. math::", lines[i]):
            i += 1
            continue

        pad = len(lines[i]) - len(lines[i].lstrip())
        i += 1
        started = False                     # have we passed the option block?
        while i < len(lines):
            line = lines[i]
            if line.strip():
                if len(line) - len(line.lstrip()) <= pad:
                    break                   # dedent: directive body has ended
                started = started or not re.match(r"^\s*:\w[\w-]*:", line)
                out.append(nestable_math(line))
                i += 1
                continue

            # Blank line: keep the one separating options from content, and
            # stop at the blank that actually ends the directive.
            j = i
            while j < len(lines) and not lines[j].strip():
                j += 1
            inside = j < len(lines) and len(lines[j]) - len(lines[j].lstrip()) > pad
            if not inside:
                break
            if not started:
                out.append("")
            i = j
        out.append("")
    return "\n".join(out)


def postprocess(rst, labels, refs, cites, figures, equations, anchors, title) -> str:
    # Re-emit the environments pandoc could not handle. The surrounding blank
    # lines are required: without them docutils treats an anchor as paragraph
    # text and silently drops the target.
    def block(render):
        return lambda m: "\n\n" + render(int(m.group(1))).strip("\n") + "\n\n"

    rst = re.sub(r"\n*^[ \t]*XFIG(\d{4})XFIG[ \t]*$\n*",
                 block(lambda i: render_figure(figures[i])), rst, flags=re.M)
    rst = re.sub(r"\n*^[ \t]*XEQN(\d{4})XEQN[ \t]*$\n*",
                 block(lambda i: render_equation(equations[i])), rst, flags=re.M)
    rst = re.sub(r"\n*^[ \t]*XANC(\d{4})XANC[ \t]*$\n*",
                 block(lambda i: f".. _{anchor(anchors[i])}:"), rst, flags=re.M)

    # Restore cross-references, dropping any "Fig."/"Table" the source wrote by
    # hand since :numref: generates that prefix itself.
    def put_ref(m):
        label = refs[int(m.group(1))]
        return f" :{role_for(label)}:`{anchor(label)}` "

    rst = re.sub(r"\s?XREF(\d{4})XREF\s?", put_ref, rst)
    rst = re.sub(r"\b(?:Fig(?:ure)?|Tab(?:le)?|Eq(?:uation)?)\.?~?[ \t]*(?=:numref:|:eq:)",
                 "", rst, flags=re.I)
    rst = re.sub(r"\s?XCIT(\d{4})XCIT\s?",
                 lambda m: " " + " ".join(f":cite:`{k.strip()}`"
                                          for k in cites[int(m.group(1))].split(",")) + " ", rst)

    rst = rst.replace("figs/", "images/").replace("./images/", "images/")
    rst = re.sub(r"(`)\s+([.,;:)\]])", r"\1\2", rst)   # " `x` ." -> " `x`."

    # Any stray raw-latex pandoc emitted would render as literal noise.
    rst = re.sub(r"^\.\. raw:: latex\n(?:\n|   .*\n)*", "", rst, flags=re.M)
    rst = re.sub(r"^\.\. container:: float\s*\n", "", rst, flags=re.M)

    # Re-attach section anchors by matching the heading text pandoc emitted.
    by_title = {}
    for k, v in labels.items():                 # dicts keep insertion order
        if v["kind"] == "section":
            by_title.setdefault(v["key"], []).append(k)
    lines, out = rst.split("\n"), []
    for n, line in enumerate(lines):
        nxt = lines[n + 1] if n + 1 < len(lines) else ""
        heading = (line.strip() and nxt.strip()
                   and re.fullmatch(r"[-=~^\"'`#*+]{3,}", nxt.strip())
                   and len(nxt.strip()) >= len(line.strip()))
        if heading and by_title.get(line.strip()):
            out += [f".. _{anchor(by_title[line.strip()].pop(0))}:", ""]
        out.append(line)

    body = collapse_math_blanks(normalize_headings(re.sub(r"\n{4,}", "\n\n\n", "\n".join(out))))
    return f"{'=' * len(title)}\n{title}\n{'=' * len(title)}\n\n{body}\n"


def main():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    report = {"labels": {}, "manual": [], "refs": set(), "duplicates": []}
    for stem, out_name, title in CHAPTERS:
        tex, labels, refs, cites, figs, eqs, ancs = preprocess(read_tex(stem))
        rst = postprocess(pandoc(tex), labels, refs, cites, figs, eqs, ancs, title)
        (BUILD / f"{out_name}.rst").write_text(rst, encoding="utf-8")

        for name, meta in labels.items():
            if name in report["labels"]:
                report["duplicates"].append(
                    f"{name} (in {report['labels'][name]['file']} and {out_name}.rst)")
            report["labels"][name] = {**meta, "file": f"{out_name}.rst"}
            if meta["kind"] == "manual":
                report["manual"].append(f"{name} ({out_name}.rst)")
        report["refs"].update(refs)
        print(f"  {stem}.tex -> {out_name}.rst  ({len(rst.splitlines())} lines, "
              f"{len(figs)} figures, {len(eqs)} eqns, {len(labels)} labels)")

    report["dangling"] = sorted(r for r in report["refs"] if r not in report["labels"])
    report["refs"] = sorted(report["refs"])
    (ROOT / "build" / "conversion_report.json").write_text(json.dumps(report, indent=2))

    if report["manual"]:
        print(f"\n  anchors needing manual placement ({len(report['manual'])}):")
        for m in report["manual"]:
            print(f"    - {m}")
    if report["duplicates"]:
        print(f"\n  labels defined twice -- fix in the LaTeX source "
              f"({len(report['duplicates'])}):")
        for dup in report["duplicates"]:
            print(f"    - {dup}")
    if report["dangling"]:
        print(f"\n  referenced but never defined in the LaTeX: "
              f"{', '.join(report['dangling'])}")


if __name__ == "__main__":
    main()
