"""One appearance: the AuScope house style, with no alternative and no control that chooses one.

A second, dark appearance was chosen in the map's welcome dialog or on About and remembered in the
browser under the "ausmt_theme" key by a script of its own. That appearance, its chooser and its
script are retired, and these pins keep them out of every surface: the six static pages, the engine's
page shell (engine/extract/_pages.py) and the SPA's scripts.

A browser that stored the old preference is unaffected because nothing reads the key: no script names
it, no stylesheet keys on an attribute a script could set, and no media query consults the system
scheme. The pages paint the house style from their stylesheet alone, so there is nothing to flash.

FAILS IF:
  * any page, or the engine's shell, declares a data-theme selector, a prefers-color-scheme query, a
    dark color-scheme, or a theme-light or theme-dark variant class;
  * the appearance script (theme.js under src/) ships, any surface loads it, or any portal script
    names the stored key, the change event, the data-theme attribute or the window.AusmtTheme
    interface;
  * any surface draws a white variant of the AuScope mark or lock-up, which only a dark ground took;
  * the welcome dialog or About carries an appearance control, or About keeps an Appearance section
    or a contents link to one;
  * the welcome dialog loses what it keeps: the tour offer, the browse button and the dismissal box;
  * the SPA map mounts its basemap in any flavour but light, or listens for an appearance change.
"""
import re
from pathlib import Path

import pytest

from engine_chrome import PAGES_PY

ROOT = Path(__file__).resolve().parent.parent   # portal/
PAGES = ("index.html", "about.html", "add-survey.html", "brand.html", "releases.html", "404.html")
SURFACES = PAGES + ("engine/extract/_pages.py",)

# What a second appearance needs in a stylesheet or its markup, by spelling.
_SWITCH = ("data-theme", "prefers-color-scheme", "color-scheme:dark", "theme-light", "theme-dark")
# What the retired appearance script read, wrote or announced, by spelling.
_SCRIPT_HOOKS = ("/src/theme.js", "ausmt_theme", "ausmt:theme", "data-theme", "AusmtTheme",
                 "prefers-color-scheme")
# The white files, drawn only on a dark ground.
_WHITE_FILES = ("/vendor/auscope/auscope-mark-white.svg", "/vendor/auscope-ncris-white.png")


def _text(where):
    path = PAGES_PY if where.startswith("engine/") else ROOT / where
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("where", SURFACES)
def test_no_surface_declares_a_second_appearance(where):
    text = _text(where)
    for needle in _SWITCH:
        assert needle not in text, f"{where}: {needle!r} serves an appearance the portal no longer has"


@pytest.mark.parametrize("where", SURFACES)
def test_no_surface_loads_the_appearance_script(where):
    assert "theme.js" not in _text(where), f"{where}: loads the retired appearance script"


def test_the_appearance_script_is_gone():
    assert not (ROOT / "src" / "theme.js").exists(), "portal/src/theme.js is retired"


def test_no_portal_script_reads_or_writes_the_appearance_preference():
    for path in sorted((ROOT / "src").glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for needle in _SCRIPT_HOOKS:
            assert needle not in text, f"src/{path.name}: names {needle!r}"


@pytest.mark.parametrize("where", SURFACES)
def test_no_surface_draws_a_white_variant(where):
    text = _text(where)
    for name in _WHITE_FILES:
        assert name not in text, f"{where}: names {name}, which only a dark ground took"


def test_no_drawn_figure_carries_a_white_variant():
    """The collection figure's corner mark is drawn by drawer.js on the SPA."""
    text = (ROOT / "src" / "drawer.js").read_text(encoding="utf-8")
    for name in _WHITE_FILES:
        assert name not in text, f"src/drawer.js: names {name}"


@pytest.mark.parametrize("where", SURFACES)
def test_no_surface_carries_an_appearance_control(where):
    text = _text(where)
    assert 'name="appearance"' not in text, f"{where}: carries an appearance radio"
    assert "<legend>Appearance</legend>" not in text, f"{where}: carries an appearance fieldset"
    assert not re.search(r"\.(?:introwelcome-)?appearance\b", text), (
        f"{where}: styles an appearance control")


def _welcome():
    text = _text("index.html")
    start = text.index('<div id="introWelcome"')
    return text[start:text.index("</main>", start)]


def test_the_welcome_dialog_keeps_its_offer_and_loses_only_the_appearance_row():
    dialog = _welcome()
    assert "appearance" not in dialog.lower(), "the welcome dialog offers no appearance choice"
    for hook in ('id="introWelcomeHeading"', 'id="introWelcomeText"', 'id="welcomeTour"',
                 'id="welcomeBrowse"', 'id="welcomeDismiss"'):
        assert dialog.count(hook) == 1, f"the welcome dialog keeps {hook}"
    assert 'role="dialog"' in dialog and 'aria-modal="true"' in dialog, "the dialog stays a modal"


def test_about_has_no_appearance_section():
    text = _text("about.html")
    assert 'id="appearance"' not in text and 'href="#appearance"' not in text, (
        "About carries no Appearance section and no contents link to one")
    assert "Appearance" not in text, "About names no appearance setting"
    numbers = re.findall(r"<h2>(\d+) · ", text)
    assert numbers == [str(n) for n in range(1, len(numbers) + 1)], (
        f"About's sections are numbered without a gap: {numbers}")


def test_the_map_draws_the_light_basemap_and_hears_no_appearance_change():
    code = (ROOT / "src" / "map.js").read_text(encoding="utf-8")
    flavours = re.findall(r'flavor:"([a-z]+)"', code)
    assert flavours == ["light", "light"], f"both pmtiles layers are the light flavour: {flavours}"
    assert "ausmt:theme" not in code and "resolvedTheme" not in code, (
        "the map listens for no appearance change")
