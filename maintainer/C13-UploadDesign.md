# C13 — Direct upload from the Add Survey page ("Submit to AusMT")

**Status: FROZEN 2026-07-06 (chief-architect design). Implementation must not deviate without a
design amendment recorded here first.**

C10 built the gateway (upload → ClamAV → validate → preview → tokenised status). C11 built the
curator half (queue → review → approve = commit-and-push). C13 closes the contributor loop: the
add-survey page, which already builds a validated submission zip in the browser, gains a
**Submit to AusMT** action that POSTs that zip to the gateway — replacing "download the zip and
open a GitHub PR by hand" as the primary path wherever a gateway is running, while keeping the
manual-PR path fully working as the fallback.

## §0 Invariants (violating any of these is a design change, not an implementation detail)

1. **No server change.** C13 is a portal-only contract. The gateway's submit API is consumed
   exactly as shipped by C10/C11 (§3 below). If the implementation appears to need *any* edit under
   `gateway/`, STOP and escalate to the maintainer.
2. **Same-origin only, no config knob.** The page calls literal relative `/gateway/...` paths.
   This is what makes the flow CORS-free and covered by the existing CSP (`connect-src 'self'` on
   add-survey.html — see the Caddyfile comment block). Do NOT add a `gateway_base_url` config: a
   cross-origin gateway would need CORS the gateway deliberately does not set, and a CSP edit.
   No change to `portal.config.yaml`, `config.js`, or the Caddyfile directives (a comment-block
   sentence in the Caddyfile is allowed; directives are not).
3. **The submit key is radioactive.** It exists only in the `<input type="password">` element and
   transiently in the request header. Never persisted (no localStorage / sessionStorage / cookies /
   IndexedDB), never in a URL, never in any `track()` payload, never echoed into the DOM, never
   written into the zip (MANIFEST.json / SUBMISSION.md / survey.yaml), never in an error message.
4. **PII discipline (C3 doctrine) unchanged.** Submitter email/ORCID ride ONLY as multipart form
   fields into the gateway's sqlite. The package bytes stay identical in PII terms: no email, no
   submitter ORCID in any packaged file. The `submission_id` is treated as capability-adjacent:
   it must not enter `track()` payloads.
5. **Package format unchanged.** The gateway runner already consumes the page's zip layout
   (`<slug>/survey.yaml` + `transfer_functions/{edi,mth5}/...` + MANIFEST.json + SUBMISSION.md).
   The zip built for direct upload is byte-for-byte the same builder output as the download path
   (one shared build function; the download path must not regress).
6. **One inline script block.** All new page logic lives in the existing single inline `<script>`
   (pure logic exported via the existing `module.exports` for the jsdom harness, which extracts
   the block by regex — so still no literal script-open-tags in comments). No new external JS file,
   no new dependency (XMLHttpRequest is native; JSZip is already vendored).
7. **Graceful degradation.** With no reachable gateway (static-only deploys, `file://`, GH Pages),
   the page looks and behaves exactly as today: the gateway UI stays hidden and the manual-PR
   instructions remain the primary path. Degradation is dynamic (healthz probe), not configured.

## §1 Gateway detection

- On page load, `fetch("/gateway/healthz")` with an `AbortController` timeout of 5 s.
- The gateway counts as PRESENT only if: HTTP 200 **and** the body parses as JSON **and**
  `json.ok === true`. Anything else — network error, timeout, non-200, HTML body (an SPA-fallback
  or portal 404 page can 200 with HTML) — counts as ABSENT. This exact-shape check is the
  anti-false-positive guard; keep it strict.
- Probe result drives visibility of the submit UI (§2). One probe per page load; no polling, no
  retry loop. A failed probe leaves the page identical to the pre-C13 page.
- The probe result mapping is a pure exported function (`gatewayPresent(status, bodyText)`) so the
  strictness is unit-tested without a DOM.

## §2 UX

- New **"Submit to AusMT"** block in the actions area, hidden until the probe passes:
  - `<input type="password" id="m_submit_key" autocomplete="off">` labelled "Submit key", with a
    hint: issued by the AusMT operator; contact details on the About page.
  - Primary button **"Submit to AusMT"**. The existing "Package submission .zip" button remains,
    reworded as the manual/fallback path when the gateway is present.
- Submit flow, in order:
  1. `validateSurvey(...)` — any FAIL blocks (same gate as packaging).
  2. Submitter-ORCID **checksum** check (§4) — blocks with a clear message *before* upload
     (server enforces ISO 7064 MOD 11-2 and would 400 after a full upload; fail fast client-side).
     PI-ORCID handling is unchanged (format WARNING only).
  3. Empty submit key → block: "enter your submit key".
  4. Build the package via the shared builder (same output as download).
  5. POST via `XMLHttpRequest` (upload progress): visible progress bar, a Cancel button
     (`xhr.abort()`), submit button disabled while in flight (double-submit guard). No client
     timeout (250 MB on slow links is legitimate); Cancel is the escape hatch.
