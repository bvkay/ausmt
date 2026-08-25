# Survey metadata

`survey-metadata.json` is the canonical public metadata record of one survey dataset/release: the
full credit, funding, subject, identifier, citation and rights detail that `mtcat.json` deliberately
keeps to a discovery minimum. One document is served per survey at
`/data/products/<survey_id>/survey-metadata.json`, for every survey the catalogue lists, including
embargoed and metadata-only surveys. It is generated from the survey's private `survey.yaml` (the
curation source of truth) and never invents a fact: every property is either copied from curation
or is document provenance.

The document describes the DATASET/RELEASE unless a property says otherwise. Research activities
(`activities[]`), source releases (`relationships[]`) and the AusMT representation (`attribution`)
are linked, never conflated with it. It carries no station list, no distribution facts (no formats,
no download paths) and no numeric science; stations are described by
[`station.json`](station-products.md#1-stationjson) and discovery by [MTCAT](mtcat-schema.md).

This page describes survey-metadata schema version 0.1, a draft: the document `version` literal is
`"0.1"`, the schema title displays `0.1-draft`, and the shape may gain properties before 1.0 but
every property described here is emitted as described.

## Normative artifact

| | |
|---|---|
| Normative artifact | `engine/schema/ausmt-survey-metadata.schema.json`, JSON Schema draft-07 |
| Served locations | `/data/schemas/ausmt-survey-metadata/0.1/ausmt-survey-metadata.schema.json` (version-specific, immutable) and `/data/ausmt-survey-metadata.schema.json` (latest convenience copy) |
| `$id` | `https://ausmt.auscope.org.au/data/schemas/ausmt-survey-metadata/0.1/ausmt-survey-metadata.schema.json` |
| Schema version | 0.1 (draft); the machine-readable source is the `SURVEY_METADATA_VERSION` constant in `contract/generate.py`, which the schema `title` displays |
| Document version | declared per document in `version` |
| Validated | the build validates every emitted document against the shipped schema with format checking on (dates, timestamps), refuses to publish a document that fails, and copies the schema byte for byte to both served locations; `scripts/verify.py` re-validates every document after the build and checks that the set of documents equals the set of catalogued surveys |

Where this page and the schema disagree, the schema is right. Every property carries its own
`description` in the schema.

### The `$id` policy

The canonical identifier of each schema release is its version-specific URL under
`/data/schemas/ausmt-survey-metadata/<MAJOR.MINOR>/`. That artifact is immutable once released.
The unversioned `/data/ausmt-survey-metadata.schema.json` is the latest-convenience route and
always resolves to the current release. This is the same policy MTCAT 2.0 adopted.

## Document structure

| Key | Obligation | Type | Describes |
|---|---|---|---|
| `schema` | mandatory | string, always `"ausmt-survey-metadata"` | the document |
| `version` | mandatory | string | the document (the schema version it conforms to) |
| `survey_id` | mandatory | string | the dataset, as the cross-layer join key |
| `title` | mandatory | string | the dataset |
| `dataset_version` | optional | string | the dataset/release (not emitted in 0.1, see [4](#4-dataset_version)) |
| `dates` | optional | object | the dataset (coverage) and the release (issued) |
| `identifiers` | optional | array of object | identifiers OF the dataset/release |
| `activities` | optional | array of object | related research activities |
| `abstract` | optional | string | the dataset |
| `subjects` | optional | array of object | the dataset |
| `creators` | optional | array of object | the dataset/release citation authors |
| `contributors` | optional | array of object | the dataset/release |
| `organisations` | optional | array of object | the dataset/release |
| `funders` | optional | array of object | the dataset/release |
| `citation` | optional | object | citation guidance over the identifier set |
| `acknowledgements` | optional | array of object | acknowledgement wording, per row |
| `rights` | optional in the schema, always emitted | object | the dataset |
| `extent` | optional | object | the dataset |
| `relationships` | optional | array of object | links from the dataset to other records |
| `attribution` | optional | object | the AusMT representation |
| `provenance` | optional in the schema, always emitted | object | the document |

Unknown keys ride through (`additionalProperties` is true on every object), so a consumer written
for one 0.x release reads a later one unchanged.

ABSENCE MEANS NO ASSERTION. A property whose curated value does not exist is omitted, never
emitted as `null` and never as an empty array or object. The document defines no null at all, and
the build and `verify.py` both refuse a document carrying one. A placeholder in curation (`TBD`,
`TODO`, an empty string, the template's replace marker) is treated as absent. Test for key
presence, and never read absence as a negative claim: a survey without `funders` is a survey
whose funding AusMT has not asserted, not an unfunded survey.

A survey that carries only the validator's required facts (`slug`, `name`, `country`,
`organisation.name`, `license`, `access.level`) emits exactly `schema`, `version`, `survey_id`,
`title`, `rights` and `provenance`. Nothing else is defaulted in.

### Embargoed and metadata-only surveys

The document is served for every catalogued survey whatever its access state, and the access
state withholds nothing in it. Discovery is universal in AusMT: an embargoed survey is listed in
`mtcat.json` with every curated class it has, and this document emits the same classes for it,
including identifiers, relationships, citation guidance, acknowledgements and the curated extent.
What the access state withholds is bytes (downloads) and derived science, and this document
carries neither. `rights.access` states the access level and `rights.embargo_until` the declared
end date, so a consumer can tell an embargoed record from an open one. The only policy seam in
the document is the coordinate policy: a survey whose station coordinates are withheld emits no
`extent`.

### Identity

`survey_id` is the survey's slug, identical to `mtcat.json`'s `surveys[].survey_id` and to the
directory component of the document's own path. `title` is the curated `project_name`, else
`name`; it is never derived from a directory name. `mtcat.json`'s `title` is the shorter display
label (`name`), so the two may differ.

---

## 1 schema

| | |
|---|---|
| Definition | Names the schema this document is written to. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, the constant `"ausmt-survey-metadata"` |
| Example | `"ausmt-survey-metadata"` |

## 2 version

| | |
|---|---|
| Definition | The schema version this document conforms to. Never the dataset version. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, `MAJOR.MINOR` |
| Example | `"0.1"` |
| Note | Generated from the single-source constant; the schema served beside the document displays the same version. |

## 3 survey_id

| | |
|---|---|
| Definition | The cross-layer joining identifier of the survey: the survey slug. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Example | `"auslamp-qld-phase-3"` |
| Note | Equals `mtcat.json` `surveys[].survey_id` and the `<survey_id>` path component. Source: `survey.yaml` `slug`. |

## 4 dataset_version

| | |
|---|---|
| Definition | The version of the dataset/release itself: for a record that represents a source release, that release's version; for a distinct AusMT release, the AusMT release version. Never a schema or package version. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Note | Not emitted in 0.1: `survey.yaml` has no home for a dataset version (its `version` is the package version, which is explicitly not this), so no document carries it until a curated home exists. |

## 5 title

| | |
|---|---|
| Definition | The title of the dataset. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, at least one character |
| Example | `"AusLAMP Queensland Phase 3"` |
| Note | Source: `survey.yaml` `project_name`, else `name`. |

## 6 dates

| | |
|---|---|
| Definition | The acquisition coverage of the observations and the publication date of the release, as two distinct facts. |
| Obligation | optional; present when either member exists |
| Occurrence | 0-1 |
| Type | object |
| Example | `{"coverage": {"year_start": 2023, "year_end": 2024}, "issued": "2024-10-01"}` |

Members:

| Member | Obligation | Type | Meaning |
|---|---|---|---|
| `coverage.year_start` | optional | integer | first acquisition year, from `survey.yaml` `dates.start` through the same year parser the catalogue uses |
| `coverage.year_end` | optional | integer | last acquisition year, from `dates.end` |
| `issued` | optional | string, ISO `YYYY-MM-DD`, format-checked | publication or release date of the dataset/release, from `dates.issued`; never derived from acquisition coverage; absent when unknown |

## 7 identifiers[]

| | |
|---|---|
| Definition | Identifiers OF this dataset/release, per its identity classification. The curated primary identifier among them anchors the citation and the MTCAT `doi` projection. |
| Obligation | optional; present only when curation designates at least one |
| Occurrence | 0-n |
| Type | array of `{scheme, identifier}`, at least one entry when present |
| Example | `[{"scheme": "DOI", "identifier": "10.26186/150000"}]` |
| Note | See [Identifiers and relationships](#identifiers-and-relationships). DOIs are bare (`10.x/...`), never resolver-prefixed; case is preserved. |

## 8 activities[]

| | |
|---|---|
| Definition | Related research activities (projects, programmes), each an activity identifier. Plural by design: a dataset may relate to several activities and an activity is never a dataset. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of `{identifier, scheme, relation?, title?}`, at least one entry when present |
| Example | `[{"identifier": "https://raid.org/10.12345/AB1234", "scheme": "RAiD"}]` |
| Note | Source in 0.1: `survey.yaml` `identifiers.project_raid` only (one RAiD row). `mtcat.json`'s `raid` scalar projects only when exactly one activity exists. |

## 9 abstract

| | |
|---|---|
| Definition | The full dataset description, uncapped. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Note | Source: `survey.yaml` `abstract`, verbatim. The concise discovery text is `mtcat.json`'s `description`. |

## 10 subjects[]

| | |
|---|---|
| Definition | Thematic classification of the dataset as controlled concept rows `{code, scheme, label?, uri?}`. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of object, at least one entry when present |
| Example | `[{"code": "370602", "scheme": "ANZSRC-FoR-2020"}]` |
| Note | The same row definition as [`mtcat.json` subjects](mtcat-schema.md#228-surveyssubjects), verbatim from `survey.yaml` `subjects`. |

## 11 creators[]

| | |
|---|---|
| Definition | The citation authors of the dataset/release, in citation order. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of `{name, name_type?, orcid?, ror?}`, at least one entry when present |
| Example | `[{"name": "Thiel, S.", "name_type": "person", "orcid": "0000-0002-1825-0097"}]` |
| Note | Source: `survey.yaml` `creators`, verbatim and in order. Never synthesised: a survey without a curated creators list has no `creators`. AusMT is never a creator. |

## 12 contributors[]

| | |
|---|---|
| Definition | Role-typed parties who contributed to the dataset/release. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of `{name, name_type?, role?, orcid?, ror?}`, at least one entry when present; `role`, when present, is one of `ProjectLeader`, `ProjectMember`, `DataCollector`, `ContactPerson`, `DataCurator`, `Sponsor`, `RightsHolder`, `Distributor`, `HostingInstitution` |
| Note | Source: `survey.yaml` `contributors`, verbatim. Unlike the MTCAT export, no `HostingInstitution` row is appended by the engine: this document states only what curation states. |

## 13 organisations[]

| | |
|---|---|
| Definition | Role-typed organisation rows. The publisher is explicit here because structured citation generation fails closed without one; a publisher is never inferred from the custodian. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of `{name, ror?, roles[], primary_custodian?}`, at least one entry when present; `roles` values are `publisher`, `custodian`, `distributor`, `data_collector`, `rights_holder`, `hosting_institution` |
| Example | `[{"name": "Geological Survey of South Australia", "roles": ["custodian", "publisher"], "primary_custodian": true}]` |
| Note | Source: `survey.yaml` `organisations`, verbatim. `primary_custodian` is present-true on at most one custodial row and is the deterministic source of `mtcat.json`'s `organisation`; it is never emitted as `false`. |

## 14 funders[]

| | |
|---|---|
| Definition | Funding of the dataset/release, DataCite-aligned. A name-only row is valid. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of `{name, ror?, award_number?, award_uri?, award_title?}`, at least one entry when present |
| Example | `[{"name": "AuScope", "award_uri": "https://doi.org/10.47486/XN002"}]` |
| Note | Source: `survey.yaml` `funding` rows: `organisation` becomes `name`, `organisation_ror` becomes `ror`, `grant_id` becomes `award_number`, `grant_title` becomes `award_title`, `funding_doi` becomes `award_uri` as `https://doi.org/<bare DOI>`. |

## 15 citation

| | |
|---|---|
| Definition | Citation preference and guidance over the identifier set. Never a duplicate bibliographic record; a dataset without a DOI remains citable. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | object |
| Note | See [The citation block](#the-citation-block). Source: `survey.yaml` `citation`, verbatim. |

Members:

| Member | Obligation | Type | Meaning |
|---|---|---|---|
| `preferred_identifier` | optional | `{scheme, identifier}` | the identifier to cite; must equal an `identifiers[]` entry |
| `preferred_text` | optional | string | source- or custodian-provided citation wording, verbatim |
| `text_source` | optional | `source_provided` or `ausmt_generated` | where the wording came from |
| `additional[]` | optional, at least one row when present | rows `{identifier?, preferred_text?, reason}` | further citations a user of the data should give; `reason` is required, for example `derived_product`, `repository_product`, `required_source_credit`, `companion_release` |

## 16 acknowledgements[]

| | |
|---|---|
| Definition | Plural acknowledgement wording, permanently distinct from citation. Authority-supplied wording is preserved verbatim. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of `{text, type?, source?}`, at least one entry when present; `type` is a free token, for example `required_source`, `custodian`, `community`, `traditional_owners`, `field_support`, `infrastructure`, `access_provider` |
| Note | Source: `survey.yaml` `acknowledgements`, verbatim. The engine authors no acknowledgement of its own. |

## 17 rights

| | |
|---|---|
| Definition | The licence and access state of the dataset. |
| Obligation | always emitted (`access` is always known) |
| Occurrence | 1 |
| Type | object |
| Example | `{"license": "CC-BY-4.0", "access": "embargoed", "embargo_until": "2027-02-01"}` |

Members:

| Member | Obligation | Type | Meaning |
|---|---|---|---|
| `license` | optional | string | `survey.yaml` `license` as curated |
| `access` | always | string | the normalised `access.level`: `open`, `metadata_only`, `embargoed` (an unknown token passes through and fails closed at serve time) |
| `embargo_until` | optional | string, ISO `YYYY-MM-DD`, format-checked | the declared embargo end date; absent means no declared date, not "not embargoed" |

## 18 extent

| | |
|---|---|
| Definition | The bounding box of the dataset, WGS 84 decimal degrees. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | object `{bbox: {west, south, east, north}}`, all four numbers |
| Example | `{"bbox": {"west": 136.97, "south": -30.22, "east": 137.07, "north": -30.1}}` |
| Note | Source: the curated `survey.yaml` `geographic_extent` only, emitted when its datum is WGS 84, its bounds are numbers and not the template's all-zero placeholder, and the survey's coordinates are not withheld. Never derived from station positions (that is `mtcat.json`'s `bbox`). |

## 19 relationships[]

| | |
|---|---|
| Definition | Typed links from this dataset to other records: source releases, collections, archives, reports. |
| Obligation | optional |
| Occurrence | 0-n |
| Type | array of `{identifier, identifier_type?, relation?}`, at least one entry when present; `identifier_type` is `DOI`, `Handle`, `URL` or `RAiD`; `relation` is a DataCite relationType read as "this dataset, relation, that record" |
| Example | `[{"identifier": "10.25914/bzd5-n780", "identifier_type": "DOI", "relation": "IsDerivedFrom"}]` |
| Note | See [Identifiers and relationships](#identifiers-and-relationships). The rows carry only the shared clean core; MTCAT's `custodian`, `identifies` and `resolution` extensions are not part of this document. |

## 20 attribution

| | |
|---|---|
| Definition | Provenance of the AusMT representation: who declared it, whether AusMT changed anything and what. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | object `{custodian?, custodian_ror?, statement?, changes_made?, changes_summary?, declared_by?, declared_date?}` |
| Note | Source: `survey.yaml` `attribution`, verbatim. `changes_made` is provenance; it never decides the dataset's identity and never triggers a DOI. |

## 21 provenance

| | |
|---|---|
| Definition | Document provenance: when and by what this document was generated. Not dataset dates. |
| Obligation | always emitted |
| Occurrence | 1 |
| Type | object `{generated, generator}` |
| Example | `{"generated": "2026-08-22T03:10:44Z", "generator": "ausmt/extract.build_portal 0.2.1"}` |
| Note | `generated` is a UTC timestamp, format-checked; `generator` is the pipeline name and version. |

---

## Identifiers and relationships

`survey.yaml` records the persistent identifiers around a survey as `related_identifiers` rows,
each typed and labelled with the data level it points at. Which of those rows are identifiers OF
this dataset (and so belong in `identifiers[]`) and which are links to other records (and so belong
in `relationships[]`) is a curation decision, the identity classification:

- Case A: the record represents the SAME dataset/release as one or more cited source identifiers.
  Curation lists those identifiers as `identity_classification.represents`; the emitter copies them
  into `identifiers[]` in curated order.
- Case B: the record is a DISTINCT AusMT-published release. Curation lists the release's own
  identifiers as `identity_classification.own_identifiers`; the emitter copies them into
  `identifiers[]`, and every source identifier is a relationship.

Every `related_identifiers` row that is not a designated identifier becomes a `relationships[]`
row reduced to `{identifier, identifier_type, relation}`. `relation` is the row's explicit relation
when one is curated, else the one its data level derives to (`collection` gives `IsPartOf`;
`raw_packed`, `level0` and `level1` give `IsDerivedFrom`; `level2` and `entire` give
`IsVariantFormOf`; `level3` gives `IsSourceOf`), else absent. Identifiers are emitted in canonical
form: a DOI loses any `https://doi.org/` or `http://dx.doi.org/` prefix, its case is preserved, and
exact duplicate rows are dropped. A survey whose classification is not yet curated has no
`identifiers[]`, and all of its related identifiers are relationships. Identity is curated and
resolution is a time-varying status: a reserved DOI that does not yet resolve is still emitted as
curated, with no resolution facet.

## The citation block

Citation lives here, not in `mtcat.json`. The model is source-led: the preferred citation is the
source or custodian release where one exists, AusMT does not become the citation target because it
provides access, and a DOI is never required for citability.

- `citation.preferred_identifier` names the identifier to cite. INVARIANT: it must equal one of
  the `identifiers[]` entries (the primary identifier designated in curation). The survey
  validator refuses a survey that violates this at the entry gates, and the build refuses to
  publish a document that violates it. `mtcat.json`'s `doi`, this primary identifier and the
  preferred citation identifier form one chain that can never disagree.
- `citation.preferred_text` carries source- or custodian-provided wording verbatim, with
  `text_source` saying where it came from. A dataset with no persistent identifier remains citable
  by this text alone.
- `citation.additional[]` lists further citations a user of the data should give (a derived
  product, the repository copy, a required source credit, a companion release), each with its
  `reason`.
- Structured citation generation that needs a publisher fails closed when `organisations[]`
  names none; a source-provided `preferred_text` stays valid and never causes a publisher to be
  inferred.

Acknowledgements are a separate class (`acknowledgements[]`) and never substitute for citation.
Where a source or custodian supplies required wording, it is preserved verbatim.

## Worked examples

Four documents in `engine/tests/fixtures/survey-metadata/` exercise the shape; they are synthetic,
because the corpus has no curated Case B release, no RAiD and no source-provided citation text
yet.

A Case B release (`synthetic-case-b.json`, excerpt): the release's own DOI is the identifier, the
two source releases are relationships, and the preferred citation is the own DOI.

```json
{
  "identifiers": [{"scheme": "DOI", "identifier": "10.99999/ausmt-example-merged-2026"}],
  "citation": {
    "preferred_identifier": {"scheme": "DOI", "identifier": "10.99999/ausmt-example-merged-2026"},
    "text_source": "ausmt_generated",
    "additional": [
      {"identifier": {"scheme": "DOI", "identifier": "10.99999/source-release-a"}, "reason": "required_source_credit"},
      {"identifier": {"scheme": "DOI", "identifier": "10.99999/source-release-b"}, "reason": "required_source_credit"}
    ]
  },
  "relationships": [
    {"identifier": "10.99999/source-release-a", "identifier_type": "DOI", "relation": "IsDerivedFrom"},
    {"identifier": "10.99999/source-release-b", "identifier_type": "DOI", "relation": "IsDerivedFrom"}
  ]
}
```

Two related activities (`synthetic-multi-activity.json`, excerpt): both are stated here; `mtcat.json`
emits no `raid` for this survey because the scalar projects only when exactly one activity exists.

```json
{
  "activities": [
    {"identifier": "https://raid.org/10.99999/programme", "scheme": "RAiD", "relation": "IsPartOf", "title": "Example national MT programme"},
    {"identifier": "https://raid.org/10.99999/phase-1-project", "scheme": "RAiD", "relation": "IsOutputOf", "title": "Example Phase 1 project"}
  ]
}
```

No persistent identifier (`synthetic-no-identifier-text.json`, excerpt): no `identifiers[]`, no
`relationships[]`, and the dataset is cited by the custodian's own wording.

```json
{
  "citation": {
    "preferred_text": "Example Researcher (2004). Example legacy broadband MT survey data package. Example University.",
    "text_source": "source_provided"
  }
}
```

The minimal document, emitted for a survey that curates nothing beyond the required facts:

```json
{
  "schema": "ausmt-survey-metadata",
  "version": "0.1",
  "survey_id": "min-survey",
  "title": "Minimal Survey",
  "rights": {"license": "CC-BY-4.0", "access": "open"},
  "provenance": {"generated": "2026-08-22T03:10:44Z", "generator": "ausmt/extract.build_portal 0.2.1"}
}
```

## Relationship to MTCAT

`mtcat.json` is the discovery projection of the same survey and the two agree where they overlap:
`survey_id` is identical; `subjects[]` rows share one definition; relationship rows share the core
`{identifier, identifier_type, relation}`; `mtcat.json`'s `doi`, when emitted, identifies the same
dataset/release as the designated primary identifier here; its `raid` is present only when exactly
one activity is asserted here; its `organisation` is the curated primary custodian where
`organisations[]` is curated. Funding, the full citation block, acknowledgements and the uncapped
abstract live only here.

## Validation and the build

The build validates every document it emits against the shipped schema with format checking on,
scans for nulls and empty containers, checks the citation invariant, and exits non-zero rather than
publish a failing document. After the build, `scripts/verify.py` validates every
`products/<slug>/survey-metadata.json` again, checks that the set of documents equals
`mtcat.json`'s `surveys[].survey_id`, and fails when the build's report lists any survey the
survey validator rejected (`build_report.json` `surveys_skipped_validation`) or dropped for any
other survey-granularity reason (`surveys_dropped`: an unreadable or non-mapping `survey.yaml`, an
invalid coordinate policy or `station_ids` block, a zero-station parse, an unserialisable metadata
record), so a build that lost a survey is never swapped in.
