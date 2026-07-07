# Developer architecture

This page is the entry point for maintaining or extending the AusMT code. It describes where
everything lives, how data flows, and the boundaries that changes must respect.

## Repositories and top-level layout

The `ausmt` monorepo holds the framework. Survey data lives in the separate `ausmt-surveys`
repository, which has its own lifecycle and access rules.

```text
ausmt-surveys/    curated survey packages: survey.yaml + transfer_functions/ per survey,
                  plus _validation/ (the survey validator and contributor CLI)

ausmt/
  engine/         offline build: survey packages -> validation -> extraction -> science ->
                  portal JSON products, canonical EMTF XML, download bundles
  portal/         static consumer site; reads the generated data/*.json and computes nothing
  gateway/        submission service: upload -> antivirus scan -> validate -> curator review ->
                  publish (a git commit to ausmt-surveys); includes the curator UI and the
                  metadata editor
  deploy/         Docker Compose deployment: images, Makefile, operator runbook
  contract/       the positional column contract shared by engine and portal (single source)
  docs/           this documentation site
  maintainer/     design records: the numbered C-series design documents and ADRs
```

Data flows in one direction: submissions enter through the gateway, reviewed packages are
committed to `ausmt-surveys`, the engine builds products from that repository, and the portal
serves them. The portal never computes science. The engine never serves requests. The gateway
never parses survey content in its own process (see Trust boundaries below).

## The build pipeline

`engine/extract/build_portal.py` is the single build command:

```text
python -m extract.build_portal --surveys <survey-root> --out <out> --products <dir> --bundle-edi
```

Per survey package it runs:

```text
survey.yaml + transfer_functions/
      |  validate_survey.py        submission gate; a FAIL skips the survey
      v
   EXTRACT    mt_metadata reads each EDI (standard and Phoenix SPECTRA dialects) into a
      |       canonical record and component dict (_mtm); MTH5 input goes through _mth5.
      |       EDI, MTH5 and canonical-XML input feed the same downstream math, so
      |       differences between them are parsing and storage round-trip only
      |       (pinned by tests/test_canonical_parity.py).
      v
   SCIENCE    phase tensor, dimensionality, diagnostics; one implementation
      |       (_ediparse.pt_params) shared by every consumer
      v
   WRITE      data/{catalogue,tf,sci,surveys,collections,build_provenance,manifest,
              mtcat,qc_report}.json, canonical EMTF XML per station (xml/<slug>/),
              per-survey EDI and XML zip bundles, products/survey_digests.json
```

An incremental build cache (`--incremental --cache-dir`) keys station products on the EDI
bytes, the engine commit, library versions, the column contract, and the survey.yaml digest.
The verification step (`scripts/verify.py`) is cache-independent: it checks the built products
against schemas and, given `--surveys`, proves every served XML was produced from the current
survey.yaml. A degenerate cache salt (unknown or dirty engine commit) disables the cache for
that build.

Run modes: survey-package mode (`--surveys`, the standard loop) and raw/bulk mode (`--raw` with
`--collections` and `--seed-meta`) for regenerating a seed from loose EDI folders. Raw mode is
excluded from caching.

## The submission pipeline

The gateway is three containers (compose profile `gateway`):

```text
gateway     FastAPI intake + curator UI. Streams uploads to quarantine, enforces size and
            rate caps, tracks state in SQLite. Never parses EDI or YAML content.
clamd       antivirus. An unreachable scanner holds submissions at RECEIVED.
gw-runner   the engine image with the gateway package bind-mounted, network disabled.
            Executes validation, preview builds and metadata edits from a file-based job
            queue. The only component that parses submitted content.
```

States are fail-closed: RECEIVED, SCANNED, VALIDATED, QUARANTINED, RETURNED, REJECTED,
PUBLISHING, PUBLISH_FAILED, PUBLISHED. Publishing is a git commit and push to `ausmt-surveys`;
serving the result requires a separate engine rebuild by the operator. The curator metadata
editor round-trips survey.yaml through the runner (ruamel.yaml), enforces a semantic-version
bump with release notes, and commits through the same publish path.

## The positional data contract

