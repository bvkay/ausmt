"""A3 (LANE-CONTRACT-FORM-CREDIT) GREP PIN: no retired flat credit key is written, read or named
anywhere in the shipped portal.

lead_investigator and principal_investigators were retired by the ratified contributor-credit model:
the corpus migration seeded creators[]/contributors[] from them and DELETED them, the engine reads
neither, and the curator editor models neither. A public form that still emitted them would produce
keys nobody downstream can read or fix, so the whole surface has to go at once - inputs, readers,
emission, hints and copy.

Scope is the SHIPPED portal (pages, src/, and the non-test half of tools/). portal/tests/ and the
tools/*_test.js jsdom drivers are excluded, because the pins themselves must name the keys in order to
assert their absence.
"""
from pathlib import Path

import pytest

PORTAL = Path(__file__).resolve().parent.parent
RETIRED = ("lead_investigator", "principal_investigators")
SUFFIXES = {".html", ".js", ".json", ".css", ".yaml", ".yml", ".md", ".py"}
SKIP_DIRS = {"tests", "node_modules", "vendor", "data"}


def _shipped_files():
    for path in sorted(PORTAL.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        rel = path.relative_to(PORTAL)
        if rel.parts and rel.parts[0] in SKIP_DIRS:
            continue
        if path.name.endswith("_test.js") or path.name.endswith(".test.js"):
            continue            # a jsdom driver is test code wherever it lives
        yield rel, path


@pytest.mark.parametrize("key", RETIRED)
def test_no_shipped_portal_file_names_a_retired_credit_key(key):
    offenders = [str(rel) for rel, path in _shipped_files()
                 if key in path.read_text(encoding="utf-8", errors="replace")]
    assert not offenders, f"{key} still referenced in the shipped portal: {offenders}"


def test_the_form_emitter_carries_the_replacement_questions():
    """NON-VACUOUS guard for the pin above: the keys are absent because the questions were REWRITTEN
    onto the ratified homes, not because the whole credit surface was deleted."""
    html = (PORTAL / "add-survey.html").read_text(encoding="utf-8")
    for needle in ("Who should the citation name, in order?", "Who led this survey?", "Who did what?",
                   "Does this dataset already have a citation or DOI?",
                   "Which organisations were involved, and how?",
                   "Is there wording you must include?",
                   "When was this dataset published?",
                   "organisationsEmit", "acknowledgementsEmit", "citationIdentifierRow"):
        assert needle in html, f"the replacement credit surface is missing: {needle}"
