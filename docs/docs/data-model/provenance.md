# Provenance Model

Provenance is the origin and history of a scientific product: what was collected, how it was
processed, which products came out, and how they relate. AusMT treats it as a scientific
product rather than an administrative record, because the failure it prevents is the common
one. Transfer functions survive; the processing history does not. Years later nobody can say
which software was used, which parameters were applied, or which version is authoritative.

The goal is not to record every computational step. It is to capture enough that a future user
can answer: which survey is this from, which observations were used, which software produced
it, what was derived from it, and who published on it.

## The provenance chain

```text
Field Acquisition
↓
Time Series
↓
Transfer Functions
↓
Derived Products
↓
Publications
```

**Observations.** AusMT does not normally store them. Survey packages record typed pointers
instead: a `related_identifiers[]` row names the identifier, says what kind it is, and states
which data level it points at, so a reader can tell an NCI parent collection from the raw
packed time series inside it. The DataCite relation follows from that level rather than being
typed by hand. Fields are in the
[survey.yaml reference](../reference/survey-yaml.md#identifiers-by-data-level); the reasoning
is in [Why identifiers carry a data level](../rationale/identifiers-by-level.md).

**Transfer functions** are the products AusMT preserves. Where the record allows, provenance
identifies the format, creation date, processing software and version, and any relevant notes.
For legacy datasets this is often partial, and the model accommodates that.

**Derived products** keep explicit links to the transfer functions they were computed from, so
any diagnostic can be traced back to its input bytes.

**Publications** are part of the chain in both directions: dataset to publication and
publication to dataset. Recording both improves discovery and supports attribution.

## What ships today

> **Implementation status (current).** The Level 0 to 3 taxonomy below is a **conceptual
> framework** for reasoning about provenance completeness. It is not a field, a badge or a
> validated schema anywhere in the codebase. What is actually shipped: (1) every
> build-generated product carries a per-product `input_file` and `input_sha256` alongside the
> pipeline's parameters and version info (`build_provenance.json`, emitted by `_build_prov()`
> in `build_portal.py`); (2) submitter-side provenance lives in `survey.yaml` (the
> `processing.*` fields and free-text notes) and in the EDI headers, which the build scrapes
> for processing metadata, with no separate per-package provenance file; and (3) the
> canonical-XML store records per-station conditioning notes in its own `provenance.json`.
> Placing a survey on the scale below is a human judgement, not a computed classification.

- **Level 0, product only.** The transfer function survives and little else. Typical of older
  datasets.
- **Level 1, basic.** Survey association, station metadata and product information: the origin
  can be established.
- **Level 2, processing.** Software, version and processing notes: how the product was made
  can be understood.
- **Level 3, reproducible.** Parameters, workflow descriptions and versioned software
  references: all or part of the products can be regenerated.

## Provenance is broader than reproducibility

A dataset can have useful provenance without being reproducible. The software may be gone, the
workflow may never have been written down, the time series may not have survived. Provenance
still supplies the context that makes the product interpretable, which is why the model records
what is known rather than requiring what would be ideal.
