# Releases tier

A release is a frozen copy of one build's catalogue surface plus every per-survey bundle that build
served, cut into `/data/releases/<tag>/` with a provenance document and a DataCite record beside it. It
exists so a paper can cite a specific state of the corpus: build directories are pruned and the current
build moves on every rebuild, so neither is a citable target.

```text
/data/releases/releases.json          the newest-first index
/data/releases/<tag>/release.json     that release's own record
/data/releases/<tag>/datacite.json    a DataCite record, prepared and not submitted
/data/releases/<tag>/mtcat.json       the frozen catalogue surface
/data/releases/<tag>/surveys.json     the frozen survey metadata
/data/releases/<tag>/manifest.json    the frozen download manifest
/data/releases/<tag>/bundles/         the frozen artifacts
```

The fetch semantics, including what a `404` on the index means, are in the
[data reference](../interoperability/api-reference.md#the-releases-tier).

## Normative artifact

| | |
|---|---|
| Normative artifact | `engine/extract/cut_release.py` |
| Served location | `/data/releases/` |
| Index version | 1.0, declared in `releases.json` as `schema` and `version` |
| DataCite profile | DataCite Metadata Schema 4, `http://datacite.org/schema/kernel-4` |

There is no JSON Schema artifact for these documents. Where this page and the tool disagree, the tool is
right.

## Properties of a cut

A release directory is immutable. An existing tag is never overwritten; re-running a cut on a tag that
exists is a hard error. The one path allowed to touch an existing tag stamps a minted DOI into
`release.json` and regenerates `datacite.json`, and re-copies no data.

Every copied bundle is re-hashed from the bytes that landed in the release directory and checked against
the download manifest's own SHA-256 claim. Any mismatch, and any repository-tier bundle the manifest
claims but the build does not hold, fails the cut and leaves nothing behind. A citation has to resolve
to bytes that match their recorded digests.

A tag is a single safe path component, matching `^[A-Za-z0-9][A-Za-z0-9._-]*$`, because it becomes both
a directory name and a git tag suffix.

The tool mints nothing. It has no network access, no DataCite credentials and no git write path. It
prints the corpus tag commands for an operator to run.

---

## 1 releases.json

The newest-first index of every cut release.

```json
{
 "schema": "ausmt-releases",
 "version": "1.0",
 "updated_at": "2026-08-01T02:14:00Z",
 "releases": [
  {"tag": "2026-Q3", "cut": "2026-08-01T02:14:00Z", "doi": null,
   "note": "first citable snapshot", "build_id": "0d705ea…-2a6624e-2026-07-27T08:08:07.007756+00:00",
   "n_surveys": 21, "n_stations": 1418, "path": "releases/2026-Q3/"}
 ]
}
```

### 1.1 schema

| | |
|---|---|
| Definition | Names the index format. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Allowed values | `ausmt-releases` |

### 1.2 version

| | |
|---|---|
| Definition | Version of the index format. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Example | `"1.0"` |

### 1.3 updated_at

| | |
|---|---|
| Definition | When the index was last written. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string or null |
| Format | ISO 8601 with a `Z` suffix |
| Default | `null` in a freshly initialised index with no releases |

### 1.4 releases[]

| | |
|---|---|
| Definition | One row per cut release, newest first. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | array of object |
| Default | `[]` before the first cut |
| Note | Sorted by cut time descending, with the tag as the tie-break, so two cuts inside the same second still order deterministically. Sorting rather than prepending keeps the order true after a hand edit or an out-of-order cut. |

Row members:

| Member | Type | Definition |
|---|---|---|
| `tag` | string | the release tag, which is also its directory name |
| `cut` | string or null | wall-clock time the release was frozen |
| `doi` | string or null | the minted DOI, or null until one exists |
| `note` | string or null | the one-line note the cut carried |
| `build_id` | string or null | identity of the build the release was frozen from |
| `n_surveys` | integer or null | surveys in the frozen catalogue |
| `n_stations` | integer or null | stations in the frozen catalogue |
| `path` | string | `releases/<tag>/`, relative to the data root |

The index row's `cut` is a scalar. The release document's own `cut_at` is a two-timestamp object. The
names are kept distinct so no consumer meets one key carrying two different types across the two files.

---

## 2 release.json

One release's own record, written inside its directory.

```json
{
 "tag": "2026-Q3",
 "cut_at": {"build_generated": "2026-07-27T08:08:07.007756+00:00", "cut": "2026-08-01T02:14:00Z"},
 "build_id": "0d705ea…-2a6624e-2026-07-27T08:08:07.007756+00:00",
 "engine_commit": "0d705eaaa22ded1564f6d36e349ef5d5761b3e69",
 "source_commit": "2a6624e",
 "n_surveys": 21,
 "n_stations": 1418,
 "files": [{"path": "mtcat.json", "size": 275587, "sha256": "0d70…"}],
 "doi": null,
 "note": "first citable snapshot"
}
```

### 2.1 tag

| | |
|---|---|
| Definition | The release tag. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Format | `^[A-Za-z0-9][A-Za-z0-9._-]*$` |
| Example | `"2026-Q3"` |

### 2.2 cut_at

| | |
|---|---|
| Definition | Both clocks the snapshot depends on. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | object with members `build_generated` and `cut` |
| Note | `build_generated` is when the bytes were built, taken from the build's own identity document. `cut` is when they were frozen. They differ whenever a release is cut some time after the rebuild, which is the normal case. |

### 2.3 build_id

| | |
|---|---|
| Definition | Identity of the build this release was frozen from. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string |
| Note | A build with no `build_id` fails the cut. A snapshot whose commits cannot be named is not citable provenance. |

### 2.4 engine_commit

| | |
|---|---|
| Definition | Engine commit the frozen build ran at. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string or null |

### 2.5 source_commit

| | |
|---|---|
| Definition | Survey-repository commit the frozen build read. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string or null |
| Note | The commit an operator tags in the survey repository as `ausmt-release-<tag>`. `null` for a raw or non-git build, in which case the cut prints that the tag step was skipped. |

### 2.6 n_surveys

| | |
|---|---|
| Definition | Surveys in the frozen catalogue. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | integer |
| Note | Counted off the copied `mtcat.json`, so the release record can never disagree with the catalogue shipped beside it. |

### 2.7 n_stations

| | |
|---|---|
| Definition | Stations in the frozen catalogue. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | integer |

### 2.8 files[]

| | |
|---|---|
| Definition | Every file frozen into the release directory, with its integrity. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | array of object with members `path`, `size` and `sha256` |
| Example | `{"path": "bundles/vulcan-2022-edi.zip", "size": 1841022, "sha256": "9c31…"}` |
| Note | `path` is relative to the release directory. `sha256` is recomputed from the bytes that landed there, not copied from the manifest. |

### 2.9 doi

| | |
|---|---|
| Definition | The minted DOI for this release. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string or null |
| Default | `null` until a DOI is minted and stamped back in |
| Note | Render a null as plain text. Nothing in the tooling mints a DOI, so a resolver link built from a null would be dead. |

### 2.10 note

| | |
|---|---|
| Definition | The one-line note the cut carried. |
| Obligation | mandatory |
| Occurrence | 1 |
| Type | string or null |

---

## 3 datacite.json

A DataCite Metadata Schema 4 record for one release, in the shape the DataCite REST API accepts under
`attributes`, ready to submit unchanged. It is prepared and never submitted.

| Member | Obligation | Type | Definition |
|---|---|---|---|
| `schemaVersion` | mandatory | string | `http://datacite.org/schema/kernel-4` |
| `titles` | mandatory | array | one title, `AusMT Data Portal, Release <tag>` |
| `publisher` | mandatory | string | `AuScope` |
| `publicationYear` | mandatory | integer or null | the year of the cut |
| `version` | mandatory | string | the release tag |
| `types` | mandatory | object | `{"resourceTypeGeneral": "Dataset", "resourceType": "Catalogue snapshot"}` |
| `creators` | mandatory | array | portal-level attribution: `AuScope` and `AusMT contributors`, both organisational |
| `contributors` | mandatory | array | one row, AusMT as `HostingInstitution` |
| `dates` | mandatory | array | one `Created` date, the cut time |
| `rightsList` | mandatory | array | one row per distinct data licence in the frozen manifest, plus the catalogue metadata licence |
| `sizes` | mandatory | array | `["<n> files", "<n> bytes"]` |
| `formats` | mandatory | array | the distinct artifact formats in the frozen manifest |
| `relatedIdentifiers` | mandatory | array | one `HasPart` row per survey DOI in the frozen catalogue, plus an `IsNewVersionOf` row when a prior release has a DOI |
| `descriptions` | mandatory | array | an `Abstract`, an `Other` licensing note, and a `TechnicalInfo` entry when the cut carried a note |
| `doi` | optional | string | present only once a DOI is minted |
| `identifiers` | optional | array | present only once a DOI is minted |

### Notes

A release is the aggregate work of the corpus, not of any one survey's authors. Each survey keeps its
own creators and its own DOI in the frozen catalogue, and the release's `relatedIdentifiers` point at
them.

`rightsList` is derived from the licences actually present in the frozen download manifest, so it states
what the corpus is licensed under at that cut. A row carries an SPDX identifier and scheme only for a
licence id AusMT holds a deed URL for, so a non-SPDX corpus value is never dressed up as an SPDX id it
is not.

`IsNewVersionOf` is emitted only against a real prior DOI, chaining past any number of releases that
have not been minted. A null related identifier is invalid DataCite, and a placeholder would be a claim
about an identifier that does not exist.

While `release.json`'s `doi` is null the DataCite record carries no `doi` and no `identifiers` key at
all. Both appear together once a DOI is stamped in. Everything else in the record is final on the day of
the cut.
