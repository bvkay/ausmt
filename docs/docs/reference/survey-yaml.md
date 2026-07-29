# survey.yaml Reference

`survey.yaml` is the survey-level metadata document inside a survey package. Every package
contains exactly one, and it is the single source of survey metadata for the whole system: the
validator checks it, the engine reads it to build the portal's data files and the MTCAT discovery
document, and the portal renders it. No survey metadata is hard-coded anywhere else.

This page describes the current model, which is what `ausmt-surveys/_template/survey.yaml` and the
worked `_example` ship. Three ratified changes reshaped it during July 2026, and each is covered
below: the contributor credit model (`creators[]` and `contributors[]`), identifier consolidation
(one typed `related_identifiers[]` list), and the survey-level coordinate-access policy
(`access.coordinates`). Fields the validator now treats as retired are listed under
[Retired fields](#retired-fields); they still parse, so no package needs migrating to keep
publishing.

## Schema versions

`schema_version` is validated. Two values are known:

| Value | Meaning |
|---|---|
| `"0.2"` | the structured form. Use this unless you set an `attribution` block. |
| `"0.3"` | 0.2 plus the C46 rights fields (`attribution`). Bump to `"0.3"` when you fill any of them. |

Anything else warns. The older flat 0.1 spelling is no longer a recognised `schema_version`, but
the flat key aliases it used are still read by both the validator and the engine, so a legacy
package keeps working. See [Legacy key aliases](#legacy-key-aliases).

## Required fields

The validator fails a package when any of these is missing or left as `TODO`/`TBD`:

| Field | Notes |
|---|---|
| `slug` | Must equal the package folder name, and must match `^[a-z0-9]+(-[a-z0-9]+)*$`. It becomes the id root `au.<slug>.<station>`. |
| `project_name` (or `name`) | Human-readable survey name. Either key satisfies the check. |
| `country` | Drives the Country, Organisation, Survey discovery hierarchy. |
| `organisation` | The `.name`. A bare string is accepted too. |
| `access` | The `.level`, one of `open`, `metadata_only`, `embargoed`. An out-of-enum value fails. |
| `license` | A recognised licence id. A missing licence fails; `TBD…` warns, and `--strict` turns every warning into a failure at the publication gate. |

Everything else is optional. Richer metadata means better discovery, citation and reuse, so most
of the optional blocks are worth filling.

## Field reference

```yaml
schema_version: "0.2"                 # "0.2" or "0.3" (0.3 adds the attribution block)

slug: my-survey-2026                  # REQUIRED, must equal the folder name
project_name: "Survey Name (Org)"     # REQUIRED, human-readable name
name: "Survey Name (Org)"             # accepted alias of project_name
version: "1.0.0"                      # survey-package semver, not the schema version
country: Australia                    # REQUIRED
region: "South Australia"             # optional, a finer geographic facet than country

organisation:                         # REQUIRED (.name). A bare string also works.
  name: "University of Example"
  ror: null                           # ROR URL, e.g. https://ror.org/00892tw58

creators:                             # optional, ORDERED: who the citation names, in author order
  - name: "Family, Given"
    name_type: person                 # person | organisation (fail-closed)
    orcid: null                       # people only
  - name: "Geological Survey of Example"
    name_type: organisation
    ror: null                         # organisations only

contributors:                         # optional, repeatable: who did what
  - name: "Family, Given"
    name_type: person
    role: ProjectLeader               # see the role vocabulary below (fail-closed)
    orcid: null

abstract: >                           # one short paragraph
  Free text describing the survey.

geographic_extent: { west: 0.0, east: 0.0, south: 0.0, north: 0.0, datum: WGS84 }

data_types: [BBMT]                    # all that apply: AMT | BBMT | LPMT | GDS
data_type: BBMT                       # primary single value, kept for back-compat

identifiers:
  survey_pid: null                    # AuScope Instrument Registry survey handle
  instrument_pid: null                # the ONE survey/platform instrument PID (PIDINST)
  project_raid: null                  # https://raid.org/… RAiD for the project

related_identifiers:                  # optional, repeatable: the single carrier for dataset-level
  - identifier: "10.25914/…"          #   DOIs, handles and URLs AusMT does not own
    identifier_type: DOI              # DOI | Handle | URL | RAiD (fail-closed)
    identifies: raw_packed            # the data level it points at (fail-closed, see below)
    custodian: "NCI"                  # free text: who holds the identified record
    # relation: IsDerivedFrom         # optional; normally derived from `identifies`
    # title / licence / retrieved / statement / profile  are optional acquisition keys,
    # used when this identifier is an upstream dataset AusMT obtained

funding:                              # repeatable
  - organisation: "Funding body"
    organisation_ror: null
    grant_id: null
    grant_title: null
    funding_doi: null

license: "CC-BY-4.0"                  # REQUIRED
access:                               # REQUIRED (.level)
  level: open                         # open | metadata_only | embargoed
  embargo_until: null                 # ISO YYYY-MM-DD when level is embargoed
  contact: null
  coordinates: exact                  # optional: exact | generalised | withheld. Absent means exact.
  coordinate_overrides: {}            # optional {STATION_ID: policy} map, for individual sites

attribution:                          # optional, schema 0.3 only: rights of THIS AusMT release
  custodian: "Custodian of record"    #   may differ from organisation.name
  custodian_ror: null
  statement: null                     # verbatim wording where the custodian prescribes one
  changes_made: true                  # CC-BY 3(a) flag
  changes_summary: null
  declared_by: null
  declared_date: null                 # ISO YYYY-MM-DD

time_series:                          # pointers ONLY. AusMT never hosts time series.
  levels_available: []                # e.g. [raw_packed, level0, level1]

nci_base: null                        # optional: one NCI THREDDS fileServer directory the survey's
                                      # TF files already sit flat under. Set it and downloads point
                                      # at NCI instead of AusMT-served bytes.

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

collection:                           # optional programme membership, rolled up in MTCAT
  id: auslamp                         # lowercase-hyphenated
  title: AusLAMP
  type: programme                     # programme | release | institutional | other
  status: completed                   # active | completed | archived
  start_year: 2013
  last_updated: "2026-01-01"
  description: >-
    One paragraph shown on the collection card and page.

release_notes:                        # optional changelog, one entry per published version
  - { version: "1.0.0", date: "2026-01-01", note: "Initial AusMT publication." }

coordinate_resolution:                # optional, resolves the DMS sign-bug ambiguity
  dms_sign: info                      # info | head, which source is ground truth
  basis: "INFO decimal matches field GPS; HEAD latitude is floored DMS"

care:                                 # governance facts only, never sensitive detail
  traditional_owner_acknowledgement: null
  land_access: { permission_obtained: unknown, agreement_type: null }
  restrictions_requested: false
```

## Credit: `creators[]` and `contributors[]`

Two lists carry credit, and they answer different questions.

`creators[]` is who the citation names. It is an ordered editorial list, and the order is the
author order used by the APA, BibTeX and RIS exports and by the attribution line written into the
canonical EMTF XML. Omit the block and the citation falls back to an honest organisation-and-year
synthesis, which is the right answer for most state-survey data.

`contributors[]` is who did what. It is repeatable, and each row states a `name`, a `name_type`
and a `role`. The same person can appear in several rows. This is where the real release chain is
recorded: a state survey that released the data is a `Distributor`, a mining company that paid for
it is a `Sponsor`, a company that held it through an embargo is a `RightsHolder`, and a field
contractor is usually an organisation acting as `DataCollector`.

Both lists share a row shape:

| Key | Applies to | Notes |
|---|---|---|
| `name` | both | the name as it should be shown |
| `name_type` | both | `person` or `organisation`. Fail-closed. |
| `role` | contributors | one of the roles below. Fail-closed. |
| `orcid` | people | optional, format-checked as a warning |
| `ror` | organisations | optional, format-checked as a warning |

The role vocabulary is the DataCite `contributorType` subset ratified for real Australian release
chains, in the order the editor presents it:

`ProjectLeader`, `ProjectMember`, `DataCollector`, `ContactPerson`, `DataCurator`, `Sponsor`,
`RightsHolder`, `Distributor`.

An out-of-vocabulary `name_type` or `role` is a hard failure. Getting one wrong would publish a
false statement about who did what, so the validator blocks rather than ships it. Unknown keys in
a row warn.

The reasoning behind the two-list split is in
[Why the credit model has two lists](../rationale/credit-model.md).

## Identifiers by data level

`related_identifiers[]` is the one place dataset-level DOIs, handles and URLs are recorded. Each
row is a typed pointer to a record AusMT does not own.

`identifies` states what the identifier points at, using the NCI Table 1 data-level terms. The
vocabulary is ordered and fail-closed:

| `identifies` | What it means | Derived relation |
|---|---|---|
| `collection` | the parent record, for example an NCI parent collection | `IsPartOf` |
| `raw_packed` | raw or packed time series | `IsDerivedFrom` |
| `level0` | edited time series | `IsDerivedFrom` |
| `level1` | transformed time series | `IsDerivedFrom` |
| `level2` | derived frequency-domain processed data (EDI/TF) | `IsVariantFormOf` |
| `level3` | models | `IsSourceOf` |
| `entire` | one record covering all levels, such as a GA eCAT record or a state landing page | `IsVariantFormOf` |

The DataCite `relation` is derived from the level, so curators state the level and the relation
follows. A hand-edited file may still set `relation` explicitly. When both are present and they
disagree, the validator warns and the explicit value stands.

`identifier_type` is one of `DOI`, `Handle`, `URL`, `RAiD`, also fail-closed. A state-survey
landing page with no DOI belongs here as a `URL` row with `identifies: entire`.

When the identifier is an upstream dataset AusMT obtained rather than merely relates to, the row
may also carry `title`, `licence` (as obtained), `retrieved`, `statement`, `profile` and
`custodian`. Those keys replace the retired `sources[]` list.

The reasoning is in [Why identifiers carry a data level](../rationale/identifiers-by-level.md).

## `access.coordinates`

`access.coordinates` is the survey-level policy for how station coordinates are served:

- `exact` serves the true position. This is the default when the key is absent.
- `generalised` rounds latitude and longitude to 0.1 degrees, roughly 11 km.
- `withheld` serves no position. The station keeps its catalogue row and its response curves still
  serve; it simply has no coordinate. The survey's position then comes from the curator-declared
  `geographic_extent`, and a survey with no declared extent shows no position at all.

`access.coordinate_overrides` is an optional `{STATION_ID: policy}` map for individual sites. The
key is the physical station id, so an override covers every processing variant of that site. The
engine validates the keys against the real parsed station ids before it emits any of the survey's
bytes, and an id that matches nothing fails the survey build.

The engine applies the policy at one seam, before every emitter, so nothing downstream can leak a
finer position. A station whose coordinates are not exact is also excluded from byte distribution,
because an EDI header carries the true position. An out-of-enum value fails the build rather than
falling back to `exact`.

This is a distinct concern from `coordinate_resolution` below, which is a data-quality correction,
not an access control. See [Why coordinates have an access policy](../rationale/coordinate-access.md).

### `coordinate_resolution`

Some processing tools write a corrupted DMS coordinate into the EDI `HEAD` block while the correct
decimal value survives in `INFO`. It is a sign or floor bug, and it is common for negative
latitudes. The build flags such stations `dms_sign_ambiguous` and keeps the EDI-standard `HEAD`
value by default. A curator who knows the ground truth can set
`coordinate_resolution: { dms_sign: info }`, and the build substitutes the `INFO` coordinate and
records the resolution with its `basis`. With no declaration the coordinate stays at `HEAD` and
stays flagged for review.

### `identifiers.instrument_pid`

One survey-level or platform-level persistent identifier for the instrument system, for example
`https://instruments.auscope.org.au/system/LEMI-423-007` or a bare `10.82388/<id>`. The portal
renders it as a link in the survey drawer, through the same URL-shape guard as the other PID
links, so a malformed value renders inert. The validator format-checks it as a warning only and
performs no registry lookup, matching the ROR and RAiD checks.

## Retired fields

Five of these keys are still read as fallbacks (`lead_investigator`, `principal_investigators`,
`identifiers.dataset_doi`, `time_series.collection_pid`, `sources[]`), so an un-migrated package
publishes as before. The three `identifiers.*` orphans below were read by nothing and are simply
dropped. Each key raises a deprecation warning when it carries a real value, and the migration
scripts live in `ausmt-surveys/_tools/`. `instruments[].pid` is the exception on the script side.
It is retired from the editor and the validator warns on it, but no script rewrites it, so a curator
holding a real value moves it by hand. No corpus survey carries one today, so nothing is outstanding.

| Retired key | Replaced by | Migration |
|---|---|---|
| `lead_investigator` | a `contributors[]` row with `role: ProjectLeader` | `migrate_credit.py` |
| `principal_investigators` | `creators[]` | `migrate_credit.py` |
| `identifiers.dataset_doi` | a `related_identifiers[]` row | `migrate_identifiers.py` |
| `time_series.collection_pid` | a `related_identifiers[]` row; NCI-custodian rows gain `identifies: raw_packed` | `migrate_identifiers.py` moves the value; `migrate_identifies.py` then infers the `identifies` level for NCI rows and lists any other custodian for curator fill-in |
| `identifiers.related_publication_doi` | `publications[]` | `migrate_identifiers.py` |
| `identifiers.related_publication` | nothing; dead free text, dropped by the script | `migrate_identifiers.py` |
| `identifiers.project` | nothing; it was read by nothing | `migrate_identifiers.py` |
| `instruments[].pid` | `identifiers.instrument_pid`, or a typed `related_identifiers[]` row | no script; the curator moves the value by hand |
| `sources[]` | a `related_identifiers[]` row with `identifies: entire` plus the acquisition keys | `migrate_identifies.py` |

The curator metadata editor no longer offers any of them as inputs. A value it does not model is
carried through the round-trip verbatim, so hand-edited YAML is never silently dropped.

## Legacy key aliases

The flat 0.1 spellings are still accepted by both the validator and the engine, so legacy packages
need no migration:

| Structured | Flat |
|---|---|
| `project_name` | `name` |
| `organisation: { name, ror }` | `organisation: "Name"` |
| `data_types: [ … ]` | `data_type: …` |
| `funding: [ … ]` | `funders: [ … ]` |
| `processing: { software }` | `provenance: { processing_software }` |

New packages should use the structured form.

## Relationship to the survey package

`survey.yaml` describes the package as a whole; it is the package's primary metadata record.
Station-level information (coordinates, deployment dates, sensor orientations) comes from the
transfer-function files themselves. See [Survey package](../data-model/survey-package.md).
