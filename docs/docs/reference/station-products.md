# Per-station products

Each station has a small product directory holding two key-based JSON documents. `station.json` is the
per-station record and a public contract. `dimensionality.json` is served alongside it and is not a
contract: whether it folds into `station.json` or stays a feature file is an open decision, so do not
build on its shape.

```text
/data/products/<slug>/<station>/station.json
/data/products/<slug>/<station>/dimensionality.json
```

There is no index of product directories and directory listing is off. Build the paths from the slug and
the station id read out of `mtcat.json` (`survey_id`, and the station part of `station_id`). That is safe here because the product path
uses the station id verbatim, unlike an artifact filename.

Those two are the derived RECORDS. A served station also has downloadable transfer-function FILES, which
are a different thing in three ways: they are the data rather than a description of it, they exist only
for a station whose bytes AusMT distributes, and their paths are read from the download manifest rather
than built from the station id.

| File | Served path | Format |
|---|---|---|
| Transfer function as EDI | `/data/edi/<slug>/<file>.edi` | EDI, the custodian's own file for a station submitted as EDI, and one generated from the same transfer function for a station submitted only as EMTF XML |
| Canonical transfer function | `/data/xml/<slug>/<station>.xml` | EMTF XML, derived by the build |
| Station MTH5 | `/data/h5/<slug>/<station>.h5` | MTH5, transfer functions only, derived by the build |

