# Portal data files (the producer and consumer contract)

Not a public surface. The files on this page (`catalogue.json`, `sci.json`, `tf.json`, `surveys.json`,
`collections.json`, `build_provenance.json`, `coord_policy.json`, `base_ids.json`, `ts_access.json`, the portal-side use of
`manifest.json`, and the operator-only `build_report.json` and `qc_report.json`) are portal-internal or
operator-only: they carry no public contract and no stability promise, and any build may change or drop
them. This page is the engine-to-portal positional contract, for people working on the portal or the
engine. A consumer reads the public contracts, `mtcat.json`, `survey-metadata.json` and `station.json`,
documented under [Reference](../reference/index.md), and the download index `manifest.json`, documented in the
[data reference](../interoperability/api-reference.md#download-inventory-manifestjson).

The authoritative definition of the JSON files the `engine` generates and the `portal` reads.

`catalogue.json`, `sci.json` and `tf.json` are POSITIONAL arrays, read by index, not by key: bare
arrays with no field names, written by position and read by the same hard-coded index in a different
subdirectory and language. Adding or reordering a column shifts every consumer and silently corrupts the
portal. The single source of truth is `contract/columns.json`. To change a column: (1) edit
`contract/columns.json`, (2) run `python contract/generate.py`, which regenerates
`engine/extract/_contract.py` and `portal/src/contract.js`, (3) update this page, (4) extend any
consumer that needs the new field. CI's `generate.py --check` fails on drift and the build asserts each
row's width; an equal-width reorder passes that assert and corrupts every consumer, so append, never
reorder.

## Row alignment, metadata and observations

`catalogue[i]`, `tf[i]` and `sci[i]` describe the same station; alignment is by array index only, with
no key on the wire, and preserving it is the central data-integrity invariant of the product set.

Observations are measured physics: the impedance tensor and tipper per period with their errors, which
become `tf.json` and the phase-tensor fields of `sci.json`. Metadata is asserted and human-curated:
everything in `survey.yaml`, plus processing strings scraped from EDI text. Metadata must never silently
overwrite an observation; where it corrects one (coordinate resolution below), the correction is
declared in the survey package and recorded in provenance.

## Who produces and consumes what

| File | Produced by | Read by |
|---|---|---|
| `catalogue.json` | `extract/build_portal.py` (`CATALOGUE_COLUMNS`) | `portal/src/main.js` (builds `ST`), `drawer.js`, `exports.js`, `plots.js`; `engine/scripts/verify.py`; `ausmt-surveys/_validation/contribute.py` |
| `sci.json` | `extract/_edi_science.py` (`SCI_COLUMNS`), written by `build_portal.py` | `main.js` (`SCI`), `drawer.js`, `exports.js` |
| `tf.json` | `extract/_edi_tf.py` (`TF_COLUMNS`), written by `build_portal.py` | `main.js` (`TFD`), `drawer.js`, `plots.js`, `exports.js` |
| `surveys.json` | `build_portal.survey_meta_from_yaml` | `main.js` (`SMETA`), `drawer.js`, `exports.js` |
| `collections.json` | `build_portal.collections_document` | `main.js` (`COLL`) |
| `build_provenance.json` | `build_portal.py` (`PROV`) | `data.js` (`PROV`), `drawer.js` provenance panel |
| `build_report.json` | `build_portal.py` (per-survey report accumulator) | the curator serve-state view; validated against `schema/build_report.schema.json`; re-checked by `engine/scripts/verify.py` |
| `mtcat.json` | `build_portal.mtcat_document` | external harvesters; validated against `schema/mtcat.schema.json` |
| `products/<slug>/survey-metadata.json` | `build_portal.survey_metadata_document` | a public contract, not read by the portal; validated against `schema/ausmt-survey-metadata.schema.json`, see [Survey metadata](../reference/survey-metadata.md) |
| `products/<slug>/<station>/station.json` | `build_portal.station_document` | a public contract; `portal/src/drawer.js` reads two members of it (`frame`, `processing.file_written_by`); validated against `schema/ausmt-station.schema.json` and against the semantic layer in `extract/_stationcheck.py`, see [Per-station products](../reference/station-products.md) |
| `qc_report.json` | `build_portal.qc_pass` | curator-facing; not read by the portal runtime |
| `manifest.json` | `extract/build_portal.py` (download manifest) | `portal/src/data.js` (download resolver); validated against `schema/manifest.schema.json` |
| `coord_policy.json` | `extract/build_portal.py` (the coordinate mask seam) | `portal/src/drawer.js`, to badge a generalised or withheld position |
| `base_ids.json` | `extract/build_portal.py` (`_coordaccess.base_station_id`) | the curator workbench, so a per-station coordinate override is keyed by the base station id |
| `ts_access.json` | `extract/build_portal.py` (`_tsproject.route_rows`, from the `--ts-index` register) | `portal/src/data.js`, for the Download block's time-series rows, the Data available filter and the hand-off pointer files |

`coord_policy.json`, `base_ids.json` and `ts_access.json` are emitted only when they would carry
information; a consumer treats an absent file as "every station is exact", "every station is its own
base" or "this deployment publishes no download index". `coord_policy.json`
is in [Portal-internal documents](portal-documents.md#coord_policyjson); `ts_access.json` is in
[the same page](portal-documents.md#ts_accessjson); `base_ids.json`,
`qc_report.json` and `build_report.json` are operator-only and have no public documentation beyond this
table and [the build report](build-lifecycle.md#the-build-report).

## `catalogue.json`: one array per station, `r[0..15]`

Source of truth: `CATALOGUE_COLUMNS` in `extract/build_portal.py`.

| Index | Name | Type | Meaning |
|---|---|---|---|
| `r[0]` | `id` | string | station id (EDI `DATAID`; `<station>.<variant>` when one site has multiple processings) |
| `r[1]` | `survey` | string | survey label (the `survey.yaml` `name`) |
| `r[2]` | `lat` | number | latitude (decimal degrees, WGS84) |
| `r[3]` | `lon` | number | longitude (decimal degrees, WGS84) |
| `r[4]` | `period_min_s` | number\|null | shortest period, seconds |
| `r[5]` | `period_max_s` | number\|null | longest period, seconds |
| `r[6]` | `n_periods` | integer | number of periods |
| `r[7]` | `comps` | string | components present, e.g. `"ZT"` (Z and tipper) |
| `r[8]` | `type` | string | band: `AMT` / `BBMT` / `LPMT` / `GDS` / `unknown` |
| `r[9]` | `region` | string | survey-driven region facet (`survey.yaml` `region`, else `country`, else `"?"`) |
| `r[10]` | `file` | string | source transfer-function filename |
| `r[11]` | `coord_flag` | bool | true if the coordinate was flagged/resolved (HEAD/INFO conflict) |
| `r[12]` | `ausmt_id` | string | globally unique id `au.<slug>.<station>[.<variant>]`; keys URLs, exports, products |
| `r[13]` | `edi_available` | 0\|1 | 1 if the EDI is redistributably licensed and bundled for download |
| `r[14]` | `sha256` | string | SHA-256 of the source file (provenance/anti-tamper) |
| `r[15]` | `site_name` | string\|null | original pre-sanitisation station/site name, emitted only when it differs from `r[0]` (e.g. `SA28_2B` beside `SA282B`); null otherwise |

## `sci.json`: one array per station (aligned to `catalogue.json`), `sc[0..11]`

Source of truth: `SCI_COLUMNS` in `extract/_edi_science.py`. All values are automated, indicative
diagnostics, not curated ratings. `rr`, `sw` and `alg` are best-effort scrapes of the EDI free text, so
absence means "not stated", not "not used". `sw` is the program that PROCESSED the transfer function,
never the one that wrote the file; the header's program stamp names an exporter (Geotools, WinGLink,
MTpy) on most of the corpus and is published separately as `processing.file_written_by` in
`station.json`, whose `processing` block holds the richer detail outside the positional contract.

| Index | Name | Type | Meaning |
|---|---|---|---|
| `sc[0]` | `q` | number\|null | completeness/smoothness diagnostic, 0-5 (NOT a quality ranking); **null on a tipper-only station**, which has no impedance to screen; defined under [`station.json` 1.8](../reference/station-products.md#18-diagnostics) |
| `sc[1]` | `qb` | string | basis of `q`: `"e"` error-based, `"s"` shape-based; `"s"` where `q` is null |
| `sc[2]` | `rr` | 0\|1 | remote reference stated in the EDI |
| `sc[3]` | `sw` | string\|null | the program that processed the transfer function (mined from the file's free text) |
| `sc[4]` | `alg` | string\|null | processing algorithm (scraped) |
| `sc[5]` | `dim` | string\|null | dimensionality: `1-D`/`2-D`/`3-D`/`indeterminate`/null (phase-tensor screening; thresholds under [`dimensionality.json`](../reference/station-products.md#2-dimensionalityjson)) |
| `sc[6]` | `p3d` | integer\|null | % of periods with \|β\| > 3° |
| `sc[7]` | `gd` | 0\|1 | galvanic/static-shift heuristic: resistivity modes offset by a near-constant factor in log space while phases coincide; the station drawer shows a warning |
| `sc[8]` | `ellip` | number\|null | median phase-tensor ellipticity |
| `sc[9]` | `skew` | number\|null | median \|β\| (degrees) |
| `sc[10]` | `mre` | number\|null | median relative apparent-resistivity error (2× the relative impedance error, from `drho/rho = 2·|dZ|/|Z|`) |
| `sc[11]` | `decades` | number | period coverage, log10 decades |

## `tf.json`: one entry per station (aligned to `catalogue.json`), each a list of 18 column-arrays

Source of truth: `TF_COLUMNS` in `contract/columns.json` (imported into `extract/_edi_tf.py`). Each
entry is `[col0, col1, …, col17]`, where each `colN` is an array thinned to the SAME axis of at most 32
periods (nulls where data are absent, invalid or masked). Columns are append-only; `t[0]…t[9]` keep
their positions and values byte for byte, including `t[5] tip_mag`, which the portal no longer plots.

| Index | Name | Meaning |
|---|---|---|
| `t[0]` | `periods` | period axis, seconds |
| `t[1]` | `rho_xy` | apparent resistivity, xy |
| `t[2]` | `rho_yx` | apparent resistivity, yx |
| `t[3]` | `phs_xy` | phase, xy (degrees) |
| `t[4]` | `phs_yx_adj` | phase, yx (+180° adjusted into the first quadrant) |
| `t[5]` | `tip_mag` | tipper magnitude (kept for compatibility) |
| `t[6]` | `pt_min` | phase-tensor Φmin (degrees) |
| `t[7]` | `pt_max` | phase-tensor Φmax (degrees) |
| `t[8]` | `pt_az` | phase-tensor azimuth α−β (degrees, measurement frame) |
| `t[9]` | `pt_beta` | phase-tensor skew β (degrees) |
| `t[10]` | `rho_xy_err` | apparent-resistivity error, xy (Ω·m) |
| `t[11]` | `rho_yx_err` | apparent-resistivity error, yx (Ω·m) |
| `t[12]` | `phs_xy_err` | phase error, xy (degrees) |
| `t[13]` | `phs_yx_err` | phase error, yx (degrees) |
| `t[14]` | `tzx_re` | tipper Tx real (Hz/Hx) |
| `t[15]` | `tzx_im` | tipper Tx imaginary (Hz/Hx) |
| `t[16]` | `tzy_re` | tipper Ty real (Hz/Hy) |
| `t[17]` | `tzy_im` | tipper Ty imaginary (Hz/Hy) |

### Error propagation (columns `t[10]…t[13]`)

Both errors are the standard small-error linear propagation from the single per-component
impedance-error magnitude `|dZ|` (mt_metadata's `impedance_error`, a real std; for an EDI `√VAR`). With
`ρ = 0.2·T·|Z|²` and `φ = atan2(Im Z, Re Z)`: `rho_*_err = 0.4·T·|Z|·|dZ|` and
`phs_*_err = degrees(|dZ| / |Z|)`. Because both come from the one `|dZ|`, the ρ- and φ-error columns
cannot diverge. Errors are `null` where the source carried no impedance error, and (for ρ) only attach
where the ρ value itself renders. These are one-standard-error bars (1σ), not confidence intervals. The
relative ρ error is twice the relative impedance error, and `mre` is the median of the
resistivity-relative quantity. The complete VAR blocks for all components remain in the served EDI.

### Tipper frame and placeholder rule (columns `t[14]…t[17]`)

The tipper components are `Tx = Hz/Hx` and `Ty = Hz/Hy` as read, with no sign changes at the data
layer. The source-data frame is x = north, y = east, so `Tx` couples the vertical field to the NORTH
horizontal field and `Ty` to the EAST field.

Some EDIs carry an unphysical placeholder tipper: `|T|` identically 1.0 at every period, one component
near 1e-17. At extraction, a tipper with 4 or more present periods whose `|T|` is FLAT
(`max|T| − min|T| < 1e-6`) AND AT UNITY (`||T| − 1| < 1e-3` at every period) is masked wholesale (all
four `tzx/tzy` series and `tip_mag` become `null`) and a build NOTICE names the station. This composes
with the fill and exact-zero masking.

### Induction-arrow panel and error bars (portal)

The station drawer renders an induction-arrow panel below the phase-tensor plot. Per thinned period: a
REAL arrow in the Parkinson convention, screen `(east, north) = (−tzy_re, −tzx_re)` (real arrows point
toward conductors), and an IMAGINARY arrow unreversed, `(tzy_im, tzx_im)`, drawn lighter, at a fixed
scale with a `|T| = 0.5` corner reference; no panel for an absent or masked tipper. The ρ and φ curves
gain error bars from `t[10]…t[13]` (ρ in the log domain clipped at a small positive floor; φ in
degrees), drawn only where the error is present; a station whose EDI carries no error blocks shows no
bars and its `q` falls back to the shape basis.

## The key-based documents

`surveys.json` is `{ "<survey name>": { …SMETA… } }`, produced by `survey_meta_from_yaml`; key-based,
so safe to extend, and a key is absent rather than null when a survey declares nothing
([Portal-internal documents](portal-documents.md#surveysjson)).

`manifest.json` is the key-based download index beside the positional catalogue
([Download inventory](../interoperability/api-reference.md#download-inventory-manifestjson)). Download metadata is added beside the
positional arrays, never as new `catalogue`/`sci`/`tf` columns; extend it by adding keys. It is written
to both the portal data dir and the `--products` dir. A row exists only for what AusMT serves; a
non-served station has no row and the portal routes it to the source archive via `r[13] = 0`. The
bundle set is flag-gated by `flags:` in `portal/portal.config.yaml`, mirrored to `config.js`, read by
the build and recorded in `build_provenance.json` under `distribution_flags`; the EDI zip and the
EMTF-XML zip are unconditional for a served survey. Which digests are cross-build invariants is stated
in the [download inventory](../interoperability/api-reference.md#download-inventory-manifestjson); do not write a
test that asserts otherwise.

The per-station products `station.json` (a public contract) and `dimensionality.json` (served alongside
it; not a contract) under `products/<survey-slug>/<station>/` are key-based
([Per-station products](../reference/station-products.md)). `coordinate_qc` and
`canonical_conditioning` are `null` unless the parse flagged something; `coordinate_policy` is present
only when the policy is not `exact`; `runs` and `resources` are present only where a source asserts an
acquisition fact and where the station serves bytes, and absence in both is the open-world statement,
not an empty array. `--products` is a served surface, so it rides the same access gate
as `tf.json`/`sci.json`. `station.json` is written under `<out>/products/` whether or not `--products`
is given, because it is a public contract; passing `--products` writes a second copy there and is what
puts `dimensionality.json` on disk at all. Deployment passes `--products <out>/products`, so the two are
one directory and the served paths are the same either way. Every product carries a `provenance` block,
with one exception: a withheld `station.json` is a closed-world stub of twelve members and carries
none. A new product emits
`products/<survey>/<station>/<product>.json` with a `method`/citation field, a `screening_diagnostic`
or interpretation caveat, a `provenance` block and any companion assets; the steps are in
[How to extend](extending.md#2-add-a-new-derived-science-product-eg-wire-up-strike) and the pattern is
`ausmt_science/decomposition/`.

`mtcat.json` ([MTCAT schema](../reference/mtcat-schema.md)) declares its schema version in
`portal.version`. `build_report.json` ([the build report](build-lifecycle.md#the-build-report))
reuses the identity helpers `build.json` uses, so the recorded commits cannot drift between the two, and
one shared function produces both its `conditioning` array and the build's `[xml] NOTICE` log lines.
`build_provenance.json` records the dimensionality thresholds by reading the named constants in
`_edi_science`, so the recorded parameters cannot drift from the code that ran. `collections.json` is in
[Portal-internal documents](portal-documents.md#collectionsjson).

## Interpretation-sensitive operations

Changes to any of the following alter scientific interpretation and need corresponding review:

1. **Dimensionality classification** (`sc[5]`, `_edi_science.py`): the named threshold constants
   `SKEW_3D_DEG`, `PCT_PERIODS_3D_THRESHOLD`, `ELLIP_2D_DEG`, `BETA_PHYSICAL_CAP_DEG`,
   `MIN_USABLE_PERIOD_FRAC`. The most interpretation-sensitive output in the set.
2. **Phase-tensor mathematics** (`_ediparse.pt_params`, Caldwell et al. 2004): the single implementation
   for every consumer. Its near-singular guard (`PT_MIN_REZ_ROW_SINE`) decides which periods are
   trusted; changing it changes β, azimuth and therefore dimensionality.
3. **Phoenix SPECTRA input**: mt_metadata solves Z from the spectra cross-powers. The single-station form
   of that solve is noise-biased toward zero, a property of the source data's processing. A stated
   remote site is recorded where the header encodes one; its absence does not prove single-station
   processing.
4. **Apparent-resistivity and phase fallback** (`_ediparse`): computed from Z when the EDI lacks ρ/φ
   blocks. Computed and file-provided values are not distinguished downstream.
5. **Period thinning** (`_edi_tf`, at most 32 periods): a display reduction only. Science is computed
   from the full-resolution component dict.

## Coordinate resolution

Some legacy EDIs carry a floored-DMS HEAD coordinate that conflicts with a decimal INFO coordinate (a
sign-handling bug in historic processing software, worth about 1° of latitude). The build detects the
arithmetic signature and flags the station. The coordinate is replaced only when the survey package
declares a resolution (`coordinate_resolution` in `survey.yaml`); the applied choice, its basis and its
source are recorded, and `r[11]` marks the row. An undeclared conflict stays flagged.
