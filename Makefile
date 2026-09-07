.PHONY: install test report clean

install:
	uv sync

test:
	uv run pytest

# ponytail: wired up once ingest (build order step 2) and the renderers
# (step 13) exist. Definition of done for Phase 0: this writes
# out/<PLAYER>.pdf, out/<PLAYER>.xlsx, out/<PLAYER>.json.
report:
	uv run python -m engine.render.report --player $(PLAYER)

clean:
	rm -rf out/* warehouse/*.duckdb .pytest_cache
