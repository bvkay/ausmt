# External Archives

## Overview

AusMT does not attempt to store every product associated with an MT survey.

Its primary role is to publish and describe transfer functions, survey metadata, provenance records and derived products needed for discovery and reuse.

Other materials may remain in external archives.

This includes raw MT time-series data, native recorder files, large reports, project documentation, site photographs and other supporting material.

AusMT records links to these resources where they are useful, but does not duplicate them.

---

## Why External Archives Matter

Many MT datasets are already held by universities, government agencies, national facilities and institutional repositories.

Moving all associated material into AusMT would create unnecessary duplication and increase long-term maintenance costs.

External archives allow AusMT to remain focused on its primary role:

```text
Transfer functions
Metadata
Provenance
Discovery
```

while allowing large or specialised resources to remain in systems designed to manage them.

---

## Time-Series Data

Raw MT time-series data are out of scope for AusMT.

Time-series archives may be large, complex and governed by different access conditions.

They may include:

- Native instrument files
- Calibrated time-series
- Continuous recordings
- Intermediate processing products
- Large MTH5 observational datasets

These products should remain in appropriate external repositories.

Where available, AusMT records persistent identifiers or stable links connecting survey packages to the relevant time-series collections.

---

## Publications and Reports

AusMT does not store publication PDFs, reports, theses, posters or presentations.

Instead, survey packages may record references to related publications and resources.

Preferred identifiers include:

- DOI
- Handle
- institutional repository record
- stable landing page

The objective is to preserve the relationship between the survey package and related resources, not to duplicate those resources.

---

## Site Photographs and Field Material

Site photographs, field notebooks and large supporting collections should normally be stored outside AusMT.

Where this material is important, AusMT may record references to the external collection.

Lightweight structured notes may be included in the survey package where they improve interpretation or provenance.

Examples include:

- station deployment notes
- site condition notes
- known acquisition issues

These should normally be stored as small text, CSV or metadata fields rather than as image or PDF collections.

---

## Persistent Links

External archive references should use persistent identifiers wherever possible.

Examples include:

- DOI
- Handle
- ARK
- RAiD
- institutional repository identifier
- NCI collection identifier

Ordinary URLs may change over time and should be avoided where better identifiers exist.

---

## What AusMT Records

For each external archive reference, AusMT should record enough information for a user to understand the relationship.

Examples include:

yaml related_resources:   - type: time_series_collection     title: Vulcan MT raw time-series collection     pid: ...     repository: NCI    - type: publication     doi: 10.xxxx/example 

Useful fields include:

- resource type
- title
- identifier
- repository
- access conditions
- relationship to the survey package

---

## Access Conditions

External resources may have different access conditions from the AusMT survey package.

Examples include:

- open access
- embargoed
- restricted access
- mediated access
- unavailable

AusMT should not imply that externally referenced material is openly available unless that has been confirmed.

Where possible, access conditions should be recorded in the metadata.

---

## Governance and CARE Considerations

Some external resources may have additional governance requirements.

Examples include:

- Indigenous data governance considerations
- cultural heritage constraints
- community agreements
- project-specific access restrictions

These should be recorded where known and reviewed during curation.

AusMT may expose metadata for discovery while access to the underlying resource remains restricted.

---

## Relationship to Provenance

External archive links are part of the provenance record.

They help users understand where the published transfer functions came from and where supporting material may be found.

For example:

```text
Time-series collection
↓
Processing
↓
Transfer functions
↓
AusMT survey package
```

Even where AusMT does not hold the original observations, links to external archives help preserve the connection between observations and published products.

---

## Principle

AusMT should not become a general document or media archive.

Its role is to preserve and publish the MT products needed for discovery and reuse, while linking to external archives for material that is too large, too specialised or outside the core scope of the project.

The boundary is simple:

```text
AusMT stores the survey package.
External archives store large or supporting resources.
```