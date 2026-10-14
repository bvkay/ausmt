"""The Advanced search box's vertical padding, pinned from the declared terms.

Collapsed, the box is its border, its own padding and one summary line:

    above the text = details padding-top    + summary padding-top
    below the text = summary padding-bottom + details padding-bottom   (collapsed)

The box's 10px foot belongs to the open body, so it rides the [open] rule: on the base rule it would
make the collapsed box 2 + 9 = 11px above the summary's line box and 9 + 10 = 19px below it, and the
label would sit visibly high. Collapsed, the box is 11px on both sides; open, it keeps 11px above the
summary text and 10px under its last field.

The pin compares declared constants rather than measured pixels: a pixel count is a statement about
the runner's font, and the two expressions above hold at every font and every width.
"""
import re
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / "index.html"


def _rules():
    """{selector: {property: value}} for every rule whose selector starts with details.advanced."""
    css = "".join(re.findall(r"<style[^>]*>([\s\S]*?)</style>", INDEX.read_text(encoding="utf-8")))
    css = re.sub(r"/\*[\s\S]*?\*/", "", css)
    out = {}
    for sel, body in re.findall(r"(details\.advanced[^{]*)\{([^}]*)\}", css):
        decls = dict((k.strip(), v.strip()) for k, v in
                     (d.split(":", 1) for d in body.split(";") if ":" in d))
        for one in sel.split(","):
            out.setdefault(one.strip(), {}).update(decls)
    return out


def _box(shorthand):
    """[top, right, bottom, left] in px from a 1 to 4 value padding shorthand."""
    v = [float(x[:-2]) if x.endswith("px") else float(x) for x in shorthand.split()]
    assert 1 <= len(v) <= 4, shorthand
    top, right = v[0], v[1 % len(v)]
    bottom = v[2] if len(v) > 2 else top
    left = v[3] if len(v) > 3 else right
    return [top, right, bottom, left]


def test_the_collapsed_box_holds_its_summary_text_centred():
    """FAILS IF the collapsed box shows more space under the summary text than above it, or the
    reverse."""
    r = _rules()
    box, summary = _box(r["details.advanced"]["padding"]), _box(r["details.advanced>summary"]["padding"])
    above, below = box[0] + summary[0], summary[2] + box[2]
    assert above == below == 11, f"collapsed: {above}px above the summary text, {below}px below"


def test_the_open_box_keeps_its_spacing():
    """FAILS IF opening the box loses the 10px foot under its last field, or the summary's own
    padding changes, which would move the text in both states at once."""
    r = _rules()
    assert r["details.advanced[open]"].get("padding-bottom") == "10px", r["details.advanced[open]"]
    assert _box(r["details.advanced>summary"]["padding"]) == [9, 0, 9, 0]
    assert _box(r["details.advanced"]["padding"])[0] == 2, "the text keeps its 11px above when open"
