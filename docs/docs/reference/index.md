# Reference

Every machine-readable surface AusMT publishes, with the artifact that defines it and the page that
documents it field by field.

Paths in the Reference section are relative to the portal root: `/data/mtcat.json` means
`<portal root>/data/mtcat.json`. Join them onto the deployment you are reading from.

## Documentation versions

This documentation is versioned with the MTCAT schema. A documentation version is cut per MTCAT
schema version, as an annotated `docs-mtcat-<version>` tag on the commit the schema version changed
at, so the pages behind a cut describe every surface as that schema version serves it. The tags are
the version list; nothing in the repository enumerates them, so a cut needs no file change.

**The current documentation describes schema version 1.2.** Check `portal.version` in
`/data/mtcat.json` to see which schema version a deployment serves. Where a deployment serves a
different version, the served document is the authority for that deployment.

## Served documents

| Document | Served path | Normative artifact | Version | Reference |
|---|---|---|---|---|
| MTCAT catalogue | `/data/mtcat.json` | `engine/schema/mtcat.schema.json` | 1.2 | [MTCAT schema](mtcat-schema.md) |
| MTCAT schema | `/data/mtcat.schema.json` | itself | 1.2 | [MTCAT schema](mtcat-schema.md#normative-artifact) |
| Download manifest | `/data/manifest.json`, `/data/products/manifest.json` | `engine/schema/manifest.schema.json` | 1.0 | [Download manifest schema](manifest-schema.md) |
| Build report | `/data/build_report.json` | `engine/schema/build_report.schema.json` | 1.0 | [Build report schema](build-report-schema.md) |
| Station catalogue | `/data/catalogue.json` | `contract/columns.json` | 16 columns | [Portal data files](../developer/data-files.md) |
| Science diagnostics | `/data/sci.json` | `contract/columns.json` | 12 columns | [Portal data files](../developer/data-files.md) |
| Transfer-function curves | `/data/tf.json` | `contract/columns.json` | 18 columns | [Portal data files](../developer/data-files.md) |
| Survey metadata | `/data/surveys.json` | `survey_meta_from_yaml` in the build | none declared | [Served documents](portal-documents.md#surveysjson) |
| Collections | `/data/collections.json` | `collections_document` in the build | none declared | [Served documents](portal-documents.md#collectionsjson) |
| Build identity | `/data/build.json` | the build | none declared | [Served documents](portal-documents.md#buildjson) |
| Build provenance | `/data/build_provenance.json` | the build | none declared | [Served documents](portal-documents.md#build_provenancejson) |
| Coordinate policy | `/data/coord_policy.json` | the build | none declared | [Served documents](portal-documents.md#coord_policyjson) |
| Base station ids | `/data/base_ids.json` | the build | none declared | [Served documents](portal-documents.md#base_idsjson) |
| QC report | `/data/qc_report.json` | the build | none declared | [Served documents](portal-documents.md#qc_reportjson) |
| Survey feed | `/data/feed.xml` | Atom 1.0 (RFC 4287) | none declared | [Served documents](portal-documents.md#feedxml) |
| Digest stamp sidecar | `/data/products/survey_digests.json` | the build | none declared | [Build lifecycle](../developer/build-lifecycle.md#the-build-step-by-step) |
| Per-station record | `/data/products/<slug>/<station>/station.json` | the build | none declared | [Per-station products](station-products.md#1-stationjson) |
| Dimensionality screening | `/data/products/<slug>/<station>/dimensionality.json` | the build | none declared | [Per-station products](station-products.md#2-dimensionalityjson) |
| Releases index | `/data/releases/releases.json` | `cut_release` | 1.0 | [Releases tier](releases.md#1-releasesjson) |
| Release record | `/data/releases/<tag>/release.json` | `cut_release` | none declared | [Releases tier](releases.md#2-releasejson) |
| DataCite record | `/data/releases/<tag>/datacite.json` | DataCite Metadata Schema 4 | kernel-4 | [Releases tier](releases.md#3-datacitejson) |

The digest stamp sidecar is operational rather than scientific. It maps each served survey's slug to
`{yaml_digest_current, xml_digest_stamped}`: the digest of the `survey.yaml` the build read, and the
digest each served station XML was produced under. `engine/scripts/verify.py` compares those stamps
against the live sources, so a product served from a stale cache entry fails verification. It is
listed here because it is served, not because a consumer is expected to read it.

## Source documents

These are not served. They define what the served documents are built from.

| Document | Location | Normative artifact | Version | Reference |
|---|---|---|---|---|
| Survey metadata record | `survey.yaml`, one per survey package | the survey validator | `schema_version` 0.2 or 0.3 | [survey.yaml reference](survey-yaml.md) |
| Positional column order | `contract/columns.json` | itself | append-only | [Portal data files](../developer/data-files.md) |

## Reading the field entries

The numbered field entries on [MTCAT schema](mtcat-schema.md), [Download manifest
schema](manifest-schema.md), [Build report schema](build-report-schema.md), the
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

[Served documents](portal-documents.md) uses a compact `Member | Type | Definition` table instead. The
documents on that page declare no schema and no obligations, so whether a member is present is stated in
its Definition rather than in an Obligation row. `Note` means the same thing there: non-normative, and
everything outside it normative.

## Other reference pages

- [Glossary](glossary.md)
- [License](license.md)
