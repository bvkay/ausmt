# Survey Package

The survey package is the central object in AusMT. Collections organise survey packages,
stations belong to survey packages, transfer functions are published through survey packages,
and provenance, versioning and citation are tracked at the package level.

## Collections, surveys and stations

```text
Collection
    ↓
Survey Package
    ↓
Station
    ↓
Transfer Function
```

A **collection** is a logical grouping of related surveys: a national program, an institutional
holding, a state release. `AusLAMP` grouping `AusLAMP SA` and `AusLAMP Tasmania` is the usual
shape. Collections carry discovery context, not data.

A **survey** is the primary scientific object. Its package combines survey and station
metadata, transfer functions, provenance records, citation information and publication
references into one unit that should stay understandable after the original project ends.

A **station** is one observation location within a survey, carrying one or more
transfer-function products and the metadata that go with them.

## Package structure

The layout is deliberately small:

```text
survey-slug/
├── survey.yaml            (survey metadata, credit, identifiers, provenance, access)
├── README.md              (generated at intake when absent)
├── LICENSE.md             (generated at intake when absent)
└── transfer_functions/
    ├── edi/               (one EDI per station occupation)
    ├── mth5/              (where a survey has it)
    └── emtfxml/           (build output, not an ingest folder)
```

`slug` and the folder name must match; the validator fails the package otherwise.

**EDI and MTH5 are the accepted submission inputs.** EMTF XML and processing-software products
such as `.zmm`, `.zrr` and `.j` are opt-in: the validator fails them unless a curator enables
them for that submission, and even then they are stored rather than parsed.

> `transfer_functions/emtfxml/` in a published package is a **build output**, not an input;
> [Transfer functions](../science/transfer-functions.md) owns that statement and its status.

There is no per-station side sheet. `stations.csv` was considered and rejected: station
metadata lives in each transfer-function file and in `survey.yaml`. Submitter-side provenance
lives in `survey.yaml`'s `processing.*` and free-text fields; there is no separate provenance
file.

**Derived products are never stored in the package.** The engine generates them at build time
from the package contents, so they can be regenerated and improved without touching the
published record. Raw time series are not stored either; where a survey's time-series
collection has a persistent identifier, `survey.yaml` records it.

Every field is specified in the [survey.yaml reference](../reference/survey-yaml.md).

## Versions and releases

Each package carries a semantic `version` in `survey.yaml` with per-version `release_notes`
that the portal displays. The authoritative history is the survey repository's git history.
Immutable per-version release archives are planned; see [Versioning](versioning.md) for what
ships today.

## Relationship to other components

Collections organise survey packages. MTCAT advertises them. The portal's machine-readable
JSON products expose their metadata and the portal visualises their contents.
