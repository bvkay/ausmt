# MTCAT schema

MTCAT (Magnetotelluric Catalogue) is a JSON discovery schema for exchanging information about MT
holdings between repositories. An MTCAT document describes the collections, surveys, stations and
transfer-function availability that a portal exposes, and answers four questions: what collections and
surveys exist, where they are and which stations they hold, which organisation published them, and what
access conditions apply.

MTCAT carries no transfer functions, no time series, no derived products and no inversion models. It
replaces neither EDI, EMTF XML, MTH5 nor mt_metadata. The survey package is the authoritative scientific
object; an MTCAT record is a discovery record describing it.

Two fields on a survey record are owned elsewhere in this documentation and this page describes only how
they are served: the two-list credit model is specified in
[survey.yaml](survey-yaml.md#3-credit-creators-and-contributors), and what an access level does to the
bytes is specified in [Publication](../operations/publication.md#access-levels-and-embargoes).

## Normative artifact

| | |
|---|---|
| Normative artifact | `engine/schema/mtcat.schema.json`, JSON Schema draft-07 |
| Served location | `/data/mtcat.schema.json`, beside the document it describes |
| `$id` | `https://ausmt.au/data/mtcat.schema.json` |
| Schema version | 1.2, declared in the schema `title` |
| Document version | declared per document in `portal.version` |
| Validated | the build validates its emitted `mtcat.json` against the shipped schema before publishing, and copies that schema byte for byte to the served location |

Where this page and the schema disagree, the schema is right. Every field, type and controlled
vocabulary carries its own `description` in the schema, so the schema reads on its own and does not
depend on this page.

AusMT serves one schema file at one unversioned URL, and the schema's `$id` is that same URL. Each
consumer need is met without encoding the version in the path: the document states its version in
`portal.version`, the schema states its version in its `title`, and the served URL always resolves to
the current schema. A producer that wants older schema releases to stay addressable publishes them
alongside under whatever names it likes; the unversioned URL keeps resolving to the current one.

## Document structure

| Key | Obligation | Type | Contents |
|---|---|---|---|
| `portal` | mandatory | object | identity of the producing portal |
| `surveys` | mandatory | array of object | the discovery records |
| `stations` | mandatory | array of object | site-level discovery records |
| `collections` | optional | array of object | roll-up groupings over surveys |
| `mt_metadata_version` | optional | string or null | library version the build ran against |
| `mth5_version` | optional | string or null | library version the build ran against |

Unknown keys ride through. `additionalProperties` is true on every record object, so a consumer written
for one minor version reads a later one unchanged. The single exception is `surveys[].data_types`, which
is a map rather than a record: there `propertyNames` pins the key names, because an unexpected key is an
unknown band and not a local extension.

---

## 1 portal

The portal object identifies the catalogue source.

```json
{
  "portal_id": "ausmt",
  "portal_name": "AusMT",
  "schema": "mtcat",
  "version": "1.2",
  "schema_url": "mtcat.schema.json",
  "metadata_license": "CC0-1.0",
  "generated_at": "2026-07-27T08:29:39Z"
}
```

### 1.1 portal.portal_id

| | |
|---|---|
| Definition | Stable identifier of the portal that produced this document. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Example | `"ausmt"` |

### 1.2 portal.portal_name

| | |
|---|---|
| Definition | Display name of the portal that produced this document. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"AusMT"` |

### 1.3 portal.schema

| | |
|---|---|
| Definition | Names the interchange schema this document is written to. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | `mtcat` |
| Example | `"mtcat"` |

### 1.4 portal.version

| | |
|---|---|
| Definition | MAJOR.MINOR version of the MTCAT schema this document was written against. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string matching `^[0-9]+\.[0-9]+$` |
| Example | `"1.2"` |
| Note | Read the version from here rather than assuming one. A deployment updates its served schema on its next data build, so a served document can trail the schema in this repository by one version. |

### 1.5 portal.schema_url

| | |
|---|---|
| Definition | Location of the MTCAT schema served beside this document, so a harvester can validate without resolving the `$id` host. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string, relative or absolute |
| Example | `"mtcat.schema.json"` |

### 1.6 portal.metadata_license

| | |
|---|---|
| Definition | Licence of the catalogue metadata itself, as an SPDX identifier. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `"CC0-1.0"` |
| Note | This covers the catalogue metadata only. A survey's data licence is [2.6 surveys[].license](#26-surveyslicense) and varies by survey. Conflating the two republishes restricted data under CC0. |

### 1.7 portal.generated_at

| | |
|---|---|
| Definition | UTC build timestamp of this document. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, ISO 8601 with a `Z` suffix |
| Example | `"2026-07-27T08:29:39Z"` |

---

## 2 surveys[]

Survey records are the main discovery objects. Each is keyed by `survey_id`, which is the survey slug.

```json
{
  "survey_id": "auslamp-musgraves-apy-2016",
  "title": "AusLAMP Musgraves APY 2016",
  "organisation": "Geological Survey of South Australia",
  "country": "Australia",
  "license": "CC-BY-4.0",
  "access": "open",
  "collection_id": "auslamp",
  "version": "1.0.0",
  "bbox": {"west": 128.9, "south": -27.1, "east": 133.6, "north": -25.8},
  "centroid": {"latitude": -26.45, "longitude": 131.25},
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

### 2.1 surveys[].survey_id

| | |
|---|---|
| Definition | The survey's slug, and the key every other document joins a survey on. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Format | lowercase, hyphen separated, matching `^[a-z0-9]+(-[a-z0-9]+)*$` |
| Example | `"vulcan-2022"` |

### 2.2 surveys[].title

| | |
|---|---|
| Definition | Human-readable survey name. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"Vulcan 2022"` |

### 2.3 surveys[].organisation

| | |
|---|---|
| Definition | Custodian organisation of the survey. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"University of Adelaide"` |

### 2.4 surveys[].country

| | |
|---|---|
| Definition | Country the survey was acquired in. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"Australia"` |

### 2.5 surveys[].doi

| | |
|---|---|
| Definition | DOI of the survey dataset, where the custodian has minted one. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `null` |
| Note | AusMT mints no DOIs. Identifiers pointing at records AusMT does not own are carried in [2.25 surveys[].related_identifiers](#225-surveysrelated_identifiers). |

### 2.6 surveys[].license

| | |
|---|---|
| Definition | Licence the survey data is released under. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `"CC-BY-4.0"` |

### 2.7 surveys[].access

| | |
|---|---|
| Definition | Normalised access level of this survey. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Allowed values | `open`, `metadata_only`, `embargoed` |
| Note | Not enum-pinned in the schema. The producer normalises but does not coerce an unrecognised level, and anything other than `open` withholds the bytes, so an unexpected token here means a withheld survey rather than a broken document. |

### 2.8 surveys[].embargo_until

| | |
|---|---|
| Definition | ISO date the declared embargo lapses. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Format | `YYYY-MM-DD` |
| Example | `"2027-06-30"` |
| Note | Present only for a survey that declares an end date, so absence means no declared end date rather than not embargoed. A date that has passed publishes nothing by itself; a curator releases a survey by changing the level. |

### 2.9 surveys[].bbox

| | |
|---|---|
| Definition | Geographic footprint, derived from this survey's served station coordinates. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | object or null, with required members `west`, `south`, `east`, `north`, each a number |
| Default | `null` when the survey has no located station |
| Example | `{"west": 135.1, "south": -31.2, "east": 136.4, "north": -30.4}` |

### 2.10 surveys[].centroid

| | |
|---|---|
| Definition | Centre of the survey's bbox. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | object or null, with required members `latitude`, `longitude`, each a number |
| Default | `null` when the survey has no located station |
| Example | `{"latitude": -30.8, "longitude": 135.7}` |
| Note | A survey centroid is the centre of its bbox. A [collection centroid](#411-collectionscentroid) is the mean of its member station positions. The two are computed differently. |

### 2.11 surveys[].n_stations

| | |
|---|---|
| Definition | Count of this survey's stations in this document's `stations[]` array. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | integer, minimum 0 |
| Example | `88` |
| Note | Derived, so it exists to size a survey without walking the station list. `stations[]` stays authoritative if the two ever disagree. |

### 2.12 surveys[].data_types

| | |
|---|---|
| Definition | The survey's band mix, as a map of band to station count, derived by counting this survey's `stations[]` entries. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | object, integer values with minimum 0 |
| Allowed values | keys drawn from `AMT`, `BBMT`, `LPMT`, `GDS`, `unknown` |
| Default | `{}` for a survey with no stations |
| Example | `{"BBMT": 62, "LPMT": 26}` |
| Note | Emitted in the canonical band order BBMT, LPMT, AMT, GDS. This is the one object in the document whose keys are pinned, because an unexpected key is an unknown band and not a local extension. |

### 2.13 surveys[].period_min_s

| | |
|---|---|
| Definition | Shortest period across this survey's stations, in seconds. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | number greater than 0, or null |
| Default | `null` when no station reports a period range |
| Example | `8.0` |

### 2.14 surveys[].period_max_s

| | |
|---|---|
| Definition | Longest period across this survey's stations, in seconds. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | number greater than 0, or null |
| Default | `null` when no station reports a period range |
| Example | `16384.041943` |

### 2.15 surveys[].n_stations_tipper

| | |
|---|---|
| Definition | How many of this survey's stations carry a tipper, derived from the per-station component list. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | integer, minimum 0 |
| Example | `88` |
| Note | Always less than or equal to `n_stations`. Compare the two to read tipper coverage across the survey. |

### 2.16 surveys[].formats

| | |
|---|---|
| Definition | The distribution formats served for this survey, derived from the build's download manifest. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | array of string, unique |
| Allowed values | `edi`, `edi-zip`, `emtfxml`, `mth5`, `xml-zip` |
| Example | `["edi", "edi-zip", "emtfxml", "mth5", "xml-zip"]` |
| Note | An empty array means this build distributes nothing for this survey, which covers a withheld survey and a metadata-only build alike. It never means unknown. An AusMT build always derives the key from the manifest it has just written, so the key is always present; absence is reserved for a producer with no manifest to derive from, and there means not known. |

### 2.17 surveys[].year_start

| | |
|---|---|
| Definition | First year of acquisition the survey declares. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | integer or null |
| Default | `null` when the survey declares no date |
| Example | `2016` |
| Note | Passed through from the survey's declared date range, never inferred from file timestamps. |

### 2.18 surveys[].year_end

| | |
|---|---|
| Definition | Last year of acquisition the survey declares. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | integer or null |
| Default | `null` when the survey declares no date, equal to `year_start` for a single-season survey |
| Example | `2018` |

### 2.19 surveys[].version

| | |
|---|---|
| Definition | Semantic version of the AusMT survey package. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Format | `MAJOR.MINOR.PATCH` |
| Example | `"1.0.0"` |
| Note | This is the survey package version, not the MTCAT schema version. |

### 2.20 surveys[].collection_id

| | |
|---|---|
| Definition | Id of the collection or programme this survey belongs to. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `"auslamp"` |
| Note | Matches a [4.1 collections[].collection_id](#41-collectionscollection_id) in this document when the collection is published here. Grouping is an exact string match. |

### 2.21 surveys[].organisation_ror

| | |
|---|---|
| Definition | ROR identifier of the custodian organisation. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `"https://ror.org/00892tw58"` |

### 2.22 surveys[].raid

| | |
|---|---|
| Definition | RAiD (Research Activity Identifier) of the project. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `"https://raid.org/10.12345/AB1234"` |

### 2.23 surveys[].creators[]

| | |
|---|---|
| Definition | The citation authors of this release, as DataCite creators. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of object |
| Example | `[{"name": "Family, Given", "name_type": "person", "orcid": "0000-0002-9738-7277"}]` |
| Note | Present only when the survey declares creators, so absence means undeclared rather than empty. Order is the citation author order and is preserved verbatim; see [Credit is two lists](#credit-is-two-lists-and-they-are-not-interchangeable). |

Row members:

| Member | Obligation | Type | Allowed values |
|---|---|---|---|
| `name` | mandatory | string, at least one character | free text, the creator as cited |
| `name_type` | recommended | string | `person`, `organisation` |
| `orcid` | optional | string | bare or full-URL ORCID iD, people only |
| `ror` | optional | string | ROR identifier, organisations only |

A row that declares no `orcid` or `ror` omits the key rather than serving a null.

### 2.24 surveys[].contributors[]

| | |
|---|---|
| Definition | Who did what on this release, as DataCite contributors, in the export form. |
| Obligation | recommended |
| Occurrence | 0-n |
| Type | array of object |
| Example | `[{"name": "Geological Survey of South Australia", "name_type": "organisation", "role": "Distributor"}]` |
| Note | Emitted for every survey, because every survey in this document is hosted. The list is the survey's own declared contributors in declared order, followed by the hosting portal appended with role `HostingInstitution`. Order carries no citation meaning. |

Row members:

| Member | Obligation | Type | Allowed values |
|---|---|---|---|
| `name` | mandatory | string, at least one character | free text |
| `name_type` | recommended | string | `person`, `organisation` |
| `role` | recommended | string | the nine DataCite contributor types listed under [Credit is two lists](#credit-is-two-lists-and-they-are-not-interchangeable) |
| `orcid` | optional | string | bare or full-URL ORCID iD |
| `ror` | optional | string | ROR identifier |

### 2.25 surveys[].related_identifiers[]

| | |
|---|---|
| Definition | The survey's typed provenance links to related records, chiefly the upstream time-series holdings a transfer-function release derives from. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of object |
| Example | `[{"identifier": "10.25914/bzd5-n780", "identifier_type": "DOI", "relation": "IsDerivedFrom", "identifies": "raw_packed", "custodian": "NCI", "resolution": "ok"}]` |
| Note | Present only when the survey declares at least one. The vocabularies and the reading direction are set out under [related_identifiers records what a survey points at](#related_identifiers-records-what-a-survey-points-at). |

Row members:

| Member | Obligation | Type | Allowed values |
|---|---|---|---|
| `identifier` | recommended | string or null | free text |
| `identifier_type` | recommended | string or null | four identifier types, enum-pinned |
| `relation` | recommended | string or null | six DataCite relation types, enum-pinned |
| `identifies` | recommended | string | seven NCI data levels, enum-pinned |
| `custodian` | optional | string or null | free text, because the custodian may be any archive |
| `resolution` | optional | string | `ok`, `reserved` |

### 2.26 surveys[].attribution

| | |
|---|---|
| Definition | Rights of this release: custodian of record, the required attribution statement, and the CC-BY changes declaration. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | object or null, open to further keys |
| Note | Present only when the survey declares it. |

Members:

| Member | Type | Definition |
|---|---|---|
| `custodian` | string or null | rights holder of record, which may differ from the acquiring organisation |
| `custodian_ror` | string or null | ROR identifier of that custodian |
| `statement` | string or null | attribution statement to reproduce verbatim where the upstream licence prescribes wording |
| `changes_made` | boolean or null | whether this release changed the upstream material, per CC-BY 4.0 section 3(a) |
| `changes_summary` | string or null | plain-language summary of what changed |
| `declared_by` | string or null | who recorded the declaration |
| `declared_date` | string or null | ISO date the declaration was recorded, not a date of the data |

### 2.27 surveys[].sources[]

| | |
|---|---|
| Definition | Upstream source datasets this release was built from, one entry per obtained dataset. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of object, or null |
| Note | Present only when the survey declares them. |

Row members:

| Member | Type | Definition |
|---|---|---|
| `title` | string or null | title of the upstream dataset as obtained |
| `custodian` | string or null | who published the upstream dataset |
| `identifier` | string or null | identifier of the upstream dataset |
| `identifier_type` | string or null | same vocabulary as `related_identifiers[].identifier_type` |
| `relation` | string or null | same vocabulary as `related_identifiers[].relation` |
| `identifies` | string | same vocabulary as `related_identifiers[].identifies` |
| `licence` | string or null | licence the source was obtained under. Note the spelling: this key is `licence`, unlike the survey-level `license` |
| `retrieved` | string or null | when the source was obtained, at whatever precision is known |
| `statement` | string or null | attribution wording the source custodian prescribes |
| `profile` | string or null | which custodian attribution profile applies when composing the notice |

### 2.28 surveys[].changes

| | |
|---|---|
| Definition | The survey's declared changes descriptor, per CC-BY 4.0 section 3(a). |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | object or null |
| Note | Present only when the survey declares `changes_made`. |

Members:

| Member | Type | Definition |
|---|---|---|
| `made` | boolean | whether the upstream material was changed in producing this release |
| `summary` | string | plain-language summary; an empty string when changes were declared without one |

---

## 3 stations[]

Station records are flat and small. Detailed station metadata stays in the survey package and in the
underlying MT metadata structures.

```json
{
  "station_id": "au.vulcan-2022.A1",
  "survey_id": "vulcan-2022",
  "latitude": -30.123,
  "longitude": 135.456,
  "data_type": "BBMT"
}
```

### 3.1 stations[].station_id

| | |
|---|---|
| Definition | Globally unique station identifier, which is the `ausmt_id` every other document carries. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Format | `au.<slug>.<station>` |
| Example | `"au.vulcan-2022.A1"` |

### 3.2 stations[].survey_id

| | |
|---|---|
| Definition | The survey this station belongs to. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Example | `"vulcan-2022"` |
| Note | Matches [2.1 surveys[].survey_id](#21-surveyssurvey_id). |

### 3.3 stations[].latitude

| | |
|---|---|
| Definition | WGS84 latitude in decimal degrees. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | number between -90 and 90, or null |
| Example | `-30.123` |
| Note | This is the position the custodian chose to publish, not necessarily the surveyed position. A position may be generalised to 0.1 degrees or withheld as `null`; see [Coordinate access](../rationale/coordinate-access.md). |

### 3.4 stations[].longitude

| | |
|---|---|
| Definition | WGS84 longitude in decimal degrees. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | number between -180 and 180, or null |
| Example | `135.456` |
| Note | See the note on latitude. |

### 3.5 stations[].data_type

| | |
|---|---|
| Definition | The station's band, derived from its shortest period and which transfer functions are present. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | `AMT` audio-magnetotelluric, shortest period under 1e-3 s; `BBMT` broadband, shortest period under 1 s; `LPMT` long period; `GDS` geomagnetic depth sounding, a tipper-only station with no impedance; `unknown` no period range could be read |
| Example | `"BBMT"` |
| Note | The band is derived, never declared by the survey. Canonical presentation order is BBMT, LPMT, AMT, GDS. |

---

## 4 collections[]

Collections group related surveys for discovery and navigation. They are roll-ups: a collection holds no
transfer functions of its own, and all scientific provenance stays with its member surveys.

```json
{
  "collection_id": "auslamp",
  "title": "AusLAMP",
  "type": "programme",
  "status": "active",
  "start_year": 2013,
  "last_updated": "2026-07-12",
  "n_surveys": 9,
  "n_stations": 459,
  "bbox": {"west": 128.9, "south": -38.1, "east": 141.0, "north": -25.8},
  "centroid": {"latitude": -31.4, "longitude": 135.2}
}
```

### 4.1 collections[].collection_id

| | |
|---|---|
| Definition | Id that member surveys point at through `surveys[].collection_id`. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Format | lowercase, hyphen separated |
| Example | `"auslamp"` |
| Note | Grouping is an exact string match. Two ids differing only in case are two collections. |

### 4.2 collections[].title

| | |
|---|---|
| Definition | Display name of the collection. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"AusLAMP"` |

### 4.3 collections[].type

| | |
|---|---|
| Definition | What kind of grouping this is. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Allowed values | `programme`, `release`, `institutional`, `other` |
| Example | `"programme"` |

### 4.4 collections[].status

| | |
|---|---|
| Definition | Lifecycle state of the programme. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Allowed values | `active`, `completed`, `archived` |
| Default | `null` where member surveys declared a value outside that set |
| Example | `"active"` |
| Note | Not enum-pinned in the schema, because the producer already reduces an unrecognised value to null and warns. |

### 4.5 collections[].start_year

| | |
|---|---|
| Definition | Year the programme began, as declared by its member surveys. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | integer or null |
| Default | `null` when no member survey declares one |
| Example | `2013` |

### 4.6 collections[].last_updated

| | |
|---|---|
| Definition | ISO date the programme record was last updated. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Format | `YYYY-MM-DD` |
| Example | `"2026-07-12"` |
| Note | A curation date for the programme description. It is not the acquisition date of any survey and not the document's `generated_at`. |

### 4.7 collections[].description

| | |
|---|---|
| Definition | Prose description of the programme, as declared by its member surveys. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |

### 4.8 collections[].n_surveys

| | |
|---|---|
| Definition | How many surveys belong to this collection. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | integer, minimum 0 |
| Example | `9` |

### 4.9 collections[].n_stations

| | |
|---|---|
| Definition | How many stations the member surveys hold in total. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | integer, minimum 0 |
| Example | `459` |

### 4.10 collections[].bbox

| | |
|---|---|
| Definition | Footprint across every member survey's stations. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | object or null, same shape as [2.9 surveys[].bbox](#29-surveysbbox) |
| Default | `null` when no member station is located |

### 4.11 collections[].centroid

| | |
|---|---|
| Definition | Mean of the member station positions. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | object or null, with required members `latitude`, `longitude` |
| Default | `null` when no member station is located |
| Note | A collection centroid is the mean of its member station positions. A [survey centroid](#210-surveyscentroid) is the centre of its bbox. |

---

## 5 Document-level keys

### 5.1 mt_metadata_version

| | |
|---|---|
| Definition | Version of the mt_metadata library the producing build ran against. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Default | `null` when that library was not available to the build |
| Example | `"1.0.9"` |

### 5.2 mth5_version

| | |
|---|---|
| Definition | Version of the mth5 library the producing build ran against. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Default | `null` when that library was not available to the build |
| Example | `"0.6.8"` |

---

## Extensibility and compatibility

The schema permits additional properties, so a portal can carry local fields without breaking
interoperability. Local fields must never be required for basic discovery.

Minor schema updates add optional fields, or type fields a producer was already serving through
`additionalProperties`. Both are backward compatible: a document that validated against an earlier minor
version still validates. Major updates may introduce incompatible changes.

```text
1.x -> 2.0
```

Every field described here is typed, and where a value comes from a ratified vocabulary that vocabulary
is enum-pinned in the schema, so an out-of-vocabulary token fails the build rather than reaching a
consumer. Two fields are deliberately not pinned, [2.7 surveys[].access](#27-surveysaccess) and
[4.4 collections[].status](#44-collectionsstatus), because the producer passes an unrecognised value
through and withholds rather than failing the build.

---

## Reading a served survey record

This section is the consumer guide to the field meanings that a type alone cannot carry: which orders
matter, how a vocabulary should be read, what an absent key means, and which key joins to which. It
describes MTCAT v1.2. The document is served at [`/data/mtcat.json`](../interoperability/api-reference.md)
with the schema beside it at `/data/mtcat.schema.json`, so a second implementation can validate without
resolving anything off-site, and a fetched schema identifies its own version in its `title`.

### Credit is two lists, and they are not interchangeable

`creators[]` is the citation author list. Its ORDER is load-bearing, so reproduce it as given.

`contributors[]` records who did what. Each row carries a `role` from the eight DataCite contributor
types a survey may declare: `ProjectLeader`, `ProjectMember`, `DataCollector`, `ContactPerson`,
`DataCurator`, `Sponsor`, `RightsHolder`, `Distributor`. A ninth value, `HostingInstitution`, appears
only on the row AusMT appends to every survey for itself; no survey declares it. Order in
`contributors[]` carries no citation meaning.

Rows in both lists mark themselves `person` or `organisation` in `name_type` and carry `orcid` or `ror`
where one was declared. A row that declares neither omits the key rather than serving a null.

### related_identifiers records what a survey points at

Each row of `related_identifiers[]` carries the identifier and its `identifier_type` (`DOI`, `Handle`,
`URL`, `RAiD`), a DataCite `relation` to be read as "this survey *relation* that record", and
`identifies`, which states what data LEVEL the identifier points at in NCI Table 1 terms:

| `identifies` | what the identifier points at |
| --- | --- |
| `collection` | the parent collection record |
| `raw_packed` | raw time series, packed |
| `level0` | edited time series |
| `level1` | transformed time series |
| `level2` | processed data, EDI and transfer functions |
| `level3` | models |
| `entire` | one record covering all levels |

`resolution` states whether the identifier resolves, from a cached check the build consumes but never
performs. `ok` means it resolves today, `reserved` means registered but not yet active. The key is
ABSENT when the answer is unknown, and absent never means broken, so still link an identifier that
carries no `resolution`.

### Access and embargo withhold bytes, never discovery

`access` is the normalised level: `open`, `metadata_only` or `embargoed`. Only `open` distributes data.
Anything else, including a level AusMT does not recognise, fails closed.

An embargoed survey keeps its full catalogue record, its stations and its footprint, and only its bytes
are withheld, so it serves an empty `formats` list and has no rows in the download manifest.

`embargo_until` is present only when the survey declares an end date, so its absence means no declared
end date rather than "not embargoed". A date that has passed publishes nothing by itself. A curator
releases a survey by changing the level.

### One survey, two key names

MTCAT keys a survey by `survey_id`, which is the slug (`vulcan-2022` and the like).
`/data/surveys.json` is keyed by the survey's display NAME and carries that same slug under `slug`. The
download manifest names surveys by display name in `files[].survey` but by slug in `bundles[].slug`.

Below the survey, the stable join is the station. `ausmt_id` is the one identifier the catalogue row and
the manifest row both carry.
