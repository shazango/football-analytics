"""PDF renderer (build order step 13): Jinja2 -> WeasyPrint. Board-ready,
one page of substance (brief §9). Pure projection of the report IR — no
recomputation; suppression applied the same way as the XLSX renderer.

ponytail: WeasyPrint needs system libraries (Pango/cairo/gobject) not
present on this dev machine (no Homebrew) — the template/render call is
correct but untestable here. `build_report`'s CLI catches the resulting
OSError and skips the PDF rather than failing the whole run.
"""

from pathlib import Path

import jinja2
from weasyprint import HTML

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_pdf(report: dict, path: Path) -> None:
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(TEMPLATE_DIR), autoescape=True)
    template = env.get_template("report.html")
    html = template.render(report=report)
    HTML(string=html).write_pdf(str(path))
