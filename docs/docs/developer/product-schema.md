# Derived-product schema

The engine writes per-station product files under `products/<survey-slug>/<station>/` (the
`--products` dir). This page defines their shape so new products stay consistent. The portal data
files are defined separately in [Portal Data Files](data-files.md).

## Implemented today (`build_portal.py`)

**`station.json`** — the per-station product record:

```json
{
  "ausmt_id": "au.<slug>.<station>", "station": "<id>", "survey": "<name>",
  "country": "...", "organisation": "...",
  "location": { "lat": 0.0, "lon": 0.0 },
  "data": { "type": "BBMT", "n_periods": 0, "period_min_s": 0.0, "period_max_s": 0.0 },
  "diagnostics": { "median_relative_error": 0.0, "remote_reference": false,
                   "tipper_available": false, "dimensionality": "2-D", "skew_beta_median_deg": 0.0,
                   "completeness_smoothness_diagnostic": { "value": 0.0, "basis": "e",
                     "note": "not a quality or geological-value judgement" } },
  "distribution": { "edi_available": false, "license": "...", "edi_path": null },
  "provenance": { "...PROV...": "...", "input_file": "...", "input_sha256": "..." },
  "coordinate_qc": { "flag": "...", "head_info_conflict_deg": null, "resolution": {} }
}
```

**`dimensionality.json`** — `{ classification, skew_beta_median_deg, pct_periods_3d, method,
screening_diagnostic, note }`.

Every product MUST carry a `provenance` block (input file + sha256 + pipeline/params) so it is
traceable to its source — this is non-negotiable for reproducibility.

## Planned products

The `ausmt_science/` submodules (`strike`, `distortion`, `decomposition`, `quicklooks`, …) are
**PLANNED scaffolding** (their `write()` raises `NotImplementedError`). When implemented, each should
emit `products/<survey>/<station>/<product>.json` following the conventions above:

- a `method`/citation field,
- a `screening_diagnostic`/interpretation caveat where relevant,
- a `provenance` block,
- optional companion assets (e.g. an SVG) alongside the JSON.

See [How to extend → new science product](extending.md) for the wiring steps and
`ausmt_science/decomposition/` for the reference pattern.
