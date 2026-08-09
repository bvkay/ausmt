# Curator checklist

The automated validator (`ausmt-surveys/_validation/validate_survey.py`) checks structure and
vocabulary; this checklist is the human review a curator does before a survey is published. The
conceptual rationale is in [Review and Curation](../operations/review.md); this is the practical list.

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

**Credit**

- [ ] `creators[]` names the right parties in the right order, or is absent on purpose (the
      organisation-and-year fallback is correct for most state-survey data).
- [ ] Every `contributors[]` role matches what that party actually did. A wrong role publishes a
      false claim, so check the release chain rather than accepting the defaults.
- [ ] ORCIDs sit on people and RORs on organisations, never the other way round.
- [ ] Any surviving `lead_investigator`/`principal_investigators` values were migrated
      (`_tools/migrate_credit.py`), not left to the back-compat reader.

**Transfer-function inputs**

- [ ] The transfer functions sit under `transfer_functions/edi|emtfxml|mth5/` and are the format
      their extension claims. EDI, EMTF XML and MTH5 are accepted inputs; `.zmm`/`.zrr`/`.j` still
      need `--allow-optin-formats` and are stored rather than parsed.
- [ ] Where a station is supplied in more than one format, the EDI is what gets served. Check
      `build_report.json`'s `ingest_sources` for the preview build and confirm the source per
      station is the one the custodian intends to be citable.
- [ ] No `xml_failures` rows in the preview `build_report.json`. A station supplied only as EMTF
      XML that fails the canonical round trip serves nothing at all, so it must be fixed upstream
      rather than published with a gap.
- [ ] The EDI `>INFO` pre-flight was read. Gateway submissions carry it already: the runner writes
      `reports/edi-preflight.json` and puts a bounded summary into the preview warnings on the
      submission page. For a direct-PR contribution, or any package on disk, run it yourself:

    ```
    python -m extract.edi_preflight <package-or-directory> --json preflight.json
    ```

    It reads only, changes nothing, and always exits 0. It is advice, not a gate. It reports three
    things per station:

    - **will not read.** The file does not open in the reader AusMT uses, and has to be fixed by
      whoever produced it. A reference latitude written `--26.0322667` (a doubled minus) is the
      real example; `capricorn-2010`'s `CP3B21.edi` still carries it.
    - **needs the `>INFO` repair.** AusMT can read the file, but only via the parse-only fallback
      recorded in
      [`source_parse_fallbacks`](../reference/build-report-schema.md#211-surveyssource_parse_fallbacks).
      246 of the 312 EDIs in the GSSA Western Gawler 2023 delivery are in this state. Worth telling
      the custodian about, because every other tool reading their file hits the same wall.
    - **reads, but damage on the way in.** These build green and nothing else will ever mention
      them. Two classes: metadata values stored with a trailing comma (JSON punctuation the reader
      keeps; 141 of 159 scraped values on one Western Gawler station), and number fields that carry
      their units in the value, such as a contact resistance written `2.5 kilo-ohms`, which are
      dropped in silence and publish empty.

    Only the first is a reason to hold a package. The other two are reasons to write to the
    custodian, and the pre-flight is the only thing that will tell you they are there.

**Coordinates** (the common real-world problem)

- [ ] Station locations were confirmed on the Add Survey map; any HEAD/INFO DMS conflict is resolved
      via `coordinate_resolution` in `survey.yaml`.
- [ ] No `coord_flag`/`info_anomalous_review` left unexplained in `qc_report.json`.
- [ ] If the custodian asked for reduced precision, `access.coordinates` says so, and any
      `access.coordinate_overrides` keys are real station ids (the build fails the survey otherwise).

**Licensing & governance**

- [ ] The licence permits what the access level claims; redistribution gating is correct.
- [ ] Any CARE/embargo considerations are recorded and respected.

**Provenance**

- [ ] Dataset-level identifiers are typed `related_identifiers[]` rows with the right `identifies`
      level, not flat `dataset_doi`/`collection_pid` values. Run `_tools/migrate_identifiers.py` if
      the deprecation warnings fire.
- [ ] The survey has at least one provenance identifier, or the absence is acknowledged.
- [ ] Processing software/method are recorded where known.

**Submission envelope**

- [ ] Gateway submissions carry no submitter contact details in the package by design (they are
      form fields held in the gateway database, curator-visible only) — nothing to strip.
- [ ] For a legacy or manually-prepared package: confirm no private submitter block
      (`SUBMISSION.md`/`MANIFEST.json` email) remains in the published record.
