# Documentation pipeline

Builds the elmfire.io documentation site directly from this repository's
LaTeX sources. The LaTeX is the single source of truth: the PDF guide and the
website are two renderings of the same content.

## Quick start

```bash
./scripts/setup.sh            # one time: creates .venv with Sphinx + pandoc
./scripts/build.sh --serve    # build and preview on http://localhost:8000
./scripts/deploy.sh           # dry run against /var/www/html
./scripts/deploy.sh --apply --host user@elmfire.io
```

`setup.sh` needs no root. Two optional system packages improve the output:
`poppler-utils` (rasterises PDF figures) and `latexmk` (builds the downloadable
PDF alongside the site).

## What each script does

| Script | Purpose |
| --- | --- |
| `setup.sh` | Creates `.venv/` with Sphinx, the RTD theme and a bundled pandoc. |
| `tex2rst.py` | Converts the four chapter `.tex` files to reStructuredText. |
| `tables2csv.py` | Turns the 391-row `inputSwitches.tex` longtable into one CSV and csv-table section per namelist group. |
| `bibcheck.py` | Lists *cited* bib entries missing required fields, into `build/bib_incomplete.txt`. |
| `build.sh` | Runs the converters, stages figures and the Sphinx project, then runs `sphinx-build`. `--strict` fails on warnings. |
| `deploy.sh` | Verifies the build, snapshots the docroot, and rsyncs. Dry run unless `--apply`. |

## Layout

```
sphinx/            hand-maintained: conf.py, index.rst, theme assets
sphinx/overlay/    hand-written .rst that overrides generated files
scripts/           this pipeline
build/docs/        generated RST tree      (gitignored)
build/html/        the site                (gitignored)
build/conversion_report.json   labels, cross-references, dangling refs
```

## Editing rules

Everything under `build/` is regenerated from scratch on every build, so edits
there are lost. To change the site:

* **Content** - edit the `.tex` files. Both the PDF and the site follow.
* **Structure, theme, landing page** - edit `sphinx/`.
* **A page that should not come from LaTeX** - add it to `sphinx/overlay/`,
  which is copied over the generated tree last and wins any conflict.

## How LaTeX constructs are mapped

`tex2rst.py` extracts the constructs pandoc handles badly to sentinels before
pandoc runs, then re-emits them as Sphinx directives:

* `figure` environments become `.. figure::` with caption, width and anchor
  (pandoc otherwise turns them into `raw:: latex` containers and drops labels).
* Labelled `equation`/`align`/`gather` become `.. math::` with `:label:`.
* `\ref` becomes `:numref:` for figures and tables, `:eq:` for equations and
  `:ref:` for sections; a hand-written "Fig."/"Table" lead-in is removed since
  `:numref:` generates its own.
* `\cite` becomes `:cite:`, resolved against `references.bib`.
* Local macros (`\code`, `cfTable`) and sizing wrappers (`\resizebox`,
  `adjustbox`) are unwrapped -- pandoc discards their contents entirely.
* `\textbf{...}` used as a heading with a `\label` is promoted to a real
  subsubsection so the anchor has a title and appears in the sidebar.
* A `\label` on the same line as its heading is split onto its own line.
* Heading depth is re-mapped so it never jumps more than one level (the guide
  uses `\paragraph` directly under `\subsection`, which docutils rejects).
* Blank lines inside `.. math::` bodies are removed. Sphinx splits a math
  directive on blank lines into separate equations, so the blank lines the
  LaTeX uses to space out `cases`/`aligned` rows would otherwise cut one
  equation into unterminated fragments, and MathJax reports
  `\begin{cases} ended with \end{split}`.

## Bibliography

`references.bib` is a 348-entry working set, but only the ~32 entries actually
cited by `\cite` appear on the site -- `bibliography.rst` deliberately omits
`:all:`, matching what `\bibliographystyle{plain}` puts in the PDF.

`conf.py` suppresses `bibtex.missing_field`, which fired ~55 times and made
`--strict` unusable. `bibcheck.py` reports the same information for cited
entries only, which is a much shorter list. Filling those in needs the original
sources, so nothing is auto-fixed.

## Replacing the old site

The site is static files only, so the new page structure replaces the old one
by replacing the docroot -- nothing in nginx/Apache, DNS or TLS needs changing.
`deploy.sh` syncs with `--delete`, so pages that no longer exist
(`tutorials.html`, `getting_started.html`, `user_guide/io.html`, ...) are
removed, and old URLs will 404.

Files the web server owns rather than Sphinx are excluded from the delete:

    /.well-known/  /.htaccess  /robots.txt  /favicon.ico  /.git/

`.well-known/` matters most -- certbot writes its ACME challenge there, and
deleting it breaks TLS renewal weeks later, with no immediate symptom. Add to
the `KEEP` array in `deploy.sh` if the docroot holds anything else hand-placed;
check with `ls -a` on the server first, since a plain `ls` hides all of these.

Always dry-run first. The `*deleting` lines list exactly what goes.

## Unattended deployment

`autodeploy.sh` pulls, and if `origin/main` has moved, rebuilds and publishes.
It exits silently when nothing changed, so it is safe to run often.

    ./scripts/autodeploy.sh --dry-run    # report what would happen
    ./scripts/autodeploy.sh --force      # rebuild and publish regardless

Safety properties, in order of importance:

* The site is replaced **only if the build passes `--strict`**. A broken
  commit on main leaves the previous site serving and the run exits non-zero.
* `flock` prevents overlapping runs; a build plus rsync can outlast a timer.
* `git merge --ff-only`, and it refuses to run with a dirty working tree --
  unattended merges are never resolved by guessing.
* `deploy.sh` still takes its backup and still refuses stale build output.

Install the timer:

    sudo cp etc/elmfire-docs.{service,timer} /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now elmfire-docs.timer

    systemctl list-timers elmfire-docs      # when it next runs
    journalctl -u elmfire-docs -n 50        # what happened last time
    tail -f build/autodeploy.log            # the run log

Or with cron, if you prefer:

    0 4 * * *  /home/chris/ELMFIRE-Guide/scripts/autodeploy.sh

### Running without sudo

An unattended run must never block on a password prompt, so the service user
needs to own both the docroot and the backup directory:

    sudo chown -R chris:chris /var/www/html
    mkdir -p ~/site-backups

`deploy.sh` escalates only when either is unwritable, so once both are owned by
the service user it never calls sudo. `BACKUP_DIR` and `KEEP_BACKUPS` are set
in the unit file; the default retention is the 5 most recent backups, pruned
automatically, since a daily deploy would otherwise add ~28 MB a day.

The alternative is a narrow sudoers rule for `rsync` and `cp`, but owning the
directories is simpler and gives the timer no privileges it does not need.

## Known source issues

The build is warning-clean and passes `--strict`. Three cited bibliography
entries are still incomplete; `build/bib_incomplete.txt` lists them.
