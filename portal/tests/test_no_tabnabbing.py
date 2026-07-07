"""Reverse-tabnabbing guard (Invariant 10).

drawer.js used `target="_rel"` on 6 external-link sites and `window.open(url, "_rel")` on 3 more, all
opening third-party origins (DOI resolvers, hdl.handle.net, an NCI collection, funder PIDs) in a new tab
WITHOUT `rel="noopener noreferrer"` — textbook reverse tabnabbing: the opened page gets `window.opener`
and can navigate the AusMT tab to a phishing look-alike. `target="_rel"` is not even a real browser target
keyword (it looks like a typo for "noopener" that never got the accompanying `rel` attribute), so every
one of those links opened a tab the parent page could be redirected through.

Fails if: any `_rel` string reappears anywhere under portal/src/*.js or the two shipped HTML pages
(index.html, about.html) — the ONLY place `_rel` could legitimately appear was as this bad target value,
so a bare substring grep is a sufficient regression guard (proven non-vacuous: this test fails against
the pre-fix drawer.js, which has 9 such sites).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/


def _files():
    yield from (ROOT / "src").glob("*.js")
    yield ROOT / "index.html"
    yield ROOT / "about.html"
    yield ROOT / "add-survey.html"


def test_no_rel_target_anywhere():
    hits = []
    for f in _files():
        if not f.exists():
            continue
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), start=1):
            if "_rel" in line:
                hits.append(f"{f.relative_to(ROOT.parent)}:{lineno}: {line.strip()}")
    assert not hits, "found '_rel' (reverse-tabnabbing target) — use target=\"_blank\" rel=\"noopener noreferrer\" instead:\n" + "\n".join(hits)


def test_new_tab_links_carry_noopener_noreferrer():
    # Every target="_blank" anchor in drawer.js must be paired with rel="noopener noreferrer" (order-
    # independent would be nicer, but the fix always writes them in this order — assert that literally).
    src = (ROOT / "src" / "drawer.js").read_text(encoding="utf-8")
    blank_count = src.count('target="_blank"')
    paired_count = src.count('target="_blank" rel="noopener noreferrer"')
    assert blank_count > 0, "expected at least one target=\"_blank\" external link in drawer.js"
    assert blank_count == paired_count, "every target=\"_blank\" anchor must carry rel=\"noopener noreferrer\""
