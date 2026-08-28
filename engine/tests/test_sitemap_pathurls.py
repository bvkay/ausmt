"""Path-URL contract (owner ruling 2026-08-18): the sitemap advertises the contract, and
collections join it.

/surveys/<slug>, /stations/<ausmt_id> and /collections/<id> are the PUBLISHED URL contract; the
front door 301s each shape into the SPA's hash route (tier 1, deploy/frontdoor/Caddyfile). The
sitemap is where the contract is ADVERTISED, so it must emit the path form and nothing else:

  * per-survey URLs are <base>/surveys/<slug>, carrying the AUTHORITATIVE slug (the survey.yaml
    slug the build stamps into smeta and every ausmt_id), never a re-slugified display label: a
    declared slug that differs from slugify(label) would otherwise advertise a URL the portal
    cannot resolve;
  * station URLs are DELIBERATELY ABSENT: the station pages exist (the served URL contract)
    but are unadvertised and noindexed, so the sitemap cannot dilute the survey and collection
    pages that carry the ranking;
  * per-collection URLs are ADDED as <base>/collections/<id> (the sitemap previously emitted no
    collection links at all);
  * the hash-fragment forms leave the sitemap entirely: the path form is the published contract,
    and crawlers ignore fragments anyway;
  * the Atom feed entry <link> moves to the same path form.

FAILS PRE-CHANGE: the sitemap emitted <base>#/survey/<slugified-label> + <base>#/station/<id>
fragment URLs, no collection URLs, and the feed linked <base>#/survey/<slug>.
"""
import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from extract import build_portal as bp   # noqa: E402

ATOM_NS = "{http://www.w3.org/2005/Atom}"
BASE = "https://ausmt.example.test/"


def _member_pkg(base, slug, name, edi, collection_block, extra=""):
    """A member survey package cloned from the vendored example fixture (the same scaffold
    test_collections.py uses), with a declared slug and optional collection block."""
    from _fixtures import EXAMPLE_SURVEY as ex
    y = ex.joinpath("survey.yaml").read_text(encoding="utf-8")
    y = (y.replace("slug: example-survey", f"slug: {slug}")
           .replace('project_name: "Example MT Survey 2026"', f'project_name: "{name}"')
           .replace('name: "Example MT Survey 2026"', f'name: "{name}"'))
    if collection_block:
        y = y.replace("country: Australia\n", "country: Australia\n" + collection_block, 1)
    if extra:
        y = y.replace("country: Australia\n", "country: Australia\n" + extra, 1)
    d = base / slug
    (d / "transfer_functions" / "edi").mkdir(parents=True)
    shutil.copy(edi, d / "transfer_functions" / "edi" / edi.name)
    (d / "survey.yaml").write_text(y)


def _build(tmp_path, *, sitemap_base=BASE):
    out = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(tmp_path / "surveys"), "--out", str(out),
                    "--no-validate", "--sitemap-base", sitemap_base],
                   cwd=str(ROOT), check=True, capture_output=True)
    return out


def _locs(out) -> list[str]:
    root = ET.fromstring((out / "sitemap.xml").read_text(encoding="utf-8"))
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    return [u.find(f"{ns}loc").text for u in root.findall(f"{ns}url")]


def test_sitemap_advertises_surveys_and_collections_never_stations(tmp_path):
    """E2E over the CLI: the sitemap carries the base, <base>surveys/<slug> per survey,
    and <base>collections/<id> per collection, NO station URLs at all, and carries
    NO fragment URL at all. FAILS PRE-CHANGE (fragment forms, no collections)."""
    pytest.importorskip("mt_metadata")
    from _fixtures import example_edis
    edis = example_edis()
    assert len(edis) >= 2
    cblock = ("collection:\n  id: auslamp\n  title: AusLAMP\n  type: programme\n"
              "  status: active\n  start_year: 2013\n")
    base = tmp_path / "surveys"
    _member_pkg(base, "sa-2017", "SA Campaign 2017", edis[0], cblock)
    _member_pkg(base, "vic-2018", "Victoria 2018", edis[1], cblock)
    out = _build(tmp_path)

    locs = _locs(out)
    assert BASE in locs, "the base URL must stay in the sitemap"
    assert f"{BASE}surveys/sa-2017" in locs and f"{BASE}surveys/vic-2018" in locs, (
        f"per-survey path URLs missing: {locs}")
    assert f"{BASE}collections/auslamp" in locs, (
        f"the collection must join the sitemap as a path URL: {locs}")
    mt = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    station_ids = [s["station_id"] for s in mt["stations"]]
    assert station_ids, "fixture build must produce stations"
    assert not any("/stations/" in u for u in locs), (
        f"station URLs must stay OUT of the sitemap (unadvertised-but-served posture): {locs}")
    assert not any("#/" in u for u in locs), (
        f"the hash-fragment forms must leave the sitemap (the path form is the contract): {locs}")
    # One URL per entity + the base, nothing else silently added.
    assert len(locs) == 1 + 2 + 1, locs
    # The emitted file's own comment describes tier 1 honestly (redirects into the SPA, prerender
    # still needed for real per-page indexing), not the retired fragment story.
    xml_text = (out / "sitemap.xml").read_text(encoding="utf-8")
    assert "path-URL contract" in xml_text, "the sitemap's comment must describe the contract"
    assert "#/station/" not in xml_text, "no fragment residue anywhere in the file"


def test_sitemap_uses_the_authoritative_slug_never_a_relabelled_one(tmp_path):
    """The per-survey URL carries the survey.yaml slug the build stamps everywhere else (smeta,
    ausmt_id, product paths). A DECLARED slug that differs from slugify(display name) must win.
    FAILS PRE-CHANGE: the sitemap re-slugified the display label, advertising /#/survey/<label-ish>
    while the router resolves smeta slugs."""
    pytest.importorskip("mt_metadata")
    from _fixtures import example_edis
    edis = example_edis()
    base = tmp_path / "surveys"
    _member_pkg(base, "vulcan-2022", "Vulcan MT Array (2022 Release)", edis[0], "")
    out = _build(tmp_path)
    locs = _locs(out)
    assert f"{BASE}surveys/vulcan-2022" in locs, (
        f"the declared slug must be the advertised id: {locs}")
    assert not any("vulcan-mt-array" in u for u in locs), (
        f"a re-slugified display label must never be advertised: {locs}")


def test_feed_entry_links_use_the_path_form():
    """The Atom feed's entry <link> is the published contract too: <base>surveys/<slug>, no
    fragment. FAILS PRE-CHANGE (base + '#/survey/<slug>')."""
    smeta = {"S": {"slug": "vulcan-2022", "release_notes": [{"date": "2022-03-15"}]}}
    xml_text = bp.build_feed_xml(smeta, base_url=BASE)
    root = ET.fromstring(xml_text)
    link = root.find(f"{ATOM_NS}entry").find(f"{ATOM_NS}link").get("href")
    assert link == f"{BASE}surveys/vulcan-2022", link
    assert "#/" not in xml_text, "no fragment URL may remain in the feed"
