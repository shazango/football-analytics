.PHONY: install test ingest report clean

export PYTHONPATH := src

install:
	uv sync

test:
	uv run pytest

# Default competition/season: Bundesliga 2023/24 (Bayer Leverkusen) — the
# only open-data slice that's both a full single-club season (needed for
# per-90 / min_sample thresholds) and has 100% 360 coverage. Also required
# by build order step 11 (line_break_value validation against Impect).
COMPETITION ?= 9
SEASON ?= 281

ingest:
	uv run python -m engine.ingest.statsbomb --competition-id $(COMPETITION) --season-id $(SEASON)

# ponytail: wired up once the renderers (build order step 13) exist.
# Definition of done for Phase 0: this writes out/<PLAYER>.pdf,
# out/<PLAYER>.xlsx, out/<PLAYER>.json.
report:
	uv run python -m engine.render.report --player $(PLAYER)

clean:
	rm -rf out/* warehouse/*.duckdb .pytest_cache
