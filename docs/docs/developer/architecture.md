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
survey.yaml + transfer_functions/
      |  validate_survey.py        submission gate; a FAIL skips the survey
      v
   EXTRACT    _mtm (mt_metadata) -> canonical record + component dict; _mth5 for MTH5 input
      v
   SCIENCE    phase tensor, dimensionality, diagnostics (_ediparse.pt_params)
      v
   WRITE      data/*.json, canonical EMTF XML per station, per-survey bundles, per-station
              products
```

Steps, exit codes, run modes, the incremental cache and the verification step are in
[Build lifecycle](build-lifecycle.md).

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

States are fail-closed: RECEIVED, SCANNED, VALIDATED, QUARANTINED, REJECTED_AV, RETURNED,
REJECTED, PUBLISHING, PUBLISH_FAILED, PUBLISHED. Publishing is a git commit and push to `ausmt-surveys`;
serving the result requires a separate engine rebuild by the operator. The curator metadata
editor round-trips survey.yaml through the runner (ruamel.yaml), enforces a semantic-version
bump with release notes, and commits through the same publish path.

## The positional data contract

`catalogue.json`, `sci.json` and `tf.json` are bare arrays decoded by index in two languages,
from one source of order (`contract/columns.json`). Read
[Portal data files](data-files.md) before touching any of the three, and follow the ordered
recipes in [How to extend](extending.md).

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
| `_coordaccess.py` | the C42 coordinate-access mask seam and its per-station byte gate |
| `_conventions.py` | the C25 frame and sign-convention gates run at parse time |
| `_license_text.py` | licence primitives and the rights text shared by the build and the bundles |
| `cache.py` | the incremental build cache (content-addressed, self-verifying entries) |
| `compare_mth5.py` | a standalone EDI-versus-MTH5 ingestion comparison, run from CI |
| `_contract.py` | generated column constants; do not edit by hand |

`engine/ausmt_science/` holds `ingest.normalize` (the canonical EMTF XML store) and planned
product stubs (`strike`, `distortion`, `decomposition`, `exports`, `provenance`, `quicklooks`).
The stubs are not wired into the build.

Gateway (`gateway/`): `app.py` (intake + curator routes), `upload.py` (streamed, capped
intake), `states.py`, `db.py`, `checklist.py`, `publish.py` (preflight, commit, push,
rollback), `orcid.py`, `clamd.py`, and `runner/` (the job loop, safe extraction, validation,
preview, metadata edit). The runner package is what the gw-runner container executes.

Portal (`portal/src/`): plain JavaScript with no module system and no build step. `index.html`
loads scripts in dependency order: `contract, security, state, data, plots, map, filters, drawer,
exports, main, tour`, with `analytics-shim` loaded separately in the head so the page keeps a
`script-src 'self'` policy. `add-survey.html` loads `security`, `contract` and `doi_harvest`, the
last shared byte-for-byte with the curator editor. Presentation only.

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

The four boundaries are stated in [Architecture](../architecture/repositories.md#trust-boundaries).
Their implementation here: content parsing happens only in the network-disabled runner
container, and `safe_component` sanitises DATAID and slug values before they touch paths or
markup. Submitter contact details live only in the gateway database and never enter the package
tree, reports, logs or git. The deployment binds all published ports to loopback; external
access is by the operator's reverse proxy or tailnet (see `deploy/README.md`).

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
