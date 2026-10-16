# Why the portal looks the way it does

AusMT is an AuScope service, and its pages wear AuScope's house style. The decision is Owner ruling
2026-10-12: the AuScope identity opens every page and the house style is the portal's appearance.
This page explains the choices that ruling and the decisions after it settled. The tokens, the rules
and the pins that hold them are in [Portal internals](../reference/portal-internals.md).

## One appearance

The portal has one appearance, the AuScope Style Guide's palette: a grey page ground, white cards,
Royal Blue headings, links and active controls (Owner decision 2026-10-15). The house style reads as
the professional face of an AuScope service, and a second appearance was a second set of colours
every page, map and figure had to be checked against.

Until that decision the navy palette the portal grew up with stayed available as a dark appearance,
chosen in the map's welcome popup or on the About page and remembered in the browser. The dark
appearance, its chooser and the script that applied it are gone. The welcome popup keeps its tour
offer, its browse button and its "Don't show this again" box, and About ends at its Documentation
section. A browser that remembered the dark choice is unaffected: nothing reads the stored choice
any more, so every visitor sees the house style from the first paint, with nothing to flash.

The stylesheets name colours by role (page ground, surface, line, text, heading, accent) rather than
by hue, so a new page takes the house style from the roles rather than picking colours of its own.

## The data colours are data, not chrome

The four data types are coloured from the house-style ramp: long period blue, broadband amber, AMT
green and GDS magenta. The colours were chosen to stay separable for red-green colour-blind readers
and to stay clear of the accent, the page ground and the card surface. The plot curves and the
collection colours are data too, and keep their own colours.

## AuScope's identity in the chrome

Every header opens with the AuScope mark and AusMT's name, and closes with the tagline (Owner
decision 2026-10-13). The mark is the brand kit's vector icon, 36px square, in the kit's colours.
The name beside it is set at the AuScope logo's own proportions, scaled to that mark: the gap from
mark to name is the logo's, 12px; the type is 24.5px, so its capitals stand 0.48 of the mark's
height; and "Aus" is heavy against a light "MT", as "Au" is heavy against "Scope" in AuScope's own
logo. The two read as a pair, an AuScope service and its name. The tagline, "Magnetotelluric Data
Discovery & Access", sits on one line at the right of the header; where a narrow window leaves it
less room than that line, it ends in an ellipsis rather than running under the controls. The header
is 57px tall on any window wider than 900px, the height its tabs set.

The name is set in Calibre, AuScope's typeface. AusMT is an AuScope sub-domain, and AuScope's licence
for Calibre covers it, so the name's type leads with Calibre (Owner decision 2026-10-13). The font
files follow in a later change; until they are served, a reader who does not have Calibre installed
sees the name in the site's own sans-serif, at the same size and weights.

The AuScope and NCRIS lock-up closes the footer at the bottom right of every page without the big
map: About, Brand, Releases, Add survey, the page-not-found page, and every survey, station and
collection page (Owner decision 2026-10-13). It links AuScope's home page in a new tab, as the
footer's line does. It is drawn 30px tall and set so that it does not make the footer any taller on
a wider window; on a phone-sized window, where the footer scrolls with the page, it takes a line of
its own, and on the surveys catalogue the counts beside it can wrap to a second line. On the map
page the lock-up is in the map's corner instead, and the footer keeps its live counts.
About also shows the lock-up in its "Who enables AusMT" section.

The AusMT symbol stays AusMT's product mark: the documentation sidebar and the social card carry it,
and the brand page offers it for talks and papers. The browser tab and the home-screen icons carry
the AuScope mark, and so do the collection maps.

The files are the 2025 AuScope brand kit's own (Owner decision 2026-10-13). The kit's mark carries
Tasmania; the cuts first taken from the style guide's page did not, so they were retired rather than
corrected by hand. The mark is the kit's vector icon, in the colours the kit file states, and the
lock-up is the kit's colour PNG, used as published. The kit's white files ship beside them for
the link-preview cards, which keep their navy ground; no page draws them.

The header carries four controls: Map, Surveys, Collections and About. Contributing a survey is
reached from About, where a contributor reads what a submission involves before starting one.

## Phones and small tablets

On a window 900px wide or narrower, the header is one row, 52px tall: the AuScope mark and AusMT's
name at the left, and the section tabs at the right, each at least 44px square so a thumb can hit it
(Owner decision 2026-10-14). The tagline is hidden. While the map page shows the map the tabs are
Surveys and Collections, with no Map tab, because the screen is the map; when it shows its own lists
of surveys or collections the Map tab comes back, as the way back to the map. The Surveys,
Collections, About and other static pages show Map, Surveys and Collections in the same row. About
leaves the header at these widths and becomes a link at the end of the map page's sheet, and on the
other pages, and on the map page's lists, a link beside the catalogue link at the left of the
footer. The row is the same on every page, as
the desktop header is.

900px is the line between the two layouts (Owner decision 2026-10-16). Above it the side-by-side map
and panel stay exactly as they are on a desktop. Below it the map comes first: the map fills the
screen under the header, and the panel lives in a sheet that slides up over it, with three heights a
thumb can pick: a peek that shows only the counts and Browse and Select, half the screen, and the
whole screen below the header (Owner decision 2026-10-14). A station's details open in the same sheet,
in place of the filters, with a Back control that returns to them. From 761px to 900px the sheet is a
floating card at the bottom left, so the map stays in view beside it. The footer leaves the screen on
a phone and its contents, the catalogue link and the line naming AuScope, end the sheet beside the
About link. On phones and in the tablet card, selecting stations means what is on the screen rather
than drawing a shape with one finger (Owner decision 2026-10-16): "Select what's in view" takes every
station the map shows that passes the filters, with the number it would take beside it, and in Select
a tap on a station adds it or takes it out instead of opening its details. The selection is listed
in the sheet, a row per station with a control that removes it, above the downloads, and a selected
station is ringed in the colour a drawn selection shape is drawn in. The drawing tools, the map's
toolbar and the panel's two draw buttons, are hidden at these widths, and the downloads are the
desktop's, over the same stations.

On a touch screen every control a finger is expected to hit is at least 44px in each direction,
and text inputs are 16px, the size below which iOS Safari zooms the page when one is tapped. Pages
are drawn edge to edge and keep their content clear of a phone's notch, rounded corners and home
indicator. None of this changes what a desktop window with a mouse shows.

The footer states who enables AusMT and that data licences vary by survey: "AusMT is enabled by
AuScope · Data licences vary by survey". AuScope's name is the line's link and opens AuScope's
home page in a new tab; the address is not printed beside it (Owner decision 2026-10-13). It carries
the machine-readable catalogue link on the left and, on the right, the map's live counts on the map
page and the lock-up everywhere else, after the counts on the surveys catalogue.

## The lock-up on the map

The map carries the AuScope and NCRIS lock-up in its bottom-right corner (Owner decision 2026-10-13),
because the map is what people screenshot into talks and reports and a screenshot keeps neither the
header nor the footer; the lock-up names both AuScope and NCRIS where the mark alone named AuScope.
It is 44px tall and keeps the style guide's breathing space, one logo height on every side, so the
collapsed map credit sits in the top-right corner. It is drawn at 80 percent opacity; opacity is the
only change made to it, and the file keeps the brand kit's own colours, with no filter, tint or
blend. On a narrow map the legend in the opposite corner can reach it, and the legend then sits on
top so it stays readable; on a phone-sized window the lock-up is not drawn. The basemap is the light
flavour, and the station dots take a near-black edge that reads on it.
