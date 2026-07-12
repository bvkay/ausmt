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
import threading
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
# C45 usage analytics (record D4/D5). The host aggregator (deploy/scripts/aggregate_stats.py, a daily
# timer) folds the Caddy access log into this cumulative stats.json in the SAME state dir; the Analytics
# screen reads it SERVER-side (the ops-status.json seam — no new mount, no new privilege, C40 intact).
# The gateway NEVER writes it. It carries aggregates only — counts + dailies, never an address or a UA.
STATS_FILENAME = "stats.json"

# C43 S2b-ii: the privileged INTENT files the gateway WRITES and the host actions agent
# (deploy/scripts/actions.sh) executes (record D8/D9). Fixed enum — these names MUST match the host
# agent's allow-list exactly. The gateway only ASKS (writes an intent); the host validates + acts.
# `rebuild.request` (above) stays existence-keyed for reconcile; these four ride the actions agent.
INTENT_FILENAMES: dict[str, str] = {
    "update": "update.request",
    "backup": "backup.request",
    "rollback": "rollback.request",
    "restore": "restore.request",
}
PAUSE_FILENAME = "pause.flag"                 # a FLAG reconcile respects (not an actions-agent intent)
ROLLBACK_PIN_FILENAME = "rollback.pin"        # host-written after a rollback; read here for display
ACTIONS_AUDIT_FILENAME = "actions-audit.log"  # host-written append-only audit; read here (tail) only

# PUBLISH_LOCK-class serialisation for the gateway-side intent writes (contract binding constraint): the
# single-flight check ("is this kind already pending?") and the atomic write must be one critical
# section, else two concurrent requests both see "not pending" and both write. A threading.Lock works
# from both the sync (`def`, threadpool) and async route paths the workbench uses.
_INTENT_LOCK = threading.Lock()


class IntentAlreadyPending(Exception):
    """A privileged intent of this kind is already waiting for the host agent to consume it — the
    single-flight guard (D9.3). The route surfaces this as 'already pending' UX, never a second write
    (one privileged action of a kind at a time)."""


class StateDirUnwritable(Exception):
    """The gateway state dir is missing or not writable — the rebuild request cannot be recorded.
    Raised so the route can fail CLOSED with a 503 (mirrors the curator-config 503 house style),
    never silently swallow a button press."""


def _now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_write(state_dir: Path, filename: str, payload: dict) -> Path:
    """Atomically write `payload` as JSON to <state_dir>/<filename> (tmp + os.replace — a real rename,
    so the host agent never reads a half-written file). Raises StateDirUnwritable on any failure so the
    route can fail CLOSED with a 503 rather than pretend the request was queued."""
    if not state_dir.is_dir():
        raise StateDirUnwritable(f"gateway state dir does not exist: {state_dir}")
    dest = state_dir / filename
    tmp = state_dir / f"{filename}.tmp.{os.getpid()}"
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, dest)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise StateDirUnwritable(f"cannot write {filename} under {state_dir}: {exc}") from exc
    return dest


def write_rebuild_request(state_dir: Path, *, requested_by: str, full: bool = False) -> Path:
    """Write {requested_at, requested_by[, full]} to <state_dir>/rebuild.request ATOMICALLY. Idempotent:
    a second press overwrites the same path (design §3 — "pressing twice = still one file"). The content
    is AUDIT ONLY for reconcile's existence-keyed consume — EXCEPT the optional `full` boolean (C43
    S2b-ii Force-full-rebuild): reconcile reads ONLY that one flag and, when true, runs the build in
    cache-REFRESH mode (recompute everything, no cache reuse). A bounded parse: the worst a compromised
    gateway can do is force a full — same corpus, just more expensive.

    Raises StateDirUnwritable if the dir is missing or the write cannot land."""
    payload: dict = {"requested_at": _now_utc(), "requested_by": requested_by}
    if full:
        payload["full"] = True
    return _atomic_write(state_dir, REQUEST_FILENAME, payload)


def write_intent(state_dir: Path, kind: str, *, requested_by: str,
                 extra: dict | None = None, single_flight: bool = True) -> Path:
    """Write a privileged INTENT file for the host actions agent (record D8/D9). `kind` is one of
    INTENT_FILENAMES (update/backup/rollback/restore); `extra` carries the validated id for the
    parameterised kinds (rollback: {'build_id': ...}; restore: {'snapshot_id': ...}) — the HOST
    re-validates it against the real inventory (D9.2, gateway-side is UX only). The whole payload is
    {requested_at, requested_by, **extra}.

    SINGLE-FLIGHT (D9.3): with single_flight True (the default) a pending intent of the SAME kind
    raises IntentAlreadyPending — one privileged action of a kind at a time. The check + write are one
    critical section under _INTENT_LOCK so two concurrent requests cannot both pass the check.
    """
    if kind not in INTENT_FILENAMES:
        raise ValueError(f"unknown intent kind: {kind!r}")
    filename = INTENT_FILENAMES[kind]
    with _INTENT_LOCK:
        if not state_dir.is_dir():
            raise StateDirUnwritable(f"gateway state dir does not exist: {state_dir}")
        if single_flight and (state_dir / filename).is_file():
            raise IntentAlreadyPending(kind)
        payload: dict = {"requested_at": _now_utc(), "requested_by": requested_by}
        if extra:
            payload.update(extra)
        return _atomic_write(state_dir, filename, payload)


