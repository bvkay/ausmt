# Why the portal looks the way it does

AusMT is an AuScope service, and its pages wear AuScope's house style. The decision is Owner ruling
2026-10-12: the AuScope identity opens every page, the house style is the default appearance, and the
navy palette the portal grew up with stays available as a dark theme. This page explains the choices
that ruling settled. The tokens, the rules and the pins that hold them are in
[Portal internals](../reference/portal-internals.md).

## Two themes, one set of roles

The light theme is the AuScope Style Guide's palette: a grey page ground, white cards, Royal Blue
headings, links and active controls. The dark theme is the navy palette, unchanged, with the coral
accent. A visitor chooses in the footer of any page, or from the welcome popup on the map, where
"Follow system" is offered too. The choice is remembered in the browser and applied before the first
paint, so a returning visitor never sees a flash of the other theme.

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

Every header opens with the AuScope mark, with AusMT's name and tagline beside it, and closes with the
AuScope and NCRIS lock-up, linked to AuScope. The AusMT symbol stays AusMT's product mark: the
documentation sidebar and the social card carry it, and the brand page offers it for talks and papers.
The browser tab and the home-screen icons carry the AuScope mark, like the header.

The header carries four controls: Map, Surveys, Collections and About. Contributing a survey is
reached from About, where a contributor reads what a submission involves before starting one.

The footer states who enables AusMT and that data licences vary by survey. It carries the
machine-readable catalogue link on the left and, on the right, the map's live counts where there is a
map, then the appearance control.

## The mark on the map

The map carries the AuScope mark in its bottom-right corner, because the map is what people screenshot
into talks and reports and a screenshot keeps neither the header nor the footer. The mark keeps the
style guide's breathing space, one logo height on every side, so the collapsed map credit moved to the
top-right corner. The basemap follows the theme, light or dark, and the station dots take an edge that
reads on either.
