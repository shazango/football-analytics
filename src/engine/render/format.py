"""How a number is written down. One implementation, used by every part
of the report that puts a value in front of a reader.

This exists because there were two. The claim sentences formatted a
benchmark position in Python and the PDF table formatted it again in
Typst, and the two drifted: the summary said "91st percentile of 22
goalkeepers" while the table beside it said "91th of 22" — an ordinal
suffix hardcoded to "th", and a percentile wearing an ordinal's clothes,
which produced impossibilities like "82th of 60".

So the strings live in the IR, built here, and renderers project them
(brief §9: renderers must not recompute anything — presentation is
recomputation too).
"""

import math

# Below this many comparators a position is stated as an ordinal ("5th of
# 7"); at or above it, as a percentile ("82nd percentile of 60"). Over
# seven players a percentile can only take seven values, so its decimals
# claim a precision that isn't there (docs/verdict_bands.md).
ORDINAL_BELOW_N = 20

# Declared per metric in metrics/*.yaml. A unit is a property of the
# metric, not something to infer from whether it carries a per-90
# adjustment: psxg_ga and pass_completion_middle_third are both
# adjustment-free, and one is goals while the other is a percentage.
UNIT_SUFFIX = {
    "percent": "%",
    "metres": " m",
    None: "",
}


def significant(value: float, figures: int = 3) -> str:
    """Three significant figures, trailing zeros kept.

    Fixed decimals would print Xhaka's 0.047 xG as "0.0" — a number that
    reads as "he generated none". Significant figures alone would print
    80.0 as "80", so a column of values comes out ragged. Both, then.
    """
    if value == 0:
        return "0." + "0" * (figures - 1)
    digits = max(0, (figures - 1) - math.floor(math.log10(abs(value))))
    return f"{value:.{digits}f}"


def format_value(
    value: float | None,
    unit: str | None = None,
    adjustment: str | None = None,
    ci_low: float | None = None,
    ci_high: float | None = None,
) -> str | None:
    """The number as a reader sees it, wherever they see it: same string
    in the summary, the table and the spreadsheet.

    A confidence interval is part of the value, not a decoration on it —
    brief §6, "never render a bare point estimate for these". Building it
    into the one string every renderer prints is what makes that
    structural rather than a rule each renderer has to remember.
    """
    if value is None:
        return None
    if unit is not None and unit not in UNIT_SUFFIX:
        raise ValueError(f"unknown unit '{unit}' (known: {sorted(k for k in UNIT_SUFFIX if k)})")
    suffix = UNIT_SUFFIX[unit] or (" per 90" if adjustment == "per_90" else "")
    text = f"{significant(value)}{suffix}"
    if ci_low is not None and ci_high is not None:
        text += f" ({significant(ci_low)} to {significant(ci_high)})"
    return text


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th … 11th, 12th, 13th … 21st, 82nd, 91st."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def states_percentile(benchmark_n: int) -> bool:
    return benchmark_n >= ORDINAL_BELOW_N


def comparison_short(entry: dict) -> str | None:
    """Where the player sits, for a table cell. "5th of 7", or "82nd
    percentile of 60" once the set is big enough to support one."""
    n = entry.get("benchmark_n")
    if not n or entry.get("benchmark_percentile") is None:
        return None
    if states_percentile(n):
        return f"{ordinal(round(entry['benchmark_percentile'] * 100))} percentile of {n}"
    return f"{ordinal(entry['benchmark_rank'])} of {n}"


def comparison_phrase(entry: dict, noun: str) -> str:
    """The same position in a sentence, for a claim. Names the ends —
    "highest of 7 midfielders" beats "1st of 7 midfielders" — where the
    table has no room to."""
    n = entry["benchmark_n"]
    if states_percentile(n):
        return (
            f"{ordinal(round(entry['benchmark_percentile'] * 100))} percentile "
            f"of {n} {noun}"
        )
    rank = entry["benchmark_rank"]
    if rank == 1:
        return f"highest of {n} {noun} in the comparison set"
    if rank == n:
        return f"lowest of {n} {noun} in the comparison set"
    return f"{ordinal(rank)} of {n} {noun} in the comparison set"
