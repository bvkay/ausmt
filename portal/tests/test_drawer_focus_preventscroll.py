"""Drawer focus must not scroll the page (first-open bounce guard).

On the FIRST station/survey open the #drawer is still transform:translateX(102%) off-screen mid slide-in.
_focusDrawer() (drawer.js) moves focus onto the drawer .close button for accessibility — but a bare
t.focus() makes the browser scroll documentElement ~428px left to reveal the off-screen focus target,
then snap back when the .16s slide settles: a visible page-wide bounce (measured scrollLeft 0->428->0,
map re-fit unchanged). The fix passes { preventScroll: true } so focus still lands on the close button
WITHOUT the scroll-into-view.

jsdom cannot exercise the scroll itself (no layout/transition), so this pins the CALL SHAPE as a cheap
regression guard — proven non-vacuous: it fails against the pre-fix drawer.js (bare t.focus()). The real
proof is the instrumented browser run.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # portal/


def test_focus_drawer_passes_preventscroll():
    src = (ROOT / "src" / "drawer.js").read_text(encoding="utf-8")
    m = re.search(r"function _focusDrawer\(\)\{.*?\}\}", src, re.DOTALL)
    assert m, "could not locate _focusDrawer() in drawer.js"
    body = m.group(0)
    # The focus call inside _focusDrawer must pass preventScroll:true so an off-screen focus target does
    # not trigger the browser's scroll-into-view (the first-open page bounce).
    assert re.search(r"\.focus\(\s*\{\s*preventScroll\s*:\s*true\s*\}\s*\)", body), (
        "_focusDrawer() must call .focus({ preventScroll: true }) to avoid the off-screen "
        "focus-into-view page bounce on first drawer open; found:\n" + body
    )
    # Guard against a stray bare focus() slipping back in alongside the fixed one.
    assert not re.search(r"\.focus\(\s*\)", body), (
        "_focusDrawer() still contains a bare .focus() (no preventScroll) — would reintroduce the bounce"
    )
