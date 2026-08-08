# Build report schema

`build_report.json` is the structured per-survey record of what a build produced: how many stations each
survey built, which it dropped and why, the survey-scoped warnings, the canonical-conditioning notes, the
build-cache counters and the per-survey wall time.

It is public build metadata. The portal runtime does not read it; the curator serve-state view and any
operator tooling do. `build_provenance.json` says how the build was configured, and this document says
what that configuration produced, survey by survey.

## Normative artifact

| | |
|---|---|
| Normative artifact | `engine/schema/build_report.schema.json`, JSON Schema draft-07 |
| Served location | `/data/build_report.json` |
| `$id` | `https://ausmt.org/schema/build-report-1.0.schema.json` |
| Schema version | 1.0, carried in the schema filename |
| Validated | the build validates the document in its self-check; the verify step re-checks its presence, its schema, and a station-count cross-check against the download manifest |

Where this page and the schema disagree, the schema is right.

## Document structure

| Key | Obligation | Type | Contents |
|---|---|---|---|
| `generated` | mandatory | string | build timestamp |
| `engine_commit` | mandatory | string | engine commit the build ran at |
| `source_commit` | recommended | string or null | survey-repository commit the build read |
| `build_id` | recommended | string | the build identity string |
| `pipeline_version` | recommended | string | engine distribution version |
| `surveys` | mandatory | object | per-survey entries, keyed by slug |
| `totals` | mandatory | object | corpus totals |

The identity fields come from the same helpers that write `build.json` and `build_provenance.json`, so
the three documents cannot disagree about which commits produced a build.

```json
{
 "generated": "2026-07-27T08:29:41Z",
 "engine_commit": "0d705ea",
 "source_commit": "2a6624e",
 "build_id": "0d705ea…-2a6624e-2026-07-27T08:08:07.007756+00:00",
 "pipeline_version": "0.9.0",
 "surveys": {
  "vulcan-2022": {
   "stations_built": 34,
   "stations_dropped": [],
   "warnings": [],
   "conditioning": [
    {"note": "rotation frame not asserted by source", "count": 34, "stations": null, "except": null}
   ],
   "cache": {"digest": "1f4c8a9b2d3e", "hits": 34, "misses": 0, "writes": 0},
   "duration_seconds": 4.21
  }
 },
 "totals": {"surveys": 21, "stations_built": 1418, "warnings": 0}
}
```

---

## 1 Document keys

### 1.1 generated

| | |
|---|---|
| Definition | UTC timestamp the report was written. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string, ISO 8601 with a `Z` suffix |
| Example | `"2026-07-27T08:29:41Z"` |

### 1.2 engine_commit

