# Portal data files (the producer ↔ consumer contract)

This page is the **authoritative definition** of the JSON files that the `engine` generates and the
`portal` reads. It is the single most important document for anyone changing how data flows
through AusMT.

> **⚠ These are POSITIONAL arrays — read by index, not by key.**
> `catalogue.json`, `sci.json` and `tf.json` are arrays of bare arrays (no field names) for
> compactness. The producer writes them by position and the portal reads them by the **same**
> hard-coded index, in a different subdirectory and language. **Adding or reordering a column shifts
> every consumer and silently corrupts the portal** — there is no key to protect you.
>
> The single source of truth is **`contract/columns.json`** (ADR-001). To change a column: (1) edit
> `contract/columns.json`, (2) run `python contract/generate.py` (regenerates the engine's
> `engine/extract/_contract.py` and the portal's `portal/src/contract.js` named index maps), (3) update
> this page, and (4) extend any consumer that needs the new field. CI's `generate.py --check` fails on
> drift, and the build asserts each row's width — but an equal-width *reorder* is only safe because the
> regenerated indices move in lockstep, so still **append, never reorder**.

## Row alignment, metadata and observations

`catalogue[i]`, `tf[i]` and `sci[i]` describe the same station: alignment is by array index
only, with no key on the wire. Preserving that alignment is the central data-integrity
invariant of the product set.

Two kinds of value flow through these files. Observations are measured physics: the impedance
tensor and tipper per period with their errors, from the transfer-function files, which become
`tf.json` and the phase-tensor fields of `sci.json`. Metadata is asserted and human-curated:
everything in `survey.yaml`, plus processing strings scraped from EDI text. Metadata can be
wrong, stale or absent, and must never silently overwrite an observation; where a metadata
assertion corrects an observation (see Coordinate resolution below), the correction is
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
| `mtcat.json` | `build_portal.mtcat_document` | external harvesters; validated against `schema/mtcat.schema.json` |
| `qc_report.json` | `build_portal.qc_pass` | curator-facing; not read by the portal runtime |
| `manifest.json` | `extract/build_portal.py` (download manifest) | `portal/src/data.js` (download resolver); validated against `schema/manifest.schema.json` |

## `catalogue.json` — one array per station, `r[0..14]`

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
| `r[9]` | `region` | string | survey-driven region facet (`survey.yaml` `region` → `country` → `"?"`) |
| `r[10]` | `file` | string | source transfer-function filename |
| `r[11]` | `coord_flag` | bool | true if the coordinate was flagged/resolved (HEAD/INFO conflict) |
| `r[12]` | `ausmt_id` | string | globally unique id `au.<slug>.<station>` — keys URLs, exports, products |
| `r[13]` | `edi_available` | 0\|1 | 1 if the EDI is redistributably licensed and bundled for download |
| `r[14]` | `sha256` | string | SHA-256 of the source file (provenance/anti-tamper) |

## `sci.json` — one array per station (aligned to `catalogue.json` order), `sc[0..11]`

Source of truth: `SCI_COLUMNS` in `extract/_edi_science.py`. All values are **automated, indicative**
diagnostics, not curated ratings. The `rr`, `sw` and `alg` fields are best-effort scrapes of the
EDI free text; mt_metadata exposes no structured processing metadata for these files, so absence
means "not stated", not "not used". Richer processing detail (remote site, per-station notes)
lives in each station's `station.json` `processing` block, outside the positional contract.

| Index | Name | Type | Meaning |
|---|---|---|---|
| `sc[0]` | `q` | number\|null | completeness/smoothness diagnostic, 0–5 (NOT a quality ranking) |
| `sc[1]` | `qb` | string | basis of `q`: `"e"` error-based, `"s"` shape-based |
| `sc[2]` | `rr` | 0\|1 | remote reference stated in the EDI |
| `sc[3]` | `sw` | string\|null | processing software (scraped) |
| `sc[4]` | `alg` | string\|null | processing algorithm (scraped) |
| `sc[5]` | `dim` | string\|null | dimensionality: `1-D`/`2-D`/`3-D`/`indeterminate`/null (phase-tensor screening) |
| `sc[6]` | `p3d` | integer\|null | % of periods with \|β\| > 3° |
| `sc[7]` | `gd` | 0\|1 | galvanic/static-shift heuristic |
| `sc[8]` | `ellip` | number\|null | median phase-tensor ellipticity |
| `sc[9]` | `skew` | number\|null | median \|β\| (degrees) |
| `sc[10]` | `mre` | number\|null | median relative impedance error |
| `sc[11]` | `decades` | number | period coverage, log10 decades |

## `tf.json` — one entry per station (aligned to `catalogue.json`), each a list of 18 column-arrays

Source of truth: `TF_COLUMNS` in `contract/columns.json` (imported into `extract/_edi_tf.py`). Each entry
is `[col0, col1, …, col17]`, where each `colN` is an array thinned to the SAME ≤ 32-period axis (nulls
where data are absent/invalid/masked). **C20** appended columns `t[10]…t[17]` — APPEND-only; `t[0]…t[9]`
keep their positions and values byte-for-byte (including `t[5] tip_mag`, retained for compatibility even
though the portal no longer plots it).

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

### C20 error propagation (columns `t[10]…t[13]`)

Both the apparent-resistivity and phase errors are the standard small-error **linear propagation** from
the single per-component impedance-error magnitude `|dZ|` (mt_metadata's `impedance_error`, a real std;
for an EDI this is `√VAR`). With `ρ = 0.2·T·|Z|²` and `φ = atan2(Im Z, Re Z)`:

- `rho_*_err = 0.4·T·|Z|·|dZ|`
- `phs_*_err = degrees(|dZ| / |Z|)`

Because both come from the one `|dZ|`, the ρ- and φ-error columns cannot diverge. Errors are `null` where
the source carried no impedance error, and (for ρ) only attach where the ρ value itself renders.

### C20 tipper frame + placeholder rule (columns `t[14]…t[17]`)

The tipper components are the transfer-function elements `Tx = Hz/Hx` and `Ty = Hz/Hy` **as read** — no
sign changes at the data layer (any convention reversal is a presentation concern; see the arrow panel
below). The source-data frame is **x = north, y = east**, so `Tx` couples the vertical field to the
NORTH horizontal field and `Ty` to the EAST field.

**Placeholder-tipper honesty.** Some EDIs carry an unphysical placeholder tipper — observed as `|T|`
identically 1.0 at every period, one component ≈ 1e-17 (a filler, not an estimate). At extraction, a
tipper with ≥ 4 present periods whose `|T|` is FLAT (`max|T|−min|T| < 1e-6`) AND AT UNITY
(`||T|−1| < 1e-3` at every period) is masked WHOLESALE — all four `tzx/tzy` series and `tip_mag` become
`null` — and a build NOTICE names the station. Real (varying, or off-unity) tippers are untouched. This
composes with the C19b fill/exact-zero masking.

### C20 induction-arrow panel + error bars (portal)

The station drawer replaces the `|T|`-magnitude plot with an **induction-arrow panel** rendered below the
phase-tensor plot. Per thinned period, from the log-period axis: a REAL arrow in the **Parkinson
convention** — screen `(east, north) = (−tzy_re, −tzx_re)` (real arrows point toward conductors) — and an
IMAGINARY arrow **unreversed** — `(tzy_im, tzx_im)`, drawn lighter — at a fixed scale with a `|T| = 0.5`
corner reference. Stations with an absent/masked tipper show the no-tipper state (no panel). The ρ and φ
curves gain error bars from `t[10]…t[13]` (ρ in the log domain clipped at a small positive floor; φ in
degrees), drawn only where the error is present.

## `surveys.json` — object keyed by survey label

`{ "<survey name>": { …SMETA… } }`, produced by `survey_meta_from_yaml`. Unlike the arrays above this
is **key-based** (safe to extend). Notable keys: `country`, `region`, `org`, `org_ror`, `version`,
`slug`, `collection`, `software`, `lic`, `doi`, `pid`, `dates`, `investigators`, `funders`, `pubs`,
`blurb`, `access`, `instrument_model`, `edi`, `mth5`, `ts`, `cite`, `coord_resolution`,
`release_notes`. See `survey_meta_from_yaml` for the full, current set.

## `manifest.json` — key-based download index (rides beside the positional catalogue)

Source of truth: [`schema/manifest.schema.json`](../reference/manifest-schema.md) in the `engine`. This
file is the **authoritative index of every downloadable artifact**: per-station EDI/EMTF-XML copies and
per-survey bundles, each with `size` + `sha256` integrity and a tier-resolved `url`.

> **This is NOT new catalogue columns.** Download metadata is added *safely* as a separate **key-based**
> file that rides *beside* `catalogue.json` — the positional `catalogue.json`/`sci.json`/`tf.json` arrays
> are **unchanged**. Extend `manifest.json` by adding keys, not by shifting array indices.

It is written to **both** the portal data dir **and** the `--products` dir.

### Top-level shape

| Key | Type | Meaning |
|---|---|---|
| `generated_count` | integer | total artifacts = `len(files)` + `len(bundles)` |
| `base_url` | string | URL prefix applied to artifact urls; `""` means **portal-relative** (the portal joins it onto its `data_base_url`) |
| `files` | array | per-station downloadable artifacts (see below) |
| `bundles` | array | per-survey bundles (see below) |

Empty build:
`{"generated_count": 0, "base_url": "", "files": [], "bundles": []}`.

### `files[]` — one row per station artifact

| Key | Type | Meaning |
|---|---|---|
| `ausmt_id` | string | globally unique station id (`au.<slug>.<station>`, matches `catalogue.json` `r[12]`) |
| `survey` | string | survey label |
| `station` | string | station id |
| `format` | `"edi"` \| `"emtfxml"` | served artifact format |
| `url` | string\|null | portal-relative path, e.g. `edi/<slug>/<file>.edi`, `xml/<slug>/<station>.xml` (EDIs are namespaced by survey slug, like the XML and bundles); the portal joins it onto `data_base_url`. **`null`** when `tier: "nci"` (see tiers below) |
| `size` | integer | size of the **served** artifact, bytes |
| `sha256` | string | SHA-256 of the **served** artifact (64 hex chars) — download integrity |
| `tier` | `"repo"` \| `"nci"` | where the artifact is served from (see below) |
| `license` | string | license of the served artifact |

### `bundles[]` — one row per survey bundle

| Key | Type | Meaning |
|---|---|---|
| `survey` | string | survey label |
| `slug` | string | survey slug |
| `format` | `"edi-zip"` \| `"xml-zip"` \| `"mth5"` | bundle format (`mth5` = transfer functions only) |
| `url` | string\|null | portal-relative path, e.g. `bundles/<slug>-edi.zip`, `bundles/<slug>-xml.zip`, `bundles/<slug>-tf.h5`; **`null`** for `tier: "nci"` |
| `size` | integer | size of the served bundle, bytes |
| `sha256` | string | SHA-256 of the served bundle (64 hex chars) |
| `tier` | `"repo"` \| `"nci"` | where the bundle is served from |
| `license` | string | license of the served bundle |
| `n_stations` | integer | number of stations in the bundle |

### Semantics

- **`url` resolution.** Urls are **portal-relative by default** (`base_url: ""`); the portal joins each
  `url` onto its `data_base_url`. For `tier: "nci"` the `url` is **`null`** — this tier is **RESERVED**
  for the future NCI/THREDDS migration and no NCI base is configured yet, so the current build emits only
  `tier: "repo"` rows.
- **Integrity, and what is reproducible.** `size`/`sha256` describe the **served** artifact so a consumer
  can verify the bytes it fetched. The EDI copies and the per-survey EDI zip are **byte-reproducible**
  across builds. **EMTF XML (and the EMTF-XML zip) and the transfer-function MTH5 embed timestamps/UUIDs
  and are NOT byte-reproducible** — their `sha256` is a *per-build* integrity hash, not a cross-build
  invariant.
- **Manifest = "what you can download here", with integrity.** Only redistributably-licensed
  (CC\*/CC0/public-domain/ODbL/ODC-BY) **served** surveys appear. A non-served station has **no manifest
  row**; the portal instead routes it to the source DOI archive via the catalogue's `edi_available` bit
  (`r[13] = 0`).
- **Feature flags.** Distribution is gated by a `flags:` block in `portal/portal.config.yaml`
  (default **OFF**), mirrored to `config.js` and read by the build:
  - `survey_h5_enabled` — gates the per-survey transfer-function MTH5 bundle (`bundles/<slug>-tf.h5`).
    Per decision **D4**, MTH5 stays **OFF** pending a storage/management decision. The EDI zip and the
    EMTF-XML zip are unconditional for a served survey.
  - `collection_download_enabled` — **reserved**; no producer yet.

  Both flags are also recorded in `build_provenance.json` under `distribution_flags`.

## Interpretation-sensitive operations

Changes to any of the following alter scientific interpretation, not just presentation, and
need corresponding review:

1. **Dimensionality classification** (`sc[5]`, `_edi_science.py`). Named threshold constants:
   3-D if median |β| exceeds `SKEW_3D_DEG` or the `p3d` share exceeds its threshold; 2-D if
   median ellipticity exceeds `ELLIP_2D_DEG`; otherwise 1-D; `indeterminate` when fewer than
   half the periods are usable. The classifier is the most interpretation-sensitive output in
   the product set.
2. **Phase-tensor mathematics** (`_ediparse.pt_params`, Caldwell et al. 2004). The single
   implementation for every consumer. Its near-singular guard (`PT_MIN_REZ_ROW_SINE`) decides
   which periods are trusted; changing it changes β, azimuth and therefore dimensionality.
3. **Phoenix SPECTRA input**. mt_metadata solves Z from the spectra cross-powers. The
   single-station form of that solve is noise-biased toward zero; this is a property of the
   source data's processing. A stated remote site is recorded where the header encodes one,
   but its absence does not prove single-station processing.
4. **Apparent-resistivity and phase fallback** (`_ediparse`). Computed from Z when the EDI
   lacks ρ/φ blocks. Computed and file-provided values are not distinguished downstream.
5. **Period thinning** (`_edi_tf`, ≤ 32 periods). A display reduction only. Science is
   computed from the full-resolution component dict; thinning must never feed back into it.

## Coordinate resolution

Some legacy EDIs carry a floored-DMS HEAD coordinate that conflicts with a decimal INFO
coordinate (a sign-handling bug in historic processing software, worth ~1° of latitude).
The build detects the specific arithmetic signature and flags the station. The coordinate is
replaced only when the survey package explicitly declares a resolution
(`coordinate_resolution` in `survey.yaml`); the applied choice, its basis and its source are
recorded, and `r[11]` marks the row. An undeclared conflict stays flagged rather than being
silently auto-picked.

## `mtcat.json`, `collections.json`, `build_provenance.json`, `qc_report.json`

- **`mtcat.json`** — the MTCAT v1.0 discovery/federation document; its shape is fixed by
  [`schema/mtcat.schema.json`](../reference/mtcat-schema.md) and validated in tests. This is the
  recommended integration point for external systems (key-based, schema-versioned).
- **`collections.json`** — `{ <collection_id>: { id, title, type, surveys[], n_surveys, n_stations,
  bbox, centroid, … } }`; empty `{}` when no survey declares collection membership.
- **`build_provenance.json`** — `PROV` block: pipeline, pipeline_version, extractor, software,
  git_commit, parameters (the dimensionality thresholds), generated timestamp, plus `n_stations`,
  `n_surveys`, `input_formats`, `edi_bundled`, and the served-tool versions `mt_metadata_version` /
  `mth5_version` (also written to `build.json` and the MTCAT document). Optional — the portal loads
  without it. The dimensionality thresholds it records are read from the named constants in
  `_edi_science`, never re-typed, so the recorded parameters cannot drift from the code that ran;
  provenance describes what actually executed.
- **`qc_report.json`** — curator-facing QC findings (duplicate ids, coord flags, near-duplicates,
  out-of-extent); not consumed by the portal runtime.
