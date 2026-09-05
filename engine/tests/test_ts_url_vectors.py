"""The percent-encoding of a hand-off route, pinned against the SHARED vector file.

Three surfaces render an NCI fileServer address from one register `url_path`, and only one of them
can be the implementation:

  * `_stationcheck.ts_access_url` - what `station.json` publishes as `access_url` (and what
    `_stationcheck` then checks with `_TS_ENCODED`);
  * `deploy/scripts/gen_ts_routes.py` - the committed Caddy map value the front door redirects to,
    written by a tool that must not import the ingest stack;
  * `portal/src/data.js tsArchiveUrl` - the inert archive reference beside the route in the hand-off
    pointer file, in a language that has no `quote(safe="/")` at all.

The first two now CALL the leaf; the JS one cannot, so it is held to the same bytes instead. That is
what this file and its Node twin (`portal/tests/ts_url_vectors.test.js`) do, on the
`license_instrument_vectors.json` precedent: each vector's `expected` is the LEAF'S OWN output, and
both mirrors are asserted against it, so a rendering change that updates one side reds on the other.
The generator's arm lives in `deploy/tests/test_frontdoor_ts_routes.py`, which already imports it.

NON-VACUOUS failure criteria:
  * every vector round-trips through the leaf byte-for-byte (the mutation target: change the safe
    set or drop the strip and exactly the affected vectors red, here and in the Node twin);
  * the file exercises the classes that MATTER for a route, not a list of plain paths: the corpus
    space-and-brackets case, the sub-delims Python escapes and JavaScript does not, a literal `%`,
    the two characters that would end a path at the client, and a non-ASCII code point;
  * every encoded path satisfies `_TS_ENCODED`, the rule the published route is judged by, so the
    vectors cannot drift into a form the emitter's own gate would refuse.
Stdlib only.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "extract"))
import _stationcheck as stcheck   # noqa: E402

VECTORS = HERE / "fixtures" / "ts_url_vectors.json"


def _load():
    return json.loads(VECTORS.read_text(encoding="utf-8"))


def test_the_leaf_reproduces_every_shared_vector():
    doc = _load()
    assert doc["prefix"] == stcheck.TS_ACCESS_PREFIX, "the vectors name another host"
    bad = [v["name"] for v in doc["vectors"]
           if stcheck.ts_access_url(v["url_path"]) != v["expected"]
           or stcheck.ts_encode_path(v["url_path"]) != v["encoded_path"]]
    assert not bad, f"ts_access_url diverged from ts_url_vectors.json: {bad}"


def test_the_absolute_route_is_the_prefix_plus_the_encoded_path_and_nothing_else():
    # The two exported forms are one string, so a caller that needs the bare path (the Caddy map
    # value) and a caller that needs the URL (station.json) can never disagree about the middle.
    for v in _load()["vectors"]:
        assert v["expected"] == stcheck.TS_ACCESS_PREFIX + v["encoded_path"], v["name"]


def test_every_encoded_vector_passes_the_gate_the_published_route_is_judged_by():
    # The encoder writes what _stationcheck admits. If these two ever part company the workflow publishes
    # routes its own semantic layer would reject, which is a build failure disguised as a vector file.
    for v in _load()["vectors"]:
        assert stcheck._TS_ENCODED.match(v["encoded_path"]), v["name"]


def test_the_vectors_cover_the_classes_a_route_can_die_on():
    # Non-vacuity of the FILE: a set of plain paths would pass every assertion above while proving
    # nothing about the cases that actually break a download.
    names = {v["name"] for v in _load()["vectors"]}
    for needed in ("plain_path", "space_and_brackets", "leading_slashes_stripped",
                   "surrounding_whitespace_trimmed", "sub_delims_are_escaped",
                   "percent_is_itself_escaped", "query_and_fragment_cannot_split_the_route",
                   "non_ascii_becomes_utf8_bytes", "astral_code_point_is_one_character_not_two",
                   "unreserved_survive_untouched"):
        assert needed in names, f"the vector file misses the {needed!r} class"


def test_the_expected_strings_carry_the_distinctive_escapes():
    # Non-vacuity of the EXPECTED values, independent of the render: a vector file whose expectations
    # were regenerated from a broken encoder would still satisfy the round-trip above.
    by = {v["name"]: v["encoded_path"] for v in _load()["vectors"]}
    assert by["space_and_brackets"].endswith("C5%20%5BREMOTE%5D.zip")
    # !'()* are the set encodeURIComponent leaves alone, which is why the JS mirror cannot delegate
    # to it; + and & would otherwise be read as a space and a parameter separator.
    for esc in ("%21", "%27", "%28", "%29", "%2A", "%2B", "%26"):
        assert esc in by["sub_delims_are_escaped"], esc
    assert "%25" in by["percent_is_itself_escaped"]
    assert "%3F" in by["query_and_fragment_cannot_split_the_route"]
    assert "%23" in by["query_and_fragment_cannot_split_the_route"]
    assert "%C3%BC" in by["non_ascii_becomes_utf8_bytes"]      # one code point, two UTF-8 bytes
    # Four UTF-8 bytes for ONE character. The BMP vector above cannot catch a per-code-unit mirror:
    # only a code point above the BMP splits into surrogates and takes encodeURIComponent down.
    assert "%F0%9F%98%80" in by["astral_code_point_is_one_character_not_two"]
    assert by["unreserved_survive_untouched"] == "my80/a-b_c.d~e/F9.zip"
    assert by["leading_slashes_stripped"] == by["surrounding_whitespace_trimmed"]
