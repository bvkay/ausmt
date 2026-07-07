# Interoperability Overview

## Overview

Interoperability is a core principle of AusMT.

The project was not created to replace existing repositories, archives or community standards. Instead, it aims to improve the discoverability, accessibility and long-term usability of magnetotelluric datasets across organisations, jurisdictions and software ecosystems.

Many valuable MT datasets already exist.

The challenge is often not the absence of data, but the difficulty of discovering, understanding and reusing them.

AusMT seeks to address this challenge by providing common structures for describing, publishing and linking MT survey products.

---

## Why Interoperability Matters

MT datasets are produced by many organisations, including:

- Universities
- Government agencies
- Geological surveys
- Research infrastructure facilities
- Industry groups

These datasets may be stored in:

- Institutional repositories
- National archives
- Project websites
- Research data platforms
- Local organisational systems

Each repository serves a different purpose and operates within different technical and organisational constraints.

The result is a distributed landscape of valuable but often disconnected datasets.

Interoperability allows these datasets to remain distributed while becoming easier to discover and reuse.

---

## Independence and Discovery

AusMT does not require all MT data to be stored in a single location.

Instead, the project is built around a simple principle:

> Repositories remain independent. Discovery becomes shared.

Organisations should be able to maintain their own infrastructure, governance arrangements and data-management practices while still participating in a broader discovery ecosystem.

This reduces duplication and supports long-term sustainability.

---

## Layers of Interoperability

Interoperability occurs at multiple levels.

### Scientific Products

Transfer functions should be exchangeable between software systems and repositories.

Examples include:

- MTH5
- EMTFXML
- EDI

These formats provide interoperability at the product level.

---

### Metadata

Metadata should be understandable across systems.

Examples include:

- Survey metadata
- Station metadata
- Product metadata
- Provenance information

Metadata interoperability allows datasets to remain discoverable and interpretable beyond their original repository.

---

### Identifiers

Persistent identifiers reduce ambiguity and improve linking between systems.

Examples include:

- DOI
- ORCID
- ROR
- RAiD

Identifiers allow people, organisations, projects and datasets to be connected consistently.

---

### Discovery

Discovery interoperability allows users to determine what datasets exist without needing to understand the internal structure of every repository.

This is one of the primary motivations behind MTCAT.

---

### Software

Scientific products should remain usable across multiple software environments.

Examples include:

- MTpy-v2
- mt_metadata
- MTH5
- Aurora
- ModEM
- Occam

No single software package should be required to access or interpret published products.

---

## Relationship to Existing Standards

AusMT does not define a new MT processing standard.

Instead, it builds upon existing community standards and practices.

Examples include:

- MTH5
- mt_metadata
- EMTFXML
- EDI
- DOI
- ORCID
- ROR

Where established standards exist, AusMT seeks to adopt them rather than replace them.

---

## Relationship to MTH5

MTH5 provides a modern format for storing MT observations, transfer functions and metadata.

AusMT supports MTH5 because it improves interoperability between software systems and repositories.

However, interoperability is broader than any single file format.

A repository can participate in the AusMT ecosystem regardless of whether its holdings are stored as:

- EDI
- EMTFXML
- MTH5
- Other established MT formats

The goal is interoperability of scientific products, not uniformity of implementation.

---

## Relationship to MTCAT

MTCAT provides a discovery layer for MT collections, surveys and products.

While transfer-function formats describe scientific data, MTCAT describes the existence of those datasets.

This distinction is important.

```text
MTH5
↓
What is in the dataset?

MTCAT
↓
What datasets exist?
```

Together these layers support both scientific reuse and dataset discovery.

---

## Collections and Survey Packages

AusMT uses collections and survey packages as the primary organisational units.

This model provides a consistent structure that can be understood across repositories.

```text
Collection
↓
Survey Package
↓
Station
↓
Transfer Function
↓
Derived Product
```

The model is intentionally lightweight and designed to complement, rather than replace, existing repository structures.

---

## FAIR and CARE

AusMT supports both FAIR and CARE principles.

FAIR emphasises that data should be:

- Findable
- Accessible
- Interoperable
- Reusable

CARE emphasises:

- Collective Benefit
- Authority to Control
- Responsibility
- Ethics

Interoperability must therefore consider not only technical compatibility but also governance, stewardship and community expectations. (For what CARE support currently means in practice — recorded fields reviewed manually by a curator, no automated enforcement — see the implementation status in [Scientific Philosophy](../introduction/scientific-philosophy.md).)

---

## International Context

AusMT forms part of a broader international MT ecosystem.

Relevant initiatives include:

- EarthScope
- EPOS
- mt_metadata
- MTH5
- International MT archives
- National geophysical repositories

The objective is not to create an isolated Australian platform, but to contribute to a broader ecosystem of interoperable MT resources.

---

## Long-Term Stewardship

Interoperability is ultimately a stewardship issue.

Scientific data often outlive:

- Software systems
- Storage technologies
- Research projects
- Individual careers

A dataset that can only be understood within a single repository or software environment is more difficult to preserve and reuse.

Interoperability improves resilience by ensuring that scientific products remain understandable across organisations, technologies and generations of researchers.

---

## Principle

The objective of interoperability is not to make every repository identical.

The objective is to allow independent systems to communicate using shared concepts, shared standards and shared identifiers.

In practical terms, interoperability means that a researcher should be able to discover a dataset, understand its context and use its products without needing to know where the dataset originated or how the underlying repository is implemented.