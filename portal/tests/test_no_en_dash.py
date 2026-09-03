"""U+2013 (the en dash) is banned from portal source: the sweep pin.

The rule prefers plain dashes: the drawer's empty-value placeholder renders the
hyphen-minus "-", ranges take the spaced hyphen (display grammar), and no portal source file
carries the en dash at all, so the glyph cannot creep back through a copied string or a quoted
example. The sweep covers src/*.js, portal-root *.html and tools/*.js; vendor/ and node_modules/
sit outside those globs by construction (third-party bytes are not ours to edit). Em dashes
(U+2014) are governed separately (pre-existing ones stay, and the standing rule already blocks
new ones), so this pin checks U+2013 only. The codepoint is spelt as an escape throughout this
file so the pin never trips a sweep itself.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # portal/

EN_DASH = "\u2013"
SWEEP_GLOBS = ("src/*.js", "*.html", "tools/*.js")


def test_no_en_dash_in_portal_source():
    swept = []
    hits = {}
    for pattern in SWEEP_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            swept.append(path)
            count = path.read_text(encoding="utf-8").count(EN_DASH)
            if count:
                hits[str(path.relative_to(ROOT))] = count
    # Non-vacuity: the globs must actually reach the drawer (the old placeholder site), the
    # interaction harness (the old quoted-example site) and the SPA shell, else a moved file
    # would hollow the sweep without failing it.
    names = {p.name for p in swept}
    assert {"drawer.js", "interaction_test.js", "index.html"} <= names, sorted(names)
    assert not hits, (
        "U+2013 (en dash) found in portal source; the ruling is plain hyphens "
        "(an absent table value renders '-'): "
        + ", ".join("%s x%d" % (name, count) for name, count in sorted(hits.items()))
    )