- Response handling — every server-derived string rendered through `esc()`:
  - **201** → success panel: submission id, and the status link rendered as an anchor ONLY if
    `status_url` matches `^\/gateway\/status\/[A-Za-z0-9_-]+$` (exported guard `statusUrlSafe()`;
    otherwise show the id and no link). Bold note: **"Save this link — it is the only way to check
    your submission's status."** Do not auto-navigate.
  - **401** → "submit key not accepted" (do not distinguish absent/wrong — mirror the server).
  - **409** → "an identical package is already in the pipeline (submission `<id>`)" — no status
    link exists for it by design (tokens are per-submitter secrets).
  - **413** → over the size limit; **429** → capacity, try later; **503** → gateway
    starting/paused, try later; **400** → `esc(detail)`.
  - Network error and user-cancel get distinct, honest messages.
  - The mapping is a pure exported function (`submitResultMessage(status, bodyJsonOrNull)`).
- On success, additionally remind: email stays private to the curators; the manual-PR path note is
  suppressed in the success panel.
- `track()` events (PII-free, consistent with existing): `GatewayDetected`,
  `GatewaySubmitAttempted` (counts only), `GatewaySubmitResult` `{code}` — no ids, no key, no email.
- Page copy: the lede and SUBMISSION.md "How to submit" text gain the direct-upload path as option
  1 where available, PR as option 2 — SUBMISSION.md must stay accurate for BOTH transport paths
  (it travels inside the zip either way).

## §3 Wire contract consumed (authoritative, from C10/C11 as shipped)

- `POST /gateway/submit`, header `X-AusMT-Submit-Key: <key>`.
- `multipart/form-data`: one file part (`file`, the zip, filename = generated package name) +
  fields `submitter_name` (required), `submitter_email` (required), `submitter_orcid` (OMIT the
  field entirely when empty). Parser limits: 1 file, ≤ 8 fields — do not add fields.
- `201 {"submission_id": ..., "status_url": "/gateway/status/<token>"}`; errors per §2. The
  status URL is same-origin relative and is used verbatim as an href only after `statusUrlSafe()`.

## §4 New pure logic (exported for tests, alongside the existing exports)

- `isOrcidChecksum(s)` — ISO 7064 MOD 11-2, mirroring `gateway/orcid.py` exactly (hyphenated or
  bare 16-char form; `X` only in the final position). The existing `isOrcid()` format check and
  its uses stay untouched.
- `gatewayPresent(status, bodyText)` — §1 strict shape check.
- `statusUrlSafe(url)` — §2 anchor guard.
- `submitResultMessage(status, bodyJsonOrNull)` — §2 message mapping (returns text, no HTML).
- `submitFormFields(meta)` — `{submitter_name, submitter_email}` + `submitter_orcid` only when
  non-empty.

## §5 Tests (extend the existing harnesses; new-feature tests may be written with the feature,
but every bug found during implementation still gets a proven-failing-first regression test)

- Node/jsdom (`portal/tests/`, driven by the existing python runner pattern):
  - `isOrcidChecksum`: the ORCID doc example `0000-0002-1825-0097` valid; same digits with wrong
    check digit invalid; bare-16 form; `X` check digit; format-invalid strings.
  - `gatewayPresent`: 200+`{"ok":true}` → true; 200+HTML → false; 200+`{"ok":false}` → false;
    404/500/network-shape → false.
  - `statusUrlSafe`: accepts `/gateway/status/<urlsafe-token>`; rejects `http://…`, `//…`,
    `javascript:…`, path traversal, and a tampered prefix.
  - `submitResultMessage`: every §2 code; a hostile `detail` (`<img src=x onerror=…>`) must come
    back as plain text that the page then escapes — plus a DOM-level assertion that the rendered
    panel contains no element injection (XSS regression, same style as the existing tests).
  - `submitFormFields`: ORCID omitted when empty.
  - Interaction (jsdom + mocked XHR/fetch): probe-fail leaves the submit UI hidden; probe-pass
    shows it; in-flight disables the button; 201 renders the escaped link; **the submit key
    appears nowhere except the `X-AusMT-Submit-Key` header of the mock request** — assert it is
    absent from the built zip bytes, all `track()` payloads, `document.body.innerHTML` (outside
    the input's live value), and every URL the mock saw.
  - Source assertions (grep-style, like the ROR endpoint pin): the page contains no new external
    origin; the healthz/submit paths are the literal same-origin `/gateway/...` strings.
- Existing portal tests (`add_survey_logic.test.js`, interaction tests) must pass unmodified in
  behaviour — the package-download path is regression-covered by them.
- No engine/surveys/gateway test changes expected; run those suites once at the end to prove the
  no-server-change invariant (they cannot fail from a portal-only diff; if they do, something
  leaked).

## §6 Docs

- `deploy/README.md` (gateway section): one short paragraph — the add-survey page auto-detects a
  same-origin gateway and offers direct upload; submit keys are distributed operator-to-tester
  out-of-band, and the manual-PR path remains available and documented.
- Caddyfile comment block: one sentence noting add-survey.html now also POSTs same-origin to
  `/gateway/submit` (covered by the existing `connect-src 'self'`; no directive change).

## §7 Size + scope guards

- Net new non-test code ≤ ~350 lines, all within `portal/add-survey.html` (+ the two §6 doc
  touches). No new files except tests. No new dependencies, no vendored additions.
- Out of scope: gateway/server changes, key persistence or "remember me", upload resume/retry,
  multi-package submissions, curator notifications, any `contract/` or `engine/` file.
