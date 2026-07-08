# Metadata Model

## Overview

Metadata provide the information required to understand, discover, interpret and reuse a dataset.

Within AusMT, metadata are treated as scientific products rather than supplementary information.

A transfer function without metadata may be difficult to interpret, difficult to reproduce and difficult to cite.

For this reason, metadata are considered a core component of every survey package.

---

## Objectives

The AusMT metadata model has four primary objectives:

### Discovery

Allow users to find relevant datasets.

Examples include:

- Geographic searches
- Collection searches
- Survey searches
- Organisation searches
- Investigator searches

### Interpretation

Provide sufficient context to understand what was collected and how.

Examples include:

- Survey design
- Instrumentation
- Acquisition dates
- Processing information

### Reproducibility

Record information required to understand how products were generated.

Examples include:

- Processing software
- Product lineage
- Provenance records

### Citation

Support attribution of:

- Surveys
- Investigators
- Organisations
- Publications
- Funding programs

---

## Metadata as a Hierarchy

The AusMT metadata model follows the same organisational structure as the data model:

```text
Collection
↓
Survey
↓
Station
↓
Transfer Function
↓
Derived Product
```

Different metadata belong at different levels.

Understanding these boundaries is important.

---

## Collection Metadata

Collection metadata describe groups of related surveys.

Examples include:

- Collection title
- Collection description
- Custodian organisation
- Geographic coverage
- Time span
- Collection identifiers

Examples of collections include:

- AusLAMP
- Institutional holdings
- State-based releases

Collection metadata provide broad discovery context.

---

## Survey Metadata

Survey metadata describe a specific survey.

Examples include:

- Survey title
- Survey identifier
- Abstract
- Principal investigators
- Organisations
- Funding sources
- Acquisition dates
- Geographic extent
- Licence information
- Related publications

Survey metadata provide the primary discovery and citation information used within AusMT.

---

## Station Metadata

Station metadata describe individual observation locations.

Examples include:

- Station identifier
- Coordinates
- Elevation
- Deployment dates
- Instrumentation
- Sensor orientations

Station metadata provide the observational context required for transfer functions and derived products.

---

## Transfer Function Metadata

Transfer-function metadata describe the published MT products.

Examples include:

- Product format
- Period range
- Processing software
- Processing version
- Creation date
- Product identifiers

These metadata help users understand how a transfer function was generated and how it should be interpreted.

---

## Derived Product Metadata

Derived products should retain links to the transfer functions from which they were generated.

Examples include:

- Product type
- Creation date
- Software version
- Source transfer function
- Processing parameters

This information supports provenance and reproducibility.

---

## Persistent Identifiers

AusMT encourages the use of persistent identifiers wherever practical.

Persistent identifiers improve discoverability and reduce ambiguity.

> **Implementation status (current).** AusMT records DOIs supplied by the submitter (e.g. a
> Zenodo or institutional DOI minted externally) — it does not mint or register identifiers
> itself. Integrated DataCite DOI minting via ARDC is planned for a future slice, not implemented.
> ORCID (investigators), ROR (organisations), instrument PIDs and RAiD (projects) have fields in
> `survey.yaml`; how much of each propagates into the portal's served products is still partial
> and being completed field by field.

Examples include:

### DOI

Used to identify:

- Datasets
- Publications

### ORCID

Used to identify:

- Investigators
- Contributors

### ROR

Used to identify:

- Organisations
- Institutions

### RAiD

Used to identify:

- Research projects
- Research activities

Not all surveys will contain all identifier types.

The metadata model is designed to accommodate varying levels of identifier availability.

---

## Relationship to Existing Standards

AusMT does not define a new MT metadata standard.

Instead, it builds upon existing community standards.

Examples include:

- mt_metadata
- MTH5
- EMTFXML metadata
- DOI metadata
- ORCID
- ROR

Where established standards exist, they should be used in preference to project-specific alternatives.

---

## Required and Optional Metadata

Not all surveys contain the same level of metadata completeness.

This is particularly true for historical datasets.

The metadata model therefore distinguishes between:

### Required Metadata

Minimum information required for publication.

Examples include:

- Survey title
- Survey identifier
- Geographic location
- Transfer-function products

### Recommended Metadata

Information that substantially improves reuse.

Examples include:

- Investigators
- Organisations
- Acquisition dates
- Publications

The objective is to encourage publication of valuable historical datasets without imposing unrealistic requirements.

---

## Metadata Quality

Completeness and quality vary between datasets.

Validation therefore focuses on:

- Consistency
- Structure
- Discoverability

rather than attempting to enforce perfect metadata.

Historical surveys frequently remain scientifically valuable despite incomplete records.

The metadata model is intended to support these datasets while encouraging improvements over time.

---

## Metadata and Provenance

Metadata and provenance are closely related but serve different purposes.

Metadata describe a product.

Provenance describes how that product came into existence.

For example:

```text
Metadata:
    Survey title
    Acquisition dates
    Investigator

Provenance:
    Processing software
    Product lineage
    Derived products
```

Both are required to fully understand a scientific dataset.

---

### Governance Metadata

Some datasets may contain governance information beyond traditional scientific metadata.

Examples include:

- Access conditions
- Usage constraints
- Indigenous data governance requirements
- Embargo information

These metadata help ensure that datasets remain discoverable while respecting applicable governance requirements.

---

## Long-Term Perspective

The value of metadata often increases with time.

Immediately after a survey is completed, many details remain known by the project team.

Years later, metadata may become the primary source of information describing how a dataset was collected and used.

For this reason metadata are treated as part of the scientific record rather than supplementary documentation.

A transfer function can often survive for decades.

Understanding what it represents depends on the metadata that accompany it.