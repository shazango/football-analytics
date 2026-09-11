"""Claims: the verdict layer over benchmarked foundation metrics
(docs/verdict_bands.md).

A table of numbers with a percentile column asserts nothing. This turns
the few metrics where a player is genuinely unusual into sentences a
reader can disagree with — a verdict, the evidence, and the comparison
that justifies the verdict.

Everything here is a table lookup, a sort, and string formatting. No
language model produces a verdict, chooses which metrics are notable, or
writes a sentence. That boundary is structural rather than conventional:
a claim carries its own verdict, value, comparison and band version, so a
model added later can be handed finished claims and never the inputs that
would let it decide any of them.

Called from build_report, not from a renderer — all three renderers
project the same claims, as with every other value (brief §9).
"""

from dataclasses import dataclass
from pathlib import Path
from statistics import median

import yaml

DEFAULT_BANDS_PATH = Path("bands/verdict_bands.yaml")

# Below this many comparators a claim states its ordinal ("4th of 7")
# rather than its percentile: over seven players a percentile can only
# take seven values, and rendering 85.7 claims a precision that isn't
# there.
ORDINAL_BELOW_N = 20

MAX_CLAIMS_PER_DIRECTION = 3

BUCKET_NOUN = {
    "GK": "goalkeepers",
    "DF": "defenders",
    "MF": "midfielders",
    "FW": "forwards",
}


@dataclass(frozen=True)
class VerdictBands:
    """The versioned ruleset that decides what a report is allowed to
    assert: which word a percentile earns, and how far from typical a
    value must sit before it earns a sentence at all. Both belong to the
    same version — each decides what the report says."""

    version: int
    methodology: str
    # (min_percentile, verdict, direction), ordered high to low.
    bands: tuple[tuple[float, str, str], ...]
    # Minimum distance from the positional median, in MADs, for a claim.
    notable_distance_mads: float

    def classify(self, percentile: float) -> tuple[str, str]:
        """(verdict, direction) for a percentile in [0, 1]. Boundaries are
        inclusive at the bottom, so exactly 90 reads elite and 89 strong."""
        points = percentile * 100
        for min_percentile, verdict, direction in self.bands:
            if points >= min_percentile:
                return verdict, direction
        raise ValueError(f"no band covers percentile {points}")


def load_bands(path: Path = DEFAULT_BANDS_PATH) -> VerdictBands:
    raw = yaml.safe_load(path.read_text())
    methodology = raw["methodology"]
    if not Path(methodology).exists():
        # Same rule metric definitions are held to (definitions.py): the
        # page that explains a judgement ships with the judgement.
        raise FileNotFoundError(
            f"verdict bands declare methodology page '{methodology}' "
            "which does not exist"
        )
    bands = tuple(
        (float(b["min_percentile"]), b["verdict"], b["direction"])
        for b in sorted(raw["bands"], key=lambda b: -b["min_percentile"])
    )
    if "notable_distance_mads" not in raw:
        # Not defaulted: a ruleset that doesn't state its floor would
        # silently inherit whatever the code last thought it was, which is
        # the thing versioning this is meant to prevent.
        raise KeyError(
            f"verdict bands '{path}' must declare notable_distance_mads "
            "(see docs/verdict_bands.md)"
        )
    return VerdictBands(
        version=raw["version"],
        methodology=methodology,
        bands=bands,
        notable_distance_mads=float(raw["notable_distance_mads"]),
    )


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_value(value: float, adjustment: str | None) -> str:
    # Three significant figures, not fixed decimals: these metrics span
    # xG near 0.05 and pass completion near 90, and "%.1f" turns Xhaka's
    # 0.047 xG into "0.0 per 90" — a sentence claiming he generated
    # literally none.
    return f"{value:.3g} per 90" if adjustment == "per_90" else f"{value:.3g}%"


def _comparison_phrase(entry: dict, noun: str) -> str:
    n = entry["benchmark_n"]
    if n >= ORDINAL_BELOW_N:
        return f"{_ordinal(round(entry['benchmark_percentile'] * 100))} percentile of {n} {noun}"
    rank = entry["benchmark_rank"]
    if rank == 1:
        return f"highest of {n} {noun} in the comparison set"
    if rank == n:
        return f"lowest of {n} {noun} in the comparison set"
    return f"{_ordinal(rank)} of {n} {noun} in the comparison set"