`catalogue.json`, `sci.json` and `tf.json` are bare arrays decoded by index in two languages.
The column order is defined once in `contract/columns.json` and generated into the engine's
`extract/_contract.py` and the portal's `src/contract.js`; CI fails if either generated file is
out of sync. Column order is a published interface: columns are append-only, and a reorder is
a breaking change. Read [Portal Data Files](data-files.md) before touching any of the three
products, and follow the ordered recipes in [How to extend](extending.md).

## Module map

Engine (`engine/extract/`):

| File | Role |
|---|---|
| `build_portal.py` | orchestrator and all JSON output; owns discovery, gating, emission |
| `_mtm.py` | the sole EDI parser (mt_metadata); canonical record + component dict |
| `_mth5.py` | MTH5 transfer-function input, routed through `_mtm` |
| `_ediparse.py` | shared math hub: `pt_params`, rho/phase fallback, read-once cache |
| `_edi_catalog.py` | coordinate reads and QC, `state_of`, DATAID helpers |
| `_edi_tf.py` | TF rows from the component dict (`TF_COLUMNS`) |
| `_edi_science.py` | per-station diagnostics (`SCI_COLUMNS`) |
| `cache.py` | the incremental build cache (content-addressed, self-verifying entries) |
| `_contract.py` | generated column constants; do not edit by hand |

`engine/ausmt_science/` holds `ingest.normalize` (the canonical EMTF XML store) and planned
product stubs (`strike`, `distortion`, `decomposition`, `exports`, `provenance`, `quicklooks`).
The stubs are not wired into the build.

Gateway (`gateway/`): `app.py` (intake + curator routes), `upload.py` (streamed, capped
intake), `states.py`, `db.py`, `checklist.py`, `publish.py` (preflight, commit, push,
rollback), `orcid.py`, `clamd.py`, and `runner/` (the job loop, safe extraction, validation,
preview, metadata edit). The runner package is what the gw-runner container executes.

Portal (`portal/src/`): plain JavaScript with no module system; concatenation order is the
dependency order: `contract, security, state, data, plots, map, filters, drawer, exports,
main, tour`. Presentation only.

## Ownership boundaries

- `ausmt-surveys` owns the definition of a survey and the source bytes. It computes nothing.
  A survey slug is a permanent identifier.
- `engine/` owns all computation and the column order. It hosts no raw time series and no
  presentation logic.
- `gateway/` owns intake, curation state and publication. It never parses survey content in
  its own process and holds no science.
- `portal/` owns presentation. It computes nothing scientific and owns no source of truth.
- `contract/` owns the column order. Both generated forms are committed and CI-checked.
- `docs/` owns the human specification. Where documentation and code disagree, code wins on
  contracts and formulas; documentation wins on governance principles.
- Within the engine, `extract/` is the shipping path and `ausmt_science/` (except
  `ingest`) is planned scaffolding. `_mtm` owns parsing; `_ediparse` owns the phase-tensor
  math. Do not re-implement either elsewhere.

## Trust boundaries

- Submitted packages are untrusted until the validator and a curator pass them. Content
  parsing happens only in the network-disabled runner container. `safe_component` sanitises
  DATAID and slug values before they touch paths or markup.
- Submitter contact details are stored only in the gateway database. They never enter the
  package tree, reports, logs or git.
- Publication is a reviewed git commit. The portal is a read-only consumer.
- The deployment binds all published ports to loopback; external access is by the operator's
  reverse proxy or tailnet. See `deploy/README.md`.

## What must not break

1. Column order and row alignment of `catalogue`, `sci` and `tf`.
2. Uniqueness and stability of `ausmt_id`; it keys URLs, exports and products.
3. The single-source status of `_ediparse.pt_params` and of `contract/columns.json`.
4. The `extract/` and `ausmt_science/` separation (stubs are wired in deliberately or not at
   all).
5. Provenance fidelity: `build_provenance.json` describes what actually ran.
6. Fail-closed behaviour: gateway states, validator resolution, embargo and licence gates
   refuse rather than guess.

## Build, test, run

See the repository root `RUNBOOK-DEV.md` for the test-suite commands, the local portal server,
and the development environment. `deploy/README.md` is the operator runbook for the container
deployment.

## To change something

[How to extend](extending.md) has ordered recipes: new EDI dialect, new science product, new
catalogue column, new survey.yaml field. For anything touching a frozen design decision, read
the relevant `maintainer/C*.md` design record first.
