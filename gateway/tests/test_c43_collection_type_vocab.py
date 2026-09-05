"""The collection type vocabulary, held equal as a SET across every carrier that states it.

The `type` key is validator-unenforced, so the console's select IS the guardrail. That makes
the vocabulary a contract with no schema behind it, and it is written out in seven places. Adding a
value to the prose carriers alone left the two gateway tuples short, which is a hard 400 on the
publish spec path and a select that renders (unset) for a value the corpus legitimately carries: the
console misreports the record it is editing. Adding it to the tuples alone would let a curator save a
value no page documents.

So: read the vocabulary FROM each carrier, by regex over the shipped files rather than from a literal
copied into this test, and assert one set. Any carrier edited alone goes red here.

Carriers:
  gateway/curatorpage.py            _COLLECTION_TYPE_VOCAB, the select's options (the guardrail)
  gateway/app.py                    the same tuple, imported, for both write-path gates
  docs/.../collection-ids.md        the survey.yaml example's `type:` comment
  docs/.../collection-ids.md        the Type vocabulary definition list
  docs/.../mtcat-schema.md          4.3 collections[].type, "Allowed values"
  docs/.../survey-yaml.md           the collection key table's `type` row
  docs/.../portal-documents.md      the collections record's `type` member
  engine/extract/_pages.py          the /collections hub lede (every value but the `other` catch-all)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from gateway import app as app_mod
from gateway import curatorpage

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS = _REPO_ROOT / "docs" / "docs"
_COLLECTION_IDS_MD = _DOCS / "developer" / "collection-ids.md"
_PORTAL_DOCUMENTS_MD = _DOCS / "developer" / "portal-documents.md"
_MTCAT_SCHEMA_MD = _DOCS / "reference" / "mtcat-schema.md"
_SURVEY_YAML_MD = _DOCS / "reference" / "survey-yaml.md"
_PAGES_PY = _REPO_ROOT / "engine" / "extract" / "_pages.py"


def _text(path: Path) -> str:
    assert path.is_file(), f"carrier missing from the checkout: {path}"
    return path.read_text(encoding="utf-8")


def _sole(pattern: str, text: str, what: str) -> str:
    """The ONE line matching `pattern`. Two matches means the anchor stopped being unique and the
    test would silently start reading a different row, so that is a failure, not a first-match."""
    found = re.findall(pattern, text, flags=re.M)
    assert len(found) == 1, f"expected exactly one {what}, found {len(found)}: {found!r}"
    return found[0]


def _section(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def _backticked(fragment: str) -> set[str]:
    return set(re.findall(r"`([a-z]+)`", fragment))


def _carriers() -> dict[str, set[str]]:
    ids_md = _text(_COLLECTION_IDS_MD)
    return {
        "curatorpage select tuple": set(curatorpage._COLLECTION_TYPE_VOCAB),  # noqa: SLF001
        "app write-path tuple": set(app_mod._COLLECTION_TYPE_VOCAB),  # noqa: SLF001
        "collection-ids.md type comment": {
            v.strip() for v in
            _sole(r"^\s*type:\s*\w+\s*#\s*(.+?)\s*$", ids_md, "`type:` comment in collection-ids.md").split("|")
        },
        "collection-ids.md Type vocabulary list": set(re.findall(
            r"^- `([a-z]+)`:", _section(ids_md, "## Type vocabulary", "\n## "), flags=re.M)),
        "mtcat-schema.md 4.3 Allowed values": _backticked(_sole(
            r"^\| Allowed values \| (.+?) \|$",
            _section(_text(_MTCAT_SCHEMA_MD), "### 4.3 collections[].type", "### 4.4"),
            "Allowed values row under mtcat-schema.md 4.3")),
        "survey-yaml.md collection type row": _backticked(_sole(
            r"^\| `type` \| recommended \| string \| (.+?) \|$", _text(_SURVEY_YAML_MD),
            "collection `type` row in survey-yaml.md")),
        "portal-documents.md type member": _backticked(_sole(
            r"^\| `type` \| string or null \| (.+?) \|$", _text(_PORTAL_DOCUMENTS_MD),
            "collections `type` row in portal-documents.md")),
    }


def _hub_lede() -> str:
    """The lede string as the engine ships it, read by parsing the module (not importing it: the
    engine stack is not installed in the gateway test environment)."""
    tree = ast.parse(_text(_PAGES_PY))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_COLLECTIONS_LEDE" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("_COLLECTIONS_LEDE is gone from engine/extract/_pages.py")


# THE PIN. Every carrier states the same set, or this is red. FAILS IF one carrier is edited alone.
# RED (executed): dropping "compilation" from either gateway tuple fails here naming that carrier.
def test_collection_type_vocabulary_is_one_set_across_every_carrier():
    carriers = _carriers()
    reference = carriers["curatorpage select tuple"]
    assert reference, "the select's option tuple is empty"
    for name, values in carriers.items():
        assert values == reference, (
            f"the collection type vocabulary has drifted: {name} states {sorted(values)}, "
            f"the console's select offers {sorted(reference)}")


# The two gateway tuples are ONE object, not two equal copies: app.py imports the select's tuple, so
# the write path cannot refuse a value the console offers. FAILS IF app.py restates it (the drift that
# left the publish spec path 400-ing on a value while every doc said it was legal).
def test_app_write_path_uses_the_selects_own_tuple():
    assert app_mod._COLLECTION_TYPE_VOCAB is curatorpage._COLLECTION_TYPE_VOCAB  # noqa: SLF001


# The hub lede names every value a reader can meet as a chip. `other` is the catch-all and naming it
# in a sentence tells a reader nothing, so it is the one deliberate omission.
def test_hub_lede_names_every_vocabulary_value_but_the_catch_all():
    lede = _hub_lede()
    for value in sorted(set(curatorpage._COLLECTION_TYPE_VOCAB) - {"other"}):  # noqa: SLF001
        assert re.search(rf"\b{value}\b", lede), f"the /collections hub lede does not name {value!r}: {lede!r}"


# The vocabulary is CLOSED. test_c43_stage3b.py's probe publishes ctype="campaign" and expects a
# refusal, so this keeps that negative pin non-vacuous: if "campaign" is ever added to the vocabulary, that probe
# must move to another out-of-vocab value rather than quietly passing for the wrong reason.
def test_campaign_stays_out_of_vocab():
    assert "campaign" not in curatorpage._COLLECTION_TYPE_VOCAB  # noqa: SLF001


# The vocabulary change has to REACH behaviour, not just the constants: the publish spec gate admits
# the value, the select marks it selected instead of falling through to (unset), and the
# dropped value is still refused.
def test_compilation_passes_the_spec_gate_and_renders_selected():
    op = {"slug": "auslamp-b", "op": "set",
          "block": {"id": "australia-legacy-gds", "title": "Australia legacy GDS",
                    "type": "compilation", "status": "completed"}}
    assert app_mod._collection_spec_violation(  # noqa: SLF001
        "australia-legacy-gds", [op], "note") is None
    bad = {**op, "block": {**op["block"], "type": "campaign"}}
    assert app_mod._collection_spec_violation(  # noqa: SLF001
        "australia-legacy-gds", [bad], "note") == "an operation carries an out-of-vocab collection type"

    html = curatorpage._select_html(  # noqa: SLF001
        "f_type", curatorpage._COLLECTION_TYPE_VOCAB, "compilation", blank_label="(unset)")  # noqa: SLF001
    assert '<option value="compilation" selected>compilation</option>' in html
    assert '<option value="" selected>' not in html, "a value in the vocabulary must not render as (unset)"
