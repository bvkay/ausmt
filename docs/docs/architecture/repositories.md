# Repositories

## Overview

AusMT is the `ausmt` monorepo (with `engine/`, `portal/`, `docs/` and `maintainer/` subdirectories), plus the separate `ausmt-surveys` data repository, each with a defined role.

This separation is deliberate. It keeps the public portal lightweight, keeps scientific processing out of the website, and keeps published survey packages separate from code that generates or displays them.

The main components are:

```text
ausmt-surveys     (separate data repo)
ausmt/engine
ausmt/portal
ausmt/docs
```

Together they define the AusMT system.

---

## Component Roles

```text
ausmt-surveys     Published survey packages and products (separate repo)
ausmt/engine      Offline processing and product generation
ausmt/portal      Public website and API
ausmt/docs        System documentation
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

The repository is organised around survey packages.

```text
ausmt-surveys/
├── _template/
├── _validation/
├── vulcan-2022/
├── curnamona-2017/
├── kapunda-2019/
└── ...
```

A survey package may include:

```text
survey-slug/
├── survey.yaml
├── stations.csv
├── README.md
├── LICENSE.md
│
├── transfer_functions/
│   ├── edi/
│   ├── emtfxml/
│   └── mth5/
│
├── derived/
│   ├── quicklooks/
│   ├── phase_tensor/
│   ├── strike/
│   ├── dimensionality/
│   └── decomposition/
│
├── provenance/
│   └── provenance.json
│
└── publications/
```

This repository does not contain raw MT time-series data.

Where available, links to external time-series collections are recorded in the survey metadata.

---

## engine

`engine/` (formerly the separate `ausmt-science` repo) is the offline scientific processing engine.

It is responsible for generating derived products from published or staged transfer functions.

Examples include:

- Apparent resistivity and phase plots
- Tipper plots
- Phase tensor products
- Strike summaries
- Dimensionality diagnostics
- Decomposition products
- Validation reports
- Product manifests

Scientific processing belongs here rather than in the public portal.

This avoids making the website depend on large scientific Python stacks and keeps the published products reproducible.

The engine may depend on packages such as:

- MTpy-v2
- mt_metadata
- MTH5
- numpy
- scipy
- pandas
- matplotlib

These dependencies are intentionally kept out of the portal.

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
- API access

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
Survey package
↓
Validation
↓
Science processing
↓
Published products
↓
Portal display
↓
Documentation and citation
```

In component terms:

```text
ausmt-surveys
↓
ausmt/engine
↓
ausmt-surveys
↓
ausmt/portal
```

The engine reads survey packages, generates products, and writes approved outputs back into the survey repository.

The portal then consumes those products.

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

They are staged, validated and reviewed before publication.

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