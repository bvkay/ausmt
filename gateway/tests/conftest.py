"""Test seams (design §8): a fake clamd speaking INSTREAM over a real asyncio TCP server, an
in-process app via httpx ASGITransport, and zip-building helpers.

No docker, no real clamd, and NO pytest-asyncio (not among the four permitted deps). Async work runs
under a per-test asyncio.run via the `harness` context manager, so every test stays a plain sync
function that passes on Windows.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import zipfile
from pathlib import Path

import httpx

import os

from gateway import clamd
from gateway.app import create_app
from gateway.config import Config

# --------------------------------------------------------------------------------------------------
# C35b/D3 (code-health review F7): validator-oracle resolution.
# The cross-repo validator oracles (test_runner.py, test_edit_runner.py) used to skipif on a sibling
# ausmt-surveys checkout that no CI has, silently reverting the suite to same-author mocks. Now they
# resolve UNCONDITIONALLY: the SIBLING checkout when present (dev box — tests the LIVE cross-repo pair),
# else the VENDORED pinned copy (CI / fresh clones — tests the PINNED contract). "Neither present" is a
# broken checkout (the vendored copy is committed), so the oracle FAILS rather than skips.
# The validator is dependency-light (stdlib + optional yaml/mt_metadata) so the vendored copy RUNS in
# the stack-less gateway test env — no mt_metadata needed for the validate-survey contract itself.
# --------------------------------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).resolve().parent                    # gateway/tests
SIBLING_VALIDATOR_DIR = _TESTS_DIR.parents[1] / "ausmt-surveys" / "_validation"
VENDORED_VALIDATOR_DIR = _TESTS_DIR / "fixtures" / "vendored_validation"


def resolve_validator_dir() -> Path | None:
    """Return the directory holding validate_survey.py for the oracles: sibling if present, else the
    vendored pinned copy, else None (the caller FAILS — never skips — because the vendored copy is
    committed, so absence is a broken checkout). AUSMT_FORCE_VENDORED_VALIDATOR=1 forces the vendored
    branch even when a sibling is present, so the CI (no-sibling) path is verifiable on a dev box
    without touching the real sibling checkout."""
    force_vendored = os.environ.get("AUSMT_FORCE_VENDORED_VALIDATOR") == "1"
    if not force_vendored and (SIBLING_VALIDATOR_DIR / "validate_survey.py").is_file():
        return SIBLING_VALIDATOR_DIR
    if (VENDORED_VALIDATOR_DIR / "validate_survey.py").is_file():
        return VENDORED_VALIDATOR_DIR
    return None


def require_validator_dir() -> Path:
    """resolve_validator_dir() or FAIL loudly (never skip). The vendored copy is committed, so a None
    result means a broken checkout — an assert, not a skip (F7: no more silent same-author-mock fallback)."""
    d = resolve_validator_dir()
    assert d is not None, (
        "no validator available: neither the sibling ausmt-surveys/_validation checkout nor the "
        f"committed vendored copy at {VENDORED_VALIDATOR_DIR} was found. The vendored copy is committed, "
        "so this is a BROKEN CHECKOUT, not a legitimate skip (C35b/D3, review F7).")
    return d


# The EICAR test string. The fake clamd flags any stream containing it, so an "EICAR upload =>
# REJECTED_AV" test needs no live signatures.
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

SUBMIT_KEY = "test-submit-key-0123456789"  # >= 16 chars so fail_closed_startup() accepts it
GOOD_EMAIL = "tester@example.org"          # the PII grep fixture (design §8)


class FakeClamd:
    """A real asyncio TCP server speaking the INSTREAM subset the client uses. `mode` picks
    behaviour: clean / detect_eicar / always_found."""

    def __init__(self, mode: str = "clean"):
        self.mode = mode
        self.server: asyncio.AbstractServer | None = None
        self.host = "127.0.0.1"
        self.port = 0
        self.scanned = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, self.host, 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            header = await reader.readexactly(len(b"zINSTREAM\0"))
            if not header.startswith(b"zINSTREAM"):
                writer.close()
                return
            buf = bytearray()
            while True:
                size = int.from_bytes(await reader.readexactly(4), "big")
                if size == 0:
                    break
                buf += await reader.readexactly(size)
            self.scanned += 1
            found = self.mode == "always_found" or (self.mode == "detect_eicar" and EICAR in bytes(buf))
            writer.write(b"stream: Eicar-Test-Signature FOUND\0" if found else b"stream: OK\0")
            await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()


def scanner_via_fake(fake: FakeClamd):
    async def _scan(data: bytes):
        return await clamd.scan_bytes(fake.host, fake.port, data)
    return _scan


def scanner_clean():
    async def _scan(data: bytes):
        return clamd.ScanResult(clean=True, signature=None)
    return _scan


def scanner_down():
    async def _scan(data: bytes):
        raise clamd.ScanError("fake: clamd down")
    return _scan


def scanner_eicar_aware():
    """Flags any buffer containing the EICAR string; clean otherwise. No TCP needed."""
    async def _scan(data: bytes):
        if EICAR in data:
            return clamd.ScanResult(clean=False, signature="Eicar-Test-Signature")
        return clamd.ScanResult(clean=True, signature=None)
    return _scan


# --------------------------------------------------------------------------------------------------
# Zip builders
# --------------------------------------------------------------------------------------------------
def make_zip(members: dict[str, bytes], *, external_attrs: dict[str, int] | None = None) -> bytes:
    external_attrs = external_attrs or {}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            info = zipfile.ZipInfo(name)
            if name in external_attrs:
                info.external_attr = external_attrs[name]
            zf.writestr(info, data)
    return out.getvalue()


def good_package_zip() -> bytes:
    return make_zip({
        "mysurvey/survey.yaml": b"survey:\n  slug: mysurvey\n",
        "mysurvey/transfer_functions/edi/S01.edi": b">HEAD\n  DATAID=S01\n>END\n",
    })


def eicar_package_zip() -> bytes:
    """A structurally valid package whose bytes contain the EICAR string, so a scan flags it."""
    return make_zip({
        "mysurvey/survey.yaml": b"survey:\n  slug: mysurvey\n",
        "mysurvey/transfer_functions/edi/S01.edi": b">HEAD\n" + EICAR + b"\n>END\n",
    })


def ratio_bomb_zip() -> bytes:
    """A member with compress_size > 1 MiB (real stored bytes) but a LYING uncompressed file_size
    200x larger, forged directly into the zip headers. Real deflate can't produce ratio>100 with
    compress_size>1MiB (repetitive data compresses too small to pass the 1-MiB gate), so a genuine
    zip-bomb is forged, not compressed — which is exactly what a hostile submitter would send."""
    payload = b"A" * (2 * 1024 * 1024)  # 2 MiB STORED -> compress_size ~2 MiB (> 1 MiB gate)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("mysurvey/survey.yaml", b"s")
        zf.writestr("mysurvey/transfer_functions/edi/S01.edi", b"e")
        zf.writestr("mysurvey/big.bin", payload)
    raw = bytearray(out.getvalue())
    fake = len(payload) * 200
    name = b"mysurvey/big.bin"
    _patch_uncompressed_size(raw, name, fake, local=True)
    _patch_uncompressed_size(raw, name, fake, local=False)
    return bytes(raw)


def _patch_uncompressed_size(raw: bytearray, name: bytes, fake: int, *, local: bool) -> None:
    """Overwrite the uncompressed-size field (NOT compress-size) of a named member in either the
    local file header (PK\\x03\\x04) or the central directory record (PK\\x01\\x02)."""
    import struct
    sig = b"PK\x03\x04" if local else b"PK\x01\x02"
    name_off = 30 if local else 46
    size_off = 22 if local else 24
    i = 0
    while True:
        j = raw.find(sig, i)
        if j < 0:
            return
        if local:
            nlen = struct.unpack_from("<H", raw, j + 26)[0]
            elen = struct.unpack_from("<H", raw, j + 28)[0]
            span = name_off + nlen + elen
        else:
            nlen = struct.unpack_from("<H", raw, j + 28)[0]
            elen = struct.unpack_from("<H", raw, j + 30)[0]
            clen = struct.unpack_from("<H", raw, j + 32)[0]
            span = name_off + nlen + elen + clen
        if bytes(raw[j + name_off:j + name_off + nlen]) == name:
            struct.pack_into("<I", raw, j + size_off, fake)
        i = j + span


def corrupt_deflate_zip() -> bytes:
    """A zip whose central directory is intact (passes zipsafety.inspect) but whose compressed data
    for one DEFLATED member is corrupted, so decompression at extraction raises zlib.error/BadZipFile
    — NOT an OSError. This is the crafted zip the reviewer used to crash the runner (fix #3)."""
    import struct
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mysurvey/survey.yaml", b"survey:\n")
        zf.writestr("mysurvey/transfer_functions/edi/S01.edi", b">HEAD\n" + b"X" * 5000 + b"\n>END\n")
    raw = bytearray(out.getvalue())
    sig = b"PK\x03\x04"
    i = 0
    while True:
        j = raw.find(sig, i)
        if j < 0:
            break
        nlen = struct.unpack_from("<H", raw, j + 26)[0]
        elen = struct.unpack_from("<H", raw, j + 28)[0]
        csize = struct.unpack_from("<I", raw, j + 18)[0]
        name = bytes(raw[j + 30:j + 30 + nlen])
        data_off = j + 30 + nlen + elen
        if name.endswith(b"S01.edi") and csize > 10:
            for k in range(data_off + 3, data_off + min(csize, 40)):
                raw[k] ^= 0xFF  # flip a run of the compressed stream -> corrupt deflate
        i = data_off + csize
    return bytes(raw)


# --------------------------------------------------------------------------------------------------
# App harness
# --------------------------------------------------------------------------------------------------
# C11 curator fixtures. A configured curator key (>= 16 chars per the fail-closed floor) and a fake
# git seam so publish tests need no real git (design §8 — same injected-callable pattern as the clamd
# scanner seam). No rebuild seam: v2 publish is commit-and-push ONLY (the operator rebuilds by hand).
CURATOR_NAME = "curator1"
CURATOR_KEY = "curator-secret-key-0123456789"     # >= 16 chars
CURATOR_KEYS = f"{CURATOR_NAME}:{CURATOR_KEY}"

# The fixed commit-author identity a publish must use (design §5.3). Tests assert one of these
# markers appears in the git commit invocation (the -c user.name/user.email config flags).
COMMIT_AUTHOR_MARKERS = ("AusMT Gateway", "gateway@ausmt.local")


def make_config(tmp_path: Path, **overrides) -> Config:
    kwargs = dict(
        submit_key=SUBMIT_KEY,
        data_dir=Path(tmp_path) / "gw",
        max_upload_mb=1,
        max_inflight=8,
        max_per_day=25,
        job_timeout_s=900,
        clamd_host="127.0.0.1",
        clamd_port=3310,
        curator_keys=CURATOR_KEYS,
        surveys_live_dir=Path(tmp_path) / "surveys-live",
        session_ttl_s=12 * 3600,
        login_max_attempts=5,
        login_window_s=300,
    )
    kwargs.update(overrides)
    return Config(**kwargs)


class FakeGit:
    """A small in-memory model of the surveys-live git repo (design §5 v2, commit-and-push ONLY —
    NO rebuild). Records every invocation AND tracks enough state (current branch, HEAD ref, whether
    a rollback happened) to prove the fail-closed rollback restores the pre-state. No real repo, no
    real git — the whole point of the injected seam (design §8).

    STRICT (C35b/D2): every git verb this fake serves is enumerated in __call__; an unmodeled verb
    RAISES AssertionError naming the argv instead of returning a silent rc=0. Extending the fake to a
    new verb must be a conscious act, with the real-git lane (test_publish_real_git.py) as the
    reference for honest behaviour. The verbs modeled today: status, rev-parse, checkout, add, commit,
    merge, push, reset, clean, branch.

    Knobs:
      dirty=True             -> `git status --porcelain` reports a dirty tree (pre-flight abort test).
      start_branch="submitX" -> HEAD starts on a stale submit branch (rollback-restores-branch test).
      fail_on={verb:(rc,err)} -> make one git verb fail ('push', 'commit', 'merge', ...).
    """

    def __init__(self, fail_on: dict | None = None, *, dirty: bool = False,
                 start_branch: str = "main"):
        self.calls: list[list[str]] = []
        self.fail_on = fail_on or {}
        self._dirty = dirty
        self.branch = start_branch
        self.start_branch = start_branch
        self.head_ref = "cafe0000000000000000000000000000000000ff"  # a stable pre-state ref
        self.start_ref = self.head_ref
        self.reset_targets: list[str] = []   # every `reset --hard <ref>` target, for rollback asserts
        self.rolled_back = False
        self._pre_surveys: set[str] | None = None  # surveys/ entries that pre-existed (tracked)

    def __call__(self, args, *, cwd, env=None):
        from gateway.publish import GitResult
        self.calls.append(list(args))
        verb = _git_verb(args)
        if self._pre_surveys is None:
            # First call for this repo: snapshot the surveys/ entries that already exist. They stand
            # in for tracked/committed state, so a later `git clean` model spares them.
            surveys = Path(cwd) / "surveys"
            self._pre_surveys = {p.name for p in surveys.iterdir()} if surveys.exists() else set()

        if args[:2] == ["status", "--porcelain"]:
            return GitResult(returncode=0, stdout=(" M surveys/x\n" if self._dirty else ""), stderr="")
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return GitResult(returncode=0, stdout=self.branch + "\n", stderr="")
        if args[:2] == ["rev-parse", "HEAD"]:
            return GitResult(returncode=0, stdout=self.head_ref + "\n", stderr="")

        key = verb
        if key in self.fail_on:
            rc, err = self.fail_on[key]
            return GitResult(returncode=rc, stdout="", stderr=err)

        # Model the mutating verbs so branch/ref/rollback state stays coherent. STRICT (C35b/D2):
        # every verb this fake serves is enumerated below; the final `else` RAISES on any unmodeled
        # verb rather than returning a silent rc=0 (the old behaviour, which made push/merge/a typo'd
        # flag look like unconditional success). Extending the fake is now a deliberate act — add an
        # explicit branch here, with the REAL-git lane (test_publish_real_git.py) as the reference for
        # what honest behaviour is.
        if verb == "checkout":
            # -B <branch> creates+switches; -f <branch> / <branch> switches. NOTE (nit #8): the branch
            # target is modeled as args[-1], correct for the forms publish.py actually issues
            # (`checkout -B <b>`, `checkout -f <b>`, `checkout main`). A bare `checkout -f` with no
            # branch is never issued by the publish code, so it is intentionally NOT modeled — the
            # real-git lane covers the true checkout semantics.
            target = args[-1]
            self.branch = target
        elif verb == "commit":
            self.head_ref = "beef1111111111111111111111111111111111ff"  # a new post-commit ref
        elif verb == "reset":
            # `reset --hard <ref>` or `reset --hard` (empty tree).
            target = args[-1] if args[-1] != "--hard" else ""
            self.reset_targets.append(target)
            if target == self.start_ref:
                self.rolled_back = True
            if target:
                self.head_ref = target
        elif verb == "clean":
            # `git clean -fd -- surveys` removes UNTRACKED files under surveys/ only. A real repo
            # leaves TRACKED (previously-committed) survey dirs in place. Model that faithfully: on
            # the FIRST git call for a cwd, snapshot the surveys/ entries that already existed (they
            # stand in for tracked/committed state); clean removes only entries added SINCE that
            # snapshot (this publish's freshly-staged tree). So a rollback removes the staged tree but
            # never a pre-existing committed survey.
            import shutil
            surveys = Path(cwd) / "surveys"
            if surveys.exists():
                for child in surveys.iterdir():
                    if child.name in self._pre_surveys:
                        continue  # tracked/committed — git clean would not touch it
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
        elif verb == "rm":
            # `git rm -- <path>...` removes from the index AND the working tree. Model the working-tree
            # side so the removal rollback tests are honest (a rollback must restore a git-rm'd path).
            # The leading `--` and any flags are skipped; the rest are repo-relative paths. C41: `git rm
            # -r -- surveys/<slug>` retires a WHOLE survey (a DIRECTORY), so when `-r`/`-rf` is present a
            # directory target is removed recursively (rmtree) — modeled explicitly (C35b strict-fake:
            # extending the fake to survey-scope removal is a deliberate act, with the real-git lane in
            # test_publish_real_git.py as the reference for the true recursive-rm semantics).
            import shutil
            recursive = any(a.startswith("-") and "r" in a for a in args[1:] if a != "--")
            for arg in args[1:]:
                if arg == "--" or arg.startswith("-"):
                    continue
                p = Path(cwd) / arg
                if p.is_file():
                    p.unlink()
                elif p.is_dir() and recursive:
                    shutil.rmtree(p)
        elif verb in ("add", "merge", "push", "branch"):
            # No modeled state change, but these ARE verbs the publish/edit sequence legitimately
            # drives, so they get an explicit rc=0 (the fake does not model push ARRIVAL — the real-git
            # lane asserts the push reaches the bare origin; here `push` in fail_on is how a rejection
            # is simulated, handled above).
            pass
        else:
            raise AssertionError(
                f"FakeGit: unmodeled git verb {verb!r} (argv={list(args)!r}). C35b made FakeGit "
                "strict: model this verb explicitly in conftest.FakeGit.__call__ (with the real-git "
                "lane as the reference) instead of relying on a silent rc=0.")
        return GitResult(returncode=0, stdout="", stderr="")


def _git_verb(args) -> str:
    i = 0
    while i < len(args):
        if args[i] == "-c":
            i += 2
            continue
        return args[i]
    return ""


@contextlib.asynccontextmanager
async def app_client(tmp_path: Path, *, scanner=None, run_poll: bool = False,
                     git_runner=None, edit_runner=None, mailer=None, **cfg_overrides):
    """In-process app + httpx client. When run_poll is False the poll-loop task is NOT started (the
    tests drive gw.poll_once() explicitly for determinism); the app object is still returned so a
    test can reach gw = app.state.gw. git_runner injects the publish seam (there is no rebuild seam
    in the v2 commit-and-push model); edit_runner injects the C31 metadata-editor seam (an in-process
    call to the runner edit bodies, so no subprocess/yaml enters the gateway process during tests);
    mailer injects the K3 mail seam (a fake sender so smtplib never touches the network — when
    provided, self-serve issuance is ENABLED regardless of SMTP config)."""
    cfg = make_config(tmp_path, **cfg_overrides)
    app = create_app(cfg=cfg, scanner=scanner, git_runner=git_runner, edit_runner=edit_runner,
                     mailer=mailer)
    gw = app.state.gw
    # https base_url so the client's cookie jar retains the Secure session cookie (design §2 sets
    # Secure; over a plain-http base httpx drops it). The ASGI app is scheme-agnostic; in production
    # it is always behind Caddy/TLS, so Secure is correct and stays.
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="https://gw")
    try:
        yield client, app, gw, cfg
    finally:
        await client.aclose()
        gw.close()


