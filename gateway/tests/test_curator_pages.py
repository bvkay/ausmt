"""Curator queue/detail rendering + return/reject + the PII surface split (design §3/§4/§8).

Guards under test:
- queue lists VALIDATED/RETURNED/PUBLISH_FAILED newest-first with the submitter + WARN count.
- detail renders the submitter block (curator-only PII), the checklist, the report bundle, and the
  action forms WITH a CSRF hidden field.
- return/reject record the note with actor curator:<name>; a RETURNED submission's note appears on
  the PUBLIC status page but its submitter block does NOT (the PII split).
- PII: the submitter email fixture appears in the CURATOR detail HTML (by design) but NOT in the
  served preview output, and NOT on the public status page.
"""
from __future__ import annotations

from gateway import curator_auth, states
from gateway.tests.conftest import (
    CURATOR_NAME, FakeGit, app_client, csrf_for_session, curator_login, run, seed_validated,
    settle_publish,
)

PII_EMAIL = "curator-visible-7781@example.test"
PII_NAME = "Detailview Submittername"


class _BlockingGit(FakeGit):
    """A FakeGit whose FIRST invocation blocks until `release` is set, holding the publish task at
    its pre-flight git call so the submission stays deterministically in PUBLISHING while the test
    inspects the public status page (review finding 2 — the PUBLISHING-window leak). The git call
    runs inside asyncio.to_thread, so blocking on a threading.Event does not stall the event loop."""

    def __init__(self):
        import threading
        super().__init__()
        self.release = threading.Event()
        self._held_once = False

    def __call__(self, args, *, cwd, env=None):
        if not self._held_once:
            self._held_once = True
            self.release.wait(timeout=15)  # bounded: a bug fails the test, never hangs the suite
        return super().__call__(args, cwd=cwd, env=env)


def test_queue_lists_actionable_states(tmp_path):
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            v = seed_validated(gw, cfg, slug="alpha", name=PII_NAME)
            # A RETURNED one (terminal for this submission but still shown in the queue history view).
            r = seed_validated(gw, cfg, slug="beta")
            gw.db.transition(r, states.RETURNED, actor="curator:curator1", reason="needs a licence")
            await curator_login(client)
            page = await client.get("/gateway/curator/queue")
            assert page.status_code == 200
            assert v[:12] in page.text
            assert "alpha" in page.text and "beta" in page.text
            assert PII_NAME in page.text  # the submitter name shows in the curator queue
    run(_body())


def test_detail_shows_submitter_and_csrf_form(tmp_path):
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email=PII_EMAIL, name=PII_NAME)
            await curator_login(client)
            page = await client.get(f"/gateway/curator/submission/{sid}")
            assert page.status_code == 200
            # Curator-only PII is present here BY DESIGN (design §2).
            assert PII_EMAIL in page.text
            assert PII_NAME in page.text
            # Every action form carries the CSRF hidden field.
            assert curator_auth.CSRF_FIELD in page.text
            expected = csrf_for_session(client)
            assert expected in page.text
            # The checklist + report bundle render.
            assert "Checklist" in page.text
            assert "Report bundle" in page.text
    run(_body())