def intent_pending(state_dir: Path, kind: str) -> bool:
    """True if a privileged intent of `kind` is waiting for the host agent (single-flight UX)."""
    fn = INTENT_FILENAMES.get(kind)
    return bool(fn) and (state_dir / fn).is_file()


def pending_intents(state_dir: Path) -> dict[str, dict]:
    """{kind: parsed-content} for every pending privileged intent (real-time, read straight from the
    state dir the gateway writes — fresher than ops-status.json's 15-min snapshot). A malformed intent
    still reports as pending with an empty dict (its presence is what disables the button)."""
    out: dict[str, dict] = {}
    for kind, fn in INTENT_FILENAMES.items():
        p = state_dir / fn
        if p.is_file():
            try:
                with open(p, encoding="utf-8") as fh:
                    doc = json.load(fh)
                out[kind] = doc if isinstance(doc, dict) else {}
            except (OSError, ValueError):
                out[kind] = {}
    return out


def write_pause_flag(state_dir: Path, *, requested_by: str) -> Path:
    """Write pause.flag {paused_at, requested_by} ATOMICALLY — reconcile then skips the auto-rebuild
    while it is fresh (auto-expires after 6 h; the alert timer alarms on a persistent re-arm). A
    re-pause overwrites (idempotent)."""
    return _atomic_write(state_dir, PAUSE_FILENAME,
                         {"paused_at": _now_utc(), "requested_by": requested_by})


def remove_pause_flag(state_dir: Path) -> bool:
    """Explicit RESUME: remove pause.flag. Returns True if a flag was removed, False if none existed.
    Never raises on a missing file (resume is idempotent)."""
    p = state_dir / PAUSE_FILENAME
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StateDirUnwritable(f"cannot remove pause flag under {state_dir}: {exc}") from exc


def pause_active(state_dir: Path) -> bool:
    """True if a pause.flag exists (the gateway shows 'paused'; freshness/expiry is reconcile's job)."""
    return (state_dir / PAUSE_FILENAME).is_file()


def read_pause_flag(state_dir: Path) -> dict | None:
    """Parsed pause.flag, or None if absent/unreadable/malformed. Never raises."""
    return _read_json(state_dir / PAUSE_FILENAME)


def read_rollback_pin(state_dir: Path) -> dict | None:
    """Parsed rollback.pin (host-written after a 'serve this build' rollback), or None. Never raises —
    the serve screen shows the pinned build when present so the drift is explained, not alarming."""
    return _read_json(state_dir / ROLLBACK_PIN_FILENAME)


def read_actions_audit_tail(state_dir: Path, *, n: int = 40) -> list[str]:
    """The last `n` lines of the host actions-audit.log (append-only, host-written 0644 so the gateway
    can read it). Read-only display of who/what/when/outcome for the privileged actions. Never raises;
    an absent log => [].

    Splits on '\\n' ONLY (never str.splitlines()): the host already scrubs control + unicode-separator
    chars from the attacker-controlled fields (actions.sh _scrub, S4), but the gateway must not TRUST
    that a host file is clean — splitlines() would treat a stray U+2028/U+2029/VT/FF as a line break
    and could fabricate whole tail entries from one crafted line. Splitting on the host's real
    separator (\\n) keeps a crafted line as ONE rendered entry (later _esc'd, so inert)."""
    p = state_dir / ACTIONS_AUDIT_FILENAME
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            lines = [ln.rstrip("\r") for ln in fh.read().split("\n") if ln.strip()]
        return lines[-n:]
    except OSError:
        return []


def _read_json(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


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


def read_stats(state_dir: Path) -> dict | None:
    """Return the parsed stats.json (the C45 usage-analytics aggregates), or None if it is absent (the
    aggregator timer is not installed / has not run) or unreadable/malformed. Never raises — mirrors
    read_ops_status: a broken stats file must not 500 the Analytics screen; the caller treats None as
    'no analytics yet' and renders the empty state (never a partial/last-known-good crash)."""
    path = state_dir / STATS_FILENAME
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
    # Fail-closed BOTH directions (gate finding 2026-07-11): a FUTURE generated_at (forward clock
    # step, then the timer dies) must be STALE too — a negative age is not freshness, it is doubt,
    # and doubt resolves to STALE. Freshness is the narrow band 0 <= age <= threshold.
    age = now - ts
    return not (0.0 <= age <= (stale_periods * period * 60.0))


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
