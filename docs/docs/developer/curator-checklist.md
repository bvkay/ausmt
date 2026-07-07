# Curator checklist

The automated validator (`ausmt-surveys/_validation/validate_survey.py`) is Stage 2. This checklist
is **Stage 3** — the human review a curator does before a survey is published. The conceptual
rationale is in [Review and Curation](../operations/review.md); this is the practical list.

## Before approving a survey package

**Automated gate**

- [ ] Validation passed with no `FAIL` (gateway submissions: the validator report in the curator
      queue; direct-PR contributions: CI). WARNINGs are reviewed, not auto-blocking.
- [ ] Antivirus (ClamAV) ran (per submission in the gateway; in CI for direct PRs).
- [ ] For gateway submissions: the engine preview built, and the rendered preview looks right.

**Identity & metadata**

- [ ] `slug` equals the folder name and is stable/unique.
- [ ] `project_name`/`name`, `organisation`, `country`, `license`, `access` are real (no `TBD`/`TODO`).
- [ ] `version` is semantic (e.g. `1.0.0`).
- [ ] `collection.id` (if any) is a confirmed, correctly-spelled id — see [Collection IDs](collection-ids.md).

**Coordinates** (the common real-world problem)

- [ ] Station locations were confirmed on the Add Survey map; any HEAD/INFO DMS conflict is resolved
      via `coordinate_resolution` in `survey.yaml`.
- [ ] No `coord_flag`/`info_anomalous_review` left unexplained in `qc_report.json`.

**Licensing & governance**

- [ ] The licence permits what the access level claims; redistribution gating is correct.
- [ ] Any CARE/embargo considerations are recorded and respected.

**Provenance**

- [ ] A dataset DOI or survey PID is present, or the absence is acknowledged.
- [ ] Processing software/method are recorded where known.

**Submission envelope**

- [ ] Gateway submissions carry no submitter contact details in the package by design (they are
      form fields held in the gateway database, curator-visible only) — nothing to strip.
- [ ] For a legacy or manually-prepared package: confirm no private submitter block
      (`SUBMISSION.md`/`MANIFEST.json` email) remains in the published record.
