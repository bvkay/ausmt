# Survey Package

The survey package is the central object in AusMT. Collections organise survey packages, stations
belong to survey packages, transfer functions are published through survey packages, and provenance,
versioning and citation are tracked at the package level.

```text
Collection  ->  Survey Package  ->  Station  ->  Transfer Function
```

A **collection** groups related surveys (a national program, an institutional holding, a state release);
`AusLAMP` grouping `AusLAMP SA` and `AusLAMP Tasmania` is the usual shape. Collections carry discovery
context, not data. A **survey** is the primary scientific object. A **station** is one observation
location within a survey, carrying one or more transfer-function products and their metadata.

## Package structure

```text
survey-slug/
├── survey.yaml            (survey metadata, credit, identifiers, provenance, access)
├── README.md              (generated at intake when absent)
├── LICENSE.md             (generated at intake when absent)
└── transfer_functions/
    ├── edi/               (one EDI per station occupation)
    ├── mth5/              (where a survey has it)
    └── emtfxml/           (where a survey has it)
```

`slug` and the folder name must match; the validator fails the package otherwise.

EDI, EMTF XML and MTH5 are the accepted submission inputs. Processing-software products such as
`.zmm`, `.zrr` and `.j` are opt-in: the validator fails them unless a curator enables them for that
submission, and even then they are stored rather than parsed.

Where one station arrives as both an EDI and an EMTF XML, the EDI is the canonical source and the XML
is kept in the package without being ingested. The build records the ingest source for every station
in `build_report.json`. The build also writes its own canonical EMTF XML for every served station, into
the served data tree rather than back into the package;
[Transfer functions](../science/transfer-functions.md) owns that statement.

There is no per-station side sheet: station metadata lives in each transfer-function file and in
`survey.yaml`. Submitter-side provenance lives in `survey.yaml`'s `processing.*` and free-text fields;
there is no separate provenance file.

Derived products are never stored in the package. The engine generates them at build time, so they can
be regenerated without touching the published record. Raw time series are not stored either; where a
survey's time-series collection has a persistent identifier, `survey.yaml` records it.

Every field is specified in the [survey.yaml reference](../reference/survey-yaml.md).

## Versions and releases

Each package carries a semantic `version` in `survey.yaml` with per-version `release_notes` that the
portal displays. The authoritative history is the survey repository's git history. Immutable
corpus-level release snapshots ship under `/data/releases/`; see [Versioning](versioning.md) and the
[Releases tier](../reference/releases.md).
