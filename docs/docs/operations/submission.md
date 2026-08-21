# Submission

AusMT is curated: survey packages are submitted for review rather than published directly, so that
what is published is still usable long after the original project has ended.

## How submission works

Submissions run through the AusMT submission gateway, a small service beside the portal; the portal's
Add survey page packages your files and uploads them directly. Every submission follows the same
fail-closed pipeline:

1. **Upload.** The package is received into quarantine and assigned a tracking id with a private
   status link.
2. **Antivirus scan.** Nothing advances until the scan completes.
3. **Validation.** The survey validator checks structure, metadata, licensing and EDI parseability,
   and an engine preview build proves the package builds.
4. **Curation.** A curator reviews the validated package, its reports and a rendered preview before
   approving. See [Review](review.md).
5. **Publication.** Approval commits the package to the survey repository; the live portal picks it
   up at the next data rebuild. See [Publication](publication.md).

At every step the system refuses rather than guesses. Submitter contact details are held separately
from the package and never enter the published record. Upload keys are issued by a curator (email the
operator to request one); the key travels only as the upload request header, never inside the package.

## Who can submit, and what

Researchers, survey custodians, universities, government agencies, research infrastructure facilities
and industry partners. The submitter should have the authority to publish the dataset or act on behalf
of the custodian.

The unit of submission is the [survey package](../data-model/survey-package.md): EDI, EMTF XML and
MTH5 by default, and processing-software products (`.zmm`, `.zrr`, `.j`) only when a curator enables
them for that submission with `--allow-optin-formats` in `validate_survey.py` (`--allow-mth5` is a
deprecated alias), and even then stored rather than parsed.

What belongs elsewhere: raw time series, native recorder files, processing workspaces, site
photographs, PDF reports, journal articles, presentations, project backups and large supplementary
datasets. Reference them from the survey metadata; see
[External archives](../interoperability/external-archives.md).

Before submitting, confirm that the dataset can be shared, that ownership is clear, and that licensing
has been considered. Historical datasets are welcome with incomplete metadata.

## Validation

Validation is automated and structural: it asks whether the package is well formed, not whether the
science is good. Checks include:

- package structure (`survey.yaml` present, transfer functions under the expected directories)
- required metadata (name, licence, access level; semantic version and release-notes shape)
- closed vocabularies: access level, coordinate-access policy, contributor roles and name types,
  identifier types and data levels. An out-of-vocabulary value fails
- coordinate sanity checks, including DMS/decimal cross-checks
- transfer-function file-type gates, signature checks and EDI parseability
- MTH5 structural validity (HDF5 signature, supported version, transfer-function groups)
- station identifier validity (character set, collisions)
- file-size caps
- `version` shaped `MAJOR.MINOR.PATCH`; `release_notes` entries shaped `{version, date, note}`
- deprecation warnings for retired `survey.yaml` fields, pointing at the migration script

Submitter-side provenance lives in `survey.yaml`'s `processing.*` and free-text fields and is checked
structurally with the rest of the metadata.

Separate from validation, every submission gets an **EDI `>INFO` pre-flight**. It reports what each
file's `>INFO` block will do to the metadata AusMT can read: whether the file opens in a standard reader
at all, whether it needs the repair AusMT applies to a temporary copy, how many metadata values will be
stored with a stray comma, and which number fields carry their units in the value and will publish
empty. The pre-flight is advice, never a gate: it cannot fail a submission and never changes a file. Its
findings appear in the preview summary on the submission status page, worst first, capped at a dozen
stations; the complete per-station list is written on the server beside the validator's report. The
[Curator checklist](../developer/curator-checklist.md) says how to read it.

Validation produces one of three outcomes. **PASS**: every required check is satisfied. **WARNING**:
the package is valid but something should be looked at (missing recommended metadata, incomplete
provenance, no publication references, no identifiers); warnings do not block publication. **FAIL**:
something prevents publication (missing required metadata, invalid coordinates, an unsupported format,
a corrupted transfer function, an invalid package structure); the package must be corrected.

Validation is not a quality measure. A package can pass while containing noisy data, and a historically
important dataset can generate warnings purely because its records are incomplete. Scientific judgement
stays with the user, and the diagnostics that support it are defined in
[Per-station products](../reference/station-products.md#18-diagnostics).

## CARE considerations

Indigenous data governance requirements, cultural heritage considerations, community agreements,
access restrictions and embargo requirements are recorded in `survey.yaml`'s `care.*` fields and
reviewed by a curator. No automated check blocks publication on CARE grounds. See
[Scientific philosophy](../introduction/scientific-philosophy.md#care).

## Updating a published survey

Metadata corrections, recovered provenance, new publication references, additional formats and
improved documentation follow the same validation and review path as a first submission, and land as a
new version. See [Versioning](../data-model/versioning.md).
