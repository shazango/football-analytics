# pass_completion_{defensive,middle,attacking}_third

A ratio, not a per-90 rate — `per_90`/`possession`/`opposition_strength`
don't apply and aren't declared in these metrics' YAML. Value is
completion percentage; sample size is pass attempts (not minutes), so the
`min_sample` threshold here is an attempt count, not a minutes figure.

Pitch is split into three equal bands by the pass's **start** location
(`event.location_x`), using our normalised 0-100 orientation (`x`
increases toward the attacking goal regardless of team/half):

- defensive third: `0 <= x < 33.33`
- middle third: `33.33 <= x < 66.67`
- attacking third: `66.67 <= x <= 100`

Completion = `outcome = 'COMPLETE'`. Passes that went out of play, were
offside, or incomplete all count as attempts but not completions.
