"""C43 Stage 2a verification pins (record D13 + the contract's pin list). Each pin states its failure
criterion (Invariant 10) and is mutation-provable — the report carries a captured failing run for each
guarded behaviour. Async bodies run under conftest.run().

Pins here:
  * PHASE QUADRANT + φyx UNWRAP (phaseqc, the authoritative server-side seam the STATIONS_JS mirrors):
    the +180 presentation shift on t[4] is inverted before classifying — a TRUE-Q3 station (stored t[4]
    near 0…90) classifies IN-quadrant; reading the stored value as true phase mis-classifies it.
  * [FC-2] LAG LABEL: with served ≠ published the Stations panel carries the publish-pending label.
  * CSP SWEEP extended to every NEW Stage-2a renderer/JS constant + rendered surface.
  * HISTORY READ-ONLY: the history-job argv carries only the read-only `log` verb (allowlist assertion).
  * QUARANTINE CONTAINMENT: a traversal attempt 404s; a real package file serves with the safe
    attachment + nosniff discipline.
  * KEYS: a note is stored + rendered + ABSENT from any git-bound artifact; submission counts are
    correct; revoked rows render read-only (no note editor, no revoke button).
  * S2a-5 BUILD-ID SHORTENER: canonical triple-barrel -> short display; malformed -> verbatim fallback.
"""
from __future__ import annotations

import re
import subprocess

from gateway import builddisplay, curatorpage, phaseqc
from gateway.runner import edit as edit_mod
from gateway.tests.conftest import (
    CURATOR_NAME, FakeGit, app_client, csrf_for_session, curator_login, inproc_edit_runner, run,
    write_survey_live,
)


# ==================================================================================================
# Phase quadrant classification + the φyx +180 unwrap (phaseqc — the authoritative seam)
# ==================================================================================================
def test_phi_xy_quadrant_classification():
    """φxy (t[3], stored = true) classifies against Q1 (0…90). FAILS IF an in-Q1 value is called out,
    or an out-of-Q1 value is called in."""
    assert phaseqc.in_quadrant_xy(0.0) is True
    assert phaseqc.in_quadrant_xy(45.0) is True
    assert phaseqc.in_quadrant_xy(90.0) is True
    assert phaseqc.in_quadrant_xy(-10.0) is False
    assert phaseqc.in_quadrant_xy(120.0) is False
    assert phaseqc.in_quadrant_xy(None) is None


def test_phi_yx_unwrap_true_q3_classifies_in_quadrant():
    """THE φyx-UNWRAP PIN. A station whose TRUE φyx sits in Q3 (−180…−90) has a STORED t[4] near 0…90
    (because engine _edi_tf stores phs_yx_adj = true + 180, re-wrapped). The workbench MUST subtract
    the shift and classify the TRUE phase — so a true-Q3 station classifies IN-quadrant. FAILS IF the
    workbench reads the stored value as the true phase (then stored 45° would look like Q1 = 'in Q1',
    and against Q3 it would read as OUT — the mis-classification this pin catches).

    NON-VACUOUS: for true φyx = −135°, stored t[4] = +45°. in_quadrant_yx(+45°) must be True (it
    unwraps to −135° ∈ Q3). A naive `Q3_LO <= 45 <= Q3_HI` is False — so a no-unwrap implementation
    fails this exact assertion."""
    for true_yx in (-135.0, -100.0, -170.0, -90.0, -180.0, -91.0):
        stored = phaseqc.wrap180(true_yx + phaseqc.YX_PRESENTATION_SHIFT_DEG)  # == engine norm_phase
        assert phaseqc.true_phi_yx(round(stored, 1)) is not None
        assert abs(phaseqc.true_phi_yx(round(stored, 1)) - true_yx) < 0.05, (true_yx, stored)
        assert phaseqc.in_quadrant_yx(round(stored, 1)) is True, (
            f"true φyx={true_yx} (stored t[4]={round(stored, 1)}) must classify IN Q3 after the +180 "
            "unwrap — reading the stored value directly would mis-classify it")


