"""XLSX renderer (build order step 13): flat tabular projection, "the
working format for the actual users" (brief §9). Pure projection of the
report IR — no recomputation. Suppresses sub-min_sample values here
(brief §6), showing "insufficient sample" instead — the JSON renderer
is where the raw numbers still live.
"""

from pathlib import Path

import xlsxwriter


def _display_value(entry: dict):
    if entry["value"] is None:
        return "no data"
    if entry["suppressed"]:
        return "insufficient sample"
    return entry["value"]


def _write_metric_table(sheet, rows: list[dict], bold, has_benchmark: bool) -> None:
    headers = ["Metric", "Value", "Sample size", "Min sample"]
    if has_benchmark:
        headers += ["Percentile", "Benchmark n"]
    for col, header in enumerate(headers):
        sheet.write(0, col, header, bold)
    for r, entry in enumerate(rows, start=1):
        sheet.write(r, 0, entry["title"])
        sheet.write(r, 1, _display_value(entry))
        sheet.write(r, 2, entry["sample_size"])
        sheet.write(r, 3, entry["min_sample"])
        if has_benchmark:
            pct = entry.get("benchmark_percentile")
            sheet.write(r, 4, round(pct * 100, 1) if pct is not None else "n/a")
            sheet.write(r, 5, entry.get("benchmark_n", "n/a"))


def render_xlsx(report: dict, path: Path) -> None:
    workbook = xlsxwriter.Workbook(str(path))
    bold = workbook.add_format({"bold": True})

    identity = workbook.add_worksheet("Identity")
    identity_rows = [
        ("Name", report["name"]),
        ("Position", report["primary_position"]),
        ("Position bucket", report["position_bucket"]),
        ("Competition", report["competition"]["name"]),
        ("Season", report["competition"]["season"]),
        ("Minutes", round(report["minutes"], 1)),
        ("Generated at", report["generated_at"]),
        ("Attribution", report["attribution"]),
    ]
    for r, (label, value) in enumerate(identity_rows):
        identity.write(r, 0, label, bold)
        identity.write(r, 1, value)

    foundation_sheet = workbook.add_worksheet("Foundation Metrics")
    _write_metric_table(foundation_sheet, report["foundation_metrics"], bold, has_benchmark=True)

    if report["position_panel"]:
        panel_sheet = workbook.add_worksheet(f"{report['position_bucket']} Panel")
        _write_metric_table(panel_sheet, report["position_panel"], bold, has_benchmark=False)

    if report["throw_in_profile"]:
        throw_sheet = workbook.add_worksheet("Throw-in Profile")
        _write_metric_table(throw_sheet, report["throw_in_profile"], bold, has_benchmark=False)

    gs_sheet = workbook.add_worksheet("Game State Response")
    gs_headers = ["Stat", "Bucket", "Value", "Sample size", "Min sample"]
    for col, header in enumerate(gs_headers):
        gs_sheet.write(0, col, header, bold)
    for r, row in enumerate(report["game_state_response"], start=1):
        display = "insufficient sample" if row["suppressed"] else (
            "no data" if row["value"] is None else row["value"]
        )
        gs_sheet.write(r, 0, row["stat_id"])
        gs_sheet.write(r, 1, row["bucket"])
        gs_sheet.write(r, 2, display)
        gs_sheet.write(r, 3, row["sample_size"])
        gs_sheet.write(r, 4, row["min_sample"])

    methodology_sheet = workbook.add_worksheet("Methodology")
    methodology_sheet.write(0, 0, "Metric", bold)
    methodology_sheet.write(0, 1, "Methodology page", bold)
    seen = set()
    r = 1
    for entry in report["foundation_metrics"] + (report["position_panel"] or []):
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        methodology_sheet.write(r, 0, entry["title"])
        methodology_sheet.write(r, 1, entry["methodology"])
        r += 1

    workbook.close()
