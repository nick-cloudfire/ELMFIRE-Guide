#!/usr/bin/env python3
"""Report bibliography entries missing fields their entry type requires.

Sphinx emits one warning per incomplete entry, which buries real problems and
makes `build.sh --strict` unusable. conf.py suppresses that warning category;
this script keeps the information available as a to-do list instead.

Nothing here edits references.bib -- filling these in needs the actual sources.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIB = ROOT / "references.bib"
OUT = ROOT / "build" / "bib_incomplete.txt"

# Fields the standard BibTeX styles require, by entry type. A tuple means any
# one of the alternatives satisfies the requirement.
REQUIRED = {
    "article":       ["author", "title", "journal", "year"],
    "book":          [("author", "editor"), "title", "publisher", "year"],
    "inbook":        [("author", "editor"), "title", "publisher", "year"],
    "incollection":  ["author", "title", "booktitle", "publisher", "year"],
    "inproceedings": ["author", "title", "booktitle", "year"],
    "conference":    ["author", "title", "booktitle", "year"],
    "techreport":    ["author", "title", "institution", "year"],
    "phdthesis":     ["author", "title", "school", "year"],
    "mastersthesis": ["author", "title", "school", "year"],
    "proceedings":   ["title", "year"],
    "manual":        ["title"],
}


def entries(text: str):
    """Yield (key, type, {fields}) for every entry in the file."""
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        i, depth = text.index("{", m.start()) + 1, 1
        while depth and i < len(text):
            depth += (text[i] == "{") - (text[i] == "}")
            i += 1
        body = text[m.end():i]
        fields = {f.lower() for f in re.findall(r"^\s*(\w+)\s*=", body, re.M)}
        yield m.group(2), m.group(1).lower(), fields


def cited_keys() -> set:
    """Keys actually referenced by \\cite in the chapter sources."""
    keys = set()
    for tex in ROOT.glob("*.tex"):
        for group in re.findall(r"\\cite[tp]?\{([^}]*)\}", tex.read_text(errors="replace")):
            keys.update(k.strip() for k in group.split(",") if k.strip())
    return keys


def main():
    cited = cited_keys()
    report, total = [], 0
    for key, etype, fields in entries(BIB.read_text(errors="replace")):
        if key not in cited:
            continue
        total += 1
        missing = []
        for req in REQUIRED.get(etype, []):
            if isinstance(req, str):
                if req not in fields:
                    missing.append(req)
            elif not set(req) & fields:
                missing.append("/".join(req))
        if missing:
            report.append(f"{key:<50} @{etype:<14} missing: {', '.join(missing)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    header = (f"{len(report)} of {total} CITED references.bib entries are missing "
              f"required fields.\nUncited entries are ignored -- they do not appear on "
              f"the site or in the PDF.\nFilling these in needs the original sources; "
              f"nothing here is auto-fixable.\n\n")
    OUT.write_text(header + "\n".join(sorted(report)) + "\n")
    print(f"  {len(report)}/{total} cited bib entries incomplete"
          + (f" -> build/bib_incomplete.txt" if report else ""))


if __name__ == "__main__":
    main()
