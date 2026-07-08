# Provenance Model

## Introduction

Provenance describes the origin and history of a scientific product.

For a magnetotelluric dataset, provenance provides the information needed to understand:

- what was collected
- how it was processed
- which products were generated
- how those products relate to one another

Without provenance, a transfer function may still be usable, but it becomes increasingly difficult to determine where it came from, whether it represents the authoritative version of a dataset and how it should be interpreted.

AusMT treats provenance as a core scientific product rather than an administrative record.

---

## Why Provenance Matters

Many historical MT datasets remain scientifically valuable long after the original project has concluded.

However, over time it is common for information to become separated.

Examples include:

- Transfer functions surviving while metadata are lost.
- Metadata surviving while the data become difficult to locate.
- Publications surviving while intermediate products disappear.
- Multiple versions of a dataset existing without clear lineage.
- Processing workflows becoming undocumented.

These problems become more common as personnel change, storage systems evolve and projects conclude.

Provenance provides the context needed to understand and reuse a dataset many years after its original acquisition.

---

## Provenance as a Scientific Product

Within AusMT, provenance is published alongside transfer functions, metadata and derived products.

The intention is not to record every processing step ever performed.

Instead, the goal is to capture the key relationships needed to understand how a published product came into existence.

In practical terms, provenance answers questions such as:

- Which survey does this product belong to?
- Which observations were used?
- Which processing software was used?
- Which derived products were generated?
- Which publications used this dataset?

---

## The Provenance Chain

Most survey packages can be described using a simple lineage:

```text
Field Acquisition
↓
Time-Series Data
↓
Transfer Functions
↓
Derived Products
↓
Publications
```

Each stage contributes information that may be useful to future users.

---

## Observations

The provenance chain begins with the original observations.

Examples include:

- Electric field measurements
- Magnetic field measurements
- Station metadata
- Acquisition logs
- Instrument information

AusMT does not normally store the observations themselves.

Instead, survey packages may record persistent identifiers linking published products to the corresponding time-series collections.

---

## Transfer Functions

Transfer functions are the primary scientific products preserved within AusMT.

Examples include:

- EDI
- EMTFXML
- MTH5 transfer-function products

Where possible, provenance records should identify:

- Product format
- Creation date
- Processing software
- Processing version
- Relevant notes

For legacy datasets, this information may not always be available.

The provenance model is designed to accommodate incomplete historical records where necessary.

---

## Derived Products

Many products displayed within AusMT are generated from transfer functions.

Examples include:

- Apparent resistivity and phase plots
- Tipper products and induction arrows
- Phase tensor products
- Dimensionality diagnostics
- Strike screening (selection-level rose diagrams)
- Distortion analyses (planned)

These products should retain explicit links to the transfer functions from which they were generated.

This allows users to trace derived products back to their underlying data.

---

## Publications

Publications represent an important part of the provenance chain.

Scientific papers often contain:

- Interpretations
- Methodological descriptions
- Geological context
- Processing decisions

Where available, survey packages should record links between datasets and publications.

This relationship works in both directions:

```text
Dataset → Publication
Publication → Dataset
```

Maintaining these links improves discoverability and supports proper attribution.

---

## Provenance Levels

Not all datasets contain the same amount of provenance information.

AusMT therefore accommodates multiple levels of provenance completeness.

> **Implementation status (current).** The Level 0–3 taxonomy below is a **conceptual framework**
> for reasoning about provenance completeness — it is not a field, badge or validated schema
> anywhere in the codebase today. What is actually shipped: (1) every build-generated product
> carries a per-product `input_file` name and `input_sha256` alongside the pipeline's parameters
> and version info (`build_provenance.json`, emitted by `_build_prov()` in `build_portal.py`);
> (2) submitter-side provenance lives in `survey.yaml` (the `processing.*` fields and free-text
> notes) and in the EDI headers themselves, which the build scrapes for processing metadata —
> there is no separate per-package provenance file; and (3) the canonical-XML store records
> per-station conditioning notes in its own `provenance.json`. Mapping a survey onto Level 0–3
> is a manual, human judgement, not a computed classification.

### Level 0 — Product Only

The transfer function is available.

Little or no provenance information survives.

Typical of many historical datasets.

---

### Level 1 — Basic Provenance

Includes:

- Survey association
- Station metadata
- Product information

The origin of the product can be established.

---

### Level 2 — Processing Provenance

Includes:

- Processing software
- Processing version
- Processing notes

Users can understand how products were generated.

---

### Level 3 — Reproducible Provenance

Includes sufficient information to reproduce all or part of the published products.

Examples may include:

- Processing parameters
- Workflow descriptions
- Versioned software references

---

## Provenance and Reproducibility

Provenance and reproducibility are related but distinct concepts.

A dataset may have useful provenance without being fully reproducible.

For example:

- Processing software may no longer exist.
- Historical workflows may be incomplete.
- Original time-series data may not survive.

The purpose of provenance is therefore broader than reproducibility.

It provides context, even when complete reproduction is no longer possible.

---

## Provenance Records

Within AusMT, provenance information is stored alongside the survey package.

Typical provenance records may describe relationships between:

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
↓
Publication
```

This structure allows users to navigate both scientific products and their associated context.

---

## Stewardship

The value of provenance increases with time.

Shortly after a survey is completed, many details are still known by the project team.

Twenty years later, those same details may only survive if they were recorded.

For this reason provenance is treated as part of the dataset rather than supplementary information.

A transfer function can often be preserved indefinitely.

Understanding where it came from is usually much harder.

The provenance model adopted by AusMT is intended to preserve that understanding alongside the scientific products themselves.