# Validation Workflow

## Overview

Validation is the process used to assess whether a survey package satisfies the structural and metadata requirements of AusMT.

Validation occurs before review and publication.

Its purpose is to identify issues that may affect discoverability, usability or long-term stewardship.

Validation is primarily concerned with consistency and completeness.

It is not intended to assess scientific quality or interpretation.

---

## Validation and Review

Validation and review serve different purposes.

### Validation

Validation asks:

> Is this survey package structurally valid?

Examples include:

- Is the metadata complete?
- Are required fields present?
- Are coordinates valid?
- Are identifiers correctly formatted?
- Are transfer-function products readable?

Validation is largely automated.

---

### Review

Review asks:

> Should this survey package be published?

Examples include:

- Is ownership clear?
- Is licensing appropriate?
- Are CARE considerations documented?
- Is collection membership correct?
- Are there known issues requiring curator attention?

Review requires human judgement.

---

## Validation Objectives

Validation aims to ensure that published survey packages are:

- Discoverable
- Consistent
- Interoperable
- Maintainable

The objective is not perfection.

The objective is to ensure that users can understand and reuse published products.

---

## Validation Scope

Validation may assess:

### Package Structure

Examples:

- Required files present
- Directory structure valid
- Required metadata files present

### Metadata

Examples:

- Required fields present
- Required identifiers present
- Date formats valid
- Coordinate formats valid

### Transfer Functions

Examples:

- EDI readable
- EMTFXML readable
- MTH5 readable
- Station identifiers consistent

### Provenance

Examples:

- Provenance records present
- Required relationships valid
- Referenced products exist

### Versioning

Examples:

- Version identifier present
- Version format valid
- Version history consistent

---

## Validation Outcomes

Validation produces one of three outcomes:

```text
PASS
WARNING
FAIL
```

---

### PASS

The package satisfies all required validation checks.

Minor issues may still exist, but no problems have been identified that prevent publication.

---

### WARNING

The package is valid but contains issues that should be reviewed.

Examples include:

- Missing recommended metadata
- Missing publication references
- Incomplete provenance
- Missing identifiers
- Incomplete station notes

Warnings do not necessarily prevent publication.

They provide additional information for reviewers and users.

---

### FAIL

The package contains issues that prevent publication.

Examples include:

- Missing required metadata
- Invalid coordinates
- Unsupported formats
- Corrupted transfer-function products
- Missing survey identifiers
- Invalid package structure

A failed package must be corrected before it can proceed.

---

## Required and Recommended Metadata

Validation distinguishes between:

### Required

Information necessary for publication.

Examples:

- Survey identifier
- Survey title
- Geographic information
- Transfer-function products

---

### Recommended

Information that improves reuse and interpretation.

Examples:

- Investigator information
- Organisation identifiers
- Provenance records
- Publication references
- Funding information

Missing recommended metadata may generate warnings but not necessarily failures.

---

## Historical Surveys

Historical datasets often contain incomplete metadata.

AusMT recognises this reality.

The validation framework is designed to encourage preservation of valuable legacy datasets without imposing unrealistic requirements.

For this reason:

- Missing required information may fail validation.
- Missing historical context may generate warnings.

The intention is to preserve scientifically valuable datasets while clearly communicating limitations.

---

## Validation Reports

Validation generates a report summarising the outcome.

Typical reports include:

- Validation status
- Errors
- Warnings
- Metadata summary
- Product summary

Reports provide a transparent record of what was checked and what issues were identified.

---

## Validation Does Not Measure Scientific Quality

Validation should not be interpreted as a measure of scientific quality.

A survey package may pass validation while containing:

- Noisy data
- Sparse coverage
- Incomplete interpretations

Similarly, an historically important dataset may generate warnings because metadata are incomplete.

Validation assesses structure and metadata.

Scientific interpretation remains the responsibility of users.

---

## Continuous Improvement

Validation requirements will evolve as AusMT develops.

New metadata fields, product types and standards may be introduced over time.

The validation framework is therefore expected to change.

Where possible, changes should remain backwards compatible and avoid creating unnecessary barriers to publication.

---

## Principle

Validation exists to improve consistency and long-term usability.

It is not intended to prevent data publication.

A survey package that can be understood and reused is generally more valuable than a survey package that remains unpublished while waiting for perfect metadata.