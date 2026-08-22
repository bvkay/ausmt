# Metadata Model

Metadata are what let a transfer function be found, interpreted, reproduced and cited, so AusMT treats
them as scientific products. Twenty years after a survey the metadata may be the only place the
details survive.

## Metadata follow the data hierarchy

| Level | What its metadata describe |
| --- | --- |
| Collection | Title, description, custodian organisation, geographic coverage, time span, identifiers. |
| Survey | Title, identifier, abstract, creators and contributors, organisations, funding, acquisition dates, extent, licence, access level and coordinate policy, related identifiers and publications. The primary discovery and citation record. |
| Station | Identifier, coordinates, elevation, deployment dates, instrumentation, sensor orientations. |
| Transfer function | Format, period range, processing software and version, creation date, product identifiers. |
| Derived product | Product type, creation date, software version, source transfer function, parameters. Always linked back to its transfer function. |

The survey level is recorded field by field in [survey.yaml](../reference/survey-yaml.md). Persistent
identifiers are covered in [Standards and alignment](../introduction/standards.md); the rule that a
dataset identifier states which data level it points at is in
[Identifiers by data level](../reference/survey-yaml.md#6-identifiers-by-data-level).

## Required and recommended

**Required** for publication: survey title, survey identifier, geographic location, transfer-function
products. Missing any of these fails validation. **Recommended**: credit (`creators[]` and
`contributors[]`), organisations and their roles, acquisition dates, publications, identifiers.
Missing these produces warnings.

A historical survey with thin records is usually more valuable published with its gaps visible than
withheld while someone tries to reconstruct them, so validation checks consistency, structure and
discoverability rather than enforcing complete metadata; the checks are listed under
[Submission](../operations/submission.md). Metadata completeness is not scientific quality: a sparsely
documented survey can hold excellent transfer functions.

## Governance metadata

Access conditions, usage constraints, Indigenous data governance requirements and embargo terms are
recorded beside the scientific metadata so a dataset can stay discoverable while its access conditions
are respected. The serving consequences are in [Publication](../operations/publication.md).

Metadata describe a product; provenance describes how it came into existence. The provenance model is
in [Provenance](provenance.md).
