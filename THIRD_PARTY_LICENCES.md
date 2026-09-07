# Third-party licences

This project is built entirely on free, openly licensed data and open-source
libraries. No API keys, no credentials, no paid connectors.

## Data

### StatsBomb Open Data
- Source: https://github.com/hudl/open-data
- Licence: free for research and public analytics work
- **Attribution to StatsBomb is required in any published output** that uses
  this data (see the Player Report's attribution line).

### SkillCorner Open Data
- Source: https://github.com/SkillCorner/opendata
- Content: 10 matches of A-League 2024/25 broadcast tracking (10fps) plus
  physical aggregates
- Licence: MIT

## Libraries

| Library | Purpose | Licence |
|---|---|---|
| kloppy | Provider normalisation, pitch coordinate model | BSD-3 |
| socceraction | Possession value (xT, VAEP), SPADL | MIT |
| mplsoccer | Pitch plots, radars | MIT |
| polars | Dataframes | MIT |
| pandas | Dataframes (library boundaries) | BSD-3 |
| duckdb | Local analytical store | MIT |
| statsmodels | Statistics / bootstrapping | BSD-3 |
| scikit-learn | Statistics / modelling | BSD-3 |
| jinja2 | Templating | BSD-3 |
| weasyprint | PDF rendering | BSD-3 |
| xlsxwriter | XLSX rendering | BSD-2 |
| uv | Packaging | MIT / Apache-2.0 |
| pytest | Tests | MIT |

**BSD-3 note (kloppy):** do not use kloppy's or its contributors' names in
any promotional copy.
