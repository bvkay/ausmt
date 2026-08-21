# Releases tier

A release is a frozen copy of one build's catalogue surface plus every per-survey bundle that build
served, cut into `/data/releases/<tag>/` with a provenance document and a DataCite record beside it. It
exists so a paper can cite a specific state of the corpus: build directories are pruned and the current
build moves on every rebuild, so neither is a citable target.

No release has been cut yet. `/data/releases/releases.json` returns `404` on the live site and the
portal's Releases page says so. This page documents a served-but-not-yet-populated tier: the layout
below is what `engine/extract/cut_release.py` writes, and `release.json` and `datacite.json` have no
JSON Schema artifact yet.

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

Where this page and the tool disagree, the tool is right.

## Properties of a cut

A release directory is immutable. An existing tag is never overwritten, and re-running a cut on a tag
that exists is a hard error. The one path allowed to touch an existing tag stamps a minted DOI into
`release.json` and regenerates `datacite.json`; it re-copies no data.

Every copied bundle is re-hashed from the bytes that landed in the release directory and checked against
the download manifest's own SHA-256 claim. Any mismatch, and any repository-tier bundle the manifest
claims but the build does not hold, fails the cut and leaves nothing behind. A tag is a single safe path
component, matching `^[A-Za-z0-9][A-Za-z0-9._-]*$`, because it becomes both a directory name and a git
tag suffix.

The tool mints nothing. It has no network access, no DataCite credentials and no git write path; it
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

| Member | Type | Definition |
|---|---|---|
| `schema` | string | always `ausmt-releases` |
| `version` | string | the index format version, `"1.0"` |
| `updated_at` | string or null | when the index was last written, ISO 8601 with a `Z` suffix; `null` in a freshly initialised index |
| `releases` | array | one row per cut release, newest first; `[]` before the first cut |

Rows are sorted by cut time descending with the tag as the tie-break, so two cuts inside the same second
still order deterministically, and the order stays true after a hand edit or an out-of-order cut.

| Row member | Type | Definition |
|---|---|---|
| `tag` | string | the release tag, which is also its directory name |
| `cut` | string or null | wall-clock time the release was frozen |
| `doi` | string or null | the minted DOI, or null until one exists |
| `note` | string or null | the one-line note the cut carried |
| `build_id` | string or null | identity of the build the release was frozen from |
| `n_surveys`, `n_stations` | integer or null | surveys and stations in the frozen catalogue |
| `path` | string | `releases/<tag>/`, relative to the data root |

The index row's `cut` is a scalar; the release document's own `cut_at` is a two-timestamp object. The
names are distinct so no consumer meets one key carrying two types across the two files.

---

## 2 release.json

One release's own record, written inside its directory. Every member is mandatory.

| Member | Type | Definition |
|---|---|---|
| `tag` | string | the release tag, `^[A-Za-z0-9][A-Za-z0-9._-]*$` |
| `cut_at` | object | `{build_generated, cut}`: when the bytes were built and when they were frozen, which differ whenever a release is cut some time after the rebuild |
| `build_id` | string | identity of the frozen build; a build with no `build_id` fails the cut, because a snapshot whose commits cannot be named is not citable provenance |
| `engine_commit` | string or null | engine commit the frozen build ran at |
| `source_commit` | string or null | survey-repository commit the frozen build read, the commit an operator tags as `ausmt-release-<tag>`; `null` for a raw or non-git build, in which case the cut prints that the tag step was skipped |
| `n_surveys`, `n_stations` | integer | counted off the copied `mtcat.json`, so the record cannot disagree with the catalogue shipped beside it |
| `files` | array | every file frozen into the release directory as `{path, size, sha256}`; `path` is relative to the release directory and `sha256` is recomputed from the bytes that landed there, not copied from the manifest |
| `doi` | string or null | `null` until a DOI is minted and stamped back in; render a null as plain text, because nothing in the tooling mints one and a resolver link built from it would be dead |
| `note` | string or null | the one-line note the cut carried |

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
| `doi`, `identifiers` | optional | string, array | present only once a DOI is minted; both appear together |

A release is the aggregate work of the corpus, not of any one survey's authors: each survey keeps its
own creators and its own DOI in the frozen catalogue, and `relatedIdentifiers` points at them.
`rightsList` is derived from the licences present in the frozen manifest, and a row carries an SPDX
identifier and scheme only for a licence id AusMT holds a deed URL for, so a non-SPDX value is never
dressed up as an SPDX id. `IsNewVersionOf` is emitted only against a real prior DOI, chaining past any
number of unminted releases, because a null related identifier is invalid DataCite and a placeholder
would claim an identifier that does not exist. Everything other than `doi` and `identifiers` is final on
the day of the cut.