def test_phi_yx_unwrap_true_q1_classifies_out_of_quadrant():
    """The converse: a station whose TRUE φyx is in Q1 (a genuinely wrong-quadrant yx) has stored t[4]
    near ±135/−170, and must classify OUT of Q3. FAILS IF the unwrap is skipped (stored −135 would then
    read as Q3 = 'in', hiding the real wrong-quadrant station)."""
    for true_yx in (45.0, 10.0, -45.0, -89.0):
        stored = round(phaseqc.wrap180(true_yx + phaseqc.YX_PRESENTATION_SHIFT_DEG), 1)
        assert phaseqc.in_quadrant_yx(stored) is False, (true_yx, stored)


def test_classify_series_aggregate_verdict():
    """classify_series aggregates a phase column: any_out drives the ⚠ verdict + red points, all_in the
    ✓ verdict. FAILS IF a single out-of-quadrant point does not flip any_out, or an all-None series
    invents a verdict."""
    # xy series: one out-of-Q1 point among in-Q1 points => any_out True, all_in False.
    xy = phaseqc.classify_series([10.0, 45.0, 200.0], mode="xy")
    assert xy["any_out"] is True and xy["all_in"] is False and xy["n_classified"] == 3
    assert xy["points"] == [True, True, False]
    # yx series (stored values): all TRUE-Q3 => all_in True. Stored for true −135/−100 = +45/+80.
    yx_stored = [round(phaseqc.wrap180(v + 180.0), 1) for v in (-135.0, -100.0)]
    yx = phaseqc.classify_series(yx_stored, mode="yx")
    assert yx["all_in"] is True and yx["any_out"] is False
    # all-None => no verdict.
    empty = phaseqc.classify_series([None, None], mode="xy")
    assert empty["any_out"] is False and empty["all_in"] is False and empty["n_classified"] == 0


def test_stations_js_mirrors_phaseqc_constants():
    """SOURCE ASSERTION: the browser-side STATIONS_JS embeds the SAME phase constants phaseqc defines,
    so the mirror cannot silently drift from the pinned server-side spec. FAILS IF the JS drops the
    +180 shift, the Q1/Q3 bounds, or the unwrap-then-classify structure."""
    js = curatorpage.STATIONS_JS
    assert "YX_SHIFT = 180.0" in js, "the +180 presentation shift must be in the JS mirror"
    assert "Q1_LO = 0.0" in js and "Q1_HI = 90.0" in js
    assert "Q3_LO = -180.0" in js and "Q3_HI = -90.0" in js
    # trueYx must SUBTRACT the shift then wrap (the unwrap), and inQ3 must go through trueYx.
    assert "wrap180(stored - YX_SHIFT)" in js, "φyx must be unwrapped (stored - shift), not read raw"
    assert "var v = trueYx(stored)" in js, "inQ3 must classify the UNWRAPPED true phase"


