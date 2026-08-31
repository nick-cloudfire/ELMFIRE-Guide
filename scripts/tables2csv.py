#!/usr/bin/env python3
"""Turn tables/inputSwitches.tex into a browsable Sphinx reference page.

The LaTeX source is one 391-row landscape longtable, which is unreadable on
the web. \\multicolumn rows in it mark namelist groups (MISCELLANEOUS, SMOKE,
INPUTS, ...), so we split on those and emit one csv-table section per group.
"""

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tables" / "inputSwitches.tex"
OUT = ROOT / "build" / "docs"

COLUMNS = ["Name", "Default", "Type", "Units", "Description"]
GROUP = re.compile(r"\\multicolumn\{\d+\}\{[^}]*\}\{([^}]+)\}")


def clean(cell: str) -> str:
    """LaTeX cell -> RST cell."""
    cell = cell.strip()
    cell = re.sub(r"\\ref\{([^}]*)\}",
                  lambda m: f":ref:`{m.group(1).replace(':', '-').replace('_', '-').lower()}`", cell)
    cell = re.sub(r"\\text(bf|it|tt)\{([^}]*)\}", r"\2", cell)
    cell = cell.replace("\\_", "_").replace("\\&", "&").replace("\\%", "%").replace("\\#", "#")
    cell = re.sub(r"\\[a-zA-Z]+\s*", "", cell)          # leftover bare macros
    return cell.strip().strip("{}").strip()


def parse():
    """Yield (group_name, [row, ...]) in source order."""
    groups, current, name = [], [], "General"
    for raw in SRC.read_text(encoding="utf-8").split("\\\\"):
        line = raw.strip()
        if not line or line.startswith("%"):
            continue
        if g := GROUP.search(line):
            if current:
                groups.append((name, current))
            name, current = clean(g.group(1)).title(), []
            continue
        if "&" not in line:
            continue
        cells = [clean(c) for c in line.split("&")]
        # Skip the repeated header row and any rule-only remnants.
        if not cells[0] or cells[0].lower() in {"name", "switch"}:
            continue
        cells = (cells + [""] * len(COLUMNS))[:len(COLUMNS)]
        current.append(cells)
    if current:
        groups.append((name, current))
    return groups


def main():
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    groups = parse()

    title = "Input Parameter Reference"
    page = [".. _tab-inputswitches:", "", "=" * len(title), title, "=" * len(title), "",
            "Every namelist entry ELMFIRE accepts, grouped by namelist. The",
            "Description column links to the section of the guide that explains",
            "the parameter in context.", ""]

    total = 0
    for name, rows in groups:
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        path = OUT / "tables" / f"{slug}.csv"
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(COLUMNS)
            w.writerows(rows)
        total += len(rows)
        page += [name, "-" * len(name), "",
                 f".. csv-table::",
                 f"   :file: tables/{slug}.csv",
                 "   :header-rows: 1",
                 "   :widths: 30 18 12 12 28",
                 ""]

    (OUT / "input_reference.rst").write_text("\n".join(page) + "\n", encoding="utf-8")
    print(f"  inputSwitches.tex -> input_reference.rst "
          f"({len(groups)} namelist groups, {total} parameters)")


if __name__ == "__main__":
    main()
