// Player Report, PDF (build order step 13, brief §9: "board-ready").
//
// Reads report.json — the exact IR the JSON renderer writes — from the
// directory it is compiled in. Nothing is computed here: every number is
// projected, and the two presentation rules the document applies
// (suppression text, ordinal vs percentile) are driven by flags and
// thresholds the IR already carries.
//
// Fonts are the ones bundled with the typst wheel (Libertinus Serif,
// DejaVu Sans Mono), never the host's. Typst falls back silently on a
// missing font, so asking for Helvetica would render differently on a
// machine that has it than on one that doesn't — and the point of this
// renderer is that it produces the same document anywhere.

#let report = json("report.json")

#let muted(body) = text(fill: rgb("#8a8a8a"), style: "italic", size: 0.85em)[#body]

// Typst prints floats with trailing zeros stripped, so a column of
// rounded values comes out as "2", "1.31", "90.0" — ragged and hard to
// scan. Pad back to a fixed width.
#let fixed(v, digits) = {
  let s = str(calc.round(v, digits: digits))
  if digits <= 0 { return s }
  if not s.contains(".") { s = s + "." }
  s + "0" * calc.max(0, digits - s.split(".").at(1).len())
}

// Three significant figures, the same rule the claim sentences use
// (docs/verdict_bands.md), so a value never appears two ways in one
// document: 0.0468 in the summary and 0.05 in the table.
#let sig3(v) = {
  if v == 0 { return "0.00" }
  fixed(v, calc.max(0, 2 - calc.floor(calc.log(calc.abs(v), base: 10))))
}

#let mono(s) = text(font: "DejaVu Sans Mono", size: 0.85em)[#s]
#let num(v) = if v == none { muted[—] } else { mono(sig3(v)) }
#let count(v) = if v == none { muted[—] } else { mono(fixed(v, 0)) }

#set page(
  paper: "a4",
  margin: (x: 1.6cm, y: 1.5cm),
  footer: context [
    #set text(size: 6.5pt, fill: rgb("#777777"))
    #report.attribution
    #linebreak()
    Generated #report.generated_at.
    Verdict bands v#report.claims.band_version (#report.claims.methodology).
    #h(1fr)
    #counter(page).display("1 of 1", both: true)
  ],
)
#set text(font: "Libertinus Serif", size: 9.5pt, lang: "en")
#set par(justify: false, leading: 0.55em)

#let section(title) = block(above: 14pt, below: 6pt)[
  #set text(size: 11pt, weight: "bold")
  #title
  #v(-4pt)
  #line(length: 100%, stroke: 0.8pt + black)
]

// --- identity -------------------------------------------------------

#text(size: 19pt, weight: "bold")[#report.name]
#linebreak()
#text(size: 9pt, fill: rgb("#555555"))[
  #report.primary_position (#report.position_bucket)
  · #calc.round(report.minutes, digits: 0) minutes
  · #report.competition.name #report.competition.season
]

// --- summary: the part a manager reads ------------------------------

#section[Summary]

#let claims = report.claims
#let all-claims = claims.strengths + claims.weaknesses

#if all-claims.len() > 0 [
  #for c in all-claims [
    // Labelled so `typst query '<claim>'` can read back what this
    // document actually says — the cross-renderer test compares the
    // compiled PDF's claims against the JSON's, rather than trusting
    // that a template which compiled also rendered the right sentences.
    #metadata(c.headline + " " + c.evidence) <claim>
    #block(below: 7pt, width: 100%)[
      #text(weight: "bold")[#c.headline] #c.evidence
    ]
  ]
] else [
  #muted[
    No claim in this report is supported by the data. Of
    #(claims.suppressed + claims.eligible) foundation metrics,
    #claims.suppressed fall below their sample threshold or have too small a
    comparison set to rank against. The tables below show what was measured.
  ]
]

#block(above: 8pt)[
  #set text(size: 7pt, fill: rgb("#777777"))
  #if claims.suppressed > 0 [
    #claims.suppressed of #(claims.suppressed + claims.eligible) foundation
    metrics could not be judged — sample or comparison set too small.
  ]
  #if claims.not_notable > 0 [
    #claims.not_notable sat outside the typical band but within
    #claims.notable_distance_mads MAD of the positional median — too close to
    assert.
  ]
]

