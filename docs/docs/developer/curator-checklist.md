# Curator checklist

The validator (`ausmt-surveys/_validation/validate_survey.py`) checks structure and vocabulary; this is
the human review a curator does before a survey is published. The rationale is in
[Review](../operations/review.md).

## Before approving a survey package

**Automated gate**

- [ ] Validation passed with no `FAIL` (gateway submissions: the validator report in the curator queue;
      direct-PR contributions: CI). WARNINGs are reviewed, not auto-blocking.
- [ ] Antivirus (ClamAV) ran.
- [ ] For gateway submissions: the engine preview built, and the rendered preview looks right.

**Identity and metadata**

- [ ] `slug` equals the folder name and is stable and unique.
- [ ] `project_name`/`name`, `organisation`, `country`, `license`, `access` are real (no `TBD`/`TODO`).
- [ ] `version` is semantic (`1.0.0`).
- [ ] `collection.id` (if any) is a confirmed, correctly spelled id; see
      [Collection IDs](collection-ids.md).

**Credit**

- [ ] `creators[]` names the right parties in the right order, or is absent on purpose (the
      organisation-and-year fallback is correct for most state-survey data).
- [ ] Every `contributors[]` role matches what that party did. A wrong role publishes a false claim.
- [ ] ORCIDs sit on people and RORs on organisations.
- [ ] Any surviving `lead_investigator`/`principal_investigators` values were migrated
      (`_tools/migrate_credit.py`).

**Transfer-function inputs**

- [ ] The transfer functions sit under `transfer_functions/edi|emtfxml|mth5/` and are the format their
      extension claims. `.zmm`/`.zrr`/`.j` need `--allow-optin-formats` and are stored rather than
      parsed.
- [ ] Where a station is supplied in more than one format, the EDI is what gets served. Check
      `build_report.json`'s `ingest_sources` for the preview build.
- [ ] No `xml_failures` rows in the preview `build_report.json`. A station supplied only as EMTF XML
      that fails the canonical round trip serves nothing, so it must be fixed upstream.
- [ ] The EDI `>INFO` pre-flight was read. Gateway submissions carry it already: the runner writes
      `reports/edi-preflight.json` and puts a bounded summary into the preview warnings. For a direct-PR
      contribution, or any package on disk:

    ```
    python -m extract.edi_preflight <package-or-directory> --json preflight.json
    ```

    It reads only, changes nothing, always exits 0, and reports three things per station:

    - **will not read.** The file does not open in the reader AusMT uses and has to be fixed by whoever
      produced it. A reference latitude written `--26.0322667` (a doubled minus) is the real example;
      `capricorn-2010`'s `CP3B21.edi` carries it.
    - **needs the `>INFO` repair.** AusMT reads the file only via the parse-only fallback recorded in
      [`source_parse_fallbacks`](../reference/build-report-schema.md#211-surveyssource_parse_fallbacks).
      246 of the 312 EDIs in the GSSA Western Gawler 2023 delivery are in this state. Worth telling the
      custodian, because every other tool reading their file hits the same wall.
    - **reads, but damage on the way in.** These build green and nothing else mentions them: metadata
      values stored with a trailing comma (141 of 159 scraped values on one Western Gawler station), and
      number fields that carry their units in the value, such as a contact resistance written
      `2.5 kilo-ohms`, which are dropped in silence and publish empty.

    Only the first is a reason to hold a package. The other two are reasons to write to the custodian.
    The bounded summary is ordered worst first; `reports/edi-preflight.json` holds the full per-station
    detail on the server, keeping the first few damaged-value samples per file plus the true count. The
    CLI prints every one.

**Coordinates**

- [ ] Station locations were confirmed on the Add Survey map; any HEAD/INFO DMS conflict is resolved via
      `coordinate_resolution` in `survey.yaml`.
- [ ] No `coord_flag`/`info_anomalous_review` left unexplained in `qc_report.json`.
- [ ] If the custodian asked for reduced precision, `access.coordinates` says so, and any
      `access.coordinate_overrides` keys are real station ids (the build fails the survey otherwise).

**Licensing and governance**

- [ ] The licence permits what the access level claims; redistribution gating is correct.
- [ ] Any CARE/embargo considerations are recorded and respected.

**Provenance**

- [ ] Dataset-level identifiers are typed `related_identifiers[]` rows with the right `identifies`
      level, not flat `dataset_doi`/`collection_pid` values. Run `_tools/migrate_identifiers.py` if the
      deprecation warnings fire.
- [ ] The survey has at least one provenance identifier, or the absence is acknowledged.
- [ ] Processing software and method are recorded where known.

**Submission envelope**

- [ ] Gateway submissions carry no submitter contact details in the package by design (form fields held
      in the gateway database, curator-visible only).
- [ ] For a legacy or manually prepared package: no private submitter block (`SUBMISSION.md`,
      `MANIFEST.json` email) remains in the published record.
