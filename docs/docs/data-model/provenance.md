# Provenance Model

Provenance is the origin and history of a scientific product: what was collected, how it was processed,
which products came out, and how they relate. The goal is not to record every computational step but
to let a future user answer: which survey is this from, which observations were used, which software
produced it, what was derived from it, and who published on it.

## The provenance chain

```text
Field Acquisition -> Time Series -> Transfer Functions -> Derived Products -> Publications
```

**Observations.** AusMT does not normally store them. Survey packages record typed pointers: a
`related_identifiers[]` row names the identifier, says what kind it is, and states which data level it
points at, so a reader can tell an NCI parent collection from the raw packed time series inside it.
The DataCite relation follows from that level. Fields are in the
[survey.yaml reference](../reference/survey-yaml.md#6-identifiers-by-data-level); the reasoning is in
[Why identifiers carry a data level](../rationale/identifiers-by-level.md).

**Transfer functions** are the products AusMT preserves. Where the record allows, provenance identifies
the format, creation date, processing software and version. For legacy datasets this is often partial.

**Derived products** keep explicit links to the transfer functions they were computed from.

**Publications** are recorded in both directions, dataset to publication and publication to dataset.

## What is recorded

1. Every build-generated product carries `input_file` and `input_sha256` alongside the pipeline's
   parameters and version. The build-wide record is
   [`build_provenance.json`](../developer/portal-documents.md#build_provenancejson); the per-station
   record is [`station.json`](../reference/station-products.md#111-provenance).
2. Submitter-side provenance lives in `survey.yaml` (the `processing` block and its free-text notes)
   and in the transfer-function headers, which the build reads for processing metadata. There is no
   separate per-package provenance file.
3. The canonical EMTF XML store records per-station conditioning notes in its own provenance record,
   and each station's product carries the same notes under `canonical_conditioning`.

## Provenance completeness

A way of reasoning about a survey's provenance; a human judgement, not a field or a badge.

- **Level 0, product only.** The transfer function survives and little else.
- **Level 1, basic.** Survey association, station metadata and product information.
- **Level 2, processing.** Software, version and processing notes.
- **Level 3, reproducible.** Parameters, workflow descriptions and versioned software references.

A dataset can carry useful provenance without being reproducible. The model records what is known, so
a survey at Level 0 or 1 is still published.