async def curator_login(client, *, key: str = CURATOR_KEY):
    """POST the curator key and return the response. On success the httpx client retains the session
    cookie (cookie jar) so subsequent curator requests are authenticated."""
    return await client.post("/gateway/curator/login", data={"curator_key": key},
                             follow_redirects=False)


def csrf_for_session(client) -> str:
    """Derive the CSRF token the server expects for the client's current session cookie — the same
    value the server embeds in every rendered form. Lets a POST test carry a VALID token without
    scraping the HTML."""
    from gateway import curator_auth
    raw = client.cookies.get(curator_auth.SESSION_COOKIE)
    return curator_auth.csrf_token_for(raw)


async def settle_publish(gw, sid, *, tries: int = 50):
    """Yield control until the background publish task for `sid` leaves PUBLISHING (or a bound is
    hit). The publish runs as an asyncio task on the same loop; awaiting sleep(0) lets it progress
    deterministically without a real timer."""
    from gateway import states as states_mod
    for _ in range(tries):
        if gw.db.get(sid).state != states_mod.PUBLISHING:
            return
        # A small REAL sleep (not sleep(0)): the publish runs its blocking git calls via
        # asyncio.to_thread on the default executor, so the loop must actually wait for the executor
        # thread's done-callback to fire — a bare sleep(0) yields one iteration and misses it.
        await asyncio.sleep(0.01)
    # Fall through: some tests intentionally leave it PUBLISHING (reconciliation).


