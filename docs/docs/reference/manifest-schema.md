# Download manifest schema

`manifest.json` is the key-based index of every downloadable AusMT artifact. It states what can be
downloaded for a station or a survey, in which format, from where, and with what integrity (size and
SHA-256).

It rides beside the positional `catalogue.json` / `sci.json` / `tf.json` arrays. Download metadata is
never added as new positional columns, so adding or changing it costs the index-reading consumers
nothing. The portal's download resolver is the primary consumer; the fetch patterns are in the
[data reference](../interoperability/api-reference.md#per-station-fetch-through-the-manifest) and the
producer-side rules are in [Portal data files](../developer/data-files.md#manifestjson-key-based-download-index-rides-beside-the-positional-catalogue).

## Normative artifact

| | |
|---|---|
| Normative artifact | `engine/schema/manifest.schema.json`, JSON Schema draft-07 |
| Served location | `/data/manifest.json` (compact) and `/data/products/manifest.json` (indented) |
| `$id` | `https://ausmt.org/schema/manifest-1.0.schema.json` |
| Schema version | 1.0, carried in the schema filename |
| Validated | the build validates the emitted manifest against the shipped schema before publishing |

Where this page and the schema disagree, the schema is right.

The two served copies parse to identical content. The build writes one compact and one indented; the
portal's own resolver reads `/data/manifest.json`.

## Document structure

| Key | Obligation | Type | Contents |
|---|---|---|---|
| `generated_count` | mandatory | integer | total artifacts, `len(files) + len(bundles)` |
| `base_url` | optional | string | URL prefix applied to artifact urls |
| `files` | mandatory | array of object | per-station downloadable artifacts |
| `bundles` | mandatory | array of object | per-survey bundles |

An empty deployment emits a valid empty manifest:

```json
{ "generated_count": 0, "base_url": "", "files": [], "bundles": [] }
```

Rows use `additionalProperties: false`, so an unrecognised key in a `files[]` or `bundles[]` row is a
validation failure rather than a local extension. The document root stays open.

---

## 1 Document keys

### 1.1 generated_count

| | |
|---|---|
| Definition | Total number of artifacts the manifest indexes. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | integer, minimum 0 |
| Example | `2421` |
| Note | Equal to `len(files) + len(bundles)`. Use it as a cheap sanity check after parsing. |

### 1.2 base_url

| | |
|---|---|
| Definition | URL prefix applied to every artifact `url` in this document. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Default | `""`, meaning the urls are portal-relative |
| Example | `""` |
| Note | The escape hatch for a deployment that publishes artifacts elsewhere. When it is set, join `url` onto it instead of onto the portal data root. A row whose `url` already carries a scheme needs no joining at all. |

---

## 2 files[]

One row per downloadable file for one station.

```json
{
  "ausmt_id": "au.vulcan-2022.A1",
  "survey": "Vulcan 2022",
  "station": "A1",
  "format": "edi",
  "url": "edi/vulcan-2022/Vulcan_A1.edi",
  "size": 48213,
  "sha256": "0d70…",
  "tier": "repo",
  "license": "CC-BY-4.0"
}
```

### 2.1 files[].ausmt_id

| | |
|---|---|
| Definition | The station's unique public id, and the join key back to the station catalogue. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Format | `au.<slug>.<station>` |
| Example | `"au.vulcan-2022.A1"` |
| Note | The one identifier a catalogue row and a manifest row both carry. Catalogue column 12. |

### 2.2 files[].survey

| | |
|---|---|
| Definition | The survey's display name. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"Vulcan 2022"` |
| Note | This is the display name, not the slug. To filter by slug, test `ausmt_id` for the prefix `au.<slug>.` instead. |

### 2.3 files[].station

| | |
|---|---|
| Definition | Station id within the survey. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"A1"` |

### 2.4 files[].format

| | |
|---|---|
| Definition | Artifact format of this row. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | `edi`, `emtfxml` |
| Example | `"edi"` |
| Note | `mth5` is a per-survey bundle format and never appears here. Filtering station rows by it returns nothing. |

### 2.5 files[].url

| | |
|---|---|
| Definition | Where the artifact is served. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string or null |
| Example | `"edi/vulcan-2022/Vulcan_A1.edi"` |
| Note | For `tier: "repo"` this is a portal-relative path joined onto `base_url`. For `tier: "nci"` it is an absolute NCI THREDDS fileServer URL. It is `null` only when a `tier: "nci"` survey has no resolvable base. A served filename is not derivable from the station id, so read the path from here rather than templating one. |

### 2.6 files[].size

| | |
|---|---|
| Definition | Size in bytes of the served artifact. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | integer, minimum 0 |
| Example | `48213` |

### 2.7 files[].sha256

| | |
|---|---|
| Definition | SHA-256 of the served artifact. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string matching `^[0-9a-f]{64}$` |
| Note | The digest is of the bytes the server hands you, so a download is checkable end to end. See [Integrity across builds](#integrity-across-builds) for which formats are byte-reproducible. |

### 2.8 files[].tier

| | |
|---|---|
| Definition | Which hosting tier serves this artifact. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | `repo`, `nci` |
| Example | `"repo"` |

### 2.9 files[].license

| | |
|---|---|
| Definition | The survey's licence as declared, carried on the row so a consumer never has to resolve one. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"CC-BY-4.0"` |
| Note | A row exists only for a survey whose licence is on the redistributable list, so a licence here is always a redistributable one. |

### 2.10 files[].canon_license

| | |
|---|---|
| Definition | Canonical, de-aliased licence id of the raw `license` string. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Example | `"CC-BY-4.0"` |
| Note | Use this rather than `license` when grouping or comparing licences across surveys; `license` is the string as declared. |

### 2.11 files[].custodian

| | |
|---|---|
| Definition | Custodian of record for the artifact: the declared rights custodian, falling back to the survey's organisation. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `"Geological Survey of South Australia"` |

---

## 3 bundles[]

One row per pre-built per-survey download.

```json
{
  "survey": "Vulcan 2022",
  "slug": "vulcan-2022",
  "format": "edi-zip",
  "url": "bundles/vulcan-2022-edi.zip",
  "size": 1841022,
  "sha256": "9c31…",
  "tier": "repo",
  "license": "CC-BY-4.0",
  "n_stations": 34
}
```

### 3.1 bundles[].survey

| | |
|---|---|
| Definition | The survey's display name. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"Vulcan 2022"` |

### 3.2 bundles[].slug

| | |
|---|---|
| Definition | The survey slug, path-safe and the key used in bundle filenames. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"vulcan-2022"` |
| Note | A bundle row carries the slug where a `files[]` row carries only the display name. To group bundles per survey, group on this. |

### 3.3 bundles[].format

| | |
|---|---|
| Definition | Bundle format of this row. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | `edi-zip`, `xml-zip`, `mth5` |
| Example | `"edi-zip"` |
| Note | `mth5` here is a transfer-function-only HDF5 file for the whole survey. |

### 3.4 bundles[].url

| | |
|---|---|
| Definition | Where the bundle is served. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string or null |
| Example | `"bundles/vulcan-2022-edi.zip"` |
| Note | Same tier rules as [2.5 files url](#25-filesurl). |

### 3.5 bundles[].size

| | |
|---|---|
| Definition | Size in bytes of the served bundle. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | integer, minimum 0 |

### 3.6 bundles[].sha256

| | |
|---|---|
| Definition | SHA-256 of the served bundle. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string matching `^[0-9a-f]{64}$` |

### 3.7 bundles[].tier

| | |
|---|---|
| Definition | Which hosting tier serves this bundle. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | `repo`, `nci` |

### 3.8 bundles[].license

| | |
|---|---|
| Definition | The survey's licence as declared. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"CC-BY-4.0"` |
| Note | A `LICENSE.txt` carrying the same licence and its required attribution rides inside each zip. The MTH5 bundle carries it as an attribute instead, on `Experiment/Surveys/<slug>` as `release_license`. |

### 3.9 bundles[].canon_license

| | |
|---|---|
| Definition | Canonical, de-aliased licence id of the raw `license` string. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |

### 3.10 bundles[].custodian

| | |
|---|---|
| Definition | Custodian of record for the bundle. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |

### 3.11 bundles[].n_stations

| | |
|---|---|
| Definition | Number of stations inside the bundle. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | integer, minimum 0 |
| Example | `34` |

---

## Semantics

### URLs are portal-relative by default

The served forms are `edi/<slug>/<file>.edi`, `xml/<slug>/<station>.xml`, `bundles/<slug>-edi.zip`,
`bundles/<slug>-xml.zip` and `bundles/<slug>-tf.h5`. The portal joins each url onto its configured data
base, so moving a tier to NCI is a manifest change with no consumer edits.

### Integrity across builds

The digests are of the served bytes in every case. EDI copies and the per-survey EDI zip are
byte-reproducible across builds given a fixed zlib, so their SHA-256 is a stable cross-build invariant.
EMTF XML, the EMTF-XML zip and the transfer-function MTH5 embed timestamps and UUIDs and are not
byte-reproducible: their SHA-256 is a per-build download-integrity hash, not a cross-build invariant.

### The manifest lists only what AusMT serves

Only redistributably licensed surveys with an open access level appear. A non-served station has no row,
and the portal routes it to the source archive through the catalogue's `edi_available` bit. An embargoed
survey has no rows at all, so a consumer has no access error to handle and no request to make.

### Feature flags gate the optional bundles

The bundle set is gated by the deployment's `flags:` configuration and recorded in
`build_provenance.json` under `distribution_flags`. `survey_h5_enabled` produces the per-survey
transfer-function MTH5 and ships enabled; `collection_h5_enabled` gates the collection-level producer and
`collection_download_enabled` gates its portal tile, and both ship disabled. The EDI zip and the
EMTF-XML zip are unconditional for a served survey.

## Versioning

The schema id carries the version. Minor updates may add optional fields; incompatible changes bump the
major version and ship as a separate schema file, mirroring the MTCAT policy.
