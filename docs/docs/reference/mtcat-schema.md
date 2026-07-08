# MTCAT Schema

## Overview

MTCAT is a lightweight JSON-based discovery schema for magnetotelluric catalogue exchange.

It is designed to describe the collections, surveys, stations and transfer-function availability exposed by an MT portal or repository.

MTCAT does not store transfer functions.

It does not replace EDI, EMTFXML, MTH5 or mt_metadata.

Its purpose is discovery.

---

## Schema Version

Released schema files should include the schema version in the filename.

Recommended naming:

```text
mtcat-1.0.schema.json
```

Future releases should use separate schema files:

```text
mtcat-1.1.schema.json
mtcat-2.0.schema.json
```

The schema identifier should also include the version:

json "$id": "https://ausmt.org/schema/mtcat-1.0.schema.json" 

This makes schema validation explicit and avoids ambiguity when older MTCAT records are encountered.

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

json {   "portal_id": "ausmt",   "portal_name": "AusMT",   "schema": "mtcat",   "version": "1.0",   "generated_at": "2026-06-15T00:00:00Z" } 

The portal.version field records the MTCAT schema version used by the document.

The portal object also carries two optional fields: `schema_url`, the location of the MTCAT schema served beside the document (AusMT emits `"mtcat.schema.json"`, so a harvester can validate the catalogue without resolving the canonical `$id` host); and `metadata_license`, the licence of the catalogue metadata itself, distinct from the per-survey data licences (AusMT declares `CC0-1.0` so the discovery metadata may be freely harvested and redistributed).

---

## Collections

Collections are optional roll-up objects used to group related surveys.

Examples include:

- AusLAMP
- WAMT
- Institutional holdings
- State-based releases

Example:

json {   "collection_id": "auslamp",   "title": "AusLAMP",   "type": "programme",   "n_surveys": 6,   "n_stations": 1200 } 

Collections should be lightweight. They are intended for discovery and navigation, not detailed archival description.

---

## Surveys

Survey records are the main discovery objects.

Required fields:

json {   "survey_id": "vulcan-2022",   "title": "Vulcan MT Survey",   "organisation": "University of Adelaide",   "country": "Australia" } 

Recommended fields include:

json {   "doi": null,   "license": "CC-BY-4.0",   "access": "open",   "collection_id": "institutional",   "version": "1.0.0" } 

Spatial fields may include:

json {   "bbox": {     "west": 135.1,     "south": -31.2,     "east": 136.4,     "north": -30.4   },   "centroid": {     "latitude": -30.8,     "longitude": 135.7   } } 

The survey version field refers to the AusMT survey package version, not the MTCAT schema version.

---

## Stations

Station records describe site-level discovery information.

Required fields:

json {   "station_id": "V001",   "survey_id": "vulcan-2022",   "latitude": -30.123,   "longitude": 135.456,   "data_type": "BBMT" } 

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

Minor schema updates may add optional fields.

Examples:

```text
1.0 → 1.1
```

Major schema updates may introduce incompatible changes.

Examples:

```text
1.x → 2.0
```

Older released schema files should remain available.

MTCAT records should declare the schema version they use.

---

## Recommended Location

Published schemas should be available from a stable URL.

Example:

```text
https://ausmt.org/schema/mtcat-1.0.schema.json
```

A copy should also be stored in the documentation or schema repository.

Example:

```text
schemas/mtcat-1.0.schema.json
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