def seed_validated(gw, cfg, *, slug: str = "mysurvey", email: str = GOOD_EMAIL,
                   name: str = "Test Tester", write_reports: bool = True,
                   fail_item: bool = False, pii_in_preview: bool = False,
                   foreign_email_in_preview: str | None = None,
                   package_files: dict[str, str] | None = None,
                   token: str | None = None) -> str:
    """Insert a submission and drive it directly to VALIDATED via the DB (bypassing the scan/job
    pipeline — those are C10-tested), materialising a package tree + reports on disk so the checklist
    and preview have something to read. Returns the submission id.

    fail_item -> writes a FAIL validator item so the blocking-FAIL guard fires.
    pii_in_preview -> writes the submitter's OWN email into the built preview product.
    foreign_email_in_preview -> writes a DIFFERENT person's email into the preview (proves the
        generic email pattern fires, not just the submitter-email needle).
    package_files -> extra files written UNDER the package tree (relative path -> text). Used by the
        C11b tests to inject a hostile file name and a many-generic-hits case that the PII sweep sees.
    token -> when given, the submission gets this REAL status token (hashed like the app does) so the
        test can fetch /gateway/status/<token>; the default is an unusable placeholder hash.
    """
    import hashlib

    from gateway import db as db_mod
    from gateway import states as states_mod

    sid = db_mod.new_id()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else "t" * 64
    gw.db.insert_submission(
        submission_id=sid, zip_sha256="d" * 64, zip_bytes=10,
        submitter_name=name, submitter_email=email, submitter_orcid=None, token_hash=token_hash,
    )
    gw.db.transition(sid, states_mod.SCANNED, actor="gateway", reason="clean")
    gw.db.transition(sid, states_mod.VALIDATED, actor="runner", reason="validated", slug=slug)

    if write_reports:
        import json
        pkg = cfg.quarantine_dir / sid / "package" / slug
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "survey.yaml").write_text("survey:\n  slug: %s\n" % slug, encoding="utf-8")
        reports = cfg.quarantine_dir / sid / "reports"
        preview = reports / "preview-data"
        preview.mkdir(parents=True, exist_ok=True)
        items = [{"level": "PASS", "name": "structure", "message": "ok"}]
        if fail_item:
            items.append({"level": "FAIL", "name": "schema", "message": "missing required field"})
        (reports / "validate.json").write_text(json.dumps({"items": items}), encoding="utf-8")
        (reports / "preview-summary.json").write_text(
            json.dumps({"station_count": 1, "types": ["MT"], "coord_flags": [], "warnings": []}),
            encoding="utf-8")
        index = "<!doctype html><title>preview</title><p>preview shell</p>"
        if pii_in_preview:
            index += "<!-- %s -->" % email
        if foreign_email_in_preview:
            index += "<!-- contact %s -->" % foreign_email_in_preview
        (preview / "index.html").write_text(index, encoding="utf-8")
        (preview / "catalogue.json").write_text(json.dumps([[slug, "S01"]]), encoding="utf-8")
        if package_files:
            base = cfg.quarantine_dir / sid / "package"
            for rel, text in package_files.items():
                dest = base / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
    return sid


