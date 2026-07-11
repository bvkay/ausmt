"""FastAPI app: upload -> scan -> queue, plus the single asyncio poll loop that ingests done-files,
retries clamd on held submissions, does the post-unpack sweep, and re-queues dead jobs (design
§4/§5/§6). The gateway never parses EDI/YAML; the deepest it inspects submitted bytes is the zip
central directory (zipsafety). It is the ONLY DB writer.

No CORS headers anywhere (design §1) — same-origin by construction through Caddy. No cookies/sessions
(design §3). Auth is the submit key on POST and the capability token on GET.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import os
import secrets
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Form, Header, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import checklist as checklist_mod
from . import (clamd, curator_auth, curatorpage, db, editor_form, jobs, metaedit, publish,
               serve_state, states, statuspage, totp, uploader_keys as uploader_keys_mod, zipsafety)
from . import upload as upload_intake
from .config import Config, fail_closed_startup, load_config
from .orcid import is_valid_orcid

logger = logging.getLogger("ausmt.gateway")

# Stream the multipart body in these chunks so a 250 MB upload never lands whole in RAM (design
# §4.1). Also the granularity at which the size cap is enforced mid-stream.
_UPLOAD_CHUNK = 1024 * 1024
_POLL_INTERVAL_S = 5.0
_STATUS_404_BODY = b"not found"  # byte-identical for every unknown/invalid token (design §3)

# C43 fix-round F5: server-side length caps on the uploader-key free-text fields. The caps are the
# GATE (an over-length POST is refused 400, never silently truncated); the form maxlength attributes
# are client courtesy only. Modest values: a note is "who it's for / expiry intent" (2000 chars is
# paragraphs), a name is a short operator label, an email caps at the RFC 5321 path limit.
_NOTE_MAX_CHARS = 2000
_KEY_NAME_MAX_CHARS = 120
_KEY_EMAIL_MAX_CHARS = 254


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


class Gateway:
    """Holds the app's mutable seams (config, DB, a scanner callable) so tests can inject a fake
    clamd and a temp data dir without monkeypatching module globals."""

    def __init__(self, cfg: Config, scanner=None, git_runner=None, edit_runner=None):
        self.cfg = cfg
        for d in (cfg.incoming_dir, cfg.quarantine_dir, cfg.jobs_dir, cfg.state_dir):
            d.mkdir(parents=True, exist_ok=True)
        jobs.ensure_dirs(cfg.jobs_dir)
        self.db = db.Database(cfg.db_path)
        # scanner(data:bytes) -> awaitable[clamd.ScanResult]; default hits the real clamd. Injected
        # in tests so no real daemon is needed and the fail-closed path is exercisable.
        self._scan_bytes = scanner or self._real_scan
        # C11 publish seam (design §5 v2), same injected-callable pattern as the scanner: git_runner
        # defaults to the real subprocess call and is overridden in tests so no real git is needed.
        # There is NO rebuild seam — demo publish is COMMIT-AND-PUSH ONLY; the operator runs
        # `make rebuild-data` by hand afterward, so the gateway never invokes the build (and never
        # needs the Docker socket the C10 §0 invariant forbids it).
        self._git_runner = git_runner or publish.real_git_runner
        # C31 metadata-editor seam (same injected-callable pattern as scanner/git). Default ENQUEUES
        # the job on the jobs/edit/ file queue and polls for the gw-runner's result with a bounded
        # timeout — the yaml work happens in the gw-runner service (the ENGINE image, where ruamel
        # lives), never in this process (C31 §0.1 / review FIX 1). The seam BLOCKS while polling, so
        # async handlers call it via asyncio.to_thread (review FIX 4); the sync form route already
        # runs in Starlette's threadpool. Tests inject an in-process seam.
        self._edit_runner = edit_runner or (
            lambda job: metaedit.default_edit_runner(job, self.cfg.jobs_dir,
                                                     timeout_s=self.cfg.edit_timeout_s))
        # C11 curator auth (design §2). Keys are parsed LAZILY (curator_keys()) so a malformed config
        # fail-closes each curator route with a 503 rather than aborting startup — the submit half of
        # the gateway must keep working even if curator config is broken. The rate limiter is a single
        # process-global (design §6: no per-source trust on a tailnet).
        self._login_limiter = curator_auth.LoginRateLimiter(
            max_attempts=cfg.login_max_attempts, window_s=cfg.login_window_s)
        # C41 D2: a SECOND process-global throttle for the destructive-op TOTP factor (the same
        # login-throttle pattern, a distinct counter so a burst of wrong codes cannot lock out normal
        # login and vice-versa). Reuses the login knobs (5 attempts / 5 min) — a single-digit curator
        # population entering a real 6-digit code will not trip it, but a brute-force stream will.
        self._totp_limiter = curator_auth.LoginRateLimiter(
            max_attempts=cfg.login_max_attempts, window_s=cfg.login_window_s)
        # Tracks submission ids with a live in-process publish task, so the poll-loop reconciliation
        # (design §5.4) can tell a genuinely-stuck PUBLISHING row (gateway restarted mid-publish) from
        # one this process is actively working on. A restart empties this set, so every PUBLISHING row
        # it finds is stuck by definition.
        self._publishing: set[str] = set()
        self._poll_task: asyncio.Task | None = None
        # Cap TOCTOU fix (design §4.2): the DB count is durable truth but is read then followed by an
        # await (body read) before the row is inserted, so N concurrent submits could all pass a bare
        # read-check. `_reserved` is an in-memory count of accepted-but-not-yet-inserted submissions,
        # incremented atomically the instant a submit passes the gate and decremented if it fails
        # before insert. count_inflight() + _reserved is the real live count. The event loop is
        # single-threaded, so incrementing _reserved between the check and the first await is
        # indivisible — no lock needed, and it never races a second coroutine mid-increment.
        self._reserved = 0

    async def _real_scan(self, data: bytes):
        return await clamd.scan_bytes(self.cfg.clamd_host, self.cfg.clamd_port, data)

    def close(self) -> None:
        self.db.close()

    # ---- upload ------------------------------------------------------------------------------

    async def handle_submit(self, request: Request, submit_key: str | None):
        auth = self._resolve_submit_auth(submit_key)
        if auth is None:
            # Uniform 401; no hint about whether the key was absent, wrong, revoked, or unknown.
            return JSONResponse({"detail": "unauthorized"}, status_code=401)

        # Capacity gate (design §4.2), reserved ATOMICALLY before the body read so N concurrent
        # submits cannot all slip past a bare read-check (cap TOCTOU). count_inflight() is durable
        # truth; _reserved covers the window between here and insert_submission(). The increment
        # below happens with no await between it and this check, so it is indivisible on the single
        # event loop — the reservation is held for the whole handler and released on any early return.
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if self.db.count_inflight() + self._reserved >= self.cfg.max_inflight:
            return JSONResponse({"detail": "too many in-flight submissions"}, status_code=429)
        if self.db.count_today(day) + self._reserved >= self.cfg.max_per_day:
            return JSONResponse({"detail": "daily submission cap reached"}, status_code=429)
        if _free_bytes(self.cfg.incoming_dir) < 3 * self.cfg.max_upload_bytes:
            return JSONResponse(
                {"detail": "insufficient disk headroom"}, status_code=503,
                headers={"Retry-After": "3600"},
            )
        self._reserved += 1
        try:
            return await self._handle_submit_reserved(request, auth)
        finally:
            self._reserved -= 1

    async def _handle_submit_reserved(self, request: Request, auth: "_SubmitAuth"):
        # Parse the multipart body under a hard total-byte cap that fires as bytes arrive (chunked-
        # safe, no Content-Length dependency) and spools only onto the measured incoming volume
        # (design §4.1 — see gateway/upload.py for why request.form() alone is unsafe here).
        submission_id = db.new_id()
        part_path = self.cfg.incoming_dir / f"{submission_id}.zip.part"
        final_path = self.cfg.incoming_dir / f"{submission_id}.zip"
        try:
            parsed = await upload_intake.parse_capped(
                request, self.cfg.max_upload_bytes, self.cfg.incoming_dir)
        except upload_intake.UploadTooLarge:
            return JSONResponse({"detail": "upload exceeds size limit"}, status_code=413)
        except upload_intake.MultiPartException as exc:
            return JSONResponse({"detail": f"malformed upload: {exc.message}"}, status_code=400)

        upload = parsed.file
        name = (parsed.fields.get("submitter_name") or "").strip()
        email = (parsed.fields.get("submitter_email") or "").strip()
        orcid = (parsed.fields.get("submitter_orcid") or "").strip()

        if upload is None or not hasattr(upload, "read"):
            return JSONResponse({"detail": "missing file"}, status_code=400)
        if not name or not email:
            return JSONResponse({"detail": "submitter_name and submitter_email are required"}, status_code=400)
        if orcid and not is_valid_orcid(orcid):
            return JSONResponse({"detail": "submitter_orcid failed checksum"}, status_code=400)

        # Copy the parsed file part to the .part file, re-enforcing the cap as the AUTHORITATIVE
        # per-file bound (the parse cap above allows framing overhead; this bounds the file alone).
        sha = hashlib.sha256()
        total = 0
        try:
            await upload.seek(0)
            with open(part_path, "wb") as fh:
                while True:
                    chunk = await upload.read(_UPLOAD_CHUNK)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.cfg.max_upload_bytes:
                        raise _Oversize()
                    sha.update(chunk)
                    fh.write(chunk)
                fh.flush()
                os.fsync(fh.fileno())
        except _Oversize:
            part_path.unlink(missing_ok=True)
            return JSONResponse({"detail": "upload exceeds size limit"}, status_code=413)
        except Exception:  # noqa: BLE001 -- any write failure must not leave a .part behind
            part_path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        # Zip central-directory safety (design §4.3) BEFORE promoting the part-file. A rejection here
        # writes nothing under quarantine/ and no DB row (design §8: rejected at upload, nothing in
        # quarantine).
        try:
            zipsafety.inspect(part_path, self.cfg.max_upload_bytes)
        except zipsafety.ZipRejection as rej:
            part_path.unlink(missing_ok=True)
            return JSONResponse({"detail": str(rej)}, status_code=400)

        digest = sha.hexdigest()
        dup = self.db.find_active_by_sha(digest)
        if dup is not None:
            part_path.unlink(missing_ok=True)
            return JSONResponse(
                {"detail": "duplicate submission", "submission_id": dup.id}, status_code=409
            )

        os.replace(part_path, final_path)  # atomic promote

        token = secrets.token_urlsafe(32)
        self.db.insert_submission(
            submission_id=submission_id, zip_sha256=digest, zip_bytes=total,
            submitter_name=name, submitter_email=email,
            submitter_orcid=(orcid or None), token_hash=_token_hash(token),
            uploader_name=auth.uploader_name,
        )
        # Stamp last_used on the DB key that authorised this submit (best-effort audit; a DB-key
        # uploader is the only one with a per-key usage signal). The env-bootstrap key has no row.
        if auth.uploader_key_id is not None:
            self.db.stamp_uploader_key_used(auth.uploader_key_id)

        # clamd scan of the raw zip (design §4.5). Fail closed: on ScanError the row STAYS RECEIVED
        # and the poll loop retries; only a definite clean advances to SCANNED + queues the job.
        await self._scan_and_advance(submission_id, final_path)

        return JSONResponse(
            {"submission_id": submission_id, "status_url": f"/gateway/status/{token}"},
            status_code=201,
        )

    async def _scan_and_advance(self, submission_id: str, zip_path: Path) -> None:
        try:
            data = await asyncio.to_thread(zip_path.read_bytes)
            result = await self._scan_bytes(data)
        except clamd.ScanError as exc:
            logger.info("clamd unavailable for %s (%s) — holding at RECEIVED", submission_id, exc)
            return
        if result.clean:
            self.db.transition(submission_id, states.SCANNED, actor="gateway",
                               reason="clamd clean")
            jobs.write_pending(self.cfg.jobs_dir, submission_id, zip_path,
                               self.cfg.quarantine_dir / submission_id)
        else:
            zip_path.unlink(missing_ok=True)
            self.db.transition(submission_id, states.REJECTED_AV, actor="gateway",
                               reason=f"virus signature: {result.signature}")

    # ---- status ------------------------------------------------------------------------------

    def handle_status(self, token: str) -> Response:
        # Hash-then-lookup, no early exit: an unknown token and a wiped-row token both fall through
        # to the same 404 with a byte-identical body (design §3).
        sub = self.db.get_by_token_hash(_token_hash(token))
        if sub is None:
            return Response(content=_STATUS_404_BODY, status_code=404,
                            media_type="text/plain", headers={"Cache-Control": "no-store"})
        validator_report, preview_summary, note = self._load_reports(sub)
        html = statuspage.render(
            submission_id=sub.id, state=sub.state, updated_utc=sub.updated_utc,
            validator_report=validator_report, preview_summary=preview_summary, note=note,
        )
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})

    def _load_reports(self, sub: db.Submission):
        """Pull the validator table / preview summary from the quarantine reports for a terminal
        submission. Absent files => empty (a QUARANTINED-before-reports submission still renders).
        The reason from the last transition is the note (AV verdict / failure cause)."""
        reports = self.cfg.quarantine_dir / sub.id / "reports"
        validator = _read_json(reports / "validate.json")
        preview = _read_json(reports / "preview-summary.json")
        trans = self.db.transitions_for(sub.id)
        note = trans[-1]["reason"] if trans else ""
        return validator, preview, note or ""

    # ---- poll loop ---------------------------------------------------------------------------

    async def poll_once(self) -> None:
        """One pass of the ingest/retry loop. Split out so tests drive it deterministically instead
        of waiting on the 5 s timer. Fully awaited (not fire-and-forget) so a test that calls
        poll_once() observes all resulting transitions synchronously afterward."""
        await self._retry_held()
        await self._ingest_done()
        self._requeue_dead()
        self._reconcile_publishing()
        self._purge_sessions()

    async def _retry_held(self) -> None:
        # Re-scan submissions still at RECEIVED (clamd was down at upload). Awaited in sequence so
        # the scanner is not hit concurrently for many rows (the poll interval bounds throughput).
        rows = self.db.ids_in_state(states.RECEIVED)
        for sid in rows:
            zip_path = self.cfg.incoming_dir / f"{sid}.zip"
            if zip_path.exists():
                await self._scan_and_advance(sid, zip_path)

    async def _ingest_done(self) -> None:
        done_dir = self.cfg.jobs_dir / "done"
        for path in sorted(done_dir.glob("*.json")):
            done = jobs.read_done(path)
            if done is None:
                logger.warning("ignoring malformed/forged done-file: %s", path.name)
                path.unlink(missing_ok=True)
                continue
            sub = self.db.get(done.submission_id)
            if sub is None or sub.state != states.SCANNED:
                # A done-file for an unknown or non-SCANNED submission cannot drive a transition
                # (design §8) — the state machine would reject it anyway; drop it explicitly.
                logger.warning("done-file for non-SCANNED submission %s ignored", done.submission_id)
                path.unlink(missing_ok=True)
                continue
            await self._apply_done(sub, done)
            self._archive_done(path, done.submission_id)

    async def _apply_done(self, sub: db.Submission, done: jobs.DoneFile) -> None:
        if done.outcome == jobs.OUTCOME_VALIDATED:
            # Second clamd sweep of the unpacked tree (design §5) — the runner had no network.
            hit = await self._post_unpack_sweep(sub.id)
            if hit is not None:
                self.db.transition(sub.id, states.QUARANTINED, actor="gateway",
                                   reason=f"av_post_unpack: {hit}")
                return
            slug = _slug_from_refs(done.report_refs)
            self.db.transition(sub.id, states.VALIDATED, actor="runner",
                               reason=done.reason or "validated", slug=slug,
                               report_ref="reports/validate.json")
        else:
            self.db.transition(sub.id, states.QUARANTINED, actor="runner",
                               reason=done.reason or "quarantined",
                               report_ref="reports/validate.json")

    async def _post_unpack_sweep(self, submission_id: str) -> str | None:
        """clamd-sweep every file under quarantine/<id>/package (bounded by the §4.3 member cap).
        Returns a signature string on a hit, None if clean. Fail closed: a sweep we could not
        complete returns a non-None sentinel so the caller quarantines (an incomplete sweep is not
        a clean one). Uses the injected scanner seam so tests need no real clamd."""
        pkg = self.cfg.quarantine_dir / submission_id / "package"
        if not pkg.exists():
            return None
        files = [p for p in pkg.rglob("*") if p.is_file()][: zipsafety.MAX_MEMBERS]
        for f in files:
            try:
                data = await asyncio.to_thread(f.read_bytes)
                res = await self._scan_bytes(data)
            except clamd.ScanError:
                return "post-unpack scan could not complete (fail closed)"
            if not res.clean:
                return res.signature or "unknown"
        return None

    def _requeue_dead(self) -> None:
        """A running/<id>.json older than 2x timeout => re-queue once; a second death => QUARANTINED
        'job died twice' (design §5). Tracked by a marker suffix so the second pass can tell a
        re-queued job from a first-timer."""
        running = self.cfg.jobs_dir / "running"
        if not running.exists():
            return
        cutoff = time.time() - 2 * self.cfg.job_timeout_s
        for path in sorted(running.glob("*.json")):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            sid = path.stem
            requeued_marker = running / f"{sid}.requeued"
            sub = self.db.get(sid)
            if sub is None or sub.state != states.SCANNED:
                path.unlink(missing_ok=True)
                continue
            if requeued_marker.exists():
                path.unlink(missing_ok=True)
                requeued_marker.unlink(missing_ok=True)
                self.db.transition(sid, states.QUARANTINED, actor="gateway",
                                   reason="job died twice")
            else:
                requeued_marker.write_text("1", encoding="utf-8")
                path.unlink(missing_ok=True)
                jobs.write_pending(self.cfg.jobs_dir, sid,
                                   self.cfg.incoming_dir / f"{sid}.zip",
                                   self.cfg.quarantine_dir / sid)

    def _archive_done(self, path: Path, submission_id: str) -> None:
        reports = self.cfg.quarantine_dir / submission_id / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            shutil.copy2(path, reports / "job-result.json")
        path.unlink(missing_ok=True)

    # ---- curator auth + session (C11 §2/§6) --------------------------------------------------

    def _curator_keys(self) -> dict[str, str]:
        """Parse AUSMT_CURATOR_KEYS on every use. Raises curator_auth.CuratorConfigError (a 503 at
        the route) if unset/malformed — fail closed: no configured curator identity means no curator
        route works (design §2). Cheap enough to parse per-request; not cached so a config change on
        restart takes effect and a broken config can never be masked by a stale good parse."""
        return curator_auth.parse_curator_keys(self.cfg.curator_keys)

    def _session_curator(self, request: Request) -> str | None:
        """Return the curator name for a valid, unexpired session cookie, else None. Purges the row
        if expired (absolute expiry, design §6) so a stale session cannot be replayed."""
        raw = request.cookies.get(curator_auth.SESSION_COOKIE)
        if not raw:
            return None
        row = self.db.get_session(curator_auth.hash_session_token(raw))
        if row is None:
            return None
        name, expires_utc = row
        now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if curator_auth.is_session_expired(expires_utc, now_utc):
            self.db.delete_session(curator_auth.hash_session_token(raw))
            return None
        return name

    def _raw_session(self, request: Request) -> str | None:
        return request.cookies.get(curator_auth.SESSION_COOKIE)

    def handle_curator_root(self, request: Request) -> Response:
        try:
            self._curator_keys()
        except curator_auth.CuratorConfigError:
            return self._curator_503()
        if self._session_curator(request) is not None:
            return RedirectResponse("/gateway/curator/queue", status_code=303)
        return self._html(curatorpage.render_login())

    def handle_curator_login(self, request: Request, curator_key: str | None) -> Response:
        try:
            keys = self._curator_keys()
        except curator_auth.CuratorConfigError:
            return self._curator_503()
        # ONE atomic decision (design §6, thread-safe): the blocked-check, the key match, and the
        # failure/success record all happen under the limiter's lock, so a burst of concurrent login
        # POSTs (this route is sync `def` → threadpool) cannot slip past the cap. A blocked window
        # refuses even a correct key, so brute force cannot outrun the limiter by occasionally
        # guessing right.
        outcome, name = self._login_limiter.evaluate(keys, curator_key or "")
        if outcome == "blocked":
            return HTMLResponse(curatorpage.render_login(error="Too many attempts — wait and retry."),
                                status_code=429, headers={"Retry-After": str(self.cfg.login_window_s),
                                                          "Cache-Control": "no-store"})
        if outcome == "denied" or name is None:
            return HTMLResponse(curatorpage.render_login(error="Invalid curator key."),
                                status_code=401, headers={"Cache-Control": "no-store"})
        token = secrets.token_urlsafe(32)
        self.db.create_session(curator_auth.hash_session_token(token), name, self.cfg.session_ttl_s)
        resp = RedirectResponse("/gateway/curator/queue", status_code=303)
        self._set_session_cookie(resp, token)
        return resp

    def handle_curator_logout(self, request: Request, csrf: str | None) -> Response:
        raw = self._raw_session(request)
        if raw is None:
            return RedirectResponse("/gateway/curator/", status_code=303)
        if not curator_auth.csrf_ok(raw, csrf):
            return self._forbidden("bad csrf token")
        self.db.delete_session(curator_auth.hash_session_token(raw))
        resp = RedirectResponse("/gateway/curator/", status_code=303)
        resp.delete_cookie(curator_auth.SESSION_COOKIE, path="/gateway/curator")
        return resp

    def handle_curator_queue(self, request: Request) -> Response:
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        rows = []
        for sub in self.db.queue(states.QUEUE_STATES):
            validator, _preview, _note = self._load_reports(sub)
            warn_count = 0
            items = (validator or {}).get("items") if isinstance(validator, dict) else None
            if isinstance(items, list):
                warn_count = sum(1 for i in items if isinstance(i, dict)
                                 and str(i.get("level") or i.get("status") or "").upper()
                                 in ("WARN", "WARNING"))
            rows.append({"id": sub.id, "slug": sub.slug, "submitter_name": sub.submitter_name,
                         "state": sub.state, "updated_utc": sub.updated_utc, "warn_count": warn_count})
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(request, active="queue", crumb="<b>Submission queue</b>")
        # C43 FR2-1: the queue page is purely the queue now (owner ruling, ratified 2026-07-11). The
        # serve-state panel moved to /gateway/curator/serve; the ever-present drift chip + that screen
        # own the served-vs-published job, so a second copy here was redundant.
        return self._html(curatorpage.render_queue(curator_name=name, rows=rows, csrf_token=csrf,
                                                   nav=nav))

    def _nav_context(self, request: Request, *, active: str, crumb: str) -> "curatorpage.NavContext":
        """Build the C43 nav-shell chrome inputs (S1-1) for a curator page. Reads the published
        surveys-live HEAD server-side (best-effort — degrades to 'unavailable', never 500s the page,
        exactly like the serve panel) and the session CSRF for the ever-present Request-rebuild button.
        The served-build id + currency verdict are filled BROWSER-side by context-bar.js."""
        published = serve_state.read_published_head(self._git_runner, self.cfg.surveys_live_dir)
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        return curatorpage.NavContext(
            active=active, crumb=crumb, published_head=published.short,
            published_available=published.available, csrf=csrf)

    def handle_rebuild_request(self, request: Request, csrf: str | None) -> Response:
        """POST /gateway/curator/rebuild (design §3, brief note 4): session + CSRF gated exactly like
        the uploader-key POSTs. Writes /gw/state/rebuild.request ATOMICALLY with {requested_at,
        requested_by} — AUDIT ONLY; the host reconcile agent keys on the file's EXISTENCE and never
        parses its content (zero-argument by design). Idempotent (a second press overwrites the same
        file). Fails CLOSED with a 503 if the state dir is missing/unwritable (mirrors the house
        curator-503 style) rather than pretending the request was queued. On success, redirects to the
        serve-state screen's panel (303) — C43 FR2-1 moved the serve panel (and its pending indicator)
        off the queue page to /gateway/curator/serve, so that is where the curator lands to see the
        'rebuild requested — pending' state (matching how the other curator form posts respond)."""
        curator = self._session_curator(request)
        if curator is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, csrf):
            return self._forbidden("bad csrf token")
        try:
            serve_state.write_rebuild_request(self.cfg.state_dir, requested_by=curator)
        except serve_state.StateDirUnwritable as exc:
            logger.warning("rebuild request could not be recorded (fail closed): %s", exc)
            return JSONResponse({"detail": "rebuild request could not be recorded"}, status_code=503,
                                headers={"Cache-Control": "no-store"})
        return RedirectResponse("/gateway/curator/serve#serve-state", status_code=303)

    def handle_serve_state(self, request: Request) -> Response:
        """GET /gateway/curator/serve — the first-class serve-state screen (C43 S2b-i, record D8/D15).
        The existing serve panel (published HEAD, served build + currency, per-survey build report,
        last reconcile) PLUS the operations floor: the reconcile SYNC strip, four cards (Backups,
        Alerts, Box, Freshness), and the retained-builds + backup-snapshots tables — all READ-ONLY (no
        privileged action rendered). The ops facts come from ops-status.json read SERVER-side (the
        reconcile-status.json seam — serve_state.read_ops_status; no new mount, C40 intact). Every
        read is best-effort: published HEAD degrades to 'unavailable', a missing/stale ops-status.json
        flips every dependent card to an explicit STALE state — the page never 500s. `def` (blocking
        file/git reads run in Starlette's threadpool, matching the queue rationale)."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        published = serve_state.read_published_head(self._git_runner, self.cfg.surveys_live_dir)
        status = serve_state.read_reconcile_status(self.cfg.state_dir)
        pending = serve_state.rebuild_request_pending(self.cfg.state_dir)
        ops = serve_state.read_ops_status(self.cfg.state_dir)
        ops_stale = serve_state.ops_status_stale(ops)
        nav = self._nav_context(request, active="serve", crumb="<b>Serve state</b>")
        return self._html(curatorpage.render_serve_page(
            published_head=published.short, published_available=published.available,
            status=status, pending=pending, csrf_token=csrf, ops=ops, ops_stale=ops_stale, nav=nav))

    def handle_serve_build_detail(self, request: Request, build_ref: str) -> Response:
        """GET /gateway/curator/serve/build/{build_ref} — read-only build forensics (S2b-i B4). Matches
        build_ref against the ops-status.json inventory SERVER-side (serve_state.read_ops_status +
        curatorpage.find_build) — NEVER a filesystem path build, so a hostile ref just fails to match
        and yields a 'no such build' page, never a traversal. Renders identity + the C18-A4 cache
        counters (salt_fp / write_errors / read_errors) + the build log tail. NO serve/rollback action
        (Stage 2b-ii). A stale/missing ops-status.json renders an explicit STALE state."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        ops = serve_state.read_ops_status(self.cfg.state_dir)
        ops_stale = serve_state.ops_status_stale(ops)
        build = curatorpage.find_build(ops, build_ref)
        generated_at = ops.get("generated_at") if isinstance(ops, dict) else None
        # The single newest build log (ops-status logs.build) belongs to the NEWEST build — associate
        # it only there, so an older retained build never claims a log that is not its own.
        log_tail = None
        if isinstance(ops, dict) and build is not None:
            blist = ops.get("builds") or []
            if blist and isinstance(blist[0], dict) and blist[0].get("dir") == build_ref:
                log_tail = (ops.get("logs") or {}).get("build")
        nav = self._nav_context(request, active="serve",
                                crumb='<a href="/gateway/curator/serve">Serve state</a> › '
                                      f'<b>{curatorpage._esc(build_ref)}</b>')  # noqa: SLF001
        return self._html(curatorpage.render_build_detail(
            build=build, generated_at=generated_at, log_tail=log_tail, ops_stale=ops_stale, nav=nav))

    def handle_curator_ui_js(self, request: Request) -> Response:
        """GET /gateway/curator/ui.js — the shared curator-page behaviours (delegated data-confirm /
        data-toggle-big handlers) as an external same-origin script. The strictPages CSP blocks
        BOTH inline script blocks and inline on*-attribute handlers on every /gateway/* page —
        three shipped inline and silently never ran (found 2026-07-08: the Reject and Revoke
        confirms and the preview size toggle). Deliberately UNGATED (review C2): the LOGIN page
        loads it via the shared shell before any session exists — a gate here means every login
        view fetches JS, gets a 303 to HTML, and logs a nosniff console error. The content is a
        static public-repo constant; there is nothing to protect."""
        return Response(curatorpage.CURATOR_UI_JS,
                        media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    def handle_serve_state_js(self, request: Request) -> Response:
        """GET /gateway/curator/serve-state.js — the serve-state panel's JS as a same-origin EXTERNAL
        script. Exists because the Caddyfile's strictPages CSP (script-src 'self', applied to every
        /gateway/* page) BLOCKS inline script blocks — the first install shipped the panel JS
        inline and the browser never executed it. 'self' permits this URL. Session-gated for
        consistency with the page that references it (the code is public-repo — the gate is
        consistency, not secrecy)."""
        name = self._require_session(request)
        if not isinstance(name, str):
            return name
        return Response(curatorpage.SERVE_PANEL_JS,
                        media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    def handle_context_bar_js(self, request: Request) -> Response:
        """GET /gateway/curator/context-bar.js — the nav-shell drift chip's served-build half as a
        same-origin EXTERNAL script (C43 Stage 1). Same CSP reason as serve-state.js/ui.js: the
        strictPages script-src 'self' blocks inline scripts, so the chip's /data/build.json fetch lives
        behind this route. Session-gated for consistency with the pages that reference it (the code is
        a public-repo constant; the gate is consistency, not secrecy). DEGRADES without it — the chip
        shows the server-rendered published HEAD and a '…' served build, never breaking the page."""
        name = self._require_session(request)
        if not isinstance(name, str):
            return name
        return Response(curatorpage.CONTEXT_BAR_JS,
                        media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    def handle_survey_hub_js(self, request: Request) -> Response:
        """GET /gateway/curator/survey-hub.js — the survey hub's browser-side script (C43 Stage 1):
        the Overview & QA tab's /data/build_report.json + /data/build.json render AND the Metadata
        tab's one-section-at-a-time TOC enhancement. Same CSP reason as the other external scripts
        (script-src 'self' blocks inline). Session-gated for consistency; the content is a public-repo
        constant. DEGRADES: the Overview placeholders stay, and the Metadata sections render stacked
        and fully functional without it."""
        name = self._require_session(request)
        if not isinstance(name, str):
            return name
        return Response(curatorpage.SURVEY_HUB_JS,
                        media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    def handle_stations_js(self, request: Request) -> Response:
        """GET /gateway/curator/stations.js — the C43 Stage-2a Stations tab's browser-side script (the
        filterable table, drill-down facts panel, hand-built SVG response-curve plots + quadrant
        verdicts, [FC-2] lag label). Same CSP reason as the other external scripts (script-src 'self'
        blocks inline). Session-gated for consistency; the content is a public-repo constant. DEGRADES:
        without it the Stations tab shows only its loading placeholder, the page never breaks."""
        name = self._require_session(request)
        if not isinstance(name, str):
            return name
        return Response(curatorpage.STATIONS_JS,
                        media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    def handle_surveys_list_js(self, request: Request) -> Response:
        """GET /gateway/curator/surveys-list.js — the Surveys list's browser-side enrichment (C43
        FR2-1): fill the display name / version / licence / served station-count columns from the
        served /data corpus (surveys.json + build_report.json), the serve-panel pattern (script-src
        'self' blocks inline). Session-gated for consistency; the content is a public-repo constant.
        DEGRADES: without it every row still shows its slug + the hub link, the page never breaks."""
        name = self._require_session(request)
        if not isinstance(name, str):
            return name
        return Response(curatorpage.SURVEYS_LIST_JS,
                        media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    def handle_editor_ui_js(self, request: Request) -> Response:
        """GET /gateway/curator/editor.js — the metadata-editor's repeatable-row add/remove behaviour
        as a same-origin EXTERNAL script. Same CSP reason as serve-state.js/ui.js: the strictPages
        script-src 'self' blocks inline scripts, so the row JS lives behind this route. Session-gated
        for consistency with the edit page that references it (the code is a public-repo constant; the
        gate is consistency, not secrecy). The behaviour DEGRADES without JS — the form renders spare
        blank rows server-side — so a 404 here would not break adding entries, only the +/- buttons."""
        name = self._require_session(request)
        if not isinstance(name, str):
            return name
        return Response(curatorpage.EDITOR_UI_JS,
                        media_type="application/javascript; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    def handle_curator_detail(self, request: Request, submission_id: str) -> Response:
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        if not db.is_valid_id(submission_id):
            return self._not_found()
        sub = self.db.get(submission_id)
        if sub is None:
            return self._not_found()
        validator, preview, _note = self._load_reports(sub)
        trans = self.db.transitions_for(sub.id)
        last_note = trans[-1]["reason"] if trans else ""
        cl = self._build_checklist(sub, validator, preview)
        preview_index = (self.cfg.quarantine_dir / sub.id / "reports" / "preview-data" / "index.html")
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        # C43 FR2-1: the detail page joins the nav shell (full width, two-column review layout).
        nav = self._nav_context(request, active="queue",
                                crumb='<a href="/gateway/curator/queue">Submission queue</a> › '
                                      f'<b>{curatorpage._esc(sub.id[:12])}</b>')  # noqa: SLF001
        html_out = curatorpage.render_detail(
            submission_id=sub.id, state=sub.state, updated_utc=sub.updated_utc,
            submitter_name=sub.submitter_name, submitter_email=sub.submitter_email,
            submitter_orcid=sub.submitter_orcid, validate_report=validator,
            preview_summary=preview, cl=cl, csrf_token=csrf, note=last_note or "",
            has_preview=preview_index.exists(), nav=nav)
        return self._html(html_out)

    def _build_checklist(self, sub: db.Submission, validator, preview) -> checklist_mod.Checklist:
        pkg = self.cfg.quarantine_dir / sub.id / "package"
        preview_dir = self.cfg.quarantine_dir / sub.id / "reports" / "preview-data"
        return checklist_mod.build(
            validate_report=validator, preview_summary=preview, submission_slug=sub.slug,
            submitter_email=sub.submitter_email, package_dir=pkg, preview_dir=preview_dir)

    # ---- uploader keys (schema v2 — curator-managed submit keys) ------------------------------

    def handle_uploaders(self, request: Request, error: str = "", status_code: int = 200) -> Response:
        """GET the uploader-key page: the create form + the list of issued keys (active and revoked).
        Session-gated exactly like the other curator GET pages. The list carries curator-only PII
        (uploader email) but NEVER a plaintext key (only key_sha256 is stored; the plaintext was shown
        once at creation)."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        keys = self.db.list_uploader_keys()
        # D7 submission counts from the audit trail (best-effort; a DB hiccup must not 500 the page —
        # the counts are an operator aid, and an empty map renders 0 for every key).
        try:
            counts = self.db.submission_counts_by_uploader()
        except Exception:  # noqa: BLE001 -- a count read must never break the key-management page
            logger.warning("uploader submission-count read failed — rendering zeros")
            counts = {}
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(request, active="uploaders", crumb="<b>Uploader keys</b>")
        return self._html(curatorpage.render_uploaders(
            curator_name=name, keys=keys, csrf_token=csrf, error=error,
            submission_counts=counts, nav=nav),
            status_code=status_code)

    def handle_uploader_create(self, request: Request, name_field: str | None,
                               email_field: str | None, csrf: str | None) -> Response:
        """POST create: session + CSRF gated. Mints a key, stores ONLY its sha256, and shows the
        plaintext ONCE (never persisted, never retrievable). A duplicate name is refused with a clear
        409 — the DB UNIQUE(name) constraint is the single source of truth (no read-then-insert race).
        Creation is audit-logged via the row's created_by = the curator's name."""
        curator = self._session_curator(request)
        if curator is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, csrf):
            return self._forbidden("bad csrf token")
        name = (name_field or "").strip()
        email = (email_field or "").strip() or None
        if not name:
            return self.handle_uploaders(request, error="A name is required.", status_code=400)
        # F5 (fix-round): modest server-side caps, consistent with the note cap — refused, not truncated.
        if len(name) > _KEY_NAME_MAX_CHARS:
            return self.handle_uploaders(
                request, error=f"Name too long ({len(name)} chars; max {_KEY_NAME_MAX_CHARS}).",
                status_code=400)
        if email and len(email) > _KEY_EMAIL_MAX_CHARS:
            return self.handle_uploaders(
                request, error=f"Email too long ({len(email)} chars; max {_KEY_EMAIL_MAX_CHARS}).",
                status_code=400)
        key = uploader_keys_mod.mint_key()
        try:
            self.db.create_uploader_key(
                name=name, email=email, key_sha256=uploader_keys_mod.key_hash(key),
                created_by=curator)
        except sqlite3.IntegrityError:
            # UNIQUE(name) (or the vanishingly-unlikely UNIQUE(key_sha256)) collision — refuse with a
            # clear message and create nothing (the plaintext above is discarded, never shown).
            return self.handle_uploaders(
                request, error=f"An uploader key named {name!r} already exists — names must be unique.",
                status_code=409)
        return self._html(curatorpage.render_uploader_created(
            curator_name=curator, name=name, key=key))

    def handle_uploader_revoke(self, request: Request, key_id: int, csrf: str | None) -> Response:
        """POST revoke: session + CSRF gated. Sets revoked_utc/revoked_by (audit); the row STAYS
        listed (no delete). Idempotent — revoking an unknown/already-revoked id redirects back without
        error rather than leaking whether the id existed."""
        curator = self._session_curator(request)
        if curator is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, csrf):
            return self._forbidden("bad csrf token")
        self.db.revoke_uploader_key(key_id, revoked_by=curator)
        return RedirectResponse("/gateway/curator/uploaders", status_code=303)

    def handle_uploader_note(self, request: Request, key_id: int, note: str | None,
                             csrf: str | None) -> Response:
        """POST set-note (C43 D7): session + CSRF gated. Stores a free-text curator annotation on an
        ACTIVE key — SQLITE ONLY, never a git-bound path (the PII-containment invariant, D2.5).

        F6 (fix-round, architect ruling): a REVOKED key is a READ-ONLY audit row (record D7) — a note
        POST to a revoked id is REFUSED with 409 and changes nothing (the UI already hides the editor;
        this is the server-side enforcement, plus the DB layer's own `AND revoked_utc IS NULL` guard).
        An UNKNOWN id keeps the idempotent no-oracle redirect (matching revoke's posture).

        F5 (fix-round): the note is capped at _NOTE_MAX_CHARS server-side — an over-length POST is
        REFUSED with 400 (rejected, not truncated: silently dropping the tail of a curator's note
        loses information without telling them; the 400 matches the house 'a decision note is
        required' style). The textarea carries maxlength as client courtesy; this is the gate.

        An empty note clears it (stored NULL). Never touches key material or the lifecycle."""
        curator = self._session_curator(request)
        if curator is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, csrf):
            return self._forbidden("bad csrf token")
        # CRLF-normalise like the editor scalars so a textarea edit never embeds a lone \r.
        clean = (note or "").replace("\r\n", "\n").replace("\r", "\n")
        if len(clean) > _NOTE_MAX_CHARS:
            return JSONResponse(
                {"detail": f"note too long ({len(clean)} chars; max {_NOTE_MAX_CHARS})"},
                status_code=400, headers={"Cache-Control": "no-store"})
        key = self.db.get_uploader_key(key_id)
        if key is not None and key.revoked_utc is not None:
            # F6: revoked = read-only audit row; the note is frozen at revocation time.
            return JSONResponse(
                {"detail": "this key is revoked — a revoked key is a read-only audit row"},
                status_code=409, headers={"Cache-Control": "no-store"})
        self.db.set_uploader_key_note(key_id, note=clean)
        return RedirectResponse("/gateway/curator/uploaders", status_code=303)

    # ---- curator security: TOTP second factor (schema v4 — C41 D2) ---------------------------

    def _totp_state(self, curator_name: str) -> tuple[str, str | None]:
        """Map the stored TOTP row to a page state: ('none'|'pending'|'active', enrolled_utc)."""
        row = self.db.get_totp(curator_name)
        if row is None:
            return "none", None
        if not row.active:
            return "pending", None
        return "active", row.enrolled_utc

    def handle_security(self, request: Request, error: str = "", status_code: int = 200) -> Response:
        """GET the Security page: shows the curator's enrolment state (none/pending/active). Session-
        gated like the other curator GET pages. NEVER renders the secret (it is shown once, only as the
        direct response to enrol/rotate)."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        state, enrolled = self._totp_state(name)
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(request, active="security", crumb="<b>Security</b>")
        return self._html(curatorpage.render_security(
            curator_name=name, csrf_token=csrf, state=state, enrolled_utc=enrolled,
            error=error, nav=nav), status_code=status_code)

    def _security_page_with_secret(self, request: Request, name: str, secret: str) -> Response:
        """Render the Security page with the SHOW-ONCE secret + otpauth URI (the response to a begin or
        a rotate). The secret is displayed here and never again."""
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(request, active="security", crumb="<b>Security</b>")
        uri = totp.otpauth_uri(secret, account=name)
        return self._html(curatorpage.render_security(
            curator_name=name, csrf_token=csrf, state="pending", secret=secret,
            otpauth_uri=uri, nav=nav))

    def handle_security_enrol(self, request: Request, csrf: str | None) -> Response:
        """POST begin-enrolment: session + CSRF gated. Generates a fresh secret, stores it as a PENDING
        enrolment (not active), and shows it ONCE with the activate form. Refused when an enrolment is
        already ACTIVE — an active secret is rotated (with the current code), never silently replaced by
        a session-only begin (that would be the collapse D2 forbids)."""
        curator = self._session_curator(request)
        if curator is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, csrf):
            return self._forbidden("bad csrf token")
        row = self.db.get_totp(curator)
        if row is not None and row.active:
            return self.handle_security(
                request, error="You are already enrolled. Use Rotate (with your current code) to "
                                "replace the secret.", status_code=409)
        secret = totp.generate_secret()
        self.db.begin_totp_enrolment(curator, secret)
        return self._security_page_with_secret(request, curator, secret)

    def handle_security_activate(self, request: Request, code: str | None,
                                 csrf: str | None) -> Response:
        """POST activate: session + CSRF gated + rate-limited. Verifies `code` against the PENDING
        secret and, on success, marks the enrolment ACTIVE (the activating step is recorded as used so
        it cannot be replayed to gate a deletion). Fail-closed: no pending enrolment, a wrong/absent
        code, or a tripped rate limit => the page re-renders with an error and NOTHING is activated."""
        curator = self._session_curator(request)
        if curator is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, csrf):
            return self._forbidden("bad csrf token")
        row = self.db.get_totp(curator)
        if row is None or row.active:
            return self.handle_security(
                request, error="There is no pending enrolment to activate. Begin enrolment first.",
                status_code=409)
        if self._totp_limiter.blocked():
            return self.handle_security(
                request, error="Too many code attempts — wait and retry.", status_code=429)
        step = totp.verify(code or "", row.secret)
        if step is None:
            self._totp_limiter.record_failure()
            return self.handle_security(
                request, error="That code did not match — check your authenticator and try again.",
                status_code=400)
        self._totp_limiter.record_success()
        # activate_totp only fires on a still-pending row; a concurrent activate that already flipped
        # it returns False, which we surface as "already active" rather than a spurious error.
        self.db.activate_totp(curator, step)
        return self.handle_security(
            request, error="")  # renders the now-active state

    def handle_security_rotate(self, request: Request, code: str | None,
                               csrf: str | None) -> Response:
        """POST rotate: session + CSRF gated + rate-limited. Requires a valid CURRENT code from the
        ACTIVE enrolment (the collapse guard — a session alone must never rotate the secret, D2). On a
        valid current code, generates a NEW secret, stages it as PENDING (the old one is retired), and
        shows it once. Fail-closed: not active, a wrong/absent current code, or a tripped rate limit =>
        the page re-renders with an error and the existing secret is UNCHANGED."""
        curator = self._session_curator(request)
        if curator is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, csrf):
            return self._forbidden("bad csrf token")
        row = self.db.get_totp(curator)
        if row is None or not row.active:
            return self.handle_security(
                request, error="You are not enrolled, so there is nothing to rotate. Begin enrolment.",
                status_code=409)
        if self._totp_limiter.blocked():
            return self.handle_security(
                request, error="Too many code attempts — wait and retry.", status_code=429)
        # The CURRENT-code check is the collapse guard: verify against the ACTIVE secret. Dropping this
        # check (a mutation) would let a session-only rotation through — the collapse-guard pin.
        step = totp.verify(code or "", row.secret)
        if step is None:
            self._totp_limiter.record_failure()
            return self.handle_security(
                request, error="Rotation requires a valid CURRENT code from your existing "
                                "authenticator.", status_code=400)
        self._totp_limiter.record_success()
        secret = totp.generate_secret()
        self.db.begin_totp_enrolment(curator, secret)  # stages the new secret as pending (old retired)
        return self._security_page_with_secret(request, curator, secret)

    # ---- C31 metadata editor -----------------------------------------------------------------

    def handle_edit_list(self, request: Request) -> Response:
        """List PUBLISHED surveys editable in v1 (C31 §1.1): a directory listing of surveys-live —
        NEVER content parsing (the survey.yaml presence check is a stat, not a load)."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        slugs = metaedit.list_published_slugs(self.cfg.surveys_live_dir)
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(request, active="surveys", crumb="<b>Surveys</b>")
        return self._html(curatorpage.render_edit_list(
            curator_name=name, slugs=slugs, csrf_token=csrf, nav=nav))

    def handle_survey_hub(self, request: Request, slug: str, tab: str = "overview") -> Response:
        """The per-survey hub (C43 Stage 1 S1-2; C43-HUB header treatment). Overview & QA (default) /
        Stations / Metadata / History, inside the nav shell. EVERY tab runs the metadata read-job so
        the mockup's header (title + slug chip + orientation line) renders hub-wide — strict on the
        Metadata tab (the editor is useless without fields, so a failure bounces to the list),
        DEGRADABLE elsewhere (header falls back to the slug). Tab content beyond the header stays
        browser-populated from /data (Overview/Stations) or runner read-jobs (History). Sync `def`
        route -> the seam's bounded blocking poll runs in Starlette's threadpool."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        tab = tab if tab in ("overview", "stations", "metadata", "history") else "overview"
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(request, active="surveys",
                                crumb=f'<a href="/gateway/curator/edit">Surveys</a> › '
                                      f'<b>{curatorpage._esc(slug)}</b>')  # noqa: SLF001
        version = None
        fields: dict = {}
        commits: list = []
        history_error = ""
        if tab == "metadata":
            try:
                result = self._edit_runner(metaedit.make_read_job(slug))
            except metaedit.EditRunnerError as exc:
                logger.warning("survey-hub read-job failed for %s: %s", slug, exc)
                return self.handle_edit_list(request)
            if not result.get("ok"):
                return self.handle_edit_list(request)
            version = result.get("version")
            fields = result.get("fields") or {}
        else:
            # C43-HUB H1: every tab renders the mockup's header (title + slug chip + orientation
            # line from version/licence/access/collection), so the read-job runs hub-wide. On the
            # non-metadata tabs it DEGRADES instead of bouncing: a failed read renders the header
            # with the slug and no orientation segments — the tab's own content is unaffected.
            try:
                result = self._edit_runner(metaedit.make_read_job(slug))
            except metaedit.EditRunnerError as exc:
                logger.warning("survey-hub read-job failed for %s (header degrades): %s", slug, exc)
                result = None
            if result and result.get("ok"):
                version = result.get("version")
                fields = result.get("fields") or {}
        if tab == "history":
            # The runner OWNS the git read (record D4 / S2a-2): enqueue a `history` read-job and render
            # the returned commit list. A runner error/refusal degrades to a curator-facing message on
            # the tab (never a 500, never a blank page) — the audit trail is informational, not gating.
            try:
                result = self._edit_runner(metaedit.make_history_job(slug))
            except metaedit.EditRunnerError as exc:
                logger.warning("survey-hub history-job failed for %s: %s", slug, exc)
                history_error = f"the history could not be read: {exc}"
            else:
                if result.get("ok"):
                    commits = result.get("commits") or []
                else:
                    history_error = result.get("error") or "the history could not be read"
        # [FC-2] served-vs-published lag label for the Stations panel: computed server-side from the
        # published HEAD (the served build id is browser-filled by the stations JS, which compares).
        build_lag = self._build_lag_hint() if tab == "stations" else None
        return self._html(curatorpage.render_survey_hub(
            slug=slug, tab=tab, version=version, fields=fields, csrf_token=csrf, nav=nav,
            commits=commits, history_error=history_error, build_lag=build_lag))

    def _build_lag_hint(self) -> dict:
        """The server-side half of the Stations [FC-2] lag label: the published surveys-live HEAD (or
        None). The stations JS fetches /data/build.json browser-side, reads its build_id + source_commit,
        and — when the served source_commit differs from this published HEAD — renders the
        'facts from build <build_id> — publish pending' label ON THE PANEL (not only the drift chip).
        Best-effort: an unavailable HEAD just means the JS cannot judge lag and shows no label."""
        published = serve_state.read_published_head(self._git_runner, self.cfg.surveys_live_dir)
        return {"published_head": published.short if published.available else None}

    def handle_edit_form(self, request: Request, slug: str, error: str = "",
                         field_errors: list | None = None, submitted: dict | None = None) -> Response:
        """Open the edit form for a published survey (C31 §1.2): the gateway enqueues a `read`
        edit-job on the jobs/edit/ queue, the gw-runner returns the editable subset as JSON, the
        gateway renders the seeded form. This handler is a sync `def` route, so the seam's bounded
        blocking poll runs in Starlette's threadpool — never on the event loop (review FIX 4).
        `field_errors` (a list of editor_form.SectionError) re-renders the per-section widget
        annotations after a failed preview; `submitted` (the raw form dict) re-prefills the widgets
        with the curator's typed values so a validation error never discards their work."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        try:
            result = self._edit_runner(metaedit.make_read_job(slug))
        except metaedit.EditRunnerError as exc:
            logger.warning("edit read-job failed for %s: %s", slug, exc)
            return self._html(curatorpage.render_edit_list(
                curator_name=name, slugs=metaedit.list_published_slugs(self.cfg.surveys_live_dir),
                csrf_token=curator_auth.csrf_token_for(self._raw_session(request))), status_code=500)
        if not result.get("ok"):
            return self.handle_edit_list(request)
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(
            request, active="surveys",
            crumb=f'<a href="/gateway/curator/edit">Surveys</a> › '
                  f'<a href="/gateway/curator/survey/{curatorpage._esc(slug)}">'  # noqa: SLF001
                  f'{curatorpage._esc(slug)}</a> › <b>edit metadata</b>')  # noqa: SLF001
        return self._html(curatorpage.render_edit_form(
            slug=slug, version=result.get("version"), fields=result.get("fields") or {},
            csrf_token=csrf, error=error, field_errors=field_errors, submitted=submitted, nav=nav))

    async def handle_edit_preview(self, request: Request, slug: str, form: dict) -> Response:
        """Submit the edit (C31 §1.3/§1.4): build the patch from the form, enqueue a `merge`
        edit-job, render the returned diff + validator verdict. Session + CSRF gated. The seam's
        blocking poll runs via asyncio.to_thread so the single-worker event loop keeps serving
        (review FIX 4)."""
        name = self._session_curator(request)
        if name is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, form.get("csrf_token")):
            return self._forbidden("bad csrf token")
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        note = (form.get("note") or "").strip()
        bump = (form.get("bump") or "patch").strip()
        if bump not in ("patch", "minor", "major"):
            bump = "patch"
        patch, patch_errors = self._build_patch(form)
        if patch_errors:
            # Per-field validation failures (bad ORCID/DOI/date/level, malformed advanced JSON):
            # re-render the form with each error rather than a blanket failure (C31 §2, deliverable
            # 12). The errors carry the section so the renderer can annotate the right widget block,
            # and the submitted form is passed back so the curator's typed values survive the round
            # (never silently discarded — the old blanket path lost them).
            return self.handle_edit_form(request, slug, field_errors=patch_errors,
                                         submitted=form)
        # The runner alone loads the current version; it resolves the bump KIND to a concrete semver
        # and enforces semver-greater (all version logic stays runner-side, C31 §0.3). The gateway
        # passes only the bump kind, so preview and confirm reproduce identical bytes deterministically.
        merge = metaedit.make_merge_job(slug, patch, bump, note,
                                        time.strftime("%Y-%m-%d", time.gmtime()))
        try:
            result = await asyncio.to_thread(self._edit_runner, merge)
        except metaedit.EditRunnerError as exc:
            logger.warning("edit merge-job failed for %s: %s", slug, exc)
            return self.handle_edit_form(request, slug,
                                         error=f"the edit could not be processed: {exc}")
        if not result.get("ok"):
            return self.handle_edit_form(request, slug, error=result.get("error") or "edit refused")
        csrf = curator_auth.csrf_token_for(raw)
        nav = self._nav_context(
            request, active="surveys",
            crumb=f'<a href="/gateway/curator/edit">Surveys</a> › '
                  f'<a href="/gateway/curator/survey/{curatorpage._esc(slug)}">'  # noqa: SLF001
                  f'{curatorpage._esc(slug)}</a> › <b>preview edit</b>')  # noqa: SLF001
        import json as _json
        return self._html(curatorpage.render_edit_preview(
            slug=slug, version=result.get("new_version") or "", diff=result.get("diff") or "",
            validate_report=result.get("validator"), has_fail=bool(result.get("has_fail")),
            new_sha256=result.get("new_sha256") or "", note=note,
            patch_json=_json.dumps(patch), bump=bump, csrf_token=csrf, nav=nav))

    async def handle_edit_confirm(self, request: Request, slug: str, form: dict) -> Response:
        """Confirm + commit (C31 §1.5): re-run the merge server-side to reproduce the EXACT bytes,
        re-hash and 409 on any mismatch with the previewed sha (§0.6), then commit+push through the
        publish primitives under PUBLISH_LOCK with byte-exact rollback on failure. Session + CSRF."""
        name = self._session_curator(request)
        if name is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, form.get("csrf_token")):
            return self._forbidden("bad csrf token")
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        expected_sha = (form.get("new_sha256") or "").strip()
        bump = (form.get("bump") or "patch").strip()
        if bump not in ("patch", "minor", "major"):
            bump = "patch"
        note = (form.get("note") or "").strip()
        import json as _json
        try:
            patch = _json.loads(form.get("patch_json") or "{}")
        except ValueError:
            return self._forbidden("malformed confirm payload")
        if not isinstance(patch, dict):
            return self._forbidden("malformed confirm payload")
        # Re-run the merge to regenerate the exact bytes the curator confirmed (no yaml in the gateway
        # — the gw-runner does it). This is the authoritative artifact; the §0.6 hash pin is checked
        # against it at commit time inside publish.commit_metadata_edit. Blocking poll off the loop
        # via to_thread (review FIX 4).
        merge = metaedit.make_merge_job(slug, patch, bump, note,
                                        time.strftime("%Y-%m-%d", time.gmtime()))
        try:
            result = await asyncio.to_thread(self._edit_runner, merge)
        except metaedit.EditRunnerError as exc:
            logger.warning("edit confirm merge-job failed for %s: %s", slug, exc)
            return JSONResponse({"detail": "the edit could not be processed"}, status_code=500)
        if not result.get("ok"):
            return JSONResponse({"detail": result.get("error") or "edit refused"}, status_code=409)
        if result.get("has_fail"):
            # A validator FAIL at confirm time is the §0.4 server-side guarantee, independent of the UI.
            return JSONResponse({"detail": "validator FAILED on the edited survey"}, status_code=409)
        if not expected_sha or result.get("new_sha256") != expected_sha:
            return JSONResponse(
                {"detail": "preview is stale (content hash mismatch) — re-open the edit"},
                status_code=409)
        # Reconstruct the EXACT bytes from base64 (never the lossy display string) so what is committed
        # is byte-identical to what was hashed; commit_metadata_edit re-hashes and 409s on any drift.
        import base64
        try:
            new_yaml = base64.b64decode(result.get("new_yaml_b64") or "")
        except (ValueError, TypeError):
            return JSONResponse({"detail": "the edit could not be processed"}, status_code=500)
        return await self._commit_edit(slug, new_yaml, expected_sha, name, note)

    async def _commit_edit(self, slug: str, new_yaml: bytes, expected_sha: str, curator: str,
                           note: str) -> Response:
        surveys_live = self.cfg.surveys_live_dir
        if surveys_live is None:
            return JSONResponse({"detail": "AUSMT_SURVEYS_LIVE is not configured"}, status_code=503)
        try:
            safe_slug = publish.validate_slug(slug)
        except publish.PublishError as exc:
            return JSONResponse({"detail": exc.message}, status_code=400)
        async with publish.PUBLISH_LOCK:
            try:
                await asyncio.to_thread(
                    self._commit_edit_blocking, surveys_live, safe_slug, new_yaml, expected_sha,
                    curator, note)
            except publish.PublishError as exc:
                logger.warning("metadata edit publish failed for %s at %s: %s",
                               slug, exc.phase, exc.message)
                # Fail-closed: surveys-live was rolled back byte-for-byte inside commit_metadata_edit.
                return JSONResponse({"detail": f"publish failed: {exc.message}"}, status_code=409)
        return self._html(
            curatorpage._page(  # noqa: SLF001 -- reuse the page chrome for the terminal confirmation
                f"AusMT edit committed {slug}",
                f'<h1>Metadata edit committed — {curatorpage._esc(slug)}</h1>'  # noqa: SLF001
                '<p class="sub">Committed to surveys-live and pushed. The serve-reconcile agent '
                'rebuilds and serves it automatically on its next tick (typically within 15 '
                'minutes) — see the serve-state panel on the queue page, or run '
                '<code>make rebuild-data</code> by hand.</p>'
                '<p><a href="/gateway/curator/queue">back to queue</a></p>'))

    def _commit_edit_blocking(self, surveys_live: Path, slug: str, new_yaml: bytes,
                              expected_sha: str, curator: str, note: str) -> None:
        pre = publish.preflight(self._git_runner, surveys_live)
        publish.commit_metadata_edit(self._git_runner, surveys_live, slug, new_yaml, expected_sha,
                                     curator, note, pre)

    # ---- C31 station (EDI) removal -----------------------------------------------------------

    def handle_stations_list(self, request: Request, slug: str, error: str = "") -> Response:
        """List the survey's EDI files for removal (removal deliverable 1): the gateway enqueues a
        `list_stations` edit-job, the gw-runner returns the EDI filenames + derived station ids from
        the surveys-live checkout, the gateway renders the checkbox list. Sync `def` route so the
        seam's bounded blocking poll runs in Starlette's threadpool (review FIX 4)."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        try:
            result = self._edit_runner(metaedit.make_list_stations_job(slug))
        except metaedit.EditRunnerError as exc:
            logger.warning("list-stations job failed for %s: %s", slug, exc)
            return self.handle_edit_list(request)
        if not result.get("ok"):
            return self.handle_edit_list(request)
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(
            request, active="surveys",
            crumb=f'<a href="/gateway/curator/edit">Surveys</a> › '
                  f'<a href="/gateway/curator/survey/{curatorpage._esc(slug)}">'  # noqa: SLF001
                  f'{curatorpage._esc(slug)}</a> › <b>stations</b>')  # noqa: SLF001
        return self._html(curatorpage.render_stations_list(
            slug=slug, version=result.get("version"), stations=result.get("stations") or [],
            csrf_token=csrf, error=error, nav=nav))

    async def handle_stations_preview(self, request: Request, slug: str, form) -> Response:
        """Preview a station removal (deliverable 2): the selected EDIs, count before→after, the
        survey.yaml diff, and the validator's verdict on the package WITHOUT the removed files. The
        `form` is the raw FormData (NOT collapsed to a dict) so repeated `remove` checkboxes are read
        with getlist. Session + CSRF gated; the blocking poll runs off the loop via to_thread."""
        name = self._session_curator(request)
        if name is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, form.get("csrf_token")):
            return self._forbidden("bad csrf token")
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        filenames = _selected_removals(form)
        note = (form.get("note") or "").strip()
        bump = (form.get("bump") or "minor").strip()
        if bump not in ("patch", "minor", "major"):
            bump = "minor"
        if not filenames:
            return self.handle_stations_list(request, slug,
                                             error="Select at least one station to remove.")
        job = metaedit.make_remove_stations_job(slug, filenames, bump, note,
                                                time.strftime("%Y-%m-%d", time.gmtime()))
        try:
            result = await asyncio.to_thread(self._edit_runner, job)
        except metaedit.EditRunnerError as exc:
            logger.warning("remove-stations job failed for %s: %s", slug, exc)
            return self.handle_stations_list(request, slug,
                                             error=f"the removal could not be processed: {exc}")
        if not result.get("ok"):
            return self.handle_stations_list(request, slug, error=result.get("error") or "refused")
        csrf = curator_auth.csrf_token_for(raw)
        nav = self._nav_context(
            request, active="surveys",
            crumb=f'<a href="/gateway/curator/edit">Surveys</a> › '
                  f'<a href="/gateway/curator/survey/{curatorpage._esc(slug)}">'  # noqa: SLF001
                  f'{curatorpage._esc(slug)}</a> › <b>preview removal</b>')  # noqa: SLF001
        import json as _json
        return self._html(curatorpage.render_removal_preview(
            slug=slug, version=result.get("new_version") or "",
            removed=result.get("removed") or [],
            station_count_before=result.get("station_count_before") or 0,
            station_count_after=result.get("station_count_after") or 0,
            diff=result.get("diff") or "", validate_report=result.get("validator"),
            has_fail=bool(result.get("has_fail")), new_sha256=result.get("new_sha256") or "",
            note=note, bump=bump, filenames_json=_json.dumps(result.get("removed") or []),
            csrf_token=csrf, nav=nav))

    async def handle_stations_confirm(self, request: Request, slug: str, form: dict) -> Response:
        """Confirm + commit a station removal (deliverable 3): re-run the remove job server-side to
        reproduce the EXACT survey.yaml bytes, re-hash and 409 on any mismatch with the previewed sha,
        then git-rm the EDIs + write survey.yaml through commit_station_removal under PUBLISH_LOCK with
        byte-exact rollback on failure. Session + CSRF."""
        name = self._session_curator(request)
        if name is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, form.get("csrf_token")):
            return self._forbidden("bad csrf token")
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        expected_sha = (form.get("new_sha256") or "").strip()
        bump = (form.get("bump") or "minor").strip()
        if bump not in ("patch", "minor", "major"):
            bump = "minor"
        note = (form.get("note") or "").strip()
        import json as _json
        try:
            filenames = _json.loads(form.get("filenames_json") or "[]")
        except ValueError:
            return self._forbidden("malformed confirm payload")
        if not isinstance(filenames, list) or not all(isinstance(x, str) for x in filenames):
            return self._forbidden("malformed confirm payload")
        job = metaedit.make_remove_stations_job(slug, filenames, bump, note,
                                                time.strftime("%Y-%m-%d", time.gmtime()))
        try:
            result = await asyncio.to_thread(self._edit_runner, job)
        except metaedit.EditRunnerError as exc:
            logger.warning("remove-stations confirm job failed for %s: %s", slug, exc)
            return JSONResponse({"detail": "the removal could not be processed"}, status_code=500)
        if not result.get("ok"):
            return JSONResponse({"detail": result.get("error") or "refused"}, status_code=409)
        if result.get("has_fail"):
            return JSONResponse({"detail": "validator FAILED on the survey without these stations"},
                                status_code=409)
        if not expected_sha or result.get("new_sha256") != expected_sha:
            return JSONResponse(
                {"detail": "preview is stale (content hash mismatch) — re-open the stations page"},
                status_code=409)
        import base64
        try:
            new_yaml = base64.b64decode(result.get("new_yaml_b64") or "")
        except (ValueError, TypeError):
            return JSONResponse({"detail": "the removal could not be processed"}, status_code=500)
        return await self._commit_removal(slug, new_yaml, result.get("removed") or [],
                                          expected_sha, name, note)

    async def _commit_removal(self, slug: str, new_yaml: bytes, removed: list, expected_sha: str,
                              curator: str, note: str) -> Response:
        surveys_live = self.cfg.surveys_live_dir
        if surveys_live is None:
            return JSONResponse({"detail": "AUSMT_SURVEYS_LIVE is not configured"}, status_code=503)
        try:
            safe_slug = publish.validate_slug(slug)
        except publish.PublishError as exc:
            return JSONResponse({"detail": exc.message}, status_code=400)
        async with publish.PUBLISH_LOCK:
            try:
                await asyncio.to_thread(
                    self._commit_removal_blocking, surveys_live, safe_slug, new_yaml, removed,
                    expected_sha, curator, note)
            except publish.PublishError as exc:
                logger.warning("station removal publish failed for %s at %s: %s",
                               slug, exc.phase, exc.message)
                return JSONResponse({"detail": f"publish failed: {exc.message}"}, status_code=409)
        n = len(removed)
        return self._html(
            curatorpage._page(  # noqa: SLF001 -- reuse the page chrome for the terminal confirmation
                f"AusMT stations removed {slug}",
                f'<h1>Removed {n} station(s) — {curatorpage._esc(slug)}</h1>'  # noqa: SLF001
                '<p class="sub">The EDI file(s) were deleted from surveys-live and pushed. The '
                'serve-reconcile agent rebuilds and serves the result automatically on its next tick '
                '(typically within 15 minutes) — see the serve-state panel on the queue page, or run '
                '<code>make rebuild-data</code> by hand.</p>'
                '<p><a href="/gateway/curator/queue">back to queue</a></p>'))

    def _commit_removal_blocking(self, surveys_live: Path, slug: str, new_yaml: bytes, removed: list,
                                 expected_sha: str, curator: str, note: str) -> None:
        pre = publish.preflight(self._git_runner, surveys_live)
        publish.commit_station_removal(self._git_runner, surveys_live, slug, new_yaml, removed,
                                       expected_sha, curator, note, pre)

    # ---- C41 survey retirement (D2) — the destructive whole-survey removal + its TOTP gate --------

    def _station_count_for(self, slug: str) -> int | None:
        """The published station (EDI) count for `slug`, via the runner's list_stations job — for the
        retirement confirmation disclosure (record D2: 'N station files, N stated'). Degrades to None
        (runner down / refusal) so the confirmation page still renders honestly without a number,
        never a 500 on the disclosure path."""
        try:
            result = self._edit_runner(metaedit.make_list_stations_job(slug))
        except metaedit.EditRunnerError as exc:
            logger.warning("retire confirm: list-stations failed for %s: %s", slug, exc)
            return None
        if not result.get("ok"):
            return None
        stations = result.get("stations")
        return len(stations) if isinstance(stations, list) else None

    def _is_last_survey(self) -> bool:
        """True if the corpus holds one (or zero) published surveys, so retiring one would EMPTY it.
        C41 T6 (evidenced, not guessed): the production serve build (deploy/Makefile rebuild-data)
        invokes build_portal WITHOUT --allow-empty, and the real engine exits 2 on an empty corpus, so
        an empty surveys-live breaks the next rebuild and the retired survey keeps serving off the last
        good build indefinitely. The last-survey guard refuses this.

        This is the FAST PRE-REJECT used by the confirmation page + POST handler (good UX, no code
        burned); it reads outside PUBLISH_LOCK and is therefore racy. The AUTHORITATIVE guard against
        two concurrent retires emptying the corpus lives in _commit_retire_blocking, under the lock (F1)."""
        slugs = metaedit.list_published_slugs(self.cfg.surveys_live_dir)
        return len(slugs) <= 1

    def _retire_confirm_response(self, request: Request, name: str, slug: str, *, error: str = "",
                                 status_code: int = 200) -> Response:
        """Render the retirement confirmation page for `slug`: the record-D2 disclosure + the typed-slug
        / release-note / TOTP-code form — or, when the action cannot proceed, the honest refusal in
        place of the form (the last-survey guard, or an un-enrolled curator). Reused by the GET
        confirmation route AND by the POST handler's fail-closed re-renders (so a refusal shows the
        reason on the same page with the right status code)."""
        csrf = curator_auth.csrf_token_for(self._raw_session(request))
        nav = self._nav_context(
            request, active="surveys",
            crumb=f'<a href="/gateway/curator/edit">Surveys</a> › '
                  f'<a href="/gateway/curator/survey/{curatorpage._esc(slug)}">'  # noqa: SLF001
                  f'{curatorpage._esc(slug)}</a> › <b>retire survey</b>')  # noqa: SLF001
        is_last = self._is_last_survey()
        totp_row = self.db.get_totp(name)
        enrolled = totp_row is not None and totp_row.active
        # Only pay for the station-count runner round-trip when the form will actually render.
        station_count = self._station_count_for(slug) if (not is_last and enrolled) else None
        return self._html(curatorpage.render_survey_retire_confirm(
            slug=slug, station_count=station_count, csrf_token=csrf, enrolled=enrolled,
            is_last_survey=is_last, error=error, nav=nav), status_code=status_code)

    def handle_survey_retire_confirm(self, request: Request, slug: str) -> Response:
        """GET the retirement confirmation page (record D2): session-gated. Resolves the package (404 if
        the slug is unknown), then renders the disclosure + form (or the refusal when the last-survey
        guard fires or the curator is not enrolled). No mutation — a GET only reads."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        return self._retire_confirm_response(request, name, slug)

    async def handle_survey_retire(self, request: Request, slug: str, form: dict) -> Response:
        """POST the retirement (record D2): the server GATES IN ORDER — session, CSRF, the last-survey
        guard, the TOTP second factor (enrolled? rate-limited? valid? not-replayed?), then the typed-
        slug match and the required note — and only then consumes the code and commits `git rm -r` under
        PUBLISH_LOCK. ANY failure returns 400/409/429 with NOTHING staged (no git mutation runs before
        every gate has passed).

        Ordering nuance: the TOTP code is VERIFIED (and replay-checked) at the TOTP gate position, but
        the code is only CONSUMED (last_used_step advanced, atomically) AFTER the typed-slug/note gates
        pass — so a mistyped slug or an empty note does NOT burn the curator's code (they can retry with
        the same still-valid code). The atomic consume closes the TOCTOU: a concurrent re-use loses."""
        name = self._session_curator(request)
        if name is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, form.get("csrf_token")):
            return self._forbidden("bad csrf token")
        pkg = self._edit_package_or_error(slug)
        if isinstance(pkg, Response):
            return pkg
        # T6 last-survey guard — FAST PRE-REJECT (F1): refusing to retire the final survey (an empty
        # corpus breaks the next rebuild). Checked before the TOTP gate so a doomed retirement never
        # burns a code, and it surfaces the guard on the confirmation page. It is OUTSIDE PUBLISH_LOCK
        # and racy by design; the AUTHORITATIVE, lock-serialised guard is in _commit_retire_blocking.
        if self._is_last_survey():
            return self._retire_confirm_response(
                request, name, slug,
                error="Refusing to retire the last remaining survey — an empty corpus breaks the next "
                      "rebuild, so the retired survey would keep serving. Publish another survey first.",
                status_code=409)
        # TOTP gate (fail-closed). Unenrolled => refuse with an enrol pointer (rendered by the confirm
        # page's not-enrolled state).
        totp_row = self.db.get_totp(name)
        if totp_row is None or not totp_row.active:
            return self._retire_confirm_response(
                request, name, slug,
                error="You must enrol an authenticator before retiring a survey — see Security.",
                status_code=409)
        if self._totp_limiter.blocked():
            return self._retire_confirm_response(
                request, name, slug, error="Too many code attempts — wait and retry.",
                status_code=429)
        code = (form.get("code") or "").strip()
        step = totp.verify(code, totp_row.secret)
        if step is None:
            self._totp_limiter.record_failure()
            return self._retire_confirm_response(
                request, name, slug,
                error="That code did not match — check your authenticator and try again.",
                status_code=400)
        # Replay CHECK at the TOTP gate (the consume/advance happens after the content gates). A code at
        # or below the last consumed step is a replay of an already-used code.
        if totp_row.last_used_step is not None and step <= totp_row.last_used_step:
            self._totp_limiter.record_failure()
            return self._retire_confirm_response(
                request, name, slug,
                error="That code was already used — wait for a fresh code from your authenticator.",
                status_code=409)
        # The code is valid: clear the throttle (it guards wrong CODES, not wrong slugs/notes below).
        self._totp_limiter.record_success()
        # Typed-slug + note gates (BEFORE consuming the code, so a typo does not burn it).
        typed = (form.get("typed_slug") or "").strip()
        if typed != slug:
            return self._retire_confirm_response(
                request, name, slug,
                error="The typed survey name did not match — type the exact slug to confirm.",
                status_code=400)
        note = (form.get("note") or "").strip()
        if not note:
            return self._retire_confirm_response(
                request, name, slug,
                error="A release note is required (why the survey is retired) — it becomes the commit "
                      "message.", status_code=400)
        # All gates passed: CONSUME the code atomically (advance last_used_step). A concurrent re-use of
        # the same code loses this race and is refused with nothing staged.
        if not self.db.consume_totp_step(name, step):
            return self._retire_confirm_response(
                request, name, slug,
                error="That code was already used — wait for a fresh code from your authenticator.",
                status_code=409)
        return await self._commit_retire(slug, name, note)

    async def _commit_retire(self, slug: str, curator: str, note: str) -> Response:
        surveys_live = self.cfg.surveys_live_dir
        if surveys_live is None:
            return JSONResponse({"detail": "AUSMT_SURVEYS_LIVE is not configured"}, status_code=503)
        try:
            safe_slug = publish.validate_slug(slug)
        except publish.PublishError as exc:
            return JSONResponse({"detail": exc.message}, status_code=400)
        async with publish.PUBLISH_LOCK:
            try:
                await asyncio.to_thread(
                    self._commit_retire_blocking, surveys_live, safe_slug, curator, note)
            except publish.PublishError as exc:
                logger.warning("survey retirement publish failed for %s at %s: %s",
                               slug, exc.phase, exc.message)
                return JSONResponse({"detail": f"publish failed: {exc.message}"}, status_code=409)
        return self._html(curatorpage.render_survey_retired(slug=slug, curator=curator))

    def _commit_retire_blocking(self, surveys_live: Path, slug: str, curator: str, note: str) -> None:
        pre = publish.preflight(self._git_runner, surveys_live)
        # F1 (TOCTOU) — the AUTHORITATIVE last-survey guard, re-evaluated INSIDE PUBLISH_LOCK after
        # preflight from on-disk truth. The check in handle_survey_retire is only a fast, friendly
        # pre-reject (it shows the guard on the confirmation page and avoids burning a TOTP code); it is
        # OUTSIDE the lock and therefore racy — two concurrent retires can both read count>1 there before
        # either commits, then both remove their survey and EMPTY the corpus. This runs under
        # PUBLISH_LOCK, so it serialises against every other retire/publish: once a first retire has
        # removed its survey, a second interleaved retire sees the now-smaller corpus HERE and is refused.
        # Two retires can therefore never empty the corpus (the silent-drift break the guard exists for).
        if len(metaedit.list_published_slugs(surveys_live)) <= 1:
            raise publish.PublishError(
                "guard", "refusing to retire the last remaining survey "
                         "(an empty corpus breaks the next rebuild)")
        publish.commit_survey_removal(self._git_runner, surveys_live, slug, curator, note, pre)

    def _edit_package_or_error(self, slug: str):
        """Resolve the surveys-live package dir for `slug` or return a Response (404). Charset-
        validates the slug (publish.validate_slug) BEFORE it touches a path — the same guard the
        publish path uses so a spoofed slug can never traverse."""
        surveys_live = self.cfg.surveys_live_dir
        if surveys_live is None:
            return JSONResponse({"detail": "AUSMT_SURVEYS_LIVE is not configured"}, status_code=503)
        try:
            safe = publish.validate_slug(slug)
        except publish.PublishError:
            return self._not_found()
        pkg = metaedit.package_root_for(surveys_live, safe)
        if not (pkg / "survey.yaml").is_file():
            return self._not_found()
        return pkg

    def _build_patch(self, form: dict):
        """Turn the edit form fields into the merge patch (C31 §2). Top-level SCALAR fields (f_*)
        become their string values (browser CRLF normalised to LF so a textarea edit never embeds
        \\r into the yaml). The STRUCTURED sections are assembled by editor_form.build_section_patch
        from the per-section widget inputs (s_/l_/c_) — or, when a section's advanced <details>
        raw-JSON box (j_<section>) is non-empty, from that JSON, which OVERRIDES the widgets for that
        section (the single documented precedence point, enforced in editor_form.assemble_section).
        json is stdlib, not survey content — the §0.1 no-yaml rule is unbroken. Returns
        (patch, errors): errors is a list of editor_form.SectionError (empty on success); a non-empty
        list yields a curator-facing per-field message and NO patch. The validator location is NOT the
        gateway's business — the gw-runner resolves it from its own AUSMT_VALIDATOR_PATH."""
        patch: dict = {}
        for key in ("project_name", "name", "region", "license", "abstract"):
            raw = form.get(f"f_{key}")
            if raw is not None:
                patch[key] = raw.replace("\r\n", "\n").replace("\r", "\n")
        section_patch, errors = editor_form.build_section_patch(form)
        if errors:
            return None, errors
        patch.update(section_patch)
        return patch, []

    # ---- preview sandbox (design §7) ---------------------------------------------------------

    def handle_curator_preview(self, request: Request, submission_id: str, subpath: str) -> Response:
        # Authorized by the UNGUESSABLE submission id in the path, NOT the session (revised design §7).
        # The null-origin sandboxed iframe that embeds this preview cannot send the curator cookie —
        # its subresource fetches (catalogue.json etc.) are credential-less cross-origin — so a
        # session gate here would 401 the preview's own assets and it would never render. The id is a
        # ULID (the same id the session-gated detail page embeds); the served bytes are the build
        # engine's already-embargo-safe, PII-scrubbed preview product. The DETAIL page that embeds the
        # iframe stays session-gated (handle_curator_detail); only this static subtree is id-authorized.
        # Residual (documented, deploy/README.md): a tailnet member who obtains a submission id can
        # view its (embargo-safe, PII-scrubbed) preview without a curator session.
        if not db.is_valid_id(submission_id):
            return self._not_found()
        # The id must correspond to a real submission (a random-but-valid ULID resolves to nothing).
        if self.db.get(submission_id) is None:
            return self._not_found()
        root = (self.cfg.quarantine_dir / submission_id / "reports" / "preview-data").resolve()
        # Path containment (design §7): resolve the requested sub-path and confirm it stays UNDER the
        # preview-data root. `..`/absolute/symlink escapes resolve to something outside root and 404.
        target = (root / subpath).resolve()
        if target != root and root not in target.parents:
            return self._not_found()
        if not target.is_file():
            return self._not_found()
        media_type = _preview_media_type(target)
        if media_type is None:
            # Unknown/unsafe type: refuse rather than guess a Content-Type an attacker could abuse.
            return self._not_found()
        data = target.read_bytes()
        # Strict CSP (design §7): default-src 'self' confines what the preview can load to same-origin;
        # nosniff stops content-type confusion. frame-ancestors 'self' lets the curator detail page
        # frame it but nothing cross-origin. Content-Disposition inline only for these known-safe types.
        headers = {
            "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Cache-Control": "no-store",
        }
        return Response(content=data, media_type=media_type, headers=headers)

    # ---- C43 D6 quarantine view (read-only) --------------------------------------------------

    def handle_quarantine_list(self, request: Request) -> Response:
        """GET the quarantine list: every QUARANTINED submission with its refusal reason. Session-gated
        like the other curator GET pages. Read-only — no action forms (the review flow is untouched,
        D6). The reason is the last transition's reason (the quarantine outcome cause), read from the
        DB the gateway already owns; no new mount, no file read for the LIST view."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        rows = []
        for sid in self.db.ids_in_state(states.QUARANTINED):
            sub = self.db.get(sid)
            if sub is None:
                continue
            trans = self.db.transitions_for(sid)
            reason = trans[-1]["reason"] if trans else ""
            rows.append({"id": sub.id, "slug": sub.slug, "updated_utc": sub.updated_utc,
                         "reason": reason})
        # Newest first (id is time-prefixed, like the queue's ORDER BY id DESC).
        rows.sort(key=lambda r: r["id"], reverse=True)
        nav = self._nav_context(request, active="queue",
                                crumb='<a href="/gateway/curator/queue">Submission queue</a> › '
                                      '<b>Quarantine</b>')
        return self._html(curatorpage.render_quarantine_list(
            curator_name=name, rows=rows, nav=nav))

    def handle_quarantine_detail(self, request: Request, submission_id: str) -> Response:
        """GET a single quarantined submission's read-only view: refusal reason + package file listing.
        Session-gated. The file listing is a server-side os.walk of quarantine/<id>/package, bounded by
        a file cap so a hostile deeply-nested package cannot make the page enumeration unbounded. Only a
        submission genuinely in QUARANTINE is shown (a valid-but-non-quarantined id 404s — no oracle for
        other states through this surface)."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        if not db.is_valid_id(submission_id):
            return self._not_found()
        sub = self.db.get(submission_id)
        if sub is None or sub.state != states.QUARANTINED:
            return self._not_found()
        trans = self.db.transitions_for(submission_id)
        reason = trans[-1]["reason"] if trans else ""
        files = self._quarantine_package_files(submission_id)
        nav = self._nav_context(
            request, active="queue",
            crumb='<a href="/gateway/curator/queue">Submission queue</a> › '
                  '<a href="/gateway/curator/quarantine">Quarantine</a> › '
                  f'<b>{curatorpage._esc(submission_id[:12])}</b>')  # noqa: SLF001
        return self._html(curatorpage.render_quarantine_detail(
            submission_id=submission_id, slug=sub.slug, reason=reason, files=files, nav=nav))

    def _quarantine_package_files(self, submission_id: str, *, cap: int = 2000) -> list:
        """Enumerate files under quarantine/<id>/package as {rel, size} relative POSIX paths, sorted,
        bounded by `cap` (a hostile package with a huge file count cannot make this listing unbounded —
        the extraction member cap already bounds a real package; this is belt-and-braces for the page).
        Returns [] if the package dir is absent (quarantined before/at unpack). Symlinks are skipped
        (is_file follows them; a symlinked file is not part of the extracted content we enumerate)."""
        root = (self.cfg.quarantine_dir / submission_id / "package").resolve()
        if not root.is_dir():
            return []
        out: list = []
        for path in sorted(root.rglob("*")):
            if len(out) >= cap:
                break
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                rel = path.resolve().relative_to(root).as_posix()
                out.append({"rel": rel, "size": path.stat().st_size})
            except (OSError, ValueError):
                continue
        return out

    def handle_quarantine_file(self, request: Request, submission_id: str, subpath: str) -> Response:
        """GET one file from a quarantined submission's package, READ-ONLY, with PATH CONTAINMENT
        mirroring the preview sandbox (app.py handle_curator_preview): resolve the requested sub-path
        and confirm it stays UNDER quarantine/<id>/package — a `..`/absolute/symlink escape resolves
        outside root and 404s. Session-gated (unlike the id-authorized preview: this serves UN-curated,
        potentially hostile submitter content, so it stays behind the curator session AND a strict CSP).

        CONTENT DISCIPLINE: served with Content-Disposition: attachment and a nosniff + sandboxing CSP
        so the browser NEVER inline-renders or executes submitter bytes (an uploaded .html/.svg is a
        script vector). Unlike the preview route there is NO media-type allow-list gating WHICH files
        are viewable — a quarantined package is arbitrary submitter content and the curator may need to
        inspect any of it — so instead EVERY file is forced to download as an opaque octet-stream-ish
        payload under default-src 'none', which is the safe way to expose arbitrary bytes."""
        name = self._require_session(request)
        if isinstance(name, Response):
            return name
        if not db.is_valid_id(submission_id):
            return self._not_found()
        sub = self.db.get(submission_id)
        if sub is None or sub.state != states.QUARANTINED:
            return self._not_found()
        root = (self.cfg.quarantine_dir / submission_id / "package").resolve()
        target = (root / subpath).resolve()
        # Containment: the resolved target must be root itself's descendant (never root, which is a dir).
        if root not in target.parents:
            return self._not_found()
        if target.is_symlink() or not target.is_file():
            return self._not_found()
        try:
            data = target.read_bytes()
        except OSError:
            return self._not_found()
        # Force download of opaque bytes; never inline-render/execute untrusted submitter content.
        headers = {
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "attachment",
            "Cache-Control": "no-store",
        }
        return Response(content=data, media_type="application/octet-stream", headers=headers)

    # ---- curator actions (design §3/§5) ------------------------------------------------------

    async def handle_curator_action(self, request: Request, submission_id: str, action: str,
                                    csrf: str | None, note: str | None,
                                    confirm_overwrite: bool, ack_pii: bool = False) -> Response:
        name = self._session_curator(request)
        if name is None:
            return self._unauthorized_api()
        raw = self._raw_session(request)
        if not curator_auth.csrf_ok(raw, csrf):
            # A missing/mismatched CSRF token is a 403 with NO action taken and NO git call — the
            # guarantee that a cross-site form cannot drive a state change (design §2/§8).
            return self._forbidden("bad csrf token")
        if not db.is_valid_id(submission_id):
            return self._not_found()
        note = (note or "").strip()
        if not note:
            # EVERY action requires a non-empty decision note (design §3 — no reject exemption). Empty
            # note => 400, no transition. The reject form supplies a real curator note.
            return JSONResponse({"detail": "a decision note is required"}, status_code=400)
        sub = self.db.get(submission_id)
        if sub is None:
            return self._not_found()

        if action == "return":
            return self._simple_transition(sub, states.RETURNED, name, note, "returned to submitter")
        if action == "reject":
            return self._simple_transition(sub, states.REJECTED, name, note, "rejected")
        if action in ("approve", "retry"):
            return await self._begin_publish(sub, name, note, action, confirm_overwrite, ack_pii)
        return self._not_found()

    def _simple_transition(self, sub: db.Submission, to_state: str, curator: str, note: str,
                           fallback: str) -> Response:
        try:
            self.db.transition(sub.id, to_state, actor=f"curator:{curator}",
                               reason=note or fallback)
        except db.IllegalTransition:
            return JSONResponse({"detail": f"cannot {to_state.lower()} from {sub.state}"},
                                status_code=409)
        return RedirectResponse("/gateway/curator/queue", status_code=303)

    async def _begin_publish(self, sub: db.Submission, curator: str, note: str, action: str,
                             confirm_overwrite: bool, ack_pii: bool = False) -> Response:
        expected = states.VALIDATED if action == "approve" else states.PUBLISH_FAILED
        if sub.state != expected:
            return JSONResponse({"detail": f"cannot {action} from {sub.state}"}, status_code=409)
        # Blocking-FAIL guard (design §4/§5 + C11b §2): re-check server-side and REFUSE with 409 even if
        # the button/checkbox was hidden — that is UX; the 409 is the guarantee. Retry from
        # PUBLISH_FAILED re-checks too, and acknowledgement is PER-ACTION (C11b §2): nothing about the
        # ack persists on the row, so a retry needs ack_pii again.
        #   - ANY non-acknowledgeable blocking FAIL (every submitter-email hit — C11b §0 — and every
        #     non-PII block) => 409, no acknowledgement can override it.
        #   - blocking FAILs that are ALL acknowledgeable => 409 UNLESS ack_pii is affirmative.
        validator, preview, _note = self._load_reports(sub)
        cl = self._build_checklist(sub, validator, preview)
        if cl.has_unacknowledgeable_blocking_fail:
            return JSONResponse(
                {"detail": "a blocking check failed", "reasons": cl.blocking_fail_reasons},
                status_code=409)
        if cl.has_acknowledgeable_blocking_fail and not ack_pii:
            return JSONResponse(
                {"detail": "a blocking check failed", "reasons": cl.blocking_fail_reasons},
                status_code=409)
        # When an acknowledged approve proceeds, prefix the PUBLISHING audit reason so the existing
        # audit table records who acknowledged what (C11b §2 — no schema change). File names only; the
        # matched address is never in the checklist detail, so it can never reach here either.
        reason = note
        if cl.has_acknowledgeable_blocking_fail:
            files = cl.pii_generic_files
            reason = (f"PII-ACK ({len(files)} file(s): {checklist_mod.bounded_names(files)}): "
                      f"{note}")
        # Transition to PUBLISHING synchronously (audit row, actor curator:<name>) BEFORE returning,
        # then run the publish in a background task so the request returns immediately (design §5).
        try:
            self.db.transition(sub.id, states.PUBLISHING, actor=f"curator:{curator}",
                               reason=reason)
        except db.IllegalTransition:
            return JSONResponse({"detail": f"cannot publish from {sub.state}"}, status_code=409)
        self._publishing.add(sub.id)
        asyncio.create_task(self._run_publish(sub.id, sub.slug, curator, note, confirm_overwrite))
        return RedirectResponse(f"/gateway/curator/submission/{sub.id}", status_code=303)

    async def _run_publish(self, submission_id: str, slug: str | None, curator: str, note: str,
                           confirm_overwrite: bool) -> None:
        """The design §5 v2 publish (commit-and-push ONLY, no build): single-flight under PUBLISH_LOCK,
        fail-closed at every git step. git runs in a thread (blocking subprocess calls) so the event
        loop keeps serving. On ANY PublishError the submission goes to PUBLISH_FAILED with the reason
        and surveys-live is rolled back byte-for-byte to the captured pre-state. The lock is released
        in finally so a failure never wedges the queue. PUBLISHED here means committed+pushed, NOT
        served — the operator's manual `make rebuild-data` is what serves it."""
        async with publish.PUBLISH_LOCK:
            try:
                await asyncio.to_thread(
                    self._publish_blocking, submission_id, slug, curator, note, confirm_overwrite)
                self.db.transition(submission_id, states.PUBLISHED, actor=f"curator:{curator}",
                                   reason="committed to surveys-live; the reconcile agent serves it "
                                          "on its next tick")
            except publish.PublishError as exc:
                logger.warning("publish failed for %s at %s: %s", submission_id, exc.phase, exc.message)
                self._fail_publish(submission_id, curator, exc.message)
            except Exception as exc:  # noqa: BLE001 -- any unexpected error must still fail closed
                logger.exception("unexpected publish error for %s", submission_id)
                self._fail_publish(submission_id, curator, f"unexpected error: {type(exc).__name__}")
            finally:
                self._publishing.discard(submission_id)

    def _publish_blocking(self, submission_id: str, slug: str | None, curator: str, note: str,
                          confirm_overwrite: bool) -> None:
        surveys_live = self.cfg.surveys_live_dir
        if surveys_live is None:
            raise publish.PublishError("guard", "AUSMT_SURVEYS_LIVE is not configured")
        slug = publish.validate_slug(slug)
        # Pre-flight (design §5 step 1): abort unless the checkout is clean and on main, capturing the
        # pre-state (ref + branch) for a byte-exact rollback. Nothing is staged if this aborts.
        pre = publish.preflight(self._git_runner, surveys_live)
        package_dir = self.cfg.quarantine_dir / submission_id / "package"
        publish.stage_and_commit(self._git_runner, package_dir, surveys_live, slug, submission_id,
                                 curator, note, pre, allow_overwrite=confirm_overwrite)

    def _fail_publish(self, submission_id: str, curator: str, reason: str) -> None:
        try:
            self.db.transition(submission_id, states.PUBLISH_FAILED, actor=f"curator:{curator}",
                               reason=reason)
        except db.IllegalTransition:
            logger.error("could not move %s to PUBLISH_FAILED (state moved underneath)", submission_id)

    def _reconcile_publishing(self) -> None:
        """Poll-loop reconciliation (design §5.4): a PUBLISHING row with no live in-process task means
        the gateway restarted mid-publish. Move it to PUBLISH_FAILED with 'publish interrupted' — never
        left hanging, never auto-retried (a half-done git state needs human eyes; the retry's pre-flight
        clean check then catches a genuinely dirty tree rather than compounding it).

        This — and the single-flight PUBLISH_LOCK — assume ONE gateway process: `_publishing` is
        in-memory, so a second worker's live task would look 'stuck' to this one. The deployment MUST
        run single-worker (uvicorn --workers 1); see deploy/README.md. Cross-worker coordination is
        deliberately out of scope for the demo."""
        for sid in self.db.ids_in_state(states.PUBLISHING):
            if sid in self._publishing:
                continue  # this process is actively publishing it
            self._fail_publish(sid, "gateway", "publish interrupted (gateway restarted mid-publish)")

    def _purge_sessions(self) -> None:
        now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.db.purge_expired_sessions(now_utc)

    # ---- curator response helpers ------------------------------------------------------------

    def _require_session(self, request: Request):
        """Return the curator name, or a Response (401 for a broken config; redirect to login for a
        missing session) that the caller returns as-is."""
        try:
            self._curator_keys()
        except curator_auth.CuratorConfigError:
            return self._curator_503()
        name = self._session_curator(request)
        if name is None:
            return RedirectResponse("/gateway/curator/", status_code=303)
        return name

    def _set_session_cookie(self, resp: Response, token: str) -> None:
        # Secure; HttpOnly; SameSite=Strict (design §2). Path scoped to the curator area. HttpOnly
        # keeps the token out of page JS entirely; SameSite=Strict means a cross-site form cannot send
        # it even with a live session; max_age matches the absolute session TTL.
        resp.set_cookie(
            curator_auth.SESSION_COOKIE, token, max_age=self.cfg.session_ttl_s,
            httponly=True, secure=True, samesite="strict", path="/gateway/curator")

    def _html(self, body: str, status_code: int = 200) -> Response:
        return HTMLResponse(content=body, status_code=status_code,
                            headers={"Cache-Control": "no-store"})

    def _curator_503(self) -> Response:
        return JSONResponse({"detail": "curator interface not configured"}, status_code=503,
                            headers={"Cache-Control": "no-store"})

    def _forbidden(self, detail: str) -> Response:
        return JSONResponse({"detail": detail}, status_code=403, headers={"Cache-Control": "no-store"})

    def _not_found(self) -> Response:
        return Response(content=_STATUS_404_BODY, status_code=404, media_type="text/plain",
                        headers={"Cache-Control": "no-store"})

    def _unauthorized_api(self) -> Response:
        return JSONResponse({"detail": "unauthorized"}, status_code=401,
                            headers={"Cache-Control": "no-store"})

    # ---- auth --------------------------------------------------------------------------------

    def _resolve_submit_auth(self, submit_key: str | None) -> "_SubmitAuth | None":
        """Resolve a presented X-AusMT-Submit-Key to an authenticated identity, else None (=> 401).
        Accepts EITHER the env AUSMT_SUBMIT_KEY (bootstrap + CI e2e path, unchanged — the env check
        needs no DB, so it survives a DB outage) OR an ACTIVE DB uploader key (schema v2). Timing:
        the env key compares raw bytes with hmac.compare_digest; the DB key is HASHED FIRST and looked
        up by an indexed SQL equality on the sha256 digest — that comparison is not constant-time, and
        does not need to be: it operates on a one-way digest of a ~256-bit random secret, so equality
        timing leaks nothing usable about the plaintext (and it is a hash lookup, not a per-key scan).
        A revoked/unknown key resolves to None — the SAME 401 as a wrong env key, no oracle for which
        case it was.

        FAIL-CLOSED: if the DB lookup raises (DB unavailable mid-auth), we REJECT rather than fall back
        to env-only or accept — an auth error is never an auth bypass. The env path is tried FIRST and
        returns without touching the DB, so a DB outage never blocks the bootstrap key."""
        if not submit_key:
            return None
        if hmac.compare_digest(submit_key, self.cfg.submit_key):
            return _SubmitAuth(uploader_name=None, uploader_key_id=None)
        try:
            row = self.db.get_active_uploader_key_by_hash(uploader_keys_mod.key_hash(submit_key))
        except Exception:  # noqa: BLE001 -- a DB error during auth must fail closed, never bypass
            logger.warning("uploader-key lookup failed during submit auth — rejecting (fail closed)")
            return None
        if row is None:
            return None
        return _SubmitAuth(uploader_name=row.name, uploader_key_id=row.id)


@dataclass(frozen=True)
class _SubmitAuth:
    """The authenticated submit identity. uploader_name/uploader_key_id are None for the env key
    (bootstrap/CI); set for a DB uploader key so the handler can attribute the upload and stamp
    last_used."""
    uploader_name: str | None
    uploader_key_id: int | None


class _Oversize(Exception):
    pass


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _slug_from_refs(refs: dict) -> str | None:
    slug = refs.get("slug") if isinstance(refs, dict) else None
    return slug if isinstance(slug, str) and slug else None


def _selected_removals(form) -> list[str]:
    """The EDI filenames the curator ticked, from repeated `remove` checkboxes. Starlette's FormData
    is a multidict, so getlist('remove') returns EVERY checked value (a plain dict() would collapse
    them to the last one, silently dropping all but one selection). Deduped, order-preserving, blanks
    dropped. The runner + publish re-validate each name's charset before it becomes a path component,
    so this only needs to gather them."""
    getlist = getattr(form, "getlist", None)
    raw = getlist("remove") if callable(getlist) else form.get("remove")
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[str] = []
    for v in raw:
        name = str(v).strip()
        if name and name not in out:
            out.append(name)
    return out


# The ONLY content types the preview route serves (design §7). An allow-list, not a guess: the
# preview product is generated JSON + the static portal shell, so every legitimate asset is one of
# these. An extension outside this set 404s rather than being served with a sniffed/guessed type an
# attacker could abuse (e.g. an uploaded .html that is really a script vector). No .html-with-inline-
# script risk: even served .html is under the strict CSP (default-src 'self') set by the route.
_PREVIEW_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".map": "application/json",
}


def _preview_media_type(path: Path) -> str | None:
    return _PREVIEW_MEDIA_TYPES.get(path.suffix.lower())


def create_app(cfg: Config | None = None, scanner=None, git_runner=None, edit_runner=None) -> FastAPI:
    cfg = cfg or load_config()
    fail_closed_startup(cfg)
    gw = Gateway(cfg, scanner=scanner, git_runner=git_runner, edit_runner=edit_runner)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        # The single asyncio poll loop (design §9 — the ONE background task). Started here so the
        # app has a running loop; cancelled + DB closed on shutdown. Tests construct the app without
        # entering the lifespan and drive gw.poll_once() directly, so this task never competes with
        # their deterministic assertions.
        gw._poll_task = asyncio.create_task(_poll_forever(gw))
        try:
            yield
        finally:
            gw._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await gw._poll_task
            gw.close()

    app = FastAPI(title="AusMT submission gateway", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.gw = gw

    for name, value in cfg.redacted_items():
        logger.info("config %s=%s", name, value)

    @app.post("/gateway/submit")
    async def submit(request: Request,
                     x_ausmt_submit_key: str | None = Header(default=None)):
        return await gw.handle_submit(request, x_ausmt_submit_key)

    # Deliberately `def`, NOT `async def` (review #9): handle_status does blocking sqlite + file
    # reads, so Starlette runs a sync route handler in its threadpool — a burst of GET /status can no
    # longer stall the event-loop poll task. The DB serialises cross-thread access with its own lock.
    @app.get("/gateway/status/{token}")
    def status(token: str):
        return gw.handle_status(token)

    @app.get("/gateway/healthz")
    async def healthz():
        # Liveness only; no auth, no data — used by compose/operator. Deliberately reveals nothing.
        return JSONResponse({"ok": True})

    # ---- curator routes (C11 §3). All session-gated except login; every state-changing POST is
    # CSRF-checked inside the handler. The GET pages that do blocking sqlite/file reads are declared
    # `def` (Starlette runs them in its threadpool) so a burst does not stall the event-loop poll
    # task — matching the C10 status route's rationale.
    @app.get("/gateway/curator/")
    def curator_root(request: Request):
        return gw.handle_curator_root(request)

    @app.post("/gateway/curator/login")
    def curator_login(request: Request, curator_key: str = Form(default="")):
        return gw.handle_curator_login(request, curator_key)

    @app.post("/gateway/curator/logout")
    def curator_logout(request: Request, csrf_token: str = Form(default="")):
        return gw.handle_curator_logout(request, csrf_token)

    @app.get("/gateway/curator/queue")
    def curator_queue(request: Request):
        return gw.handle_curator_queue(request)

    @app.get("/gateway/curator/submission/{submission_id}")
    def curator_detail(request: Request, submission_id: str):
        return gw.handle_curator_detail(request, submission_id)

    @app.get("/gateway/curator/preview/{submission_id}/{subpath:path}")
    def curator_preview(request: Request, submission_id: str, subpath: str):
        return gw.handle_curator_preview(request, submission_id, subpath)

    # ---- C43 D6 quarantine view (read-only). GET pages: blocking sqlite/file reads -> threadpool,
    # `def` (matching the queue/detail rationale). No POSTs — the surface is inspection only.
    @app.get("/gateway/curator/quarantine")
    def curator_quarantine_list(request: Request):
        return gw.handle_quarantine_list(request)

    @app.get("/gateway/curator/quarantine/{submission_id}")
    def curator_quarantine_detail(request: Request, submission_id: str):
        return gw.handle_quarantine_detail(request, submission_id)

    @app.get("/gateway/curator/quarantine/{submission_id}/file/{subpath:path}")
    def curator_quarantine_file(request: Request, submission_id: str, subpath: str):
        return gw.handle_quarantine_file(request, submission_id, subpath)

    # ---- uploader-key routes (schema v2). GET is `def` (blocking sqlite read -> threadpool, matching
    # the queue/detail rationale); both POSTs are CSRF-checked in the handler.
    @app.get("/gateway/curator/uploaders")
    def curator_uploaders(request: Request):
        return gw.handle_uploaders(request)

    @app.post("/gateway/curator/uploaders/create")
    def curator_uploader_create(request: Request, name: str = Form(default=""),
                                email: str = Form(default=""), csrf_token: str = Form(default="")):
        return gw.handle_uploader_create(request, name, email, csrf_token)

    @app.post("/gateway/curator/uploaders/{key_id}/revoke")
    def curator_uploader_revoke(request: Request, key_id: int, csrf_token: str = Form(default="")):
        return gw.handle_uploader_revoke(request, key_id, csrf_token)

    # C43 D7: set a free-text note on an uploader key (sqlite only, never git). CSRF-checked in the
    # handler, matching the create/revoke POSTs.
    @app.post("/gateway/curator/uploaders/{key_id}/note")
    def curator_uploader_note(request: Request, key_id: int, note: str = Form(default=""),
                              csrf_token: str = Form(default="")):
        return gw.handle_uploader_note(request, key_id, note, csrf_token)

    # ---- curator security: TOTP second factor (schema v4 — C41 D2). GET is `def` (blocking sqlite
    # read -> threadpool). The code-verifying POSTs are `async def` so the throttle decision
    # (blocked-check -> verify -> record) runs to completion on the event loop with NO await between
    # its steps — atomic against a concurrent burst without needing the login route's evaluate() form.
    @app.get("/gateway/curator/security")
    def curator_security(request: Request):
        return gw.handle_security(request)

    @app.post("/gateway/curator/security/enrol")
    async def curator_security_enrol(request: Request, csrf_token: str = Form(default="")):
        return gw.handle_security_enrol(request, csrf_token)

    @app.post("/gateway/curator/security/activate")
    async def curator_security_activate(request: Request, code: str = Form(default=""),
                                        csrf_token: str = Form(default="")):
        return gw.handle_security_activate(request, code, csrf_token)

    @app.post("/gateway/curator/security/rotate")
    async def curator_security_rotate(request: Request, code: str = Form(default=""),
                                      csrf_token: str = Form(default="")):
        return gw.handle_security_rotate(request, code, csrf_token)

    # ---- C40 serve-reconcile: the curator "request rebuild" button. Session + CSRF (checked in the
    # handler); writes the zero-argument rebuild.request the host reconcile agent consumes. `def`
    # (not async) — a tiny atomic file write, no await, consistent with the other simple POSTs.
    @app.post("/gateway/curator/rebuild")
    def curator_rebuild(request: Request, csrf_token: str = Form(default="")):
        return gw.handle_rebuild_request(request, csrf_token)

    # ---- C43 S2b-i: the first-class serve-state screen + the read-only build-detail view. Both GETs
    # do blocking file/git reads -> `def` (threadpool), matching the queue rationale. Read-only: no
    # POST, no privileged action (rollback/restore/update/backup/pause are Stage 2b-ii).
    @app.get("/gateway/curator/serve")
    def curator_serve_state(request: Request):
        return gw.handle_serve_state(request)

    @app.get("/gateway/curator/serve/build/{build_ref}")
    def curator_serve_build_detail(request: Request, build_ref: str):
        return gw.handle_serve_build_detail(request, build_ref)

    # The serve-state panel's JS as an EXTERNAL same-origin script — the strictPages CSP
    # (script-src 'self') blocks inline scripts on every /gateway/* page, so the queue page loads
    # this URL instead (see curatorpage.SERVE_PANEL_JS).
    @app.get("/gateway/curator/serve-state.js")
    def curator_serve_state_js(request: Request):
        return gw.handle_serve_state_js(request)

    # The shared curator-page UI behaviours (data-confirm / data-toggle-big delegation) — loaded by
    # every curator page via _TAIL; external for the same CSP reason as serve-state.js.
    @app.get("/gateway/curator/ui.js")
    def curator_ui_js(request: Request):
        return gw.handle_curator_ui_js(request)

    # The metadata-editor's repeatable-row add/remove JS — EXTERNAL for the same CSP reason; the edit
    # form loads it via a same-origin external script URL. Degrades to server-rendered spare rows
    # when JS is unavailable.
    @app.get("/gateway/curator/editor.js")
    def curator_editor_js(request: Request):
        return gw.handle_editor_ui_js(request)

    # The C43 nav-shell context bar's drift chip served-build half — EXTERNAL for the same CSP reason;
    # every shelled curator page loads it via a same-origin external script URL. Degrades gracefully.
    @app.get("/gateway/curator/context-bar.js")
    def curator_context_bar_js(request: Request):
        return gw.handle_context_bar_js(request)

    # The C43 survey-hub script (Overview & QA render + Metadata one-section-at-a-time TOC) — EXTERNAL
    # for the same CSP reason; the hub page loads it via a same-origin external script URL.
    @app.get("/gateway/curator/survey-hub.js")
    def curator_survey_hub_js(request: Request):
        return gw.handle_survey_hub_js(request)

    # The C43 Stage-2a Stations tab script — EXTERNAL for the same CSP reason; the hub's Stations tab
    # loads it via a same-origin external script URL. Degrades to the loading placeholder without JS.
    @app.get("/gateway/curator/stations.js")
    def curator_stations_js(request: Request):
        return gw.handle_stations_js(request)

    # The C43 FR2-1 Surveys-list enrichment script — EXTERNAL for the same CSP reason; the surveys
    # list loads it to fill the name/version/licence/count columns from the served corpus. Degrades to
    # the slug-only rows without JS.
    @app.get("/gateway/curator/surveys-list.js")
    def curator_surveys_list_js(request: Request):
        return gw.handle_surveys_list_js(request)

    # ---- C31 metadata-editor routes (session-gated; POSTs CSRF-checked in the handler). GET pages
    # do blocking directory/subprocess work so they are `def` (threadpool), matching the C10/C11
    # rationale; the POSTs are async (they take the PUBLISH_LOCK / await to_thread for git).
    @app.get("/gateway/curator/edit")
    def curator_edit_list(request: Request):
        return gw.handle_edit_list(request)

    # C43 survey hub (Overview & QA / Metadata). GET `def` (blocking read-job -> threadpool). The tab
    # is a query param so both tabs share one route + one crumb; unknown tabs fall back to overview.
    @app.get("/gateway/curator/survey/{slug}")
    def curator_survey_hub(request: Request, slug: str, tab: str = "overview"):
        return gw.handle_survey_hub(request, slug, tab)

    @app.get("/gateway/curator/edit/{slug}")
    def curator_edit_form(request: Request, slug: str):
        return gw.handle_edit_form(request, slug)

    @app.post("/gateway/curator/edit/{slug}/preview")
    async def curator_edit_preview(request: Request, slug: str):
        form = dict(await request.form())
        return await gw.handle_edit_preview(request, slug, form)

    @app.post("/gateway/curator/edit/{slug}/confirm")
    async def curator_edit_confirm(request: Request, slug: str):
        form = dict(await request.form())
        return await gw.handle_edit_confirm(request, slug, form)

    # ---- station (EDI) removal routes. GET lists the EDIs (blocking runner poll -> threadpool, `def`);
    # the POSTs are async (they await the runner seam / take the PUBLISH_LOCK for git). The preview POST
    # passes the RAW FormData (not a collapsed dict) so repeated `remove` checkboxes survive.
    @app.get("/gateway/curator/edit/{slug}/stations")
    def curator_stations_list(request: Request, slug: str):
        return gw.handle_stations_list(request, slug)

    @app.post("/gateway/curator/edit/{slug}/stations/preview")
    async def curator_stations_preview(request: Request, slug: str):
        form = await request.form()
        return await gw.handle_stations_preview(request, slug, form)

    @app.post("/gateway/curator/edit/{slug}/stations/confirm")
    async def curator_stations_confirm(request: Request, slug: str):
        form = dict(await request.form())
        return await gw.handle_stations_confirm(request, slug, form)

    # ---- C41 survey retirement. GET renders the danger-zone confirmation page (blocking read-job ->
    # threadpool, `def`); the POST is async (it verifies the TOTP factor then takes the PUBLISH_LOCK for
    # the git rm -r). Both live under the survey hub path so the crumb + rail highlight stay coherent.
    @app.get("/gateway/curator/survey/{slug}/retire")
    def curator_survey_retire_confirm(request: Request, slug: str):
        return gw.handle_survey_retire_confirm(request, slug)

    @app.post("/gateway/curator/survey/{slug}/retire")
    async def curator_survey_retire(request: Request, slug: str):
        form = dict(await request.form())
        return await gw.handle_survey_retire(request, slug, form)

    @app.post("/gateway/curator/submission/{submission_id}/{action}")
    async def curator_action(request: Request, submission_id: str, action: str,
                             csrf_token: str = Form(default=""), note: str = Form(default=""),
                             confirm_overwrite: str = Form(default=""),
                             ack_pii: str = Form(default="")):
        if action not in ("approve", "return", "reject", "retry"):
            return gw._not_found()
        # Parse confirm_overwrite AND ack_pii as EXACT affirmative tokens, default DENY (design §5.2 /
        # C11b §2). NOT bool(str): "0"/"false"/any non-empty string would otherwise enable a silent
        # overwrite or a silent PII acknowledgement.
        confirm = confirm_overwrite.strip().lower() in ("1", "yes", "true", "on")
        ack = ack_pii.strip().lower() in ("1", "yes", "true", "on")
        return await gw.handle_curator_action(
            request, submission_id, action, csrf_token, note, confirm, ack)

    return app


async def _poll_forever(gw: Gateway) -> None:
    while True:
        try:
            await gw.poll_once()
        except Exception:  # noqa: BLE001 -- the loop must survive one bad pass, never die silently
            logger.exception("poll pass failed")
        await asyncio.sleep(_POLL_INTERVAL_S)
