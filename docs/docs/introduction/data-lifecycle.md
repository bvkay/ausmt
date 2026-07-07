# Data Lifecycle

## Overview

Magnetotelluric datasets do not begin as transfer functions.

They begin as observations of naturally occurring electromagnetic field variations recorded at the Earth's surface.

Over time those observations are transformed into transfer functions, scientific products, publications and interpretations. Long after the original project has finished, the resulting products may continue to be reused for new scientific questions.

AusMT is concerned with preserving this chain of information.

The data lifecycle adopted by AusMT can be summarised as:

```text
Field Acquisition
↓
Time-Series Data
↓
Transfer Functions
↓
Survey Package
↓
Validation
↓
Publication
↓
Discovery
↓
Reuse
```

Each stage contributes information that may be important for future users.

---

## Field Acquisition

The lifecycle begins with field observations.

These may be acquired using:

- Long-period MT systems
- Broadband MT systems
- Audio-frequency MT systems
- Related electromagnetic techniques

Field acquisition generates the primary observations from which all subsequent products are derived.

Information recorded during this stage often includes:

- Station locations
- Acquisition dates
- Instrumentation
- Sensor orientations
- Deployment notes
- Site photographs
- Environmental observations

Although these records may appear routine at the time of acquisition, they often become critical when datasets are revisited years later.

---

## Time-Series Data

The raw observations are stored as time-series measurements of electric and magnetic field variations.

These observations form the foundation of all subsequent processing.

Time-series archives may be maintained by:

- National Computational Infrastructure (NCI)
- Universities
- Government agencies
- Project repositories

AusMT does not store raw time-series data.

Instead, survey packages may record persistent identifiers linking published products to the corresponding time-series collections.

This approach allows responsibilities to remain clearly separated:

- Time-series repositories preserve observations.
- AusMT preserves transfer functions, metadata and scientific context.

---

## Transfer Functions

Transfer functions are the primary scientific products derived from MT observations.

Processing may involve:

- Data selection
- Robust estimation
- Remote-reference processing
- Quality control
- Error estimation

The resulting products may be represented as:

- EDI
- EMTFXML
- MTH5 transfer-function products

For many datasets, particularly historical surveys, the transfer functions are the products most commonly reused and cited.

They therefore form the core data products managed by AusMT.

---

## Survey Package Creation

Within AusMT, transfer functions are organised into survey packages.

A survey package combines:

- Survey metadata
- Station metadata
- Transfer functions
- Citation information
- Provenance records
- Derived products
- Publication references

The survey package is the primary scientific object published by AusMT.

This reflects how MT datasets are typically managed and cited within the research community.

---

## Validation

Before publication, survey packages pass through a validation process.

Validation helps identify issues such as:

- Missing metadata
- Invalid coordinates
- Incomplete provenance
- Unsupported formats
- Duplicate records

Validation produces one of three outcomes:

```text
PASS
WARNING
FAIL
```

Warnings do not necessarily prevent publication but provide additional information for curators and users.

Validation improves consistency across collections and helps maintain the long-term quality of published survey packages.

---

## Review and Curation

Validation alone is insufficient.

Many important decisions require scientific judgement.

Examples include:

- Dataset ownership
- Licensing
- Embargo requirements
- Metadata completeness
- Collection membership
- Provenance quality

For this reason survey packages undergo review before publication.

This process aims to improve long-term usability rather than act as a barrier to data sharing.

---

## Derived Scientific Products

Additional products may be generated from published transfer functions.

Examples include:

- Apparent resistivity and phase plots
- Tipper products and induction arrows
- Phase tensor products
- Dimensionality diagnostics
- Strike screening (selection-level rose diagrams)
- Distortion and decomposition products (planned)

These products assist users in understanding and evaluating datasets before downloading the underlying transfer functions.

Derived products do not replace the transfer functions.

They provide additional context.

---

## Publication

Following validation and review, survey packages are published within AusMT.

Publication makes the package available through:

- Collection pages
- Survey pages
- Search interfaces
- Machine-readable JSON products (catalogue, MTCAT, download manifest)
- Download services

Published packages become part of the curated AusMT record.

---

## Discovery

The value of a dataset depends on whether it can be found.

Discovery occurs at multiple levels:

```text
Collection
↓
Survey
↓
Station
```

Users may search by:

- Region
- Collection
- Survey
- Organisation
- Time period
- Scientific product

The objective is to allow users to identify relevant datasets without prior knowledge of file names or storage locations.

---

## Reuse

Reuse is the stage that ultimately justifies the existence of a data infrastructure.

Examples include:

- New interpretations of historical datasets
- Integration with newer surveys
- Regional studies
- Lithospheric investigations
- Resource exploration
- Methodological research
- Student projects

Many surveys continue to produce scientific value long after their original objectives have been achieved.

Supporting this reuse is one of the primary goals of AusMT.

---

## Preservation

The lifecycle does not end at publication.

Published survey packages continue to evolve.

Metadata may be improved.

Additional provenance may be recovered.

New publications may appear.

Derived products may be regenerated using improved methods.

The role of AusMT is to provide a stable framework within which these updates can occur while preserving the history and context of the original dataset.

The underlying objective remains straightforward: a future researcher should be able to understand what was collected, how it was processed and how it has been used, even when the original project team is no longer available.