async def submit_zip(client, zip_bytes: bytes, *, email: str = GOOD_EMAIL, name: str = "Test Tester",
                     orcid: str | None = None, key: str | None = SUBMIT_KEY):
    files = {"file": ("package.zip", zip_bytes, "application/zip")}
    data = {"submitter_name": name, "submitter_email": email}
    if orcid is not None:
        data["submitter_orcid"] = orcid
    headers = {"X-AusMT-Submit-Key": key} if key is not None else {}
    return await client.post("/gateway/submit", files=files, data=data, headers=headers)


def run(coro):
    """Drive an async test body to completion. Every test function is sync and calls run(_body())."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------------------------------
# C31 metadata-editor seams + fixtures
# --------------------------------------------------------------------------------------------------
# A well-formed block-style survey.yaml with comments, a null field, a block-scalar abstract, and an
# UNKNOWN custom key the editor form does not model. The round-trip-fidelity contract (C31 §0.2/§3.1)
# is proved against this: an edit must touch nothing but the edited field + version + release_notes.
EDIT_EXEMPLAR = """\
schema_version: "0.2"
slug: demo-survey-2026
project_name: Demo Survey            # human-readable name
version: 1.0.0
country: Australia
region: South Australia

organisation:
  name: University of Example
  ror: null                          # ROR URL when known

