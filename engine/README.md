# engine

The scientific processing and catalogue-generation engine for AusMT. The engine validates survey
packages, extracts transfer-function metadata, generates catalogue products, produces screening
diagnostics, and builds the JSON documents consumed by the AusMT Portal.

The engine processes transfer-function products (EDI and MTH5) and does not host or distribute
raw MT time-series data.

> **Maintaining or extending the code?** Start with the developer docs in `docs`:
> `developer/architecture.md` (the system map), `developer/extending.md` (how to add a dialect /
> product / column / `survey.yaml` field), and `developer/data-files.md` (the JSON contract).

---

## Role within AusMT

AusMT is organised as the `ausmt` monorepo (`engine/`, `portal/`, `docs/`, `maintainer/`) plus the
separate `ausmt-surveys` data repo:

| Component | Purpose |
|------------|---------|
| engine | Validation, extraction, catalogue generation, science products, and MTCAT generation |
| ausmt-surveys | Curated survey packages, transfer functions, metadata, and provenance |
| portal | Discovery, visualisation, citation, and contributor interfaces |

Project-wide documentation, standards, governance, and MTCAT specifications are maintained through
the AusMT documentation site (`docs`).

---

## Build workflow

```text
Survey package (survey.yaml + EDI/MTH5)
  ↓ Validation
  ↓ Transfer-function extraction
  ↓ Science products
  ↓ MTCAT generation
  ↓ Portal JSON products
```

Generated outputs (consumed directly by the AusMT Portal):

```text
catalogue.json  tf.json  sci.json  surveys.json  collections.json  mtcat.json  manifest.json
```

The positional shape of these files is defined in `docs` → `developer/data-files.md`.

---

## Run locally

```bash
python -m venv .venv          # Python 3.12 (the tested/locked engine)
source .venv/bin/activate
pip install -r requirements-dev.txt -e .            # tests + the engine package (mt_metadata/mth5)
# for the PINNED, reproducible engine (what CI uses), also install the lock:
pip install -r environments/requirements-mtmetadata-lock.txt
pytest -q
python -m extract.build_portal --surveys data --out portal_data --products products
```

mt_metadata/mth5 is the sole parser since the regex retirement
so it is a core dependency and the build requires
it. `python scripts/verify.py` runs the tests + a build + an MTCAT schema check in one go.

---

## Science products

AusMT distinguishes between authoritative metadata, derived products, screening diagnostics, and
not-provided products. Definitions, provenance policy and classification rules live in the AusMT
documentation site (`docs` → `developer/product-schema.md` and `science/science-products.md`).

Current outputs: transfer-function metadata, period coverage, apparent resistivity and phase, tipper
availability, dimensionality screening diagnostics, collection metadata, survey metadata and
provenance, and MTCAT discovery documents.

AusMT does not provide geological interpretation, prospectivity assessment, resource ranking, or
exploration recommendations.

---

## MTCAT

Each build emits an MTCAT discovery document (`mtcat.json`) — an open JSON schema for magnetotelluric
catalogue discovery, enabling interoperable discovery and metadata exchange across independent MT
catalogue systems. Schema: `docs` → `reference/mtcat-schema.md` / `schema/mtcat.schema.json`.

---

## Testing

The engine includes standalone fixtures and does not require a sibling checkout of other AusMT
components.

```bash
pytest
```

runs the full validation and build test suite.

---

## License

Apache-2.0 — see the repository-root `LICENSE` and `NOTICE`. This covers the engine **software** only. The
magnetotelluric survey **data** the engine processes is licensed separately by its custodians (typically
CC-BY-4.0); the sample survey bundled under `engine/data/` for testing carries its own `LICENSE.md`
(CC-BY-4.0).
