# Review

Review is where a validated survey package is assessed for inclusion in the curated record. It
sits between [validation](submission.md#validation), which asks whether the package is
structurally valid, and [publication](publication.md), which makes it part of the record.
Review asks a different question: should this be published?

It is not scientific peer review. It does not assess geological interpretations, inversion
results or conclusions.

## How review happens

Review runs in the gateway's curator interface. A curator signs in to a private queue of
validated submissions and, for each one, sees the validation report, a per-item checklist, the
submission's report bundle, and a rendered preview of the actual portal built from the
submitted package (sandboxed, reachable only by submission id). Submitter contact details are
visible to curators only and never enter the published record.

Every decision requires a written curator note and is recorded in the audit log. Approval
publishes the package as a git commit to the survey repository; the live portal serves it after
the operator's next data rebuild. Published and served are deliberately distinct states.

The practical item-by-item list is the
[Curator checklist](../developer/curator-checklist.md).

## What review considers

**Ownership.** Is the custodian identified, is the contributor identified, and is the
submitter's authority to publish established? This is the one finding that can stop a package
outright.

**Licensing.** The package must state its licence and any access conditions clearly enough
that a future user knows how it may be used. Embargo and access level are set here; their
serving consequences are in [Publication](publication.md#access-levels-and-embargoes).

**Metadata.** Opportunities to improve descriptions, collection assignment, identifiers,
citation information and resource references. This is about discoverability, not about
enforcing completeness.

**Provenance.** Whether what is recorded is adequate for the nature of the dataset. Historical
packages will be thin; the objective is to record what is known, not to require what would be
ideal.

**CARE considerations.** A manual check against the `care.*` fields recorded in `survey.yaml`.
There is no automated CARE enforcement anywhere in the pipeline.

**Collection assignment.** A package should sit in the right collection, because that is how
most people navigate to it.

## Outcomes

Each outcome requires a curator note.

**Publish.** The package is committed to the survey repository and appears on the portal at
the next data rebuild. Minor improvements can be recommended in the note and addressed in a
future version; curators can also apply metadata corrections through the gateway's metadata
editor, which follows the same validated, versioned, audited path.

**Return for revision.** Unclear ownership, missing licensing information, incorrect collection
assignment or significant metadata problems. The package may be resubmitted.

**Reject.** The package is not suitable for AusMT: material outside the repository's scope, or
a submission that cannot establish publication authority.

## Consistency and record

The same standards apply to universities, agencies, research infrastructure facilities and
industry contributors alike; review looks at the package, not the submitter. Decisions are
documented so that a future user can tell when a package was reviewed, which version was
reviewed, what was recommended and why the decision went the way it did.

A survey should not be rejected because personnel have retired, field records are incomplete
or processing details are gone. Review exists to leave a package better than it arrived, not
to hold the line against imperfect history.
