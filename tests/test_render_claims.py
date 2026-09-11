"""Claims layer (docs/verdict_bands.md): verdicts, selection, and the
guarantee that all three renderers say the same thing.

The band boundaries and the n=20 ordinal cutoff are product decisions, so
they get pinned here rather than left to whatever the YAML happens to
say — a change to either should have to change a test on its way in.
"""

import json
from pathlib import Path

import pytest

from engine.render.claims import (
    NOTABLE_DISTANCE_MADS,
    ORDINAL_BELOW_N,
    VerdictBands,
    _claimable,
    build_claims,
    load_bands,
)

BANDS = load_bands()


def _entry(**overrides) -> dict:
    base = {
        "id": "line_break_value",
        "title": "Line-break value",
        "value": 74.8,
        "adjustment": "per_90",
        "sample_size": 3018,
        "min_sample": 450,
        "suppressed": False,
        "methodology": "docs/metrics/line_break_value.md",
        "benchmark_n": 7,
        "benchmark_suppressed": False,
        "benchmark_percentile": 1.0,
        "benchmark_median": 21.5,
        "benchmark_mad": 10.0,
        "benchmark_rank": 1,
    }
    return {**base, **overrides}


# --- bands -----------------------------------------------------------


@pytest.mark.parametrize(
    "percentile, verdict",
    [
        (1.00, "elite"),
        (0.90, "elite"),    # boundary is inclusive at the bottom
        (0.89, "strong"),
        (0.75, "strong"),
        (0.74, "typical"),
        (0.40, "typical"),
        (0.39, "below par"),
        (0.15, "below par"),
        (0.14, "weak"),
        (0.00, "weak"),
    ],
)
def test_band_boundaries(percentile, verdict):
    assert BANDS.classify(percentile)[0] == verdict


def test_bands_require_an_existing_methodology_page(tmp_path):
    bad = tmp_path / "bands.yaml"
    bad.write_text(
        "id: verdict_bands\nversion: 1\nmethodology: docs/nope.md\n"
        "bands:\n  - {verdict: elite, min_percentile: 90, direction: strength}\n"
    )
    with pytest.raises(FileNotFoundError, match="docs/nope.md"):
        load_bands(bad)


# --- no verdict without a defensible comparison ----------------------


@pytest.mark.parametrize(
    "override",
    [
        {"suppressed": True},
        {"benchmark_suppressed": True},
        {"value": None},
        {"benchmark_percentile": None},
        {"benchmark_median": None},
    ],
    ids=["sub_min_sample", "tiny_benchmark", "no_value", "no_percentile", "no_median"],
)
def test_no_claim_for_a_metric_that_cannot_be_judged(override):
    entry = _entry(**override)
    assert not _claimable(entry)
    claims = build_claims([entry], "MF", BANDS)
    assert claims["strengths"] == []
    assert claims["weaknesses"] == []
    assert claims["suppressed"] == 1


def test_typical_band_is_never_surfaced():
    # An average player is not a claim. 50th percentile, huge distance
    # from the median in MAD terms, still nothing.
    claims = build_claims(
        [_entry(benchmark_percentile=0.5, value=1000.0)], "MF", BANDS
    )
    assert claims["strengths"] == []
    assert claims["weaknesses"] == []
    assert claims["eligible"] == 1  # judged, just not notable


# --- comparison basis ------------------------------------------------


def test_ordinal_below_twenty_percentile_at_or_above():
    small = build_claims([_entry(benchmark_n=ORDINAL_BELOW_N - 1)], "MF", BANDS)
    claim = small["strengths"][0]
    assert claim["comparison_basis"] == "ordinal"
    assert "highest of 19 midfielders" in claim["text"]
    assert "percentile" not in claim["text"]

    big = build_claims(
        [_entry(benchmark_n=ORDINAL_BELOW_N, benchmark_percentile=0.92)], "MF", BANDS
    )
    claim = big["strengths"][0]
    assert claim["comparison_basis"] == "percentile"
    assert "92nd percentile of 20 midfielders" in claim["text"]