def _distance_from_median(entry: dict) -> float | None:
    """How far from typical, in median absolute deviations.

    Not raw units: these metrics run from xG near 0.3 to pass completion
    near 90, so ranking on raw distance would surface pass completion
    every time.

    None means the distribution has no spread at all (MAD = 0, i.e. at
    least half the comparison set share one value) and the player is not
    on it — a difference that cannot be measured in MADs because the unit
    is zero, but which is as unusual as this set gets. Treated as
    maximally distant, and kept as null rather than infinity so the JSON
    renderer emits valid JSON.
    """
    mad = entry.get("benchmark_mad")
    deviation = abs(entry["value"] - entry["benchmark_median"])
    if mad:
        return deviation / mad
    return None if deviation else 0.0


def _sort_distance(claim: dict) -> float:
    distance = claim["distance_from_median"]
    return float("inf") if distance is None else distance


def _notable(claim: dict, bands: VerdictBands) -> bool:
    """Landing in a non-typical band is not enough. On a small comparison
    set a percentile is really an ordinal — 6th of 7 is the 14th
    percentile whatever the numbers say — so without a distance floor
    rank noise becomes a verdict."""
    distance = claim["distance_from_median"]
    return distance is None or distance >= bands.notable_distance_mads


def _claimable(entry: dict) -> bool:
    """A verdict inherits every suppression rule already in force. There
    is no hedged verdict for a thin sample — there is no verdict."""
    return (
        not entry.get("suppressed")
        and not entry.get("benchmark_suppressed")
        and entry.get("value") is not None
        and entry.get("benchmark_percentile") is not None
        and entry.get("benchmark_median") is not None
    )


def _claim(entry: dict, bands: VerdictBands, noun: str) -> dict:
    verdict, direction = bands.classify(entry["benchmark_percentile"])
    value_text = _format_value(entry["value"], entry.get("adjustment"))
    median_text = _format_value(entry["benchmark_median"], entry.get("adjustment"))
    comparison = _comparison_phrase(entry, noun)
    return {
        "metric_id": entry["id"],
        "title": entry["title"],
        "verdict": verdict,
        "direction": direction,
        "value": entry["value"],
        "benchmark_n": entry["benchmark_n"],
        "benchmark_percentile": entry["benchmark_percentile"],
        "benchmark_median": entry["benchmark_median"],
        "benchmark_rank": entry["benchmark_rank"],
        "comparison_basis": "percentile" if entry["benchmark_n"] >= ORDINAL_BELOW_N else "ordinal",
        "distance_from_median": _distance_from_median(entry),
        "band_version": bands.version,
        "methodology": entry["methodology"],
        "text": f"{entry['title']}: {verdict}. {value_text} — {comparison}, "
                f"against a positional median of {median_text}.",
    }


def build_claims(
    foundation_metrics: list[dict], position_bucket: str, bands: VerdictBands
) -> dict:
    """Up to three strengths and up to three weaknesses, furthest from the
    positional median first, and only where that distance clears the
    ruleset's notable_distance_mads. Fewer if fewer qualify — never
    padded, and a player with nothing notable gets none."""
    noun = BUCKET_NOUN.get(position_bucket, "players")
    claims = [_claim(e, bands, noun) for e in foundation_metrics if _claimable(e)]

    def top(direction: str) -> list[dict]:
        selected = [c for c in claims if c["direction"] == direction and _notable(c, bands)]
        selected.sort(key=_sort_distance, reverse=True)
        return selected[:MAX_CLAIMS_PER_DIRECTION]

    return {
        "band_version": bands.version,
        "methodology": bands.methodology,
        # Carried so the JSON says which floor filtered it, not only which
        # bands judged it.
        "notable_distance_mads": bands.notable_distance_mads,
        "strengths": top("strength"),
        "weaknesses": top("weakness"),
        # Why a report that should have claims has none: the reader needs
        # to see "the data didn't support it", not an empty section.
        "eligible": sum(1 for e in foundation_metrics if _claimable(e)),
        "suppressed": sum(1 for e in foundation_metrics if not _claimable(e)),
        # Judged, in a strength/weakness band, but too close to the
        # positional median to be worth asserting.
        "not_notable": sum(
            1 for c in claims if c["direction"] != "neutral" and not _notable(c, bands)
        ),
    }


def benchmark_stats(values: list[float], value: float | None) -> dict:
    """Median, MAD and rank-from-the-top of `value` within a stored
    benchmark distribution. Computed in build_report (renderers must not
    recompute anything, brief §9) and carried in the IR beside n and the
    percentile."""
    if not values:
        return {"benchmark_median": None, "benchmark_mad": None, "benchmark_rank": None}
    med = median(values)
    return {
        "benchmark_median": med,
        "benchmark_mad": median(abs(v - med) for v in values),
        # Ties share the better rank: two players level on top are both 1st.
        "benchmark_rank": (
            sum(1 for v in values if v > value) + 1 if value is not None else None
        ),
    }
