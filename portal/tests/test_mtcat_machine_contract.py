"""About's "Machine contract" entry: the plain-language field guide for the served MTCAT schema.

MTCAT v1.2 typed every field AusMT already served and enum-pinned the ratified vocabularies, which turned
those vocabularies into BUILD GATES. About now explains them to a harvester author in prose. Prose is
exactly the wrong place for a vocabulary to live twice, so nothing here checks that the copy reads well;
every assertion checks that a statement on the page is still TRUE of the artifact it describes:

  * the schema the entry links must be the one the build actually copies beside the data (a documented
    path nobody serves is the failure mode this whole lane exists to avoid);
  * the version and the metadata licence the entry states must equal the values their single sources
    produce (portal.config.yaml's schema_version and the emitter's defaults), not values typed by hand;
  * every vocabulary the entry lists must match the schema's enum SET-FOR-SET, in both directions. A
    missing token would send a consumer looking for a level or a role that exists in the data and is not
    documented; an extra token would document one the build hard-fails on. Both are silent until someone
    writes an importer against the page, which is the whole point of publishing it.

RED-proven, per assertion, by mutating the page: dropping `Sponsor` from the role list, adding a
plausible-looking `level4` to the NCI levels, adding a phantom `legacy` access level, and pointing the
link at a versioned schema filename all fail here.

RESOLVED (fix round): the schema's own description of `surveys[].access` used to claim AusMT emits
"open, metadata_only, embargoed or legacy", and the same phantom fourth value survived in two older
engine/portal comments. No such level has ever existed: ACCESS_LEVELS in the emitter (and in
gateway/editor_form.py, and in the surveys validator) is the three-value tuple this module reads. All
three sites now name the three real levels, and the claim is gated from both ends: this module's
test_access_levels_match_the_producer fails if the PAGE grows a fourth, and the engine's
test_access_description_names_no_phantom_level fails if the SCHEMA DESCRIPTION does.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # portal/
REPO = ROOT.parent                                     # the ausmt monorepo root
ABOUT = ROOT / "about.html"
SCHEMA = REPO / "engine" / "schema" / "mtcat.schema.json"
BUILDER = REPO / "engine" / "extract" / "build_portal.py"
PORTAL_CFG = ROOT / "portal.config.yaml"


# ---------------------------------------------------------------- page slicing helpers

def _docs_section() -> str:
    """The raw markup of <section id="docs"> only, so a pin cannot pass on text elsewhere on the page."""
    raw = ABOUT.read_text(encoding="utf-8")
    assert '<section id="docs">' in raw, 'about.html has no <section id="docs">'
    return raw.split('<section id="docs">', 1)[1].split("</section>", 1)[0]


def _contract_block() -> str:
    """The Machine-contract field guide: from its <h3> to the end of the documentation section."""
    docs = _docs_section()
    assert "<h3>Machine contract</h3>" in docs, (
        "the documentation section must carry a <h3>Machine contract</h3> field guide")
    return docs.split("<h3>Machine contract</h3>", 1)[1]


def _entry_li() -> str:
    """The Machine-contract <li> in the documentation list. It states the version and the licence too, and
    it sits OUTSIDE _contract_block(), so it needs its own pin or it can go stale on its own."""
    hits = [li for li in _docs_section().split("<li")[1:] if "<b>Machine contract</b>" in li]
    assert len(hits) == 1, f"expected exactly one 'Machine contract' entry in the docs list; found {len(hits)}"
    return hits[0].split("</li>", 1)[0]


def _bullet(*must_contain: str) -> str:
    """The one <li> of the field-guide card that contains all of `must_contain`. Slicing per bullet keeps
    a vocabulary pin from passing on a token that happens to appear in a neighbouring bullet."""
    hits = [li for li in _contract_block().split("<li>")[1:]
            if all(m in li for m in must_contain)]
    assert len(hits) == 1, (
        f"expected exactly one field-guide bullet containing all of {must_contain}; found {len(hits)}")
    return hits[0].split("</li>", 1)[0]


def _codes(fragment: str) -> set:
    """Every <code>token</code> value in a fragment."""
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
    """A `p.get("<key>", "<default>")` default from mtcat_document's portal block."""
    m = re.search(rf'p\.get\(\s*"{re.escape(key)}"\s*,\s*"([^"]+)"\s*\)',
                  BUILDER.read_text(encoding="utf-8"))
    assert m, f'could not find the mtcat_document default for "{key}" in build_portal.py'
    return m.group(1)


def _config_schema_version() -> str:
    m = re.search(r"^\s*schema_version:\s*\"([^\"]+)\"", PORTAL_CFG.read_text(encoding="utf-8"), flags=re.M)
    assert m, "could not read portal.schema_version from portal/portal.config.yaml"
    return m.group(1)


# ---------------------------------------------------------------- the entry itself

