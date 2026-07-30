# Versioning and releases

AusMT versions survey packages and freezes citable corpus releases. Versioning exists so that a package
downloaded in future is scientifically identical to the version originally published, and so that a
citation can name what was actually used.

Versioning happens at two grains, and they are independent of each other:

| Grain | Identifier | What it names |
|---|---|---|
| Survey package | `MAJOR.MINOR.PATCH` in `survey.yaml` | the state of one survey's metadata and transfer functions |
| Corpus release | a release tag, for example `2026-Q3` | the state of the whole served corpus at one moment |

There is no third grain. A station's transfer function has no version of its own, and
[Reprocessed transfer functions](#reprocessed-transfer-functions) states what that means for a curator.

## Survey package versions

A survey package carries a semantic version.

| Level | Meaning | Example |
|---|---|---|
| PATCH | metadata-only corrections | `1.0.1` |
| MINOR | additions, such as new stations | `1.1.0` |
| MAJOR | reprocessed transfer functions | `2.0.0` |

The validator warns when `version` is missing or is not shaped `MAJOR.MINOR.PATCH`, and when
`release_notes` entries are not `{version, date, note}` records. The curator metadata editor enforces a
monotonic bump with release notes on every published edit, and commits through the publish path, so a
change to a published survey cannot land without its version moving and its note being written.

The portal renders `release_notes` in the survey drawer and uses the latest entry's date in the
recently-added feed. The fields are specified in the
[survey.yaml reference](../reference/survey-yaml.md#13-release-notes).

A published version is never edited in place to mean something different: a correction takes a new
version. The history of a package is the git history of the survey repository, and each build
reconstructs the current state from it. Cite the version you used.

## Corpus releases

A release freezes one build's catalogue surface (`mtcat.json`, `surveys.json`, `manifest.json`) plus
every per-survey bundle into `/data/releases/<tag>/`, writes a provenance document and a DataCite record
beside them, and updates a newest-first index at `/data/releases/releases.json`.

Releases exist because the current build moves. Build directories are pruned and the pointer to the
current build is swapped on every rebuild, so neither is a citable target. A release directory is
immutable: an existing tag is never overwritten, every copied bundle is re-hashed and checked against
the manifest's own digest claim, and any mismatch fails the cut and leaves nothing behind.

The release tooling mints no DOIs. It prepares a DataCite record so that a release can be submitted as
it stands and the minted DOI stamped back into the release that already exists. Until a DOI is minted a
release's `doi` is `null`, and a consumer renders that as plain text rather than as a link.

The documents and their fields are in the [Releases tier reference](../reference/releases.md).

## Reprocessed transfer functions

A station's transfer function can be re-made: reprocessed with a better remote reference, longer runs
folded in, a newer code, different error floors. AusMT versions that at the survey grain. A reprocessing
is a MAJOR bump of the survey package, carrying the release note the publish path already requires; the
station's file under `transfer_functions/edi/` is replaced in place, and the previous bytes stay in the
git history of the survey repository.

No per-station version number exists anywhere in the system. `survey.yaml` has no station-level version
key, the station product and the MTCAT station record carry no version field, and no manifest row carries
a version or a supersession flag. The manifest and build-report row definitions are closed
(`additionalProperties: false`), so serving a second version of one station's transfer function means
changing those schemas and the build, not adding a curation convention on top of them.

What distinguishes one processing run from another is recorded in two places, both survey-current:
[`processing`](../reference/survey-yaml.md#111-processing) in `survey.yaml`, which is survey-wide, and
each station product's [`processing`](../reference/station-products.md#19-processing) block, read from
the source file's own header. No station in the corpus carries a second transfer function.
