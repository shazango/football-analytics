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
    VerdictBands,
    _claimable,
    build_claims,
    load_bands,
)
from engine.render.format import (
    ORDINAL_BELOW_N,
    comparison_short,
    format_number,
    format_value,
    ordinal,
    unit_label,
)

BANDS = load_bands()


def _entry(**overrides) -> dict:
    """A benchmarked foundation-metric entry as build_report produces it,
    display_value included — the claim layer prints the IR's string rather
    than formatting its own copy."""
    base = {
        "id": "line_break_value",
        "title": "Line-break value",
        "value": 74.8,
        "adjustment": "per_90",
        "unit": None,
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
    entry = {**base, **overrides}
    entry.setdefault(
        "display_value",
        format_value(entry["value"], entry["unit"], entry["adjustment"]),
    )
    entry.setdefault("benchmark_comparison", comparison_short(entry))
    entry.setdefault("display_number", format_number(entry["value"]))
    entry.setdefault("unit_label", unit_label(entry["unit"], entry["adjustment"]))
    return entry


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
        "notable_distance_mads: 1.0\n"
        "bands:\n  - {verdict: elite, min_percentile: 90, direction: strength}\n"
    )
    with pytest.raises(FileNotFoundError, match="docs/nope.md"):
        load_bands(bad)


def test_bands_must_declare_their_distance_floor(tmp_path):
    # Not defaulted: a ruleset that doesn't state its floor would silently
    # inherit whatever the code last thought it was, which is what
    # versioning the floor exists to prevent.
    bad = tmp_path / "bands.yaml"
    bad.write_text(
        "id: verdict_bands\nversion: 1\nmethodology: docs/verdict_bands.md\n"
        "bands:\n  - {verdict: elite, min_percentile: 90, direction: strength}\n"
    )
    with pytest.raises(KeyError, match="notable_distance_mads"):
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
    # "0.0 per 90" reads as "he generated none". This is Xhaka's real xG.
    claim = build_claims(
        [_entry(id="xg", title="Expected goals", value=0.0468, benchmark_median=0.224,
                benchmark_mad=0.05, benchmark_percentile=0.0, benchmark_rank=7)],
        "MF", BANDS,
    )["weaknesses"][0]
    assert "0.0468 per 90" in claim["text"]
    assert "against a positional median of 0.224 per 90" in claim["text"]


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

    assert qualifies(BANDS.notable_distance_mads)
    assert not qualifies(BANDS.notable_distance_mads - 0.01)


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
    bumped = VerdictBands(
        version=BANDS.version + 1, methodology=BANDS.methodology, bands=BANDS.bands,
        notable_distance_mads=BANDS.notable_distance_mads,
    )
    after = build_claims([_entry()], "MF", bumped)
    assert after != claims
    assert after["strengths"][0]["band_version"] == BANDS.version + 1


def test_the_distance_floor_belongs_to_the_ruleset():
    # Raising the floor is a ruleset change, so it must come from the
    # versioned bands and be visible in the output — not from a constant
    # that two reports could straddle indistinguishably.
    entry = _entry(value=23.5, benchmark_median=21.5, benchmark_mad=1.0,
                   benchmark_percentile=0.95)  # 2 MADs out
    claims = build_claims([entry], "MF", BANDS)
    assert claims["notable_distance_mads"] == BANDS.notable_distance_mads
    assert len(claims["strengths"]) == 1

    stricter = VerdictBands(
        version=BANDS.version + 1, methodology=BANDS.methodology, bands=BANDS.bands,
        notable_distance_mads=3.0,
    )
    after = build_claims([entry], "MF", stricter)
    assert after["strengths"] == []
    assert after["not_notable"] == 1
    assert after["notable_distance_mads"] == 3.0


def test_shipped_bands_match_the_documented_table():
    # The methodology page publishes these; a silent edit to the YAML
    # would make the page a lie.
    assert BANDS.version == 1
    assert BANDS.notable_distance_mads == 1.0
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
        "minutes": 3018.0, "display_minutes": "3018",
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

    # Read back out of the compiled document rather than asserted against
    # the template source: a template that compiles is not evidence that
    # it rendered the right sentences, which is how the old PDF renderer
    # went unrun for so long.
    from engine.render.pdf_renderer import claims_in_pdf, render_pdf

    assert claims_in_pdf(report) == expected
    pdf_out = tmp_path / "r.pdf"
    render_pdf(report, pdf_out)
    assert pdf_out.read_bytes()[:5] == b"%PDF-"