// --- foundation metrics ---------------------------------------------

#let comparison-cell(m) = {
  if m.benchmark_suppressed {
    muted[n=#m.benchmark_n, too few]
  } else if m.benchmark_percentile == none {
    muted[n/a]
  } else if m.benchmark_n < claims.ordinal_below_n {
    // Below the ordinal threshold a percentile can only take n values;
    // the rank is the honest form (docs/verdict_bands.md).
    [#m.benchmark_rank of #m.benchmark_n]
  } else {
    [#calc.round(m.benchmark_percentile * 100, digits: 0)#super[th] of #m.benchmark_n]
  }
}

#let value-cell(m) = {
  if m.value == none { muted[no data] }
  else if m.suppressed { muted[insufficient sample] }
  else { num(m.value) }
}

#let metric-table(rows, with-benchmark) = {
  // Headers, widths and alignment are all built from the same flag. An
  // align tuple longer than the column list silently right-aligns the
  // last column, which is how the panel tables drifted out of step with
  // the foundation one.
  let headers = if with-benchmark {
    ([Metric], [Value], [Comparison], [Sample], [Methodology])
  } else { ([Metric], [Value], [Sample], [Methodology]) }
  // "insufficient sample" has to fit on one line: wrapped over two it
  // doubles the row height and a table of suppressions (the goalkeeper's)
  // reads as a mess rather than as a considered result.
  let columns = if with-benchmark {
    (1fr, 8.6em, 6em, 3.6em, 15em)
  } else { (1fr, 8.6em, 3.6em, 15em) }
  let alignment = if with-benchmark {
    (left, right, right, right, left)
  } else { (left, right, right, left) }
  table(
    columns: columns,
    stroke: (x, y) => (bottom: 0.4pt + rgb("#d8d8d8")),
    inset: (x: 4pt, y: 3.5pt),
    align: alignment,
    table.header(..headers.map(h => text(weight: "bold", size: 8.5pt)[#h])),
    ..rows.map(m => (
      [#m.title],
      value-cell(m),
      ..if with-benchmark { (comparison-cell(m),) } else { () },
      count(m.sample_size),
      text(size: 6.5pt, fill: rgb("#777777"))[#m.methodology],
    )).flatten(),
  )
}

#section[Foundation metrics]
#metric-table(report.foundation_metrics, true)

#let no-comparison = report.claims.benchmark_suppressed_count
#if no-comparison > 0 [
  #block(above: 4pt)[
    #set text(size: 7pt, fill: rgb("#777777"))
    Comparison unavailable for #no-comparison of
    #report.foundation_metrics.len() metrics: fewer than
    #report.foundation_metrics.at(0).benchmark_min_n qualifying players in the
    #report.position_bucket bucket for this competition and season. The values
    themselves are measured and shown; only the ranking is withheld.
  ]
]

// --- position panel --------------------------------------------------

#if report.position_panel != none [
  #section[#report.position_bucket panel]
  #metric-table(report.position_panel, false)
]

#if report.throw_in_profile != none [
  #section[Throw-in profile]
  #metric-table(report.throw_in_profile, false)
]

// --- game state ------------------------------------------------------

#section[Game-state response]

#let gs = report.game_state_response
#let buckets = gs.map(r => r.bucket).dedup()
#let stats = gs.map(r => r.stat_id).dedup()
#let cell(stat, bucket) = {
  let hit = gs.filter(r => r.stat_id == stat and r.bucket == bucket)
  if hit.len() == 0 { muted[—] } else { value-cell(hit.at(0)) }
}

#table(
  columns: (auto,) + buckets.map(_ => 1fr),
  stroke: (x, y) => (bottom: 0.4pt + rgb("#d8d8d8")),
  inset: (x: 4pt, y: 3pt),
  align: (left,) + buckets.map(_ => right),
  table.header(
    text(weight: "bold", size: 8.5pt)[Stat],
    ..buckets.map(b => text(weight: "bold", size: 8.5pt)[#b.replace("_", " ")]),
  ),
  ..stats.map(s => ([#s], ..buckets.map(b => cell(s, b)))).flatten(),
)