| | |
|---|---|
| Definition | Short git HEAD of the engine repository the build ran from. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"0d705ea"` |
| Note | Mirrors `build.json`. |

### 1.3 source_commit

| | |
|---|---|
| Definition | Short git HEAD of the survey-repository checkout the build read. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string or null |
| Default | `null` for a build run against a raw or non-git survey directory |
| Note | Mirrors `build.json`. |

### 1.4 build_id

| | |
|---|---|
| Definition | The build identity string: engine commit, survey-data commit and build timestamp. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |
| Note | Mirrors `build.json`. It changes whenever anything that could change the output changed. |

### 1.5 pipeline_version

| | |
|---|---|
| Definition | Version of the engine distribution that produced the build. |
| Obligation | recommended |
| Occurrence | 0-1 |
| Type | string |
| Note | Mirrors `build_provenance.json`. |

### 1.6 totals

| | |
|---|---|
| Definition | Corpus totals over every survey entry. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | object with required members `surveys`, `stations_built`, `warnings`, each an integer of minimum 0 |
| Example | `{"surveys": 21, "stations_built": 1418, "warnings": 0}` |
| Note | Closed to further keys. |

### 1.7 surveys

| | |
|---|---|
| Definition | Per-survey build entries, keyed by survey slug. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | object, values as in [section 2](#2-a-survey-entry) |
| Note | A survey the build skipped has no entry. |

---

## 2 A survey entry

Every survey entry is closed to further keys and carries all six of `stations_built`,
`stations_dropped`, `warnings`, `conditioning`, `cache` and `duration_seconds`. Four more,
`xml_failures`, `ingest_sources`, `frame` and `source_integrity`, are optional.

### 2.1 surveys.<slug>.stations_built

| | |
|---|---|
| Definition | How many of the survey's stations this build produced products for. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | integer, minimum 0 |
| Example | `34` |

### 2.2 surveys.<slug>.stations_dropped

| | |
|---|---|
| Definition | Stations the build refused, one entry each. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | array of object with required members `station` and `reason`, both strings |
| Example | `[]` |
| Note | Populated by the convention gates. A gate refusal names the gate, the angles and the fix in `reason`. |

### 2.3 surveys.<slug>.warnings

| | |
|---|---|
| Definition | The survey-scoped warnings the build produced. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | array of string |
| Example | `[]` |
| Note | Covers access-gate warnings and a dropped non-http `nci_base`, among others. Counted into `totals.warnings`. |

### 2.4 surveys.<slug>.xml_failures

| | |
|---|---|
| Definition | Per-station EMTF-XML emission failures. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | array of object with required members `station` and `error`, both strings |
| Example | `[]` |
| Note | `error` is the exception class raised while writing the canonical XML. Each entry is also counted as a `warnings` entry, so a green build cannot hide the gap. The consequence depends on the station's ingest source, so read it next to [`ingest_sources`](#25-surveysingest_sources). |

What a listed station still serves depends on where it came from. An `edi`-sourced station falls back
to the custodian EDI it was built from and loses only its XML download. An `emtfxml`-sourced station
has no custodian file behind it, so it serves nothing at all: no canonical XML, no generated EDI, no
manifest row. Either way the served tree is left clean. The canonical XML and the derived EDI are
both written before the round-trip comparison runs, so a failure leaves two unverified files behind;
the build removes them, and neither is fetchable at the URL it would otherwise have occupied.

### 2.5 surveys.<slug>.ingest_sources

| | |
|---|---|
| Definition | The ingest source of each built station, keyed by station id. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | object whose values are one of `edi`, `mth5` or `emtfxml` |
| Example | `{"A1": "edi", "A2": "emtfxml"}` |
| Note | Derived from the suffix of the file each station record was parsed from, not from the survey's primary format, so a package holding both formats records which stations the EDI-wins precedence rule resolved to EDI and which came from EMTF XML. This is the only place that fact is published. Absent from reports written before EMTF XML became an ingest format. |

An `emtfxml` station is served differently from an `edi` one in a way no other field states. Its EDI
download is generated by mt_metadata from the submitted XML rather than copied from a custodian file,
so `catalogue.json` column 14, which is the SHA-256 of the file the custodian submitted, matches
neither of that station's manifest rows. For an `edi` station column 14 and the `edi` row agree.

### 2.6 surveys.<slug>.source_integrity

| | |
|---|---|
| Definition | The served-bytes integrity result for this survey's EDI-sourced stations. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | object with required members `checked`, `verified` (integers, minimum 0) and `mismatches` (array) |
| Example | `{"checked": 34, "verified": 34, "mismatches": []}` |
| Note | AusMT serves a custodian's EDI byte for byte and never rewrites it. This field is the evidence rather than the claim: after each file is copied the build re-hashes what actually landed in the served tree and compares it with the file supplied. `checked` counts the stations whose bytes were copied, `verified` those that matched. Closed to further keys. Absent from reports written before the gate existed. |

Each `mismatches` entry carries `station`, `file`, `source_sha256` and `served_sha256`. A mismatch is
a gate, not a note. The station's served file is removed, it gets no manifest row and it serves no
bytes at all, and the failure is also raised as a counted `warnings` entry so an otherwise green build
cannot hide it. The reasoning is in [survey.yaml section 16](survey-yaml.md#16-station-identifiers):
for third-party data the served file is the custodian's published record, and identifiers are
corrected in `survey.yaml` rather than in the file.

### 2.7 surveys.<slug>.conditioning

| | |
|---|---|
| Definition | The canonical-conditioning notes for this survey, aggregated by distinct note. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | array of [conditioning entry](#3-a-conditioning-entry) |
| Note | One entry per distinct note, ordered by first appearance. This is a survey-level view: the per-station notes stay in each station's `station.json` under `canonical_conditioning` and in the canonical store's own provenance record. One shared function produces both this array and the build's survey-level log lines, so the human log and the machine report cannot disagree. |

### 2.8 surveys.<slug>.frame

| | |
|---|---|
| Definition | Frame and sign-convention notes for this survey, aggregated the same way as `conditioning`. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | array of [conditioning entry](#3-a-conditioning-entry) |
| Note | Covers derotation records, convention warnings and insufficient-data notes. |

### 2.9 surveys.<slug>.cache

| | |
|---|---|
| Definition | The incremental build cache's counters for this survey. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | object with required members `digest` (string), `hits`, `misses` and `writes` (integers, minimum 0) |
| Example | `{"digest": "1f4c8a9b2d3e", "hits": 34, "misses": 0, "writes": 0}` |
| Note | `digest` is the first twelve hex characters of the survey's `survey.yaml` digest, or an empty string for a raw build. The cache may only change build speed: the products are byte-identical whether they came from a hit or a fresh compute. Closed to further keys. |

### 2.10 surveys.<slug>.duration_seconds

| | |
|---|---|
| Definition | Wall time this survey took to build. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | number, minimum 0 |
| Example | `4.21` |

---

## 3 A conditioning entry

A conditioning entry describes one distinct note and how many of the survey's note-carrying stations
carry it. Entries are closed to further keys and all four members are always present.

| Member | Obligation | Type | Definition |
|---|---|---|---|
| `note` | mandatory | string | the note text |
| `count` | mandatory | integer, minimum 1 | how many note-carrying stations carry it |
| `stations` | mandatory | array of string, or null | the carrier set, listed when it is short enough to enumerate |
| `except` | mandatory | array of string, or null | the absentee complement, listed when that side is the short one |

At most one of `stations` and `except` is non-null. Both null means neither side is short enough to
enumerate and the count alone tells the story. The enumeration limit is five stations on either side.
