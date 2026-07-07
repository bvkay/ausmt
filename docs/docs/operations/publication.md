# Publication Workflow

## Overview

Publication is the process by which a validated and reviewed survey package becomes part of the curated AusMT record.

Publication occurs after:

```text
Submission
        ↓
Validation
        ↓
Review
        ↓
Publication
```

The objective is to provide a stable, discoverable and citable representation of a survey package while maintaining a clear record of provenance and version history.

Publication is not simply a file transfer operation. It establishes the survey package as an official AusMT release.

---

## Publication Principles

Several principles guide publication within AusMT.

### Curation

Published survey packages have passed validation and review.

Publication indicates that the package satisfies the requirements for inclusion within AusMT.

It does not imply endorsement of scientific interpretations or conclusions.

---

### Reproducibility

Published products should be traceable to their source transfer functions, metadata and provenance records.

Where derived products are generated, the relationships between inputs and outputs should be recorded.

---

### Stability

Users should be able to reference a published survey package with confidence that the cited version will remain identifiable over time.

---

### Transparency

Changes to a survey package should be visible through version history and provenance records.

Users should be able to determine what changed between releases.

---

## Publication Unit

The survey package is the unit of publication.

A publication may include:

- Survey metadata
- Station metadata
- Transfer-function products
- Derived products
- Provenance records
- Citation information
- References to related publications and external resources

Publication occurs at the survey level rather than the individual file level.

---

## Publication Checklist

Before publication, a survey package should satisfy:

### Validation

- Required metadata present
- Package structure valid
- Transfer-function products readable
- Version information present

### Review

- Ownership confirmed
- Licensing confirmed
- Collection assignment confirmed
- CARE considerations reviewed where applicable

### Provenance

- `survey.yaml` processing fields recorded where available
- Version and `release_notes` updated

---

## Derived Products

After publication, the next data rebuild generates the derived products:

- Apparent resistivity and phase (with per-period errors)
- Tipper products and induction arrows
- Phase tensor products
- Dimensionality diagnostics
- Canonical EMTF XML and download bundles

(Strike summaries and decomposition products are planned.)

These products are generated from the published transfer functions into the portal's data
products — they are **not** written back into the survey package, so they can be regenerated
and improved without touching the published record.

---

## Collection Registration

Published surveys are registered within one or more collections.

Examples include:

- AusLAMP
- Institutional holdings
- State-based releases

Collection registration improves discovery and provides organisational context.

---

## Catalogue Registration

Publication includes creation or update of discovery metadata.

This allows the survey package to be discovered through:

- Collection pages
- Search interfaces
- MTCAT records (the machine-readable interface that exists today; a REST API is planned but not
  yet implemented — see [API Overview](../interoperability/api-overview.md))

Discovery metadata are generated from the survey package rather than maintained separately.

---

## Version Assignment

Every publication is associated with a version.

Examples:

```text
1.0.0
Initial publication

1.1.0
Additional provenance and derived products

2.0.0
Reprocessed transfer functions
```

Versioning provides a stable mechanism for tracking the evolution of a survey package.

---

## Citation

Published survey packages should be citable.

Where available, citations may include:

- Survey title
- Version
- DOI or persistent identifier
- Publication date

The DOI, where present, is one supplied by the submitter and minted through an external service (e.g. Zenodo/institutional) — AusMT does not mint DOIs itself; integrated DataCite minting via ARDC is planned, not implemented.

Users should cite the version used in their analysis.

---

## Updating Published Surveys

Publication is not the final stage in a survey package's lifecycle.

Metadata may improve.

Additional provenance may be recovered.

New publication references may become available.

Derived products may be regenerated.

These updates result in a new published version of the survey package.

Earlier versions remain part of the publication history.

---

## Access levels and embargoes

Every survey declares an access level in `survey.yaml`, and the build pipeline **enforces** it — this is
the serving gate, not a documentation convention:

```yaml
access:
  level: open            # open | metadata_only | embargoed
  embargo_until: null    # ISO date YYYY-MM-DD; required in spirit when level is embargoed
```

- **`open`** — the survey's transfer-function bytes are distributed (subject also to a redistributable
  licence). This is the default when the field is absent, matching the legacy all-open corpus.
- **`metadata_only`** — the survey is fully discoverable (catalogue, map, science diagnostics and the
  machine-readable MTCAT record) but **no product bytes are served**: no EDI/EMTF-XML/bundle downloads,
  and `edi_available` is `0`. Downloads route to the source archive.
- **`embargoed`** — same as `metadata_only` (discoverable, bytes withheld) until the embargo lifts.

Embargoes are common for active research projects, industry collaborations and funding-agreement
requirements. Metadata **remains discoverable throughout** an embargo — only the bytes are withheld.

The access level is the **state of record**. A lapsed `embargo_until` date does **not** auto-publish the
survey: releasing data is a deliberate act, so the build keeps an embargoed survey withheld even past its
date and raises a stale-embargo warning for the curator. To release the data, a curator changes
`level` to `open` and re-runs the build. Conversely, an `embargoed` level with no `embargo_until`, or with
an unparseable date, is treated as embargoed indefinitely (fail-closed) with a loud warning.

The submission validator enforces the same contract at the contributor gate: `access.level` must be one of
the three enum values (a hard failure otherwise), `embargo_until` must be an ISO `YYYY-MM-DD` date when
present, any non-`open` level raises a curator-attention warning, and a past-dated embargo raises the
stale-embargo warning.

> Note: the canonical EMTF-XML store (`--canonical-dir`) and the per-station `station.json` products are
> preservation/curation artifacts, not distribution surfaces, and are emitted for all surveys regardless of
> access level — they carry no served download bytes or manifest rows.

---

## Withdrawal and Supersession

In rare circumstances, a published package may need to be withdrawn or superseded.

Examples include:

- Serious metadata errors
- Incorrect product assignment
- Ownership disputes
- Replacement by a corrected version

Where possible, withdrawn packages should remain discoverable with an explanation of their status.

Maintaining a visible publication history is generally preferable to removing records entirely.

---

## Stewardship

Publication marks the point at which a survey package becomes part of the long-term AusMT record.

The role of publication is not simply to make data available today. It is to ensure that future users can discover the survey, understand what was published and identify the version that was used.

As with all parts of AusMT, the emphasis is on preserving both the scientific products and the context needed to understand them.