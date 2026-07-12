"""C43 Stage-3a collections console — page/route pins (record D5-A / D13, Invariant 10).

Drive the two READ-ONLY routes through the in-process app (httpx ASGITransport) with the in-process
edit seam (inproc_edit_runner — the runner's real job dispatch, no file queue, no yaml in the gateway
process). Pins: the CSP sweep on both new surfaces, the nav rail (Collections present + active), the
unknown-id 404, the empty-corpus empty state, that NO POST route exists on /collections*, and that the
index/detail render their information-design surfaces (cards / bands / member-Declares table).
"""
from __future__ import annotations

import re

from gateway.tests.conftest import app_client, curator_login, inproc_edit_runner, run


def _write_collection_survey(surveys_live, slug: str, *, name: str, collection: str | None,
                             n_edi: int = 1) -> None:
    d = surveys_live / "surveys" / slug
    (d / "transfer_functions" / "edi").mkdir(parents=True, exist_ok=True)
    for i in range(n_edi):
        (d / "transfer_functions" / "edi" / f"S{i:02d}.edi").write_text(">HEAD\n>END\n", encoding="utf-8")
    body = f"slug: {slug}\nname: \"{name}\"\nversion: 1.0.0\ncountry: Australia\n"
    if collection:
        body += collection
    with open(d / "survey.yaml", "w", encoding="utf-8", newline="") as fh:
        fh.write(body)


def _seed_corpus(surveys_live) -> None:
    """A corpus that exercises both honesty seams: an auslamp with a title+status divergence, a clean
    capricorn, and a case-colliding 'AusLAMP' near-duplicate."""
    _write_collection_survey(
        surveys_live, "auslamp-sa-gawler-2014", name="AusLAMP SA Gawler",
        collection="collection:\n  id: auslamp\n  title: AusLAMP\n  type: programme\n"
                   "  status: active\n  start_year: 2003\n  last_updated: 2026-06-15\n"
                   "  description: Australian Lithospheric Architecture MT Project.\n", n_edi=54)
    _write_collection_survey(
        surveys_live, "auslamp-sa-ne-2014", name="AusLAMP SA NE",
        collection="collection:\n  id: auslamp\n  title: AusLAMP Project\n  status: completed\n",
        n_edi=87)
    _write_collection_survey(
        surveys_live, "capricorn-2010", name="Capricorn 2010",
        collection="collection:\n  id: capricorn\n  title: Capricorn\n  type: programme\n"
                   "  status: completed\n", n_edi=147)
    _write_collection_survey(
        surveys_live, "vulcan-2022", name="Vulcan 2022",
        collection="collection:\n  id: AusLAMP\n  title: AusLAMP\n  type: programme\n"
                   "  status: active\n", n_edi=12)


def _assert_csp_clean(html: str) -> None:
    """Record D13 CSP sweep: every <script> carries src= (inline blocks are dead under script-src
    'self'), NO on*= handler attributes, and the shared ui.js loads. Mirrors
    test_serve_reconcile.test_queue_page_is_pure_queue_and_csp_clean."""
    for m in re.finditer(r"<script\b[^>]*>", html):
        assert re.search(r"\bsrc\s*=", m.group(0)), f"inline <script> is dead under the CSP: {m.group(0)}"
    handlers = re.findall(r"<[^>]*\son\w+\s*=", html)
    assert handlers == [], f"inline event handlers are dead under the CSP: {handlers}"
    assert 'src="/gateway/curator/ui.js"' in html


