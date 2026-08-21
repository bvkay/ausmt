# Reference

The machine-readable surfaces AusMT publishes, in two tiers: the public contracts, each with the
artifact that defines it and the page that documents it field by field, and the download surface.
Paths are relative to the portal root: `/data/mtcat.json` means `<portal root>/data/mtcat.json`.

## Documentation versions

This documentation is versioned with the MTCAT schema: a documentation version is cut per schema
version, as an annotated `docs-mtcat-<version>` tag on the commit the schema version changed at. The
tags are the version list; nothing in the repository enumerates them.

**The current documentation describes schema version 2.0.** Check `portal.version` in
`/data/mtcat.json` to see which schema version a deployment serves; where a deployment serves a
different version, the served document is the authority for that deployment.

## Public contracts

Three metadata documents are contracts: their shape is promised, schema-versioned and documented field
by field. Nothing else under `/data` is.

| Contract | Served path | Normative artifact | Version | Reference |
|---|---|---|---|---|
| MTCAT catalogue | `/data/mtcat.json` | `engine/schema/mtcat.schema.json` | 2.0 | [MTCAT schema](mtcat-schema.md) |
| MTCAT schema | `/data/mtcat.schema.json`, `/data/schemas/mtcat/2.0/mtcat.schema.json` | itself | 2.0 | [MTCAT schema](mtcat-schema.md#normative-artifact) |
| Per-station record | `/data/products/<slug>/<station>/station.json` | the build's product emitter; its schema artifact arrives with the station promotion lane | none declared | [Per-station products](station-products.md#1-stationjson) |
| Survey metadata | `survey-metadata.json`, not yet served | arrives with the survey-metadata lane | | the survey record's owner; until it ships, the survey-level facts are the ones `mtcat.json` carries |

## Download surface

Public by nature and documented as downloads, never as metadata contracts. The download index promises
its row shape (`url`, `size`, `sha256`, `format`, `tier`, `license`) and nothing more.

| Surface | Served path | Reference |
|---|---|---|
| Download index | `/data/manifest.json` | [Download inventory](../interoperability/api-reference.md#download-inventory-manifestjson) |
| Transfer-function files | `/data/edi/<slug>/<file>.edi`, `/data/xml/<slug>/<station>.xml`, `/data/h5/<slug>/<station>.h5`, paths read from the index | [Per-station fetch](../interoperability/api-reference.md#per-station-fetch-through-the-manifest) |
| Survey bundles | `/data/bundles/<slug>-edi.zip`, `-xml.zip`, `-tf.h5` | [Whole-survey bundles](../interoperability/api-reference.md#whole-survey-bundles) |
| Survey feed | `/data/feed.xml`, Atom 1.0 (RFC 4287) | [feed.xml](../interoperability/api-reference.md#feedxml) |
| Stations GeoJSON | `/data/stations.geojson`, a GIS export (RFC 7946) | [stations.geojson](../interoperability/api-reference.md#stationsgeojson) |
| Releases tier | `/data/releases/releases.json`, `/data/releases/<tag>/` | [Releases tier](releases.md) |

Everything else under `/data` is portal-internal or operator-only: served because the site needs it,
with no contract and no stability promise, and documented only in the Developer section.

## Source documents

Not served; they define what the served documents are built from.

| Document | Location | Normative artifact | Version | Reference |
|---|---|---|---|---|
| Survey metadata record | `survey.yaml`, one per survey package | the survey validator | `schema_version` 0.2 or 0.3 | [survey.yaml reference](survey-yaml.md) |

## Reading the field entries

The numbered field entries on [MTCAT schema](mtcat-schema.md), the
[survey.yaml reference](survey-yaml.md), [Per-station products](station-products.md) and the
[Releases tier](releases.md) carry the same rows.

| Row | Meaning |
|---|---|
| Definition | What the field states. |
| Obligation | `mandatory` (the artifact is invalid without it), `recommended` (emitted whenever the value exists), `optional`. |
| Occurrence | `1` exactly one, `0-1` at most one, `1-n` one or more, `0-n` any number. |
| Type | JSON type, including `null` where null is a valid value. |
| Allowed values | The controlled list, where one applies. |
| Default | The value assumed when the field is absent, where one applies. |
| Example | A value from the served corpus. |
| Note | Non-normative guidance. Every other row is normative. |

## Other reference pages

- [Glossary](glossary.md)
- [License](license.md)