abstract: >
  A short paragraph describing the survey that a naive emitter would re-wrap but which
  must stay exactly as written, word for word, across the round trip.

license: CC-BY-4.0
access:
  level: open
  embargo_until: null
  contact: null

# an unknown custom key the editor form does not model — must survive verbatim
custom_local_note: "keep me byte-for-byte"
"""


def write_survey_live(surveys_live: Path, slug: str = "demo-survey-2026",
                      yaml_text: str = EDIT_EXEMPLAR) -> Path:
    """Materialise a published survey package under surveys-live/surveys/<slug>/ with a survey.yaml
    (newline='' so the exact bytes land on disk on Windows too) + a token EDI so the validator sees a
    complete package. Returns the package dir."""
    pkg = surveys_live / "surveys" / slug
    (pkg / "transfer_functions" / "edi").mkdir(parents=True, exist_ok=True)
    with open(pkg / "survey.yaml", "w", encoding="utf-8", newline="") as fh:
        fh.write(yaml_text)
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  LAT=-30:08:45\n  LONG=136:58:12\n>FREQ\n", encoding="utf-8")
    return pkg


# Validator stand-ins for the in-process seam. In production the merge runs the REAL validator over
# a scratch copy; unit tests simulate the verdict so no real validator is needed on disk.
def validator_pass(_package_root) -> dict:
    return {"items": [{"level": "PASS", "check": "metadata", "message": "ok"}]}


def validator_fail(_package_root) -> dict:
    return {"items": [{"level": "FAIL", "check": "metadata", "message": "required field missing"}]}


def inproc_edit_runner(surveys_live: Path, *, validator_override=validator_pass,
                       validator_path: str = ""):
    """An in-process C31 edit seam for the gateway-flow tests: dispatch a job dict straight through
    the runner's REAL job dispatch (_dispatch_edit — slug charset validation, containment, scratch
    layout included), just without the file queue in between. ruamel/yaml stays out of every
    gateway/ module exactly as in production — the import lives in gateway.runner.edit, invoked here
    by the TEST harness (the subprocess import-hygiene test proves the gateway process itself never
    pulls it). `validator_override` (callable(package_root)->report) simulates the validator verdict;
    pass None + a real validator_path to run the real subprocess."""
    import tempfile

    from gateway.runner import edit as edit_mod
    from gateway.runner.runner import RunnerConfig

    scratch_root = Path(tempfile.mkdtemp(prefix="edit-inproc-"))
    cfg = RunnerConfig(
        incoming_dir=scratch_root / "incoming", quarantine_dir=scratch_root / "quarantine",
        jobs_dir=scratch_root / "jobs", validator_path=validator_path,
        surveys_root=Path(surveys_live))

    def _seam(job: dict) -> dict:
        import uuid
        scratch = cfg.jobs_dir / "edit" / "scratch" / uuid.uuid4().hex
        try:
            # The merge AND the C43 Stage-3b collection_batch jobs both validate patched packages via
            # edit._validate_patched (per survey for the batch); override it so the test controls the
            # per-survey verdict. The override callable receives the survey package_root, so a batch
            # test can PASS most surveys and FAIL a chosen one by inspecting package_root.name (slug).
            if validator_override is not None and job.get("kind") in ("merge", "collection_batch"):
                orig = edit_mod._validate_patched
                edit_mod._validate_patched = (
                    lambda pr, _nb, _vp, _sd: validator_override(pr))
                try:
                    return edit_mod._dispatch_edit(cfg, job, scratch)
                finally:
                    edit_mod._validate_patched = orig
            return edit_mod._dispatch_edit(cfg, job, scratch)
        except edit_mod.EditError as exc:
            return {"ok": False, "error": str(exc)}

    return _seam
