# What is AusMT?

## Overview

AusMT is a survey-centric magnetotelluric data infrastructure for the publication, discovery and long-term stewardship of magnetotelluric transfer functions and associated metadata.

The project provides a consistent framework for organising collections, surveys and stations together with the information required to understand, evaluate, reproduce and reuse the resulting scientific products.

AusMT focuses on transfer functions and derived products rather than raw time-series data. Time-series archives remain within their original repositories, while AusMT provides a curated view of the transfer functions, metadata, provenance records and related scientific products derived from those observations.

---

## Why AusMT Exists

Magnetotelluric surveys have been acquired across Australia for more than four decades by universities, government agencies, national research infrastructure facilities and industry.

These datasets represent a significant scientific investment and continue to support research into:

- Lithospheric architecture
- Crustal evolution
- Mineral systems
- Groundwater systems
- Geothermal resources
- Natural hydrogen systems
- Tectonic processes

Many of these datasets remain scientifically valuable long after the original project has concluded.

However, long-term reuse can be difficult.

Common problems include:

- Transfer functions surviving while metadata are lost.
- Metadata surviving while the data become difficult to locate.
- Processing workflows that are undocumented or no longer available.
- Multiple versions of a dataset with no clear authoritative source.
- Survey information distributed across reports, publications and personal archives.
- Inconsistent publication practices between organisations.

AusMT was developed to address these challenges by providing a consistent framework for publishing and managing MT survey products.

---

## Collections, Surveys and Stations

AusMT is organised around three levels:

```text
Collection
↓
Survey
↓
Station
```

### Collection

A collection is a logical grouping of related surveys.

Examples include:

- National programs
- Institutional holdings
- State-based releases

A collection may contain one or more surveys.

Examples:

```text
AusLAMP
├── AusLAMP SA
├── AusLAMP NSW
└── AusLAMP WA

WAMT
├── South West–Esperance
├── Eastern Goldfields
└── Northern Youanmi
```

### Survey

The survey is the primary scientific object within AusMT.

A survey package combines:

- Survey metadata
- Station metadata
- Transfer functions
- Derived products
- Provenance records
- Citation information
- Publications

Researchers typically refer to surveys rather than individual files.

### Station

Stations are individual observation locations within a survey.

Each station may contain one or more transfer-function products together with associated metadata and derived analyses.

---

## Scope

AusMT focuses on the products generated from MT observations.

Supported products include:

- EDI files
- EMTFXML files
- MTH5 transfer-function products
- Survey metadata
- Station metadata
- Provenance records
- Citation records
- Derived scientific products

Examples of derived products include:

- Apparent resistivity and phase plots
- Tipper products
- Phase tensor products
- Strike analyses
- Dimensionality diagnostics
- Distortion and decomposition products

---

## Out of Scope

AusMT is not intended to replace existing time-series archives.

Raw MT time-series data remain within repositories designed for long-term storage and preservation, including:

- National Computational Infrastructure (NCI)
- Institutional repositories
- University archives

Where available, AusMT records persistent identifiers linking transfer-function products to their associated time-series collections.

This approach avoids duplication while maintaining traceability between published products and the underlying observations.

---

## Why the Survey Matters

A collection of EDI files is rarely sufficient to understand a dataset.

Researchers also need:

- Survey context
- Acquisition dates
- Instrumentation details
- Processing information
- Provenance records
- Publications
- Citation information

AusMT therefore treats the survey package, rather than the individual file, as the fundamental unit of publication and discovery.

This reflects how MT datasets are typically managed and cited within the scientific community.

---

## Provenance and Reproducibility

Transfer functions are only one part of a scientific dataset.

Understanding how they were generated is often equally important.

AusMT therefore treats provenance as a core product.

Where available, survey packages record relationships between:

```text
Observations
↓
Processing
↓
Transfer Functions
↓
Derived Products
↓
Publications
```

This information helps users determine what was done, how products were generated and which version of a dataset was used.

---

## Relationship to Existing Standards

AusMT does not introduce new transfer-function formats.

Instead, it adopts and supports existing community standards wherever practical.

Examples include:

- EDI
- EMTFXML
- MTH5
- mt_metadata

This reduces duplication and improves interoperability with existing software, repositories and workflows.

---

## Intended Audience

AusMT is intended for:

- Researchers
- Students
- Survey custodians
- Data managers
- Research infrastructure operators
- Government agencies
- Industry users

The project supports both newly acquired surveys and legacy datasets that remain scientifically valuable.

---

## Long-Term Objective

The objective is simple.

A researcher should be able to discover a collection, identify a survey, obtain the relevant transfer functions, understand how they were generated and cite them correctly.

As datasets age and projects conclude, preserving this context becomes just as important as preserving the files themselves.