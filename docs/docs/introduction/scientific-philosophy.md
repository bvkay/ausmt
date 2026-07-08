# Scientific Philosophy

## Introduction

AusMT was developed in response to practical problems encountered when attempting to discover, understand and reuse magnetotelluric datasets.

Many of these problems are not technical. They arise because data, metadata, processing history and scientific context are often preserved separately, if they are preserved at all.

The purpose of AusMT is not simply to store transfer functions. The objective is to preserve enough information that future users can understand what was collected, how it was processed and how it has been used.

The decisions described in this document reflect that objective.

---

## The Survey is the Scientific Object

Most archives are organised around files.

From a storage perspective this makes sense. Files are easy to catalogue, transfer and preserve.

Researchers, however, do not generally think in terms of files.

A researcher rarely asks:

> Where is station SA103.edi?

More commonly they ask:

> Where is the processed AusLAMP data?

or

> Is the Vulcan dataset available?

The scientific context usually exists at the survey level.

Acquisition strategy, instrumentation, processing decisions, publications and interpretation are typically associated with the survey rather than individual transfer-function files.

For this reason AusMT treats the survey as the primary unit of publication, discovery and citation.

Files remain important, but they exist within the context of a survey package.

---

## Collections Matter

Surveys rarely exist in isolation.

Many form part of larger programs, institutional holdings or regional investigations.

Examples include:

- AusLAMP
- WAMT
- University collections
- Geological Survey programs

Grouping surveys into collections provides additional context and improves discoverability.

The organisational hierarchy adopted by AusMT is therefore:

```text
Collection
↓
Survey
↓
Station
```

This structure reflects how many organisations already manage their data and how most users search for it.

---

## Why Transfer Functions?

AusMT focuses on transfer functions rather than raw time-series data.

This decision is primarily practical.

Time-series archives can be very large and require specialist infrastructure for storage, preservation and access. National facilities such as NCI and institutional repositories are generally better suited to this role.

Transfer functions are the products most commonly exchanged, interpreted, published and reused within the MT community.

In many cases they are also the only surviving products from older surveys.

By concentrating on transfer functions and their associated metadata, AusMT can provide broad coverage of historical and contemporary datasets without duplicating existing archival infrastructure.

Where possible, survey packages maintain links to the underlying time-series collections through persistent identifiers.

---

## Metadata is Data

The distinction between data and metadata is often artificial.

A transfer function without metadata may be difficult or impossible to interpret.

Questions such as:

- Where was the station located?
- When was it recorded?
- Which instruments were used?
- Was remote reference applied?
- Which processing software was used? what version?

are often as important as the transfer function itself.

For this reason metadata is treated as a first-class product within AusMT rather than supplementary information.

---

## Provenance is a Scientific Product

A recurring problem in older datasets is that transfer functions survive while the processing history does not.

Years later it may be impossible to determine:

- Which software was used.
- Which parameters were applied.
- Which version of the dataset is authoritative.
- Whether subsequent products are reproducible.

AusMT therefore treats provenance as a scientific product rather than an administrative record.

Where possible, survey packages document the relationships between:

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

The objective is not to record every computational step ever performed.

The objective is to preserve enough information that future users can understand where a product came from.

---

## Reproducibility Where Possible

Reproducibility is an important goal, but it has practical limits.

Many historical datasets were processed using software that is no longer available, operating systems that no longer exist or workflows that were never fully documented.

AusMT does not require perfect reproducibility.

Instead, it seeks to preserve enough information that future researchers can understand the available products and reproduce them where practical.

This distinction is particularly important for legacy datasets.

---

## Interoperability Over Reinvention

The MT community already maintains a number of widely used formats and standards.

Examples include:

- MTH5
- mt_metadata
- EMTFXML
- EDI

AusMT adopts these standards wherever practical.

Creating new formats is easy.

Maintaining them for decades is much harder.

Whenever an established standard adequately solves a problem, it is generally preferred over a project-specific alternative.

---

## Curation Over Open Upload

Scientific archives accumulate value over time when users trust the contents.

For this reason AusMT is designed as a curated repository rather than an unrestricted file-sharing platform.

Submitted datasets pass through validation and review before publication.

This process helps ensure that:

- Metadata are complete.
- Products are discoverable.
- Provenance is recorded.
- Licensing is clear.
- Collections remain consistent.

The goal is not to restrict access, but to improve long-term usability.

---

## Scientific Products Beyond Transfer Functions

Transfer functions are only one way of describing a dataset.

Many users are interested in products that help them assess or interpret the data before downloading anything.

Examples include:

- Apparent resistivity and phase plots
- Tipper products and induction arrows
- Phase tensor products
- Dimensionality diagnostics
- Strike screening (selection-level rose diagrams)
- Distortion analyses (planned)

These products are intended to complement, rather than replace, the transfer functions themselves.

---

## CARE

AusMT supports both FAIR and CARE principles. While FAIR focuses on making data discoverable and reusable, CARE emphasises the rights, interests and governance expectations of Indigenous Peoples and communities. The project seeks to support both principles through its metadata, provenance and publication workflows.

> **Implementation status (current).** CARE support today means `survey.yaml`'s `care.*` fields
> are recorded and surfaced to reviewers — there is no automated enforcement. A curator reads and
> acts on them manually during review; nothing in the pipeline blocks publication based on their
> content. Machine-checked CARE gating is an aspiration, not a shipped mechanism.

---

## Stewardship

Scientific data often outlive the projects that created them.

Students graduate.

Researchers retire.

Funding programs conclude.

Storage systems change.

The long-term usefulness of a dataset depends not only on preserving files but also on preserving the information required to understand those files.

AusMT is intended to support that process by bringing together transfer functions, metadata, provenance and scientific context within a consistent framework.