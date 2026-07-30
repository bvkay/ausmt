# Metadata Model

Metadata are what let a transfer function be found, interpreted, reproduced and cited, so
AusMT treats them as scientific products rather than supporting paperwork. Their value also
grows: shortly after a survey the project team still knows the details, and twenty years later
the metadata may be the only place those details survive.

## Metadata follow the data hierarchy

Different metadata belong at different levels, and the level a fact sits at is part of what it
means.

| Level | What its metadata describe |
| --- | --- |
| Collection | Title, description, custodian organisation, geographic coverage, time span, collection identifiers. Broad discovery context. |
| Survey | Title, identifier, abstract, creators and contributors, organisations, funding, acquisition dates, geographic extent, licence, access level and coordinate policy, related identifiers and publications. The primary discovery and citation record. |
| Station | Identifier, coordinates, elevation, deployment dates, instrumentation, sensor orientations. The observational context for a transfer function. |
| Transfer function | Format, period range, processing software and version, creation date, product identifiers. |
| Derived product | Product type, creation date, software version, source transfer function, parameters. Always linked back to the transfer function it came from. |

The survey level is where most of this is recorded, field by field, in
[survey.yaml](../reference/survey-yaml.md). Persistent identifiers (DOI, ORCID, ROR, RAiD) are
covered in [Standards and alignment](../introduction/standards.md), and the rule that a
dataset identifier must state which data level it points at is in
[Identifiers by data level](../reference/survey-yaml.md#6-identifiers-by-data-level).

## Required and recommended

Completeness varies, particularly for historical datasets, so the model separates two tiers.

**Required** for publication: survey title, survey identifier, geographic location,
transfer-function products. Missing any of these fails validation.

**Recommended** because they substantially improve reuse: investigators, organisations,
acquisition dates, publications, identifiers. Missing these produces warnings, not failures.

That split is deliberate. A historical survey with thin records is usually more valuable
published with its gaps visible than withheld while someone tries to reconstruct them.
Validation therefore checks consistency, structure and discoverability rather than trying to
enforce complete metadata; the checks themselves are listed under
[Submission](../operations/submission.md).

## Governance metadata

Some datasets carry access conditions, usage constraints, Indigenous data governance
requirements or embargo terms. These are recorded alongside the scientific metadata so that a
dataset can stay discoverable while its access conditions are respected. The serving
consequences are in [Publication](../operations/publication.md).

## Metadata and provenance

Metadata describe a product. Provenance describes how it came into existence. Both are needed
to understand a dataset, and AusMT records both; the provenance model is in
[Provenance](provenance.md).
