# Survey Package Specification

## Overview

The survey package is the central scientific object within AusMT.

Everything in AusMT ultimately relates back to a survey package. Collections organise survey packages, stations belong to survey packages, transfer functions are published through survey packages, and provenance, versioning and releases are tracked at the survey-package level.

```text
Collection
    ↓
Survey Package
    ↓
Station
    ↓
Transfer Function
```

A survey package is intended to contain everything required to discover, understand, cite and reuse a published MT survey.

## Design Principles

A survey package should:

- Be self-describing.
- Be versioned.
- Be citable.
- Be reproducible.
- Remain understandable independent of the original project.

Raw time-series data are not required to be stored within the package.

## Package Structure

Typical layout:

```text
survey-slug/
├── survey.yaml
├── stations.csv
├── transfer_functions/
├── provenance/
├── releases/
└── README.md
```

Derived products may be included, but transfer functions remain the authoritative scientific products.

## Releases

Survey packages are published through immutable releases.

Each release corresponds to a specific survey-package version.

```text
vulcan-2022_v1.0.0_survey-package.zip
```

The release archive is the object cited, downloaded and preserved.

## Relationship to Other Components

- Collections organise survey packages.
- MTCAT advertises survey packages.
- The API exposes survey-package metadata.
- The portal visualises survey-package contents.

The survey package is therefore the centre of the AusMT architecture.
