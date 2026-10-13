"""The site chrome every surface wears, stated once for the pins that hold the surfaces to it.

The static pages and the engine's generated pages each carry their own copy of this chrome, because
the portal ships as classic static pages with no template step. These literals are the contract those
copies are compared against: the appearance tokens, the header's identity and tagline, the lock-up
the footers and the map carry, the footer's regions and the appearance row. A pin compares a surface with these strings rather than with
another surface, so two copies that drift together still fail.
"""
import re

# The two token blocks, light (the AuScope house style) and dark. Every page declares both verbatim.
LIGHT = {
    "--bg": "#F2F2F1", "--surface": "#FFFFFF", "--surface-2": "#F2F3F2", "--line": "#CED4DA",
    "--text": "#333333", "--muted": "#6C757D", "--heading": "#282572", "--accent": "#282572",
    "--accent-ink": "#FFFFFF",
    "--lpmt": "#3F88C8", "--bbmt": "#FFC14F", "--amt": "#9FCB5A", "--gds": "#CE348A", "--dot-edge": "#231F20",
    "--ok": "#598F39", "--part": "#9A6B00", "--no": "#EA1E31", "--unk": "#6C757D",
    "--map-bg": "#DFE6E9", "--map-panel": "#F4F5F4", "--map-line": "#CED4DA", "--coast-fill": "#FFFFFF",
    "--coast-line": "#9AA0A6",
    "--shadow": "0 1px 3px rgba(35,31,32,.12)",
    "--mono": "ui-monospace,'SF Mono','Cascadia Mono','Consolas',monospace",
    "--sans": "'Libre Franklin',Inter,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif",
    "color-scheme": "light",
}
DARK = {
    "--bg": "#11182D", "--surface": "#18213D", "--surface-2": "#1E2B4F", "--line": "#2B3557",
    "--text": "#E8EDF1", "--muted": "#8FA3B0", "--heading": "#FFFFFF", "--accent": "#EF7256",
    "--accent-ink": "#16110B",
    "--dot-edge": "#11182D",
    "--ok": "#5BAE6A", "--part": "#D9A23B", "--no": "#E2938B", "--unk": "#5A6E7D",
    "--map-bg": "#0F1626", "--map-panel": "#18213D", "--map-line": "#222C4E", "--coast-fill": "#1D3140",
    "--coast-line": "#3A5266",
    "--shadow": "none",
    "color-scheme": "dark",
}
# The data-type ramp is deliberately absent from the dark block: a legend must not change meaning with
# the theme.
RAMP = ("--lpmt", "--bbmt", "--amt", "--gds")

# The tokens the previous palette used for chrome. No surface declares or reads them.
RETIRED_TOKENS = ("--ink", "--panel", "--panel-2", "--copper")

THEME_SCRIPT = '<script src="/src/theme.js"></script>'

ICON_BLOCK = ('<link rel="icon" href="/favicon.ico" sizes="any">\n'
              '<link rel="icon" href="/vendor/favicon.svg" type="image/svg+xml">\n'
              '<link rel="apple-touch-icon" href="/vendor/auscope/icon-180.png">')

# The AuScope mark pair, the brand kit's vector icon in its own colours and in white. It opens every
# header's identity zone, 36px square, and the collection figures and the icons draw the same files.
MARK_LIGHT = "/vendor/auscope/auscope-mark.svg"
MARK_DARK = "/vendor/auscope/auscope-mark-white.svg"
MARK_SIZE = 36
MARK_PAIR = (f'<img class="brandmark theme-light" src="{MARK_LIGHT}" alt="AuScope" width="36" height="36">'
             f'<img class="brandmark theme-dark" src="{MARK_DARK}" alt="AuScope" width="36" height="36">')

# AusMT's name, set at the AuScope logo's own proportions scaled to the 36px mark: the identity zone's
# 12px gap from mark to name, a 24.5px size whose cap height is 0.48 of the mark, and "Aus" heavy
# against a light "MT" as "Au" is heavy against "Scope". The family stack leads with Calibre, which
# AuScope's licence covers on this site; no sheet declares an @font-face for it and nothing names a
# font file, so a reader without the face installed sees the --sans stack.
WORDMARK_FAMILY = "'Calibre',var(--sans)"
NAME = "<b>Aus</b>MT"
TAGLINE = "Australia's Magnetotelluric Data Portal"
H1_TEXT = "AusMT - Australia's Magnetotelluric (MT) Data Portal"
INDEX_IDENTITY = (f'<h1 class="brandh1"><span class="wordmark">{NAME}</span>'
                  '<span class="visually-hidden"> - Australia\'s Magnetotelluric (MT) Data Portal</span></h1>')
