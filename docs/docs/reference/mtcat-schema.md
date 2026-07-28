# MTCAT Schema

## Overview

MTCAT is a lightweight JSON-based discovery schema for magnetotelluric catalogue exchange.

It is designed to describe the collections, surveys, stations and transfer-function availability exposed by an MT portal or repository.

MTCAT does not store transfer functions.

It does not replace EDI, EMTFXML, MTH5 or mt_metadata.

Its purpose is discovery.

---

## Normative Artifact

This page is prose. The **normative** artifact is the JSON Schema itself:

```text
engine/schema/mtcat.schema.json      (shipped copy, in the repository)
https://ausmt.au/data/mtcat.schema.json   (served copy, beside the document it describes)
```

The two are byte-identical: the build copies the shipped file to the served location, and the product
self-check validates the emitted `mtcat.json` against it before anything is published. Where this page and
the schema disagree, the schema is right. Every field, type and controlled vocabulary carries its own
`description` there, so the schema is readable on its own and does not depend on this page.

---

## Schema Version

An MTCAT document declares its own schema version in `portal.version`, and points at the schema it was
validated against with `portal.schema_url`.

AusMT serves **one** schema file at **one unversioned URL**, and the schema's `$id` is that same URL:

```json
"$id": "https://ausmt.au/data/mtcat.schema.json"
```

This is deliberately *not* a versioned-filename convention, and it replaces the versioned-`$id` advice this
page used to carry. A versioned identifier that nobody serves is worse than no identifier at all: it looks
dereferenceable and is not. Every consumer need is met without encoding the version in the path:

- the **document** says which version it is, in `portal.version` (`1.2` at the time of writing);
- the **schema** says which version it is, in its `title`, so a fetched schema is self-identifying;
- the **served URL** always resolves to the current schema, which is the one the current documents point
  at, so `$id`, `schema_url` and the file a harvester actually fetches are the same three things.

A producer that wants older releases to stay addressable should publish them alongside under whatever names
it likes, but the unversioned URL must keep resolving to the current schema.

---

## Document Structure

An MTCAT document contains four main sections:

```text
portal
collections
surveys
stations
```

The required sections are:

```text
portal
surveys
stations
```

collections is optional, but recommended where surveys form part of a program, release, institutional holding or other logical grouping.

---

## Portal

The portal object describes the catalogue source.

Required fields:

```json
{
  "portal_id": "ausmt",
  "portal_name": "AusMT",
  "schema": "mtcat",
  "version": "1.2",
  "generated_at": "2026-06-15T00:00:00Z"
}
```

The portal.version field records the MTCAT schema version used by the document.

The portal object also carries two optional fields: `schema_url`, the location of the MTCAT schema served beside the document (AusMT emits `"mtcat.schema.json"`, a relative path, so a harvester can validate the catalogue without resolving the `$id` host at all); and `metadata_license`, the licence of the catalogue metadata itself, distinct from the per-survey data licences (AusMT declares `CC0-1.0` so the discovery metadata may be freely harvested and redistributed).

---

## Collections

Collections are optional roll-up objects used to group related surveys.

Examples include:

- AusLAMP
- Institutional holdings
- State-based releases

Example:

```json
{
  "collection_id": "auslamp",
  "title": "AusLAMP",
  "type": "programme",
  "n_surveys": 6,
  "n_stations": 1200
}
```

Collections should be lightweight. They are intended for discovery and navigation, not detailed archival description.

---

## Surveys

Survey records are the main discovery objects.

Required fields:

```json
{
  "survey_id": "vulcan-2022",
  "title": "Vulcan MT Survey",
  "organisation": "University of Adelaide",
  "country": "Australia"
}
```

Recommended fields include:

```json
{
  "doi": null,
  "license": "CC-BY-4.0",
  "access": "open",
  "collection_id": "institutional",
  "version": "1.0.0"
}
```

Spatial fields may include:

```json
{
  "bbox": {"west": 135.1, "south": -31.2, "east": 136.4, "north": -30.4},
  "centroid": {"latitude": -30.8, "longitude": 135.7}
}
```