def test_ordinal_names_the_ends_and_numbers_the_middle():
    def text(rank, n, percentile):
        entry = _entry(benchmark_rank=rank, benchmark_n=n, benchmark_percentile=percentile)
        claims = build_claims([entry], "MF", BANDS)
        return (claims["strengths"] + claims["weaknesses"])[0]["text"]

    assert "highest of 7 midfielders" in text(1, 7, 1.0)
    assert "lowest of 7 midfielders" in text(7, 7, 0.0)
    assert "4th of 7 midfielders" in text(4, 7, 0.14)


def test_small_values_are_not_rounded_to_zero():
    # "0.0 per 90" reads as "he generated none". Xhaka's xG is 0.047.
    claim = build_claims(
        [_entry(id="xg", title="Expected goals", value=0.047, benchmark_median=0.2,
                benchmark_mad=0.05, benchmark_percentile=0.0, benchmark_rank=7)],
        "MF", BANDS,
    )["weaknesses"][0]
    assert "0.047 per 90" in claim["text"]


# --- selection -------------------------------------------------------


def test_at_most_three_each_way_furthest_from_median_first():
    strengths = [
        _entry(id=f"s{i}", title=f"S{i}", benchmark_percentile=0.95,
               value=21.5 + gap, benchmark_mad=1.0)
        for i, gap in enumerate([1.0, 9.0, 5.0, 3.0, 7.0])
    ]
    claims = build_claims(strengths, "MF", BANDS)
    assert [c["title"] for c in claims["strengths"]] == ["S1", "S4", "S2"]


def test_close_to_the_median_is_not_a_claim():
    # The Xhaka key-passes case: 6th of 7 puts him in the "below par"
    # band, but 1.22 against a median of 1.26 is one key pass every thirty
    # matches. Rank noise is not a weakness.
    near = _entry(id="key_passes", title="Key passes", value=1.22,
                  benchmark_median=1.26, benchmark_mad=0.4,
                  benchmark_percentile=0.14, benchmark_rank=6)
    claims = build_claims([near], "MF", BANDS)
    assert claims["weaknesses"] == []
    assert claims["eligible"] == 1        # it was judged
    assert claims["not_notable"] == 1     # and reported as not worth asserting


def test_floor_boundary_is_inclusive():
    def qualifies(deviation_in_mads):
        entry = _entry(value=21.5 + deviation_in_mads, benchmark_median=21.5,
                       benchmark_mad=1.0, benchmark_percentile=0.95)
        return bool(build_claims([entry], "MF", BANDS)["strengths"])

    assert qualifies(NOTABLE_DISTANCE_MADS)
    assert not qualifies(NOTABLE_DISTANCE_MADS - 0.01)


def test_no_spread_counts_as_maximally_distant():
    # MAD = 0 means at least half the comparison set share one value, so
    # the distance has no unit. A player off that value is as unusual as
    # this set gets; a player on it is not unusual at all.
    off = _entry(value=3.0, benchmark_median=0.0, benchmark_mad=0.0,
                 benchmark_percentile=1.0)
    claims = build_claims([off], "MF", BANDS)
    assert len(claims["strengths"]) == 1
    # Null, not infinity — the JSON renderer has to emit valid JSON.
    assert claims["strengths"][0]["distance_from_median"] is None
    assert json.dumps(claims)

    on = _entry(value=0.0, benchmark_median=0.0, benchmark_mad=0.0,
                benchmark_percentile=1.0)
    assert build_claims([on], "MF", BANDS)["strengths"] == []


def test_unmeasurable_spread_outranks_a_measured_distance():
    off = _entry(id="a", title="A", value=3.0, benchmark_median=0.0,
                 benchmark_mad=0.0, benchmark_percentile=1.0)
    far = _entry(id="b", title="B", value=100.0, benchmark_median=0.0,
                 benchmark_mad=1.0, benchmark_percentile=0.95)
    claims = build_claims([far, off], "MF", BANDS)
    assert [c["title"] for c in claims["strengths"]] == ["A", "B"]


