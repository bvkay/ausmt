# Build lifecycle and invariants

This page describes what one build run does, how it reports failure, and the invariants that
operational changes must preserve. The system-level picture is in
[Developer architecture](architecture.md).

## The build, step by step

`python -m extract.build_portal --surveys <dir> --out <data> --products <dir>`:

1. Parse arguments; create the output directories; resolve the survey validator
   (`AUSMT_VALIDATOR_PATH` or the documented search path). An unresolvable validator aborts
   the build rather than ingesting packages unvalidated.
2. Discover survey packages: one folder per survey containing `survey.yaml` and
   `transfer_functions/edi|mth5/`. Folders prefixed `_` are skipped; a package that fails
   validation is skipped and reported.
3. Record provenance: git commit, versions, extractor, dimensionality parameters.
4. Extract: mt_metadata parses each EDI once into a canonical record and component dict.
   Standard and Phoenix SPECTRA dialects are read natively; MTH5 input goes through the same
   component dict.
5. Derive: TF rows, science diagnostics, catalogue rows; coordinate QC and declared
   coordinate resolutions applied; station-id variants disambiguated.
6. QC: duplicate `ausmt_id` values fail the build (exit 2); other findings are reported and
   written to `qc_report.json`.
7. Emit: the JSON product set, per-station products, canonical EMTF XML, bundles, the
   SHA-256 manifest and the digest sidecar.
8. Verify (`scripts/verify.py`, run separately by the deployment Makefile): schema checks
   plus the cache-independent consistency check of served XML against current survey.yaml.

With `--incremental --cache-dir`, unchanged stations are served from the build cache; the
cache can only affect build speed, never output bytes, and a degenerate salt disables it.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success, or an empty build with `--allow-empty` |
| 2 | duplicate `ausmt_id`; or an empty build without `--allow-empty`; or an argument error |
| nonzero via `sys.exit(message)` | the required mt_metadata/mth5 stack is absent, or MTH5 input was requested without `mth5` |

An empty build fails loudly by design: a green run that produced nothing would make every
other green check meaningless.

## Invariants

- **Parity.** The component dict feeds the same downstream mathematics whether the transfer
  function came from an EDI, an MTH5 file, or the canonical EMTF XML. Any difference between
  input formats is parsing or storage round-trip, never science. `tests/test_canonical_parity.py`
  pins this.
- **Traceability.** Every published value traces to a source file (`r[10]`), a content hash
  (`r[14]`), a unique identifier (`r[12]`), and `build_provenance.json`. Changes must keep
  the chain intact.
- **Build/render decoupling.** The portal renders whatever product set its `data_base_url`
  serves. The committed `portal/data/` files are the empty template; real data comes from a
  build output directory (in deployment, `site-data/current`, swapped atomically after
  verification).
- **Package resolution.** `extract` and `ausmt_science` are installed packages (editable
  locally, pip-installed in the engine image); module resolution does not depend on the
  working directory. The runner invokes the engine with an explicit working directory
  (`AUSMT_ENGINE_DIR`) all the same, so the invocation is self-describing.

## Render

The portal loads its scripts in fixed concatenation order, fetches the required products
(catalogue, tf, sci, surveys) and the optional ones (provenance, collections, build), joins
them by array index into the station table, and renders. All exports are client-side and the
portal serves archive pointers, not raw time series.

## Submission

Submissions flow through the gateway (upload, scan, validation, curation, publication), not
through direct pull requests; see [Developer architecture](architecture.md) and
[Submission Workflow](../operations/submission.md). Published packages enter `ausmt-surveys`,
and the next build serves them.
