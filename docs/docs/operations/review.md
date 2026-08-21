# Review

Review sits between [validation](submission.md#validation), which asks whether the package is
structurally valid, and [publication](publication.md), which makes it part of the record. Review asks
whether it should be published. It is not scientific peer review and does not assess interpretations.

## How review happens

Review runs in the gateway's curator interface. A curator signs in to a private queue of validated
submissions and, for each one, sees the validation report, a per-item checklist, the submission's report
bundle, and a rendered preview of the portal built from the submitted package (sandboxed, reachable only
by submission id). Submitter contact details are visible to curators only.

Every decision requires a written curator note and is recorded in the audit log. Approval publishes the
package as a git commit to the survey repository; the live portal serves it after the operator's next
data rebuild. Published and served are distinct states. The item-by-item list is the
[Curator checklist](../developer/curator-checklist.md).

## What review considers

- **Ownership.** Is the custodian identified, is the contributor identified, and is the submitter's
  authority to publish established? The one finding that can stop a package outright.
- **Licensing.** The licence and any access conditions must be stated clearly enough that a future
  user knows how the data may be used. Embargo and access level are set here; their serving
  consequences are in [Publication](publication.md#access-levels-and-embargoes).
- **Metadata.** Opportunities to improve descriptions, collection assignment, identifiers, citation
  information and resource references. Discoverability, not enforced completeness.
- **Provenance.** Whether what is recorded is adequate for the nature of the dataset. Historical
  packages will be thin.
- **CARE considerations.** A manual check against the `care.*` fields in `survey.yaml`. There is no
  automated CARE enforcement anywhere in the pipeline.
- **Collection assignment.** A package should sit in the right collection, because that is how most
  people navigate to it.

## Outcomes

Each outcome requires a curator note.

- **Publish.** The package is committed and appears on the portal at the next data rebuild. Minor
  improvements can be recommended for a future version, or applied through the gateway's metadata
  editor, which follows the same validated, versioned, audited path.
- **Return for revision.** Unclear ownership, missing licensing information, incorrect collection
  assignment or significant metadata problems. The package may be resubmitted.
- **Reject.** Material outside the repository's scope, or a submission that cannot establish
  publication authority.

The same standards apply to every contributor; review looks at the package, not the submitter.
Decisions are documented so a future user can tell when a package was reviewed, which version, what was
recommended and why. A survey should not be rejected because personnel have retired, field records are
incomplete or processing details are gone.
