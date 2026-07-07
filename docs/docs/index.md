# AusMT

AusMT is a survey-centric magnetotelluric data infrastructure for publishing, discovering, preserving and reusing magnetotelluric transfer functions and associated scientific products.

The project provides a consistent framework for managing MT surveys, transfer functions, metadata, provenance records and derived scientific products while supporting modern interoperability standards and long-term stewardship.

Unlike traditional archives that focus on individual files, AusMT treats the survey as the primary scientific object. Survey packages combine transfer functions, metadata, provenance, citations and derived products into a single, curated and reproducible unit.

---

## Why AusMT?

Over the past several decades, hundreds of magnetotelluric surveys have been acquired across Australia by universities, government agencies, research infrastructure facilities and industry.

Many of these datasets remain scientifically valuable, but are often distributed across:

- personal archives
- institutional storage systems
- project websites
- supplementary publication material
- legacy media

In many cases the transfer functions survive, while processing details, metadata or provenance records are lost. In others, detailed reports remain but the underlying data become difficult to locate or reuse.

AusMT aims to address this challenge by providing a consistent framework for:

- survey discovery
- transfer-function access
- metadata preservation
- provenance tracking
- scientific reproducibility
- long-term stewardship

---

## Scope

AusMT focuses on:

- Magnetotelluric transfer functions
- EDI products
- EMTFXML products
- MTH5 transfer-function products
- Survey metadata
- Station metadata
- Provenance records
- Derived scientific products
- Citation information

Derived products may include:

- Apparent resistivity and phase quicklooks
- Tipper products
- Phase tensor products
- Strike analyses
- Dimensionality diagnostics
- Distortion and decomposition products

---

## Out of Scope

AusMT is not a national waveform archive.

Raw time-series data remain in their original repositories, such as:

- National Computational Infrastructure (NCI)
- Institutional repositories
- University archives
- Project-specific archives

Where available, AusMT records persistent identifiers linking survey packages to their associated waveform collections.

This approach avoids duplication while allowing AusMT to focus on the long-term stewardship of transfer functions and scientific products.

---

## Design Principles

AusMT is built around several core principles.

### Survey First

The survey is the primary scientific object.

Stations, transfer functions and derived products exist within the context of a survey package.

### Reproducible

Scientific products should be traceable back to the source data, software and processing workflow used to generate them.

### Interoperable

AusMT adopts existing community standards wherever possible, including MTH5, mt_metadata, EDI and EMTFXML.

### Curated

Publication occurs through validation and review rather than unrestricted upload.

### FAIR and CARE

Metadata, provenance and citation information are treated as first-class products alongside the transfer functions themselves.

---

## System Architecture

AusMT is the `ausmt` monorepo (`engine/`, `portal/`, `docs/`, `maintainer/`) plus the separate `ausmt-surveys` data repo:

```text
ausmt-surveys
↓
engine
↓
portal
```

### ausmt-surveys

The curated collection of published survey packages.

Contains:

- Metadata
- Transfer functions
- Derived products
- Provenance records

### engine

The offline scientific processing engine.

Generates:

- Quicklook products
- Phase tensor products
- Strike analyses
- Dimensionality diagnostics
- Decomposition products

### portal

The public discovery and access interface.

The portal consumes products generated elsewhere and performs no scientific processing.

---

## Intended Audience

AusMT is intended for:

- Researchers
- Students
- Survey custodians
- Data managers
- Research infrastructure operators
- Government agencies
- Future archive maintainers

The project aims to support both the immediate reuse of MT data and its preservation for future generations of researchers.

---

## Next Steps

If you are new to AusMT, the recommended reading order is:

1. What is AusMT?
2. Scientific Philosophy
3. Architecture
4. Data Lifecycle
5. Survey Package Specification

These documents provide the conceptual foundations for the remainder of the system.