def test_documentation_section_carries_the_machine_contract_entry():
    docs = _docs_section()
    assert "<b>Machine contract</b>" in docs, (
        "the Documentation section must carry a 'Machine contract' entry in its list")
    assert "data/mtcat.schema.json" in _hrefs(docs), (
        f"the entry must LINK the served schema (data/mtcat.schema.json); section links were {_hrefs(docs)}")
    block = _contract_block()
    assert "data/mtcat.schema.json" in _hrefs(block), (
        "the field guide must link the schema it is a guide to")
    assert "data/mtcat.json" in _hrefs(block), (
        "the field guide must link the catalogue document the schema describes")


def test_the_documented_schema_path_is_the_one_the_build_serves():
    """The failure mode this lane exists to prevent: a documented path nobody serves. The entry links
    data/mtcat.schema.json, so (a) that file must exist in the repo and (b) the build must copy it to the
    served data directory under exactly that name."""
    assert SCHEMA.is_file(), f"{SCHEMA} does not exist, so the documented link resolves to nothing"
    src = BUILDER.read_text(encoding="utf-8")
    assert '(out / "mtcat.schema.json").write_bytes(' in src, (
        "about.html links data/mtcat.schema.json, so build_portal.py must copy the schema to "
        "out/mtcat.schema.json; that copy was not found")
    assert _emitter_default("schema_url") == "mtcat.schema.json", (
        "mtcat.json's schema_url must point at the same unversioned filename the page documents")
    for href in _hrefs(_contract_block()):
        assert not re.search(r"mtcat-\d", href), (
            f"the entry must link the ONE unversioned served schema, not a versioned filename: {href}")


def test_committed_placeholder_document_declares_the_current_schema_version():
    """portal/data/ ships an EMPTY placeholder set so the static portal boots before any build has run,
    and mtcat.json is the only file in it that makes a versioned claim. It sat at `"version": "1.0"`
    from the initial public release through 1.1 and 1.2, which made the one file a reader is most
    likely to open as reference output the one file advertising a retired schema version.

    Pinned to portal.config.yaml rather than to a literal, so a future bump fails here until the
    placeholder is regenerated. It is emitter-produced, not hand-typed, so it stays a truthful example
    of an empty document rather than a hand-maintained approximation of one."""
    doc = json.loads((ROOT / "data" / "mtcat.json").read_text(encoding="utf-8"))
    version = _config_schema_version()
    assert doc["portal"]["version"] == version, (
        f'portal/data/mtcat.json declares MTCAT {doc["portal"]["version"]}, but the current schema '
        f"version is {version}; regenerate the placeholder rather than leaving a stale one committed")
    assert doc["portal"]["schema"] == _schema()["properties"]["portal"]["properties"]["schema"]["const"]
    assert doc["surveys"] == [] and doc["stations"] == [], (
        "this file is the EMPTY boot placeholder; real catalogue data belongs in a build output, "
        "not in the repository")


def test_stated_schema_name_version_and_licence_track_their_single_sources():
    """Every one of these three is stated on the page as a fact about the served document, so each is
    pinned to the thing that produces it rather than to a literal typed twice."""
    block = _contract_block()
    codes = _codes(block)

    assert _schema()["properties"]["portal"]["properties"]["schema"]["const"] in codes, (
        "the entry must name the schema by the value the document actually carries in portal.schema")

    version = _config_schema_version()
    assert version == _emitter_default("schema_version"), (
        f"portal.config.yaml says schema_version {version} but the emitter defaults to "
        f"{_emitter_default('schema_version')}; the page cannot be right about both")
    assert version in codes, (
        f"the entry states the MTCAT version, which is {version} per portal.config.yaml; "
        f"the code spans in the block were {sorted(codes)}")

    licence = _emitter_default("metadata_license")
    assert licence in codes, (
        f"the entry states the catalogue-metadata licence, which the emitter sets to {licence}")

    # The list entry states both facts as well, and it can drift independently of the guide below it.
    entry = _codes(_entry_li())
    assert version in entry and licence in entry, (
        f"the Machine-contract list entry must state the same version ({version}) and metadata licence "
        f"({licence}) as the field guide; it states {sorted(entry)}")
    assert "metadata_license" in codes, (
        "the entry should name the field the licence is served in, so a reader can find it in the document")
    assert "covers the catalogue metadata only" in _flat(block), (
        "the metadata licence must be scoped explicitly: it is NOT the per-survey data licence, and a "
        "harvester that conflates the two republishes restricted data under CC0")


# ---------------------------------------------------------------- vocabularies, both directions

def test_contributor_roles_match_the_schema_enum_exactly():
    """The credit bullet lists the contributor roles. The schema enum is 9: the 8 a survey may declare
    plus HostingInstitution, which the export appends for the hosting portal and no survey declares.
    Set-for-set, so neither a dropped role nor an invented one can ship."""
    li = _bullet("creators[]", "contributors[]")
    documented = {c for c in _codes(li) if re.fullmatch(r"[A-Z][A-Za-z]+", c)}
    assert documented == set(_enum("contributors", "role")), (
        "the documented contributor roles must equal the schema enum exactly.\n"
        f"  documented not in schema: {sorted(documented - set(_enum('contributors', 'role')))}\n"
        f"  schema not documented:    {sorted(set(_enum('contributors', 'role')) - documented)}")
    assert "eight" in _flat(li) and "HostingInstitution" in li, (
        "the bullet must say plainly that eight roles are declarable and that HostingInstitution is the "
        "appended hosting row; a curator who reads nine declarable roles will try to declare the ninth")
    assert set(_enum("creators", "name_type")) <= _codes(li), (
        "the bullet names name_type, so it must give both of its values")
    assert "ORDER" in _flat(li) or "order" in _flat(li), (
        "creators[] order is the citation author order and is semantically load-bearing; the bullet has "
        "to say so or a consumer will sort it")


