# Submission

AusMT is curated: survey packages are submitted for review rather than published directly. The
point is not to restrict data sharing but to make sure what gets published is still usable
long after the original project has ended.

## How submission works

Submissions run through the AusMT **submission gateway**, a small service alongside the portal
(the portal's *Add survey* page packages your files and uploads them directly). Every
submission follows the same fail-closed pipeline:

1. **Upload.** The package is received into quarantine and assigned a tracking id with a
   private status link.
2. **Antivirus scan.** Nothing advances until the scan completes.
3. **Validation.** The survey validator checks structure, metadata, licensing and EDI
   parseability, and an engine preview build proves the package actually builds.
4. **Curation.** A curator reviews the validated package, its reports and a rendered preview
   before approving. See [Review](review.md).
5. **Publication.** Approval commits the package to the survey repository; the live portal
   picks it up at the next data rebuild. See [Publication](publication.md).

At every step the system refuses rather than guesses: an unreadable package, an unrecognised
licence or an unscanned file stops the pipeline with an explicit state rather than publishing
something ambiguous. Submitter contact details are held separately from the package and never
enter the published record.

Upload keys are issued by a curator (email the operator to request one); the key is sent
out-of-band and travels only as the upload request header, never inside the package. The
gateway's security design is frozen in the repository's design records
(`maintainer/C10-GatewayDesign.md` and its successors).

## Who can submit, and what

Researchers, survey custodians, universities, government agencies, research infrastructure
facilities and industry partners. The submitter should have the authority to publish the
dataset or act on behalf of the custodian.

The unit of submission is the survey package, whose layout and accepted transfer-function
formats are specified in [Survey package](../data-model/survey-package.md). In short: EDI and
MTH5 by default, EMTF XML and processing-software products (`.zmm`, `.zrr`, `.j`) only when a
curator enables them for that submission with `--allow-optin-formats` in `validate_survey.py`
(`--allow-mth5` still works as a deprecated alias), and even then they are stored rather than
parsed into any built product.

What belongs elsewhere: raw time series, native recorder files, processing workspaces, site
photographs, PDF reports, journal articles, presentations, project backups and large
supplementary datasets. Reference them from the survey metadata instead; see
[External archives](../interoperability/external-archives.md).

Before submitting, confirm that the dataset can be shared, that ownership is clear, that
licensing has been considered, and that the transfer functions and whatever metadata exist have
been gathered. Historical datasets are welcome with incomplete metadata. Incomplete records
should not stop a scientifically valuable dataset from being preserved.

## Validation

Validation is automated and structural. It asks whether the package is well formed, not
whether the science is good.

Checks include:

- Package structure (`survey.yaml` present, transfer functions under the expected directories)
- Required metadata (name, licence, access level; semantic version and release-notes shape)
- Closed vocabularies: access level, coordinate-access policy, contributor roles and name
  types, identifier types and data levels. An out-of-vocabulary value fails rather than
  publishing a claim nobody can act on
- Coordinate sanity checks, including DMS/decimal cross-checks
- Transfer-function file-type gates, signature checks and EDI parseability
- MTH5 structural validity (HDF5 signature, supported version, transfer-function groups)
- Station identifier validity (character set, collisions)
- File-size caps
- Version identifier present and shaped `MAJOR.MINOR.PATCH`; `release_notes` entries shaped
  `{version, date, note}`
- Deprecation warnings for retired `survey.yaml` fields, pointing at the migration script

There is no separate provenance validation: submitter-side provenance lives in `survey.yaml`'s
`processing.*` and free-text fields and is checked structurally with the rest of the metadata.

Validation produces one of three outcomes:

```text
PASS
WARNING
FAIL
```

**PASS.** Every required check is satisfied. Minor issues may remain, but nothing identified
prevents publication.

**WARNING.** The package is valid but something should be looked at: missing recommended
metadata, incomplete provenance, no publication references, no identifiers, sparse station
notes. Warnings do not block publication; they inform the curator and, later, the user.

**FAIL.** Something prevents publication: missing required metadata, invalid coordinates, an
unsupported format, a corrupted transfer function, an invalid package structure. A failed
package must be corrected before it can proceed.

Validation reports the outcome with its errors, warnings and a metadata and product summary, so
there is a transparent record of what was checked.

**Validation is not a quality measure.** A package can pass while containing noisy data, sparse
coverage or thin interpretation, and a historically important dataset can generate warnings
purely because its records are incomplete. Structure and metadata are what validation assesses.
Scientific judgement stays with the user, and the diagnostics that support it are in
[Quality metrics](../science/quality-metrics.md).

Validation requirements will change as fields, product types and standards evolve. Changes
should stay backwards compatible where they can.

## CARE considerations

Some datasets carry cultural, community or governance obligations beyond technical metadata:
Indigenous data governance requirements, cultural heritage considerations, community
agreements, access restrictions, embargo requirements. Identify any that apply during
submission. Their presence does not necessarily prevent publication, but they must be recorded
in `survey.yaml`'s `care.*` fields and reviewed by a curator. This is manual; no automated
check blocks publication on CARE grounds. See
[Scientific philosophy](../introduction/scientific-philosophy.md#care).

## Updating a published survey

Metadata corrections, recovered provenance, new publication references, additional formats and
improved documentation all follow the same validation and review path as a first submission,
and land as a new version. See [Versioning](../data-model/versioning.md).
