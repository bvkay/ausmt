# Versioning and releases

Versioning exists so that a package downloaded in future is scientifically identical to the version
originally published, and so that a citation can name what was used. It happens at two independent
grains; there is no third, because a station's transfer function has no version of its own.

| Grain | Identifier | What it names |
|---|---|---|
| Survey package | `MAJOR.MINOR.PATCH` in `survey.yaml` | the state of one survey's metadata and transfer functions |
| Corpus release | a release tag, for example `2026-Q3` | the state of the whole served corpus at one moment |

## Survey package versions

| Level | Meaning | Example |
|---|---|---|
| PATCH | metadata-only corrections | `1.0.1` |
| MINOR | additions, such as new stations | `1.1.0` |
| MAJOR | reprocessed transfer functions | `2.0.0` |

The validator warns when `version` is missing or not shaped `MAJOR.MINOR.PATCH`, and when
`release_notes` entries are not `{version, date, note}` records. The curator metadata editor enforces a
monotonic bump with release notes on every published edit, so a change to a published survey cannot
land without its version moving and its note being written. The portal renders `release_notes` in the
survey drawer and uses the latest entry's date in the recently-added feed
([survey.yaml reference](../reference/survey-yaml.md#13-release-notes)). A published version is never
edited in place to mean something different; the history of a package is the git history of the survey
repository. Cite the version you used.

## Corpus releases

A release freezes one build's catalogue surface (`mtcat.json`, `surveys.json`, `manifest.json`) plus
every per-survey bundle into `/data/releases/<tag>/`, with a provenance document and a DataCite record
beside them and a newest-first index at `/data/releases/releases.json`. Build directories are pruned
and the current-build pointer is swapped on every rebuild, so neither is a citable target; a release
directory is immutable. The tooling mints no DOIs; it prepares a DataCite record, and a minted DOI is
stamped back into the release. The documents are in the [Releases tier reference](../reference/releases.md).

## Reprocessed transfer functions

A station's transfer function can be re-made. AusMT versions that at the survey grain as a MAJOR bump,
and the build serves the result one of two ways.

**Replacement in place.** The file under `transfer_functions/edi/` is replaced: one station id, one
served transfer function, and the previous bytes stay in the survey repository's git history.

**A distinct variant station record.** When a package hands the build two transfer functions for one
station id, the build keeps both. It appends a processing-variant tag, so the records are served as
`<station>.<variant>` with `ausmt_id` `au.<slug>.<station>.<variant>`, each with its own product path
and portal route. The tag is the part of the filename beyond the station id, lowercased and sanitised
(`MBV20_LemiGraph` beside `MBV20_Ohmega` gives `MBV20.lemigraph` and `MBV20.ohmega`), or a positional
`v1`, `v2` where the filename leaves nothing to use. The build records the physical site behind a
tagged record for the curator workbench, so a per-station coordinate override keys on the site. A variant tag is an identity, not a version: nothing marks one
current and the other superseded. Reprocessings in the corpus today arrive under their own station id
(the marker rides in the source file's `DATAID`, the `...r` and `..._BxReplaced` files), so no station
currently carries a variant tag.

No per-station version number exists anywhere: `survey.yaml` has no station-level version key, the
station product and the MTCAT station record carry no version field, and no manifest row carries a
version or supersession flag (the manifest and build-report row definitions are closed,
`additionalProperties: false`). What distinguishes one processing run from another is recorded in
[`processing`](../reference/survey-yaml.md#111-processing) in `survey.yaml` (survey-wide) and in each
station product's [`processing`](../reference/station-products.md#19-processing) block, read from the
source file's header.
