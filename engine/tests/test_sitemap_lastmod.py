"""<lastmod> is a measurement, and the corpus checkout is the second thing that measures it.

A survey's release-note date is a real content-change signal, and almost no record carries one, so
the sitemap shipped a date on the homepage and on nothing else. The signal was missing rather than
withheld: the corpus IS a git repository, and the last commit that touched surveys/<slug>/ is exactly
as honest a statement about when that record last changed as a release note is.

  * A SURVEY takes the LATER of its release-note date and its directory's last commit date. Later,
    not either: a curated release note is a stronger statement than a typo fix, and a record whose
    note predates its last edit did change on the day of the edit.
  * A COLLECTION takes the maximum over its members, and the homepage and the two hubs the maximum
    over the corpus. Each of those pages is a view over what it rolls up, so it changes when any part
    of it does.
  * NONE OF IT IS A GUESS. A corpus that is not a git work tree, a directory with no commit of its
    own and a build with no --surveys root all yield nothing, and the URL carries no lastmod at all.
    A date a crawler learns to distrust costs the whole file its signal, so silence is the only
    honest answer where there is no measurement.

The static portal pages keep no lastmod: they ship with the portal image rather than being built
here, so this build knows nothing about when they last changed.
"""
import os
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

BASE = "https://ausmt.example.test/"
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
COLLECTION = ("collection:\n  id: auslamp\n  title: AusLAMP\n  type: programme\n"
              "  status: active\n  start_year: 2013\n")


def _member_pkg(base, slug, name, edi, collection_block="", extra=""):
    """A member survey package cloned from the vendored example fixture, the same scaffold
    tests/test_sitemap_pathurls.py builds its corpora from."""
    from _fixtures import EXAMPLE_SURVEY as ex
    y = (ex.joinpath("survey.yaml").read_text(encoding="utf-8")
         .replace("slug: example-survey", f"slug: {slug}")
         .replace('project_name: "Example MT Survey 2026"', f'project_name: "{name}"')
         .replace('name: "Example MT Survey 2026"', f'name: "{name}"'))
    if collection_block or extra:
        y = y.replace("country: Australia\n", "country: Australia\n" + collection_block + extra, 1)
    d = base / slug
    (d / "transfer_functions" / "edi").mkdir(parents=True)
    shutil.copy(edi, d / "transfer_functions" / "edi" / edi.name)
    (d / "survey.yaml").write_text(y, encoding="utf-8")


def _git(cwd, *args, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-c", "user.name=fixture", "-c", "user.email=fixture@example.test",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=str(cwd), check=True, capture_output=True, env=env)


def _build(tmp_path, out_name="out"):
    out = tmp_path / out_name
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(tmp_path / "surveys"), "--out", str(out),
                    "--no-validate", "--sitemap-base", BASE],
                   cwd=str(ROOT), check=True, capture_output=True)
    return out


def _lastmods(out):
    """{loc: lastmod or None} for every URL the sitemap advertises."""
    root = ET.fromstring((out / "sitemap.xml").read_text(encoding="utf-8"))
    got = {}
    for url in root.findall(f"{NS}url"):
        lm = url.find(f"{NS}lastmod")
        got[url.find(f"{NS}loc").text] = lm.text if lm is not None else None
    return got


def _corpus(tmp_path, when="2026-03-04T00:00:00+00:00"):
    """A two survey corpus in one collection, committed as a git work tree at `when`."""
    from _fixtures import example_edis
    edis = example_edis()
    assert len(edis) >= 2
    base = tmp_path / "surveys"
    _member_pkg(base, "sa-2017", "SA Campaign 2017", edis[0], COLLECTION)
    _member_pkg(base, "vic-2018", "Victoria 2018", edis[1], COLLECTION)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "corpus", date=when)
    return base


def test_two_builds_of_one_corpus_commit_emit_identical_sitemaps(tmp_path):
    """FAILS IF anything in the file moves without the corpus moving. A lastmod that changes on
    identical inputs is the signal a crawler learns to distrust, which costs every other date in the
    file its meaning."""
    pytest.importorskip("mt_metadata")
    _corpus(tmp_path)
    first = _build(tmp_path, "out-a")
    second = _build(tmp_path, "out-b")
    assert (first / "sitemap.xml").read_bytes() == (second / "sitemap.xml").read_bytes(), \
        "two builds of one corpus commit must emit the same sitemap byte for byte"


def test_the_corpus_commit_date_is_the_second_lastmod_source(tmp_path):
    """FAILS IF a survey URL carries no lastmod when its directory has a commit. The corpus is a git
    repository and almost no record carries a release note, so without this the file advertises one
    date on the homepage and none anywhere else."""
    pytest.importorskip("mt_metadata")
    _corpus(tmp_path, when="2026-03-04T00:00:00+00:00")
    got = _lastmods(_build(tmp_path))
    for loc in (f"{BASE}surveys/sa-2017", f"{BASE}surveys/vic-2018",
                f"{BASE}collections/auslamp", BASE, f"{BASE}surveys", f"{BASE}collections"):
        assert got.get(loc) == "2026-03-04", f"{loc} must carry the corpus commit date, got {got.get(loc)}"
    for page in ("about.html", "releases.html", "add-survey.html"):
        assert got.get(f"{BASE}{page}") is None, \
            f"{page} ships with the portal image; this build cannot date it"


