"""The data-level labels a reader sees, pinned across the three places that print them.

The portal names a level in its Data available chooser (portal/index.html #availSel), in its
Download rows and drawer action rows (portal/src/state.js TS_LEVELS), and the engine names the same
level on every survey, station and collection page (engine/extract/_pages.py _TS_LEVELS). Each of
the three is a literal table, so nothing but a pin keeps them reading alike: a label edited in one
would leave the map's chooser and the survey page a reader just came from naming one level two ways.

The labels follow one bracket scheme: the level, then what it is ("Level 0 (Edited Time Series)").
The chooser offers three time-series levels and Level 2, which is a catalogue predicate rather than
a route. level1_netcdf is in none of the portal's controls, yet the route table can still carry it,
so the engine still names it on a page whose register does, in the same scheme.

WHY THIS LIVES IN THE PORTAL SUITE: portal-ci runs on portal/** and on engine/extract/_pages.py, so a
change to either side fires it; the engine workflow cannot see a state.js or index.html edit.

Skips the state.js half if Node is unavailable (CI installs Node; see .github/workflows/portal-ci.yml).
"""
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from engine_chrome import namespace

PORTAL = Path(__file__).resolve().parent.parent
STATE_JS = PORTAL / "src" / "state.js"
INDEX = PORTAL / "index.html"

# The labels themselves, as literals, so no side is checked against its own copy.
TS_LABELS = [("raw_packed", "Packed raw time series"),
             ("level0", "Level 0 (Edited Time Series)"),
             ("level1_mth5", "Level 1 MTH5 (Transformed Time Series)")]
LEVEL2 = ("level2", "Level 2 (Transfer Functions)")
NETCDF = ("level1_netcdf", "Level 1 NetCDF (Transformed Time Series)")


class _Options(HTMLParser):
    """(value, text) for every <option> inside the <select id="availSel">."""

    def __init__(self):
        super().__init__()
        self.inside, self.current, self.options = False, None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "select" and a.get("id") == "availSel":
            self.inside = True
        elif tag == "option" and self.inside:
            self.current = [a.get("value"), ""]

    def handle_endtag(self, tag):
        if tag == "option" and self.current is not None:
            self.options.append((self.current[0], self.current[1].strip()))
            self.current = None
        elif tag == "select":
            self.inside = False

    def handle_data(self, data):
        if self.current is not None:
            self.current[1] += data


def _avail_options():
    p = _Options()
    p.feed(INDEX.read_text(encoding="utf-8"))
    assert p.options, "index.html must carry the #availSel chooser"
    return p.options


