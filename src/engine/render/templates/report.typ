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
#let mono(s) = text(font: "DejaVu Sans Mono", size: 0.85em)[#s]
#let count(v) = if v == none { muted[—] } else { mono(str(v)) }

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
  · #report.display_minutes minutes
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
  #muted[#claims.none_supported The tables below show what was measured.]
]

#if claims.caveats.len() > 0 [
  #block(above: 8pt)[
    #set text(size: 7pt, fill: rgb("#777777"))
    #claims.caveats.join(" ")
  ]
]

// --- foundation metrics ---------------------------------------------

// Both cells print a string the IR already built (engine/render/format.py).
// They used to format here, in parallel with the summary's Python, and the
// two drifted: "91st percentile of 22 goalkeepers" in the summary against
// "91th of 22" in the table, with impossibilities like "82th of 60" where a
// percentile was dressed as an ordinal.
#let comparison-cell(m) = {
  if m.benchmark_suppressed { muted[n=#m.benchmark_n, too few] }
  else if m.benchmark_comparison == none { muted[n/a] }
  else { [#m.benchmark_comparison] }
}

// The number alone — the unit is its own column, so a column of values
// aligns on the digits instead of being pushed around by "per 90".
#let value-cell(m) = {
  if m.display_number == none { muted[no data] }
  else if m.suppressed { muted[insufficient sample] }
  else { mono(m.display_number) }
}

#let metric-table(rows, with-benchmark) = {
  // Headers, widths and alignment are all built from the same flag. An
  // align tuple longer than the column list silently right-aligns the
  // last column, which is how the panel tables drifted out of step with
  // the foundation one.
  let headers = if with-benchmark {
    ([Metric], [Value], [Unit], [Comparison], [Sample], [Methodology])
  } else { ([Metric], [Value], [Unit], [Sample], [Methodology]) }
  // Both "insufficient sample" and "82nd percentile of 60" have to fit on
  // one line: wrapped, they double the row height, and a table full of
  // them (the goalkeeper's) reads as a mess rather than a considered
  // result.
  let columns = if with-benchmark {
    (1fr, 6.2em, 3.4em, 10.2em, 3.6em, 13.5em)
  } else {
    // No Comparison column here, so the spare width goes to Value: a
    // bootstrap metric prints "0.167 per 90 (0.0304 to 0.298)" and the
    // interval is part of the value, not an optional extra to wrap away.
    (1fr, 12.4em, 3.4em, 3.6em, 12em)
  }
  let alignment = if with-benchmark {
    (left, right, left, right, right, left)
  } else { (left, right, left, right, left) }
  table(
    columns: columns,
    stroke: (x, y) => (bottom: 0.4pt + rgb("#d8d8d8")),
    inset: (x: 4pt, y: 3.5pt),
    align: alignment,
    table.header(..headers.map(h => text(weight: "bold", size: 8.5pt)[#h])),
    ..rows.map(m => (
      [#m.title],
      value-cell(m),
      text(size: 7pt, fill: rgb("#777777"))[#m.unit_label],
      ..if with-benchmark { (comparison-cell(m),) } else { () },
      count(m.sample_size),
      text(size: 6.5pt, fill: rgb("#777777"))[#m.methodology],
    )).flatten(),
  )
}

#section[Foundation metrics]
#metric-table(report.foundation_metrics, true)

#block(above: 4pt)[
  #set text(size: 7pt, fill: rgb("#777777"))
  #if claims.no_comparison != none [#claims.no_comparison #linebreak()]
  // Both progression metrics sit in the table above and a reader will
  // assume they are measured alike. They are not, and the difference
  // changes what a high number means.
  Progressive passes count only completed passes, so they record
  *successful* progression; progressive carries have no completion outcome
  in the data, so a carry ending in a tackle still counts for the ground it
  covered — they record *attempted* progression. See
  docs/metrics/progressive_carries.md.
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
    // Every cell in this table is a per-90 rate, so the unit belongs once
    // in the header rather than as a column repeated across five buckets.
    text(weight: "bold", size: 8.5pt)[Stat (per 90)],
    ..buckets.map(b => text(weight: "bold", size: 8.5pt)[#b.replace("_", " ")]),
  ),
  ..stats.map(s => ([#s], ..buckets.map(b => cell(s, b)))).flatten(),
)