PAGE_IDENTITY = f'<a class="wordmark" href="/">{NAME}</a>'

# The identity zone's rules, verbatim on every surface. The mark's rule sets display, so it ties with
# the switch's first rule on specificity and must come BEFORE the switch. The heading rule is the
# homepage's alone, the one surface whose name is wrapped in its h1.
BRANDMARK_RULE = ".brandmark{height:36px;width:36px;display:block;flex:none}"
WORDMARK_RULES = (".wordmark{font-family:'Calibre',var(--sans);font-weight:300;font-size:24.5px;"
                  "letter-spacing:-.01em;line-height:1;color:var(--heading);text-decoration:none}",
                  ".wordmark b{font-weight:800}")
BRANDH1_RULE = ".brandh1{flex:none;font-size:inherit}"

# The right zone is the tagline alone, on one line. Where the zero-basis zone is narrower than the
# line it ends in an ellipsis inside the zone: overflowing, it would paint over the About control.
TAGLINE_RULE = (".tagline{color:var(--muted);font-size:14px;white-space:nowrap;min-width:0;"
                "overflow:hidden;text-overflow:ellipsis}")
RIGHT_ZONE = f'<div class="hzone hright"><div class="tagline">{TAGLINE}</div></div>'

# The AuScope and NCRIS lock-up is the AuScope brand kit's own colour and white PNGs, named at their
# intrinsic 1919 by 325. It closes the right of every footer on the pages without the big map, linked
# to AuScope, and it takes the map's corner on index.html, unlinked. No header carries it.
LOCKUP_LIGHT = "/vendor/auscope-ncris-colour.png"
LOCKUP_DARK = "/vendor/auscope-ncris-white.png"
LOCKUP_PIXELS = (1919, 325)
LOCKUP = ('<a class="orglockup" href="https://www.auscope.org.au" target="_blank" rel="noopener noreferrer">'
          f'<img class="theme-light" src="{LOCKUP_LIGHT}" alt="AuScope and NCRIS" width="1919" height="325">'
          f'<img class="theme-dark" src="{LOCKUP_DARK}" alt="AuScope and NCRIS" width="1919" height="325"></a>')
# The footer lock-up's rules. It is drawn 30px tall with the width following the artwork, and where
# its zone is narrower, object-fit:contain keeps the artwork's proportion inside the box. The negative
# block margin makes the anchor's margin box one footer text line, 12.5px at line-height 1.5, so the
# lock-up never sets the height of a footer row.
LOCKUP_HEIGHT = 30
FOOTER_LINE = 12.5 * 1.5
LOCKUP_RULES = (".orglockup{display:inline-block;line-height:0;margin:-5.625px 0}",
                ".orglockup img{height:30px;width:auto;max-width:100%;object-fit:contain}")
# The surfaces whose footer carries the lock-up, by the path a failure message names: every page
# without the big map. index.html's footer right zone is its live counts alone.
LOCKUP_FOOTERS = ("404.html", "about.html", "add-survey.html", "brand.html", "releases.html",
                  "engine/extract/_pages.py")

# The map's corner on index.html: the same pair, unlinked, 44px tall and inset by its own height.
MAP_LOCKUP = (f'<img class="maplock theme-light" src="{LOCKUP_LIGHT}" alt="AuScope and NCRIS" '
              'width="1919" height="325">'
              f'<img class="maplock theme-dark" src="{LOCKUP_DARK}" alt="AuScope and NCRIS" '
              'width="1919" height="325">')

# The switch, verbatim on every surface and in this order. Its first rule is one class, so it ties on
# specificity with .brandmark, which sets display:block on both variants; the switch FOLLOWS that rule
# on every surface, and nothing that selects a variant at a higher specificity may set display.
THEME_RULES = ('.theme-dark{display:none}',
               ':root[data-theme="dark"] .theme-light{display:none}',
               ':root[data-theme="dark"] .theme-dark{display:block}')

# The appearance choice: three radios named "appearance", which src/theme.js reads on change and
# checks to match the stored choice. The same row has two homes, the map page's welcome dialog and
# About's Appearance section, and differs between them only by the fieldset's class. No footer
# carries it.
APPEARANCE_CHOICES = ('<label><input type="radio" name="appearance" value="light"> Light</label>'
                      '<label><input type="radio" name="appearance" value="dark"> Dark</label>'
                      '<label><input type="radio" name="appearance" value="system"> Follow system</label>')
