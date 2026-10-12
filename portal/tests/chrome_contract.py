"""The site chrome every surface wears, stated once for the pins that hold the surfaces to it.

The static pages and the engine's generated pages each carry their own copy of this chrome, because
the portal ships as classic static pages with no template step. These literals are the contract those
copies are compared against: the appearance tokens, the header's identity and lock-up, the footer's
regions and the appearance control. A pin compares a surface with these strings rather than with
another surface, so two copies that drift together still fail.
"""
import re

# The two token blocks, light (the AuScope house style) and dark. Every page declares both verbatim.
LIGHT = {
    "--bg": "#D8D9D7", "--surface": "#FFFFFF", "--surface-2": "#F2F3F2", "--line": "#CED4DA",
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

MARK_LIGHT = "/vendor/auscope/auscope-mark.svg"
MARK_DARK = "/vendor/auscope/auscope-mark-white.svg"
MARK_PAIR = (f'<img class="brandmark theme-light" src="{MARK_LIGHT}" alt="AuScope" width="30" height="30">'
             f'<img class="brandmark theme-dark" src="{MARK_DARK}" alt="AuScope" width="30" height="30">')
MARK_RULE = ".brandmark{height:30px;width:30px;display:block;flex:none}"

# The lock-up is the AuScope brand kit's own colour and white PNGs, named at their intrinsic 1919 by 325
# and drawn 40px tall, the height of the view tabs, with the width following the artwork.
LOCKUP_LIGHT = "/vendor/auscope-ncris-colour.png"
LOCKUP_DARK = "/vendor/auscope-ncris-white.png"
LOCKUP_PIXELS = (1919, 325)
LOCKUP = ('<a class="orglockup" href="https://www.auscope.org.au" target="_blank" rel="noopener noreferrer">'
          f'<img class="theme-light" src="{LOCKUP_LIGHT}" alt="AuScope and NCRIS" width="1919" height="325">'
          f'<img class="theme-dark" src="{LOCKUP_DARK}" alt="AuScope and NCRIS" width="1919" height="325"></a>')
LOCKUP_RULES = (".orglockup{display:block;line-height:0}",
                ".orglockup img{height:40px;width:auto;max-width:100%}")

# The switch, verbatim on every surface. Its first rule ties on specificity with any one-class rule
# that also sets display, so it must follow them; nothing that selects a variant may outrank it.
THEME_RULES = ('.theme-dark{display:none}',
               ':root[data-theme="dark"] .theme-light{display:none}',
               ':root[data-theme="dark"] .theme-dark{display:block}')

TAGLINE = "Australia's Magnetotelluric Data Portal"
H1_TEXT = "AusMT - Australia's Magnetotelluric (MT) Data Portal"
INDEX_IDENTITY = ('<h1 class="brandh1"><span class="wordmark">AusMT</span>'
                  '<span class="visually-hidden"> - Australia\'s Magnetotelluric (MT) Data Portal</span></h1>')
PAGE_IDENTITY = '<a class="wordmark" href="/">AusMT</a>'

THEMECTL = ('<div class="themectl" role="group" aria-label="Appearance"><button type="button" '
            'data-theme-choice="light" aria-pressed="true">Light</button><span class="themesep">·</span>'
            '<button type="button" data-theme-choice="dark" aria-pressed="false">Dark</button></div>')

FOOTER_CENTRE = ("AusMT is enabled by AuScope · www.auscope.org.au · Data licences vary by survey")
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
# contract says it may: the identity is a link with no heading, Map is a link, the current page's
# control carries class="active", and the engine's pages root-anchor About.
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
    return ('<div class="hzone hleft">' + MARK_PAIR + identity + f'<div class="tagline">{TAGLINE}</div></div>'
            '<div class="hzone hcenter"><nav>' + nav_map +
            f'<a id="navSurveys"{cls("navSurveys")} href="/surveys">Surveys</a>'
            f'<a id="navCollections"{cls("navCollections")} href="/collections">Collections</a></nav>'
            f'<a{cls("about", "about")} href="{about}">About</a></div>'
            '<div class="hzone hright">' + LOCKUP + '</div>')


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