# --------------------------------------------------------------------------------------------------
# Pin 7 — CSP sweep on BOTH new routes. FAILS IF /collections or /collections/{id} ships any inline
# script or on*= handler (3a must be zero-JS, server-rendered).
# --------------------------------------------------------------------------------------------------
def test_collections_index_and_detail_are_csp_clean(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_corpus(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            idx = await client.get("/gateway/curator/collections")
            assert idx.status_code == 200
            _assert_csp_clean(idx.text)
            det = await client.get("/gateway/curator/collections/auslamp")
            assert det.status_code == 200
            _assert_csp_clean(det.text)
    run(_body())


# --------------------------------------------------------------------------------------------------
# Pin 8 — NAV. Collections appears in the rail (under the Surveys group) and is the ACTIVE item on
# both routes. FAILS IF the rail omits Collections or the active highlight is wrong.
# --------------------------------------------------------------------------------------------------
def test_nav_rail_has_collections_active_on_both_routes(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_corpus(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            for path in ("/gateway/curator/collections", "/gateway/curator/collections/auslamp"):
                r = await client.get(path)
                assert r.status_code == 200, path
                # The rail link exists and is marked active (class="railitem on").
                assert re.search(
                    r'<a class="railitem on" href="/gateway/curator/collections">Collections</a>',
                    r.text), f"Collections not the active rail item on {path}:\n{r.text[:400]}"
            # On an UNRELATED page the Collections rail link is present but NOT active.
            q = await client.get("/gateway/curator/queue")
            assert '<a class="railitem" href="/gateway/curator/collections">Collections</a>' in q.text
    run(_body())


# --------------------------------------------------------------------------------------------------
# Pin 9 — UNKNOWN ID -> 404. FAILS IF a bogus collection id crashes or renders a page.
# --------------------------------------------------------------------------------------------------
def test_unknown_collection_id_is_404(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_corpus(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            r = await client.get("/gateway/curator/collections/no-such-collection")
            assert r.status_code == 404, r.status_code
    run(_body())


# --------------------------------------------------------------------------------------------------
# Pin 10 — EMPTY CORPUS. A corpus with no collection blocks renders the clean 'No collections yet'
# state (matches the engine's collections.json == {}), not an error. FAILS IF it 500s or shows a band.
# --------------------------------------------------------------------------------------------------
def test_empty_corpus_renders_empty_state(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _write_collection_survey(surveys_live, "lone-2019", name="Lone Survey", collection=None, n_edi=3)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            r = await client.get("/gateway/curator/collections")
            assert r.status_code == 200
            assert "No collections yet" in r.text
            assert "Near-duplicate ids" not in r.text
            _assert_csp_clean(r.text)
    run(_body())


# --------------------------------------------------------------------------------------------------
# READ-ONLY — no POST route exists on /collections* in 3a (a POST -> 405 Method Not Allowed, which
# only happens when the PATH is registered for GET but not POST). FAILS IF a write route leaks in.
# --------------------------------------------------------------------------------------------------
def test_no_post_route_on_collections(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_corpus(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            for path in ("/gateway/curator/collections", "/gateway/curator/collections/auslamp"):
                r = await client.post(path, data={"x": "1"})
                assert r.status_code == 405, (path, r.status_code)
    run(_body())


# --------------------------------------------------------------------------------------------------
# Index information design: summary cards, BOTH inconsistency bands, the list table with the status
# chip + 'mixed' marker. FAILS IF a described surface is missing.
# --------------------------------------------------------------------------------------------------
def test_index_renders_cards_bands_and_table(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_corpus(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            html = (await client.get("/gateway/curator/collections")).text
            # Summary cards.
            for label in ("Collections", "Member surveys", "Stations rolled up", "Need attention"):
                assert label in html, label
            # Both bands.
            assert "Near-duplicate ids" in html            # id collision (auslamp / AusLAMP)
            assert "Members disagree within" in html        # per-field divergence (auslamp title+status)
            assert "AusLAMP Project" in html                # the divergent title value is named
            # List table: rows link to the detail route; the divergent collection is flagged 'mixed'.
            assert 'href="/gateway/curator/collections/auslamp"' in html
            assert "&middot; mixed" in html or "· mixed" in html
            # Membership-by-slug honesty line.
            assert "resolved by survey <b>slug</b>" in html
            # READ-ONLY: no 'New collection…' creation control in 3a (creation is Stage 3b).
            assert "New collection" not in html
    run(_body())


# --------------------------------------------------------------------------------------------------
# Detail information design: rollup facts, the member/Declares table naming outliers, the per-field
# callout, and the read-only next-stage note. NO form inputs / NO submit controls (read-only). FAILS
# IF a form input or the outlier marker is missing/leaked.
# --------------------------------------------------------------------------------------------------
def test_detail_renders_rollup_declares_and_is_read_only(tmp_path):
    surveys_live = tmp_path / "surveys-live"
    _seed_corpus(surveys_live)

    async def _body():
        async with app_client(tmp_path, edit_runner=inproc_edit_runner(surveys_live)) as (client, *_):
            await curator_login(client)
            html = (await client.get("/gateway/curator/collections/auslamp")).text
            assert "Rollup facts" in html
            assert "Declares" in html
            # The divergent member (auslamp-sa-ne-2014 declares a different title + status) is marked;
            # the first-declarer member is 'consistent'.
            assert "auslamp-sa-ne-2014" in html
            assert "badge-move" in html          # at least one ◆ outlier badge
            assert "consistent" in html
            # Read-only: the ONLY form in the page is the shared context-bar Request-rebuild chrome
            # (action=/rebuild). NO collections-targeted form, NO edit widgets (textarea/select/
            # checkbox), NO membership 'add'/'remove'/'save'/'preview' controls — those are Stage 3b.
            assert 'action="/gateway/curator/collections' not in html, "detail leaked a collections POST form"
            for widget in ("<textarea", "<select", 'type="checkbox"'):
                assert widget not in html, f"read-only detail leaked an edit widget: {widget}"
            forms = re.findall(r'<form\b[^>]*action="([^"]*)"', html)
            assert forms == ["/gateway/curator/rebuild"], \
                f"the only form must be the rebuild chrome; found {forms}"
            assert "Read-only." in html
    run(_body())
