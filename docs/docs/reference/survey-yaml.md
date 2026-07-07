# survey.yaml Reference

## Overview

`survey.yaml` is the authoritative survey-level metadata document within a survey package.
Every survey package must contain exactly one `survey.yaml`.

It is the single source of survey metadata for the whole system: the validator checks it, the
engine reads it to build the portal's data files and the MTCAT discovery
document, and the portal renders it. There is no hard-coded survey metadata anywhere else.

This page documents the **schema 0.2 (structured)** form, which the `_template`, the worked
`_example`, and the Add Survey page all use. The older **0.1 (flat)** form is still accepted for
backward compatibility (see [Backward compatibility](#backward-compatibility)).

## Required fields

The validator (`_validation/validate_survey.py`) treats a survey as publishable only when these are
present and not a placeholder (`TODO`/`TBD`):

| Field | Notes |
|---|---|
| `slug` | **Must equal the package folder name.** Becomes the stable id root `au.<slug>.<station>`. |
| `project_name` (or `name`) | Human-readable survey/project name. Either key satisfies the requirement. |
| `country` | Drives the Country → Organisation → Survey discovery hierarchy. |
| `organisation` | The `.name` of the organisation (a string is also accepted — see below). |
| `access` | The `.level` (`open` \| `metadata_only` \| `embargoed`). |
| `license` | A real licence (e.g. `CC-BY-4.0`); `TBD…` is a warning, never publish with it. |

Everything else is optional but strongly recommended — richer metadata means better discovery,
citation and reproducibility.

## Field reference

```yaml
schema_version: "0.2"                 # schema generation; "0.1" (flat) is still accepted

slug: my-survey-2026                  # REQUIRED — must equal the folder name
project_name: "Survey Name (Org)"     # REQUIRED — human-readable name
name: "Survey Name (Org)"             # backward-compatible alias of project_name
version: "1.0.0"                      # survey-package semver (NOT the schema version)
country: Australia                    # REQUIRED
region: "South Australia"            # optional — finer geographic facet than country (survey-driven;
                                      # surfaced as catalogue r[9]; replaces the old AU point-in-box state)

organisation:                         # REQUIRED (.name). May also be a bare string.
  name: "University of Example"
  ror: null                           # ROR URL, e.g. https://ror.org/00892tw58

lead_investigator:                    # or principal_investigators: [ {name, orcid}, … ]
  name: "Given Family"
  orcid: null                         # e.g. 0000-0002-1825-0097

abstract: >                           # one short paragraph
  Free text describing the survey.

geographic_extent: { west: 0.0, east: 0.0, south: 0.0, north: 0.0, datum: WGS84 }

data_types: [BBMT]                    # all that apply: AMT | BBMT | LPMT | GDS
data_type: BBMT                       # primary, backward-compatible single value

identifiers:
  dataset_doi: null                   # dataset DOI — minted externally (e.g. Zenodo/institutional) by the submitter before publication; AusMT does not mint DOIs itself (integrated minting via ARDC is planned, not implemented)
  survey_pid: null                    # AuScope Instrument Registry survey handle
  related_publication: null
  related_publication_doi: null
  project_raid: null                  # https://raid.org/… RAiD for the project

funding:                              # repeatable
  - organisation: "Funding body"
    organisation_ror: null
    grant_id: null
    grant_title: null
    funding_doi: null

license: "CC-BY-4.0"                  # REQUIRED
access:                               # REQUIRED (.level)
  level: open                         # open | metadata_only | embargoed
  embargo_until: null
  contact: null

time_series:                          # pointers ONLY — AusMT never hosts time series
  collection_pid: null                # e.g. an NCI collection DOI / handle
  levels_available: []                # e.g. [raw_packed, level0, level1]

publications: []                      # list of {author, year, title, journal, doi};
                                      # a bare DOI string per entry is also accepted

processing:                           # technical provenance
  software: "BIRRP / Aurora / EMTF / LEMI MT / Phoenix EMpower"
  version: null
  remote_reference: "unknown"         # yes | no | unknown
  notes: null

instruments:                          # repeatable
  - manufacturer: "Phoenix"
    model: "MTU-5C"
    pid: null                         # optional — AuScope Instrument Registry PID (URL or handle/DOI)

collection:                           # optional — programme membership (rolls up in MTCAT)
  id: auslamp                         # lowercase-hyphenated
  title: AusLAMP
  type: programme
  status: completed                   # active | completed | archived

release_notes:                        # optional changelog (one entry per version)
  - { version: "1.0.0", date: "2026-01-01", note: "Initial AusMT publication." }

coordinate_resolution:                # optional — resolves the DMS sign-bug ambiguity
  dms_sign: info                      # info | head — which source is ground truth for flagged stations
  basis: "INFO decimal matches field GPS; HEAD latitude is floored DMS"

care:                                 # governance facts only; never sensitive detail
  traditional_owner_acknowledgement: null
  land_access: { permission_obtained: unknown, agreement_type: null }
  restrictions_requested: false
```

### `coordinate_resolution`

Some processing tools write a corrupted DMS coordinate into the EDI `HEAD` block while the correct
decimal value survives in the `INFO` block (a sign/floor bug, common for negative latitudes). The
build flags such stations `dms_sign_ambiguous` and, by default, keeps the EDI-standard `HEAD` value.
A curator who knows the ground truth can declare `coordinate_resolution: { dms_sign: info }`, and the
build will substitute the `INFO` coordinate and record the resolution and its `basis`. With no
declaration the coordinate stays at `HEAD` and remains flagged for review.

### `instruments[].pid`

Each `instruments` entry may carry an optional `pid` — a persistent identifier for the instrument
**system** (the AuScope Instrument Registry URL or handle/DOI), e.g.
`https://instruments.auscope.org.au/system/LEMI-423-007` or `10.25914/<id>`. It is additive and
optional: omit it (or leave it `null`) and nothing changes — `manufacturer`/`model` still render as
the instrument line. When a `pid` is present, the portal renders it as a clickable link in the survey
drawer (through the same URL-shape guard as the other PID links, so a malformed value renders inert).
The validator format-checks it as a **WARNING-only** curator hint (no registry lookup), matching the
ROR/RAiD checks. `schema_version` is unchanged — old validators tolerate the extra key.

## Backward compatibility

The 0.1 (flat) form is still read by both the validator and the engine. The parsers accept
either key in each of these pairs, so legacy packages need no migration:

| 0.2 (structured) | 0.1 (flat) |
|---|---|
| `project_name` | `name` |
| `organisation: { name, ror }` | `organisation: "Name"` (string) |
| `lead_investigator: { name }` | `principal_investigators: [ { name } ]` |
| `data_types: [ … ]` | `data_type: …` |
| `funding: [ … ]` | `funders: [ … ]` |
| `processing: { software }` | `provenance: { processing_software }` |

New packages should use 0.2.

## Relationship to the survey package

`survey.yaml` describes the survey package as a whole. Station-level information (coordinates,
deployment dates, sensor orientations) comes from the transfer-function files themselves, not from
`survey.yaml`.

## Principle

If the survey package is the scientific object, `survey.yaml` is its primary metadata record.
