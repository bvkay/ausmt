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
`stations_dropped`, `warnings`, `conditioning`, `cache` and `duration_seconds`. Two more,
`xml_failures` and `frame`, are optional.

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
| Note | A station listed here is served as EDI only and has no XML download. `error` is the exception class raised while writing the canonical XML. Each entry is also counted as a `warnings` entry, so a green build cannot hide the gap. |

### 2.5 surveys.<slug>.conditioning

| | |
|---|---|
| Definition | The canonical-conditioning notes for this survey, aggregated by distinct note. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | array of [conditioning entry](#3-a-conditioning-entry) |
| Note | One entry per distinct note, ordered by first appearance. This is a survey-level view: the per-station notes stay in each station's `station.json` under `canonical_conditioning` and in the canonical store's own provenance record. One shared function produces both this array and the build's survey-level log lines, so the human log and the machine report cannot disagree. |

### 2.6 surveys.<slug>.frame

| | |
|---|---|
| Definition | Frame and sign-convention notes for this survey, aggregated the same way as `conditioning`. |
| Obligation | optional |
| Occurrence | 0-1 |
| Type | array of [conditioning entry](#3-a-conditioning-entry) |
| Note | Covers derotation records, convention warnings and insufficient-data notes. |

### 2.7 surveys.<slug>.cache

| | |
|---|---|
| Definition | The incremental build cache's counters for this survey. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | object with required members `digest` (string), `hits`, `misses` and `writes` (integers, minimum 0) |
| Example | `{"digest": "1f4c8a9b2d3e", "hits": 34, "misses": 0, "writes": 0}` |
| Note | `digest` is the first twelve hex characters of the survey's `survey.yaml` digest, or an empty string for a raw build. The cache may only change build speed: the products are byte-identical whether they came from a hit or a fresh compute. Closed to further keys. |

### 2.8 surveys.<slug>.duration_seconds

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
