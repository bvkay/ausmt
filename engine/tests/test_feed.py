"""S3: feed.xml -- a minimal Atom feed of surveys sorted by their latest release date (fallback:
dates end/start year), for a modeller to watch "what's new" without polling the whole portal.

FAILS IF (pre-fix): build_portal has no feed_entries()/build_feed_xml() at all (AttributeError);
feed.xml is not well-formed XML; entries are not sorted newest-first; a survey with zero declared
dates gets a fabricated date instead of being omitted; an empty build (no surveys) still emits a
feed.xml file (a "feed" with no dated content is not a meaningful product -- see the CONTRACT)."""
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
from _fixtures import FIXTURES           # noqa: E402

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def test_feed_entries_sorted_newest_first():
    """FAILS IF (pre-fix): feed_entries doesn't exist, or doesn't sort newest-first."""
    smeta = {
        "Old Survey": {"slug": "old", "release_notes": [{"version": "1.0.0", "date": "2019-01-01", "note": "x"}]},
        "New Survey": {"slug": "new", "release_notes": [{"version": "1.0.0", "date": "2023-05-10", "note": "x"}]},
        "Mid Survey": {"slug": "mid", "year_end": 2021},   # no release_notes -> falls back to year_end
    }
    entries = bp.feed_entries(smeta)
    assert [e["survey"] for e in entries] == ["New Survey", "Mid Survey", "Old Survey"], entries
    assert entries[0]["date"] == "2023-05-10"
    assert entries[1]["date"] == "2021-12-31"          # year-only fallback -> Dec 31


def test_feed_entries_uses_latest_release_note_not_first():
    """FAILS IF: picks the FIRST release_notes entry instead of the latest date among them."""
    smeta = {"S": {"slug": "s", "release_notes": [
        {"version": "1.0.0", "date": "2020-01-01", "note": "first"},
        {"version": "1.1.0", "date": "2022-06-01", "note": "second"},
    ]}}
    entries = bp.feed_entries(smeta)
    assert entries[0]["date"] == "2022-06-01"


def test_feed_entries_omits_surveys_with_no_date():
    """FAILS IF: an undated survey is included (e.g. with a fabricated/blank date) rather than omitted."""
    smeta = {"Dated": {"slug": "dated", "year_end": 2020}, "Undated": {"slug": "undated"}}
    entries = bp.feed_entries(smeta)
    assert [e["survey"] for e in entries] == ["Dated"]


def test_feed_entries_omits_surveys_with_no_slug():
    """A survey missing its authoritative slug can't form a #/survey/<slug> link; omit rather than crash."""
    smeta = {"NoSlug": {"year_end": 2020}}
    assert bp.feed_entries(smeta) == []


def test_build_feed_xml_none_when_no_dated_survey():
    """FAILS IF: an empty (or all-undated) survey set still produces a feed.xml file."""
    assert bp.build_feed_xml({}) is None
    assert bp.build_feed_xml({"X": {"slug": "x"}}) is None


def test_build_feed_xml_well_formed_and_sorted():
    """FAILS IF: the emitted text is not well-formed XML, or entries are out of order."""
    smeta = {
        "Old Survey": {"slug": "old", "release_notes": [{"date": "2019-01-01"}]},
        "New Survey": {"slug": "new", "release_notes": [{"date": "2023-05-10"}]},
    }
    xml_text = bp.build_feed_xml(smeta, base_url="https://org.github.io/ausmt/")
    root = ET.fromstring(xml_text)                      # raises ParseError if malformed
    assert root.tag == f"{ATOM_NS}feed"
    titles = [e.find(f"{ATOM_NS}title").text for e in root.findall(f"{ATOM_NS}entry")]
    assert titles == ["New Survey", "Old Survey"]
    ids = [e.find(f"{ATOM_NS}id").text for e in root.findall(f"{ATOM_NS}entry")]
    assert ids == ["tag:ausmt:new", "tag:ausmt:old"]
    links = [e.find(f"{ATOM_NS}link").get("href") for e in root.findall(f"{ATOM_NS}entry")]
    assert links == ["https://org.github.io/ausmt/#/survey/new", "https://org.github.io/ausmt/#/survey/old"]
    feed_updated = root.find(f"{ATOM_NS}updated").text
    assert feed_updated == "2023-05-10T00:00:00Z"        # max entry date, NOT wall-clock time


def test_build_feed_xml_omits_link_when_no_base_url():
    """The feed is still valid Atom without a base URL -- entries just carry no <link>."""
    smeta = {"S": {"slug": "s", "release_notes": [{"date": "2020-01-01"}]}}
    xml_text = bp.build_feed_xml(smeta)                  # no base_url
    root = ET.fromstring(xml_text)
    entry = root.find(f"{ATOM_NS}entry")
    assert entry.find(f"{ATOM_NS}link") is None


def test_build_feed_xml_deterministic():
    """Two builds of the same input must be byte-identical (no wall-clock timestamp leaks in)."""
    smeta = {"S": {"slug": "s", "release_notes": [{"date": "2020-01-01"}]}}
    assert bp.build_feed_xml(smeta) == bp.build_feed_xml(smeta)


def test_pid_survey_fixture_feed_entry():
    """Integration with the real pid-survey fixture: latest release_notes date wins over dates.end."""
    yaml = pytest.importorskip("yaml")
    text = (FIXTURES / "pid-survey" / "survey.yaml").read_text(encoding="utf-8")
    sm = bp.survey_meta_from_yaml(yaml.safe_load(text) or {})
    sm["slug"] = "pid-survey"
    entries = bp.feed_entries({"PID Chain Survey 2026": sm})
    assert len(entries) == 1
    assert entries[0]["date"] == "2022-03-15"            # latest release_notes date, not dates.end (2021)


@pytest.mark.skipif(bp is None, reason="unreachable guard")
def test_build_portal_cli_emits_feed_for_dated_surveys(tmp_path):
    """End-to-end: the CLI writes <out>/feed.xml when a survey package has dates, and OMITS it for an
    empty build. Uses the same example-survey fixture as test_empty_build.py / test_collections.py."""
    pytest.importorskip("mt_metadata")
    from _fixtures import EXAMPLE_SURVEY, example_edis
    edis = example_edis()
    assert edis

    base = tmp_path / "surveys" / "example-survey"
    (base / "transfer_functions" / "edi").mkdir(parents=True)
    import shutil
    shutil.copy(edis[0], base / "transfer_functions" / "edi" / edis[0].name)
    y = (EXAMPLE_SURVEY / "survey.yaml").read_text(encoding="utf-8")
    y = y.replace("country: Australia\n", "country: Australia\ndates: { start: 2024, end: 2025 }\n", 1)
    (base / "survey.yaml").write_text(y)

    out = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(tmp_path / "surveys"), "--out", str(out), "--no-validate"],
                   cwd=str(ROOT), check=True, capture_output=True)
    feed_path = out / "feed.xml"
    assert feed_path.exists()
    root = ET.fromstring(feed_path.read_text(encoding="utf-8"))
    assert root.tag == f"{ATOM_NS}feed"
    assert len(root.findall(f"{ATOM_NS}entry")) == 1

    # empty build: no surveys -> no feed.xml at all
    empty_surveys = tmp_path / "empty_surveys"
    empty_surveys.mkdir()
    empty_out = tmp_path / "empty_out"
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(empty_surveys), "--out", str(empty_out),
                    "--allow-empty", "--no-validate"],
                   cwd=str(ROOT), check=True, capture_output=True)
    assert not (empty_out / "feed.xml").exists()
