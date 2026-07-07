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

The layout is deliberately small:

```text
survey-slug/
├── survey.yaml            (survey and station metadata, provenance, citation, access)
├── README.md              (generated at intake when absent)
├── LICENSE.md             (generated at intake when absent)
└── transfer_functions/
    └── edi/               (one EDI per station occupation)
```

Transfer functions are the authoritative scientific products. Derived products are not
stored in the package — the engine generates them at build time, so they can be regenerated
and improved without touching the published record.

## Releases

Each package carries a semantic `version` in `survey.yaml`, with per-version
`release_notes` that the portal displays. The authoritative history of a package is the
survey repository's git history.

Immutable per-version release archives (a frozen zip per published version, e.g.
`vulcan-2022_v1.0.0_survey-package.zip`) are a **planned** mechanism — see
[Versioning](versioning.md) for the current implementation status.

## Relationship to Other Components

- Collections organise survey packages.
- MTCAT advertises survey packages.
- The portal's machine-readable JSON products expose survey-package metadata.
- The portal visualises survey-package contents.

The survey package is therefore the centre of the AusMT architecture.
