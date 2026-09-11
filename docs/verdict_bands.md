# verdict_bands

The mapping from a player's position in a benchmark distribution to the
word a report is allowed to use about it. Defined in
`bands/verdict_bands.yaml`, versioned, and recorded on every claim the
report makes (`band_version`).

## The bands

| Percentile | Verdict | Direction |
|---|---|---|
| ≥ 90 | elite | strength |
| 75–89 | strong | strength |
| 40–74 | typical | neutral |
| 15–39 | below par | weakness |
| < 15 | weak | weakness |

Boundaries are inclusive at the bottom: exactly 90 reads *elite*, 89 reads
*strong*.

**These numbers are a starting point, not received wisdom.** They are not
derived from anything — no study, no industry convention, no analysis of
where meaningful breaks fall in these distributions. They are round
numbers chosen so that the layer could be built and argued with. The
version field exists because we expect to change them. If a club tells us
"elite" should mean the top 5% rather than the top 10%, that is a
one-line diff and a version bump, and every report says which version
judged it.

## What a verdict requires

A verdict inherits every suppression rule already in force. There is no
verdict, not even a hedged one, when:

- the metric is below its own `min_sample` (`suppressed`), or
- the benchmark holds fewer than `MIN_BENCHMARK_N` players
  (`benchmark_suppressed`), or
- the value or percentile is missing.

The metric still appears in the report's tables with its existing
suppression text. It simply does not get a sentence. On the current
single-club dataset this leaves the goalkeeper report with no claims at
all, because one goalkeeper clears 450 minutes and a distribution of one
cannot place anybody. That is the correct output, not a gap to work
around.

## How the comparison is stated

Never a bare percentile.

- **Below n = 20**: the ordinal — "highest of 7 midfielders", "4th of 7".
  On a small set the ordinal is the more honest statement, because it
  makes the weakness of the comparison visible instead of hiding it
  behind a decimal. A percentile of 85.7 computed over seven players
  implies a precision that does not exist.
- **At or above n = 20**: the percentile, always with the set size —
  "92nd percentile of 61 midfielders".

Both forms carry the positional median, so the reader sees what the
player is being measured against and not only where they finished.

## Which metrics get surfaced

Up to three strengths and up to three weaknesses, ranked by distance from
the positional median. Fewer if fewer qualify; the report never pads to
reach three, and a player with nothing notable gets no claims.

Distance is measured in **median absolute deviations**, not raw units:
foundation metrics run from expected goals near 0.3 to pass completion
near 90, so a raw distance would rank pass completion first every time.
MAD is the same robust measure the archetype spike used, and it is scale
free.

Metrics in the *typical* band are never surfaced, in either direction.

### The distance floor

Landing in a non-typical band is not enough. A claim must also sit at
least `notable_distance_mads` from the positional median — currently
**1.0 MAD**.

This lives in `bands/verdict_bands.yaml` under the same version as the
bands themselves, because it decides what the report asserts just as much
as they do. A report stamps `band_version`, so changing the floor is a
version bump and a reviewable diff rather than an edit to a constant, and
two reports generated either side of a change are distinguishable. A
bands file that does not declare it fails to load rather than inheriting
a default.

Without the floor, rank noise becomes a verdict. On a comparison set of
seven, a percentile is really an ordinal — 6th of 7 is the 14th
percentile whatever the numbers say — so Xhaka's 1.22 key passes per 90
against a median of 1.26 was being asserted as a weakness. That gap is
about one key pass every thirty matches. One MAD is the point at which a
value is distinguishable from typical rather than merely ordered behind
it.

Metrics judged but held back this way are counted in the report as
`not_notable`, so a thin summary is legible rather than mysterious.

Where a distribution has no spread at all (MAD = 0, meaning at least half
the comparison set share one value), distance has no unit. A player off
that value is treated as maximally distant and ranks first; a player on
it is not notable. The claim records `distance_from_median: null` in that
case rather than an infinity, so the JSON stays valid JSON.

## The direction of a metric is not modelled

A verdict says where a value sits in its positional distribution. It does
not say the value is good.

For most foundation metrics these coincide — more line-break value,
more recoveries, higher pass completion are all better. They do not
coincide everywhere. A centre-back in the 95th percentile for shots gets
"Shots: elite", and whether that is a strength depends on things this
report does not model: whether the side wants that centre-back shooting,
and what he stopped doing to take them.

This is a deliberate limit, not an oversight. The alternative is a
hand-maintained table of which direction is good for which metric in
which position, which is exactly the judgement this layer exists to keep
out of the arithmetic. The claim is a reading of the distribution, stated
plainly enough that a scout can disagree with it.

## What is never generated

Verdicts, the choice of which metrics to surface, and the sentences
themselves are deterministic: table lookup, sorting, and string
formatting. No language model is involved at any point.

If a model is ever added, it joins finished claims into prose. The claim
objects in the report IR carry their own verdict, value, comparison and
band version, so a model can be handed completed claims and nothing else
— it cannot produce a number, choose a verdict, or decide what is
notable, because it is never given the inputs to any of those.