WELCOME_APPEARANCE = ('<fieldset class="introwelcome-appearance"><legend>Appearance</legend>'
                      f'{APPEARANCE_CHOICES}</fieldset>')
ABOUT_APPEARANCE = f'<fieldset class="appearance"><legend>Appearance</legend>{APPEARANCE_CHOICES}</fieldset>'

# The centre line as a reader sees it, and as markup: the organisation's name is its one link, to the
# parent organisation's address, opening in a new tab that is handed no opener and no referrer.
FOOTER_CENTRE = "AusMT is enabled by AuScope · Data licences vary by survey"
FOOTER_CENTRE_MARKUP = ('AusMT is enabled by <a href="https://www.auscope.org.au" target="_blank" '
                        'rel="noopener noreferrer">AuScope</a> · Data licences vary by survey')
FOOTER_LEFT = "MTCAT JSON ↗"


def entities(text):
    """Character references resolved, so three spellings of one separator compare as one."""
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return (text.replace("&middot;", "·").replace("&copy;", "©")
            .replace("&rarr;", "→").replace("&#8599;", "↗"))


def flat(markup):
    """Markup with comments stripped, references resolved and the whitespace between tags removed."""
    markup = re.sub(r"<!--.*?-->", "", markup, flags=re.S)
    markup = re.sub(r">\s+<", "><", entities(markup))
    return " ".join(markup.split())


def token_blocks(text):
    """(light, dark) declarations of a document's token blocks, as dicts. The light block is the
    :root rule that declares --bg; quotes may arrive escaped from a Python source string."""
    light = [b for b in re.findall(r":root\{([^}]*)\}", text) if "--bg:" in b]
    dark = re.findall(r':root\[data-theme=\\?"dark\\?"\]\{([^}]*)\}', text)
    assert len(light) == 1, f"expected one light token block, found {len(light)}"
    assert len(dark) == 1, f"expected one dark token block, found {len(dark)}"
    return _decls(light[0]), _decls(dark[0])


def _decls(body):
    out = {}
    for decl in body.split(";"):
        if ":" in decl:
            name, value = decl.split(":", 1)
            out[name.strip()] = " ".join(value.split())
    return out


# The header, by zone. index.html writes exactly this; every other surface differs only where the
# contract says it may: the name is a link with no heading, Map is a link, the current page's
# control carries class="active", and the engine's pages root-anchor About. The identity zone is the
# mark pair and the name, and the right zone is the tagline.
def header_markup(surface, active=None):
    """The header's inner markup for `surface` ("index", "page" or "engine"), active control named."""
    def cls(name, base=None):
        names = ([base] if base else []) + (["active"] if active == name else [])
        return f' class="{" ".join(names)}"' if names else ""
    if surface == "index":
        identity, nav_map = INDEX_IDENTITY, '<button id="navMap" class="active">Map</button>'
    else:
        identity, nav_map = PAGE_IDENTITY, f'<a id="navMap"{cls("navMap")} href="/">Map</a>'
    about = "/about.html" if surface == "engine" else "about.html"
    return ('<div class="hzone hleft">' + MARK_PAIR + identity + '</div>'
            '<div class="hzone hcenter"><nav>' + nav_map +
            f'<a id="navSurveys"{cls("navSurveys")} href="/surveys">Surveys</a>'
            f'<a id="navCollections"{cls("navCollections")} href="/collections">Collections</a></nav>'
            f'<a{cls("about", "about")} href="{about}">About</a></div>' + RIGHT_ZONE)


def tokens(markup):
    """Markup as a sequence of (kind, tag, attributes, text) tokens: comments dropped, attributes
    sorted, whitespace-only text dropped and the rest collapsed. Two headers compare equal exactly when
    a reader and a browser would see the same elements, attributes and words in the same order."""
    from html.parser import HTMLParser

    class _T(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out = []

        def handle_starttag(self, tag, attrs):
            self.out.append(("start", tag, tuple(sorted((k, v or "") for k, v in attrs)), ""))

        def handle_endtag(self, tag):
            self.out.append(("end", tag, (), ""))

        def handle_data(self, data):
            if data.strip():
                self.out.append(("text", "", (), " ".join(data.split())))

    p = _T()
    p.feed(markup)
    return p.out


def header_inner(text):
    """The markup between a document's <header ...> and </header>, or None when it carries none."""
    m = re.search(r"<header\b[^>]*>(.*?)</header>", text, re.S)
    return m.group(1) if m else None
