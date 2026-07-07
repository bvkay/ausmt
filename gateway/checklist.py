"""Live curator checklist (design §4): the machine-checkable subset of the curator checklist,
computed ENTIRELY from data already on disk (validate.json, preview-summary.json) plus the
submission row. The gateway does NOT re-parse the package here — it reads the runner's reports.

Each check yields PASS / WARN / FAIL / NA. A FAIL on a BLOCKING check refuses approve SERVER-SIDE
(the app returns 409 on the approve POST even if the button is hidden — the button being absent is
UX, the 409 is the guarantee, design §4). Non-blocking checks (DOI/PID) only ever WARN.

The single most important check is the PII grep: it looks for the submitter's own email (the needle
comes from the DB, curator-only) plus a generic email pattern across the built preview product +
package tree. A hit is a FAIL — publishing PII is the one thing the whole confinement design exists
to prevent. C11b splits that FAIL: a submitter-email hit is an ABSOLUTE block no acknowledgement can
override (§0); a hit on only OTHER addresses (e.g. a historical EDI `>INFO` contact line in a source
record) is a blocking FAIL a named curator MAY acknowledge (`acknowledgeable=True`). Either way the
detail names files ONLY — the matched address is never echoed anywhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
NA = "NA"

# A generic email pattern for the PII sweep (belt-and-braces alongside the exact submitter email).
_EMAIL_RE = re.compile(rb"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Coordinate anomaly flag the preview summary raises when a station's coords looked off and need a
# human ack (design §4). Its presence WARNs; it never blocks (the curator acknowledges via the note).
_COORD_ANOMALY = "info_anomalous_review"


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    status: str            # PASS / WARN / FAIL / NA
    detail: str
    blocking: bool         # a FAIL here refuses approve (design §4)
    acknowledgeable: bool = False  # C11b §1: a curator may acknowledge PAST this blocking FAIL


@dataclass(frozen=True)
class Checklist:
    checks: list[Check]
    # C11b §1: file names (relative to the scanned root) where a GENERIC (non-submitter) email
    # matched. Curator-only, file names ONLY (never an address). Used to render the classified list
    # and to build the acknowledge audit reason (§2). Empty unless the PII check is acknowledgeable.
    pii_generic_files: tuple[str, ...] = ()

    def _blocking_fails(self) -> list[Check]:
        return [c for c in self.checks if c.blocking and c.status == FAIL]

    @property
    def has_blocking_fail(self) -> bool:
        """True if any BLOCKING check is FAIL — approve must be refused (design §4/§5 guard)."""
        return bool(self._blocking_fails())

    @property
    def has_unacknowledgeable_blocking_fail(self) -> bool:
        """C11b §2: True if any blocking FAIL is NOT acknowledgeable — that is a hard 409 no
        acknowledgement can override (includes every submitter-email hit and every non-PII block)."""
        return any(not c.acknowledgeable for c in self._blocking_fails())

    @property
    def has_acknowledgeable_blocking_fail(self) -> bool:
        """C11b §2: True if there is at least one blocking FAIL and they are ALL acknowledgeable —
        the only case an affirmative ack_pii may proceed past."""
        fails = self._blocking_fails()
        return bool(fails) and all(c.acknowledgeable for c in fails)

    @property
    def blocking_fail_reasons(self) -> list[str]:
        return [f"{c.label}: {c.detail}" for c in self.checks if c.blocking and c.status == FAIL]


def _validator_items(validate_report: dict | None) -> list[dict]:
    if not isinstance(validate_report, dict):
        return []
    items = validate_report.get("items")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _level(item: dict) -> str:
    return str(item.get("level") or item.get("status") or "").upper()


# The reporting cap (C11b §1): bound the FILE-NAME lists we render, not the scan. The scan always
# visits the whole tree; only the surfaced names are capped so a package with thousands of hits does
# not produce an unbounded detail string.
_MAX_REPORTED = 20


class _PiiScan:
    """Structured result of the full-tree PII sweep (C11b §1). Scans the entire built product + package
    tree — never returns early on the first hit — and classifies each matching file as a submitter hit
    (the DB needle matched) or a generic hit (a generic email matched and the needle did NOT).

    submitter_hits / generic_hits hold FILE NAMES (relative to the scanned root) ONLY — never a matched
    address. `swept` is False when there was no built product on disk yet (→ NA, as today)."""

    __slots__ = ("submitter_hits", "generic_hits", "swept")

    def __init__(self, submitter_hits: list[str], generic_hits: list[str], swept: bool):
        self.submitter_hits = submitter_hits
        self.generic_hits = generic_hits
        self.swept = swept


def _rel_name(root: Path, p: Path) -> str:
    """File name relative to the scanned root (submitter-derived input — the caller escapes it before
    rendering, and it is NEVER an address). Falls back to the bare name if relative_to fails."""
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.name


def bounded_names(names) -> str:
    """Render a capped file-name list: up to _MAX_REPORTED names + a '+N more' suffix (§1). File names
    only — this string never contains a matched address. Public so the app can build the same bounded
    string for the acknowledge audit reason (§2) without re-deriving the cap."""
    names = list(names)
    if len(names) <= _MAX_REPORTED:
        return ", ".join(names)
    shown = names[:_MAX_REPORTED]
    return ", ".join(shown) + f", +{len(names) - _MAX_REPORTED} more"


def _grep_pii(package_dir: Path, preview_dir: Path, submitter_email: str) -> _PiiScan:
    """Sweep the built preview product + package tree for the submitter's exact email (needle from the
    DB) AND any generic email address (the generic pattern, not just the submitter's own), classifying
    each matching FILE — never echoing an address (C11b §1 / unchanged no-echo rule).

    A file whose bytes contain the needle is a SUBMITTER hit (unpublishable, no ack). A file that has a
    generic email match but NOT the needle is a GENERIC hit (a historical `>INFO` contact line in a
    source EDI — a curator may acknowledge it, §3). The scan visits the WHOLE tree so the curator sees
    every affected file, not just the first.

    Submitter-needle matching is CASE-INSENSITIVE by contract (design §1 as amended / review finding
    1): email addresses are case-insensitive in practice, and the generic regex already matches any
    case — a byte-exact needle would let 'User@Example.com' (DB) with 'user@example.com' in an artifact
    slide into the ACKNOWLEDGEABLE class, i.e. a §0 bypass. Both the needle and the scanned bytes are
    ASCII-lowercased before the containment test; a non-ASCII address falls back to byte-exact
    matching for its non-ASCII characters (bytes.lower() is ASCII-only), which is never weaker than
    the pre-fix behaviour.

    Scope note: only text-ish files are scanned as text; binaries are pattern-matched on raw bytes,
    which the generic regex tolerates. This is a heuristic sweep — a WARN-worthy safety net, elevated
    to a blocking FAIL because a false negative here is exactly the leak the whole design prevents."""
    needle = submitter_email.lower().encode("utf-8") if submitter_email else b""
    roots = [d for d in (package_dir, preview_dir) if d.exists()]
    if not roots:
        return _PiiScan([], [], swept=False)
    submitter_hits: list[str] = []
    generic_hits: list[str] = []
    for root in roots:
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            try:
                data = p.read_bytes()
            except OSError:
                continue
            name = _rel_name(root, p)
            if needle and needle in data.lower():
                # The submitter's OWN email in ANY case — the §0 needle. Unpublishable, no ack.
                submitter_hits.append(name)
            elif _EMAIL_RE.search(data) is not None:
                # A DIFFERENT address (a co-author / an EDI `>INFO` contact left in the record). Report
                # the file, not the address, so the checklist never echoes the PII it is flagging.
                generic_hits.append(name)
    return _PiiScan(submitter_hits, generic_hits, swept=True)


def build(*, validate_report: dict | None, preview_summary: dict | None,
          submission_slug: str | None, submitter_email: str,
          package_dir: Path, preview_dir: Path) -> Checklist:
    """Compute the full live checklist from reports on disk + the submission row. Pure w.r.t. the DB
    (the caller passes the slug/email); reads only the report files + built product tree."""
    checks: list[Check] = []
    items = _validator_items(validate_report)
    have_validate = validate_report is not None

    # CI/validator green — a FAIL item blocks approve (design §4).
    fails = [i for i in items if _level(i) in ("FAIL", "ERROR")]
    if not have_validate:
        checks.append(Check("validator", "Validator green", NA,
                            "validate.json not present", blocking=True))
    elif fails:
        detail = "; ".join(str(i.get("name") or i.get("check") or i.get("id") or "?") for i in fails[:5])
        checks.append(Check("validator", "Validator green", FAIL,
                            f"{len(fails)} FAIL item(s): {detail}", blocking=True))
    else:
        warns = [i for i in items if _level(i) in ("WARN", "WARNING")]
        status = WARN if warns else PASS
        checks.append(Check("validator", "Validator green", status,
                            f"{len(items)} checks, {len(warns)} warning(s)", blocking=True))

    # ClamAV ran + post-unpack sweep clean — both already recorded by the time a submission is
    # VALIDATED (a hit would have QUARANTINED it, so reaching the queue IS the pass). Informational.
    checks.append(Check("clamav", "Antivirus clean", PASS,
                        "raw scan + post-unpack sweep both passed (else the submission would be "
                        "QUARANTINED and not in this queue)", blocking=False))

    # slug present and matches the package folder (from validate.json / the runner-derived slug).
    if submission_slug:
        checks.append(Check("slug", "Slug present", PASS, submission_slug, blocking=True))
    else:
        checks.append(Check("slug", "Slug present", FAIL,
                            "no slug on the submission — cannot stage into surveys-live",
                            blocking=True))

    # Licence recognised + redistributable-consistent-with-access (from validate.json items, if the
    # validator reports one). NA when the validator says nothing about licence — a human-judgment
    # reminder rather than a machine block.
    licence_items = [i for i in items if "licence" in str(i.get("name") or i.get("id") or "").lower()
                     or "license" in str(i.get("name") or i.get("id") or "").lower()]
    if not licence_items:
        checks.append(Check("licence", "Licence recognised", NA,
                            "validator reported no licence check — confirm manually", blocking=False))
    else:
        bad = [i for i in licence_items if _level(i) in ("FAIL", "ERROR")]
        checks.append(Check("licence", "Licence recognised", FAIL if bad else PASS,
                            "; ".join(str(i.get("message") or i.get("detail") or "") for i in licence_items[:3]),
                            blocking=bool(bad)))

    # Coordinate flags resolved-or-acknowledged — an unexplained anomaly WARNs (never blocks; the
    # curator acknowledges it in the decision note).
    coord_flags = (preview_summary or {}).get("coord_flags") if isinstance(preview_summary, dict) else None
    flag_text = str(coord_flags) if coord_flags else ""
    if _COORD_ANOMALY in flag_text:
        checks.append(Check("coords", "Coordinate flags acknowledged", WARN,
                            "anomalous-coordinate review flag present — acknowledge in the note",
                            blocking=False))
    else:
        checks.append(Check("coords", "Coordinate flags acknowledged", PASS,
                            "no unresolved coordinate anomalies", blocking=False))

    # No submitter PII in the built product — the load-bearing privacy check (design §4 / C11b §1).
    # A submitter-email hit is a hard, NON-acknowledgeable block (§0). Only-generic hits are a blocking
    # FAIL a named curator may acknowledge (§3), because a historical `>INFO` contact line in a source
    # EDI is part of the record being archived, not a leak the gateway created.
    scan = _grep_pii(package_dir, preview_dir, submitter_email)
    generic_files: tuple[str, ...] = ()
    if not scan.swept:
        checks.append(Check("pii", "No submitter PII in package", NA,
                            "no built product on disk to sweep yet", blocking=False))
    elif scan.submitter_hits:
        # §0: the submitter's own email is present. Acknowledgement is NOT available for this.
        detail = (f"submitter email present in built artifact ({bounded_names(scan.submitter_hits)}) — "
                  "acknowledgement is not available for submitter PII; this block is absolute")
        checks.append(Check("pii", "No submitter PII in package", FAIL, detail, blocking=True,
                            acknowledgeable=False))
    elif scan.generic_hits:
        # §3: only non-submitter addresses. A curator may acknowledge that every one is part of the
        # original submitted records (e.g. an EDI `>INFO` contact line) and none is the submitter's.
        detail = (f"an email address is present in built artifact ({bounded_names(scan.generic_hits)}) — "
                  "acknowledgeable: confirm each is part of the original submitted records (e.g. an "
                  "EDI >INFO contact line) and none is the submitter's private contact")
        checks.append(Check("pii", "No submitter PII in package", FAIL, detail, blocking=True,
                            acknowledgeable=True))
        generic_files = tuple(scan.generic_hits)
    else:
        checks.append(Check("pii", "No submitter PII in package", PASS,
                            "no email address present in the built product or package", blocking=False))

    # DOI/PID present or absence acknowledged — WARN if absent, NEVER blocks (design §4).
    doi_items = [i for i in items if "doi" in str(i.get("name") or i.get("id") or "").lower()
                 or "pid" in str(i.get("name") or i.get("id") or "").lower()]
    if doi_items and any(_level(i) not in ("FAIL", "ERROR") for i in doi_items):
        checks.append(Check("doi", "DOI/PID present", PASS,
                            "a persistent identifier was reported", blocking=False))
    else:
        checks.append(Check("doi", "DOI/PID present", WARN,
                            "no DOI/PID reported — acknowledge in the note if intentional",
                            blocking=False))

    return Checklist(checks=checks, pii_generic_files=generic_files)