def test_a_commit_moves_the_touched_survey_its_collection_and_the_roots_only(tmp_path):
    """FAILS IF an untouched survey's date moves with its neighbour's, or if the collection and the
    roots that roll it up do not move with it. A date that moves for a record that did not change is
    the same lie as a per-build timestamp, one URL at a time."""
    pytest.importorskip("mt_metadata")
    base = _corpus(tmp_path, when="2026-03-04T00:00:00+00:00")
    before = _lastmods(_build(tmp_path, "out-before"))
    (base / "sa-2017" / "NOTES.txt").write_text("touched\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "touch one survey", date="2026-07-19T00:00:00+00:00")
    after = _lastmods(_build(tmp_path, "out-after"))

    assert after[f"{BASE}surveys/sa-2017"] == "2026-07-19", \
        f"the touched survey must move to its new commit date, got {after[f'{BASE}surveys/sa-2017']}"
    assert after[f"{BASE}surveys/vic-2018"] == before[f"{BASE}surveys/vic-2018"] == "2026-03-04", \
        "an untouched survey must keep the date of the commit that last touched it"
    assert after[f"{BASE}collections/auslamp"] == "2026-07-19", \
        "a collection is a view over its members and moves when any member does"
    for loc in (BASE, f"{BASE}surveys", f"{BASE}collections"):
        assert after[loc] == "2026-07-19", f"{loc} rolls up the whole corpus and must move with it"
    moved = {loc for loc, lm in after.items() if before.get(loc) != lm}
    assert moved == {f"{BASE}surveys/sa-2017", f"{BASE}collections/auslamp", BASE,
                     f"{BASE}surveys", f"{BASE}collections"}, \
        f"exactly the touched survey, its collection and the three roots may move, got {moved}"


def test_a_release_note_later_than_the_commit_still_wins(tmp_path):
    """FAILS IF the commit date overwrites a later release note. The rule is the LATER of the two: a
    curated release note is a stronger statement than a directory's last edit, and taking the commit
    date alone would silently retire the one honest source the file already had."""
    pytest.importorskip("mt_metadata")
    from _fixtures import example_edis
    edis = example_edis()
    base = tmp_path / "surveys"
    _member_pkg(base, "sa-2017", "SA Campaign 2017", edis[0], COLLECTION,
                extra='release_notes:\n  - date: "2027-12-01"\n    note: "later than the commit"\n')
    _member_pkg(base, "vic-2018", "Victoria 2018", edis[1], COLLECTION)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "corpus", date="2026-03-04T00:00:00+00:00")
    got = _lastmods(_build(tmp_path))
    assert got[f"{BASE}surveys/sa-2017"] == "2027-12-01", \
        f"the later of the two dates wins, got {got[f'{BASE}surveys/sa-2017']}"
    assert got[f"{BASE}surveys/vic-2018"] == "2026-03-04", \
        "a survey with no release note takes its directory's commit date"
    assert got[BASE] == "2027-12-01", "the homepage takes the maximum over the corpus"


def test_a_corpus_that_is_not_a_git_work_tree_carries_no_invented_date(tmp_path):
    """FAILS IF a build outside a repository invents a date. A plain directory copy and a partial
    checkout are both legitimate inputs, and a lastmod they cannot support must simply not be
    written."""
    pytest.importorskip("mt_metadata")
    from _fixtures import example_edis
    base = tmp_path / "surveys"
    _member_pkg(base, "sa-2017", "SA Campaign 2017", example_edis()[0], COLLECTION)
    got = _lastmods(_build(tmp_path))
    assert got[f"{BASE}surveys/sa-2017"] is None, \
        f"no commit, no date, got {got[f'{BASE}surveys/sa-2017']}"
    assert got[BASE] is None and got[f"{BASE}collections/auslamp"] is None, \
        "a roll up over nothing is nothing"


def test_every_lastmod_is_an_iso_date_and_nothing_finer(tmp_path):
    """FAILS IF a lastmod grows a time or a zone. A day is the precision both sources measure at,
    and a fabricated time on a real date is still a fabrication."""
    pytest.importorskip("mt_metadata")
    _corpus(tmp_path)
    for loc, lm in _lastmods(_build(tmp_path)).items():
        if lm is not None:
            assert len(lm) == 10 and lm[4] == "-" and lm[7] == "-" and lm.replace("-", "").isdigit(), \
                f"{loc}: lastmod must be an ISO date, got {lm!r}"