The survey version field refers to the AusMT survey package version, not the MTCAT schema version.

### Discovery facets (added in 1.2)

Every one of these is *derived* from data already in the document or in the build's own download manifest.
None of them is curated, so a producer can compute all of them without asking anybody a question. They
exist so that a harvester can filter and rank surveys without first walking `stations[]` itself. A real
entry, from the AusLAMP Musgraves APY 2016 survey:

```json
{
  "n_stations": 88,
  "n_stations_tipper": 88,
  "data_types": {"LPMT": 88},
  "period_min_s": 8.0,
  "period_max_s": 16384.041943,
  "year_start": 2016,
  "year_end": 2018,
  "formats": ["edi", "edi-zip", "emtfxml", "mth5", "xml-zip"]
}
```

`formats` is read off the distribution manifest, so it is honest by construction: a survey whose bytes are
withheld has no manifest rows and therefore an empty list, while its discovery record, its station
locations and its footprint stay public. An embargo withholds bytes, never discovery. The two embargoed
surveys in the current corpus carry `"formats": []` and a full station count alongside an
`embargo_until` date, which is present only when a survey declares one.

### Credit and provenance (typed in 1.2)

`creators[]`, `contributors[]` and `related_identifiers[]` were served from 1.1 but were only described from
1.2. Their controlled vocabularies (DataCite contributor roles and relation types, identifier types, the NCI
data levels used by `identifies`, and PID `resolution` state) are enumerated in the schema itself, which is
the only place they should be read from. Note two properties that a type alone cannot express and that the
schema states in prose:

- `creators[]` order is load-bearing. It is the citation author order, not a set.
- `contributors[]` is role-tagged and unordered.

---

## Stations

Station records describe site-level discovery information.

Required fields:

```json
{
  "station_id": "V001",
  "survey_id": "vulcan-2022",
  "latitude": -30.123,
  "longitude": 135.456,
  "data_type": "BBMT"
}
```

From 1.2 `data_type` is enum-pinned to the closed set the classifier can return
(`AMT`, `BBMT`, `LPMT`, `GDS`, `unknown`), because it drives the band filters a consumer will build.

Station records should remain lightweight.

Detailed station metadata remain in the survey package or underlying MT metadata structures.

---

## Extensibility

The MTCAT schema permits additional properties.

This allows individual portals to include local fields without breaking interoperability.

However, additional fields should not be required for basic discovery.

The core discovery fields should remain stable and simple.

---

## Versioning Policy

Minor schema updates add optional fields, or *describe* fields a producer was already serving through
`additionalProperties`. Both are backward compatible: a document that validated against the older minor
version still validates.

```text
1.0 -> 1.1 -> 1.2
```

1.1 added the rights and provenance blocks. 1.2 described everything already being served (nothing new
appeared in the bytes because of the descriptions) and added the derived discovery facets listed above.
Because 1.2 was a describe-what-ships release, the tightening was checked in the only direction that
matters: the current live 1.1 document validates against 1.2 unchanged.

Major schema updates may introduce incompatible changes.

```text
1.x -> 2.0
```

MTCAT records must declare the schema version they use, in `portal.version`.

---

## Published Location

The schema is served beside the document it describes, at a stable, unversioned URL that matches its `$id`:

```text
https://ausmt.au/data/mtcat.schema.json
```

The document points at it with a relative `portal.schema_url` (`"mtcat.schema.json"`), so a harvester that
has fetched `mtcat.json` can resolve and validate against the schema without knowing the host.

The shipped copy, which the build serves byte-identically, lives at:

```text
engine/schema/mtcat.schema.json
```

---

## Principle

MTCAT should remain small.

It exists so that portals and repositories can exchange discovery records without exchanging the underlying datasets.

The schema should describe enough to answer:

- What collections exist?
- What surveys exist?
- Where are they?
- Which stations exist?
- Which organisation published them?
- What access conditions apply?

It should not attempt to become a full scientific data model.