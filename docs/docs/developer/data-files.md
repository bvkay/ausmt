# Portal data files (the producer and consumer contract)

The authoritative definition of the JSON files the `engine` generates and the `portal` reads.

`catalogue.json`, `sci.json` and `tf.json` are POSITIONAL arrays, read by index, not by key: arrays of
bare arrays with no field names, written by position and read by the same hard-coded index in a
different subdirectory and language. Adding or reordering a column shifts every consumer and silently
corrupts the portal. The single source of truth is `contract/columns.json`. To change a column:
(1) edit `contract/columns.json`, (2) run `python contract/generate.py`, which regenerates the engine's
`engine/extract/_contract.py` and the portal's `portal/src/contract.js` named index maps, (3) update
this page, (4) extend any consumer that needs the new field. CI's `generate.py --check` fails on drift,
and the build asserts each row's width; an equal-width reorder passes that assert and corrupts every
consumer, so append, never reorder.

## Row alignment, metadata and observations

`catalogue[i]`, `tf[i]` and `sci[i]` describe the same station: alignment is by array index only, with
no key on the wire. Preserving that alignment is the central data-integrity invariant of the product
set.

Two kinds of value flow through these files. Observations are measured physics: the impedance tensor
and tipper per period with their errors, which become `tf.json` and the phase-tensor fields of
`sci.json`. Metadata is asserted and human-curated: everything in `survey.yaml`, plus processing
strings scraped from EDI text. Metadata must never silently overwrite an observation; where a metadata
assertion corrects an observation (coordinate resolution below), the correction is declared in the
survey package and recorded in provenance.

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
| `qc_report.json` | `build_portal.qc_pass` | curator-facing; not read by the portal runtime |
| `manifest.json` | `extract/build_portal.py` (download manifest) | `portal/src/data.js` (download resolver); validated against `schema/manifest.schema.json` |
| `coord_policy.json` | `extract/build_portal.py` (the coordinate mask seam) | `portal/src/drawer.js`, to badge a generalised or withheld position |
| `base_ids.json` | `extract/build_portal.py` (`_coordaccess.base_station_id`) | the curator workbench, so a per-station coordinate override is keyed by the base station id |

