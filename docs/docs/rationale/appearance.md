# Why the portal looks the way it does

AusMT is an AuScope service, and its pages wear AuScope's house style. The decision is Owner ruling
2026-10-12: the AuScope identity opens every page, the house style is the default appearance, and the
navy palette the portal grew up with stays available as a dark theme. This page explains the choices
that ruling settled. The tokens, the rules and the pins that hold them are in
[Portal internals](../reference/portal-internals.md).

## Two themes, one set of roles

The light theme is the AuScope Style Guide's palette: a grey page ground, white cards, Royal Blue
headings, links and active controls. The dark theme is the navy palette, unchanged, with the coral
accent. A visitor chooses Light, Dark or Follow system in one of two places: the welcome popup on
the map, which a first visit opens, and the Appearance section of the About page, which every
header links, so a visitor who dismissed the popup can still change it. The choice is remembered in
the browser and applied before the first paint, so a returning visitor never sees a flash of the
other theme.

The footer carries no appearance control (Owner decision 2026-10-13). The Light and Dark switch
left the right of every footer, and the choice keeps the two homes above: the welcome popup for a
first visit, and the About page for every visit after it, since About is the page every header
reaches.

The stylesheets name colours by role (page ground, surface, line, text, heading, accent) rather than by
hue, so one set of rules serves both themes and a new page cannot pick a colour that only works in one
of them.

## The data colours do not change with the theme

The four data types are coloured from the house-style ramp: long period blue, broadband amber, AMT
green and GDS magenta. The ramp is deliberately the same in both themes. A legend that changed meaning
with the theme would make a screenshot taken in one theme unreadable beside a figure made in the other,
and the colours were chosen to stay separable for red-green colour-blind readers in both. The plot
curves and the collection colours are data too, and keep their own colours.

## AuScope's identity in the chrome

Every header opens with AusMT's name and tagline and closes with the AuScope and NCRIS lock-up,
linked to AuScope. The lock-up is the header's only AuScope presence: the AuScope mark that stood
beside AusMT's name left the header (Owner decision 2026-10-13), so the identity zone holds AusMT's
name and tagline alone and the lock-up, which names AuScope and NCRIS and links AuScope, is the one
AuScope image in it. The AusMT symbol stays AusMT's product mark: the documentation sidebar and the
social card carry it, and the brand page offers it for talks and papers. The browser tab and the
home-screen icons carry the AuScope mark, and so do the map's corner and the collection maps.

The files are the 2025 AuScope brand kit's own (Owner decision 2026-10-13). The kit's mark carries
Tasmania; the cuts first taken from the style guide's page did not, so they were retired rather than
corrected by hand. The mark is the kit's vector icon, in the colours the kit file states, and the
lock-up is the kit's colour and white PNGs, used as published. The lock-up is drawn as tall as the
Map, Surveys and Collections tabs beside it, so the right of the header lines up with the controls
and the header is no taller than the tabs make it.

The header carries four controls: Map, Surveys, Collections and About. Contributing a survey is
reached from About, where a contributor reads what a submission involves before starting one.

The footer states who enables AusMT and that data licences vary by survey: "AusMT is enabled by
AuScope · Data licences vary by survey". AuScope's name is the line's one link and opens AuScope's
home page in a new tab; the address is not printed beside it (Owner decision 2026-10-13). It carries
the machine-readable catalogue link on the left and, on the right, the map's live counts where there
is a map; elsewhere the right of the footer is empty, which keeps the line centred on the page.

## The mark on the map

The map carries the AuScope mark in its bottom-right corner, because the map is what people screenshot
into talks and reports and a screenshot keeps neither the header nor the footer. The mark keeps the
style guide's breathing space, one logo height on every side, so the collapsed map credit moved to the
top-right corner. It is drawn at 80 percent opacity (Owner decision 2026-10-13); opacity is the only
change made to it, and both files keep the brand kit's own colours, with no filter, tint or blend. The
basemap follows the theme, light or dark, and the station dots take an edge that reads on either.
