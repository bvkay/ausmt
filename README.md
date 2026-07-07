# AusMT

Australian magnetotelluric (MT) data infrastructure — the **framework monorepo** (see
`maintainer/ADR-001-repo-structure.md`). An offline build engine, a static portal, and a
curated submission gateway: survey packages (EDI + `survey.yaml`) are validated, parsed with
the community mt_metadata/mth5 toolchain, and served as a browsable, citable catalogue.

| Dir | What it is |
|-----|------------|
| `engine/` | offline build engine — survey packages → portal JSON, canonical EMTF XML, bundles |
| `portal/` | static consumer site (map, station drawer, downloads) |
| `gateway/` | submission gateway + curator workflow (FastAPI): upload → AV scan → validate → curate → publish |
| `deploy/` | Docker Compose deployment: images, runbook, Makefile (see `deploy/README.md`) |
| `contract/` | the positional data contract shared by engine and portal — **load-bearing, single-sourced** |
| `docs/` | MkDocs documentation site |
| `maintainer/` | maintainer knowledge base + frozen C-series design docs |

**Where to start**

- Developing or maintaining: [`RUNBOOK-DEV.md`](RUNBOOK-DEV.md) — one page: repo map, how to run
  every test suite, the portal, and which doc owns which subsystem.
- Operating a deployment: [`deploy/README.md`](deploy/README.md) — the Docker runbook.
- Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Deep background and design history: [`maintainer/README.md`](maintainer/README.md).

Survey **data** lives in the separate **`ausmt-surveys`** repo (different lifecycle, scale, and
governance — on a path to NCI THREDDS + DataCite DOIs). The framework consumes it but is versioned
independently of it.

## License

The AusMT **framework** in this repository (`engine/`, `portal/`, `gateway/`, `deploy/`,
`contract/`, `docs/`, `maintainer/`, and tooling) is licensed under the **Apache License 2.0** —
see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

This covers the **software only**. The magnetotelluric **survey data** AusMT processes and serves —
transfer functions and survey metadata — is **not** Apache-licensed: it is licensed individually by its
custodians (typically CC-BY-4.0) and lives in the separate `ausmt-surveys` repo. The sample survey bundled
under `engine/data/` for testing carries its own `LICENSE.md` (CC-BY-4.0).

Copyright 2026 AuScope and the AusMT contributors.
