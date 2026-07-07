# Metadata Exchange

## Overview

Metadata exchange is the process by which information describing collections, surveys and products is shared between repositories, catalogues and discovery systems.

Within AusMT, metadata exchange supports interoperability without requiring datasets to be duplicated or transferred between organisations.

The objective is straightforward:

> A dataset should be discoverable beyond the repository in which it was originally published.

Metadata exchange allows repositories to remain independent while participating in a broader discovery ecosystem.

---

## Why Metadata Exchange?

Many MT datasets already exist within:

- Universities
- Government agencies
- Geological surveys
- Research infrastructure facilities
- National repositories

These organisations often maintain their own systems, identifiers and workflows.

Requiring all datasets to be moved into a single repository would create unnecessary duplication and increase long-term maintenance requirements.

Metadata exchange provides an alternative approach.

Rather than exchanging scientific products, repositories exchange descriptions of those products.

---

## Scientific Products and Metadata

Metadata exchange concerns descriptions of datasets rather than the datasets themselves.

For example:

```text
Transfer Functions
↓
Remain in source repository

Metadata
↓
May be exchanged
```

The exchanged metadata may describe:

- Collections
- Surveys
- Stations
- Products
- Publications
- Identifiers

without duplicating the underlying transfer functions.

---

## Discovery Without Duplication

The primary purpose of metadata exchange is discovery.

A researcher should be able to determine:

- What datasets exist.
- Where they are located.
- Who produced them.
- What products are available.

without downloading scientific data or understanding the structure of every repository.

This approach reduces duplication while improving visibility.

---

## Exchange Principles

Metadata exchange within AusMT is guided by several principles.

### Repository Independence

Organisations should retain control of their own repositories.

Metadata exchange should not require changes to local governance, infrastructure or storage systems.

---

### Persistent Identifiers

Identifiers provide the foundation for reliable metadata exchange.

Examples include:

- DOI
- ORCID
- ROR
- RAiD

Identifiers reduce ambiguity and improve linking between repositories.

---

### Reuse Existing Standards

Where established standards exist, they should be used.

Examples include:

- MTH5
- mt_metadata
- DOI metadata
- ORCID
- ROR

The objective is interoperability rather than creation of repository-specific metadata standards.

---

### Metadata is Authoritative

Metadata should originate from an authoritative source whenever possible.

Repositories should avoid maintaining multiple conflicting descriptions of the same dataset.

The preferred approach is:

```text
Authoritative Source
↓
Metadata Exchange
↓
Discovery Systems
```

rather than independent manual duplication.

---

## Exchange Levels

Metadata exchange may occur at several levels.

### Collection Level

Examples:

- Collection title
- Description
- Geographic extent
- Custodian organisation

Collection metadata support broad discovery and navigation.

---

### Survey Level

Survey metadata represent the primary exchange unit.

Examples include:

- Survey title
- Survey identifier
- Geographic extent
- Acquisition dates
- Organisations
- Publications
- Product availability

Most discovery workflows operate at this level.

---

### Station Level

Station metadata provide more detailed information.

Examples include:

- Station identifier
- Coordinates
- Deployment dates
- Available products

Not all repositories will choose to exchange station-level metadata.

---

### Product Level

Product metadata describe the scientific products associated with a survey.

Examples include:

- EDI availability
- EMTFXML availability
- MTH5 availability
- Derived products
- Product versions

This information helps users determine what can be accessed before downloading data.

---

## MTCAT and Metadata Exchange

MTCAT provides a lightweight framework for exchanging discovery metadata between repositories.

Its purpose is not to replace existing metadata standards.

Instead, it provides a common structure for describing:

```text
Collections
Surveys
Stations
Products
Identifiers
```

in a consistent manner.

MTCAT therefore acts as a discovery layer rather than a scientific data format.

---

## Versioning

Metadata change over time.

Examples include:

- Additional publications
- Updated provenance
- Corrected coordinates
- New product availability

Metadata exchange systems should preserve version information where possible.

Users should be able to determine:

- When metadata were created.
- When metadata were updated.
- Which version is being described.

---

## Provenance

Metadata should retain information regarding their origin.

Examples include:

- Source repository
- Source collection
- Source survey package
- Last update date

Provenance helps users understand where metadata originated and supports traceability across systems.

---

## FAIR and CARE

Metadata exchange contributes directly to FAIR principles by improving:

- Findability
- Accessibility
- Interoperability
- Reusability

CARE considerations may also influence metadata exchange.

Examples include:

- Access restrictions
- Governance requirements
- Cultural heritage considerations

Metadata may remain discoverable even when access to scientific products is restricted.

---

## Future Directions

The precise mechanisms used for metadata exchange will continue to evolve.

Examples may include:

- Static metadata exports
- Repository synchronisation
- Catalogue harvesting
- API-based exchange

AusMT does not prescribe a single technical implementation.

The objective is interoperability of metadata rather than standardisation of infrastructure.

---

## Principle

Metadata exchange is not about moving data.

It is about improving discovery.

Scientific products may remain within their original repositories, under their original governance arrangements and using their preferred storage systems.

Only the information required to discover, understand and access those products needs to be shared.

In this way, repositories remain independent while discovery becomes shared.