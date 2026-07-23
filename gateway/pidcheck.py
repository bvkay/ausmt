"""IDCONS D4/D5 (identifier-consolidation, SPEC §5) — the curator-side DOI resolution check.

The editor's "Identifiers & PIDs" page shows a per-identifier status chip (SPEC §5.5). Unlike the build
(which is OFFLINE and reads a pre-refreshed pid_status.json cache), the gateway HAS egress, so the chip
does a LIVE doi.org HEAD server-side when the curator clicks the check button. This module is that check.

THE ALIVE-RULE (SPEC §5.1 — the load-bearing semantics, identical to the engine refresh tool
engine/scripts/refresh_pid_status.py; kept as a separate copy because the gateway image is content-blind
and ships only gateway/, so it cannot import the engine — the two copies are pinned equal by
gateway/tests/test_pidcheck.py::test_alive_rule_parity_with_engine_tool):

  Only doi.org ITSELF answering 404 = `unregistered` (reserved-but-not-yet-active). EVERYTHING ELSE that
  doi.org answers — 200, a 30x redirect to the publisher, 403 (Taylor & Francis blocks bots), a 5xx from
  the landing host — means the DOI IS registered = `resolved`. A network/DNS/timeout failure = `error`
  (unknown; the chip says "check failed", the portal links as today). The gate is an HONESTY guard, not a
  liveness monitor: its only job is to catch doi.org's own 404, never to second-guess a publisher.

Redirects are NOT followed: a 404 from the PUBLISHER after a redirect is not doi.org's 404, so following
redirects would misclassify a registered DOI whose landing page is missing. We read doi.org's FIRST
response verbatim. Only DOI-shaped identifiers are checked; a non-DOI (Handle/URL/RAiD) is reported as
`skipped` (the chip cannot HEAD doi.org for it).
"""
from __future__ import annotations

import urllib.error
import urllib.request

# Status vocabulary this module returns (the curator-chip half of the SPEC §5.1 vocab). `resolved` /
# `unregistered` / `error` mirror the engine cache; `skipped` is the non-DOI case the chip surfaces.
STATUS_RESOLVED = "resolved"
STATUS_UNREGISTERED = "unregistered"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"

# Curator-facing chip labels (advisory copy; the chip NEVER blocks saving).
_LABELS = {
    STATUS_RESOLVED: "resolves",
    STATUS_UNREGISTERED: "reserved — not yet active",
    STATUS_ERROR: "check failed",
    STATUS_SKIPPED: "not a DOI — no doi.org check",
}

_TIMEOUT_S = 8.0


def is_doi(identifier: str) -> bool:
    """A DOI-shaped identifier: contains a '10.' prefix somewhere (a bare 10.xxxx/… or a
    https://doi.org/10.… URL). Matches the editor's own loose DOI heuristic (editor_form._valid_doi)."""
    return "10." in (identifier or "")


def normalise_doi(identifier: str) -> str:
    """Reduce an identifier to the bare DOI path for the doi.org HEAD: strip a leading
    (http[s]://)(dx.)doi.org/ so both a bare '10.x/y' and a full resolver URL check the same target."""
    s = (identifier or "").strip()
    for pfx in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/",
                "doi.org/", "dx.doi.org/"):
        if s.lower().startswith(pfx):
            return s[len(pfx):]
    return s


def classify(status_code: int | None, network_error: bool) -> str:
    """THE ALIVE-RULE as a pure function (so it is unit-testable without the network, and pinned equal to
    the engine tool). `status_code` is doi.org's OWN first-response code (redirects NOT followed);
    `network_error` is True when doi.org could not be reached at all.

      * network_error            -> STATUS_ERROR (unknown; links as today)
      * status_code == 404       -> STATUS_UNREGISTERED (doi.org's own 404 = reserved/unmapped)
      * any other status_code    -> STATUS_RESOLVED (registered; 200/30x/403/5xx all mean "exists")
    """
    if network_error or status_code is None:
        return STATUS_ERROR
    if status_code == 404:
        return STATUS_UNREGISTERED
    return STATUS_RESOLVED


def _head_status(url: str, *, opener: urllib.request.OpenerDirector | None = None) -> tuple[int | None, bool]:
    """HEAD `url` WITHOUT following redirects; return (doi.org's status code, network_error). A urllib
    HTTPError carries the status code (a 404/403/5xx is a normal doi.org answer, NOT a network failure);
    a URLError (DNS/timeout/refused) is the network_error case. Injectable opener for the tests."""
    req = urllib.request.Request(url, method="HEAD")
    _opener = opener or urllib.request.build_opener(_NoRedirect())
    try:
        resp = _opener.open(req, timeout=_TIMEOUT_S)
        return getattr(resp, "status", None) or resp.getcode(), False
    except urllib.error.HTTPError as exc:
        return exc.code, False
    except (urllib.error.URLError, OSError):
        return None, True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do NOT follow redirects: a 30x from doi.org means the DOI is registered (it points at the
    publisher), so we must read doi.org's own response, not chase it to a publisher 404."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def check(identifier: str, *, opener: urllib.request.OpenerDirector | None = None) -> dict:
    """Check ONE identifier and return {status, label, identifier}. A non-DOI is `skipped` (no doi.org
    target). A DOI is HEADed at https://doi.org/<bare> under the alive-rule. Never raises — a failure is
    STATUS_ERROR, because the chip is advisory and must never break the page or block a save."""
    ident = (identifier or "").strip()
    if not is_doi(ident):
        return {"status": STATUS_SKIPPED, "label": _LABELS[STATUS_SKIPPED], "identifier": ident}
    bare = normalise_doi(ident)
    code, neterr = _head_status("https://doi.org/" + urllib.request.quote(bare, safe="/:"),
                                opener=opener)
    status = classify(code, neterr)
    return {"status": status, "label": _LABELS[status], "identifier": ident}
