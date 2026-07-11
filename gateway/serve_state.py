"""Serve-state helpers for the C40 curator serve-reconcile panel.

The gap C40 closes: `PUBLISHED` means "committed to surveys-live and pushed", NOT "served" — the
portal keeps serving the old build until a rebuild runs. C40 adds a host-side reconcile timer that
rebuilds on drift, and this module is the GATEWAY half: the curator's front-door view of that state
(published HEAD vs served build, last reconcile outcome, a pending-rebuild indicator) plus the
zero-argument "request rebuild" button's write.

Pure-ish functions (filesystem + an injected git runner, no DB, no framework) so the read/write logic
is unit-testable without the whole app — the same split uploader_keys.py / publish.py use.

TRUST BOUNDARY (design §3): the gateway gains NO new privileges. It reads its OWN state dir
(/gw/state, already mounted rw) and runs `git rev-parse` over the surveys-live checkout it ALREADY
mounts for the publish flow (via the same scrubbed_env the publish git calls use). It does NOT read
site-data (it has no such mount) — the served build.json/build_report.json are fetched by the BROWSER
same-origin from Caddy, never by this server. The request file's CONTENT is audit-only: the host
reconcile agent keys only on the file's EXISTENCE and never parses it (C40 §4 — zero-argument by
design), so a compromised gateway can at worst trigger one rebuild per timer tick of the same corpus.
"""
from __future__ import annotations

import calendar
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

# The two state files the reconcile agent and the button share, under the gateway state dir
# (cfg.state_dir == /gw/state; host: $AUSMT_DATA_DIR/gateway/state). Names fixed by design §3.
REQUEST_FILENAME = "rebuild.request"
STATUS_FILENAME = "reconcile-status.json"
# C43 S2b-i: the ops floor's host-written state file (record D8/D15). Written by the alert timer
# (deploy/scripts/alert.sh) into the SAME state dir, read SERVER-side here (the reconcile-status.json
# seam — no new mount, C40 intact). The gateway never writes it.
OPS_STATUS_FILENAME = "ops-status.json"


class StateDirUnwritable(Exception):
    """The gateway state dir is missing or not writable — the rebuild request cannot be recorded.
    Raised so the route can fail CLOSED with a 503 (mirrors the curator-config 503 house style),
    never silently swallow a button press."""


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_rebuild_request(state_dir: Path, *, requested_by: str) -> Path:
    """Write {requested_at, requested_by} to <state_dir>/rebuild.request ATOMICALLY (tmp + os.replace
    — a real rename, so the host agent never sees a half-written file). Idempotent: a second press
    overwrites the same path (design §3 — "pressing twice = still one file"). The content is AUDIT
    ONLY (who asked, when); the host agent ignores it and keys only on existence.

    Raises StateDirUnwritable if the dir is missing or the write cannot land — the route turns that
    into a fail-closed 503 rather than pretending the request was queued.
    """
    if not state_dir.is_dir():
        raise StateDirUnwritable(f"gateway state dir does not exist: {state_dir}")
    payload = json.dumps({"requested_at": _now_utc(), "requested_by": requested_by})
    dest = state_dir / REQUEST_FILENAME
    tmp = state_dir / f"{REQUEST_FILENAME}.tmp.{os.getpid()}"
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, dest)  # atomic within the same directory
    except OSError as exc:
        # Clean up a stray tmp; surface a fail-closed error the route maps to 503.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise StateDirUnwritable(f"cannot write rebuild request under {state_dir}: {exc}") from exc
    return dest


def rebuild_request_pending(state_dir: Path) -> bool:
    """True if a rebuild.request is waiting to be consumed by the next reconcile tick. The panel shows
    this as "rebuild requested, pending next reconcile tick"."""
    return (state_dir / REQUEST_FILENAME).is_file()


def read_reconcile_status(state_dir: Path) -> dict | None:
    """Return the parsed reconcile-status.json, or None if it is absent (reconcile agent not installed
    yet) or unreadable/malformed. Never raises — a broken status file must not 500 the curator page;
    the panel treats None as "no status yet"."""
    path = state_dir / STATUS_FILENAME
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def read_ops_status(state_dir: Path) -> dict | None:
    """Return the parsed ops-status.json (the ops floor's host-written facts), or None if it is absent
    (the alert timer is not installed / has not run) or unreadable/malformed. Never raises — mirrors
    read_reconcile_status: a broken ops file must not 500 the serve screen; the caller treats None as
    'no ops status' and renders STALE cards (never last-known-good silently)."""
    path = state_dir / OPS_STATUS_FILENAME
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def ops_status_stale(status: dict | None, *, now_epoch: float | None = None,
                     default_period_min: float = 15.0, stale_periods: float = 2.0) -> bool:
    """True when ops-status.json is missing (status None), or older than ~`stale_periods` timer periods
    — the ops floor then renders explicit STALE cards instead of last-known-good (record D8/D15). A
    missing OR unparseable `generated_at` is STALE (fail loud, never silently fresh). The timer period
    is read from the file's own `timer_period_min` (the writer stamps its cadence); a bad/absent value
    falls back to `default_period_min`. `now_epoch` is injectable so the staleness pin is deterministic.

    FAILS-CLOSED by construction: any doubt about freshness resolves to STALE, so stale data can never
    render as fresh (the pin's failure criterion)."""
    if not isinstance(status, dict):
        return True
    gen = status.get("generated_at")
    if not isinstance(gen, str) or not gen:
        return True
    try:
        ts = calendar.timegm(time.strptime(gen, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return True
    try:
        period = float(status.get("timer_period_min"))
        if period <= 0:
            period = default_period_min
    except (TypeError, ValueError):
        period = default_period_min
    now = time.time() if now_epoch is None else now_epoch
    return (now - ts) > (stale_periods * period * 60.0)


@dataclass(frozen=True)
class PublishedHead:
    """The surveys-live HEAD as the gateway sees it server-side. `short` is the short sha (the value
    the panel compares against the served build's source_commit); `available` is False when git could
    not be run (never mounted, not a checkout, git error) — the panel shows "unavailable" and never
    500s on it."""
    short: str | None
    available: bool


def read_published_head(git_runner, surveys_live: Path | None) -> PublishedHead:
    """`git -C surveys-live rev-parse --short HEAD` through the INJECTED git seam (publish.real_git_
    runner in production, a fake in tests) — the SAME runner + scrubbed_env the publish flow uses, so
    the safe.directory GIT_CONFIG_* the compose file already declares applies and no secret leaks to
    git. Returns available=False (never raises) on any failure: an unset surveys_live, a non-checkout,
    or a non-zero git exit. The curator page shows "unavailable" instead of erroring — a missing HEAD
    is a state to display, not a page fault (design §4: "on failure show 'unavailable', never 500")."""
    if surveys_live is None:
        return PublishedHead(short=None, available=False)
    try:
        res = git_runner(["rev-parse", "--short", "HEAD"], cwd=surveys_live)
    except Exception:  # noqa: BLE001 -- any runner error degrades to "unavailable", never a 500
        return PublishedHead(short=None, available=False)
    if getattr(res, "returncode", 1) != 0:
        return PublishedHead(short=None, available=False)
    short = (res.stdout or "").strip()
    if not short:
        return PublishedHead(short=None, available=False)
    return PublishedHead(short=short, available=True)
