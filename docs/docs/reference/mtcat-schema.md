# MTCAT schema

MTCAT (Magnetotelluric Catalogue) is a JSON discovery schema for exchanging information about MT
holdings between repositories. An MTCAT document describes the collections, surveys, stations and
transfer-function availability that a portal exposes, and answers four questions: what collections and
surveys exist, where they are and which stations they hold, which organisation holds custodial
responsibility for them, and what access conditions apply.

MTCAT carries no transfer functions, no time series, no derived products and no inversion models. It
replaces neither EDI, EMTF XML, MTH5 nor mt_metadata. The survey package is the authoritative scientific
object; an MTCAT record is a discovery record describing it. Citation guidance also lives OUTSIDE
MTCAT: the catalogue exposes `doi` and `related_identifiers` for discovery only, and the richer
per-survey metadata document (a later lane) owns preferred-citation text, funding and acknowledgement
detail.

This page describes MTCAT 2.0, self-contained: every served field is defined here in full. Two survey
facts also have deeper treatments elsewhere in this documentation: the two-list credit model is
specified in [survey.yaml](survey-yaml.md#3-credit-creators-and-contributors), and what an access level
does to the bytes is specified in [Publication](../operations/publication.md#access-levels-and-embargoes).

## Normative artifact

| | |
|---|---|
| Normative artifact | `engine/schema/mtcat.schema.json`, JSON Schema draft-07 |
| Served locations | `/data/schemas/mtcat/2.0/mtcat.schema.json` (version-specific, immutable) and `/data/mtcat.schema.json` (latest convenience copy, beside the document) |
| `$id` | `https://ausmt.auscope.org.au/data/schemas/mtcat/2.0/mtcat.schema.json` |
| Schema version | 2.0; the machine-readable source is the `MTCAT_VERSION` constant in `contract/generate.py`, which the schema `title` displays |
| Document version | declared per document in `portal.version` |
| Validated | the build validates its emitted `mtcat.json` against the shipped schema before publishing, and copies that schema byte for byte to both served locations |

Where this page and the schema disagree, the schema is right. Every field, type and controlled
vocabulary carries its own `description` in the schema, so the schema reads on its own and does not
depend on this page.

### The `$id` policy

The canonical identifier of each schema release is its VERSION-SPECIFIC URL under
`/data/schemas/mtcat/<MAJOR.MINOR>/`. That artifact is immutable: once released, the bytes at that URL
never change, so a consumer that pins the `$id` validates against the same schema forever. The
unversioned `/data/mtcat.schema.json` is the latest-convenience route: it always resolves to the
current release, it is what `portal.schema_url` names, and it is served beside the document so a second
implementation can validate without resolving the canonical host at all. Earlier releases carried an
unversioned `$id` (and, before 2026-08-18, the `ausmt.au` host, which still resolves through a
permanent redirect); the versioned policy starts at 2.0.

### Portal identity

`portal.portal_id` is the stable, opaque identity token of the producing catalogue. It never changes
across rebuilds, host migrations or re-branding, which is what lets a federation form global keys by
pairing it with a record id: `(portal_id, survey_id)` and `(portal_id, station_id)` are stable claims.
`portal_name` is presentational and may change freely. A portal that forks or splits must mint a new
`portal_id`; a portal that merely moves hosts must not.

## Document structure

| Key | Obligation | Type | Contents |
|---|---|---|---|
| `portal` | mandatory | object | identity of the producing portal |
| `surveys` | mandatory | array of object | the discovery records |
| `stations` | mandatory | array of object | site-level discovery records |
| `collections` | optional | array of object | roll-up groupings over surveys; present only when at least one exists |

Unknown keys ride through. `additionalProperties` is true on every record object, so a consumer written
for one minor version reads a later one unchanged. The single exception is `surveys[].data_types`, which
is a map rather than a record: there `propertyNames` pins the key names, because an unexpected key is an
unknown band and not a local extension.

ABSENCE IS THE 2.0 DEFAULT STATE for everything optional. A key the producer cannot honestly state is
OMITTED, never emitted as `null` and never as an empty array or object. The one defined null is the
paired `stations[].latitude`/`longitude`, which means the position is not published. Consumers should
treat a missing key as "no assertion", not as an empty or negative one.

All coordinates are WGS 84 (EPSG:4326) decimal degrees.

---

## 1 portal

The portal object identifies the catalogue source.

```json
{
  "portal_id": "ausmt",
  "portal_name": "AusMT",
  "schema": "mtcat",
  "version": "2.0",
  "schema_url": "mtcat.schema.json",
  "metadata_license": "CC0-1.0",
  "generated_at": "2026-08-21T08:29:39Z"
}
```

### 1.1 portal.portal_id

| | |
|---|---|
| Definition | Stable opaque identity token of the portal that produced this document; see [Portal identity](#portal-identity). |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Example | `"ausmt"` |

### 1.2 portal.portal_name

| | |
|---|---|
| Definition | Display name of the portal that produced this document; presentational. |
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
| Example | `"2.0"` |
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
| Type | string |
| Example | `"CC0-1.0"` |
| Note | This covers the catalogue metadata only. A survey's data licence is [2.6 surveys[].license](#26-surveyslicense) and varies by survey. Conflating the two republishes restricted data under CC0. |

### 1.7 portal.generated_at

| | |
|---|---|
| Definition | UTC build timestamp of this document. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, ISO 8601 date-time with a `Z` suffix |
| Example | `"2026-08-21T08:29:39Z"` |

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
  "description": "Long-period magnetotelluric survey across the Musgraves and APY lands.",
  "subjects": [{"code": "370602", "scheme": "ANZSRC-FoR-2020"}],
  "formats": ["edi", "edi-zip", "emtfxml", "mth5", "xml-zip"]
}
```

### 2.1 surveys[].survey_id

| | |
|---|---|
| Definition | The survey's stable discovery identifier within the producing catalogue: the slug, and the key every other document joins a survey on. Document-unique, stable across rebuilds, never reused for a different survey. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Format | lowercase, hyphen separated, matching `^[a-z0-9]+(-[a-z0-9]+)*$` |
| Example | `"vulcan-2022"` |

### 2.2 surveys[].title

| | |
|---|---|
| Definition | Human-readable survey dataset title. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"Vulcan 2022"` |

### 2.3 surveys[].organisation

| | |
|---|---|
| Definition | Organisation with primary custodial responsibility for the represented dataset. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"University of Adelaide"` |

### 2.4 surveys[].country

| | |
|---|---|
| Definition | Country of the holdings. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"Australia"` |

### 2.5 surveys[].doi

| | |
|---|---|
| Definition | Persistent DOI of the exact dataset or release this record represents, bare form. Never a containing collection, report or activity identifier. |
| Obligation | optional; omitted when none is declared |
| Occurrence | 0-1 |
| Type | string |
| Example | `"10.25914/example"` |
| Note | AusMT mints no DOIs. Identifiers pointing at records AusMT does not own are carried in [2.21 surveys[].related_identifiers](#221-surveysrelated_identifiers). |

### 2.6 surveys[].license

| | |
|---|---|
| Definition | Licence the survey data is released under. |
| Obligation | recommended; omitted when undeclared |
| Occurrence | 0-1 |
| Type | string |
| Example | `"CC-BY-4.0"` |

### 2.7 surveys[].access

| | |
|---|---|
| Definition | Normalised access level of this survey. |
| Obligation | recommended; omitted when undeclared |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | `open`, `metadata_only`, `embargoed` are the well-known values |
| Note | Deliberately not enum-pinned in the schema. The producer normalises but does not coerce an unrecognised level, and anything other than `open` withholds the bytes, so an unexpected token here means a withheld survey rather than a broken document. |

### 2.8 surveys[].embargo_until

| | |
|---|---|
| Definition | ISO date the declared embargo lapses. |
| Obligation | optional; present only when an end date is declared |
| Occurrence | 0-1 |
| Type | string |
| Format | `YYYY-MM-DD` |
| Example | `"2027-06-30"` |
| Note | Absence means no declared end date rather than not embargoed. A date that has passed publishes nothing by itself; a curator releases a survey by changing the level. |

### 2.9 surveys[].bbox

| | |
|---|---|
| Definition | Geographic footprint, derived from this survey's PUBLISHED station coordinates. |
| Obligation | recommended; omitted when the survey has no located station, and always omitted when `coordinates_state` is `withheld` |
| Occurrence | 0-1 |
| Type | object with required members `west`, `south`, `east`, `north`, each a number |
| Example | `{"west": 135.1, "south": -31.2, "east": 136.4, "north": -30.4}` |

### 2.10 surveys[].centroid

| | |
|---|---|
| Definition | Centre of the survey's bbox. |
| Obligation | recommended; omitted whenever bbox is |
| Occurrence | 0-1 |
| Type | object with required members `latitude`, `longitude`, each a number |
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
| Obligation | recommended; omitted for a survey with no stations |
| Occurrence | 0-1 |
| Type | object with at least one key, integer values with minimum 0 |
| Allowed values | keys drawn from `AMT`, `BBMT`, `LPMT`, `GDS`, `unknown` |
| Example | `{"BBMT": 62, "LPMT": 26}` |
| Note | Emitted in the canonical band order BBMT, LPMT, AMT, GDS. This is the one object in the document whose keys are pinned, because an unexpected key is an unknown band and not a local extension. |

### 2.13 surveys[].period_min_s

| | |
|---|---|
| Definition | Shortest period across the represented transfer functions, in seconds. |
| Obligation | recommended; omitted when no station reports a period range |
| Occurrence | 0-1 |
| Type | number greater than 0 |
| Example | `8.0` |

### 2.14 surveys[].period_max_s

| | |
|---|---|
| Definition | Longest period across the represented transfer functions, in seconds. |
| Obligation | recommended; omitted when no station reports a period range |
| Occurrence | 0-1 |
| Type | number greater than 0 |
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
| Definition | The distribution formats this catalogue currently serves for the survey, derived from the build's download manifest. |
| Obligation | recommended; emitted ONLY when at least one format is distributed |
| Occurrence | 0-1 |
| Type | array of string, unique, at least one entry |
| Allowed values | `edi`, `edi-zip`, `emtfxml`, `mth5`, `xml-zip` |
| Example | `["edi", "edi-zip", "emtfxml", "mth5", "xml-zip"]` |
| Note | There is NO empty-array state in 2.0. A withheld (embargoed or metadata-only) survey OMITS the key: the holdings exist and their formats are known, they are simply not distributed, and an empty list would falsely assert that no formats are known. A producer with no manifest to derive from also omits the key. Absence therefore makes no assertion; presence asserts current distribution. |

### 2.17 surveys[].year_start

| | |
|---|---|
| Definition | First year of acquisition the survey declares. |
| Obligation | recommended; omitted when the survey declares no date |
| Occurrence | 0-1 |
| Type | integer |
| Example | `2016` |
| Note | Passed through from the survey's declared date range, never inferred from file timestamps. |

### 2.18 surveys[].year_end

| | |
|---|---|
| Definition | Last year of acquisition the survey declares; equal to `year_start` for a single season. |
| Obligation | recommended; omitted when the survey declares no date |
| Occurrence | 0-1 |
| Type | integer |
| Example | `2018` |

### 2.19 surveys[].version

| | |
|---|---|
| Definition | Semantic version of the represented dataset release. |
| Obligation | recommended; omitted when undeclared |
| Occurrence | 0-1 |
| Type | string |
| Format | `MAJOR.MINOR.PATCH` |
| Example | `"1.0.0"` |
| Note | This is the survey package version, not the MTCAT schema version. |

### 2.20 surveys[].collection_id

| | |
|---|---|
| Definition | Id of the collection or programme this survey belongs to. |
| Obligation | optional; omitted when the survey belongs to none |
| Occurrence | 0-1 |
| Type | string |
| Example | `"auslamp"` |
| Note | Matches a [4.1 collections[].collection_id](#41-collectionscollection_id) in this document when the collection is published here. Grouping is an exact string match. |

### 2.21 surveys[].related_identifiers[]

| | |
|---|---|
| Definition | The survey's typed provenance links to related records, chiefly the upstream time-series holdings a transfer-function release derives from. |
| Obligation | optional; present only when the survey declares at least one |
| Occurrence | 0-n |
| Type | array of object, at least one entry when present |
| Example | `[{"identifier": "10.25914/bzd5-n780", "identifier_type": "DOI", "relation": "IsDerivedFrom", "identifies": "raw_packed", "custodian": "NCI", "resolution": "ok"}]` |
| Note | The vocabularies and the reading direction are set out under [related_identifiers records what a survey points at](#related_identifiers-records-what-a-survey-points-at) and in the [identifies appendix](#appendix-the-identifies-vocabulary). Rows carry no null-valued keys: an unknown member is omitted. |

Row members:

| Member | Obligation | Type | Allowed values |
|---|---|---|---|
| `identifier` | mandatory | string, at least one character | free text, bare form for DOIs |
| `identifier_type` | recommended | string | four identifier types, enum-pinned; omitted when undeclared |
| `relation` | recommended | string | nine DataCite relation types, enum-pinned; omitted when undeclared |
| `identifies` | recommended | string | seven data levels, enum-pinned; absent on legacy rows means level not stated |
| `custodian` | optional | string | free text, because the custodian may be any archive |
| `resolution` | optional | string | `ok`, `reserved`; absent means unknown |
| `scheme` | optional | string | for HasMetadata rows only: the metadata family at the target |

### 2.22 surveys[].organisation_ror

| | |
|---|---|
| Definition | ROR identifier of the custodian organisation. |
| Obligation | optional; omitted when undeclared |
| Occurrence | 0-1 |
| Type | string |
| Example | `"https://ror.org/00892tw58"` |

### 2.23 surveys[].raid

| | |
|---|---|
| Definition | Identifier of the related research activity, emitted only when exactly one activity is asserted. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Example | `"https://raid.org/10.12345/AB1234"` |
| Note | A survey with several related activities omits it and expresses them in richer linked metadata. An activity identifier is never the dataset identifier; see [2.5 surveys[].doi](#25-surveysdoi). |

### 2.24 surveys[].creators[]

| | |
|---|---|
| Definition | The citation authors of this release, as DataCite creators, in citation order. |
| Obligation | optional; present only when the survey declares creators, with at least one row |
| Occurrence | 0-n |
| Type | array of object |
| Example | `[{"name": "Family, Given", "name_type": "person", "orcid": "0000-0002-9738-7277"}]` |
| Note | Order is the citation author order and is preserved verbatim; see [Credit is two lists](#credit-is-two-lists-and-they-are-not-interchangeable). |

Row members:

| Member | Obligation | Type | Allowed values |
|---|---|---|---|
| `name` | mandatory | string, at least one character | free text, the creator as cited |
| `name_type` | recommended | string | `person`, `organisation` |
| `orcid` | optional | string | bare or full-URL ORCID iD, people only |
| `ror` | optional | string | ROR identifier, organisations only |

A row that declares no `orcid` or `ror` omits the key rather than serving a null.

### 2.25 surveys[].contributors[]

| | |
|---|---|
| Definition | Who did what on this release, as DataCite contributors, in the export form. |
| Obligation | recommended |
| Occurrence | 0-n |
| Type | array of object, at least one entry when present |
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

### 2.26 surveys[].attribution

| | |
|---|---|
| Definition | Rights declaration of this release: custodian of record, the required attribution statement, and the CC-BY changes declaration. |
| Obligation | optional; present only when the survey declares it |
| Occurrence | 0-1 |
| Type | object, open to further keys |

Members (each omitted when undeclared):

| Member | Type | Definition |
|---|---|---|
| `custodian` | string | rights holder of record, which may differ from the acquiring organisation |
| `custodian_ror` | string | ROR identifier of that custodian |
| `statement` | string | attribution statement to reproduce verbatim where the upstream licence prescribes wording |
| `changes_made` | boolean | whether this release changed the upstream material, per CC-BY 4.0 section 3(a) |
| `changes_summary` | string | plain-language summary of what changed |
| `declared_by` | string | who recorded the declaration |
| `declared_date` | string, ISO date | date the declaration was recorded, not a date of the data |

The 1.2 `sources[]` and `changes` survey blocks are GONE in 2.0: an upstream dataset link is a
`related_identifiers[]` row, the changes facts live inside `attribution`, and richer source rights
detail (statement, licence, retrieval date) belongs to the per-survey metadata document. See the
[migration guide](#migrating-from-mtcat-12-to-20).

### 2.27 surveys[].description

| | |
|---|---|
| Definition | Concise discovery blurb for the dataset this record represents; complements, never replaces, the source's own documentation. |
| Obligation | recommended; omitted when the survey yields no discovery text |
| Occurrence | 0-1 |
| Type | string |
| Example | `"Long-period magnetotelluric survey across the Musgraves and APY lands."` |
| Note | AusMT emits the survey's explicit `discovery_description` where curated, else the survey abstract when it is already within the 1200-character discovery budget. The engine NEVER truncates: an over-long abstract with no discovery text is a curation gap, not something the emitter edits. |

### 2.28 surveys[].subjects[]

| | |
|---|---|
| Definition | Thematic classification of the represented dataset for discovery and cross-catalogue mapping, as controlled concept rows. |
| Obligation | recommended; absent means no assertion |
| Occurrence | 0-n |
| Type | array of object, at least one entry when present |
| Example | `[{"code": "370602", "scheme": "ANZSRC-FoR-2020", "label": "Electrical and electromagnetic methods in geophysics", "uri": "https://linked.data.gov.au/def/anzsrc-for/2020/370602"}]` |
| Note | Passed through VERBATIM from survey curation. Scheme tokens are bound to scheme URIs in the [subject scheme registry](#appendix-subject-scheme-token-registry) so `code` + `scheme` pairs compare across producers. |

Row members:

| Member | Obligation | Type | Allowed values |
|---|---|---|---|
| `code` | mandatory | string, at least one character | the classification code within the named scheme |
| `scheme` | mandatory | string, at least one character | an explicit scheme token, preferably a registered one |
| `label` | optional | string | human-readable label of the concept |
| `uri` | optional | string | stable concept URI governed by the scheme's authority |

### 2.29 surveys[].sample_rates_hz[]

| | |
|---|---|
| Definition | Distinct acquisition sample rates known to be represented in the survey, in Hz: discrete modes, never an extent. |
| Obligation | optional; emitted ONLY where explicit acquisition metadata declares rates |
| Occurrence | 0-1 |
| Type | array of number, each greater than 0, unique, sorted ascending, at least one entry when present |
| Example | `[10, 150, 24000]` |
| Note | Taken only from explicit run metadata (mt_metadata-parsed run declarations; MTH5 run tables), canonicalised to 6 significant figures, deduplicated and sorted. NEVER inferred from instrument capability or period coverage. Absence means no explicit rate metadata was available, not that none exists. |

### 2.30 surveys[].coordinates_state

| | |
|---|---|
| Definition | How this survey's published coordinates relate to acquisition positions. |
| Obligation | optional; emitted only when the survey DECLARES a coordinate access policy; absence makes no assertion |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | `exact`, `generalised`, `withheld` |
| Example | `"exact"` |
| Note | Over mixed per-station states the aggregation is conservative: all exact means `exact`, all withheld means `withheld`, any other mixture means `generalised`. The STATE is public; the reason need not be. A `withheld` state forbids `bbox` and `centroid` (they would republish the withheld footprint), and every one of that survey's stations serves the paired null position. See [Coordinate access](../rationale/coordinate-access.md). |

### 2.31 surveys[].n_stations_time_series_verified

| | |
|---|---|
| Definition | Count of this survey's station records carrying `has_time_series` true: a count of VERIFIED EXISTENCE, stable across access transitions. |
| Obligation | optional; emitted where the count is positive, OMITTED where it is zero (a zero would assert verified non-existence for every station of the survey) |
| Occurrence | 0-1 |
| Type | integer, minimum 0 |
| Note | Derived mechanically as the count of `has_time_series` true rows, never independently asserted, and never subtracted from `n_stations` to infer absence. |

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
| Definition | Identifier of this published station record, unique within the document; the `ausmt_id` every other AusMT document carries. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Format | `au.<slug>.<station>[.<variant>]` (the variant suffix appears only when a survey serves two processings of one site) |
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
| Note | This is the position the custodian chose to publish, not necessarily the surveyed position. A position may be generalised to 0.1 degrees, and null is DEFINED: the position is not published (withheld under policy, or unlocated). Latitude and longitude are both numeric or both null; a half-null pair is invalid. See [Coordinate access](../rationale/coordinate-access.md). |

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

### 3.6 stations[].has_time_series

| | |
|---|---|
| Definition | Present with value `true` when the producing catalogue has positively VERIFIED that a time-series resource for this station exists. Existence semantics: access is a separate question, and an embargo never flips it. |
| Obligation | optional; emitted where the producing catalogue holds a verified record of the resource, absent otherwise |
| Occurrence | 0-1 |
| Type | the constant `true` |
| Note | TRUE-OR-ABSENT: `false` is never emitted, and absence makes no assertion. A consumer must never read absence as verified non-existence. |

### Station detail is a portal convention, not an MTCAT field

AusMT serves a per-station detail document at the deterministic URL
`/data/products/<survey_id>/<station>/station.json`, where `<station>` is the station segment of the
`station_id`. Nothing about that layout is emitted in `mtcat.json`: it is an AusMT PORTAL CONVENTION,
documented here and stable, not part of the interchange schema. A federating consumer that wants
station detail from another portal should not assume the same layout exists there.

---

## 4 collections[]

Collections group related surveys for discovery and navigation. They are roll-ups: a collection holds no
transfer functions of its own, and all scientific provenance stays with its member surveys. The
`collections` key is present only when at least one collection exists.

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
| Obligation | recommended; omitted when undeclared |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | `programme`, `release`, `institutional`, `other` |
| Example | `"programme"` |

### 4.4 collections[].status

| | |
|---|---|
| Definition | Lifecycle state of the programme. |
| Obligation | recommended; omitted when undeclared or unrecognised |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | `active`, `completed`, `archived` are the well-known values |
| Example | `"active"` |
| Note | Not enum-pinned in the schema, because the producer already reduces an unrecognised value to absence and warns. |

### 4.5 collections[].start_year

| | |
|---|---|
| Definition | Year the programme began, as declared by its member surveys. |
| Obligation | optional; omitted when no member survey declares one |
| Occurrence | 0-1 |
| Type | integer |
| Example | `2013` |

### 4.6 collections[].last_updated

| | |
|---|---|
| Definition | ISO date the programme record was last updated. |
| Obligation | optional; omitted when undeclared |
| Occurrence | 0-1 |
| Type | string |
| Format | `YYYY-MM-DD` |
| Example | `"2026-07-12"` |
| Note | A curation date for the programme description. It is not the acquisition date of any survey and not the document's `generated_at`. |

### 4.7 collections[].description

| | |
|---|---|
| Definition | Prose description of the programme, as declared by its member surveys. |
| Obligation | optional; omitted when undeclared |
| Occurrence | 0-1 |
| Type | string |

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
| Obligation | recommended; omitted when no member station is located |
| Occurrence | 0-1 |
| Type | object, same shape as [2.9 surveys[].bbox](#29-surveysbbox) |

### 4.11 collections[].centroid

| | |
|---|---|
| Definition | Mean of the member station positions. |
| Obligation | recommended; omitted when no member station is located |
| Occurrence | 0-1 |
| Type | object with required members `latitude`, `longitude` |
| Note | A collection centroid is the mean of its member station positions. A [survey centroid](#210-surveyscentroid) is the centre of its bbox. |

---

## Appendix: the identifies vocabulary

`related_identifiers[].identifies` states what an identifier points at, in data-level terms. The
vocabulary is enumerated here normatively (it mirrors the levels of the NCI data hierarchy):

| Token | What the identifier points at |
| --- | --- |
| `collection` | the parent collection record |
| `raw_packed` | raw or packed time series |
| `level0` | edited time series |
| `level1` | transformed time series |
| `level2` | processed frequency-domain data, EDI and transfer functions |
| `level3` | models |
| `entire` | one record covering all levels |

A legacy row that states no level omits the key: absence means level not stated, never a level of its
own.

## Appendix: subject scheme token registry

`subjects[].scheme` tokens are registered here, each bound to the scheme URI it stands for, so a
`code` + `scheme` pair compares across producers. Producers MUST use the registered token where one
exists; unknown tokens remain valid documents under forward tolerance and simply do not compare.

| Token | Scheme | Scheme URI |
| --- | --- | --- |
| `ANZSRC-FoR-2020` | Australian and New Zealand Standard Research Classification, Fields of Research, 2020 revision | `https://linked.data.gov.au/def/anzsrc-for/2020` |

The AusMT curation default row is code `370602` in that scheme (Electrical and electromagnetic methods
in geophysics), with the concept URI
`https://linked.data.gov.au/def/anzsrc-for/2020/370602`.

---

## Migrating from MTCAT 1.2 to 2.0

MTCAT 2.0 is a MAJOR version: a valid 1.2 document does NOT validate against the 2.0 schema. The break
was chosen deliberately (correctness over compatibility while the consumer ecosystem is small), and it
is entirely mechanical. The reference transform, `migrate_12_to_20()`, ships in the engine's invariant
suite and is the normative statement of the change; this section describes it.

The breaking list:

1. NULL-AS-UNDECLARED IS REMOVED. 1.2 served `null` for every optional key a survey did not declare
   (`doi`, `license`, `raid`, `organisation_ror`, `version`, `collection_id`, `bbox`, `centroid`,
   `period_min_s`, `period_max_s`, `year_start`, `year_end`, and the members of relationship rows).
   2.0 OMITS such keys. The ONE defined null that remains is the paired
   `stations[].latitude`/`longitude`, meaning the position is not published.
2. THE EMPTY-ARRAY STATE FOR `formats` IS REMOVED (`minItems` 1). 1.2 served `formats: []` for a
   withheld survey; 2.0 omits the key, because the holdings and their formats are KNOWN, merely not
   distributed, and an empty list read as "no formats known" was a false assertion. Empty containers
   are gone document-wide: no emitted key is ever `[]` or `{}`, and `collections` is present only when
   at least one collection exists.
3. `surveys[].sources[]` AND `surveys[].changes` ARE REMOVED. A sources row maps to a
   `related_identifiers[]` row (`identifier`, `identifier_type`, `relation`, `identifies`,
   `custodian`); the changes facts already live in `attribution.changes_made`/`changes_summary`.
   A sources row carrying `statement`/`licence`/`retrieved`/`profile` content cannot be migrated
   mechanically: that rights detail moves to the per-survey metadata document, and the transform
   refuses (hard stop) rather than deleting it silently.
4. THE TOP-LEVEL `mt_metadata_version`/`mth5_version` KEYS ARE REMOVED. They were legacy 1.x
   additions; the catalogue no longer publishes tool versions.

The additions (all optional, none breaking): `surveys[].description`, `surveys[].subjects[]`,
`surveys[].sample_rates_hz[]`, `surveys[].coordinates_state`, and the
`stations[].has_time_series` / `surveys[].n_stations_time_series_verified` pair. The
`related_identifiers[].relation` vocabulary widened to nine values: `References`,
`IsIdenticalTo` and `HasMetadata` join the six 1.2 values (HasMetadata rows may carry a `scheme`
member naming the metadata family at the target); AusMT emits no HasMetadata row yet because no
genuine metadata target exists until the per-survey metadata document lands.

For a consumer, the practical migration is: stop special-casing nulls and empty arrays (test for key
PRESENCE instead), stop reading the top-level library versions, and read upstream-source links from
`related_identifiers` rather than `sources`. The additive rule re-arms for 2.x: later minor versions
add optional fields only.

---

## Extensibility and compatibility

The schema permits additional properties, so a portal can carry local fields without breaking
interoperability. Local fields must never be required for basic discovery.

Minor schema updates add optional fields, or type fields a producer was already serving through
`additionalProperties`. Both are backward compatible: a document that validated against an earlier minor
version still validates. Major updates may introduce incompatible changes, are versioned accordingly,
and ship with a migration guide, as [above](#migrating-from-mtcat-12-to-20).

Every field described here is typed, and where a value comes from a ratified vocabulary that vocabulary
is enum-pinned in the schema, so an out-of-vocabulary token fails the build rather than reaching a
consumer. Two fields are deliberately not pinned, [2.7 surveys[].access](#27-surveysaccess) and
[4.4 collections[].status](#44-collectionsstatus), because the producer passes an unrecognised value
through and withholds rather than failing the build.

---

## Reading a served survey record

This section is the consumer guide to the field meanings that a type alone cannot carry: which orders
matter, how a vocabulary should be read, what an absent key means, and which key joins to which. It
describes MTCAT v2.0. The document is served at [`/data/mtcat.json`](../interoperability/api-reference.md)
with the schema beside it at `/data/mtcat.schema.json` (and immutably at
`/data/schemas/mtcat/2.0/mtcat.schema.json`), so a second implementation can validate without
resolving anything off-site.

### Absence means no assertion

2.0 removed null-as-undeclared: an optional key the producer cannot honestly state is simply not
there. Test for key presence, never for `null`, and never read absence as a negative claim. The one
defined null is the paired station `latitude`/`longitude`, which means the position is not published.
The same rule covers containers: there are no empty arrays or objects anywhere in a served document,
so a missing `formats` or `subjects` key means "no assertion", not "none".

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
`URL`, `RAiD`), a DataCite relation to be read as "this survey *relation* that record", and
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

The relation vocabulary is fail-closed at nine values (the eight provenance relations plus
HasMetadata, whose rows also carry a scheme member naming the metadata family at the target); a row
whose relation is undeclared omits the key. `resolution` states whether the identifier resolves, from
a cached check the build consumes but never performs. `ok` means it resolves today, `reserved` means
registered but not yet active. The key is ABSENT when the answer is unknown, and absent never means
broken, so still link an identifier that carries no `resolution`.

### Access and embargo withhold bytes, never discovery

`access` is the normalised level: `open`, `metadata_only` or `embargoed`. Only `open` distributes data.
Anything else, including a level AusMT does not recognise, fails closed.

An embargoed survey keeps its full catalogue record, its stations and its footprint, and only its bytes
are withheld, so it OMITS the `formats` key (its holdings and their formats are known, merely not
distributed) and has no rows in the download manifest.

`embargo_until` is present only when the survey declares an end date, so its absence means no declared
end date rather than "not embargoed". A date that has passed publishes nothing by itself. A curator
releases a survey by changing the level.

### Coordinates carry a declared disclosure state

Where a survey declares a coordinate access policy, `coordinates_state` states how its published
positions relate to the acquired ones: `exact`, `generalised` (aggregated conservatively: any mixture
of per-station states reads as generalised) or `withheld`. The state is public; the reason stays
private. A withheld survey serves the paired null position on every station and no
`bbox`/`centroid`. A survey with no declared policy omits the key, which makes no assertion either
way.

### Verified time series are true-or-absent

`stations[].has_time_series` appears with the constant value `true` only when the catalogue has
positively verified that a time-series resource EXISTS for the station; access is a separate question.
`false` is never emitted, and absence makes no assertion, so never read a missing key as verified
non-existence. `surveys[].n_stations_time_series_verified` is the mechanical count of the true rows,
omitted where that count is zero.

AusMT populates both from a per-survey register of archive holdings that a curator maintains and an
out-of-band crawl feeds. EXISTENCE is the whole of what they claim: the flag follows that register for
every station, an embargoed one included, because an embargo says who may fetch the recording and not
whether it was made, and an outage at the archive is not a retraction either. The one lawful way the
flag goes down is curation, when the last verified row for a station is retired with its dated reason
because the resource genuinely ceased to exist. Whether AusMT can hand you a route to the file is a
DIFFERENT question, answered on the station record rather than here.

### One survey, two key names

MTCAT keys a survey by `survey_id`, which is the slug (`vulcan-2022` and the like). The download
manifest names surveys by display name in `files[].survey` but by slug in `bundles[].slug`. The
portal-internal `/data/surveys.json` (no contract, documented under Developer) is keyed by the survey's
display NAME and carries that same slug under `slug`.

Below the survey, the stable join is the station. `ausmt_id` is the one identifier the station record
and the manifest row both carry.
