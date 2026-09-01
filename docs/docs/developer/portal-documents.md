# Portal-internal documents

Not a public surface. The documents on this page are fetched by the portal's own browser code and by
the curator workbench; they carry no contract and no stability promise, and any build may change or
drop them. The public metadata contracts are `mtcat.json`, `survey-metadata.json` and `station.json`,
documented under [Reference](../reference/index.md); the download index is `manifest.json`,
documented in the [data reference](../interoperability/api-reference.md#download-inventory-manifestjson).
Read this page to work on the portal or the engine, not to build a consumer: a consumer reads the
contracts.

Five JSON documents are served under `/data/` with no JSON-Schema artifact behind them. Their shape is
defined by the build that writes them, and this page is their field reference. The positional arrays
`catalogue.json`, `sci.json` and `tf.json` are covered by [Portal data files](data-files.md), the
engine-to-portal column contract.

## Normative artifact

| | |
|---|---|
| Normative artifact | the build, `engine/extract/build_portal.py` |
| Version | none declared; every document here is key-based and additive |

Where this page and the build disagree, the build is right.

## Contents

| Document | Served path | Emitted |
|---|---|---|
| [`surveys.json`](#surveysjson) | `/data/surveys.json` | always |
| [`collections.json`](#collectionsjson) | `/data/collections.json` | always |
| [`build.json`](#buildjson) | `/data/build.json` | always |
| [`build_provenance.json`](#build_provenancejson) | `/data/build_provenance.json` | always |
| [`coord_policy.json`](#coord_policyjson) | `/data/coord_policy.json` | only when a station is not exact |
| [`ts_access.json`](#ts_accessjson) | `/data/ts_access.json` | only when a station has a verified, open archive route |

`coord_policy.json` and `ts_access.json` are emitted only when they would carry information, so a
consumer must read an absent file as a statement rather than an error. The rule is on each entry below.

---

## surveys.json

The full per-survey metadata the portal renders, generated from each survey's `survey.yaml`; that file is the field-by-field owner and is documented in the
[survey.yaml reference](../reference/survey-yaml.md).

### Structure

| | |
|---|---|
| Definition | An object of survey records. |
| Type | object |
| Keys | the survey DISPLAY name, for example `"Vulcan 2022"`, not the slug |
| Note | The slug lives in the `slug` field inside each record. Build a slug index by iterating the values. |

### Record members

| Member | Type | Definition |
|---|---|---|
| `slug` | string | the survey slug |
| `country` | string | country of acquisition |
| `region` | string or null | finer geographic facet |
| `org` | string | custodian organisation name |
| `org_ror` | string or null | ROR identifier of that organisation |
| `version` | string or null | survey package semantic version |
| `collection` | object or null | the declared collection membership block |
| `software` | string or null | processing software declared in `survey.yaml` |
| `lic` | string | the survey licence id |
| `doi` | string or null | dataset DOI, where the custodian has minted one |
| `pid` | string or null | survey handle from the instrument registry |
| `raid` | string or null | project RAiD |
| `related_identifiers` | array | typed provenance links; always a list, empty when none is declared |
| `instrument_pid` | string or null | survey or platform instrument PID |
| `instrument_model` | string or null | display string for the instrument system |
| `instruments` | array | structured instrument rows, present only when a survey declares one with a PID |
| `dates` | object or null | the declared acquisition date range |
| `year_start`, `year_end` | integer or null | acquisition year range |
| `funders` | array | funding rows |
| `pubs` | array | publication rows |
| `blurb` | string or null | the survey abstract |
| `access` | string | normalised access level: `open`, `metadata_only`, `embargoed` |
| `embargo_until` | string or null | declared embargo end date |
| `edi` | string | whether EDI is present |
| `mth5` | string | whether MTH5 is present |
| `ts` | string | `ok` when the survey declares time-series levels, otherwise `unk` |
| `ts_pid` | string or null | survey-specific raw time-series collection PID |
| `ts_levels` | array | the ordered time-series levels declared, present only when declared |
| `nci_base` | string or null | NCI THREDDS directory, where the survey sets one |
| `attribution` | object | rights of record, present only when declared |
| `sources` | array | upstream source datasets, present only when declared |
| `changes` | object | `{made, summary}`, present only when the survey declares `changes_made` |
| `cite` | object | `{au, yr, ti, ve, pb}`, the pre-rendered citation parts |
| `coord_resolution` | object or null | the declared DMS resolution, where one is set |
| `release_notes` | array or null | the declared release notes |
| `creators` | array | citation authors in citation order, present only when declared |
| `contributors` | array | role-tagged contributors, present only when declared |

### Notes

`creators` and `contributors` are what the citation and the credit rows read. There is no
`investigators` key: the back-compat facet that read the two retired flat credit keys has been
removed along with its readers, rather than left in place as a key that is always empty.

A key is absent rather than null when the survey declares nothing, which keeps a survey's record
byte-identical when a field it does not use is added to the model.

The exported `contributors` list always ends with the hosting portal appended as
`{"name": "AusMT", "name_type": "organisation", "role": "HostingInstitution"}`. No survey declares that
role for itself, so strip it when re-hosting rather than citing.

---

## collections.json

Programme groupings, rolled up from the `collection` block each member survey declares.

### Structure

| | |
|---|---|
| Definition | An object of collection records. |
| Type | object |
| Keys | the collection id, for example `"auslamp"` |
| Default | `{}` when no survey declares collection membership |

### Record members

| Member | Type | Definition |
|---|---|---|
| `id` | string | the collection id, repeated inside the record |
| `title` | string | display name; falls back to the id |
| `type` | string or null | `programme`, `release`, `institutional`, `compilation`, `other` |
| `status` | string or null | `active`, `completed`, `archived`; null where a member declared something else |
| `start_year` | integer or null | year the programme began |
| `last_updated` | string or null | ISO date the programme record was last updated |
| `description` | string or null | one paragraph shown on the collection card and page |
| `prose` | object | ABSENT unless a member declares it. Long-form page copy: `{about, data, members_before, members_after, organisations}`, each an array of paragraph strings. A paragraph beginning `# ` is a subheading. Not emitted to MTCAT or to `survey.json` |
| `surveys` | array of string | member survey DISPLAY names, sorted |
| `n_surveys` | integer | length of `surveys` |
| `n_stations` | integer | total stations across the member surveys |
| `bbox` | object or null | `{west, south, east, north}` over the member stations |
| `centroid` | object or null | `{latitude, longitude}`, the MEAN of the member station positions |

### Notes

Grouping is an exact string match on the id, so two ids differing only by case or whitespace form two
collections. The build warns when it sees such a pair.

A collection centroid is the mean of its member station positions. A survey centroid, in `mtcat.json`,
is the centre of that survey's bbox. The two are computed differently.

`mtcat.json` carries the same groupings under `collections[]`, keyed the same way, with member surveys
pointing back through `surveys[].collection_id`.

---

## build.json

The small standalone identity document the portal footer reads. A consumer polls `mtcat.json`'s
`portal.generated_at` (or its `ETag`) instead.

```json
{
 "build_id": "0d705eaaa22ded1564f6d36e349ef5d5761b3e69-2a6624e-2026-07-27T08:08:07.007756+00:00",
 "engine_commit": "0d705eaaa22ded1564f6d36e349ef5d5761b3e69",
 "source_commit": "2a6624e",
 "generated": "2026-07-27T08:08:07.007756+00:00",
 "mt_metadata_version": "1.0.9",
 "mth5_version": "0.6.8"
}
```

| Member | Obligation | Type | Definition |
|---|---|---|---|
| `build_id` | mandatory | string | engine commit, survey-data commit and build timestamp, concatenated |
| `engine_commit` | mandatory | string | git HEAD of the engine repository |
| `source_commit` | recommended | string or null | git HEAD of the survey repository; null for a raw or non-git build |
| `generated` | mandatory | string | ISO 8601 build timestamp |
| `mt_metadata_version` | recommended | string or null | version of the mt_metadata library the build ran against |
| `mth5_version` | recommended | string or null | version of the mth5 library the build ran against |

### Notes

`build_id` changes whenever anything that could change the output changed, including a metadata-only
edit. Compare it rather than the `generated` timestamp alone.

The document is a few hundred bytes and every response carries an `ETag`, so a conditional request costs
a `304` when nothing has changed.

---

## build_provenance.json

The longer record of how a build was produced and with what parameters. Use it when a paper has to state
exactly what produced the numbers it used.

| Member | Obligation | Type | Definition |
|---|---|---|---|
| `pipeline` | mandatory | string | the pipeline name |
| `pipeline_version` | mandatory | string | the engine distribution version |
| `extractor` | mandatory | string | which parser produced the canonical record |
| `software` | mandatory | object | interpreter versions, for example `{"python": "3.12.7"}` |
| `git_commit` | recommended | string or null | engine commit |
| `parameters` | mandatory | object | the dimensionality thresholds and the diagnostic description |
| `generated` | mandatory | string | ISO 8601 build timestamp |
| `n_stations` | mandatory | integer | stations in the build |
| `n_surveys` | mandatory | integer | surveys in the build |
| `input_formats` | mandatory | array of string | which input formats the build read |
| `edi_bundled` | mandatory | boolean | whether any EDI was bundled for download |
| `nci_tier_artifacts` | mandatory | integer | manifest rows served from the NCI tier |
| `distribution_flags` | mandatory | object | the bundle feature flags in force |
| `base_url` | mandatory | string | the manifest `base_url` this build wrote |
| `cache` | mandatory | object | the incremental cache counters, or `{"enabled": false}` |
| `mt_metadata_version` | recommended | string or null | mirrors `build.json` |
| `mth5_version` | recommended | string or null | mirrors `build.json` |
| `source_commit` | recommended | string or null | mirrors `build.json` |

### Notes

`parameters.dimensionality` records the thresholds the screening ran with. They are read from the named
constants in the science module rather than retyped, so the recorded parameters cannot drift from the
code that ran. Provenance describes what actually executed.

The document is optional to a consumer: the portal loads without it.

---

## coord_policy.json

A compact map of `ausmt_id` to coordinate policy, for the stations whose policy is not `exact`.

```json
{"au.example-2021.S07": "generalised", "au.example-2021.S08": "withheld"}
```

| | |
|---|---|
| Definition | Which stations are served with a position that is not the surveyed one. |
| Type | object, string values |
| Allowed values | `generalised`, `withheld` |
| Emitted | only when at least one station in the corpus is not exact |
| Note | Absence of the file means every served position is exact. It carries no coordinate, only the policy string. The per-station product carries the same value as [`coordinate_policy`](../reference/station-products.md#115-coordinate_policy); this file is the boot-time surface the portal drawer reads so it can badge a position without fetching a station record. |

---

## ts_access.json

The archive routes this deployment may hand a reader off to: `ausmt_id` to level token to the size and
the archive's own path for that station's time series at that level.

```json
{"au.example-2021.S07": {"raw_packed": {"bytes": 9868836788, "url_path": "my80/.../S07 [REMOTE].zip"},
                         "level1_mth5": {"bytes": 20360000, "url_path": "my80/.../S07.h5"}}}
```

| | |
|---|---|
| Definition | Per-station, per-level route detail for the verified time series held at NCI. |
| Type | object of objects; `bytes` integer, `url_path` string |
| Level tokens | `raw_packed`, `level0`, `level1_mth5`, `level1_netcdf` |
| Emitted | only when at least one station in the corpus has a verified, open route |
| Note | MEMBERSHIP is the access decision and it is made in the build: a station whose survey is not served, whose position is generalised or withheld, or whose register rows are pending or retired, is absent from this file, and `level2` never appears (that tree holds transfer functions, not time series). `url_path` is the archive's own string verbatim; the absolute download URL is `https://thredds.nci.org.au/thredds/fileServer/` plus its percent-encoded form, the same string the station record publishes as `access_url`. AusMT hosts none of these bytes. |
| Absence | a deployment that publishes no download index; consumers say exactly that, never "could not be loaded". |