def test_never_padded_to_three():
    claims = build_claims([_entry()], "MF", BANDS)
    assert len(claims["strengths"]) == 1
    assert claims["weaknesses"] == []


def test_distance_is_scale_free():
    # Raw distance would put pass completion (90-ish) above xG (0.3-ish)
    # every time regardless of how unusual either actually is.
    far_small = _entry(id="xg", title="xG", value=0.9, benchmark_median=0.3,
                       benchmark_mad=0.1, benchmark_percentile=0.95)   # 6 MADs
    near_large = _entry(id="pc", title="PC", value=95.0, benchmark_median=90.0,
                        benchmark_mad=5.0, benchmark_percentile=0.95)  # 1 MAD
    claims = build_claims([near_large, far_small], "MF", BANDS)
    assert [c["title"] for c in claims["strengths"]] == ["xG", "PC"]


def test_bucket_noun_falls_back_for_an_unknown_bucket():
    claim = build_claims([_entry()], "Unknown", BANDS)["strengths"][0]
    assert "highest of 7 players" in claim["text"]


# --- band version is part of the output ------------------------------


def test_band_version_rides_on_every_claim_and_changes_the_output():
    claims = build_claims([_entry()], "MF", BANDS)
    assert claims["band_version"] == BANDS.version
    assert claims["strengths"][0]["band_version"] == BANDS.version

    # Bumping the version changes stored output: a regression golden that
    # pins band_version has to be re-approved rather than drifting.
    bumped = VerdictBands(version=BANDS.version + 1, methodology=BANDS.methodology,
                          bands=BANDS.bands)
    after = build_claims([_entry()], "MF", bumped)
    assert after != claims
    assert after["strengths"][0]["band_version"] == BANDS.version + 1


def test_shipped_bands_match_the_documented_table():
    # The methodology page publishes these; a silent edit to the YAML
    # would make the page a lie.
    assert BANDS.version == 1
    assert [(p, v) for p, v, _ in BANDS.bands] == [
        (90.0, "elite"), (75.0, "strong"), (40.0, "typical"),
        (15.0, "below par"), (0.0, "weak"),
    ]
    assert Path(BANDS.methodology).exists()


# --- renderers agree -------------------------------------------------


def test_all_three_renderers_carry_identical_claims(tmp_path):
    import zipfile

    from engine.render.json_renderer import render_json
    from engine.render.xlsx_renderer import render_xlsx

    report = {
        "person_id": 1, "name": "Test Player", "primary_position": "Center Midfield",
        "position_bucket": "MF",
        "competition": {"id": "C1", "name": "Comp", "season": "S1"},
        "minutes": 3018.0,
        "foundation_metrics": [_entry(), _entry(
            id="xg", title="Expected goals", value=0.047, benchmark_percentile=0.0,
            benchmark_median=0.2, benchmark_mad=0.05, benchmark_rank=7)],
        "position_panel": None, "throw_in_profile": None, "game_state_response": [],
        "attribution": "a", "generated_at": "now",
    }
    report["claims"] = build_claims(report["foundation_metrics"], "MF", BANDS)
    expected = [c["text"] for c in report["claims"]["strengths"] + report["claims"]["weaknesses"]]
    assert len(expected) == 2

    json_out = tmp_path / "r.json"
    render_json(report, json_out)
    reloaded = json.loads(json_out.read_text())["claims"]
    assert [c["text"] for c in reloaded["strengths"] + reloaded["weaknesses"]] == expected

    xlsx_out = tmp_path / "r.xlsx"
    render_xlsx(report, xlsx_out)
    strings = zipfile.ZipFile(xlsx_out).read("xl/sharedStrings.xml").decode()
    for text in expected:
        assert text in strings

    template = (
        Path(__file__).parent.parent
        / "src" / "engine" / "render" / "templates" / "report.html"
    )
    import jinja2
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(template.parent)))
    html = env.get_template("report.html").render(report=report)
    for text in expected:
        assert text in html