# ==================================================================================================
# [FC-2] lag label on the Stations panel
# ==================================================================================================
def _hub_survey(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    write_survey_live(surveys_live, slug="s2a-survey",
                      yaml_text="schema_version: \"0.2\"\nslug: s2a-survey\n"
                                "project_name: S2a\nversion: 1.0.0\n")
    return surveys_live


def test_fc2_lag_label_rendered_when_served_differs_from_published(tmp_path):
    """[FC-2] LAG-LABEL PIN. The Stations tab carries the server-rendered published HEAD in
    data-published-head; the stations JS compares it to the served build's source_commit and renders
    the 'facts from build … — publish pending' label ON THE PANEL. This pin proves the label MACHINERY
    is present: the panel scaffold carries the published HEAD hook AND the JS carries the publish-
    pending label string + the lag comparison. FAILS IF the hook or the label machinery is absent."""
    async def _body():
        surveys_live = _hub_survey(tmp_path)

        class HeadGit(FakeGit):
            def __call__(self, args, *, cwd, env=None):
                # read_published_head runs `rev-parse --short HEAD` — answer with a KNOWN published sha.
                from gateway.publish import GitResult
                if args[:2] == ["rev-parse", "--short"]:
                    return GitResult(returncode=0, stdout="pub1234\n", stderr="")
                return super().__call__(args, cwd=cwd, env=env)

        async with app_client(tmp_path, git_runner=HeadGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/s2a-survey?tab=stations")
            assert r.status_code == 200
            # The STATIONS PANEL scaffold (not merely the drift chip elsewhere on the page) carries the
            # published-HEAD hook the stations JS reads — assert it on the survey-stations div's own tag
            # so the pin is scoped to THIS panel (the drift chip carries its own data-published-head).
            m = re.search(r'<div id="survey-stations"[^>]*>', r.text)
            assert m, "the survey-stations panel scaffold must render"
            assert 'data-published-head="pub1234"' in m.group(0), (
                "the stations panel itself must carry the [FC-2] published-HEAD hook")
            assert 'src="/gateway/curator/stations.js"' in r.text
        # The JS carries the [FC-2] label + the lag comparison (served source_commit vs published HEAD).
        js = curatorpage.STATIONS_JS
        assert "publish pending" in js, "the [FC-2] publish-pending label must be in the stations JS"
        assert "lagPending" in js and "publishedHead" in js, "the served-vs-published lag compare"
    run(_body())


# ==================================================================================================
# CSP sweep extended to every NEW Stage-2a renderer + JS constant
# ==================================================================================================
def test_c43_stage2a_js_constants_are_raw_and_csp_clean():
    """Every NEW Stage-2a JS constant (STATIONS_JS) is RAW JS — no <script> wrapper, no on*= handler,
    and no innerHTML-with-DATA path (SVG is built via createElementNS, values via textContent). FAILS
    IF a Stage-2a constant ships wrapped/inline, or a new innerHTML=<data> path lands."""
    js = curatorpage.STATIONS_JS
    assert "<script" not in js.lower(), "STATIONS_JS must be RAW JS, not <script>-wrapped"
    assert not re.search(r"""\bon[a-z]{3,}\s*=\s*['"]""", js), "no on*= handler in STATIONS_JS"
    # No innerHTML assignment anywhere (the SVG-via-string vector the contract forbids for data).
    assert ".innerHTML" not in js, "STATIONS_JS must never assign innerHTML (createElementNS/textContent only)"
    # createElementNS IS used (the SVG is genuinely DOM-built, not string-concatenated into innerHTML).
    assert "createElementNS" in js


def test_c43_stage2a_source_csp_sweep():
    """SOURCE-LEVEL CSP sweep of the modules Stage-2a touched: no inline on*= handler and no inline
    <script> block without src=. Mirrors test_serve_reconcile.py's sweep, extended to the Stage-2a
    additions. FAILS IF a new inline handler/script lands in a listed module."""
    from pathlib import Path
    pkg = Path(__file__).resolve().parents[1]
    offenders = []
    for name in ("curatorpage.py", "app.py"):
        p = pkg / name
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"""\bon[a-z]{3,}\s*=\s*['"\\]""", line):
                offenders.append(f"{name}:{i} (handler): {line.strip()[:90]}")
            if re.search(r"<script(?![^>]*\bsrc\s*=)[^>]*>", line):
                offenders.append(f"{name}:{i} (inline <script>): {line.strip()[:90]}")
    assert offenders == [], "inline JS is dead under the CSP:\n" + "\n".join(offenders)


def test_stations_and_history_rendered_surfaces_csp_clean(tmp_path):
    """RENDERED CSP sweep of the new Stations + History tabs (served bytes). FAILS IF either ships an
    inline <script> or an on*= handler."""
    async def _body():
        surveys_live = _hub_survey(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            for tab in ("stations", "history"):
                r = await client.get(f"/gateway/curator/survey/s2a-survey?tab={tab}")
                assert r.status_code == 200, (tab, r.status_code)
                for m in re.finditer(r"<script\b[^>]*>", r.text):
                    assert re.search(r"\bsrc\s*=", m.group(0)), f"{tab}: inline <script>: {m.group(0)}"
                assert re.findall(r"<[^>]*\son[a-z]{2,}\s*=", r.text) == [], f"{tab}: inline handler"
            # The stations.js route serves RAW JS (not <script>-wrapped), session-gated.
            r = await client.get("/gateway/curator/stations.js")
            assert r.status_code == 200
            assert "<script" not in r.text.lower()
    run(_body())


# ==================================================================================================
# History read-only (allowlist assertion, S1 fix-round F1 style)
# ==================================================================================================
def test_history_argv_is_read_only_log_verb():
    """HISTORY READ-ONLY PIN (allowlist style). The history-job argv carries ONLY the read-only `log`
    verb — never a mutating git verb. FAILS IF the argv's subcommand is anything but an allow-listed
    read-only verb (proven able to fail below by asserting a mutating verb is refused)."""
    from pathlib import Path
    argv = edit_mod._history_argv(Path("/srv/surveys/surveys/x"), Path("/srv/surveys"))
    verb = edit_mod._history_subcommand(argv)
    assert verb == "log", f"history argv subcommand must be 'log', got {verb!r}"
    assert verb in edit_mod._HISTORY_READONLY_VERBS
    # No mutating verb appears anywhere in the argv (belt-and-braces: the whole token list is scanned).
    mutating = {"commit", "push", "add", "rm", "reset", "checkout", "merge", "rebase", "clean",
                "tag", "branch", "fetch", "pull", "gc", "prune", "filter-branch", "update-ref"}
    assert not (set(argv) & mutating), f"history argv must carry no mutating verb: {argv}"


def test_history_job_refuses_non_read_only_verb(monkeypatch, tmp_path):
    """MUTATION-PROOF for the read-only assertion: if the argv builder is subverted to emit a mutating
    verb, run_history_job REFUSES (EditError, 'non-read-only') rather than running it — BEFORE any
    subprocess. FAILS IF a non-read-only verb can slip through the guard (proven able to fail: this is
    exactly the injected mutating-verb argv, and the pre-check must catch it)."""
    import pytest

    # A real package dir with a survey.yaml so the job passes its existence check and REACHES the
    # verb guard (the guard, not the missing-file branch, is what must fire).
    pkg = tmp_path / "surveys" / "x"
    pkg.mkdir(parents=True)
    (pkg / "survey.yaml").write_text("slug: x\n", encoding="utf-8")

    def _evil_argv(package_root, surveys_root):
        return ["git", "-C", str(package_root), "commit", "-m", "x"]

    monkeypatch.setattr(edit_mod, "_history_argv", _evil_argv)
    with pytest.raises(edit_mod.EditError, match="non-read-only"):
        edit_mod.run_history_job(pkg, surveys_root=tmp_path)


def test_history_tab_renders_real_git_log(tmp_path):
    """END-TO-END: the History tab renders the survey package's real git log (subject + release-note
    body, author, date) via the runner history read-job. FAILS IF the tab does not surface a committed
    change, or leaks a mutating action (rename/retire — Stage 4)."""
    async def _body():
        surveys_live = tmp_path / "surveys-live"
        write_survey_live(surveys_live, slug="hist-survey",
                          yaml_text="schema_version: \"0.2\"\nslug: hist-survey\n"
                                    "project_name: Hist\nversion: 1.0.0\n")
        # Make surveys-live a REAL git repo so the history read-job has commits to read.
        root = surveys_live

        def git(*a):
            subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True)

        git("init", "-q")
        git("config", "user.email", "curator@ausmt.local")
        git("config", "user.name", "AusMT Gateway")
        git("add", "-A")
        git("commit", "-qm", "initial import of hist-survey")
        (root / "surveys" / "hist-survey" / "survey.yaml").write_text(
            "schema_version: \"0.2\"\nslug: hist-survey\nproject_name: Hist\nversion: 1.1.0\n",
            encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "metadata edit by curator:alice\n\nfixed the citation author")

        async with app_client(tmp_path, git_runner=FakeGit(),
                              edit_runner=inproc_edit_runner(surveys_live),
                              surveys_live_dir=surveys_live) as (client, _app, _gw, _cfg):
            await curator_login(client)
            r = await client.get("/gateway/curator/survey/hist-survey?tab=history")
            assert r.status_code == 200
            assert "initial import of hist-survey" in r.text
            assert "metadata edit by curator:alice" in r.text
            assert "fixed the citation author" in r.text          # the release-note body renders
            # NO rename/retire ACTION in the History tab (Stage 4). Read-only: the History body carries
            # no <form> and no rename/retire action route. (The copy may mention "rename" descriptively
            # — the pin is on the absence of an ACTION, not the word.)
            history_body = r.text.split('history</h1>', 1)[-1]
            assert "<form" not in history_body, "the History tab must carry no action form (read-only)"
            assert "/rename" not in r.text and "/retire" not in r.text
    run(_body())


# ==================================================================================================
# Quarantine containment (preview-route style)
# ==================================================================================================
def _seed_quarantined(gw, cfg, *, slug="badsurvey", files=None):
    """Insert a submission, drive it SCANNED->QUARANTINED, and materialise a package tree on disk."""
    from gateway import db as db_mod
    from gateway import states as states_mod
    sid = db_mod.new_id()
    gw.db.insert_submission(submission_id=sid, zip_sha256="q" * 64, zip_bytes=10,
                            submitter_name="Bad Actor", submitter_email="b@example.org",
                            submitter_orcid=None, token_hash="q" * 64)
    gw.db.transition(sid, states_mod.SCANNED, actor="gateway", reason="clean")
    gw.db.transition(sid, states_mod.QUARANTINED, actor="runner",
                     reason="validator reported FAIL", slug=slug)
    pkg = cfg.quarantine_dir / sid / "package" / slug
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "survey.yaml").write_text("slug: %s\n" % slug, encoding="utf-8")
    for rel, text in (files or {}).items():
        dest = cfg.quarantine_dir / sid / "package" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    return sid