def test_return_note_on_public_status_but_not_submitter(tmp_path):
    # THE PII split (design §8): a RETURNED submission's note surfaces on the PUBLIC status page, but
    # its submitter block does NOT. Failure criterion: fails if the public page leaks the submitter
    # email/name, or if the return note never reached the public page.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            # Seed a submission the normal way so it has a real token for the public status page.
            from gateway import db as db_mod
            sid = db_mod.new_id()
            token = "public-status-token-xyz"
            import hashlib
            gw.db.insert_submission(
                submission_id=sid, zip_sha256="e" * 64, zip_bytes=10, submitter_name=PII_NAME,
                submitter_email=PII_EMAIL, submitter_orcid=None,
                token_hash=hashlib.sha256(token.encode()).hexdigest())
            gw.db.transition(sid, states.SCANNED, actor="gateway", reason="clean")
            gw.db.transition(sid, states.VALIDATED, actor="runner", reason="ok", slug="gamma")
            await curator_login(client)
            r = await client.post(f"/gateway/curator/submission/{sid}/return",
                                  data={"note": "Please add a licence file and resubmit.",
                                        "csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert gw.db.get(sid).state == states.RETURNED
            # Public status page: shows the note, hides the submitter PII.
            public = await client.get(f"/gateway/status/{token}")
            assert public.status_code == 200
            assert "add a licence" in public.text
            assert PII_EMAIL not in public.text
            assert PII_NAME not in public.text
    run(_body())


def test_reject_records_actor_and_note(tmp_path):
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg)
            await curator_login(client)
            r = await client.post(f"/gateway/curator/submission/{sid}/reject",
                                  data={"note": "out of scope", "csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert gw.db.get(sid).state == states.REJECTED
            last = gw.db.transitions_for(sid)[-1]
            assert last["actor"] == f"curator:{CURATOR_NAME}"
    run(_body())


def test_empty_note_refused_every_action(tmp_path):
    # EVERY action requires a non-empty note (design §3 — no reject exemption, review #11). An empty
    # note on return OR reject => 400, no transition. Failure criterion: fails if either action
    # transitions on an empty note. proven failing 2026-07-06: the `action != "reject"` exemption let
    # a reject with an empty note through, so a submission could be REJECTED with no recorded reason.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            csrf = None
            for action in ("return", "reject"):
                sid = seed_validated(gw, cfg, slug=f"s-{action}")
                if csrf is None:
                    await curator_login(client)
                    csrf = csrf_for_session(client)
                r = await client.post(f"/gateway/curator/submission/{sid}/{action}",
                                      data={"note": "   ", "csrf_token": csrf},
                                      follow_redirects=False)
                assert r.status_code == 400, f"{action} accepted an empty note"
                assert gw.db.get(sid).state == states.VALIDATED
    run(_body())


def test_ack_checkbox_shown_for_generic_only_hit(tmp_path):
    # C11b §3: when the PII block is acknowledgeable (non-submitter address) and there are NO submitter
    # hits, the approve form shows the ack_pii checkbox with the confirmation label; the Approve button
    # is NOT hard-disabled. Failure criterion: fails if the checkbox/label is absent or the button is
    # disabled. proven failing against pre-C11b code: no ack_pii control existed and any blocking FAIL
    # disabled Approve.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email="submitter@example.org",
                                 foreign_email_in_preview="contact@records.test")
            await curator_login(client)
            page = await client.get(f"/gateway/curator/submission/{sid}")
            assert page.status_code == 200
            assert 'name="ack_pii"' in page.text
            assert "deliberate curator decision" in page.text
            # The matched address is never echoed, only the file name.
            assert "contact@records.test" not in page.text
            assert "index.html" in page.text
            # The Approve button is NOT hard-disabled for an acknowledgeable-only block. The approve
            # form's submit button must not carry `disabled`.
            approve_form = page.text.split('/approve">', 1)[1].split("</form>", 1)[0]
            assert "disabled" not in approve_form
    run(_body())


def test_no_ack_checkbox_and_disabled_for_submitter_hit(tmp_path):
    # C11b §0/§3: when the submitter's OWN email is present, NO ack checkbox is rendered, the detail
    # states the block is absolute, and the Approve button is hard-disabled. Failure criterion: fails
    # if an ack_pii control appears, or the absolute-block wording is missing, or Approve is enabled.
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email="owner@private.test", pii_in_preview=True)
            await curator_login(client)
            page = await client.get(f"/gateway/curator/submission/{sid}")
            assert page.status_code == 200
            assert 'name="ack_pii"' not in page.text  # no acknowledge path for submitter PII
            assert "absolute" in page.text.lower()
            approve_form = page.text.split('/approve">', 1)[1].split("</form>", 1)[0]
            assert "disabled" in approve_form
            # The submitter address itself is never echoed in the checklist detail.
            # (It DOES appear in the curator-only submitter block by design; scope to the checklist.)
            checklist = page.text.split("Checklist", 1)[1].split("Report bundle", 1)[0]
            assert "owner@private.test" not in checklist
    run(_body())


def test_hostile_pii_filename_renders_inert(tmp_path):
    # C11b §4.7: a hostile file name in the package (an XSS payload) is submitter-derived input and
    # must render INERT (escaped) in the detail page. Rendered at the page layer directly with a
    # crafted checklist because such a name (`<`, `>`) is not a legal file on Windows, yet IS a legal
    # zip member on the Linux gateway host — the escaping, not the filesystem, is the control under
    # test. Failure criterion: fails if the raw <img ...> markup appears unescaped in the rendered
    # detail HTML.
    from gateway import checklist as checklist_mod
    from gateway import curatorpage

    hostile = "<img src=x onerror=alert(1)>.edi"
    detail = (f"an email address is present in built artifact (mysurvey/{hostile}) — "
              "acknowledgeable: confirm each is part of the original submitted records")
    cl = checklist_mod.Checklist(
        checks=[checklist_mod.Check("pii", "No submitter PII in package", checklist_mod.FAIL,
                                    detail, blocking=True, acknowledgeable=True)],
        pii_generic_files=(f"mysurvey/{hostile}",))
    html_out = curatorpage.render_detail(
        submission_id="01ABCDEFGHIJKLMNOPQRSTUVWX", state=states.VALIDATED, updated_utc="now",
        submitter_name="N", submitter_email="submitter@example.org", submitter_orcid=None,
        validate_report={"items": []}, preview_summary=None, cl=cl, csrf_token="csrf",
        note="", has_preview=False)
    # The raw payload must NOT appear; its escaped form MUST (the file name is surfaced, inert).
    assert "<img src=x onerror=alert(1)>" not in html_out
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_out


def test_public_status_identical_for_ack_vs_nonack(tmp_path):
    # C11b §4.8: the PUBLIC status page output is byte-identical for an acknowledged vs a
    # non-acknowledged submission in the same state — acknowledgement is a CURATOR-only detail and must
    # not change the public page. Failure criterion: fails if the two public pages differ (beyond the
    # submission id / token, which we normalise out).
    async def _body():
        import hashlib

        from gateway import db as db_mod
        from gateway.tests.conftest import FakeGit, settle_publish
        git = FakeGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            await curator_login(client)

            async def _publish(slug, token, *, with_generic):
                sid = db_mod.new_id()
                gw.db.insert_submission(
                    submission_id=sid, zip_sha256="a" * 64, zip_bytes=10, submitter_name="N",
                    submitter_email="submitter@example.org", submitter_orcid=None,
                    token_hash=hashlib.sha256(token.encode()).hexdigest())
                gw.db.transition(sid, states.SCANNED, actor="gateway", reason="clean")
                gw.db.transition(sid, states.VALIDATED, actor="runner", reason="ok", slug=slug)
                pkg = cfg.quarantine_dir / sid / "package" / slug
                pkg.mkdir(parents=True, exist_ok=True)
                (pkg / "survey.yaml").write_text(f"survey:\n  slug: {slug}\n", encoding="utf-8")
                reports = cfg.quarantine_dir / sid / "reports"
                preview = reports / "preview-data"
                preview.mkdir(parents=True, exist_ok=True)
                (reports / "validate.json").write_text(
                    '{"items": [{"level": "PASS", "name": "structure", "message": "ok"}]}',
                    encoding="utf-8")
                index = "<!doctype html><title>preview</title><p>shell</p>"
                if with_generic:
                    index += "<!-- contact person@records.test -->"
                (preview / "index.html").write_text(index, encoding="utf-8")
                data = {"note": "publishing this survey", "csrf_token": csrf_for_session(client)}
                if with_generic:
                    data["ack_pii"] = "yes"
                r = await client.post(f"/gateway/curator/submission/{sid}/approve", data=data,
                                      follow_redirects=False)
                assert r.status_code == 303, r.text
                await settle_publish(gw, sid)
                assert gw.db.get(sid).state == states.PUBLISHED
                return sid

            await _publish("acksurvey", "tok-ack-page-1", with_generic=True)
            await _publish("plainsurvey", "tok-plain-page-2", with_generic=False)
            page_ack = (await client.get("/gateway/status/tok-ack-page-1")).text
            page_plain = (await client.get("/gateway/status/tok-plain-page-2")).text
            # Normalise the things that legitimately differ per submission (id shown as sid[:10], the
            # slug, and the per-transition updated timestamp) so we compare the STRUCTURE — an ack must
            # not add a PII-ACK marker or otherwise change the public page.
            import re

            def _norm(text, slug):
                text = re.sub(r"[0-9A-HJKMNP-TV-Z]{10,26}", "SID", text)
                text = re.sub(r"\d{4}-\d\d-\d\dT[\d:]+Z?", "TS", text)  # updated timestamp
                return text.replace(slug, "SLUG")

            norm_ack = _norm(page_ack, "acksurvey")
            norm_plain = _norm(page_plain, "plainsurvey")
            assert "PII-ACK" not in page_ack, "acknowledgement leaked onto the public status page"
            assert norm_ack == norm_plain, "public status page differs for ack vs non-ack submission"
    run(_body())


def test_publishing_window_hides_ack_details_from_public(tmp_path):
    # Review finding 2 (HIGH): the PII-ACK-prefixed reason lands on the VALIDATED->PUBLISHING
    # transition, and the public status page rendered the LAST transition reason for ANY state with a
    # truthy note — so during the real PUBLISHING window (git runs for seconds) the submitter-visible
    # page showed 'PII-ACK', the flagged file names, and the curator's private note. C11b §2:
    # acknowledgement details are curator-only; the public page must not change. Failure criterion:
    # fails if, while the submission is verifiably in PUBLISHING after an acknowledged approve, the
    # public page contains 'PII-ACK', a flagged file name, or the curator note.
    async def _body():
        git = _BlockingGit()
        note_text = "curator-private: historic contact line acknowledged"
        flagged = "mysurvey/tf/edi/HISTORIC01.edi"
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid = seed_validated(
                gw, cfg, email="submitter@example.org", token="tok-pubwin-1",
                package_files={flagged: ">INFO\n  EMAIL=old.contact@records.test\n>END\n"})
            await curator_login(client)
            r = await client.post(f"/gateway/curator/submission/{sid}/approve",
                                  data={"note": note_text, "ack_pii": "yes",
                                        "csrf_token": csrf_for_session(client)},
                                  follow_redirects=False)
            assert r.status_code == 303
            assert gw.db.get(sid).state == states.PUBLISHING
            public = await client.get("/gateway/status/tok-pubwin-1")
            assert public.status_code == 200
            # The window held for the whole fetch — git is blocked, so this cannot be flaky.
            assert gw.db.get(sid).state == states.PUBLISHING
            assert "PII-ACK" not in public.text, "acknowledgement marker leaked during PUBLISHING"
            assert "HISTORIC01" not in public.text, "flagged file name leaked during PUBLISHING"
            assert "curator-private" not in public.text, "curator note leaked during PUBLISHING"
            # The matched address never appears anywhere public either (no-echo, belt-and-braces).
            assert "old.contact@records.test" not in public.text
            git.release.set()
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED
    run(_body())


def test_public_page_identical_ack_vs_nonack_while_publishing(tmp_path):
    # Review finding 2, identity form (extends the terminal-state identity test to the PUBLISHING
    # window): the public page must be byte-identical (after normalising id/slug/timestamp) for an
    # acknowledged vs a non-acknowledged submission BOTH sitting in PUBLISHING. Deterministic: the
    # first publish is blocked inside its git call; the second waits on the global publish lock — so
    # both stay in PUBLISHING while the pages are fetched. Failure criterion: fails if the pages
    # differ or either page carries PII-ACK.
    async def _body():
        import re

        git = _BlockingGit()
        async with app_client(tmp_path, git_runner=git) as (client, _app, gw, cfg):
            sid_ack = seed_validated(gw, cfg, slug="ackwin", email="submitter@example.org",
                                     token="tok-win-ack",
                                     foreign_email_in_preview="contact@records.test")
            sid_plain = seed_validated(gw, cfg, slug="plainwin", email="submitter@example.org",
                                       token="tok-win-plain")
            await curator_login(client)
            r1 = await client.post(f"/gateway/curator/submission/{sid_ack}/approve",
                                   data={"note": "acknowledged the record contact", "ack_pii": "yes",
                                         "csrf_token": csrf_for_session(client)},
                                   follow_redirects=False)
            assert r1.status_code == 303
            r2 = await client.post(f"/gateway/curator/submission/{sid_plain}/approve",
                                   data={"note": "clean submission approved",
                                         "csrf_token": csrf_for_session(client)},
                                   follow_redirects=False)
            assert r2.status_code == 303
            page_ack = (await client.get("/gateway/status/tok-win-ack")).text
            page_plain = (await client.get("/gateway/status/tok-win-plain")).text
            # Both verifiably still in the PUBLISHING window (blocked git / queued on the lock).
            assert gw.db.get(sid_ack).state == states.PUBLISHING
            assert gw.db.get(sid_plain).state == states.PUBLISHING

            def _norm(text, slug):
                text = re.sub(r"[0-9A-HJKMNP-TV-Z]{10,26}", "SID", text)
                text = re.sub(r"\d{4}-\d\d-\d\dT[\d:]+Z?", "TS", text)
                return text.replace(slug, "SLUG")

            assert "PII-ACK" not in page_ack
            assert _norm(page_ack, "ackwin") == _norm(page_plain, "plainwin"), (
                "public PUBLISHING page differs for acknowledged vs non-acknowledged submission")
            git.release.set()
            await settle_publish(gw, sid_ack)
            await settle_publish(gw, sid_plain)
            assert gw.db.get(sid_ack).state == states.PUBLISHED
            assert gw.db.get(sid_plain).state == states.PUBLISHED
    run(_body())


def test_pii_absent_from_served_preview(tmp_path):
    # The submitter email must appear in the CURATOR detail HTML but NEVER in the served preview
    # output (design §8 PII bullet). Failure criterion: fails if the email fixture appears in ANY
    # served preview asset. (Here the fixture package's preview is PII-clean; the checklist test
    # covers the FAIL case where PII IS present.)
    async def _body():
        async with app_client(tmp_path) as (client, _app, gw, cfg):
            sid = seed_validated(gw, cfg, email=PII_EMAIL)
            await curator_login(client)
            detail = await client.get(f"/gateway/curator/submission/{sid}")
            assert PII_EMAIL in detail.text  # curator sees it
            served = await client.get(f"/gateway/curator/preview/{sid}/index.html")
            assert PII_EMAIL not in served.text  # the preview product does not carry it
    run(_body())
