# How to extend AusMT

Ordered recipes for the changes a maintainer makes. Each lists the files to touch in order and how to
verify. Read [Developer architecture](architecture.md) and [Portal data files](data-files.md) first.

## 0. Load a real survey into the pipeline

1. **Prepare the package.** Either `cp -r ausmt-surveys/_example/example-survey
   ausmt-surveys/surveys/<your-slug>`, edit `survey.yaml` and drop the transfer functions into
   `transfer_functions/edi/` (and/or `mth5/`); or use the Add Survey page (`portal/add-survey.html`):
   drop your EDIs in the browser, fill the form, confirm station locations on the map (this resolves
   the DMS HEAD/INFO conflict and writes `coordinate_resolution`), then either upload to the submission
   gateway or download the package zip and unzip it under `surveys/<your-slug>/`. The `slug` must equal
   the folder name. Layout: [Survey package](../data-model/survey-package.md#package-structure).

2. **Validate.**

   ```bash
   cd ausmt-surveys
   python _validation/validate_survey.py surveys/<your-slug> --json /tmp/report.json
   ```

   Fix any `FAIL`; WARNINGs (no DOI yet, say) do not block. See the
   [Curator checklist](curator-checklist.md).

3. **Build the portal data.**

   ```bash
   cd ../ausmt/engine
   python -m extract.build_portal --surveys ../../ausmt-surveys/surveys --out ../portal/data --products products
   ```

   The extractor is mt_metadata, a required dependency on Python 3.12 (install
   `environments/requirements-mtmetadata-lock.txt`); the build fails loudly if it is absent, and refuses
   to emit empty products unless `--allow-empty`.

4. **Review and publish.** Gateway submissions land in the curator queue and approval publishes the
   package as a git commit, served after the operator's next data rebuild. For the manual path, open a
   pull request adding `surveys/<your-slug>/`; CI runs the validator and a curator reviews against the
   [Curator checklist](curator-checklist.md).

### Bulk and seed mode

To regenerate a large demo from loose EDI folders without packaging each one:

```bash
python -m extract.build_portal --raw <edi_root> --collections <map.json> --seed-meta <seed.json> \
       --out ../portal/data
```

This path uses `state_of()` to split AusLAMP into per-state surveys; survey-package mode does not, and
raw mode is excluded from the incremental cache.

## 1. Add support for a new EDI dialect / processing code

The parser is mt_metadata, so most dialects, including Phoenix EMpower cross-power SPECTRA-section
EDIs, already parse with no code change. Act only when mt_metadata mis-reads a file or omits metadata
AusMT relies on.

1. Does mt_metadata read the transfer function? Run the build (or `--canonical-dir`) on the file. If it
   reads the impedance but the canonical EMTF XML round-trip fails on metadata, condition it in
   `engine/ausmt_science/ingest/normalize.py` (`condition_tf`: the sanitisers for Site/Survey ids,
   `geographic_name`, citation, `rotation_angle`). If mt_metadata cannot read the impedance at all, that
   is upstream: pin a newer mt_metadata or report it.
2. Header fields mt_metadata leaves empty live in the text helpers in `engine/extract/_edi_catalog.py`:
   `info_coords` and the HEAD/REF/INFO precedence in `coords_of` (coordinates + QC), `proc_info`
   (software/algorithm/remote-ref scrape), and `parse_dataid` / `proc_note` (Phoenix `P=…R=…` DATAID to
   real station + remote site, plus the INFO note). Extend these for a new header convention.
3. Verify: drop a real sample into `engine/tests/real_dialects/` and add a case to
   `tests/test_real_dialects.py` with a golden assertion against the mt_metadata output.

## 2. Add a new derived science product (e.g. wire up `strike`)

The product modules in `engine/ausmt_science/` are planned stubs. The wiring pattern is
`ausmt_science/decomposition/` and the output shape is
[Derived-product files](data-files.md#derived-product-files).

1. Implement `ausmt_science/<product>/__init__.py`: replace the `NotImplementedError` `write()` stub
   with `write(tf, out_dir)`; reuse `_ediparse.pt_params` for any phase-tensor math. Heavy products may
   use the optional MTpy-v2 stack.
2. Define the product's JSON in [Derived-product files](data-files.md#derived-product-files) and emit
   it under `products/<survey>/<station>/<product>.json`, following how `build_portal` writes
   `station.json` / `dimensionality.json`.
3. Surface it in the portal: add a tile in `portal/src/drawer.js` `relatedProducts()`.
4. Verify: add a unit test (synthetic input to expected output); update `science-products.md` to move
   the product from planned to implemented.

## 3. Add a column to the catalogue (and show it in the portal)

This crosses the positional contract; do all of these together.

1. `contract/columns.json`: append the column name (never reorder), then run
   `python contract/generate.py`, which regenerates `engine/extract/_contract.py` and
   `portal/src/contract.js`. Do not hand-edit either generated file. CI runs `generate.py --check`.
2. `engine/extract/build_portal.py`: append the value at the matching position in the compact row (the
   build asserts row width equals the column count).
3. [Portal data files](data-files.md): add the new `r[N]` row to the table.
4. Portal consumers: the legend comment in `src/data.js`; the `ST` mapping in `src/main.js`; then
   `filters.js` / `drawer.js` / `exports.js` / `map.js` as needed, always via the named index maps
   (`r[C.*]`).
5. Out-of-repo consumers: `engine/scripts/verify.py` and `ausmt-surveys/_validation/contribute.py` read
   the catalogue positionally; the per-station product writes in `build_portal` read `sci` rows by
   named index. Check all three.
6. Verify: rebuild, confirm the width assert passes, run the portal suite. The same procedure applies
   to `sci.json` and `tf.json` columns.

## 4. Add a field to `survey.yaml` (end to end)

1. `ausmt-surveys/_template/survey.yaml` and `_example/example-survey/survey.yaml`: add the field with
   a comment.
2. `docs/docs/reference/survey-yaml.md`: document it (required vs optional, type).
3. `ausmt-surveys/_validation/validate_survey.py`: if it should be checked or required, add a rule
   (PASS/WARNING/FAIL). The validator tolerates both schema generations; keep that.
4. `engine/extract/build_portal.py`: read it in `survey_meta_from_yaml` (so it flows into
   `surveys.json`/SMETA) and/or in the per-station record if it affects the catalogue.
5. `portal/src/drawer.js`: display it from `SMETA` if user-facing.
6. The Add Survey page (`portal/add-survey.html`): add a form input and emit it in `buildSurveyYaml`,
   if contributors should set it.
7. Verify: validate `_example`, rebuild, check `surveys.json`, run the suites. Without PyYAML the
   validator uses the `_mini_yaml` fallback; if your field is a nested map or inline `{}`, confirm both
   parse it (`tests/test_mini_yaml_parity.py`).

Two settled conventions:

- **A closed vocabulary fails closed.** If a field's value must come from a fixed set (an access level,
  a contributor role, an identifier type, a data level), an out-of-vocabulary value is a hard FAIL,
  never a warning or a silent coercion, because these fields make claims about somebody else's data or
  rights.
- **Retiring a field means adding a migration, not deleting a reader.** Drop the field from the editor
  UI, leave the engine reading it, add a deprecation WARNING that fires only on a real value, and ship a
  script under `ausmt-surveys/_tools/`.

## 5. Run and deploy locally

```bash
# engine (clean all-pip venv recommended)
cd engine
pip install -r requirements-dev.txt          # tests + the core stack (mt_metadata/mth5 are core deps)
pip install -r environments/requirements-mtmetadata-lock.txt   # the PINNED stack CI runs; see the ABI note in that dir
python scripts/verify.py                      # tests + build + mtcat schema check
python -m extract.build_portal --surveys ../../ausmt-surveys/surveys --out ../portal/data --products products

# portal (must be served over HTTP; it fetches data/*.json)
cd ../portal
python3 -m http.server 8000                   # then open http://localhost:8000/
```

The portal can also fetch data from a remote base by setting `deployment.data_base_url` in
`portal.config.yaml` and regenerating `config.js` (`python tools/gen_config.py --check` is the CI drift
guard).

## 6. Change a science threshold

The dimensionality and phase-tensor thresholds are named constants in `engine/extract/_edi_science.py`
and `_ediparse.py`, and `build_provenance.json` records them by reading those constants. Change the
constant, never a re-typed literal. A threshold change alters scientific interpretation: it requires a
golden-test diff and a scientific justification in the pull request. See the interpretation-sensitive
list in [Portal data files](data-files.md#interpretation-sensitive-operations).
