"""The MTCAT machine contract, as stated on the two surfaces that state it.

MTCAT v1.2 typed every field AusMT already served and enum-pinned the vocabularies, which turned
those vocabularies into BUILD GATES. Prose is exactly the wrong place for a vocabulary to live twice, so
nothing here checks that the copy reads well; every assertion checks that a statement on a page is still
TRUE of the artifact it describes:

  * the schema a page links must be the one the build actually copies beside the data (a documented path
    nobody serves is the failure mode this whole workflow exists to avoid);
  * the version and the metadata licence About states must equal the values their single sources produce
    (the MTCAT_VERSION constant in contract/generate.py, which the schema's displayed title must match,
    and the emitter's metadata_license default), not values typed by hand;
  * every vocabulary the field guide lists must match the schema's enum SET-FOR-SET, in both directions. A
    missing token would send a consumer looking for a level or a role that exists in the data and is not
    documented; an extra token would document one the build hard-fails on. Both are silent until someone
    writes an importer against the page, which is the whole point of publishing it.

The four-bullet field guide does not live on about.html. About is the two-minute
front door, so the guide moved to docs/docs/reference/mtcat-schema.md under "Reading a served survey
record", and the vocabulary pins moved with it. What About keeps is the machine-contract PARAGRAPH
(<p id="machine-contract">), which names the schema, the version and the metadata licence and links the
served schema. This module now pins both halves, in the file each half actually lives in. The parsing
differs by necessity (HTML <code> spans on About, markdown backticks in the guide) and nothing else does.

RED-proven, per assertion, by mutating the pages: dropping `Sponsor` from the role list, adding a
plausible-looking `level4` to the NCI levels, adding a phantom `legacy` access level, and pointing the
About link at a versioned schema filename all fail here.

RESOLVED: the schema's own description of `surveys[].access` once claimed AusMT emits
"open, metadata_only, embargoed or legacy", and the same phantom fourth value survived in two older
engine/portal comments. No such level has ever existed: ACCESS_LEVELS in the emitter (and in
gateway/editor_form.py, and in the surveys validator) is the three-value tuple this module reads. All
three sites now name the three real levels, and the claim is gated from both ends: this module's
test_access_levels_match_the_producer fails if the GUIDE grows a fourth, and the engine's
test_access_description_names_no_phantom_level fails if the SCHEMA DESCRIPTION does.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
REPO = ROOT.parent                                     # the ausmt monorepo root
ABOUT = ROOT / "about.html"
GUIDE = REPO / "docs" / "docs" / "reference" / "mtcat-schema.md"
SCHEMA = REPO / "engine" / "schema" / "mtcat.schema.json"
BUILDER = REPO / "engine" / "extract" / "build_portal.py"

GUIDE_HEADING = "## Reading a served survey record"


# ---------------------------------------------------------------- page slicing helpers

def _api_section() -> str:
    """The raw markup of <section id="api"> only, so a pin cannot pass on text elsewhere on the page."""
    raw = ABOUT.read_text(encoding="utf-8")
    assert '<section id="api">' in raw, 'about.html has no <section id="api">'
    return raw.split('<section id="api">', 1)[1].split("</section>", 1)[0]


def _about_contract() -> str:
    """About's surviving machine-contract paragraph, sliced by its id so neighbouring prose can't pass a
    pin for it."""
    api = _api_section()
    assert '<p id="machine-contract">' in api, (
        'about.html must keep the machine-contract paragraph (<p id="machine-contract">) in its '
        '"Fetching data via API" section')
    return api.split('<p id="machine-contract">', 1)[1].split("</p>", 1)[0]


def _guide() -> str:
    """The field guide section of the docs MTCAT schema reference, from its heading to the next rule."""
    raw = GUIDE.read_text(encoding="utf-8")
    assert GUIDE_HEADING in raw, (
        f"{GUIDE} must carry the field guide under {GUIDE_HEADING!r}")
    body = raw.split(GUIDE_HEADING, 1)[1]
    return body.split("\n---", 1)[0]


def _sub(*must_contain: str) -> str:
    """The one ### subsection of the field guide that contains all of `must_contain`. Slicing per
    subsection keeps a vocabulary pin from passing on a token in a neighbouring subsection."""
    hits = [s for s in _guide().split("\n### ")[1:]
            if all(m in s for m in must_contain)]
    assert len(hits) == 1, (
        f"expected exactly one field-guide subsection containing all of {must_contain}; found {len(hits)}")
    return hits[0]


def _codes(fragment: str) -> set:
    """Every `token` value in a markdown fragment."""
    return {m.strip() for m in re.findall(r"`([^`\n]+)`", fragment)}


def _html_codes(fragment: str) -> set:
    """Every <code>token</code> value in an HTML fragment."""
    return {m.strip() for m in re.findall(r"<code>(.*?)</code>", fragment, flags=re.S)}


def _flat(s: str) -> str:
    """Collapse whitespace so a prose pin survives the page being re-wrapped at a different column."""
    return re.sub(r"\s+", " ", s)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        d = {k: (v or "") for k, v in attrs}
        if tag == "a" and "href" in d:
            self.hrefs.append(d["href"])


def _hrefs(fragment: str) -> list:
    p = _Links()
    p.feed(fragment)
    return p.hrefs


# ---------------------------------------------------------------- single sources

def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def _survey_props() -> dict:
    return _schema()["properties"]["surveys"]["items"]["properties"]


def _enum(*path) -> list:
    """The enum at a dotted path under surveys[].items.properties, e.g. ('contributors','role')."""
    node = _survey_props()[path[0]]["items"]["properties"][path[1]]
    return list(node["enum"])


def _access_levels() -> tuple:
    """ACCESS_LEVELS as the EMITTER declares it (the producer of mtcat's `access` field). Read out of the
    source text rather than imported: build_portal.py pulls in the mt_metadata stack at import time and
    this suite is deliberately stack-free."""
    m = re.search(r"^ACCESS_LEVELS\s*=\s*\(([^)]*)\)", BUILDER.read_text(encoding="utf-8"), flags=re.M)
    assert m, "could not find ACCESS_LEVELS in engine/extract/build_portal.py"
    levels = tuple(re.findall(r'"([^"]+)"', m.group(1)))
    assert levels, f"ACCESS_LEVELS parsed empty from {m.group(1)!r}"
    return levels


def _emitter_default(key: str) -> str:
    """A `p.get("<key>", "<default>")` LITERAL default from mtcat_document's portal block.

    schema_version is deliberately NOT one of these any more, and asking for it here now fails: it is
    read from the schema (see _schema_version) because a literal default is exactly the defect this
    workflow kept re-finding. schema_url and metadata_license stay literals because neither is derived from
    anything, so a literal is where they honestly live."""
    m = re.search(rf'p\.get\(\s*"{re.escape(key)}"\s*,\s*"([^"]+)"\s*\)',
                  BUILDER.read_text(encoding="utf-8"))
    assert m, f'could not find the mtcat_document default for "{key}" in build_portal.py'
    return m.group(1)


def _schema_version() -> str:
    """The MTCAT schema version as its SINGLE SOURCE declares it: the schema's own self-identifying
    title. The engine's emitter, load_portal_config and gen_config all derive from this file (via the
    generated MTCAT_SCHEMA_VERSION constant), so pinning the page to the same place pins it to what a
    harvester will actually be served. engine/tests/test_mtcat_version_parity.py holds the full
    cross-surface pin, including a real build; this is the half that guards the PAGE."""
    title = _schema()["title"]
    m = re.match(r"^MTCAT v(\d+\.\d+):", title)
    assert m, f"the schema must declare its version in its title as 'MTCAT v<MAJOR>.<MINOR>: ...'; got {title!r}"
    return m.group(1)


def _constant_schema_version() -> str:
    """The MTCAT version as its SINGLE SOURCE declares it since the 2.0 inversion: the
    MTCAT_VERSION constant in contract/generate.py, read raw from the source text (this suite is
    deliberately import-light). portal.config.yaml does not declare a schema_version key at all -
    config.js is GENERATED from this constant, and the engine parity suite pins that the key never
    returns."""
    src = (REPO / "contract" / "generate.py").read_text(encoding="utf-8")
    m = re.search(r'^MTCAT_VERSION\s*=\s*"(\d+\.\d+)"', src, flags=re.M)
    assert m, "contract/generate.py must declare MTCAT_VERSION (the single source)"
    return m.group(1)


# ---------------------------------------------------------------- About's surviving paragraph

def test_about_keeps_the_machine_contract_paragraph_with_its_schema_link():
    """The stage-2 rule: About keeps the quickstart plus the machine-contract line with its
    schema link. FAILS if the paragraph is dropped, if it stops linking the served schema, or if it stops
    linking the catalogue document the schema describes."""
    para = _about_contract()
    assert "<b>Machine contract.</b>" in para, (
        "the paragraph must still label itself, so a reader scanning About can find the contract statement")
    hrefs = _hrefs(para)
    assert "data/mtcat.schema.json" in hrefs, (
        f"the paragraph must LINK the served schema (data/mtcat.schema.json); its links were {hrefs}")
    assert "data/mtcat.json" in hrefs, (
        f"the paragraph must link the catalogue document the schema describes; its links were {hrefs}")


def test_about_points_at_the_field_guide_it_no_longer_carries():
    """The field guide lives on the docs site. About must SEND readers there,
    or the four vocabularies become undiscoverable from the portal. FAILS if the
    pointer is missing."""
    para = _about_contract()
    assert "https://ausmt.readthedocs.io/en/latest/reference/mtcat-schema/" in para, (
        "About's machine-contract paragraph must link the docs MTCAT schema reference, which is where the "
        "field guide now lives")


def test_the_documented_schema_path_is_the_one_the_build_serves():
    """The failure mode this module exists to prevent: a documented path nobody serves. About links
    data/mtcat.schema.json, so (a) that file must exist in the repo and (b) the build must copy it to the
    served data directory under exactly that name."""
    assert SCHEMA.is_file(), f"{SCHEMA} does not exist, so the documented link resolves to nothing"
    src = BUILDER.read_text(encoding="utf-8")
    assert '(out / "mtcat.schema.json").write_bytes(' in src, (
        "about.html links data/mtcat.schema.json, so build_portal.py must copy the schema to "
        "out/mtcat.schema.json; that copy was not found")
    assert _emitter_default("schema_url") == "mtcat.schema.json", (
        "mtcat.json's schema_url must point at the same unversioned filename the page documents")
    for href in _hrefs(_about_contract()):
        assert not re.search(r"mtcat-\d", href), (
            f"the paragraph must link the ONE unversioned served schema, not a versioned filename: {href}")


def test_committed_placeholder_document_declares_the_current_schema_version():
    """portal/data/ ships an EMPTY placeholder set so the static portal boots before any build has run,
    and mtcat.json is the only file in it that makes a versioned claim. It sat at `"version": "1.0"`
    from the initial public release through 1.1 and 1.2, which made the one file a reader is most
    likely to open as reference output the one file advertising a retired schema version.

    Pinned to the single-source constant rather than to a literal, so a future bump fails here until
    the placeholder is regenerated. It is emitter-produced, not hand-typed, so it stays a truthful
    example of an empty document rather than a hand-maintained approximation of one."""
    doc = json.loads((ROOT / "data" / "mtcat.json").read_text(encoding="utf-8"))
    version = _constant_schema_version()
    assert doc["portal"]["version"] == version, (
        f'portal/data/mtcat.json declares MTCAT {doc["portal"]["version"]}, but the current schema '
        f"version is {version}; regenerate the placeholder rather than leaving a stale one committed")
    assert doc["portal"]["schema"] == _schema()["properties"]["portal"]["properties"]["schema"]["const"]
    assert doc["surveys"] == [] and doc["stations"] == [], (
        "this file is the EMPTY boot placeholder; real catalogue data belongs in a build output, "
        "not in the repository")


def test_stated_schema_name_version_and_licence_track_their_single_sources():
    """Every one of these three is stated on About as a fact about the served document, so each is
    pinned to the thing that produces it rather than to a literal typed twice."""
    codes = _html_codes(_about_contract())

    assert _schema()["properties"]["portal"]["properties"]["schema"]["const"] in codes, (
        "the paragraph must name the schema by the value the document actually carries in portal.schema")

    version = _constant_schema_version()
    assert version == _schema_version(), (
        f"contract/generate.py MTCAT_VERSION is {version} but the schema title displays "
        f"{_schema_version()}; the page cannot be right about both")
    assert version in codes, (
        f"the paragraph states the MTCAT version, which is {version} per the single-source constant; "
        f"the code spans in it were {sorted(codes)}")

    licence = _emitter_default("metadata_license")
    assert licence in codes, (
        f"the paragraph states the catalogue-metadata licence, which the emitter sets to {licence}")
    assert "metadata_license" in codes, (
        "the paragraph should name the field the licence is served in, so a reader can find it in the document")
    assert "covers the catalogue metadata only" in _flat(_about_contract()), (
        "the metadata licence must be scoped explicitly: it is NOT the per-survey data licence, and a "
        "harvester that conflates the two republishes restricted data under CC0")


# ---------------------------------------------------------------- the field guide, both directions

def test_field_guide_links_the_document_and_the_schema_it_describes():
    guide = _guide()
    assert "data/mtcat.schema.json" in guide, "the field guide must link the schema it is a guide to"
    assert "data/mtcat.json" in guide, "the field guide must link the catalogue document the schema describes"


def test_contributor_roles_match_the_schema_enum_exactly():
    """The credit subsection lists the contributor roles. The schema enum is 9: the 8 a survey may declare
    plus HostingInstitution, which the export appends for the hosting portal and no survey declares.
    Set-for-set, so neither a dropped role nor an invented one can ship."""
    sub = _sub("creators[]", "contributors[]")
    documented = {c for c in _codes(sub) if re.fullmatch(r"[A-Z][A-Za-z]+", c)}
    assert documented == set(_enum("contributors", "role")), (
        "the documented contributor roles must equal the schema enum exactly.\n"
        f"  documented not in schema: {sorted(documented - set(_enum('contributors', 'role')))}\n"
        f"  schema not documented:    {sorted(set(_enum('contributors', 'role')) - documented)}")
    assert "eight" in _flat(sub) and "HostingInstitution" in sub, (
        "the subsection must say plainly that eight roles are declarable and that HostingInstitution is "
        "the appended hosting row; a curator who reads nine declarable roles will try to declare the ninth")
    assert set(_enum("creators", "name_type")) <= _codes(sub), (
        "the subsection names name_type, so it must give both of its values")
    assert "ORDER" in _flat(sub) or "order" in _flat(sub), (
        "creators[] order is the citation author order and is semantically load-bearing; the subsection "
        "has to say so or a consumer will sort it")


def test_identifies_levels_match_the_schema_enum_exactly():
    sub = _sub("related_identifiers[]")
    levels = set(_enum("related_identifiers", "identifies"))
    documented = _codes(sub) & (levels | {c for c in _codes(sub) if re.fullmatch(r"level\d+", c)})
    assert documented == levels, (
        "the documented NCI Table 1 levels must equal the schema enum exactly.\n"
        f"  documented not in schema: {sorted(documented - levels)}\n"
        f"  schema not documented:    {sorted(levels - documented)}")
    assert "NCI Table 1" in _flat(sub), (
        "the levels are NCI Table 1 data levels; naming the table is what makes them checkable "
        "against something outside AusMT")


def test_identifier_types_and_relation_reading_are_documented():
    sub = _sub("related_identifiers[]")
    types = {t for t in _enum("related_identifiers", "identifier_type") if t is not None}
    documented = {c for c in _codes(sub) if re.fullmatch(r"[A-Z][A-Za-z]*", c)}
    assert documented == types, (
        "the documented identifier types must equal the schema enum (minus the legacy null) exactly.\n"
        f"  documented not in schema: {sorted(documented - types)}\n"
        f"  schema not documented:    {sorted(types - documented)}")
    assert "this survey" in _flat(sub) and "that record" in _flat(sub), (
        "a DataCite relation is directional and trivially readable backwards; the subsection must give "
        "the reading direction (this survey <relation> that record)")


def test_resolution_states_are_documented_with_absence_meaning_unknown():
    """`resolution` is the honesty facet: the two states are pinned, and so is the rule that ABSENCE means
    unknown rather than broken. A consumer that reads a missing key as 'does not resolve' would suppress
    working identifiers, which is exactly the dishonesty the facet was added to prevent."""
    sub = _sub("resolution")
    states = set(_enum("related_identifiers", "resolution"))
    assert states <= _codes(sub), (
        f"the subsection must name every resolution state {sorted(states)}; it named {sorted(_codes(sub))}")
    assert "ABSENT" in _flat(sub) and "absent never means broken" in _flat(sub), (
        "the subsection must state that an absent resolution means unknown, and that a consumer should "
        "still link the identifier")
    assert None not in _enum("related_identifiers", "resolution"), (
        "guards the guard: if resolution ever gains null, 'absence means unknown' stops being the whole "
        "story and this subsection needs rewriting")


def test_access_levels_match_the_producer():
    """Set-for-set against the emitter's ACCESS_LEVELS. This is the assertion that keeps the guide off the
    phantom 'legacy' level the schema description still mentions (see the module docstring)."""
    sub = _sub("embargo_until")
    levels = set(_access_levels())
    documented = _codes(sub) & (levels | {"legacy", "restricted", "closed", "public", "private"})
    assert documented == levels, (
        "the documented access levels must equal the emitter's ACCESS_LEVELS exactly.\n"
        f"  documented not emitted: {sorted(documented - levels)}\n"
        f"  emitted not documented: {sorted(levels - documented)}")
    assert "fails closed" in _flat(sub), (
        "the subsection must say that a level other than open fails closed, including an unrecognised one")
    assert "only its bytes" in _flat(sub) and "formats" in _codes(sub), (
        "the subsection must say that an embargo withholds BYTES and not discovery, and name the empty "
        "formats list a consumer will actually observe")
    assert "no declared end date" in _flat(sub), (
        "embargo_until is present only when declared, so its absence must not be read as 'not embargoed'")


def test_keying_note_names_every_key_a_consumer_will_meet():
    sub = _sub("survey_id")
    for key in ("survey_id", "slug", "ausmt_id", "files[].survey", "bundles[].slug"):
        assert key in _codes(sub), (
            f"the keying subsection must name {key}; a consumer joining mtcat to surveys.json or to the "
            f"manifest meets all of these and they are not the same key")
    assert "/data/surveys.json" in _codes(sub), "the subsection must name the file the slug is re-keyed in"


def test_field_guide_names_no_unserved_data_file():
    """Every data/<file> the field guide names must be one the build actually writes. Same discipline as
    the fictional-/api/-path scan: a plausible filename is the easiest thing in the world to document."""
    src = BUILDER.read_text(encoding="utf-8")
    named = set(re.findall(r"data/([A-Za-z0-9_.-]+\.json)", _guide()))
    assert named, "the field guide should name at least one served data file"
    for f in sorted(named):
        assert f'"{f}"' in src, (
            f"the field guide names data/{f}, but build_portal.py never writes a file by that name")
