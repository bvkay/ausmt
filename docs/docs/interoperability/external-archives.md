# External Archives

AusMT publishes transfer functions, survey metadata, provenance and derived products. Everything else
that belongs to a survey stays where it already is, and the survey package records a pointer to it.

## What stays outside

**Time series.** Native instrument files, calibrated series, continuous recordings, intermediate
processing products, observational MTH5 datasets. They are large, often governed by different access
conditions, and belong in repositories built for them (NCI, universities, agencies, project archives).
This is the boundary the whole design turns on; it is stated once here and referenced elsewhere.

**Publications and reports.** No PDFs, theses, posters or presentations; the package records references
to them.

**Site photographs and field material.** Lightweight structured notes that improve interpretation or
provenance (deployment notes, site conditions, known acquisition issues) can sit in the package as small
text or metadata fields; image and PDF collections live elsewhere.

## How the links are recorded

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

Prefer a persistent identifier (DOI, Handle, ARK, RAiD, an institutional or NCI collection identifier)
over a URL; an ordinary link does not survive a site reorganisation. A dataset identifier also states
which data level it points at, so a reader can tell a parent collection from the raw packed time series
inside it; see [Identifiers by data level](../reference/survey-yaml.md#6-identifiers-by-data-level).
Each reference should carry enough for a user to understand the relationship: resource type, title,
identifier, holding repository, access conditions.

## Access conditions

An external resource may have different access conditions from the AusMT package: open, embargoed,
restricted, mediated or unavailable. Do not imply that referenced material is openly available unless
that has been confirmed. Record the conditions and any governance requirements in the metadata, which a
curator reviews at [review](../operations/review.md) time. These links are part of the
[provenance record](../data-model/provenance.md): they preserve the connection between the observations
and the published products even where AusMT does not hold the observations.
