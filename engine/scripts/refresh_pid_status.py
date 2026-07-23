#!/usr/bin/env python3
"""IDCONS D4 (identifier-consolidation, SPEC §5.2) — refresh the DOI resolution cache (pid_status.json).

The portal build is OFFLINE and byte-reproducible: it never touches the network. This tool is the ONLY
thing that HEADs doi.org. Run it EXPLICITLY (the deploy/Makefile `refresh-pid-status` target, part of the
release ritual — SPEC §6 step 4); it sweeps every DOI-typed identifier in the corpus, classifies each
under the alive-rule, and writes pid_status.json into the build state dir. `build_portal --pid-status`
then CONSUMES that file so a reserved-but-not-yet-active DOI renders as plain text, not a dead link.

  python engine/scripts/refresh_pid_status.py --surveys <surveys-root> --out <cache-dir>/pid_status.json

THE ALIVE-RULE (SPEC §5.1 — identical semantics to gateway/pidcheck.py; the two content-blind copies are
pinned equal by gateway/tests/test_pidcheck.py::test_alive_rule_parity_with_engine_tool):

  Only doi.org's OWN 404 = `unregistered` (reserved). Every other doi.org answer (200 / 30x redirect to
  the publisher / 403 bot-block / 5xx landing error) = `resolved`. A network failure = `error` (unknown;
  the build links it as today). Redirects are NOT followed — a publisher 404 after a 30x is not doi.org's
  404. The gate is an honesty guard, not a liveness monitor.

SWEEP SCOPE (SPEC §8.2 A-C5): during migration the corpus holds DOIs in BOTH the typed related_identifiers
list AND the still-readable flat keys (identifiers.dataset_doi, time_series.collection_pid). We sweep the
UNION, keyed by the identifier string (natural dedupe), so neither the typed nor the flat-only DOIs are
missed. The flat half drops out of the sweep in the same follow-up that removes the engine flat-key reads.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Status vocabulary written to the cache (SPEC §5.1). build_portal maps resolved->ok, unregistered->
# reserved, error/absent->unknown.
STATUS_RESOLVED = "resolved"
STATUS_UNREGISTERED = "unregistered"
STATUS_ERROR = "error"

_TIMEOUT_S = 10.0


def is_doi(identifier: str) -> bool:
    """A DOI-shaped identifier: contains a '10.' prefix (bare 10.x/y or a https://doi.org/10.… URL)."""
    return "10." in (identifier or "")


def normalise_doi(identifier: str) -> str:
    """Strip a leading (http[s]://)(dx.)doi.org/ so a bare DOI and a resolver URL check the same target."""
    s = (identifier or "").strip()
    for pfx in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/",
                "doi.org/", "dx.doi.org/"):
        if s.lower().startswith(pfx):
            return s[len(pfx):]
    return s


def classify(status_code: int | None, network_error: bool) -> str:
    """THE ALIVE-RULE as a pure function (offline-testable; pinned equal to gateway/pidcheck.classify).
    network_error/None -> error; doi.org 404 -> unregistered; any other doi.org answer -> resolved."""
    if network_error or status_code is None:
        return STATUS_ERROR
    if status_code == 404:
        return STATUS_UNREGISTERED
    return STATUS_RESOLVED


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do NOT follow redirects — a 30x from doi.org means the DOI is registered (points at the publisher),
    so we classify doi.org's own answer, not a chased-to publisher 404."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def head_status(doi: str) -> tuple[int | None, bool]:
    """HEAD https://doi.org/<bare-doi> WITHOUT following redirects; return (status_code, network_error).
    THIS is the only network call in the tool. An HTTPError is doi.org answering (404/403/5xx are verdicts,
    not failures); a URLError/OSError is the network_error case."""
    url = "https://doi.org/" + urllib.request.quote(normalise_doi(doi), safe="/:")
    req = urllib.request.Request(url, method="HEAD")
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        resp = opener.open(req, timeout=_TIMEOUT_S)
        return getattr(resp, "status", None) or resp.getcode(), False
    except urllib.error.HTTPError as exc:
        return exc.code, False
    except (urllib.error.URLError, OSError):
        return None, True


def doi_identifiers_of(y: dict) -> set[str]:
    """Every DOI-shaped identifier ONE survey.yaml contributes to the sweep (SPEC §8.2 A-C5): the typed
    related_identifiers rows whose identifier_type is DOI, PLUS the still-readable flat dataset_doi and
    time_series.collection_pid when they look like DOIs. Deduped by string."""
    out: set[str] = set()
    for r in (y.get("related_identifiers") or []):
        if isinstance(r, dict) and r.get("identifier_type") == "DOI":
            ident = r.get("identifier")
            if ident not in (None, "") and is_doi(str(ident)):
                out.add(str(ident).strip())
    ids = y.get("identifiers") if isinstance(y.get("identifiers"), dict) else {}
    flat_doi = ids.get("dataset_doi")
    if flat_doi not in (None, "") and is_doi(str(flat_doi)):
        out.add(str(flat_doi).strip())
    ts = y.get("time_series") if isinstance(y.get("time_series"), dict) else {}
    cpid = ts.get("collection_pid")
    if cpid not in (None, "") and is_doi(str(cpid)):
        out.add(str(cpid).strip())
    return out


def collect_corpus(surveys_root: Path) -> set[str]:
    """The union of DOI identifiers across every <slug>/survey.yaml under `surveys_root`."""
    import yaml  # engine-image dep (mt_metadata pulls PyYAML); the tool runs only in that image.
    root = Path(surveys_root)
    out: set[str] = set()
    for sy in sorted(root.glob("*/survey.yaml")):
        try:
            y = yaml.safe_load(sy.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, yaml.YAMLError) as exc:
            print(f"skip {sy}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if isinstance(y, dict):
            out |= doi_identifiers_of(y)
    return out


def refresh(surveys_root: Path, out_path: Path, *, head_fn=head_status, now=None) -> dict:
    """Sweep the corpus, HEAD each DOI under the alive-rule, and write pid_status.json. `head_fn` is
    injectable so tests drive this with ZERO network. Returns the written {identifier: {status, checked}}
    map. `now` (an ISO string) is injectable for a deterministic `checked` timestamp in tests."""
    checked = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    identifiers = sorted(collect_corpus(surveys_root))
    status_map: dict[str, dict] = {}
    for ident in identifiers:
        code, neterr = head_fn(ident)
        status_map[ident] = {"status": classify(code, neterr), "checked": checked}
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(status_map, indent=1, ensure_ascii=False), encoding="utf-8")
    return status_map


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surveys", required=True,
                    help="root of survey packages (<slug>/survey.yaml) to sweep for DOI identifiers")
    ap.add_argument("--out", required=True,
                    help="path to write pid_status.json (e.g. <cache-dir>/pid_status.json)")
    a = ap.parse_args(argv)
    status_map = refresh(Path(a.surveys), Path(a.out))
    n_reserved = sum(1 for v in status_map.values() if v["status"] == STATUS_UNREGISTERED)
    n_error = sum(1 for v in status_map.values() if v["status"] == STATUS_ERROR)
    print(f"refresh-pid-status: wrote {len(status_map)} identifier statuses to {a.out} "
          f"({n_reserved} reserved, {n_error} unreachable).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