`coord_policy.json` maps `ausmt_id` to coordinate policy for the stations whose policy is not `exact`,
and `base_ids.json` maps `ausmt_id` to base station id for the stations that carry a processing-variant
tag. Both are emitted only when they would carry information, so a consumer treats an absent file as
"every station is exact" or "every station is its own base". Both are documented field by field in
[Served documents](../reference/portal-documents.md#coord_policyjson).

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
diagnostics, not curated ratings. `rr`, `sw` and `alg` are best-effort scrapes of the EDI free text;
mt_metadata exposes no structured processing metadata for these files, so absence means "not stated",
not "not used". `sw` is the program that PROCESSED the transfer function, never the one that wrote the
file; the EDI header's program stamp names an exporter (Geotools, WinGLink, MTpy) on most of the corpus
and is published separately as `processing.file_written_by` in `station.json`. Richer processing detail
(remote site, the file's writer, per-station notes) lives in each station's `station.json` `processing`
block, outside the positional contract.

| Index | Name | Type | Meaning |
|---|---|---|---|
| `sc[0]` | `q` | number\|null | completeness/smoothness diagnostic, 0-5 (NOT a quality ranking); defined under [`station.json` 1.8](../reference/station-products.md#18-diagnostics) |
| `sc[1]` | `qb` | string | basis of `q`: `"e"` error-based, `"s"` shape-based |
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
their positions and values byte for byte, including `t[5] tip_mag`, retained for compatibility even
though the portal no longer plots it.

| Index | Name | Meaning |
|---|---|---|
| `t[0]` | `periods` | period axis, seconds |
| `t[1]` | `rho_xy` | apparent resistivity, xy |
| `t[2]` | `rho_yx` | apparent resistivity, yx |
| `t[3]` | `phs_xy` | phase, xy (degrees) |
| `t[4]` | `phs_yx_adj` | phase, yx (+180° adjusted into the first quadrant) |
| `t[5]` | `tip_mag` | tipper magnitude (kept for compatibility; the portal renders the induction-arrow panel instead) |
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

Both the apparent-resistivity and phase errors are the standard small-error linear propagation from the
single per-component impedance-error magnitude `|dZ|` (mt_metadata's `impedance_error`, a real std;
for an EDI this is `√VAR`). With `ρ = 0.2·T·|Z|²` and `φ = atan2(Im Z, Re Z)`:

- `rho_*_err = 0.4·T·|Z|·|dZ|`
- `phs_*_err = degrees(|dZ| / |Z|)`

Because both come from the one `|dZ|`, the ρ- and φ-error columns cannot diverge. Errors are `null`
where the source carried no impedance error, and (for ρ) only attach where the ρ value itself renders.
These are one-standard-error bars (σ, from the EDI's variance blocks via `√VAR`), not confidence
intervals; an inversion error-floor policy should read them as 1σ. The relative ρ error is
algebraically twice the relative impedance error, and the `mre` diagnostic in `sci.json` is the median
of the resistivity-relative quantity. The complete VAR blocks for all components remain in the served
EDI.

### Tipper frame and placeholder rule (columns `t[14]…t[17]`)

The tipper components are the transfer-function elements `Tx = Hz/Hx` and `Ty = Hz/Hy` as read, with no
sign changes at the data layer; any convention reversal is a presentation concern. The source-data frame
is x = north, y = east, so `Tx` couples the vertical field to the NORTH horizontal field and `Ty` to
the EAST field.

Some EDIs carry an unphysical placeholder tipper: `|T|` identically 1.0 at every period, one component
near 1e-17. At extraction, a tipper with 4 or more present periods whose `|T|` is FLAT
(`max|T| − min|T| < 1e-6`) AND AT UNITY (`||T| − 1| < 1e-3` at every period) is masked wholesale (all
four `tzx/tzy` series and `tip_mag` become `null`) and a build NOTICE names the station. Real tippers
are untouched. This composes with the fill and exact-zero masking.

### Induction-arrow panel and error bars (portal)

The station drawer renders an induction-arrow panel below the phase-tensor plot. Per thinned period: a
REAL arrow in the Parkinson convention, screen `(east, north) = (−tzy_re, −tzx_re)` (real arrows point
toward conductors), and an IMAGINARY arrow unreversed, `(tzy_im, tzx_im)`, drawn lighter, at a fixed
scale with a `|T| = 0.5` corner reference. Stations with an absent or masked tipper show no panel. The
ρ and φ curves gain error bars from `t[10]…t[13]` (ρ in the log domain clipped at a small positive
floor; φ in degrees), drawn only where the error is present; a station whose EDI carries no error
blocks shows no bars and its `q` falls back to the shape basis.

## `surveys.json`: object keyed by survey label

`{ "<survey name>": { …SMETA… } }`, produced by `survey_meta_from_yaml`. Key-based, so safe to extend,
and a key is absent rather than null when a survey declares nothing. The member reference is
[Served documents](../reference/portal-documents.md#surveysjson).

## `manifest.json`: the key-based download index beside the positional catalogue

The field-by-field reference is [Download manifest schema](../reference/manifest-schema.md), and the
fetch patterns are in the
[data reference](../interoperability/api-reference.md#per-station-fetch-through-the-manifest). On the
producer side:

- It is key-based on purpose. Download metadata is added beside the positional arrays, never as new
  `catalogue`/`sci`/`tf` columns. Extend `manifest.json` by adding keys.
- It is written to both the portal data dir and the `--products` dir.
- `sha256` is of the SERVED bytes. The served EDIs and the per-survey EDI zip are byte-reproducible
  across builds (given a fixed zlib and, for generated EDIs, a fixed mt_metadata: the writer stamps
  PROGVERS into the HEAD block, so a toolchain bump moves every generated digest with no data change);
  a copied custodian EDI carries no build clock, and `_reproducible_derived_edi` stamps the one field
  mt_metadata would clock-stamp in a generated one from the source document's own date. EMTF XML, the
  EMTF-XML zip and the transfer-function MTH5 embed timestamps and UUIDs and are not reproducible:
  their digest is a per-build integrity hash, not a cross-build invariant. Do not write a test that
  asserts otherwise.
- A row exists only for what AusMT serves. A non-served station has no row; the portal routes it to the
  source DOI archive via the catalogue's `edi_available` bit (`r[13] = 0`).
- The bundle set is flag-gated by `flags:` in `portal/portal.config.yaml`, mirrored to `config.js` and
  read by the build, and recorded in `build_provenance.json` under `distribution_flags`. The EDI zip
  and the EMTF-XML zip are unconditional for a served survey.

## Derived-product files

The engine writes per-station product files under `products/<survey-slug>/<station>/` (the
`--products` dir): `station.json` and `dimensionality.json`. They are key-based, and their field
reference is [Per-station products](../reference/station-products.md). On the producer side:

- `coordinate_qc` and `canonical_conditioning` are `null` unless the parse flagged something, so an
  unflagged station is never implied to have been touched. `coordinate_policy` is present only when the
  station's policy is not `exact`.
- `--products` is a served surface in a deployment, so it rides the same access gate as
  `tf.json`/`sci.json`. A station in a non-served survey gets a withheld record with `"withheld": true`,
  no derived science, and no `dimensionality.json` at all.
- Every product carries a `provenance` block (input file, sha256, pipeline and parameters).

New products follow the same conventions: emit `products/<survey>/<station>/<product>.json` with a
`method`/citation field, a `screening_diagnostic` or interpretation caveat where relevant, a
`provenance` block, and any companion assets beside the JSON. The wiring steps are in
[How to extend](extending.md#2-add-a-new-derived-science-product-eg-wire-up-strike) and the reference
pattern is `ausmt_science/decomposition/`. Which products exist today is owned by
[Science products](../science/science-products.md).

## Interpretation-sensitive operations

Changes to any of the following alter scientific interpretation and need corresponding review:

1. **Dimensionality classification** (`sc[5]`, `_edi_science.py`). Named threshold constants
   (`SKEW_3D_DEG`, `PCT_PERIODS_3D_THRESHOLD`, `ELLIP_2D_DEG`, `BETA_PHYSICAL_CAP_DEG`,
   `MIN_USABLE_PERIOD_FRAC`); the classifier is the most interpretation-sensitive output in the set.
2. **Phase-tensor mathematics** (`_ediparse.pt_params`, Caldwell et al. 2004). The single
   implementation for every consumer. Its near-singular guard (`PT_MIN_REZ_ROW_SINE`) decides which
   periods are trusted; changing it changes β, azimuth and therefore dimensionality.
3. **Phoenix SPECTRA input.** mt_metadata solves Z from the spectra cross-powers. The single-station form
   of that solve is noise-biased toward zero, a property of the source data's processing. A stated
   remote site is recorded where the header encodes one, but its absence does not prove single-station
   processing.
4. **Apparent-resistivity and phase fallback** (`_ediparse`). Computed from Z when the EDI lacks ρ/φ
   blocks. Computed and file-provided values are not distinguished downstream.
5. **Period thinning** (`_edi_tf`, at most 32 periods). A display reduction only. Science is computed
   from the full-resolution component dict; thinning must never feed back into it.

## Coordinate resolution

Some legacy EDIs carry a floored-DMS HEAD coordinate that conflicts with a decimal INFO coordinate (a
sign-handling bug in historic processing software, worth about 1° of latitude). The build detects the
arithmetic signature and flags the station. The coordinate is replaced only when the survey package
declares a resolution (`coordinate_resolution` in `survey.yaml`); the applied choice, its basis and its
source are recorded, and `r[11]` marks the row. An undeclared conflict stays flagged rather than being
auto-picked.

## The other documents

- `mtcat.json`: the MTCAT discovery document, shape fixed by
  [`schema/mtcat.schema.json`](../reference/mtcat-schema.md) and validated in tests. It declares its
  schema version in `portal.version`; read it there. The recommended integration point for external
  systems.
- `collections.json`: `{ <collection_id>: { id, title, type, surveys[], n_surveys, n_stations, bbox,
  centroid, … } }`; `{}` when no survey declares membership. Reference:
  [Served documents](../reference/portal-documents.md#collectionsjson).
- `build_provenance.json`: the `PROV` block plus corpus counts, distribution flags and cache statistics.
  Optional to the portal. The dimensionality thresholds it records are read from the named constants in
  `_edi_science`, so the recorded parameters cannot drift from the code that ran. Reference:
  [Served documents](../reference/portal-documents.md#build_provenancejson).
- `build_report.json`: structured per-survey build metadata. It reuses the identity helpers `build.json`
  uses, so the recorded commits cannot drift between the two; one shared function produces both its
  `conditioning` array and the build's survey-level `[xml] NOTICE` log lines. Shape fixed by
  `engine/schema/build_report.schema.json`, documented in
  [Build report schema](../reference/build-report-schema.md), validated in the build self-check and
  re-checked by `engine/scripts/verify.py`. The portal runtime does not consume it.
- `qc_report.json`: curator-facing QC findings (duplicate ids, coord flags, near-duplicates,
  out-of-extent). Reference: [Served documents](../reference/portal-documents.md#qc_reportjson).
