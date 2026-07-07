# Review Workflow

## Overview

Review is the process by which a validated survey package is assessed for inclusion in the curated AusMT record.

Review occurs after validation and before publication.

```text
Submission
        ↓
Validation
        ↓
Review
        ↓
Publication
```

The purpose of review is to ensure that published survey packages are appropriately documented, attributable and discoverable.

Review is not a scientific peer-review process.

It does not assess geological interpretations, inversion results or scientific conclusions.

Instead, review focuses on the suitability of a package for publication within AusMT.

---

## Objectives

The review process aims to ensure that:

- Ownership is clear.
- Licensing is appropriate.
- Metadata are sufficient for discovery.
- Provenance information is available where possible.
- Collection membership is correct.
- CARE considerations have been considered where applicable.
- The package can be understood by future users.

Review provides a level of oversight that cannot be achieved through automated validation alone.

---

## Validation and Review

Validation and review serve different purposes.

### Validation

Validation assesses:

- Structure
- Metadata completeness
- Format compliance
- Identifier validity

Validation is largely automated.

### Review

Review assesses:

- Ownership
- Licensing
- Publication suitability
- Stewardship considerations
- Collection assignment
- Context

Review requires human judgement.

---

## Scope

Review may consider:

### Ownership

Examples include:

- Data custodian identified
- Contributor identified
- Publication authority confirmed

The reviewer should be satisfied that the submitter has the right to publish the package.

---

### Licensing

The package should clearly describe any applicable licence or access conditions.

Examples include:

- Open access licences
- Institutional licences
- Project-specific requirements
- Embargo conditions

Licensing information should be sufficiently clear that future users understand how the package may be used.

---

### Metadata

Review may identify opportunities to improve:

- Survey descriptions
- Collection assignments
- Identifiers
- Citation information
- Resource references

Review is intended to improve discoverability rather than enforce unnecessary complexity.

---

### Provenance

Reviewers should consider whether provenance information is adequate for the nature of the dataset.

Examples include:

- Processing software identified
- Product lineage recorded
- Version history documented

Historical datasets may contain incomplete provenance.

The objective is to record what is known rather than require perfect documentation.

---

### CARE Considerations

Some datasets may include additional governance considerations.

Examples include:

- Indigenous data governance requirements
- Cultural heritage considerations
- Community agreements
- Access restrictions

Where applicable, these considerations should be documented and reviewed before publication. This is a manual curator check against the `care.*` fields recorded in `survey.yaml` — there is no automated CARE enforcement in the review pipeline.

---

### Collection Assignment

Survey packages should be associated with an appropriate collection.

Examples include:

- AusLAMP
- WAMT
- Institutional holdings
- State-based releases

Correct collection assignment improves discovery and navigation.

---

## Review Outcomes

Review typically produces one of three outcomes:

### Accept

The package is suitable for publication.

Minor improvements may still be recommended.

---

### Accept with Recommendations

The package is suitable for publication but additional improvements have been identified.

Examples include:

- Additional provenance
- Improved descriptions
- Additional identifiers
- Additional publication references

These recommendations may be addressed in a future version.

---

### Return for Revision

The package requires further work before publication.

Examples include:

- Unclear ownership
- Missing licensing information
- Incorrect collection assignment
- Significant metadata issues

The package may be resubmitted following revision.

---

## Historical Surveys

Many historically important datasets contain incomplete records.

Review should recognise the realities of legacy data stewardship.

A survey should not be rejected simply because:

- Personnel have retired.
- Field records are incomplete.
- Processing details are unavailable.
- Historical documentation has been lost.

The objective is to preserve scientifically valuable datasets while clearly documenting known limitations.

---

## Independence

Review should focus on the package rather than the organisation that submitted it.

The same standards should apply to:

- Universities
- Government agencies
- Research infrastructure facilities
- Industry contributors

Consistency is important for maintaining trust in the published record.

---

## Auditability

Review decisions should be documented.

Future users should be able to determine:

- When the package was reviewed.
- Which version was reviewed.
- What recommendations were made.
- Why publication decisions were reached.

Review records form part of the stewardship history of a survey package.

---

## Stewardship

Review is not intended to act as a barrier to publication.

Its purpose is to improve the quality, discoverability and long-term usability of survey packages.

A review should leave a package in a better state than it was when submitted, while recognising that historical datasets are rarely perfect and that metadata can continue to improve over time.