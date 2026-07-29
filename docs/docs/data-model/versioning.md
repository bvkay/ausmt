# Versioning and releases

AusMT versions survey packages and freezes citable corpus releases. Versioning exists so that a package
downloaded in future is scientifically identical to the version originally published, and so that a
citation can name what was actually used.

Versioning happens at three grains, and they are independent of each other:

| Grain | Identifier | What it names |
|---|---|---|
| Survey package | `MAJOR.MINOR.PATCH` in `survey.yaml` | the state of one survey's metadata and transfer functions |
| Corpus release | a release tag, for example `2026-Q3` | the state of the whole served corpus at one moment |
| Station transfer function | an integer version per station | which processing of one station's transfer function is current |

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

## Per-station transfer-function versions

A station's transfer function can be re-made: reprocessed with a better remote reference, longer runs
folded in, a newer code, different error floors. A TF version and its processing parameters are one
structure, because the parameters are what changed between versions.

### The current file stays where it is

`transfer_functions/edi/<file>.edi` is the one served source per station. A station with one version
carries no version record, and its package has exactly the shape a single-version package has always
had.

### Superseded files

When a reprocessed transfer function replaces a current one, the old file moves to
`transfer_functions/edi/superseded/<file>@v<N>.edi`. Git history preserves the bytes regardless; the
explicit directory means the build never has to read git history, and a curator sees the lineage in a
file listing.

### The version record

`tf_versions` in `survey.yaml` carries one entry per station that holds more than one version.

```yaml
tf_versions:
  - station: NF01
    versions:
      - version: 2                      # current
        date: 2027-03-01                # when this processing was adopted
        note: "reprocessed with SA remote pair, longer runs"
        processing:
          software: "BIRRP 5.3.2"
          algorithm: robust_remote_reference
          remote_site: "NF-REF2"
          error_floor: "5% Z, absolute tipper 0.02"
          distortion_treatment: none
          params_file: NF01_v2.cfg
      - version: 1
        date: 2013-11-20
        note: "original AusLAMP processing"
        superseded: true
        processing:
          software: "BIRRP 5.2"
```

The rules are fail-closed, like the credit vocabulary:

- `version` values are integers, unique within a station, with exactly one not marked `superseded`.
- A version row without a `processing` block is a validator warning rather than a failure, and
  `processing.software` is the minimum expected.
- The keys inside `processing` are an open set with reserved names: `software`, `algorithm`,
  `remote_site`, `error_floor`, `distortion_treatment`, `params_file`, `instrument`, `acquired_by`,
  `acquired_date`.
- An absent `tf_versions` entry for a station means version 1, current.
- A version withdrawn for cause carries `withdrawn: true` with a stated reason. The record stays and
  the bytes drop, because a withdrawal is provenance rather than deletion.

### Processing sidecars

`transfer_functions/processing/<station>_v<N>.<ext>` holds the parameter file itself: a BIRRP
configuration, an EMTF parameter file, a LEMI processing log. It is referenced from `params_file` and
served through the download manifest like any other artifact, with its size, digest and the survey's
licence. Sidecars are equally welcome for single-version stations.

### What is served

The portal experience is current-version only. `tf.json`, the plots, the canonical EMTF XML and the
MTH5 bundle all carry the current version, and the round-trip and convention gates run on it.

The download manifest carries rows for superseded transfer functions and for processing sidecars, with
`tf_version` and, where it applies, `superseded: true`. They are fetchable, integrity-checked and
embargo-gated identically to everything else.

`station.json` carries the current version number and the version count, and extends its processing
block from the version record. The build report counts the stations that hold more than one version, so
a rebuild states what it served. The station entries in MTCAT gain the same two keys.

A release freezes whatever is current at cut time. Superseded artifacts do not ride into the release
bundle set: a release is the served state.

### Curation

A reprocessed transfer function is curated in three steps. The curator moves the old file into
`superseded/`, drops the new file in place, and writes the `tf_versions` record with its processing
block. The validator checks the rules above. The next rebuild serves the new current version, the survey
drawer shows it with the previous version one click away, and the manifest keeps the old bytes
fetchable.

A wholesale survey reprocessing is N explicit station records, written by a small tool rather than
inferred.

Every station in the corpus holds one transfer function today, so no survey package carries a
`tf_versions` record.
