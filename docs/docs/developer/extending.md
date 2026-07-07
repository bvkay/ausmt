# How to extend AusMT

Ordered recipes for the changes a maintainer will actually make. Each lists the files to touch **in
order** and how to verify. Read [Developer architecture](architecture.md) and
[Portal Data Files](data-files.md) first.

## 1. Add support for a new EDI dialect / processing code

The parser is **`mt_metadata`** (the community library), so most dialects — including Phoenix EMpower
cross-power **SPECTRA**-section EDIs — already parse with no code change. You only act when
mt_metadata mis-reads a file, or omits metadata AusMT relies on.

1. **Does mt_metadata read the transfer function?** Run the build (or `--canonical-dir`) on the file.
   If it reads the impedance but the canonical EMTF XML *round-trip* fails on **metadata**, condition
   it in `engine/ausmt_science/ingest/normalize.py` (`condition_tf` — the sanitisers for
   Site/Survey ids, `geographic_name`, citation, `rotation_angle`, …). If mt_metadata cannot read the
   impedance at all, that is upstream — pin a newer `mt_metadata` or report it.
2. **Header fields mt_metadata leaves empty** live in the kept text helpers in
   `engine/extract/_edi_catalog.py`: `info_coords` / the HEAD/REF/INFO precedence in
   `coords_of` (coordinates + QC), `proc_info` (software/algorithm/remote-ref scrape), and
   `parse_dataid` / `proc_note` (Phoenix `P=…R=…` DATAID → real station + remote site, plus the INFO
   note). Extend these for a new header convention.
3. **Verify**: drop a real sample into `engine/tests/real_dialects/` and add a case to
   `tests/test_real_dialects.py` with a golden assertion against the mt_metadata output, so the
   dialect handling stays locked.

## 2. Add a new derived science product (e.g. wire up `strike`)

The product modules in `engine/ausmt_science/` are **PLANNED stubs** today. The wiring pattern
is `ausmt_science/decomposition/` and the output schema is [Product schema](product-schema.md).

1. Implement `ausmt_science/<product>/__init__.py` — replace the `NotImplementedError` `write()` stub
   with `write(tf, out_dir)`; reuse `_ediparse.pt_params` for any phase-tensor math (do **not** add a
   fourth copy). Heavy products may use the optional MTpy-v2 stack (Tier-3, like decomposition).
2. Define the product's JSON in [Product schema](product-schema.md) and emit it under
   `products/<survey>/<station>/<product>.json` (follow how `build_portal` writes `station.json` /
   `dimensionality.json`).
3. Surface it in the portal: add a tile in `portal/src/drawer.js` `relatedProducts()`.
4. **Verify**: add a unit test (synthetic input → expected output); update
   `science-products.md` to move the product from *Planned* to *Implemented*.

## 3. Add a column to the catalogue (and show it in the portal)

This crosses the positional contract — do all of these together or you will silently corrupt the UI.

1. `contract/columns.json` — append the column name (never reorder), then run
   `python contract/generate.py`. This regenerates `engine/extract/_contract.py` and
   `portal/src/contract.js`; do not hand-edit either generated file. CI runs
   `generate.py --check` and fails on drift.
2. `engine/extract/build_portal.py` — append the value at the matching position in the
   compact row (the build asserts row width equals the column count).
3. [Portal Data Files](data-files.md) — add the new `r[N]` row to the table.
4. Portal consumers: the legend comment in `src/data.js`; the `ST` mapping in `src/main.js`;
   then `filters.js` / `drawer.js` / `exports.js` / `map.js` as needed, always via the named
   index maps (`r[C.*]`).
5. Out-of-repo consumers: `engine/scripts/verify.py` and
   `ausmt-surveys/_validation/contribute.py` read the catalogue positionally; the per-station
   product writes in `build_portal` read `sci` rows by named index. Check all three.
6. **Verify**: rebuild, confirm the width assert passes, run the portal suite. The same
   procedure applies to `sci.json` and `tf.json` columns. A same-width reorder passes the
   width assert and corrupts every consumer, which is why reordering is forbidden.

## 4. Add a field to `survey.yaml` (end to end)

1. `ausmt-surveys/_template/survey.yaml` and `_example/example-survey/survey.yaml` — add the field
   with a comment.
2. `docs/docs/reference/survey-yaml.md` — document it (required vs optional, type).
3. `ausmt-surveys/_validation/validate_survey.py` — if it should be checked/required, add a rule
   (PASS/WARNING/FAIL). The validator tolerates both schema generations; keep that.
4. `engine/extract/build_portal.py` — read it in `survey_meta_from_yaml` (so it flows into
   `surveys.json`/SMETA) and/or in the per-station record if it affects the catalogue.
5. `portal/src/drawer.js` — display it from `SMETA` if user-facing.
6. The **Add Survey page** (`portal/add-survey.html`) — add a form input + emit it in
   `buildSurveyYaml`, if contributors should set it.
7. **Verify**: validate `_example`, rebuild, check `surveys.json`, run the suites.

> Note: without PyYAML the validator uses a small `_mini_yaml` fallback. If your field is a nested
> map or inline `{}`, confirm both PyYAML and the fallback parse it (`tests/test_mini_yaml_parity.py`).

## 5. Run and deploy locally

```bash
# engine (clean all-pip venv recommended)
cd engine
pip install -r requirements-dev.txt          # tests
pip install -r requirements-mtmetadata.txt   # REQUIRED: mt_metadata/mth5 is the sole engine; the build below hard-exits without it (see ABI note)
python scripts/verify.py                      # tests + build + mtcat schema check
python -m extract.build_portal --surveys ../../ausmt-surveys/surveys --out ../portal/data --products products

# portal (must be served over HTTP; it fetches data/*.json)
cd ../portal
python3 -m http.server 8000                   # then open http://localhost:8000/
```

The portal can also fetch data from a remote base by setting `deployment.data_base_url` in
`portal.config.yaml` and regenerating `config.js` (`python tools/gen_config.py --check` is the
CI drift guard).

## 6. Change a science threshold

The dimensionality and phase-tensor thresholds are named constants in
`engine/extract/_edi_science.py` and `_ediparse.py`, and `build_provenance.json` records them
by reading those constants. Change the constant, never a re-typed literal. A threshold change
alters scientific interpretation: it requires a golden-test diff and a scientific
justification in the pull request, not a convenience rationale. See the
interpretation-sensitive list in [Portal Data Files](data-files.md).
