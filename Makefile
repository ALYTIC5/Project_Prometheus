PY ?= python

.PHONY: art art-slice art-build art-clean art-verify

## Full pipeline. Fails at normalize_scale if any sprite is still unnamed
## in art/sliced/overrides.json -- that is the intended human checkpoint.
art: art-slice art-build

## Stages that need no human input.
art-slice:
	$(PY) -m tools.art.recover_alpha
	$(PY) -m tools.art.slice_sheets
	$(PY) -m tools.art.manual_crops
	@echo ""
	@echo "NEXT: edit art/sliced/overrides.json -- set a 'name' for every sprite"
	@echo "      you want kept, or '-' to discard it. Review"
	@echo "      art/sliced/contact_sheet.html while you do. Then: make art-build"

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
