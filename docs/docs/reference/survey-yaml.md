# survey.yaml reference

`survey.yaml` is the survey-level metadata document inside a survey package. Every package contains
exactly one, and it is the single source of survey metadata for the whole system: the validator checks
it, the engine reads it to build the portal's data files and the MTCAT discovery document, and the
portal renders it. No survey metadata is hard-coded anywhere else.

## Normative artifact

| | |
|---|---|
| Normative artifact | the survey validator, `validate_survey.py`, in the survey repository's `_validation/` directory |
| Public copy | [`gateway/tests/fixtures/vendored_validation/validate_survey.py`](https://github.com/bvkay/ausmt/blob/main/gateway/tests/fixtures/vendored_validation/validate_survey.py), pinned and kept in step |
| Worked examples | `ausmt-surveys/_template/survey.yaml` and `ausmt-surveys/_example/` |
| Document version | declared per document in `schema_version` |
| Enforced at | submission, and again at the publication gate with `--strict` |

There is no JSON Schema artifact for `survey.yaml`. The validator is the definition. Where this page and
the validator disagree, the validator is right.

## Outcomes

The validator returns one of three outcomes per package.

| Outcome | Meaning |
|---|---|
| `PASS` | every required check is satisfied |
| `WARNING` | the package is valid, but something should be looked at |
| `FAIL` | publication is blocked until it is corrected |

`--strict`, which the publication gate uses, escalates every warning to a failure. Field entries below
state the obligation as the validator applies it: `mandatory` means a missing or placeholder value is a
`FAIL`, `recommended` means its absence is a `WARNING` or a poorer published record, `optional` means
absence is silent.

## Document structure

| Key | Obligation | Type | Section |
|---|---|---|---|
| `schema_version` | recommended | string | [1 Identity](#1-identity) |
| `slug` | mandatory | string | [1 Identity](#1-identity) |
| `project_name` (or `name`) | mandatory | string | [1 Identity](#1-identity) |
| `version` | recommended | string | [1 Identity](#1-identity) |
| `country` | mandatory | string | [1 Identity](#1-identity) |
| `region` | optional | string | [1 Identity](#1-identity) |
| `organisation` | mandatory | mapping or string | [2 Organisation](#2-organisation) |
| `creators` | optional | list of mapping | [3 Credit](#3-credit-creators-and-contributors) |
| `contributors` | optional | list of mapping | [3 Credit](#3-credit-creators-and-contributors) |
| `abstract` | recommended | string | [4 Description and extent](#4-description-and-extent) |
| `geographic_extent` | recommended | mapping | [4 Description and extent](#4-description-and-extent) |
| `data_types` (or `data_type`) | recommended | list or string | [4 Description and extent](#4-description-and-extent) |
| `identifiers` | optional | mapping | [5 Identifiers](#5-identifiers) |
| `related_identifiers` | optional | list of mapping | [6 Identifiers by data level](#6-identifiers-by-data-level) |
| `funding` | optional | list of mapping | [7 Funding and publications](#7-funding-and-publications) |
| `publications` | optional | list | [7 Funding and publications](#7-funding-and-publications) |
| `license` | mandatory | string | [8 Licence and access](#8-licence-and-access) |
| `access` | mandatory | mapping | [8 Licence and access](#8-licence-and-access) |
| `attribution` | optional | mapping | [9 Attribution](#9-attribution) |
| `time_series` | optional | mapping | [10 Time series and distribution](#10-time-series-and-distribution) |
| `nci_base` | optional | string | [10 Time series and distribution](#10-time-series-and-distribution) |
| `processing` | recommended | mapping | [11 Processing and instruments](#11-processing-and-instruments) |
| `instruments` | optional | list of mapping | [11 Processing and instruments](#11-processing-and-instruments) |
| `collection` | optional | mapping | [12 Collection membership](#12-collection-membership) |
| `release_notes` | recommended | list of mapping | [13 Release notes](#13-release-notes) |
| `coordinate_resolution` | optional | mapping | [14 Coordinate resolution](#14-coordinate-resolution) |
| `care` | optional | mapping | [15 CARE](#15-care) |

A key the validator does not model warns as unknown but is carried through the curator editor's
round-trip verbatim, so hand-edited YAML is never silently dropped.

## Worked document

```yaml
schema_version: "0.2"                 # "0.2" or "0.3" (0.3 adds the attribution block)

slug: my-survey-2026                  # REQUIRED, must equal the folder name
project_name: "Survey Name (Org)"     # REQUIRED, human-readable name
version: "1.0.0"                      # survey-package semver, not the schema version
country: Australia                    # REQUIRED
region: "South Australia"             # optional, a finer geographic facet than country

organisation:                         # REQUIRED (.name). A bare string also works.
  name: "University of Example"
  ror: null

creators:                             # optional, ORDERED: who the citation names, in author order
  - name: "Family, Given"
    name_type: person
    orcid: null

contributors:                         # optional, repeatable: who did what
  - name: "Family, Given"
    name_type: person
    role: ProjectLeader
    orcid: null

abstract: >
  Free text describing the survey.

geographic_extent: { west: 0.0, east: 0.0, south: 0.0, north: 0.0, datum: WGS84 }

data_types: [BBMT]                    # all that apply: AMT | BBMT | LPMT | GDS

identifiers:
  survey_pid: null
  instrument_pid: null
  project_raid: null

related_identifiers:
  - identifier: "10.25914/…"
    identifier_type: DOI
    identifies: raw_packed
    custodian: "NCI"

funding:
  - organisation: "Funding body"
    organisation_ror: null
    grant_id: null
    grant_title: null
    funding_doi: null

license: "CC-BY-4.0"                  # REQUIRED
access:                               # REQUIRED (.level)
  level: open
  embargo_until: null
  contact: null
  coordinates: exact
  coordinate_overrides: {}

attribution:                          # optional, schema 0.3 only
  custodian: "Custodian of record"
  custodian_ror: null
  statement: null
  changes_made: true
  changes_summary: null
  declared_by: null
  declared_date: null

time_series:
  levels_available: []

nci_base: null

publications: []

processing:
  software: "BIRRP / Aurora / EMTF / LEMI MT / Phoenix EMpower"
  version: null
  remote_reference: "unknown"
  notes: null

instruments:
  - manufacturer: "Phoenix"
    model: "MTU-5C"

collection:
  id: auslamp
  title: AusLAMP
  type: programme
  status: completed
  start_year: 2013
  last_updated: "2026-01-01"
  description: >-
    One paragraph shown on the collection card and page.

release_notes:
  - { version: "1.0.0", date: "2026-01-01", note: "Initial AusMT publication." }

coordinate_resolution:
  dms_sign: info
  basis: "INFO decimal matches field GPS; HEAD latitude is floored DMS"

care:
  traditional_owner_acknowledgement: null
  land_access: { permission_obtained: unknown, agreement_type: null }
  restrictions_requested: false
```

---

## 1 Identity

### 1.1 schema_version

| | |
|---|---|
| Definition | Which AusMT survey schema this document is written to. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | `"0.2"` the structured form; `"0.3"` adds the [attribution](#9-attribution) block |
| Example | `"0.2"` |
| Note | Any other value warns. Use `"0.2"` unless you set an attribution block, and bump to `"0.3"` when you fill any of its keys. Setting attribution while declaring `"0.2"` warns. |

### 1.2 slug

| | |
|---|---|
| Definition | The survey's permanent identifier and the root of every station id. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Format | `^[a-z0-9]+(-[a-z0-9]+)*$`, and it must equal the package folder name |
| Example | `my-survey-2026` |
| Note | It becomes `au.<slug>.<station>` in every id, URL, export and product path. A mismatch with the folder name, or a character outside the set, is a `FAIL`: either would fork the survey's identity downstream. |

### 1.3 project_name

| | |
|---|---|
| Definition | Human-readable survey name, and the key `surveys.json` is indexed by. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"Vulcan 2022"` |
| Note | `name` is an accepted alias. Either key satisfies the check. |

### 1.4 version

| | |
|---|---|
| Definition | Semantic version of the survey package. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |
| Format | `MAJOR.MINOR.PATCH` |
| Example | `"1.0.0"` |
| Note | Not the schema version. A missing or badly shaped value warns. The gateway enforces a monotonic bump on every published edit; the meaning of each level is in [Versioning and releases](../data-model/versioning.md). |

### 1.5 country

| | |
|---|---|
| Definition | Country the survey was acquired in. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `Australia` |
| Note | Drives the Country, Organisation, Survey discovery hierarchy. |

### 1.6 region

| | |
|---|---|
| Definition | A finer geographic facet than country. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Example | `"South Australia"` |
| Note | Falls back to `country`, then to `"?"`, in the catalogue's region column. |

---

## 2 Organisation

### 2.1 organisation.name

| | |
|---|---|
| Definition | Custodian organisation of the survey. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"University of Example"` |
| Note | A bare string in place of the mapping is accepted and read as the name. |

### 2.2 organisation.ror

| | |
|---|---|
| Definition | ROR identifier of the custodian organisation. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `https://ror.org/00892tw58` |
| Note | Format-checked as a warning only. No registry lookup is performed. |

---

## 3 Credit: creators and contributors

Two lists carry credit, and they answer different questions. The reasoning is in
[Why the credit model has two lists](../rationale/credit-model.md).

### 3.1 creators

| | |
|---|---|
| Definition | Who the citation names, in author order. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | list of mapping |
| Example | `- name: "Family, Given"` with `name_type: person` |
| Note | An ordered editorial list. The order is the author order used by the APA, BibTeX and RIS exports and by the attribution line written into the canonical EMTF XML. Omit the block and the citation falls back to an organisation-and-year synthesis, which is the right answer for most state-survey data. |

### 3.2 contributors

| | |
|---|---|
| Definition | Who did what, one row per role played. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | list of mapping |
| Example | `- name: "Geological Survey of Example"` with `name_type: organisation` and `role: Distributor` |
| Note | Repeatable and unordered. The same party can appear in several rows. This is where the release chain is recorded: a state survey that released the data is a `Distributor`, a mining company that paid for it is a `Sponsor`, a company that held it through an embargo is a `RightsHolder`, and a field contractor is usually an organisation acting as `DataCollector`. |

### 3.3 The shared row shape

| Key | Applies to | Obligation | Type | Allowed values |
|---|---|---|---|---|
| `name` | both | recommended | string | free text, the name as it should be shown |
| `name_type` | both | recommended | string | `person`, `organisation` |
| `role` | contributors | recommended | string | the eight roles below |
| `orcid` | people | optional | string | ORCID iD, format and checksum checked as a warning |
| `ror` | organisations | optional | string | ROR identifier, format-checked as a warning |

The role vocabulary is the DataCite `contributorType` subset ratified for Australian release chains, in
the order the curator editor presents it:

`ProjectLeader`, `ProjectMember`, `DataCollector`, `ContactPerson`, `DataCurator`, `Sponsor`,
`RightsHolder`, `Distributor`.

The validator is fail-closed on the values and warns on the structure. An out-of-vocabulary `name_type`
or `role` is a `FAIL`, because getting one wrong publishes a false statement about who did what. A
missing `name`, `name_type` or `role`, a row that is not a mapping, and an unknown key inside a row all
warn, and `--strict` turns each of those into a failure at the publication gate.

`HostingInstitution` is a ninth DataCite type. It is appended by the export for the hosting portal and is
not a value a survey declares for itself.

---

## 4 Description and extent

### 4.1 abstract

| | |
|---|---|
| Definition | One short paragraph describing the survey. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |

### 4.2 geographic_extent

| | |
|---|---|
| Definition | The curator-declared footprint of the survey. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | mapping with members `west`, `east`, `south`, `north` (number) and `datum` (string) |
| Example | `{ west: 128.9, east: 133.6, south: -27.1, north: -25.8, datum: WGS84 }` |
| Note | This is where a survey's published position comes from when its station coordinates are withheld. A survey with withheld coordinates and no declared extent shows no position at all. |

### 4.3 data_types

| | |
|---|---|
| Definition | Every acquisition band present in the survey. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | list of string |
| Allowed values | `AMT`, `BBMT`, `LPMT`, `GDS` |
| Example | `[BBMT]` |
| Note | `data_type`, a single string, is the accepted alias. The per-station band served in the catalogue and in MTCAT is derived from the transfer function itself, not from this declaration. |

---

## 5 Identifiers

`identifiers` holds the persistent identifiers AusMT records about the survey itself. Identifiers that
point at records AusMT does not own belong in [related_identifiers](#6-identifiers-by-data-level).

### 5.1 identifiers.survey_pid

| | |
|---|---|
| Definition | AuScope Instrument Registry survey handle. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |

### 5.2 identifiers.instrument_pid

| | |
|---|---|
| Definition | The one survey-level or platform-level persistent identifier for the instrument system. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Format | an `https://` URL or a bare handle or DOI |
| Example | `https://instruments.auscope.org.au/system/LEMI-423-007` |
| Note | The portal renders it as a link in the survey drawer through the same URL-shape guard as the other PID links, so a malformed value renders inert. Format-checked as a warning only, with no registry lookup, matching the ROR and RAiD checks. |

### 5.3 identifiers.project_raid

| | |
|---|---|
| Definition | RAiD (Research Activity Identifier) for the project. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Example | `https://raid.org/10.12345/AB1234` |

---

## 6 Identifiers by data level

`related_identifiers[]` is the one place dataset-level DOIs, handles and URLs are recorded. Each row is a
typed pointer to a record AusMT does not own. The reasoning is in
[Why identifiers carry a data level](../rationale/identifiers-by-level.md).

### 6.1 related_identifiers[].identifier

| | |
|---|---|
| Definition | The identifier itself. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |
| Example | `"10.25914/bzd5-n780"` |
| Note | A row without an identifier, or without an in-vocabulary `relation`, does not count as a typed provenance claim. An unrecognised key anywhere in the row warns. |

### 6.2 related_identifiers[].identifier_type

| | |
|---|---|
| Definition | What kind of identifier the row carries. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | `DOI`, `Handle`, `URL`, `RAiD` |
| Example | `DOI` |
| Note | Fail-closed. A state-survey landing page with no DOI belongs here as a `URL` row with `identifies: entire`. |

### 6.3 related_identifiers[].identifies

| | |
|---|---|
| Definition | What the identifier points at, using the NCI Table 1 data-level terms. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | see the table below |
| Example | `raw_packed` |
| Note | Fail-closed. Absence means the level was not stated, not that no level applies. |

| `identifies` | What it means | Derived relation |
|---|---|---|
| `collection` | the parent record, for example an NCI parent collection | `IsPartOf` |
| `raw_packed` | raw or packed time series | `IsDerivedFrom` |
| `level0` | edited time series | `IsDerivedFrom` |
| `level1` | transformed time series | `IsDerivedFrom` |
| `level2` | derived frequency-domain processed data, EDI and transfer functions | `IsVariantFormOf` |
| `level3` | models | `IsSourceOf` |
| `entire` | one record covering all levels, such as a GA eCAT record or a state landing page | `IsVariantFormOf` |

### 6.4 related_identifiers[].relation

| | |
|---|---|
| Definition | The DataCite relation type, read as "this survey *relation* that record". |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Default | derived from `identifies` per the table above |
| Note | Curators state the level and the relation follows. A hand-edited file may still set the relation explicitly; when both are present and disagree, the validator warns and the explicit value stands. |

### 6.5 related_identifiers[].custodian

| | |
|---|---|
| Definition | Who holds the identified record. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |
| Example | `"NCI"` |
| Note | Free text, because the custodian may be any archive. |

### 6.6 Acquisition keys

When the identifier is an upstream dataset AusMT obtained rather than merely relates to, the row may
also carry these.

| Key | Type | Definition |
|---|---|---|
| `title` | string | title of the upstream dataset as obtained |
| `licence` | string | licence the dataset was obtained under. Note the spelling |
| `retrieved` | string | when it was obtained, at whatever precision is known |
| `statement` | string | attribution wording the source custodian prescribes |
| `profile` | string | which custodian attribution profile applies when composing the notice |

---

## 7 Funding and publications

### 7.1 funding[]

| | |
|---|---|
| Definition | Who funded the survey. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | list of mapping with members `organisation`, `organisation_ror`, `grant_id`, `grant_title`, `funding_doi` |
| Note | `funders` is the accepted flat alias. |

### 7.2 publications[]

| | |
|---|---|
| Definition | Publications that use or describe the survey. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | list of mapping with members `author`, `year`, `title`, `journal`, `doi` |
| Note | A bare DOI string per entry is also accepted. |

---

## 8 Licence and access

### 8.1 license

| | |
|---|---|
| Definition | The licence the survey data is released under. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | a recognised AusMT licence id, from the allow-list and its aliases |
| Example | `"CC-BY-4.0"` |
| Note | A missing licence is a `FAIL`. A `TBD` placeholder warns, and an unrecognised id warns; `--strict` turns either into a failure at the publication gate. Only a licence on the redistributable list lets AusMT serve the bytes; a recognised but non-redistributable licence publishes the survey as metadata with the download routed to the source archive. |

### 8.2 access.level

| | |
|---|---|
| Definition | Whether AusMT distributes this survey's bytes. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | `open`, `metadata_only`, `embargoed` |
| Example | `open` |
| Note | Out of enum is a `FAIL`. Only `open` distributes data; anything else warns at validation and withholds at build. |

### 8.3 access.embargo_until

| | |
|---|---|
| Definition | The date the declared embargo lapses. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Format | `YYYY-MM-DD` |
| Note | A malformed date is a `FAIL`. A date in the past under `level: embargoed` warns and changes nothing: the survey stays withheld until a curator sets the level to `open`. An embargo is never lifted automatically. |

### 8.4 access.contact

| | |
|---|---|
| Definition | Who to approach about access to a withheld survey. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |

### 8.5 access.coordinates

| | |
|---|---|
| Definition | The survey-level policy for how station coordinates are served. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | `exact` serves the true position; `generalised` rounds latitude and longitude to 0.1 degrees, roughly 11 km; `withheld` serves no position |
| Default | `exact` when the key is absent |
| Note | Out of enum is a `FAIL` at validation and fails the build: a silent fallback would serve the exact position the curator asked to protect. A withheld station keeps its catalogue row and its response curves still serve; it simply has no coordinate, and the survey's position then comes from `geographic_extent`. A station whose coordinates are not exact is also excluded from byte distribution, because an EDI header carries the true position. The reasoning is in [Why coordinates have an access policy](../rationale/coordinate-access.md). |

### 8.6 access.coordinate_overrides

| | |
|---|---|
| Definition | Per-station coordinate policy, overriding the survey default. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | mapping of station id to policy |
| Allowed values | values from the `access.coordinates` vocabulary |
| Example | `{ SA045: withheld }` |
| Note | The key is the physical station id, so an override covers every processing variant of that site. The engine validates the keys against the real parsed station ids before it emits any of the survey's bytes, and an id that matches nothing fails the survey build. |

---

## 9 Attribution

The `attribution` block records the rights of this AusMT release and is a schema 0.3 field. Its keys are
a frozen allow-list; an unknown key warns.

| Key | Obligation | Type | Definition |
|---|---|---|---|
| `custodian` | recommended | string | rights holder of record, which may differ from `organisation.name` |
| `custodian_ror` | optional | string | ROR identifier of that custodian |
| `statement` | optional | string | verbatim wording where the custodian prescribes one |
| `changes_made` | recommended | boolean | the CC-BY 4.0 section 3(a) flag |
| `changes_summary` | optional | string | plain-language summary of what changed |
| `declared_by` | optional | string | who recorded the declaration |
| `declared_date` | optional | string | ISO date the declaration was recorded |

Setting any of these while `schema_version` is `"0.2"` warns. Some custodian profiles make `statement`
mandatory: a source that mandates exact wording fails without it.

---

## 10 Time series and distribution

### 10.1 time_series.levels_available

| | |
|---|---|
| Definition | Which time-series data levels exist for this survey, upstream. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | list of string |
| Allowed values | `raw_packed`, `level0`, `level1` |
| Example | `[raw_packed, level0]` |
| Note | Pointers only. AusMT never hosts time series. The portal renders per-level availability from this list. |

### 10.2 nci_base

| | |
|---|---|
| Definition | One NCI THREDDS fileServer directory that the survey's transfer-function files already sit flat under. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string or null |
| Format | an absolute `http` or `https` URL to a directory |
| Note | Set it and the survey's downloads point at NCI instead of AusMT-served bytes. A value that is not an absolute http URL is a `FAIL`, and the engine drops it defensively as well, because a mistyped scheme or host would publish broken or unsafe download links. |

---

## 11 Processing and instruments

### 11.1 processing

| | |
|---|---|
| Definition | Technical provenance of the transfer functions. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | mapping |
| Note | `provenance: { processing_software }` is the accepted flat alias for `processing: { software }`. |

| Key | Type | Allowed values | Definition |
|---|---|---|---|
| `software` | string | free text | the processing code, for example `BIRRP`, `Aurora`, `EMTF`, `LEMI MT`, `Phoenix EMpower` |
| `version` | string | free text | version of that code |
| `remote_reference` | string | `yes`, `no`, `unknown` | whether remote reference processing was used |
| `notes` | string | free text | anything else worth recording |

### 11.2 instruments[]

| | |
|---|---|
| Definition | The instrument systems used. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | list of mapping with members `manufacturer` and `model` |
| Example | `- manufacturer: "Phoenix"` with `model: "MTU-5C"` |

`processing` is survey-wide: no key here records processing per station, and no key versions a station's
transfer function. A reprocessing is a MAJOR bump of the package, as
[Versioning and releases](../data-model/versioning.md#reprocessed-transfer-functions) sets out. What a
station's own source file states about its processing is read into its
[station product](station-products.md#19-processing).

---

## 12 Collection membership

`collection` declares programme membership, which MTCAT and `collections.json` roll up. Grouping is an
exact match on `id`, so every member survey must spell it identically. Naming rules are in
[Collection IDs](../developer/collection-ids.md).

| Key | Obligation | Type | Allowed values |
|---|---|---|---|
| `id` | required for the block to take effect | string | lowercase, hyphen separated. Anything else warns |
| `title` | recommended | string | free text |
| `type` | recommended | string | `programme`, `release`, `institutional`, `other` |
| `status` | recommended | string | `active`, `completed`, `archived`. Anything else warns and is served as null |
| `start_year` | optional | integer | |
| `last_updated` | optional | string | ISO date |
| `description` | optional | string | one paragraph, shown on the collection card and page |

---

## 13 Release notes

### 13.1 release_notes[]

| | |
|---|---|
| Definition | One entry per published version of the package. |
| Obligation | recommended |
| Occurrence | 0-n |
| Type | list of mapping with members `version`, `date`, `note` |
| Example | `- { version: "1.0.0", date: "2026-01-01", note: "Initial AusMT publication." }` |
| Note | An entry that is not shaped `{version, date, note}`, or that carries no `version`, warns. The portal renders the list in the survey drawer, and the latest entry's date feeds the recently-added feed. The gateway requires a note with every version bump it publishes. |

---

## 14 Coordinate resolution

### 14.1 coordinate_resolution

| | |
|---|---|
| Definition | Which coordinate source is ground truth when an EDI's `HEAD` and `INFO` blocks disagree. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | mapping with members `dms_sign` and `basis` |
| Allowed values | `dms_sign` is `info` or `head` |
| Example | `{ dms_sign: info, basis: "INFO decimal matches field GPS; HEAD latitude is floored DMS" }` |
| Note | Some processing tools write a corrupted DMS coordinate into the EDI `HEAD` block while the correct decimal value survives in `INFO`. It is a sign or floor bug, and it is common for negative latitudes. The build flags such stations `dms_sign_ambiguous` and keeps the EDI-standard `HEAD` value. Declaring `dms_sign: info` substitutes the `INFO` coordinate and records the resolution with its `basis`. With no declaration the coordinate stays at `HEAD` and stays flagged for review. This is a data-quality correction, not an access control; [access.coordinates](#85-accesscoordinates) is the access control. |

---

## 15 CARE

`care` records governance facts only, never sensitive detail.

| Key | Obligation | Type | Definition |
|---|---|---|---|
| `traditional_owner_acknowledgement` | optional | string | acknowledgement text where one applies |
| `land_access.permission_obtained` | optional | string | `yes`, `no`, `unknown` |
| `land_access.agreement_type` | optional | string | the kind of agreement, where one exists |
| `restrictions_requested` | optional | boolean | whether the custodian has asked for restrictions |

No automated check blocks publication on CARE grounds. A curator reviews the block; see
[Submission](../operations/submission.md#care-considerations).

---

## Retired keys

These keys are not offered by the curator metadata editor. Each raises a deprecation warning when it
carries a real value. Nine are listed below. Six are still read as fallbacks, so an un-migrated package
publishes as before: `lead_investigator`, `principal_investigators`, `identifiers.dataset_doi`,
`time_series.collection_pid`, `instruments[].pid` and `sources[]`. The other three,
`identifiers.related_publication`, `identifiers.related_publication_doi` and `identifiers.project`, are
read by nothing and are dropped. Migration scripts live in `ausmt-surveys/_tools/`.

| Retired key | Replaced by | Migration |
|---|---|---|
| `lead_investigator` | a `contributors[]` row with `role: ProjectLeader` | `migrate_credit.py` |
| `principal_investigators` | `creators[]` | `migrate_credit.py` |
| `identifiers.dataset_doi` | a `related_identifiers[]` row | `migrate_identifiers.py` |
| `time_series.collection_pid` | a `related_identifiers[]` row; NCI-custodian rows gain `identifies: raw_packed` | `migrate_identifiers.py` moves the value; `migrate_identifies.py` infers the level for NCI rows and lists any other custodian for curator fill-in |
| `identifiers.related_publication_doi` | `publications[]` | `migrate_identifiers.py` |
| `identifiers.related_publication` | nothing; free text, dropped by the script | `migrate_identifiers.py` |
| `identifiers.project` | nothing; read by nothing | `migrate_identifiers.py` |
| `instruments[].pid` | `identifiers.instrument_pid`, or a typed `related_identifiers[]` row | no script; a curator moves the value by hand |
| `sources[]` | a `related_identifiers[]` row with `identifies: entire` plus the [acquisition keys](#66-acquisition-keys) | `migrate_identifies.py` |

A value the curator editor does not model is carried through its round-trip verbatim, so hand-edited
YAML is never silently dropped.

## Flat key aliases

Both the validator and the engine read these flat spellings, so a package that uses them needs no
migration. New packages use the structured form.

| Structured | Flat |
|---|---|
| `project_name` | `name` |
| `organisation: { name, ror }` | `organisation: "Name"` |
| `data_types: [ … ]` | `data_type: …` |
| `funding: [ … ]` | `funders: [ … ]` |
| `processing: { software }` | `provenance: { processing_software }` |

## Relationship to the survey package

`survey.yaml` describes the package as a whole; it is the package's primary metadata record.
Station-level information (coordinates, deployment dates, sensor orientations) comes from the
transfer-function files themselves. See [Survey package](../data-model/survey-package.md).
