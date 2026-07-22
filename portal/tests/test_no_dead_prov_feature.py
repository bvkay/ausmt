"""Dead m.prov (provisional DOI mapping) feature removal (Invariant 10).

SMETA.prov drove a "part" DOI badge + a "(source mapping provisional)" citation footnote + a lineage-row
"prov." span in drawer.js/exports.js, but the engine never emits a `prov` key on survey metadata (verified
against extract/build_portal.py and the survey.yaml schema) — so those branches were permanently dead:
the DOI badge could only ever render "ok" or "no", never "part", and the provisional footnotes never fired.
Dead conditionals like this are a maintenance trap (a future SMETA.prov typo would silently do nothing).

This does NOT touch the unrelated CSS class/name `.prov` used elsewhere in drawer.js as a generic
"not recorded / muted" style hook (e.g. `<span class='prov'>not recorded</span>`) — that is pre-existing,
still-live styling for missing metadata in general, not the dead SMETA.prov field this task removes.

Fails if: `m.prov` (or `SMETA[...].prov`) is referenced anywhere in portal/src — i.e. the dead conditional
reappears — or if the DOI badge stops being reachable as "ok" (doi present) / "no" (doi absent).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/


def test_no_m_prov_references():
    hits = []
    for f in (ROOT / "src").glob("*.js"):
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"\bm\.prov\b", line):
                hits.append(f"{f.name}:{lineno}: {line.strip()}")
    assert not hits, "dead SMETA.prov conditional reappeared:\n" + "\n".join(hits)


def test_doi_badge_is_ok_or_no_only():
    # The DOI badge must stay a TWO-STATE ok/no check — never the dead three-way "part" prov branch.
    # §2a broadened the predicate from a bare m.doi to hasDatasetDoi(m) ("a persistent dataset identifier
    # exists in this survey's provenance chain" — a minted dataset_doi OR a DOI-typed related_identifier),
    # shared by both badge sites. That is still ok/no only; this pins the new expression and that the badge
    # never regains a "part" state.
    src = (ROOT / "src" / "drawer.js").read_text(encoding="utf-8")
    assert 'badge("DOI",hasDatasetDoi(m)?"ok":"no")' in src, \
        "DOI badge should be ok/no via the shared hasDatasetDoi(m) predicate (no provisional/part branch)"
    assert 'badge("DOI"' not in src.replace('badge("DOI",hasDatasetDoi(m)?"ok":"no")', ""), \
        "a DOI badge site is not routed through the shared hasDatasetDoi(m) predicate"
    assert 'badge("DOI",hasDatasetDoi(m)?"ok":"part"' not in src and '"part":"no"' not in src, \
        "the DOI badge must never render a three-way 'part' state"


def test_citation_and_lineage_no_longer_annotate_provisional():
    drawer = (ROOT / "src" / "drawer.js").read_text(encoding="utf-8")
    exports = (ROOT / "src" / "exports.js").read_text(encoding="utf-8")
    assert "source mapping provisional" not in drawer
    assert "source mapping provisional" not in exports
