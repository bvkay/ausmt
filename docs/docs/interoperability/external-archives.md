# External Archives

AusMT publishes and describes transfer functions, survey metadata, provenance and derived
products. Everything else that belongs to a survey stays where it already is, and the survey
package records a pointer to it. Moving it all in would duplicate systems that already work and
add maintenance AusMT would then owe forever.

## What stays outside

**Time series.** The raw electric and magnetic field recordings: native instrument files,
calibrated series, continuous recordings, intermediate processing products, large observational
MTH5 datasets. These are large, complex and often governed by different access conditions, and
they belong in repositories built for them (NCI, universities, agencies, project archives).
This is the boundary the whole design turns on, so it is stated once here and referenced
elsewhere.

**Publications and reports.** No PDFs, theses, posters or presentations. The survey package
records references to them instead.

**Site photographs and field material.** Photographs, notebooks and large supporting
collections live elsewhere. Lightweight structured notes that improve interpretation or
provenance (station deployment notes, site conditions, known acquisition issues) can sit in the
package as small text or metadata fields rather than as image or PDF collections.

## How the links are recorded

Using the real `survey.yaml` fields:

```yaml
time_series:                 # pointers ONLY - AusMT never hosts time series
  pid: 10.25914/example      # persistent identifier of the time-series collection

publications:
  - author: Example, A.
    year: 2024
    title: An example interpretation paper
    journal: Exploration Geophysics
    doi: 10.xxxx/example
```

**Prefer a persistent identifier over a URL.** DOI, Handle, ARK, RAiD, an institutional
repository identifier or an NCI collection identifier all survive a site reorganisation;
an ordinary link does not. Where a dataset identifier is recorded, it also states which data
level it points at, so a reader can tell a parent collection from the raw packed time series
inside it; see
[Identifiers by data level](../reference/survey-yaml.md#6-identifiers-by-data-level).

Each reference should carry enough for a user to understand the relationship: resource type,
title, identifier, holding repository, access conditions, and how it relates to the survey
package.

## Access conditions

An external resource may have entirely different access conditions from the AusMT package:
open, embargoed, restricted, mediated, or unavailable. **Do not imply that referenced material
is openly available unless that has been confirmed.** Record the conditions in the metadata,
along with any governance requirements attached to the resource, which a curator reviews at
[review](../operations/review.md) time. AusMT may expose discovery metadata while the
underlying resource stays restricted.

These links are part of the [provenance record](../data-model/provenance.md): even where AusMT
does not hold the observations, they preserve the connection between the observations and the
published products.