Only the first row is ever a submitted file, and only for a station submitted as EDI. The record says
which: `provenance.input_sha256` (section 1.11) equals the manifest `edi` row's `sha256` exactly when
the served EDI is the custodian's file, and [EDI is the citable
artifact](../interoperability/tool-integration.md#edi-is-the-citable-artifact) says what that means
for a digest check.

The EDI filename is not derivable from the station id, so take all three paths from the manifest rather
than templating them. The MTH5 and EMTF XML paths do use the station id, but the manifest is still the
only place that tells you whether they exist for a given station. Their field-level documentation is in
the [data reference](../interoperability/api-reference.md#per-station-fetch-through-the-manifest) and
[Tool integration](../interoperability/tool-integration.md).

The station MTH5 is written by the same writer that produces the per-survey bundle and passes the same
round-trip gate against its source transfer function, so a station reads identically out of either. It
carries the survey's licence and credit inside the file (`Experiment/Surveys/<slug>` holds
`release_license` and the credit attributes), which is why it ships with no licence sidecar beside it.

## Normative artifact

| | |
|---|---|
| Normative artifact | `engine/schema/ausmt-station.schema.json` for `station.json`; the build's product emitter, `engine/extract/build_portal.py`, for `dimensionality.json` |
| Served location | `/data/products/<slug>/<station>/` |
| Served schema | `/data/ausmt-station.schema.json`, `/data/schemas/ausmt-station/0.1/ausmt-station.schema.json` |
| Version | 0.1 (draft) for `station.json`; `dimensionality.json` declares none and is additive and key-based |
| Status | `station.json` is a public contract; `dimensionality.json` is served alongside it and is not a contract |
| Access | the product tree is a served surface, so it rides the same access gate as the download files |
| Validated | the build validates every emitted `station.json` against the shipped schema with format checking on, and against the semantic rules JSON Schema cannot state, and refuses to publish a document that fails; `scripts/verify.py` re-runs both over the built tree and checks that the set of published `ausmt_id` values equals the set of stations `mtcat.json` catalogues |

`dimensionality.json` has no JSON Schema artifact. Where this page and the emitter disagree, the
emitter is right.

The semantic rules held above the schema, which a consumer may rely on without re-deriving them: run
ids are unique within a record and so are resource ids; a resource that names a run names one this
record publishes; `time_period` never ends before it starts; an electric channel carries the electrode
circuit and never a `sensor`, a magnetic channel the reverse; a withheld record carries the stub
members of section 1.18 and nothing else; every DOI is bare canonical; and `distribution.edi_path` and
the served EDI resource state one path or neither states any.

## Gating

The two documents are gated differently, and the difference matters when looping over stations.

| | Open survey | Withheld survey |
|---|---|---|
| `station.json` | full record | `200`, with `"withheld": true`, an `access` block, and no derived science |
| `dimensionality.json` | full record | `404`, never written |

So `station.json` always resolves and is worth requesting for any station. `dimensionality.json` should
only be requested when the survey's `access` is `open`; that `404` is not a transport error.

The three downloadable files above are gated together and more strictly: a withheld survey has none of
them and no manifest row for any of them, and inside a served survey a station whose position the
custodian generalises or withholds also has none, because all three carry the true position. A station
with no manifest rows is not an error to handle; it is the withholding, stated by omission.

---

## 1 station.json

The per-station product record: identity, location, band and period range, the derived diagnostics, the
processing strings read from the source file, the distribution state, the coordinate QC verdict, any
canonical conditioning notes, the frame facts, a provenance block naming the input file and its
SHA-256, and the two canonical blocks `runs` and `resources`. The example below shows every member
except `coordinate_policy`, which section 1.15 covers because it appears only for a station whose
position is not exact; a station whose survey declares no `station_ids` provenance carries no
`provenance.source`.

Three members open every record, on the full and the withheld branch alike: `schema` names the
contract, `version` names the schema version the document conforms to, and `survey_id` is the survey
slug. `survey` remains the display title; a display title is not an identifier, so a consumer joining
this record to `mtcat.json` or to `survey-metadata.json` keys on `survey_id`, which is the same slug in
all three.

```json
{
  "schema": "ausmt-station",
  "version": "0.1",
  "ausmt_id": "au.vulcan-2022.A1",
  "station": "A1",
  "survey": "Vulcan 2022",
  "survey_id": "vulcan-2022",
  "country": "Australia",
  "organisation": "University of Adelaide",
  "location": { "lat": -30.123, "lon": 135.456 },
  "data": { "type": "BBMT", "n_periods": 62, "period_min_s": 0.0033, "period_max_s": 1365.3 },
  "diagnostics": {
    "median_relative_error": 0.041,
    "remote_reference": false,
    "tipper_available": false,
    "completeness_smoothness_diagnostic": {
      "value": 3.4, "basis": "e",
      "note": "not a quality or geological-value judgement" },
    "classification": "2-D",
    "skew_beta_median_deg": 0.7,
    "pct_periods_3d": 0,
    "method": "phase-tensor (Caldwell 2004)",
    "note": "screening diagnostic, not an interpretation product"
  },
  "processing": { "software": "Birrp 5.0", "algorithm": null,
                  "remote_reference": false, "remote_site": null,
                  "file_written_by": { "name": "MTpy", "version": null },
                  "note": null },
  "distribution": { "edi_available": true, "license": "CC-BY-4.0",
                    "edi_path": "edi/vulcan-2022/Vulcan_A1.edi" },
  "provenance": { "pipeline": "ausmt/extract.build_portal", "input_file": "Vulcan_A1.edi",
                  "input_sha256": "0d70…",
                  "source": { "original_filename": "Vulcan_A1.edi",
                              "source_record_id": "2781110A", "acquisition_stage": "1" } },
  "coordinate_qc": null,
  "canonical_conditioning": null,
  "frame": { },
  "runs": [
    { "id": "A1-r01",
      "sample_rate_hz": 10,
      "data_logger": { "manufacturer": "LEMI", "model": "LEMI-423", "serial_number": "#0034",
                       "identifiers": [ { "scheme": "DOI", "identifier": "10.82388/u3jf7ztm" } ] },
      "channels": [
        { "component": "ex", "measurement_azimuth_deg": 180, "dipole_length_m": 43,
          "contact_resistance": { "source_value": "1.82 kilo-ohms", "value": 1820, "unit": "ohm" } },
        { "component": "hx", "measurement_azimuth_deg": 0,
          "sensor": { "manufacturer": "LEMI", "model": "LEMI-120", "serial_number": "134" } }
      ] }
  ],
  "resources": [
    { "id": "edi", "kind": "transfer_function", "format": "edi",
      "provenance_role": "source", "representation_role": "original",
      "path": "edi/vulcan-2022/Vulcan_A1.edi",
      "related_collection_identifiers": [
        { "scheme": "DOI", "identifier": "10.25914/bzd5-n780", "identifies": "raw_packed" } ] },
    { "id": "emtfxml", "kind": "transfer_function", "format": "emtfxml",
      "provenance_role": "derived", "representation_role": "alternate",
      "path": "xml/vulcan-2022/A1.xml" },
    { "id": "edi-zip", "kind": "archive", "format": "zip",
      "path": "bundles/vulcan-2022-edi.zip" },
    { "id": "xml-zip", "kind": "archive", "format": "zip",
      "path": "bundles/vulcan-2022-xml.zip" },
    { "id": "ts-raw_packed", "kind": "time_series", "format": "zip",
      "provenance_role": "source", "representation_role": "original",
      "access_url": "https://thredds.nci.org.au/thredds/fileServer/my80/…/A1.zip",
      "repository": "NCI", "processing_level": "raw", "packaging": "packed_archive",
      "bytes": 1042000000,
      "note": "verified against NCI THREDDS on 2026-08-24" }
  ]
}
```

`related_collection_identifiers` is projected per survey, so the identifiers a survey states ride
every one of its served resource rows; the example shows them on one row to stay readable. On a
time-series row the identifier rides only the level whose product it names.

### 1.1 ausmt_id

| | |
|---|---|
| Definition | The station's globally unique public id. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Format | `au.<slug>.<station>[.<variant>]` (the variant suffix appears only when a survey serves two processings of one site) |
| Example | `"au.vulcan-2022.A1"` |

### 1.2 station

| | |
|---|---|
| Definition | Station id within the survey. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"A1"` |
| Note | Carries the processing-variant suffix where one site has several processings, matching catalogue column 0. |

### 1.3 survey

| | |
|---|---|
| Definition | The survey's display name. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"Vulcan 2022"` |

### 1.4 country

| | |
|---|---|
| Definition | Country the survey was acquired in. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Default | `"Australia"` when the survey declares none |

### 1.5 organisation

| | |
|---|---|
| Definition | Custodian organisation of the survey. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |

### 1.6 location

| | |
|---|---|
| Definition | The station's published position. |
| Obligation | mandatory on a served station |
| Occurrence | 1 |
| Type | object with members `lat` and `lon`, each a number or null |
| Example | `{ "lat": -30.123, "lon": 135.456 }` |
| Note | Post-mask values: exact, generalised to 0.1 degrees, or `null` where the custodian withholds the position. This is the position the custodian chose to publish. |

### 1.7 data

| | |
|---|---|
| Definition | Band and period coverage of the transfer function. |
| Obligation | mandatory on a served station |
| Occurrence | 1 |
| Type | object |
| Example | `{ "type": "BBMT", "n_periods": 62, "period_min_s": 0.0033, "period_max_s": 1365.3 }` |

| Member | Type | Definition |
|---|---|---|
| `type` | string | band, from `AMT`, `BBMT`, `LPMT`, `GDS`, `unknown` |
| `n_periods` | integer | number of periods in the source file |
| `period_min_s` | number or null | shortest period, seconds |
| `period_max_s` | number or null | longest period, seconds |

### 1.8 diagnostics

| | |
|---|---|
| Definition | The automated screening diagnostics for this station. |
| Obligation | mandatory on a served station |
| Occurrence | 1 |
| Type | object |
| Note | Every value here is an automated, indicative diagnostic, not a curated rating. Absence of a processing string means not stated, not not used. |

| Member | Type | Definition |
|---|---|---|
| `median_relative_error` | number or null | median relative apparent-resistivity error |
| `remote_reference` | boolean | whether the source file states remote reference processing |
| `tipper_available` | boolean | whether a tipper is present |
| `completeness_smoothness_diagnostic` | object | `{value, basis, note}`; `basis` is `e` error-based or `s` shape-based |
| `classification` | string | the dimensionality screening class: `1-D`, `2-D`, `3-D` or `indeterminate` |
| `skew_beta_median_deg` | number | median absolute phase-tensor skew across usable periods, in degrees |
| `pct_periods_3d` | integer | percentage of usable periods whose absolute skew exceeds the three-dimensional threshold |
| `method` | string | the method the classification came from, `phase-tensor (Caldwell 2004)` |
| `note` | string | the caveat that qualifies the classification: a screening diagnostic, not an interpretation product |

The last five members are the dimensionality call, and the caveat is one of them on purpose. The
classification is a screening result for triage: it says which stations are worth a closer look, never
what the subsurface is. A copy of it that travelled without that sentence is the reason it was kept out
of this block until now; the sentence travels with it here.

A member the call leaves undetermined is **omitted** rather than published as null, so an
`indeterminate` station carries the class and the caveat and states no skew statistic at all.

The same five values are also served as `dimensionality.json` beside this document (section 2), from
the same computation. That document is not going away in the 0.x and 1.x series, because removing a
served file is a deprecation with its own notice; read either one.

#### 1.8.1 How the completeness-smoothness diagnostic is computed

`completeness_smoothness_diagnostic.value` is the 0-5 scalar the catalogue serves as `sci.json`
column `q`, computed by `engine/extract/_edi_science.py`. It exists so a reader screening hundreds of
stations can spot incomplete or rough transfer functions quickly. It is not a data-quality or
geological-value ranking, and AusMT ranks no station or survey. Its inputs:

| Input | Definition |
|---|---|
| completeness | fraction of periods with a positive apparent resistivity and a phase, xy mode |
| coverage | decades of period coverage divided by 4, clamped to [0, 1] |
| smoothness | 1 minus (median second-difference roughness of the xy phase curve) / 25 degrees, clamped; 0.5 when fewer than three phases exist |
| errscore | where per-period resistivity errors exist: the median relative error `mre` over both off-diagonal modes, mapped log-linearly from 30% or worse (0) to 2% or better (1) |

With errors (`basis` `e`): `value = 5 × (0.45·errscore + 0.18·coverage + 0.15·completeness + 0.22·smoothness)`.
Without usable error blocks (`basis` `s`): `value = 5 × (0.40·coverage + 0.30·completeness + 0.30·smoothness)`.
`median_relative_error` is that same `mre`, rounded to three decimals, and is null on the shape basis.

Limitations: smoothness uses the xy phase mode only; the error basis uses off-diagonal resistivity
errors only; there is no normalisation across instrument classes, so a long-period and a broadband
station score on the same scale. Read the value with the period range and the phase-tensor
diagnostics, never alone.

### 1.9 processing

| | |
|---|---|
| Definition | Processing metadata read from the source transfer-function file. |
| Obligation | mandatory on a served station |
| Occurrence | 1 |
| Type | object |
| Note | Best-effort reads of the file's free text. mt_metadata exposes no structured processing metadata for most EDI dialects, so a null here means the source did not state it. |

| Member | Type | Definition |
|---|---|---|
| `software` | string or null | the program that **processed** the transfer function |
| `algorithm` | string or null | processing algorithm |
| `remote_reference` | boolean | whether remote reference is stated |
| `remote_site` | string or null | the named reference station, where the header encodes one |
| `file_written_by` | object | `{name, version}`, the program that **wrote** the file, verbatim from its header; either member is null where the header does not state it |
| `note` | string or null | the arrangement detail from the source file's free text |

`software` and `file_written_by` are two different facts and are usually two different programs. An
EDI HEAD's `PROGNAME`/`PROGVERS` names whatever serialised the file, which across most of the corpus
is a database or plotting exporter (Geotools, WinGLink, MTpy) that estimated nothing; the program
that produced the transfer function is named only in the file's free text ("Processing code:
LEMIMT", "processing.software.name = ['Birrp 5.0', ' 5.2']"). `software` is mined from that text and
is null where the file names no processor, which means *not stated*, never *not used*. The writer
is reported separately under `file_written_by` rather than being published as the processor.

### 1.10 distribution

| | |
|---|---|
| Definition | Whether AusMT serves this station's bytes, and under what licence. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | object |
| Example | `{ "edi_available": true, "license": "CC-BY-4.0", "edi_path": "edi/vulcan-2022/Vulcan_A1.edi" }` |
| Note | `edi_path` is `null` when `edi_available` is false. A station whose coordinates are not exact is excluded from byte distribution even inside a served survey, so its record does not advertise an EDI. |

### 1.11 provenance

| | |
|---|---|
| Definition | What produced this record and from which bytes. |
| Obligation | mandatory on a served station |
| Occurrence | 1 |
| Type | object |
| Note | Carries the build provenance block (pipeline, pipeline version, extractor, software, git commit, parameters, generated timestamp) plus `input_file` and `input_sha256`. Every product carries one, so it is traceable to its source. A `source` member is added when the survey declares custodian provenance for this station's file; see below. |

#### 1.11.1 provenance.source

| | |
|---|---|
| Definition | The data custodian's own record detail for the source file this station was parsed from, carried verbatim. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | object |
| Default | absent, which is every station whose survey declares no `station_ids` provenance |
| Example | `{ "original_filename": "92_S1.edi", "source_record_id": "2781110A", "acquisition_stage": "1" }` |
| Note | Present only for a station whose survey declares a mapping-form `station_ids.map` entry carrying provenance keys, which the [survey.yaml reference](survey-yaml.md#162-station_idsmapsource-provenance) defines. `original_filename` is derived from the map key rather than declared, so it always names the file the bytes came from. AusMT does not interpret these values; they are the custodian's, and they travel in AusMT's own records only. The source file itself is served byte for byte and is never rewritten. |

### 1.12 coordinate_qc

| | |
|---|---|
| Definition | The coordinate quality-control verdict for this station. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | object or null |
| Default | `null` when the parse flagged nothing |
| Note | Present only when the parse actually flagged something, so an unflagged station is never implied to have been touched. Members are `flag`, `head_info_conflict_deg` and `resolution`. |

### 1.13 canonical_conditioning

| | |
|---|---|
| Definition | What the canonical EMTF XML writer had to change to make this station's XML schema-valid and round-trippable. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | array or null |
| Default | `null` when the station was not conditioned |
| Note | Read this before treating a value in the served XML as an observation. It is the list of things that file states which the source did not, for example a rotation angle that the source never asserted. |

### 1.14 frame

| | |
|---|---|
| Definition | The measured frame facts and the sign-convention verdict for this station. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | object or null |
| Note | Records what rotation the source declared, whether the engine derotated to geographic north at ingest, and the quadrant medians the convention gates read. `null` for inputs the gates do not cover. |

### 1.15 coordinate_policy

| | |
|---|---|
| Definition | The coordinate access policy in force for this station. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | string |
| Allowed values | `generalised`, `withheld` |
| Default | absent means `exact` |
| Note | Emitted only for a non-exact station, which keeps an exact station's record byte-unchanged. The boot-time surface the portal reads is [`coord_policy.json`](../developer/portal-documents.md#coord_policyjson). |

### 1.16 runs

| | |
|---|---|
| Definition | The acquisitions this station's source metadata describes. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | array of run objects |
| Note | Absent means run metadata is NOT asserted, never that no run occurred. |

A run is an acquisition, so a run is published only where a source states one. Most of the corpus
therefore carries no `runs` key at all: mt_metadata instantiates a placeholder run for every file it
reads, with a run id synthesised from the station name, a 0 Hz rate, a 1980 epoch window and an
unnamed logger, and none of that is a source assertion. The values published here come from the
`>INFO` block the custodian wrote, read by the dialect extractors described in
[the build lifecycle](../developer/build-lifecycle.md#the-build-step-by-step).

| Member | Type | Definition |
|---|---|---|
| `id` | string | The run's identifier: the source's own where the source declares one, otherwise a curated local id assigned once and stored in the survey package. Never regenerated, so correcting a timestamp or a serial cannot rename a run. |
| `time_period` | object | `start`, and `end` where the source states one. ISO 8601 UTC. `end` is ABSENT when unknown, never null. |
| `sample_rate_hz` | number | The run's nominal rate. Present whenever any channel declares a rate. |
| `data_logger` | object | `manufacturer`, `model`, `serial_number` and `identifiers[]`, each present only where the source states it. |
| `channels` | array | The channels acquired in this run. |

A channel enters `channels` only where it is corroborated: the `>INFO` block names it, or the served
transfer function was measured from it. A DEFINEMEAS declaration alone is not corroboration, and a
source note contradicting the channel list wins over both. The remote-reference `rr*` channels are
never published: they are library defaults, and no corpus source declares one.

| Channel member | Type | Definition |
|---|---|---|
| `component` | string | `ex`, `ey`, `hx`, `hy`, `hz`. The only mandatory member. |
| `measurement_azimuth_deg` | number | Sensor orientation where the source states it. |
| `dipole_length_m` | number | Electric channels only. |
| `contact_resistance` | object | Electric channels only: `source_value` always, plus `value` and `unit` where the unit is one the build parses. The source string is never discarded. |
| `sensor` | object | Magnetic channels only: the same shape as `data_logger`. |

### 1.17 resources

| | |
|---|---|
| Definition | The addressable things that represent this station or contain it, whether AusMT serves them or hands them off. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | array of resource objects |
| Note | Absent on a station with nothing to describe, and on every withheld record. |

Runs describe acquisitions; resources describe files. Nesting never implies that one resource
belongs to one run. A resource here is something a consumer can fetch: the station's transfer
function as the custodian's EDI, as the canonical EMTF XML, as MTH5, the per-survey archives those
files are bundled into, and the station's recorded time series held at NCI. `manifest.json` stays
the checksum and inventory authority for what AusMT serves; a resource references its path and never
restates a hash. The served rows come first and the hand-off rows after them.

An `archive` row is a containment claim, and containment is decided per station rather than per
survey. A survey bundle holds the bytes its stations actually served, so a station whose position
policy withholds its EDI and its EMTF XML is in neither zip its survey publishes, and its record
advertises neither. The number of records naming a bundle therefore equals that bundle's
`n_stations` in `manifest.json`.

| Member | Type | Definition |
|---|---|---|
| `id` | string | Stable within this document. Never an array index or a path. |
| `kind` | string | `transfer_function` for a rendition of the station's TF, `archive` for a bundle, `time_series` for the station's recording held at an external archive. |
| `format` | string | `edi`, `emtfxml`, `mth5`, `netcdf`, `zip`. |
| `path` | string | The served path, the same one the download manifest records for those bytes. AusMT-served rows only. |
| `access_url` | string | An absolute public download route at another repository. `time_series` rows only. |
| `repository` | string | The controlled token naming the repository that holds the bytes. `time_series` rows only. |
| `processing_level` | string | The product level, from the closed vocabulary below. |
| `packaging` | string | `packed_archive` where the level is served as one archive; omitted for a single file. |
| `bytes` | integer | The archive's own stated size for the routed file, converted. AusMT never measured it, and the archive states sizes to four significant digits, so above a few kilobytes read it as the estimate it is rather than as a content-length. Measured against the live archive across every published row (2026-08-24): the figure was never LARGER than the file served, and never more than 0.1% smaller. `time_series` rows only. |
| `note` | string | For a `time_series` row, the fieldnote naming the day the crawl read the file. |
| `provenance_role` | string | `source` or `derived`, emitted only where it is certain. |
| `representation_role` | string | `original`, `alternate` or `archival_copy`, on the same terms. |
| `derived_from_runs` | array | For a derived row, the runs THIS record publishes that it was built from. |
| `related_collection_identifiers` | array | Identifiers of collections that CONTAIN this resource. |

The served EDI is the custodian's file, never edited, so it is a `source` in its `original` form.
The EMTF XML and the MTH5 are this engine's conversions of it, so they are `derived` `alternate`
representations. The bundle archives carry neither axis in 0.1: whether a zip of source EDIs is
source or derived is a semantics question, not a mechanical one.

No resource carries `identifiers[]`, because no DOI identifies any exact file AusMT serves today. A
DOI that identifies a containing collection goes in `related_collection_identifiers` and carries the
curated scope it was declared with, so a collection DOI can never be read as an identifier of the
file it sits beside. A row is projected only where the curation states that scope: a bare canonical
DOI whose `identifies` names a collection or product level. A row with no scope, a row whose scope
names neither a collection nor a product level, a row that is not a DOI, and a DOI one survey
declares at two different levels are all omitted and reported for curation, because an unplaceable
row would publish a wrong citation claim.

`distribution.edi_path` is the legacy form of the same fact and stays byte-compatible through 1.x; a
test pins the two to agree, and 2.0 retires the legacy key.

#### Time-series rows

A `kind: time_series` row describes the station's recorded time series held at NCI, one row per
product level. It is a HAND-OFF, not a holding: AusMT stores none of those bytes, proxies none of
them and builds no archive of them, so the row carries `access_url` and no `path`, no checksum and
no `service_urls`. The URL is the absolute, percent-encoded route on
`thredds.nci.org.au/thredds/fileServer/`, which is the route the archive serves; OPeNDAP answers 500
for these files, so no service is advertised at all.

The rows come from the per-survey time-series register in the survey packages
([`ts-index.yaml`](survey-yaml.md#103-ts-indexyaml-the-verified-resource-register)), which is written
out of band by a crawler and read by the build as a file. Nothing in a build contacts the archive, so
the row states the day the CRAWL saw the file, verbatim: `verified against NCI THREDDS on <date>`.
An outage never changes what a row says, because discovery metadata must not follow service health.

A row exists only where the register marks it `verified`, the level is one AusMT routes, and the
station is open. A `pending` row is an adjudication-queue entry whose match nobody has confirmed; a
`retired` row is evidence of a resource that ceased to exist. A station whose coordinate policy
generalises or withholds its position gets no row either, because a raw recording carries the true
position the policy withholds. A level with nothing verified produces no row at all, never a row
with an empty route.

Withdrawal takes curation and cannot happen by accident. A URL that stops answering is an outage
until it has failed twice, at least a fortnight apart, AND a curator has set `review: retired` with
the date and the reason; the row then stops projecting entirely while staying on file as evidence.
That is also the one lawful way the catalogue's `has_time_series` flag goes down, when the retired
row was the station's last verified one.

Level 2 is excluded from this projection. The archive's `level_2` tree holds transfer functions
rather than time series, and publishing them under `kind: time_series` would assert a recorded time
series for stations that have none. The register still stores those rows for curation.

Because nothing AusMT holds corroborates a route to another host, these rows carry their own gate,
and it runs at both of the places the station record is checked: in the build before anything is
published, and again over the built tree before a deployment swaps `current`. A `time_series` row
must state a route and a product level; the route must be the absolute, percent-encoded fileServer
route, so a literal space fails and a `dodsC` URL cannot be expressed; no resource may advertise a
service; and level 2 under this kind is refused rather than merely never emitted.

Packed raw is the custodian's own recording in its original form, so it is a `source` `original`.
The level 0 and level 1 products are concatenated, resampled and rotated versions of it, so they are
`derived` `alternate`, and where this record publishes the acquisition they were built from,
`derived_from_runs` names it. A containing-collection identifier rides the row whose product it
names: the packed raw product DOI places on the packed raw row and on nothing else, and a
survey-scope collection DOI places on no time-series row at all.

#### Processing level and packaging

The schema defines two small closed vocabularies for a resource, `processing_level` (`raw`,
`level0`, `level1`, `level2`, `level3`) and `packaging` (`packed_archive`). The time-series rows
above are what emits them. They are separated deliberately: MTCAT's legacy `identifies` values mix
scope, packaging and processing level on one axis, and this schema maps OUT to that vocabulary
rather than inheriting it.

| Station `processing_level` | Station `packaging` | NCI level name | MTCAT `identifies` |
|---|---|---|---|
| `raw` | `packed_archive` | the survey's packed raw time series (NCI numbers no level for it) | `raw_packed` |
| `level0` | | `level_0` | `level0` |
| `level1` | | `level_1` | `level1` |
| `level2` | | `level_2` | `level2` |
| `level3` | | `level_3` | `level3` |

`collection` and `entire` have no station `processing_level`: they state SCOPE, not level, and
mapping them onto one is the debt these vocabularies exist to refuse. The two part company for
placement: `collection` names the parent record containing the survey's holdings, so a DOI declared
at that scope is placeable, while `entire` means one record covering all levels, which describes a
record rather than asserting containment, so a row declared at that scope is declined.

### 1.18 The withheld record

A station in a survey that is not served gets a stub carrying only the discovery-safe identity the
public catalogue already exposes.

```json
{
  "schema": "ausmt-station",
  "version": "0.1",
  "ausmt_id": "au.vulcan-2024-25.Vul24-13",
  "station": "Vul24-13",
  "survey": "Vulcan 2024-25",
  "survey_id": "vulcan-2024-25",
  "country": "Australia",
  "organisation": "Adelaide University",
  "access": { "level": "embargoed", "embargo_until": "2027-02-01", "served": false },
  "distribution": { "edi_available": false, "license": "…", "edi_path": null },
  "withheld": true,
  "note": "This survey's access state withholds its derived science products …"
}
```

The stub carries these twelve members and no thirteenth. That is enforced, not conventional: the
withheld branch of the schema is closed, nested blocks included, and the build and `verify.py` both
reject a record that grows a key. Extending the stub therefore takes a schema change, which is the
point: a key-name blocklist over an open object is bypassable, and coordinates were once shown to
validate under unbanned spellings and inside an open `access` block.

| Member | Type | Definition |
|---|---|---|
| `schema` | string | `ausmt-station`, on both branches |
| `version` | string | the schema version this document conforms to, on both branches |
| `ausmt_id` | string | the station's globally unique public id, as on a full record |
| `station` | string | station id within the survey |
| `survey` | string | the survey's display name |
| `survey_id` | string | the survey slug, on both branches |
| `country` | string | country the survey was acquired in |
| `organisation` | string | custodian organisation of the survey |
| `access` | object | `{level, embargo_until, served}`: the normalised access level, the declared embargo end date where the level carries one, and `served`, which is `false` on every withheld record |
| `distribution` | object | `{edi_available, license, edi_path}`: `false`, the survey's licence, and `null`. Nothing is distributed for a withheld record |
| `withheld` | boolean | `true`, the marker a consumer tests on |
| `note` | string | why the derived science is absent |

There is no `location`, no `data`, no `diagnostics`, no `processing`, no `runs`, no `resources` and no
`provenance`. The survey's discovery metadata stays fully public in the catalogue; only the derived
science is withheld here.

---

## 2 dimensionality.json

The phase-tensor screening result for one station, served alongside `station.json`; not a contract. It
is never written for a station in a withheld survey. Its members are documented here so a reader can
interpret what is served, not as a promise about its shape.

`station.json`'s `diagnostics` block now states the same call, from the same computation (section 1.8).
This document is the older surface and keeps being written unchanged: removing a served file is a
deprecation with its own notice, not a refactor. A consumer reading `station.json` needs neither this
file nor a second request.

The classification is assigned by `engine/extract/_edi_science.py` from the per-period phase tensor
(Caldwell et al., 2004), with every threshold a named constant that `build_provenance.json` records:

1. Periods whose absolute skew is 15 degrees or more (`BETA_PHYSICAL_CAP_DEG`) are excluded as
   non-physical: a dead channel or a near-singular tensor drives skew toward its ceiling, which is
   evidence of bad data, not of 3-D structure.
2. If fewer than half (`MIN_USABLE_PERIOD_FRAC`) of the impedance-bearing periods survive, the class
   is `indeterminate`: the data do not support a call.
3. Otherwise the class is `3-D` if the median absolute skew exceeds 5 degrees (`SKEW_3D_DEG`) or more
   than 40% (`PCT_PERIODS_3D_THRESHOLD`) of usable periods have absolute skew above 3 degrees
   (`BETA_PER_PERIOD_DEG`); else `2-D` if the median ellipticity exceeds 0.10 (`ELLIP_2D_DEG`); else
   `1-D`.

Skew and ellipticity are defined on the [phase tensor](../science/phase-tensor.md) page. The result is
a screening product for survey triage, not period-by-period dimensionality analysis, which the build
does not attempt.

```json
{
 "classification": "2-D",
 "skew_beta_median_deg": 0.7,
 "pct_periods_3d": 0,
 "method": "phase-tensor (Caldwell 2004)",
 "screening_diagnostic": true,
 "note": "screening diagnostic, not an interpretation product"
}
```

The members, as the build writes them today. Treat the classification as a filter, not as a finding.

| Member | Type | Definition |
|---|---|---|
| `classification` | string or null | the screening class: `1-D`, `2-D`, `3-D` or `indeterminate`; `indeterminate` when fewer than half the periods are usable |
| `skew_beta_median_deg` | number or null | median absolute phase-tensor skew across usable periods, in degrees |
| `pct_periods_3d` | integer or null | percentage of usable periods whose absolute skew exceeds the three-dimensional threshold |
| `method` | string | the method the classification came from, `phase-tensor (Caldwell 2004)` |
| `screening_diagnostic` | boolean | marks the payload as a screening result rather than an interpretation |
| `note` | string | the caveat that travels with the payload |

---

## New products

A new derived product follows the same conventions: emit
`products/<slug>/<station>/<product>.json` with a method or citation field, a `screening_diagnostic` or
interpretation caveat where relevant, a `provenance` block, and any companion assets alongside the JSON.
The wiring steps are in [How to extend](../developer/extending.md#2-add-a-new-derived-science-product-eg-wire-up-strike).
Which products exist today is owned by [Science products](../science/science-products.md).
