"""PDF renderer (build order step 13): Typst. Board-ready, one page of
substance (brief §9).

Was Jinja2 -> WeasyPrint, which needs Pango, cairo and libgobject as
system libraries. Those are not installable on a machine without a system
package manager, so the renderer had never actually run and every check
on the report was made against the HTML template as a proxy. Typst ships
as a self-contained wheel with its fonts bundled: no system libraries, no
package manager, same output on any machine.

Pure projection of the report IR, and structurally so — the template is
handed the exact JSON the JSON renderer writes and reads its numbers from
that, so "all three renderers show the same numbers" is a property of the
design rather than something the tests have to keep catching.
"""

import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import typst

TEMPLATE = Path(__file__).parent / "templates" / "report.typ"


@contextmanager
def _compiled(report: dict):
    """The template beside its data in a scratch directory: Typst resolves
    json("report.json") relative to the .typ file, and its root confines
    file reads to that directory."""
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        (workdir / "report.json").write_text(json.dumps(report, default=str))
        shutil.copy(TEMPLATE, workdir / "report.typ")
        yield workdir / "report.typ", workdir


def claims_in_pdf(report: dict) -> list[str]:
    """The claim sentences the compiled document actually contains, read
    back out of it via the template's `<claim>` labels.

    Lets a test compare what the PDF says against what the JSON says,
    instead of assuming a template that compiled also rendered the right
    sentences — the assumption that let the old renderer go unrun.
    """
    with _compiled(report) as (source, workdir):
        found = json.loads(typst.query(source, "<claim>", root=workdir))
    return [element["value"] for element in found]


def render_pdf(report: dict, path: Path) -> None:
    with _compiled(report) as (source, workdir):
        typst.compile(source, output=workdir / "report.pdf", root=workdir)
        shutil.move(workdir / "report.pdf", path)