def _state_tables():
    """state.js TS_LEVELS and TS_ROUTE_LEVELS as the browser sees them: the file is RUN, not parsed."""
    driver = ("const fs=require('fs'),vm=require('vm');const ctx={window:{}};ctx.globalThis=ctx;"
              "vm.createContext(ctx);"
              f"vm.runInContext(fs.readFileSync({json.dumps(str(STATE_JS))},'utf8')+"
              "';globalThis.__t={levels:TS_LEVELS,routes:TS_ROUTE_LEVELS};',ctx);"
              "process.stdout.write(JSON.stringify(ctx.__t));")
    r = subprocess.run(["node", "-e", driver], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"state.js did not execute:\n{r.stderr}"
    return json.loads(r.stdout)


def test_the_chooser_offers_the_three_time_series_levels_and_level_2_by_their_bracket_labels():
    """FAILS IF the chooser loses a level, offers NetCDF again, reorders the levels, or prints a label
    outside the bracket scheme."""
    assert _avail_options() == [("", "Any")] + TS_LABELS + [LEVEL2]


def test_the_chooser_carries_no_field_note():
    """FAILS IF a note returns under the Data available chooser: the option labels carry the levels,
    and the filter's semantics live in the documentation, not under the control."""
    html = INDEX.read_text(encoding="utf-8")
    start = html.index('<select id="availSel"')
    after = html[html.index("</select>", start):html.index("</details>", start)]
    assert "fieldnote" not in after and "keeps the stations" not in html, after


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_state_js_names_each_offered_level_as_the_chooser_does():
    """FAILS IF the Download rows or the drawer action rows (both read TS_LEVELS) name a level
    differently from the chooser, or if TS_LEVELS offers level1_netcdf, which the route list keeps."""
    t = _state_tables()
    assert [(tok, label) for tok, label, _gloss in t["levels"]] == TS_LABELS
    assert all(gloss for _tok, _label, gloss in t["levels"]), "every offered level keeps its gloss"
    assert t["routes"] == [tok for tok, _label in TS_LABELS] + [NETCDF[0]], \
        "the route list is the offered levels plus the one no control offers"


def test_the_engine_pages_name_every_level_in_the_same_scheme():
    """FAILS IF a survey, station or collection page names an offered level differently from the
    portal, or names a routed NetCDF file outside the scheme the other levels use."""
    table = namespace()["_TS_LEVELS"]
    assert [(tok, name) for tok, _badge, name in table] == TS_LABELS + [NETCDF]


DRAWER_JS = PORTAL / "src" / "drawer.js"
# Level 1 as a whole (the Files tab heading and the survey slot cover every Level 1 format) and
# Level 3, which no chooser offers, in the same bracket scheme.
LEVEL1 = "Level 1 (Transformed Time Series)"
LEVEL3 = "Level 3 (Models)"


def _drawer_files_headings():
    """The Files tab's level headings: each time-series level row's label, then the Level 2 group."""
    src = DRAWER_JS.read_text(encoding="utf-8")
    rows = re.findall(r'tsLevelRow\("([^"]+)","[^"]*","(\w+)"\)', src)
    group = re.search(r'<div class="fl-ghead">([^<]+?)\s*<small>', src)
    assert rows and group, "drawer.js must keep its Files tab level rows and its Level 2 group heading"
    return [(vocab, label) for label, vocab in rows] + [("level2", group.group(1))]


def _drawer_level_slots():
    """drawer.js DATA_LEVEL_SLOTS as (identifies key, tile name), read from its array literal."""
    src = DRAWER_JS.read_text(encoding="utf-8")
    m = re.search(r"const DATA_LEVEL_SLOTS=(\[.*?\]);", src, re.S)
    assert m, "drawer.js must keep DATA_LEVEL_SLOTS"
    return [(key, name) for key, name, _desc in json.loads(re.sub(r",\s*\]$", "]", m.group(1)))]


def test_the_files_tab_headings_use_the_level_vocabulary():
    """FAILS IF a station's Files tab heads a level in words other than the chooser's: the packed raw
    and Level 0 labels as the chooser prints them, Level 1 in the same bracket scheme, Level 2 as
    the chooser's Level 2."""
    labels = dict(TS_LABELS)
    assert _drawer_files_headings() == [("raw_packed", labels["raw_packed"]),
                                        ("level0", labels["level0"]),
                                        ("level1", LEVEL1),
                                        LEVEL2]


def test_the_survey_level_table_uses_the_level_vocabulary():
    """FAILS IF the survey drawer's data-at-every-level table names a level in words other than the
    chooser's, or loses the bracket scheme for Level 1 and Level 3."""
    labels = dict(TS_LABELS)
    assert _drawer_level_slots() == [("collection", "Collection"),
                                     ("raw_packed", labels["raw_packed"]),
                                     ("level0", labels["level0"]),
                                     ("level1", LEVEL1),
                                     LEVEL2,
                                     ("level3", LEVEL3)]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_the_files_tab_glosses_are_the_choosers_glosses():
    """FAILS IF a station's Files tab describes a level in words other than TS_LEVELS gives it, so the
    Files tab and the Download rows gloss one level two ways. Level 1 as a whole takes the gloss of
    level1_mth5, the one Level 1 format offered."""
    src = DRAWER_JS.read_text(encoding="utf-8")
    drawer = {vocab: gloss for gloss, vocab in
              re.findall(r'tsLevelRow\("[^"]+","([^"]*)","(\w+)"\)', src)}
    glosses = {tok: gloss for tok, _label, gloss in _state_tables()["levels"]}
    assert drawer == {"raw_packed": glosses["raw_packed"],
                      "level0": glosses["level0"],
                      "level1": glosses["level1_mth5"]}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_the_survey_level_table_glosses_packed_raw_as_the_chooser_does():
    """FAILS IF the survey drawer's data-at-every-level table describes packed raw time series in
    words other than TS_LEVELS gives it."""
    src = DRAWER_JS.read_text(encoding="utf-8")
    m = re.search(r"const DATA_LEVEL_SLOTS=(\[.*?\]);", src, re.S)
    assert m, "drawer.js must keep DATA_LEVEL_SLOTS"
    slots = {key: desc for key, _name, desc in json.loads(re.sub(r",\s*\]$", "]", m.group(1)))}
    glosses = {tok: gloss for tok, _label, gloss in _state_tables()["levels"]}
    assert slots["raw_packed"] == glosses["raw_packed"]