def test_quarantine_view_lists_files_and_reason(tmp_path):
    """The quarantine detail view lists the package files + the refusal reason for a QUARANTINED
    submission. FAILS IF the file listing or the reason is absent."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            sid = _seed_quarantined(gw, cfg, files={"badsurvey/notes.txt": "hello"})
            r = await client.get(f"/gateway/curator/quarantine/{sid}")
            assert r.status_code == 200
            assert "validator reported FAIL" in r.text          # the refusal reason
            assert "notes.txt" in r.text                          # a listed package file
    run(_body())


def test_quarantine_containment_traversal_404s(tmp_path):
    """QUARANTINE CONTAINMENT PIN. A `..` traversal in the file subpath resolves outside the package
    root and 404s; a real package file serves with the safe attachment + nosniff discipline. FAILS IF a
    traversal escapes containment, or a served file is inline-renderable (no attachment/nosniff)."""
    async def _body():
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            sid = _seed_quarantined(gw, cfg, files={"badsurvey/data.edi": ">HEAD\n"})
            # Plant a REAL file OUTSIDE the package root (a sibling reports/ dir) so the traversal pin is
            # NON-VACUOUS: with containment disabled, `../reports/secret.txt` would resolve to this
            # existing file and be SERVED. Containment must 404 it instead.
            outside = cfg.quarantine_dir / sid / "reports"
            outside.mkdir(parents=True, exist_ok=True)
            (outside / "secret.txt").write_text("curator-only report bytes", encoding="utf-8")
            # A real IN-PACKAGE file serves, forced to download, nosniff, under a locked-down CSP.
            ok = await client.get(f"/gateway/curator/quarantine/{sid}/file/badsurvey/data.edi")
            assert ok.status_code == 200
            assert ok.headers.get("content-disposition") == "attachment"
            assert ok.headers.get("x-content-type-options") == "nosniff"
            assert "default-src 'none'" in (ok.headers.get("content-security-policy") or "")
            # Traversals that escape the package root => 404. Use %2f (URL-encoded slash) so httpx does
            # NOT normalise the `..` away client-side — the encoded form reaches the handler as a
            # literal `../` subpath, proving SERVER-SIDE containment (not the client) stops it (the same
            # mechanism the preview-route containment test uses). The reports/secret.txt case is the
            # non-vacuous one: that file EXISTS one level above the package root, so a disabled
            # containment check would resolve to it and serve it.
            for evil in ("..%2f..%2f..%2f..%2fetc%2fpasswd", "..%2freports%2fsecret.txt",
                         "..%2freports%2fvalidate.json"):
                bad = await client.get(f"/gateway/curator/quarantine/{sid}/file/{evil}")
                assert bad.status_code == 404, (evil, bad.status_code)
                assert b"curator-only report bytes" not in bad.content
    run(_body())


def test_quarantine_non_quarantined_id_404s(tmp_path):
    """The quarantine surface 404s for an id that is NOT in QUARANTINE (no oracle for other states
    through this surface). FAILS IF a non-quarantined submission is inspectable here."""
    async def _body():
        from gateway.tests.conftest import seed_validated
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            vid = seed_validated(gw, cfg)   # a VALIDATED (not quarantined) submission
            r = await client.get(f"/gateway/curator/quarantine/{vid}")
            assert r.status_code == 404
    run(_body())


# ==================================================================================================
# Keys deltas (D7)
# ==================================================================================================
def test_key_note_stored_rendered_and_counts(tmp_path):
    """KEYS PIN. A note set on a key is stored (sqlite), rendered on the page, and the submission count
    + unused-key nudge render. FAILS IF the note round-trip breaks, the count is wrong, or the nudge is
    missing for a never-used key."""
    async def _body():
        from gateway import uploader_keys as uploader_keys_mod
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            kid = gw.db.create_uploader_key(name="field-team-1", email=None,
                                            key_sha256=uploader_keys_mod.key_hash("k1"),
                                            created_by=CURATOR_NAME)
            csrf = csrf_for_session(client)
            # Set a note via the route.
            r = await client.post(f"/gateway/curator/uploaders/{kid}/note",
                                  data={"note": "for the SA field campaign", "csrf_token": csrf},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert gw.db.list_uploader_keys()[0].note == "for the SA field campaign"
            # Attribute two submissions to this uploader (audit trail) + one to another key.
            for i in range(2):
                gw.db.insert_submission(submission_id=("A%025d" % i)[:26].upper().replace(" ", "0"),
                                        zip_sha256="z%d" % i, zip_bytes=1, submitter_name="s",
                                        submitter_email="e", submitter_orcid=None,
                                        token_hash="t%d" % i, uploader_name="field-team-1")
            page = await client.get("/gateway/curator/uploaders")
            assert "for the SA field campaign" in page.text     # note rendered
            assert "never used" in page.text                     # unused-key nudge (never used)
            assert "uploader-key-rotation" in page.text          # rotation runbook link
            counts = gw.db.submission_counts_by_uploader()
            assert counts.get("field-team-1") == 2
    run(_body())


def test_key_note_absent_from_git_bound_artifacts(tmp_path):
    """PII-CONTAINMENT PIN (D2.5): a key note lives ONLY in sqlite — it NEVER enters surveys-live (the
    git-bound publication ledger). FAILS IF a note byte reaches any file under surveys-live."""
    async def _body():
        from gateway import uploader_keys as uploader_keys_mod
        surveys_live = _hub_survey(tmp_path)
        async with app_client(tmp_path, git_runner=FakeGit(),
                              surveys_live_dir=surveys_live) as (client, _app, gw, cfg):
            await curator_login(client)
            kid = gw.db.create_uploader_key(name="k", email=None,
                                            key_sha256=uploader_keys_mod.key_hash("k1"),
                                            created_by=CURATOR_NAME)
            csrf = csrf_for_session(client)
            needle = "NOTE-NEEDLE-DO-NOT-COMMIT-abc123"
            await client.post(f"/gateway/curator/uploaders/{kid}/note",
                              data={"note": needle, "csrf_token": csrf}, follow_redirects=False)
            # The needle is in the DB...
            assert gw.db.list_uploader_keys()[0].note == needle
            # ...and NOWHERE under surveys-live (the only git-bound tree the gateway touches).
            from pathlib import Path
            for p in Path(surveys_live).rglob("*"):
                if p.is_file():
                    assert needle not in p.read_bytes().decode("utf-8", "replace"), (
                        f"key note leaked into git-bound artifact {p}")
    run(_body())


def test_revoked_key_renders_read_only(tmp_path):
    """A revoked key stays listed as an audit row with NO note editor and NO revoke button (read-only).
    FAILS IF a revoked row offers an editable note form or a revoke action."""
    async def _body():
        from gateway import uploader_keys as uploader_keys_mod
        async with app_client(tmp_path, git_runner=FakeGit()) as (client, _app, gw, cfg):
            await curator_login(client)
            kid = gw.db.create_uploader_key(name="old-key", email=None,
                                            key_sha256=uploader_keys_mod.key_hash("k1"),
                                            created_by=CURATOR_NAME)
            gw.db.set_uploader_key_note(kid, note="the revoked note")
            assert gw.db.revoke_uploader_key(kid, revoked_by=CURATOR_NAME) is True
            page = await client.get("/gateway/curator/uploaders")
            assert page.status_code == 200
            assert "revoked" in page.text
            assert "the revoked note" in page.text                # note shown read-only
            # No note-editor FORM and no revoke FORM target this revoked key id.
            assert f"/gateway/curator/uploaders/{kid}/note" not in page.text
            assert f"/gateway/curator/uploaders/{kid}/revoke" not in page.text
    run(_body())


# ==================================================================================================
# S2a-5 build-id display shortener
# ==================================================================================================
def test_build_id_shortener_canonical_and_verbatim_fallback():
    """S2a-5 PIN. A canonical triple-barrel build id shortens to '<source short> · HH:MM UTC'; a
    malformed id falls back VERBATIM (never hide information). FAILS IF the canonical form is not
    shortened, or a malformed id is mangled/hidden instead of shown verbatim."""
    canon = "252a96fed49c74477ed24e159e6689c8100fcb4c-b898f26-2026-07-10T06:00:39.252632+00:00"
    assert builddisplay.short_build_id(canon) == "b898f26 · 06:00 UTC"
    assert builddisplay.short_build_id(
        "252a96fed49c74477ed24e159e6689c8100fcb4c-b898f26-2026-07-10T06:00:39Z") == "b898f26 · 06:00 UTC"
    assert builddisplay.short_build_id("unknown-unknown-2026-07-10T06:00:39+00:00") == "unknown · 06:00 UTC"
    # Malformed => verbatim.
    assert builddisplay.short_build_id("not-a-build-id") == "not-a-build-id"
    assert builddisplay.short_build_id("just some text with no barrels") == "just some text with no barrels"
    assert builddisplay.short_build_id("") == ""
    assert builddisplay.short_build_id(None) == ""


def test_build_id_shortener_mirrored_in_chip_and_panel_js():
    """SOURCE ASSERTION: both the drift chip (CONTEXT_BAR_JS) and the Served-build card (SERVE_PANEL_JS)
    embed the shortBuildId mirror AND set the full id on hover via a title attribute (not markup).
    FAILS IF either chrome drops the shortener or the full-id-on-hover affordance."""
    for const in (curatorpage.CONTEXT_BAR_JS, curatorpage.SERVE_PANEL_JS):
        assert "function shortBuildId(id)" in const, "the shortener mirror must be in both JS constants"
        assert "setAttribute('title'" in const, "the full id must be available on hover (title attr)"
