# Repositories

## Overview

AusMT is the `ausmt` monorepo (with `engine/`, `portal/`, `gateway/`, `docs/`, `contract/`, `deploy/` and `maintainer/` subdirectories), plus the separate `ausmt-surveys` data repository, each with a defined role. The framework monorepo is public; the survey-data repository is private, because it holds embargoed material.

This separation is deliberate. It keeps the public portal lightweight, keeps scientific processing out of the website, and keeps published survey packages separate from code that generates or displays them.

The main components are:

```text
ausmt-surveys     (separate, private data repo)
ausmt/engine
ausmt/gateway
ausmt/portal
ausmt/docs
```

Together they define the AusMT system.

---

## Component Roles

```text
ausmt-surveys     Published survey packages (separate, private repo)
ausmt/engine      Offline processing and product generation
ausmt/gateway     Submission service: upload, scan, validate, curate, publish
ausmt/portal      Public website and machine-readable products
ausmt/docs        System documentation
ausmt/contract    Single-source data contract (columns.json)
ausmt/deploy      Container images and deployment configuration
```

Each component can be maintained and tested independently; the `ausmt` monorepo subdirectories are released together.

---

## ausmt-surveys

ausmt-surveys is the curated survey repository.

It contains the published scientific record used by AusMT.

Typical contents include:

- Collection metadata
- Survey metadata
- Station metadata
- Transfer functions
- Derived products
- Provenance records
- Citation information
- Publication links

The repository is organised around survey packages under `surveys/`, with the validator and
package template alongside:

```text
ausmt-surveys/
├── _template/
├── _validation/
└── surveys/
    ├── auslamp-sa/
    ├── auslamp-tas/
    ├── vulcan-2022/
    └── ...
```

A survey package is deliberately small:

```text
survey-slug/
├── survey.yaml            (all survey and station metadata, provenance and citation fields)
├── README.md              (generated at intake when absent)
├── LICENSE.md             (generated at intake when absent)
└── transfer_functions/
    └── edi/               (one EDI per station occupation)
```

EDI is the accepted submission format today; EMTF XML and MTH5 as *input* formats are gated
by the format decision (D4). Derived products are **not** stored in the package — the engine
generates them at build time from the package contents, so they can be regenerated and
improved without touching the published record. There is no per-station side sheet
(`stations.csv` was considered and rejected): station metadata lives in each EDI and in
`survey.yaml`.

This repository does not contain raw MT time-series data.

Where available, links to external time-series collections are recorded in the survey metadata.

---

## engine

`engine/` (formerly the separate `ausmt-science` repo) is the offline scientific processing engine.

It is responsible for generating derived products from published or staged transfer functions.

Examples include:

- Apparent resistivity and phase curves
- Tipper and induction-arrow products
- Phase tensor products
- Dimensionality diagnostics
- Canonical EMTF XML and download bundles
- Decomposition products (planned)
- Validation reports
- Product manifests

Scientific processing belongs here rather than in the public portal.

This avoids making the website depend on large scientific Python stacks and keeps the published products reproducible.

The engine depends on:

- mt_metadata
- MTH5
- numpy
- PyYAML / ruamel.yaml

Heavier scientific libraries (for example MTpy-v2) are adopted only when a derived product
requires them. All of these dependencies are intentionally kept out of the portal.

---

## portal

`portal/` (formerly the separate `ausmt-portal` repo) is the public discovery and access interface.

It reads published products and metadata generated elsewhere.

The portal is responsible for:

- Map-based discovery
- Collection pages
- Survey pages
- Station pages
- Product previews
- Downloads
- Citation export
- Machine-readable JSON products (a fixed, documented contract)

The portal should not perform scientific processing.

For example, it may display a phase tensor plot, but it should not calculate that plot from an EDI file at request time.

This keeps the portal stable, fast and easier to maintain.

---

## docs

`docs/` (formerly the separate `ausmt-docs` repo) contains the public documentation for the AusMT system.

It describes:

- Project concepts
- Architecture
- Data lifecycle
- Survey package model
- Science products
- Submission workflows
- Validation
- Interoperability
- Reference schemas

The documentation lives in its own subdirectory because it describes the whole system, not just one component.

---

## Information Flow

The usual flow is:

```text
Submission
↓
Gateway (scan, validate, curator review)
↓
Survey package published to ausmt-surveys
↓
Engine build (offline)
↓
Generated data products
↓
Portal display
```

In component terms:

```text
submissions -> ausmt/gateway -> ausmt-surveys -> ausmt/engine -> generated products -> ausmt/portal
```

The engine reads survey packages and writes generated products into the portal's data
directory (the deployment's site-data volume). It does **not** write back into the survey
repository — the only component that writes to `ausmt-surveys` is the gateway's publish
step, as a reviewed git commit.

The portal then consumes the generated products.

---

## Why Keep Survey Data Separate?

AusMT could have been built as a single repository containing code, data, documentation and the website.

That would be simpler at the start, but harder to manage over time.

A single repository would mix together:

- published survey products
- scientific processing code
- website code
- documentation
- validation tooling
- deployment configuration

The code, documentation and website share a release cycle and live together in the `ausmt` monorepo (`engine/`, `portal/`, `docs/`, `maintainer/`).

Published survey products have a different audience and release cycle, so they stay in the separate `ausmt-surveys` repository.

Keeping data separate from code reduces coupling.

---

## Why Not One Repository Per Survey?

A separate repository for every survey is also possible.

For example:

```text
ausmt-survey-kapunda
ausmt-survey-vulcan
ausmt-survey-curnamona
```

This can be useful for very large or independently managed datasets.

However, as a default model it creates unnecessary overhead:

- more repositories to maintain
- more permissions to manage
- more workflows to duplicate
- more places for metadata to drift
- harder discovery across surveys

For most AusMT surveys, one folder per survey inside ausmt-surveys is sufficient.

Dedicated survey repositories may still be appropriate for exceptional cases, such as large national programs or externally governed collaborations.

---

## Trust Boundaries

The repository structure reflects the trust model.

### Submitted material

External submissions are not trusted by default.

The gateway stages them in quarantine, scans and validates them, builds a preview, and a
curator reviews the result before anything is published.

### Published survey packages

Published survey packages represent the curated AusMT record.

They should only contain reviewed products.

### Science outputs

Derived products are generated by controlled workflows.

They should be traceable to input transfer functions and software versions.

### Portal display

The portal displays published products.

It does not create authoritative scientific outputs.

---

## Long-Term Maintenance

The separation of concerns is intended to keep AusMT maintainable as the system grows.

Technologies will change.

The portal may be redesigned.

Scientific processing libraries may evolve.

Documentation may be reorganised.

The core separation should remain stable:

```text
survey products
scientific processing
public access
documentation
```

This makes it easier to replace one component without rewriting the whole system.