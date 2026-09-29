PY ?= python

.PHONY: test laws health truth art art-slice art-characters art-build art-clean art-verify

## Full test suite. DB tests need TEST_DATABASE_URL (and the HOLDOUT_/RESEARCH_
## variables CI sets in .github/workflows/ci.yml); without them they skip.
test:
	$(PY) -m pytest tests -q

## The immutable law tests only (CLAUDE.md: never weakened, skipped or deleted).
laws:
	$(PY) -m pytest tests/laws -q

## docs/BUILD_PLAN.md P1 builds this: the health summary from the production API.
health:
	@echo "make health: not built yet -- docs/BUILD_PLAN.md P1"
	@exit 1

## docs/BUILD_PLAN.md P9 builds this: the nightly truth tests, run locally.
truth:
	@echo "make truth: not built yet -- docs/BUILD_PLAN.md P9"
	@exit 1

## Full pipeline. Fails at normalize_scale if any sprite is still unnamed
## in art/sliced/overrides.json -- that is the intended human checkpoint.
art: art-slice art-characters art-build

## Stages that need no human input.
art-slice:
	$(PY) -m tools.art.recover_alpha
	$(PY) -m tools.art.slice_sheets
	$(PY) -m tools.art.manual_crops
	@echo ""
	@echo "NEXT: edit art/sliced/overrides.json -- set a 'name' for every sprite"
	@echo "      you want kept, or '-' to discard it. Review"
	@echo "      art/sliced/contact_sheet.html while you do. Then: make art-build"

## PixelLab character exports (art/characters/<name>/metadata.json) -- already
## clean RGBA, no human naming step needed, registers straight into overrides.json.
art-characters:
	$(PY) -m tools.art.import_pixellab

## Stages that require overrides.json to be filled in.
art-build:
	$(PY) -m tools.art.normalize_scale
	$(PY) -m tools.art.compute_anchors
	$(PY) -m tools.art.build_palette
	$(PY) -m tools.art.pack_atlas
	$(PY) -m tools.art.verify_atlas

art-verify:
	$(PY) -m tools.art.verify_atlas

## Wipes regenerable intermediates ONLY.
## art/sliced/overrides.json is hand-edited and is NEVER deleted here --
## it holds every naming and anchor decision a human made. Deleting it
## means redoing the entire manual pass. If you truly need it gone,
## delete it by hand, deliberately.
art-clean:
	rm -rf art/recovered art/scaled art/anchored art/review
	find art/sliced -type f ! -name overrides.json -delete
	@echo "kept: art/sliced/overrides.json"