def test_identifies_levels_match_the_schema_enum_exactly():
    li = _bullet("related_identifiers[]")
    levels = set(_enum("related_identifiers", "identifies"))
    documented = _codes(li) & (levels | {c for c in _codes(li) if re.fullmatch(r"level\d+", c)})
    assert documented == levels, (
        "the documented NCI Table 1 levels must equal the schema enum exactly.\n"
        f"  documented not in schema: {sorted(documented - levels)}\n"
        f"  schema not documented:    {sorted(levels - documented)}")
    assert "NCI Table 1" in _flat(li), (
        "the levels are NCI Table 1 data levels; naming the table is what makes them checkable "
        "against something outside AusMT")


def test_identifier_types_and_relation_reading_are_documented():
    li = _bullet("related_identifiers[]")
    types = {t for t in _enum("related_identifiers", "identifier_type") if t is not None}
    documented = {c for c in _codes(li) if re.fullmatch(r"[A-Z][A-Za-z]*", c)}
    assert documented == types, (
        "the documented identifier types must equal the schema enum (minus the legacy null) exactly.\n"
        f"  documented not in schema: {sorted(documented - types)}\n"
        f"  schema not documented:    {sorted(types - documented)}")
    assert "this survey" in _flat(li) and "that record" in _flat(li), (
        "a DataCite relation is directional and trivially readable backwards; the bullet must give the "
        "reading direction (this survey <relation> that record)")


def test_resolution_states_are_documented_with_absence_meaning_unknown():
    """`resolution` is the honesty facet: the two states are pinned, and so is the rule that ABSENCE means
    unknown rather than broken. A consumer that reads a missing key as 'does not resolve' would suppress
    working identifiers, which is exactly the dishonesty the facet was added to prevent."""
    li = _bullet("resolution")
    states = set(_enum("related_identifiers", "resolution"))
    assert states <= _codes(li), (
        f"the bullet must name every resolution state {sorted(states)}; it named {sorted(_codes(li))}")
    assert "ABSENT" in _flat(li) and "absent never means broken" in _flat(li), (
        "the bullet must state that an absent resolution means unknown, and that a consumer should still "
        "link the identifier")
    assert None not in _enum("related_identifiers", "resolution"), (
        "guards the guard: if resolution ever gains null, 'absence means unknown' stops being the whole "
        "story and this bullet needs rewriting")


def test_access_levels_match_the_producer():
    """Set-for-set against the emitter's ACCESS_LEVELS. This is the assertion that keeps the page off the
    phantom 'legacy' level the schema description still mentions (see the module docstring)."""
    li = _bullet("embargo_until")
    levels = set(_access_levels())
    documented = _codes(li) & (levels | {"legacy", "restricted", "closed", "public", "private"})
    assert documented == levels, (
        "the documented access levels must equal the emitter's ACCESS_LEVELS exactly.\n"
        f"  documented not emitted: {sorted(documented - levels)}\n"
        f"  emitted not documented: {sorted(levels - documented)}")
    assert "fails closed" in _flat(li), (
        "the bullet must say that a level other than open fails closed, including an unrecognised one")
    assert "only its bytes" in _flat(li) and "formats" in _codes(li), (
        "the bullet must say that an embargo withholds BYTES and not discovery, and name the empty "
        "formats list a consumer will actually observe")
    assert "no declared end date" in _flat(li), (
        "embargo_until is present only when declared, so its absence must not be read as 'not embargoed'")


def test_keying_note_names_every_key_a_consumer_will_meet():
    li = _bullet("survey_id")
    for key in ("survey_id", "slug", "ausmt_id", "files[].survey", "bundles[].slug"):
        assert key in _codes(li), (
            f"the keying bullet must name {key}; a consumer joining mtcat to surveys.json or to the "
            f"manifest meets all of these and they are not the same key")
    assert "/data/surveys.json" in _codes(li), "the bullet must name the file the slug is re-keyed in"


def test_machine_contract_block_names_no_unserved_data_file():
    """Every data/<file> the field guide names must be one the build actually writes. Same discipline as
    the fictional-/api/-path scan: a plausible filename is the easiest thing in the world to document."""
    src = BUILDER.read_text(encoding="utf-8")
    named = set(re.findall(r"data/([A-Za-z0-9_.-]+\.json)", _contract_block()))
    assert named, "the field guide should name at least one served data file"
    for f in sorted(named):
        assert f'"{f}"' in src, (
            f"about.html's machine-contract entry names data/{f}, but build_portal.py never writes a "
            f"file by that name")