# --- one formatter, so presentation cannot drift ---------------------


@pytest.mark.parametrize(
    "n, expected",
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"),
     (13, "13th"), (20, "20th"), (21, "21st"), (22, "22nd"), (82, "82nd"),
     (91, "91st"), (95, "95th"), (100, "100th"), (111, "111th"), (112, "112th")],
)
def test_ordinal_suffixes(n, expected):
    # The PDF table hardcoded "th" and rendered "91th of 22".
    assert ordinal(n) == expected


@pytest.mark.parametrize("n", range(1, 40))
def test_an_ordinal_can_never_exceed_its_comparison_set(n):
    """"82th of 60" was on the shipped report: a percentile formatted with
    the ordinal template. An ordinal names a place in the set, so it can
    never be larger than the set."""
    for rank in (1, max(1, n // 2), n):
        entry = _entry(benchmark_n=n, benchmark_rank=rank,
                       benchmark_percentile=rank / n)
        short = comparison_short(entry)
        if "percentile" in short:
            # Percentile form: the first number is out of 100, not out of n,
            # and must say so rather than reading as a rank.
            assert n >= ORDINAL_BELOW_N
            assert short.endswith(f"of {n}")
        else:
            assert n < ORDINAL_BELOW_N
            stated = int(short.split()[0].rstrip("stndrh"))
            assert stated <= n, f"{short} claims a place beyond a set of {n}"


def test_summary_and_table_state_the_same_comparison(tmp_path):
    # The defect this guards: the claim said "91st percentile of 22
    # goalkeepers" while the table beside it said "91th of 22".
    entry = _entry(benchmark_n=22, benchmark_rank=2, benchmark_percentile=0.91)
    claim = build_claims([entry], "GK", BANDS)["strengths"][0]
    assert claim["comparison"] == comparison_short(entry) == "91st percentile of 22"
    assert "91st percentile of 22 goalkeepers" in claim["text"]
    assert entry["benchmark_comparison"] == claim["comparison"]


def test_percentage_metrics_carry_their_unit_in_both_places():
    entry = _entry(id="pass_completion_defensive_third", title="Pass completion, defensive third",
                   value=80.0, unit="percent", adjustment=None,
                   benchmark_median=70.6, benchmark_mad=4.0, benchmark_n=22,
                   benchmark_rank=2, benchmark_percentile=0.91)
    claim = build_claims([entry], "GK", BANDS)["strengths"][0]
    assert entry["display_value"] == "80.0%"           # the table prints this
    assert "80.0%" in claim["text"]                    # and so does the summary
    assert "positional median of 70.6%" in claim["text"]


def test_a_bootstrap_metric_cannot_be_formatted_without_its_interval():
    # Brief §6: never a bare point estimate for these. The interval is part
    # of the one string every renderer prints, so no renderer can drop it.
    with_ci = format_value(0.167, None, "per_90", 0.0304, 0.298)
    assert with_ci == "0.167 per 90 (0.0304 to 0.298)"
    assert format_value(0.167, None, "per_90") == "0.167 per 90"


def test_unknown_unit_is_rejected():
    with pytest.raises(ValueError, match="furlongs"):
        format_value(1.0, "furlongs")


def test_renderers_do_not_build_display_strings_of_their_own():
    """Presentation is recomputation (brief §9).

    Three independent copies of the same formatting have already been
    found — the Typst table's ordinal, the XLSX claims sheet's comparison,
    and both renderers composing "N of M could not be judged" — so this
    checks by inspection rather than waiting for the fourth. A renderer
    may lay a string out; it may not compose one from numbers.
    """
    import re

    render_dir = Path(__file__).parent.parent / "src" / "engine" / "render"
    banned = {
        # (pattern, what it would mean)
        r"\bround\(": "rounds a number instead of printing a display_* string",
        r"%\.\d": "applies a printf format to a value",
        r"\bordinal\b": "builds an ordinal outside format.py",
    }
    offenders = []
    for path in [*render_dir.glob("*.py"), *(render_dir / "templates").glob("*.typ")]:
        if path.name in {"format.py", "claims.py", "report.py"}:
            continue  # where strings are legitimately composed
        source = path.read_text()
        for pattern, reason in banned.items():
            for line in source.splitlines():
                if line.strip().startswith(("#", "//")):
                    continue
                if re.search(pattern, line):
                    offenders.append(f"{path.name}: {line.strip()[:70]} — {reason}")
    assert not offenders, "renderer builds its own display string:\n" + "\n".join(offenders)
