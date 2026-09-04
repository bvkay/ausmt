# Portal internals

The portal ships its markup, its stylesheet and its scripts to every visitor, so a comment in those
files is part of the download. The house rule keeps a comment there to the constraint it states, in
one or two sentences; where the reasoning behind a constraint runs longer than that, the reasoning
lives here and the file carries the constraint and a pointer to this page.

This is a reference for someone editing the portal, not a description of the served data. Each
section is one shipped file, and each entry under it is one note, in the order the file carries
them. Nothing here is a contract: the machine-readable surfaces are in the rest of this Reference
section, and the pins named in these notes are the authority on the behaviour they hold.

## portal/index.html

#### DUPLICATED verbatim in about.html and add-survey.html: the five surface ...

```text
DUPLICATED verbatim in about.html and add-survey.html: the five surface tokens must stay identical
across all three. --copper carries the Tangerine accent; the token name does not follow it.
```

#### --no is rendered as TEXT on --panel (5.98:1) and --panel-2 (5.00:1), so ...

```text
--no is rendered as TEXT on --panel (5.98:1) and --panel-2 (5.00:1), so it must stay above the
WCAG AA 4.5:1 floor on both. Hue-preserving danger red, distinct from --part amber and --copper.
```

#### Three-zone header

```text
Three-zone header. The side zones must take equal ZERO-basis shares (flex:1 1 0, min-width:0) or
each grows with its own content and the centred tabs land at a different x per view; pinned by
tests/test_header_geometry_parity.py.
```

#### The AusMT mark (vendor/brand/ausmt-mark.svg, from tools/gen_brand.py) ...

```text
The AusMT mark (vendor/brand/ausmt-mark.svg, from tools/gen_brand.py) is a fixed 30x30 box, so it
joins the zero-basis .hleft zone without moving the centre tabs. Stated character-identically in
engine/extract/_pages.py's sheet; pinned by tests/test_header_geometry_parity.py.
```

#### The ACTIVE view is a filled copper box with dark text (#16110b on ...

```text
The ACTIVE view is a filled copper box with dark text (#16110b on --copper = 6.44:1, AA), and every
     view control keeps a 40px click target. Inactive buttons read as buttons, not muted links.
The static header and this one must agree on the container's wrap mode: nowrap and wrap hand
     zero-basis flex children different resolved widths. Pinned pairwise by
     tests/test_header_geometry_parity.py.
```

#### The AuScope mark, top right of the MAP and nowhere else: a screenshot ...

```text
The AuScope mark, top right of the MAP and nowhere else: a screenshot carries no footer, so this is
the attribution that travels with the image, at the brand guide's clear space (32px) with neither
tint nor reduced opacity. pointer-events:none and a z-index below Leaflet's control and popup
layers keep it out of hit testing.
```

#### The map's attribution, collapsed to one glyph

```text
The map's attribution, collapsed to one glyph. The credit is a licence term and stays with the map,
because only the layer that is drawing knows which provider to name, and the 240px cap keeps the
opened text clear of the legend at 560px of map. Shared character for character with
add-survey.html; pinned by tests/test_map_attribution.py.
```

#### flex-shrink:0 is load-bearing: #filterPane is a column flex, so a tall ...

```text
flex-shrink:0 is load-bearing: #filterPane is a column flex, so a tall mode pane squashes this
control, and .seg clips its overflow, so it collapses silently to its 2px borders and leaves the
rail a one-way door into Select and download.
```

#### The tree fills the rail's remaining height and scrolls INTERNALLY; the ...

```text
The tree fills the rail's remaining height and scrolls INTERNALLY; the rail must NOT gain a second
outer scrollbar. The flex chain that allows it (each ancestor min-height:0) is on #browseMode and
treeSection below.
```

#### Disclosure carets are a separate click target inside each label row ...

```text
Disclosure carets are a separate click target inside each label row, and the handler preventDefaults
so the label never activates its checkbox. .coll and .treegroup are shared between .tree and
.collgroup.
```

#### The three link sites must be given the site accent, or they take the ...

```text
The three link sites must be given the site accent, or they take the UA's near-invisible dark blue
on the navy tiles and go purple once followed. :visited is stated explicitly, because an identifier
is not consumed by being clicked.
```

#### min-width is plots.js's design width (W=372), so the modal svg can ...

```text
min-width is plots.js's design width (W=372), so the modal svg can never render narrower than the
drawer's and shrink its axis text; the svg's matching viewBox keeps the aspect ratio at width:100%.
```

#### FOUR across at the cap and at a plain 1500px viewport, never a fifth ...

```text
FOUR across at the cap and at a plain 1500px viewport, never a fifth: the 352px floor packs four
into 1460px of grid content. The floor is min(352px,100%) because a bare minimum cannot shrink and
a 375px phone would scroll sideways.
```

#### One footer, three regions: the MTCAT link LEFT, the AuScope ...

```text
One footer, three regions: the MTCAT link LEFT, the AuScope acknowledgement CENTRE, the
AuScope-NCRIS lockup RIGHT. THIS IS THE MASTER RULE SET, carried character for character by every
other portal document and by engine/extract/_pages.py's _CSS, so nothing here may be tuned for one
page. The equal zero-basis side zones, the two queries on the FOOTER's own content width and the
lockup's max-width cap are each load-bearing; pinned by tests/test_footer_regions.py.
```

#### The hand-off snackbar sits ABOVE #toast so the two can coexist (a ...

```text
The hand-off snackbar sits ABOVE #toast so the two can coexist (a hand-off can follow an export
toast within its dwell). It carries at most one action button; it never carries a progress bar.
```

#### This sheet must carry NO rule for .introoverlay, .intropanel ...

```text
This sheet must carry NO rule for .introoverlay, .intropanel, .introclose, .introhero, .introtiles,
.introtile or .introtour, and no element here may carry those ids or classes; pinned by
tools/interaction_test.js.
```

#### --- guided tour spotlight (tour.js) --- The dim is JS-driven (tour.js ...

```text
--- guided tour spotlight (tour.js) ---
The dim is JS-driven (tour.js TOUR_DIM): on a targeted step the backdrop stays TRANSPARENT and the
     spot's box-shadow supplies it, so the element shows through the cutout. z-order backdrop 3000 <
     spot 3001 = leader < card 3002.
```

#### ===== map page and sidebar structure ...

```text
===== map page and sidebar structure ==============================================
Wrapping the rail sections in two containers costs them aside.filters' column gap, so it is
     restored here.
```

#### The Browse pane and its tree section are the flex chain that lets #tree ...

```text
The Browse pane and its tree section are the flex chain that lets #tree flex-fill and scroll
internally: each level needs min-height:0 to shrink below its content, or the tree pushes the rail
into an outer scrollbar instead.
```

#### width:36px!important must beat BOTH the 363px base rule and the inline ...

```text
width:36px!important must beat BOTH the 363px base rule and the inline width the resizer writes,
     which is not !important.
Anchored BOTTOM-right (margin-top:auto pushes it past the flex-filling pane and tree). The rail
     itself never scrolls, so it stays visible.
```

#### The four TYPE rows are real toggle BUTTONS proxying the rail's ...

```text
The four TYPE rows are real toggle BUTTONS proxying the rail's #typeBoxes checkboxes (main.js
toggleLegendType), so the UA chrome is stripped back to the .legrow look and the affordances a
control owes are added.
```

#### The metric scale bar, re-parented out of the Leaflet corner (main.js ...

```text
The metric scale bar, re-parented out of the Leaflet corner (main.js buildScaleBar) under its OWN
class, so the legend's dot and parenting pins are untouched. position:static undoes Leaflet's
absolute corner placement.
```

#### text-shadow:none is the point: Leaflet ships this control with a WHITE ...

```text
text-shadow:none is the point: Leaflet ships this control with a WHITE text-shadow, which is a halo
around near-white text on this dark panel. Weight drops to 500 for the same reason.
```

#### Twin of the static collection page's .collmap/.collmark rule ...

```text
Twin of the static collection page's .collmap/.collmark rule (engine/extract/_pages.py). The panel
is capped at the SVG's own width, so the corner the mark is pinned to is the MAP's, not the
column's.
```

#### The AusMT mark, not an organisation mark: AusMT is what this header ...

```text
The AusMT mark, not an organisation mark: AusMT is what this header IDENTIFIES, so no header on
this site carries a second mark of any kind. Same markup and same rule on every surface.
```

#### Surveys and Collections are served as pages, so these two controls are ...

```text
Surveys and Collections are served as pages, so these two controls are LINKS; Map stays a
<button>, because it is the application itself. The ids are unchanged, so the header-parity pins
and the active-state toggles address the same three elements.
```

#### The header's right zone carries only the live counts; the MTCAT ...

```text
The header's right zone carries only the live counts; the MTCAT machine-readable link lives in
the footer's bottom-left.
One SHELL, a contextual SLOT: .counts is the same element in the same place on every view and
countSlot's content is what changes (filters.js updateCounts). The markup here is the MAP form.
```

#### The single "Recently added" surface is the surveys-view #recentStrip: a ...

```text
The single "Recently added" surface is the surveys-view #recentStrip: a rail copy would un-hide
it on every view and leak onto Surveys and Collections.
The Collections group renders here as its OWN block, above the tree header. buildTree()
(filters.js) fills #collGroup when the boot data has collections; #collGroup:empty hides it
otherwise.
```

#### Availability is a single-select VIEWING filter beside data type

```text
Availability is a single-select VIEWING filter beside data type. The four level options filter on
ts_access.json membership and are DISABLED until the index settles (filters.js paintAvailSelect),
because the level filter is never live over data that has not arrived.
```

#### Discoverability: these arm the SAME rectangle/polygon draw handlers as ...

```text
Discoverability: these arm the SAME rectangle/polygon draw handlers as the map's top-left
toolbar icons (map.js armDraw); .armed mirrors the shared armedDrawMode both surfaces read.
```

#### The DOWNLOAD block

```text
The DOWNLOAD block. One scope rule, no modes: every count and size reflects the current SELECTION
when one exists, else the filtered corpus, and the scope line states which. Level 2 is served by
AusMT; the time-series rows are hand-offs (/go/ts/ 302s) to the archive that holds the files.
```

#### The rail collapse control toggles the 36px icon rail, its state ...

```text
The rail collapse control toggles the 36px icon rail, its state persisted in localStorage. As the
last rail child with margin-top:auto it stays anchored to the bottom, visible while the tree
scrolls.
```

#### Discovery controls: search, sort, live count, facet chips, a ...

```text
Discovery controls: search, sort, live count, facet chips, a compact-list toggle and
clear-filters, all wired in drawer.js where the state lives. There is deliberately NO sort or
facet for the automated completeness check, which is never a ranking.
```

#### A set year hides every undated survey, which is a SILENT exclusion that ...

```text
A set year hides every undated survey, which is a SILENT exclusion that a title attribute states
only to a reader with a mouse. Last child of the bar and full-width, so it wraps without
breaking the controls' row.
```

#### One wrapping line BELOW the discovery controls, so this reads as a ...

```text
One wrapping line BELOW the discovery controls, so this reads as a shortcut into the grid rather
than a preamble to it. The 30-day build-window rule that decides what it lists is untouched.
```

#### Dim backdrop behind the drawer on the Surveys, Collections and ...

```text
Dim backdrop behind the drawer on the Surveys, Collections and collection views, never the map
view. Click-closes the drawer, and sits beneath the drawer and its resize handle (z-index).
```

#### First-visit welcome popup: role=dialog, focus-managed, closed by Esc ...

```text
First-visit welcome popup: role=dialog, focus-managed, closed by Esc, click-out or "Browse
immediately". "Don't show this again" gates persistence via the localStorage key; ?tour=1 is the
on-demand way back into the tour.
The wget dialog: the command is SHOWN, scrollable, with its run instructions, before anything
lands on a clipboard. Filled and wired by exports.js showWgetDialog().
```

#### Per-platform tabs, the DETECTED platform pre-selected: wget -P ...

```text
Per-platform tabs, the DETECTED platform pre-selected: wget -P <survey>/<level> on Linux, curl
with explicit -o paths elsewhere, so same-named files land in their own directories. The Windows
tab must name curl.exe in full, because PowerShell aliases bare curl away.
role=tab and aria-selected on each button, set by _paintWgetTab alongside the .on class: a
tablist of plain buttons is an ARIA contract the assistive layer cannot read.
```

#### LEFT

```text
LEFT. The machine-readable MTCAT link, the same document from every page on both surfaces.
The honest link text + href/title are kept verbatim.
```

#### CENTRE

```text
CENTRE. Who enables AusMT, then the attribution and the licence note. The URL text is the one link
in the line, so it says where it goes without a title attribute; the year is a literal here and in
the engine's shell, because a year that moved on rebuild would differ across the tree.
```

#### RIGHT

```text
RIGHT. The parent organisation's lockup, linked where the centre's URL text links. The image is
same-origin and vendored, so stating the relationship takes no runtime dependency on its host.
```

#### PROGRESS BELONGS TO THE BROWSER: the 302 hands the bytes ...

```text
PROGRESS BELONGS TO THE BROWSER: the 302 hands the bytes browser-to-archive, CORS forbids an
in-page fetch of the payload, and a multi-GB Blob would be a proxy in disguise. So this page carries
no progress bar, no download-manager panel and no completion claim.
```

## portal/about.html

#### Search snippet and link preview

```text
Search snippet and link preview. The description is this page's OWN lede, word for word: an
invented summary is a second wording of the page that nobody maintains. Preview crawlers resolve
nothing relative, so og:url and og:image are absolute.
```

#### Uniform chrome: the three-zone header below is index.html's, so About ...

```text
Uniform chrome: the three-zone header below is index.html's, so About carries the same chrome as
the portal. This page is STATIC, so the centre items are links rather than app buttons and the
right zone carries catalogue totals rather than live map state; the sticky positioning is
About-specific, because this page scrolls.
```

#### The AusMT mark, generated by tools/gen_brand.py, is the header identity ...

```text
The AusMT mark, generated by tools/gen_brand.py, is the header identity on every surface of the
site. Same file, same markup and character-identical rule on index.html, brand.html and the
generated pages (engine/extract/_pages.py).
```

#### flex-wrap is a term of the header's HEIGHT, not a detail of the nav ...

```text
flex-wrap is a term of the header's HEIGHT, not a detail of the nav: the three tabs hold a
112px floor each, so on a narrow viewport a nowrap container keeps them on one row and
overruns the zone instead of stacking. Character-identical to the other four surfaces.
```

#### Centre-zone nav items are links on this static page (index uses ...

```text
Centre-zone nav items are links on this static page (index uses <button>s that switch app views),
matching index's nav: equal-width bordered boxes, 40px targets and a copper-filled active state
(#16110b on --copper = 6.44:1). None of Map/Surveys/Collections is the current page here, so the
current page is marked on its own .about link instead.
```

#### The header right zone's mono stats block, copied verbatim from ...

```text
The header right zone's mono stats block, copied verbatim from index.html's .counts so the two
headers render identically. The .corpus marker distinguishes corpus totals from index's live app
state, at a glance and in the chrome pins.
```

#### Matches index.html: at narrow widths the three header zones stack ...

```text
Matches index.html: at narrow widths the three header zones stack full-width and left-align, so the
centred nav / right-aligned mtcat link don't read as stranded fragments once they wrap.
```

#### THE IN-PAGE ANCHOR OFFSET FOLLOWS THE HEADER

```text
THE IN-PAGE ANCHOR OFFSET FOLLOWS THE HEADER. The header is sticky, so an anchor that scrolls its
section to y=0 puts the heading underneath it and scroll-margin-top is the clearance. One number
will not do: the header WRAPS as the viewport narrows, is 220px tall at 375px, and does not shrink
monotonically, so each band below carries the TALLEST header in its own range (overshooting drops
a heading a few pixels low, undershooting hides it). These are measurements of this header's
content at this font stack: anything that changes its wording, its nav or its zones moves the wrap
points and the ladder must be re-measured, and no source-read pin can see the header get taller.
tests/test_about_uniform_chrome.py holds the shape and the values at 375px and 1280px.
```

#### The AuScope-NCRIS lockup in the body, the same committed file every ...

```text
The AuScope-NCRIS lockup in the body, the same committed file every footer carries. The width is
capped HERE and not in the file, because the committed raster is 1919px wide; object-fit holds the
mark's proportions wherever that cap bites.
```

#### One footer, three regions: the MTCAT machine-readable link LEFT, the ...

```text
One footer, three regions: the MTCAT machine-readable link LEFT, the AuScope acknowledgement
CENTRE, the AuScope-NCRIS lockup RIGHT. The rule set below is index.html's, character for
character, where the zone geometry and the two container states are stated once;
tests/test_footer_regions.py holds all seven surfaces identical, so an edit here that is not an
edit there fails. STICKY, not fixed: it keeps its own box in flow, so the last line of the page
is never hidden under it, which is why body is a viewport-tall column and main takes its free
space. Below 560px of viewport it would cover most of a phone screen, so it returns to flow.
```

#### The AusMT mark, not an organisation mark: AusMT is the thing this ...

```text
The AusMT mark, not an organisation mark: AusMT is the thing this header IDENTIFIES, so it
opens the header and no header on this site carries a second mark of any kind. The AuScope
relationship is stated in the footer and in About's Who enables AusMT, which is where a
reader asks it. Same file, same markup and same rule on every surface wearing this chrome.
```

#### Each item has its own destination: Map is the SPA root, and Surveys and ...

```text
Each item has its own destination: Map is the SPA root, and Surveys and Collections are the
prerendered index pages the engine emits and the box serves at those exact paths. They carry
index's navMap/navSurveys/navCollections ids so the two headers are comparable
element-for-element (the header-parity pin). The TAG differs by necessity: on index these are
<button>s that switch app views in place, and this page is static.
```

#### The right zone carries the corpus-totals block, not index's live app ...

```text
The right zone carries the corpus-totals block, not index's live app state: this page has no map,
filter or selection to report, so the three live ids (nVis/nSel/nTot) stay off it. corpus-stats.js
reveals the block only when both documents resolve to a non-empty corpus, so a file:// page, an
unpublished deployment or an empty build shows nothing rather than a fabricated total.
```

#### About is the two-minute front door: it answers seven questions and then ...

```text
About is the two-minute front door: it answers seven questions and then hands off. Every deeper
topic is a link into the docs site, and every target was fetched and returned 200 before it was
written here. The #howto and #api ids are kept, because other surfaces deep-link them.
```

#### The no-hosting claim and the hand-off are ONE statement: the no-hosting ...

```text
The no-hosting claim and the hand-off are ONE statement: the no-hosting half alone reads as a dead
end, and stating the pair twice gives a reader two wordings of one fact to reconcile.
tests/test_about_copy_batch.py holds both halves, and holds them to being said once.
```

#### The machine-contract paragraph

```text
The machine-contract paragraph. Everything it asserts is read off engine/schema/mtcat.schema.json,
the file it links, or off the emitter that writes the document, and is pinned test-side against
both.
```

#### The releases page's ONLY route in, which is what keeps the citable ...

```text
The releases page's ONLY route in, which is what keeps the citable snapshots reachable; the
releases-page pins hold it here. No version chip: this is a route, not the running build's
identity.
```

#### The site's ONE footer, three regions, the same strings and the same ...

```text
The site's ONE footer, three regions, the same strings and the same targets index.html
carries. A sibling of main, not a child of it: it is the page's bottom edge, and only a
body-level footer is a contentinfo landmark.
```

#### CENTRE

```text
CENTRE. Who enables AusMT, then the attribution and the licence note. The URL text is the
one link in the line. The year is a literal, the mechanism both surfaces use.
```

#### A SEPARATE FILE, not an inline block: the deployed CSP for every page ...

```text
A SEPARATE FILE, not an inline block: the deployed CSP for every page except add-survey.html is
script-src 'self' with no 'unsafe-inline' (deploy/docker/caddy/Caddyfile, @strictPages), so an
inline script here would be blocked in production.
```

## portal/add-survey.html

#### The AusMT mark, generated by tools/gen_brand.py, is the header identity ...

```text
The AusMT mark, generated by tools/gen_brand.py, is the header identity on every surface of the
site. Same file, same markup and character-identical rule on index.html, brand.html and the
generated pages (engine/extract/_pages.py).
```

#### AA text contrast on the status-chip tints: the PASS tint is light ...

```text
AA text contrast on the status-chip tints: the PASS tint is light enough for --ok text to clear
4.5:1 (4.65:1), the FAIL tint for --no text (4.74:1) and the WARNING tint for --part (4.56:1).
```

#### One footer, three regions: the MTCAT machine-readable link LEFT, the ...

```text
One footer, three regions: the MTCAT machine-readable link LEFT, the AuScope acknowledgement
CENTRE, the AuScope-NCRIS lockup RIGHT. The rule set below is index.html's, character for
character, where the zone geometry and the two container states are stated once;
tests/test_footer_regions.py holds all seven surfaces identical. STICKY, not fixed, so it keeps
its box in flow and body is a viewport-tall column; below 560px it returns to ordinary flow.
```

#### Wide enough to show a full-length folder name (SLUG_MAX = 40 mono ...

```text
Wide enough to show a full-length folder name (SLUG_MAX = 40 mono characters) without scrolling:
the slug becomes au.<slug>.<station> in every id and URL and is expensive to change once a DOI is
minted, so the submitter must be able to READ it. ch units track the mono font, and max-width
keeps the field inside the flex row on a narrow viewport.
```

#### The map's attribution, collapsed to one glyph

```text
The map's attribution, collapsed to one glyph. The credit is a licence term and stays with the map,
because only the layer that is drawing knows which provider to name, and the 240px cap keeps the
opened text clear of the legend at 560px of map. Shared character for character with index.html,
because these three maps wear the same control; pinned by tests/test_map_attribution.py.
```

#### The AusMT mark, not an organisation mark: AusMT is what this header ...

```text
The AusMT mark, not an organisation mark: AusMT is what this header IDENTIFIES, so no header on
this site carries a second mark of any kind. Same markup and same rule on every surface.
```

#### Options are populated at runtime from the generated contract (LICENSES ...

```text
Options are populated at runtime from the generated contract (LICENSES in src/contract.js),
grouped redistributable against recognised-only with a TBD option, never a hand-copied list.
```

#### Always-visible disclosure of what each access level actually exposes ...

```text
Always-visible disclosure of what each access level actually exposes, and truthful to current
behaviour: every level lists the survey publicly and emits its stations with lat/lon, and only
'open' serves data bytes.
```

#### embargo_until and access contact, revealed only for a non-open level ...

```text
embargo_until and access contact, revealed only for a non-open level, mirroring the page's other
show/hide blocks. Emitted into survey.yaml's access block by buildSurveyYaml (empty to null, date
as YYYY-MM-DD).
```

#### The plain-language citation-authorship question feeds creators[], an ...

```text
The plain-language citation-authorship question feeds creators[], an ORDERED citation list. Basic
tier: a name per row, with an Organisation checkbox that sets name_type; ORCID and ROR optional.
```

#### Citation block

```text
Citation block. TWO outputs, never a third: the custodian's own wording verbatim, and a typed
related_identifiers row for a pasted identifier. The form NEVER writes
citation.preferred_identifier, because designating which identifier a citation quotes is
curation.
```

#### organisations[]

```text
organisations[]. The essential Organisation above stays the custodial discovery value AND seeds
the first row, marked for curator review; extra rows say who else was involved and how. A
publisher is NEVER inferred: it is written only when ticked.
```

#### ==================== CARD 4, "Collection / program" ...

```text
==================== CARD 4, "Collection / program" ================================
Its own tier-style disclosure, collapsed by default, so the common single-survey submission is
not slowed by programme fields. The IDs (m_coll_*) are unchanged, so the collections.json
autofill IIFE still addresses them.
```

#### Identifiers by data level, mirroring the curator editor

```text
Identifiers by data level, mirroring the curator editor. Each row states WHAT the identifier
points at in NCI Table 1 terms; the DataCite relation is DERIVED server-side from the level and
is never asked here.
```

#### CENTRE

```text
CENTRE. Who enables AusMT, then the attribution and the licence note. The URL text is the one
link in the line. The year is a literal, the mechanism every page uses.
```

#### RIGHT

```text
RIGHT. The parent organisation's full lockup, linked where the centre's URL text links. The
image is same-origin and vendored, so stating the relationship takes no runtime dependency on
the organisation's own host.
```

#### INFO-block coords, decimal (Geotools style) or DMS ('LATITUDE ...

```text
INFO-block coords, decimal (Geotools style) or DMS ('LATITUDE : -28:31:33.45', NSW
re-export style) + DMS sign-bug detection. Mirrors the backend _edi_catalog: a decimal-only
match truncated DMS INFO values at the first colon, manufacturing whole-degree (~55 km)
HEAD/INFO conflicts. head == 2*floor(info) - info is the floored-DMS signature, so the
HEAD coordinate may be ~tens-to-hundreds of km wrong while the INFO decimal is correct.
```

#### ---------- DATAID-based packaging ---------- The pipeline keys a ...

```text
---------- DATAID-based packaging ----------
The pipeline keys a station off the EDI-INTERNAL DATAID (see engine/extract/_edi_catalog.parse_dataid
+ build_portal.safe_component), NOT the on-disk filename. A submission whose files are named
LineNo__StationNo_1.edi (whose DATAIDs are ROX000 …) therefore packages under names that don't match
the station identity the engine will assign. These helpers make the PACKAGED filename match the
DATAID so the two agree at submission time. Gateway/engine are unchanged, they already glob the EDI
dir and read the DATAID; this only renames the bytes we put in the zip.

ediDataId: extract the DATAID from an EDI's >HEAD block. Reads only a bounded prefix (the DATAID is
always in the header, within the first few hundred bytes); tolerates the quoting/whitespace variants
seen across real dialects, DATAID="WG-1" (Geotools, no indent), leading-indented `   DATAID="ST01"`
(EDL), and unquoted DATAID=A01. Returns the trimmed id, or null when absent/blank (the caller blocks).
```

#### safeEdiComponent: sanitise a DATAID for use as a packaged filename ...

```text
safeEdiComponent: sanitise a DATAID for use as a packaged filename component. MIRRORS the engine's
build_portal.safe_component EXACTLY (charset [A-Za-z0-9._-], neutralise '..', strip leading dots/
dashes, never empty), NOT a new rule. The engine applies this same function to the DATAID when it
forms on-disk product paths/filenames, so packaging under the same transform keeps the two in step
(and inherits its path-traversal/XSS neutralisation for untrusted submitted DATAIDs).
```

#### deriveDataId: when an EDI carries NO DATAID in its >HEAD block, the ...

```text
deriveDataId: when an EDI carries NO DATAID in its >HEAD
block, the station id is auto-derived from the on-disk FILENAME (extension stripped, then run through
the SAME safe_component sanitiser the engine applies) rather than blocking the submission. The derived
id is flagged for curator review in the package; only a true post-sanitisation COLLISION still blocks.
```

#### effectiveDataId: the id a packaged EDI is named by, its real DATAID ...

```text
effectiveDataId: the id a packaged EDI is named by, its real DATAID when present, else the filename-
derived fallback. Single source for both the rename preview and the packaged filename.
```

#### ediNameGate: the SUBMISSION-time COLLISION guard (design: fail loud, no ...

```text
ediNameGate: the SUBMISSION-time COLLISION guard (design: fail loud, no silent auto-suffixing). Input
is the EDI entries [{name, dataid}] in list order; output is a list of blocking error strings (empty
= clean). A missing DATAID is not a hard error on its own, it auto-derives from the filename
(deriveDataId) and is flagged for curator review. The ONE remaining blocking failure is a real on-disk
collision: two files whose EFFECTIVE ids (real DATAID or filename-derived) map to the SAME packaged
name (compared on the SANITISED name, catching ids that differ only in characters the sanitiser folds).
```

#### ---------- identifiers-by-level (tier 2; mirrors the curator editor ...

```text
---------- identifiers-by-level (tier 2; mirrors the curator editor IDENTIFIES_LEVELS/_IDENTIFIES_DISPLAY
+ editor_form.IDENTIFIER_TYPES). The `relation` is DERIVED server-side from the level, so it is NOT asked
and NOT emitted here. NCI Table 1 order + human labels, kept in step with gateway/editor_form.py. ----------
```

#### relatedIdentifiersEmit: filter a meta.related_identifiers list to the ...

```text
relatedIdentifiersEmit: filter a meta.related_identifiers list to the rows worth writing (an identifier
value is the signal) and vocab-guard `identifies`/`identifier_type` so a hand-crafted out-of-vocab value
(buildSurveyYaml is a pure export callable with arbitrary meta) is dropped, never emitted. `relation`
is intentionally absent, the server derives it from `identifies`.
```

#### ---------- contributor credit model (CONTRIBUTOR-CREDIT-SPEC)

```text
---------- contributor credit model (CONTRIBUTOR-CREDIT-SPEC). creators[] is the ORDERED "who
should be credited?" citation list; contributors[] is the typed who-did-what list. NAME_TYPES and
CONTRIBUTOR_ROLES are kept byte-in-step with the surveys validator (validate_survey.NAME_TYPES /
CONTRIBUTOR_ROLES_ORDERED) so the form only ever offers the fail-closed vocab the server accepts;
CONTRIBUTOR_ROLES is the DataCite contributorType subset in ratified order (it feeds the role <select>
AND the emit-time vocab guard). CONTRIBUTOR_ROLE_DISPLAY is the human label per token (curator-facing;
the DataCite tokens are jargon). ----------
```

#### creditRowsEmit: filter a creators/contributors list to the rows worth ...

```text
creditRowsEmit: filter a creators/contributors list to the rows worth writing (a name is the signal)
and vocab-guard name_type (both lists) + role (contributors) so a hand-crafted out-of-vocab value
(buildSurveyYaml is a pure export callable with arbitrary meta) is DROPPED, never emitted, exactly as
relatedIdentifiersEmit guards identifies/identifier_type. ORDER is preserved: it is the citation order.
```

#### ---------- The MTCAT 2.0 curated homes the plain-language tier-3 ...

```text
---------- The MTCAT 2.0 curated homes the plain-language tier-3
questions write. Every vocabulary is a BAKED copy kept byte-in-step with the surveys validator
(validate_survey.ORG_ROLES_ORDERED / ACKNOWLEDGEMENT_TYPES / CITATION_TEXT_SOURCES) and with
gateway/editor_form.py, pinned by tests/add_survey_logic.test.js. Out-of-vocab values are DROPPED at
emit time, never written, exactly as relatedIdentifiersEmit guards identifies/identifier_type.
```

#### hosting_institution is AusMT's own export-side role (who hosts the ...

```text
hosting_institution is AusMT's own export-side role (who hosts the archive), never a contributor's
claim about their survey, so the form OFFERS every other role and simply does not show it.
```

#### A contributor's citation wording is ALWAYS source_provided: they are ...

```text
A contributor's citation wording is ALWAYS source_provided: they are telling us how the dataset is
already cited. `ausmt_generated` describes wording AusMT composed and is never a contributor value.
```

#### The marker written above the row seeded from the essential ...

```text
The marker written above the row seeded from the essential Organisation, and the note written above a
pasted citation identifier. Both are YAML COMMENTS: invisible to every parser, never served, and
surfaced only by the curator editor's read job, which is exactly where they are meant to be answered.
```

#### organisationsEmit: the organisations[] rows to write

```text
organisationsEmit: the organisations[] rows to write. The essential Organisation ALWAYS seeds row 0 as
the marked custodian with primary_custodian: true (the projection and the role statement cannot
disagree, and the marker keeps the mechanical seed distinguishable from a curated claim). A row naming
that same organisation MERGES its ticked roles into the seed rather than making a second row; every
other named row is appended. Roles are vocab-guarded and emitted in ORG_ROLES_ORDERED order. A publisher
is NEVER inferred: it appears only where it was ticked.
```

#### citationIdentifierRow: the ONE related_identifiers row a pasted ...

```text
citationIdentifierRow: the ONE related_identifiers row a pasted citation identifier becomes. The paste
is normalised FIRST (a resolver URL folds to the bare DOI, so the row's identifier equals what a
curator would type), then typed: a '10.' shape is a DOI, an http(s) string that is not a DOI is a URL,
and anything else is not emitted at all. `identifies` is the contributor's optional answer to "what
does it point at?"; the default ("let the curator decide") omits the key rather than guessing a level.
Returns null when there is nothing to write.
```

#### ISO 7064 MOD 11-2 checksum over the 16 chars, mirrors ...

```text
ISO 7064 MOD 11-2 checksum over the 16 chars, mirrors gateway/orcid.py::is_valid_orcid EXACTLY
(design §4). This is the STRICT check: a well-formed pattern with a WRONG check digit is rejected,
so we fail fast client-side before an upload the gateway would 400. isOrcid() above (format only)
is left untouched for the non-blocking format WARNING. `X` is allowed only in the final position.
```

#### §1 gateway detection: PRESENT only if HTTP 200 AND the body parses as ...

```text
§1 gateway detection: PRESENT only if HTTP 200 AND the body parses as JSON AND json.ok === true.
Anything else (network error/timeout -> status 0 by convention here, non-200, HTML body that a
200-ing SPA-fallback/404 page could return) is ABSENT. Strict by design, the anti-false-positive
guard. Pure so §1's strictness is unit-tested without a DOM.
```

#### §2 anchor guard: a 201 status_url is used verbatim as an href ONLY if ...

```text
§2 anchor guard: a 201 status_url is used verbatim as an href ONLY if it is a same-origin relative
/gateway/status/<urlsafe-token> path. Rejects absolute URLs (http://…), protocol-relative (//…),
javascript:, path traversal, and any tampered prefix. Token chars are the urlsafe base64 alphabet
(A-Za-z0-9_-), matching secrets.token_urlsafe on the server.
```

#### §2 message mapping: HTTP status (+ parsed JSON body or null) -> plain ...

```text
§2 message mapping: HTTP status (+ parsed JSON body or null) -> plain human text (NO HTML; the page
escapes it through esc() at render time). Server `detail` for a 400 is passed through verbatim as
text. Pure + exported so every code path is unit-tested.
```

#### §3 wire contract form fields: submitter_name + submitter_email always ...

```text
§3 wire contract form fields: submitter_name + submitter_email always; submitter_orcid ONLY when
non-empty (the field is OMITTED entirely when blank, per the gateway's ≤8-field parser + §4 PII
note). Email/ORCID ride as multipart fields into sqlite only, never into the package.
```

#### slugValid MIRRORS the AUTHORITATIVE slug rule in the vendored validator ...

```text
slugValid MIRRORS the AUTHORITATIVE slug rule in the vendored validator -
gateway/tests/fixtures/vendored_validation/validate_survey.py:331, which admits lower-case
alphanumerics in hyphen-separated groups and nothing else.
The slug becomes au.<slug>.<station> in every id/URL, so anything outside [a-z0-9-] (uppercase,
spaces, underscores, dots, slashes, leading/trailing hyphens) is silently rewritten by the pipeline's
safe_component() and forks the survey identity, a server-side hard FAIL. Mirroring it here catches
the most common first-timer mistake before a wasted quarantine cycle. Keep in sync with that line.

SLUG_MAX is the LENGTH half of the same rule. A slug longer than this survives validation and
publication and then breaks the station-MTH5 tier HOURS later, at build time: the producer passes
the slug through verbatim as the MTH5 survey id (build_portal.py, normalize(survey_id=slug)), the
HDF5 survey group name comes back TRUNCATED AT 45 CHARACTERS, and the round-trip gate then cannot
find the group it just wrote, so it withholds every station .h5 in the survey. Observed on a
54-character slug: the gate reported the group as slug[:45], exactly.
40 is the cap with margin under that 45, and every survey in the corpus at the time was 9-30.
Enforced HERE (blocking, via validateSurvey) and derived-to-fit in deriveSlug, so the form cannot
mint one; the server-side validator carries the matching check for hand-edited packages.
```

#### deriveSlug: the project name -> the auto folder name shown in the slug ...

```text
deriveSlug: the project name -> the auto folder name shown in the slug chip. Capped at SLUG_MAX so
the AUTO value is always submittable - a long project name ("AusLAMP EFTF Phase 1 - Northern
Territory and Queensland (Geoscience Australia)") otherwise derives a 54-character slug that passes
every gate and then withholds every station MTH5 at build time, which is the case
this cap exists to prevent. The cut lands on a HYPHEN BOUNDARY when one falls in the last third of
the budget, so the result reads as whole words ("auslamp-eftf-phase-1-northern-territory") rather
than a severed one ("auslamp-eftf-phase-1-northern-territor"); trailing hyphens are stripped after
the cut so the output still satisfies slugValid's charset rule. Pure, and exported for the tests.
```

#### emtfxmlLooksReal: the browser-side anti-masquerade check for a ...

```text
emtfxmlLooksReal: the browser-side anti-masquerade check for a submitted EMTF XML, the sibling of the
validator's magic-byte gate for binary TF types and its NUL-byte gate for .edi. EMTF XML is text, and
its root element is <EM_TF> (the EarthScope schema), so a .xml that never opens that element is not a
transfer function whatever it is named. Reads a bounded prefix only, like ediDataId. This is a local
pre-submission check, not the authority: validate_survey.py in the pipeline decides.
```

#### Slug charset gate, mirrors the authoritative server-side FAIL ...

```text
Slug charset gate, mirrors the authoritative server-side FAIL (validate_survey.py:331), so a
malformed slug is caught HERE instead of after a full quarantine cycle. Only when a slug is present
(the REQUIRED loop above already FAILs an empty slug; we do not double-report it).
The two halves are reported SEPARATELY: "too long" and "wrong characters" are different mistakes
with different fixes, and a single merged message sends the submitter hunting for a bad character
that is not there.
```

#### dates.issued is a PUBLICATION date (interface contract section 6): a ...

```text
dates.issued is a PUBLICATION date (interface contract section 6): a full ISO date, never a bare
year and never inferred from the acquisition window. Blocking, so the contributor fixes it here
rather than meeting the same refusal from the server validator after upload.
```

#### Provenance-identifier completeness: the hint now keys off the NEW ...

```text
Provenance-identifier completeness: the hint now keys off the NEW carrier, the identifiers-by-level
related_identifiers list (the single place a dataset DOI / collection PID / archive handle is recorded,
matching the curator editor's "This dataset elsewhere"). Warn only when NO related identifier carries a
value. The retired dataset_doi/sources slots are gone.
```

#### DATAID naming gate: a MISSING DATAID does not block, the station id ...

```text
DATAID naming gate: a MISSING DATAID does not block, the station
id auto-derives from the filename and is flagged for curator review (a WARNING, and a package note). The
ONLY blocking failure now is a true post-sanitisation COLLISION (two files -> the same packaged name).
```

#### Station-location gate (softened): BLOCKING only when the DMS resolver ...

```text
Station-location gate (softened): BLOCKING only when the DMS resolver actually found a HEAD/INFO
conflict/anomaly. Otherwise the stations are just plotted with an informational nudge (no checkbox wall).
```

#### The recognised licence-id vocabulary for the licence <select>s, derived ...

```text
The recognised licence-id vocabulary for the licence <select>s, derived from the GENERATED contract
(portal/src/contract.js LICENSES), never a hand-copied list. redistributable first, then
recognised-only (metadata-only display). Pure, so the jsdom test can pin it to the contract file.
```

#### Attribution capture: persist the uploader's licence declaration (who + ...

```text
Attribution capture: persist the uploader's licence declaration (who + when), and any upstream
source dataset. declared_date is a bare ISO scalar derived from the tsUTC seam (or an explicit
m.declared_date). A package carrying any attribution field declares schema_version 0.3.
```

#### "Does this dataset already have a citation or DOI?" -> the pasted ...

```text
"Does this dataset already have a citation or DOI?" -> the pasted identifier becomes ONE typed
related_identifiers row, deduped against an existing "This dataset elsewhere" row (a contributor who
listed it in both places gets one row, not two).
```

#### The two RETIRED flat credit keys are NEVER written

```text
The two RETIRED flat credit keys are NEVER written. The migration
seeded creators[]/contributors[] from them and deleted them corpus-wide, the engine reads neither,
and the curator editor models neither - so a form that still wrote them would be producing keys
nobody can read or fix. "Who led this survey?" writes a ProjectLeader contributors row instead
and the organisations[] block below carries the role statement.
Contributor credit model (CONTRIBUTOR-CREDIT-SPEC): creators[] (ORDERED citation names, the
"who should be credited?" question) then contributors[] (the typed who-did-what rows). A row is
emitted only when it carries a name; absent -> absent (no empty list) so a bare survey stays lean, and
DOM order is preserved as the citation order. name is QUOTED (free text: a bare "2020" / "No" /
"Sponsor, Inc" would be mis-typed unquoted, the declared_date lesson), as are orcid/ror; name_type and
role are vocab-GUARDED bare scalars (only an in-vocab token survives creditRowsEmit), the same
bare-vocab discipline as the identifies / identifier_type rows above.
```

#### "Who led this survey?" -> ONE ProjectLeader contributors row, FIRST (it ...

```text
"Who led this survey?" -> ONE ProjectLeader contributors row, FIRST (it is the question asked
first), deduped against an identical typed row so naming the lead twice does not credit them twice.
```

#### Optional acquisition window

```text
Optional acquisition window. Bare scalars; a year or an ISO date. Injection-guarded: only a
4-digit year or a strict YYYY-MM-DD is emitted unquoted, anything else is quoted as free text.
```

#### dates.issued is the PUBLICATION/RELEASE date (interface contract ...

```text
dates.issued is the PUBLICATION/RELEASE date (interface contract section 6): a full ISO date, never
a bare year, never inferred from the acquisition window. Anything else is not emitted at all (and
validateSurvey FAILs it, so the contributor is told rather than silently trimmed).
```

#### identifiers block, the CURRENT schema: only the two ...

```text
identifiers block, the CURRENT schema: only the two survey/platform-level PIDs a submitter sets
(project RAiD + the survey/platform instrument PID). The retired flat dataset-identifier keys
(dataset_doi, related_publication[_doi], project) are GONE, a dataset DOI / collection PID / archive
handle is now a typed related_identifiers row (below), matching the curator editor.
```

#### related_identifiers (identifiers by data level)

```text
related_identifiers (identifiers by data level). Each row states WHAT it points at (`identifies`, an
NCI Table 1 level); the DataCite `relation` DERIVES from that server-side and is NOT emitted here.
```

#### The contributor's intent survives into curation as a COMMENT above the ...

```text
The contributor's intent survives into curation as a COMMENT above the row: they told us this
identifier is how the dataset is cited, and only a curator may turn that into a designation.
```

#### citation{} (interface contract section 3): the custodian's own wording ...

```text
citation{} (interface contract section 3): the custodian's own wording, VERBATIM, plus where it came
from. TWO keys, never a third: citation.preferred_identifier is a curated designation and the
form never writes it. text_source rides a non-empty preferred_text and is meaningless without
one, so both appear together or not at all.
```

#### organisations[] (survey scope section 3)

```text
organisations[] (survey scope section 3). Row 0 is the marked custodian seeded from the essential
Organisation; every other row is what the contributor ticked. ror is OMITTED when blank (never
`ror: null`), roles ride as bare guarded vocab tokens, and primary_custodian: true appears on the
seeded custodian only.
```

#### acknowledgements[] (interface contract section 3): plural, verbatim ...

```text
acknowledgements[] (interface contract section 3): plural, verbatim, never a citation. The wording is
the row, so a textless row was already dropped; type is a bare guarded token and source is free text.
```

#### embargo_until / contact are only meaningful for a non-open survey ...

```text
embargo_until / contact are only meaningful for a non-open survey; blank -> null. The date is
emitted as a bare ISO YYYY-MM-DD scalar (the <input type=date> value format the validator parses),
the contact as a quoted string. For an open survey both stay null (nothing to withhold, no release
contact needed) even if the fields carry stale text from a level the submitter changed away from.
INJECTION GUARD: the date line is UNQUOTED, and this is a pure export callable with arbitrary meta
(a browser's <input type=date> constrains values; a scripted DOM does not). Anything that is not
strictly \d{4}-\d{2}-\d{2} collapses to null, a value with an embedded newline would otherwise
smuggle an injected YAML key into the generated file. Mirrors the validator's ISO-date rule
(validate_survey.py:303-308, date.fromisoformat) the same way slugValid mirrors the slug rule.
```

#### QUOTED ISO string (validated shape / tsUTC-derived)

```text
QUOTED ISO string (validated shape / tsUTC-derived). The engine threads attribution VERBATIM into
SMETA and never parses declared_date as a real date, so an UNQUOTED value here was implicit-typed by
PyYAML safe_load into a datetime.date and crashed the build's json.dumps (surveys.json/mtcat). Quoting
it makes it round-trip as a plain string everywhere, matching the curator-yaml convention. (embargo_until
above is left UNQUOTED on purpose: the engine DELIBERATELY parses it as a calendar date for the access
gate and str()-normalises it in SMETA, so it is date-typed by design and never a serialisation hazard.)
```

#### time_series: pointers only

```text
time_series: pointers only. The hard-coded collection_pid null is retired, a collection DOI/PID is a
related_identifiers row (identifies: collection). Only levels_available is emitted here.
```

#### publications: built from the DOI-first publication rows (each ...

```text
publications: built from the DOI-first publication rows (each {author,year,title,journal,doi},
harvested from Crossref/DataCite or hand-entered). The engine's _publications_of reads all five keys.
Emitted key order is author, year, title, journal, doi; only NON-EMPTY descriptive keys are written,
and doi is always emitted last (null when blank) whenever the row has any descriptive field, so the
legacy title-only / DOI-only shapes stay byte-identical. A DOI-only row emits the bare `- doi:` form.
Empty -> [].
```

#### ROR response parsing, robust across API v1 ({name ...

```text
ROR response parsing, robust across API v1 ({name, country.country_name, acronyms}) and v2
({names:[{value,types}], locations:[{geonames_details.country_name}]}). Returns clean rows only;
any item we cannot name AND identify is dropped, so the UI never shows or stores "undefined".
```

#### DOI harvest core -- normalizeDoi, looksLikeDoi, parseCrossref ...

```text
DOI harvest core -- normalizeDoi, looksLikeDoi, parseCrossref, parseDatacite, formatCitation and
harvestDoi now live in the SINGLE shared source src/doi_harvest.js (loaded in <head>; it attaches to
window.AusmtDoiHarvest), reused verbatim by the curator metadata editor so the registry parsing can
never drift between the two surfaces (CONTRIBUTOR-CREDIT-SPEC curator DOI harvest). Alias the shared
functions into this block's scope so every call site below (and the node module.exports) is unchanged.
```

#### Fold the repeatable publication rows (each ...

```text
Fold the repeatable publication rows (each {author,year,title,journal,doi}, harvested or hand-entered) into
the emission list buildSurveyYaml writes. Trims + DOI-normalises every field; a row counts when it carries
ANY content. LEGACY back-compat: when no publications[] array is supplied, the retired single-field
{pub, pub_doi} pair is folded into one row, so a caller (or an old test) built on the flat pair still emits the
same publications[] shape. Pure; the emission is byte-identical whether the row was harvested or typed.
```

#### Slug-collision awareness: the served surveys.json is {surveyName ...

```text
Slug-collision awareness: the served surveys.json is {surveyName: SMETA}, each entry carrying its
published `slug`. servedSlugMap folds that into {slug: surveyName} so a derived slug can be checked
against the ALREADY-PUBLISHED set. Tolerant of the empty portal ({}), a non-object, or a missing slug.
Pure, so the collision states are unit-tested without a fetch/DOM.
```

#### Station-count context: surveys.json carries no per-survey station ...

```text
Station-count context: surveys.json carries no per-survey station count, so the "(N stations)" the
collision warning shows is derived from the served catalogue.json (an array of station rows whose index
1 is the survey NAME). Counts rows per survey name; the warning joins slug -> name -> count. Best-effort:
an unreachable/absent catalogue simply yields no counts and the warning drops the parenthetical.
```

#### Gateway state: set true ONLY by a passing same-origin healthz probe ...

```text
Gateway state: set true ONLY by a passing same-origin healthz probe (design §1). Read by the
shared package builder so SUBMISSION.md lists the direct-upload path first when a gateway is live.
```

#### Populate the licence <select>s from the GENERATED contract vocab ...

```text
Populate the licence <select>s from the GENERATED contract vocab (LICENSES from
src/contract.js), grouped redistributable vs recognised metadata-only + a TBD workflow option.
Never a hand-copied list, the pure exported vocab is licenseSelectIds(LICENSES).
```

#### ----- identifiers-by-level rows (tier 2)

```text
----- identifiers-by-level rows (tier 2). Mirrors the curator "This dataset elsewhere" editor: an
`identifies` level <select> FIRST (human labels, exact vocab value), then the identifier, its type,
and an optional custodian. The DataCite relation is NOT collected, it derives server-side. -----
```

#### ----- DOI-first publication rows

```text
----- DOI-first publication rows. Each row's PRIMARY input is one DOI; on a valid-looking DOI the
page harvests the citation (Crossref for journal papers, DataCite for dataset DOIs, via the pure
harvestDoi) and fills the row's HIDDEN manual fields, showing a compact read-only preview. The manual
fields (author/year/title/journal) are the SINGLE source of truth readPublications reads, so the
emission is byte-identical whether a row was harvested or hand-typed. Harvest failure (network, unknown
DOI, a no-DOI report) expands those fields prefilled with whatever partial data exists; the "Edit"
affordance on a good preview opens the same fields prefilled with the harvested values (registry
formatting is sometimes ugly, the contributor stays in charge). PUB_CACHE harvests each DOI at most
once per page load; a per-row `token` keeps ONE in-flight fetch per row (a newer edit voids an older
reply); the fetch DEGRADES SILENTLY to the manual fields if it is blocked (older cached CSP, offline).
```

#### ----- Credit: creators[] (the plain-language citation-authorship ...

```text
----- Credit: creators[] (the plain-language citation-authorship question). Basic tier: an
ordered list of citation names, each a person or (org checkbox) an organisation, ORCID/ROR optional.
DOM order IS the citation order. Emitted as creators[] {name, name_type, orcid?/ror?} by readMeta ->
buildSurveyYaml. One empty row shows by default so the question is visible; a nameless row is dropped
at emit time (name is the signal), and the org toggle switches both name_type and the id hint.
```

#### ----- Credit: contributors[] (who did what)

```text
----- Credit: contributors[] (who did what). Advanced tier: typed rows adding a name_type <select>
and the fail-closed role <select> (the 8 DataCite tokens, CONTRIBUTOR_ROLES). The <select>s only ever
offer the ratified vocab, so the form cannot author a value the server would block. Emitted as
contributors[] {name, name_type, role, orcid?/ror?}. Starts empty (added on demand, like the PIs).
```

#### ----- organisations[] rows ("Which organisations were involved, and ...

```text
----- organisations[] rows ("Which organisations were involved, and how?"). A name plus an
optional ROR plus a role checkbox group over ORG_ROLES_OFFERED (every ratified role except
hosting_institution, which is AusMT's own export-side role, never a contributor's claim). The
checkboxes are the honest control: an organisation is often several things at once. The essential
Organisation is NOT repeated here - organisationsEmit seeds it as the marked custodian row.
```

#### ----- acknowledgements[] rows ("Is there wording you must include?")

```text
----- acknowledgements[] rows ("Is there wording you must include?"). The wording IS the row, so
a textless row is dropped at emit time; the type <select> only offers the ratified candidate vocab.
```

#### ----- The citation question's "what does it point at?" <select>

```text
----- The citation question's "what does it point at?" <select>. Same NCI Table 1 vocabulary and
labels as the tier-2 identifier rows; its DEFAULT is "let the curator decide", which omits the key
rather than guessing a level on the contributor's behalf.
```

#### ----- DOI normalisation on blur

```text
----- DOI normalisation on blur. A contributor who pastes a full resolver URL (https://doi.org/
10.x/y, dx.doi.org, http variants) into a DOI slot triggered the live validator's "publication DOI
looks malformed" warning. wireDoiBlur folds the field down to the bare DOI on blur and SHOWS the
normalised value, so the contributor sees exactly what will be recorded. A bare DOI and any non-DOI
string are left untouched. wireConditionalDoiBlur only folds when a sibling type <select> reads "DOI"
(a URL-typed identifier row keeps its URL, the URL is the value there).
```

#### ----- slug: AUTO-DERIVED from the project name (charset-safe, so it ...

```text
----- slug: AUTO-DERIVED from the project name (charset-safe, so it always passes slugValid), shown as
an editable chip. The derived value is a live convenience; the moment the submitter edits the slug
themselves it stops tracking the name (slugTouched). Inline validation mirrors the authoritative
validator FAIL so the most common first-timer mistake is caught at the field, not after a quarantine
cycle. The blocking gate itself lives in validateSurvey (slugValid), this is just the field-level cue.
deriveSlug lives in the pure-logic section above (beside slugValid, which it must always satisfy)
so the node tests can exercise the SLUG_MAX cap directly.
```

#### Slug-collision awareness: the derived slug can already match a ...

```text
Slug-collision awareness: the derived slug can already match a PUBLISHED survey (e.g. "vulcan
2022" -> vulcan-2022, already served). Lazily fetch the same-origin data/surveys.json (slug set) +
data/catalogue.json (station counts, for the "(N stations)" context) on first name/slug input, and
WARN with context on a match without ever BLOCKING (a custodian updating an existing survey is
legitimate). Both fetches degrade silently (opened as file://, empty portal, or no data yet).
```

#### Use the name-search `query` endpoint, NOT `affiliation`: the ...

```text
Use the name-search `query` endpoint, NOT `affiliation`: the affiliation matcher is built for parsing
full publication affiliation strings (NER-style) and mis-ranks bare names, e.g. "University of Adelaide"
returns "University of Aden" (score 0.97, chosen) and omits Adelaide entirely. `query` relevance-ranks
by name and returns the right org (verified live against api.ror.org).
```

#### wires an organisation text input -> ROR suggestion box -> fills a ROR ...

```text
wires an organisation text input -> ROR suggestion box -> fills a ROR field; on pick, also
normalises the (user-confirmed) organisation name. Never overwrites typed text before selection,
and never writes an empty/undefined value (guards below).
```

#### ----- access level: reveal the embargo date + access contact only for a ...

```text
----- access level: reveal the embargo date + access contact only for a non-open level (audit 5.2).
Same show/hide idiom as #gatewayBlock / #dmsChoice. The disclosure hint (#accessDisclosure) is always
visible; this only toggles the input block, so a submitter who never touches a non-open level sees no
extra fields, and buildSurveyYaml already null-guards on level==open regardless of any stale value.
```

#### Per-EDI rename preview: shows "originalname.edi → ROX000.edi" so the ...

```text
Per-EDI rename preview: shows "originalname.edi → ROX000.edi" so the submitter sees the DATAID-based
packaged name BEFORE uploading. A missing DATAID shows a red "no DATAID" note, the same
condition validateSurvey turns into a blocking FAIL, so the UI and the gate agree.
```

#### Per-row remove: one delegated listener (data-i indexes the `files` ...

```text
Per-row remove: one delegated listener (data-i indexes the `files` array). Splice + re-render, which
ends in updateConf() (keeps the DMS/confirm state consistent) and feeds every downstream flow
(Validate/Preview/Package/Submit all read live from `files` via ediFiles()/mth5Files()/parsed()).
```

#### EMTF XML is a TEXT format like EDI, so it is read as text and its bytes ...

```text
EMTF XML is a TEXT format like EDI, so it is read as text and its bytes are the UTF-8 encoding of
that text, the same convention the EDI branch uses for its sha256. It is NOT parsed here: the
station identity lives in the file's own Site metadata and the engine reads it at build time.
```

#### dataid: extracted once at ingest from the >HEAD block (bounded prefix)

```text
dataid: extracted once at ingest from the >HEAD block (bounded prefix). null when absent -
the validation gate turns that into a blocking FAIL. Drives both the rename preview and the
packaged filename, so a file's original name never leaks the station identity into the zip.
```

#### THE THREE MAPS ON THIS PAGE WEAR THE PORTAL MAP'S ATTRIBUTION CONTROL ...

```text
THE THREE MAPS ON THIS PAGE WEAR THE PORTAL MAP'S ATTRIBUTION CONTROL: Leaflet's default one
carries the flag and the word, which must appear on no map on this site, so each map is created
without one and src/mapattrib.js mounts a collapsed control in its place. The credit itself is
the tile layer's own and is unchanged: these three draw OpenStreetMap raster tiles directly.
```

#### The inline map: stations are plotted the instant files land

```text
The inline map: stations are plotted the instant files land. Guarded on Leaflet, so
it degrades to just the count when the map library is unavailable (e.g. the jsdom interaction driver).
```

#### Only EDIs are parsed in the browser, so only their stations plot

```text
Only EDIs are parsed in the browser, so only their stations plot. EMTF XML and MTH5 carry their
coordinates in structured metadata the engine reads at build time; rather than write a second
coordinate parser here (a second derivation of the same fact, and a divergence risk), the page
says plainly that those files were accepted and where their stations are read. Never a silent
"no stations" for a submission that is entirely EMTF XML or MTH5.
```

#### ----- shared package builder (design §0.5: ONE builder feeds BOTH the ...

```text
----- shared package builder (design §0.5: ONE builder feeds BOTH the download and the direct-
upload paths, so the bytes are identical either way). Reads the submitter's DMS choice, gates on
validation FAILs (returns null when blocked), and produces the byte-payload + metadata both
callers need. It performs NO DOM writes and NO download/upload side effect, the caller decides
what to do with the blob. Email/ORCID are NEVER written here (design §4): the package is PII-clean
whether it goes out as a public-PR attachment OR as a same-origin gateway upload.
```

#### EDI packaging: the zip entry + MANIFEST `file` path are named by the ...

```text
EDI packaging: the zip entry + MANIFEST `file` path are named by the EDI's DATAID
(<sanitized-DATAID>.edi), NOT the submitter's on-disk filename, so the packaged names match the
station identity the engine keys off. A missing DATAID auto-derives from the filename (softened gate)
and is recorded as `dataid_source: filename-derived` + a curator flag so a reviewer can confirm the
station id. validateSurvey has already blocked any real collision above. `source_filename` records
the ORIGINAL selected name as additive provenance (curator-facing).
```

#### EMTF XML is NOT renamed, for the same reason MTH5 is not: the station ...

```text
EMTF XML is NOT renamed, for the same reason MTH5 is not: the station identity travels INSIDE
the file (the Site id and, where the id needed sanitising, the Site Name), and the engine reads
it there rather than from the filename. Renaming would invent an identity the file does not
claim. source_filename == the packaged name here, uniform provenance across every tf entry.
```

#### SUBMISSION.md travels INSIDE the zip on BOTH transport paths (design ...

```text
SUBMISSION.md travels INSIDE the zip on BOTH transport paths (design §2), so it must stay accurate
for both: the direct-upload path is listed as option 1 where a gateway is available, emailing the
packaged zip to the operator as the fallback. It NEVER references email/ORCID as file CONTENT;
the operator-email path is a submission INSTRUCTION, not a stored address. `gatewayAvailable` only
reorders the guidance, the fallback is documented regardless, since the file may be read after the
fact by someone on a different deploy.
Plain-language meaning of each access level, restated in the package (audit 5.3) so the choice's
consequence travels with the data. Truthful to build_portal.py: every level is publicly discoverable
with exact coordinates; only 'open' serves data bytes; an embargo never auto-lifts.
```

#### Submission paths, honest to the current infrastructure (audit 5.1): the ...

```text
Submission paths, honest to the current infrastructure (audit 5.1): the gateway upload is the
primary path where detected; the fallback is emailing the packaged zip to the operator (the
ausmt-surveys repo is private, so there is no public PR path). Numbering stays sequential in both
branches. Contact email rides OUTSIDE this package (email body / gateway field), never in a file.
```

#### ----- collection autofill: prefill from EXISTING collections so a ...

```text
----- collection autofill: prefill from EXISTING collections so a contributor JOINS an existing
collection (exact id) instead of re-typing it and risking a typo that silently spawns a duplicate
(collection grouping is an EXACT id match in the engine). Degrades to a plain text field when
data/collections.json isn't reachable (opened as file://, or no collections published yet).
```

#### ----- Direct upload to the same-origin submission gateway ...

```text
----- Direct upload to the same-origin submission gateway ------------------------------------
Detection (design §1): one healthz probe per page load, 5 s AbortController timeout, no polling.
The submit UI stays hidden unless gatewayPresent(status, body) is strictly true (200 + JSON +
ok===true). A failed/absent probe leaves the page byte-identical to the pre-C13 page, the
download-and-email path (Package submission .zip) remains primary. Same-origin literal /gateway/...
only (no config knob, no new origin, CORS-free and covered by the existing connect-src 'self').
```

#### With a live gateway the primary public flow is validate -> submit ...

```text
With a live gateway the primary public flow is validate -> submit directly, so the package-and-
download-zip path (the email-the-operator fallback) is HIDDEN. It is shown ONLY in the degraded
no-gateway state (its default). All zip code stays intact; this is
visibility wiring only. Hiding is visual (display:none) - the packager still works if invoked.
```

#### ----- key request (a client-side stub; the endpoint is the sibling ...

```text
----- key request (a client-side stub; the endpoint is the sibling security work's). POSTs {email}
to the same-origin /gateway/request-key and ALWAYS shows the same neutral message regardless of the
response, so it can never confirm whether an address is eligible (no account enumeration). Disabled
with a clear note until the gateway probe passes.
```

#### Submit flow (design §2)

```text
Submit flow (design §2). The submit key is RADIOACTIVE (§0.3): it lives only in the password
input and, transiently, in the X-AusMT-Submit-Key request header. It is NEVER stored, never put
in a URL, never in a track() payload, never echoed to the DOM, never written into the zip.
```

#### 2

```text
2. Submitter-ORCID CHECKSUM (fail fast, the server enforces ISO 7064 MOD 11-2 and would 400
   after a full upload). Blank ORCID is fine (optional); a present one must pass the checksum.
```

#### 5

```text
5. POST via XMLHttpRequest (upload progress + Cancel). No client timeout (250 MB on slow links
   is legitimate); Cancel is the escape hatch. multipart per §3: one file part + submitter
   fields; submitter_orcid is OMITTED entirely when empty (submitFormFields).
```

#### §2 response rendering, EVERY server-derived string goes through esc()

```text
§2 response rendering, EVERY server-derived string goes through esc(). The status link is an
anchor ONLY when statusUrlSafe() accepts the server's status_url (else the id is shown, no link).
```

## portal/releases.html

#### One footer, three regions: the MTCAT link LEFT, the AuScope ...

```text
One footer, three regions: the MTCAT link LEFT, the AuScope acknowledgement CENTRE, the
AuScope-NCRIS lockup RIGHT. The rule set below is index.html's, character for character, where the
zone geometry and the two container states are stated once; tests/test_footer_regions.py holds all
seven surfaces identical. STICKY, not fixed, so it keeps its box in flow and body is a
viewport-tall column; below 560px of viewport it returns to ordinary flow.
```

#### CENTRE

```text
CENTRE. Who enables AusMT, then the attribution and the licence note. The URL text is the
one link in the line. The year is a literal, the mechanism every page uses.
```

#### RIGHT

```text
RIGHT. The parent organisation's full lockup, linked where the centre's URL text links. The
image is same-origin and vendored, so stating the relationship takes no runtime dependency
on the organisation's own host.
```

## portal/brand.html

#### Out of the search index and out of the sitemap: this page is an asset ...

```text
Out of the search index and out of the sitemap: this page is an asset shelf reached from About,
and a brand page ranking beside the survey and collection pages would spend the site's own
discovery surface on it. It stays crawlable on purpose, because a robots.txt Disallow would stop
the crawler ever reading the noindex below.
```

#### One footer, three regions: the MTCAT machine-readable link LEFT, the ...

```text
One footer, three regions: the MTCAT machine-readable link LEFT, the AuScope acknowledgement
CENTRE, the AuScope-NCRIS lockup RIGHT. The rule set below is index.html's, character for
character, where the zone geometry and the two container states are stated once;
tests/test_footer_regions.py holds all seven surfaces identical, so an edit here that is not an
edit there fails. STICKY, not fixed: it keeps its own box in flow, so the last line of the page
is never hidden under it, which is why body is a viewport-tall column and main takes its free
space. Below 560px of viewport it would cover most of a phone screen, so it returns to flow.
```

#### CENTRE

```text
CENTRE. Who enables AusMT, then the attribution and the licence note. The URL text is the one
link in the line. The year is a literal, the mechanism every page uses.
```

#### RIGHT

```text
RIGHT. The parent organisation's full lockup, linked where the centre's URL text links. The
image is same-origin and vendored, so stating the relationship takes no runtime dependency on
the organisation's own host.
```

## portal/404.html

#### One footer, three regions: the MTCAT machine-readable link LEFT, the ...

```text
One footer, three regions: the MTCAT machine-readable link LEFT, the AuScope acknowledgement
CENTRE, the AuScope-NCRIS lockup RIGHT. The rule set below is index.html's, character for
character, with the four colour tokens resolved to the literals this page writes, because it is
served for any unmatched path at any depth and carries no token layer;
tests/test_footer_regions.py holds all seven surfaces identical. STICKY, not fixed: it keeps its
own box in flow, so body is a viewport-tall column and the last line is never hidden under it;
below 560px of viewport it returns to ordinary flow.
```

#### CENTRE

```text
CENTRE. Who enables AusMT, then the attribution and the licence note. The URL text is the one
link in the line. The year is a literal, the mechanism every page uses.
```

#### RIGHT

```text
RIGHT. The parent organisation's full lockup, linked where the centre's URL text links. The
image is same-origin and vendored, so stating the relationship takes no runtime dependency on
the organisation's own host.
```

## portal/src/analytics-shim.js

#### Analytics no-op shim - EXTERNAL file so no page needs an inline ...

```text
Analytics no-op shim - EXTERNAL file so no page needs an inline <script> for it (inline script
On index.html was the only thing forcing CSP 'unsafe-inline' there; extracted so the
deployed Caddy policy can be strict script-src 'self' everywhere except add-survey.html, whose
application code is still one intentional inline block).
Safe no-op queue so track() calls never error when analytics is disabled (the default).
```

## portal/src/data.js

#### The portal computes nothing

```text
The portal computes nothing. It loads generated JSON products (incl. survey metadata and
build provenance). build_provenance.json is optional: older data sets still load without it.

POSITIONAL CONTRACT - these files are arrays read BY INDEX (no field names). The SINGLE SOURCE is
contract/columns.json, generated into engine/extract/_contract.py + portal/src/contract.js by
`python contract/generate.py`; the human reference is docs/docs/developer/data-files.md. The portal
reads columns through contract.js's NAMED index maps - r[C.*], sc[SC.*], t[T.*] - so a reorder in
columns.json regenerates the indices and no consumer can silently lag. Legend (index -> name):
  CAT[i]  r[]  = [0 id,1 survey,2 lat,3 lon,4 pmin,5 pmax,6 nper,7 comps,8 type,9 region,
                  10 file,11 coord_flag,12 ausmt_id,13 edi_available,14 sha256,15 site_name]
  SCI[i]  sc[] = [0 q,1 qb,2 rr,3 sw,4 alg,5 dim,6 p3d,7 gd,8 ellip,9 skew,10 mre,11 decades]
  TFD[i]  t[]  = [0 periods,1 rho_xy,2 rho_yx,3 phs_xy,4 phs_yx_adj,5 tip_mag,6 pt_min,7 pt_max,
                  8 pt_az,9 pt_beta,10 rho_xy_err,11 rho_yx_err,12 phs_xy_err,13 phs_yx_err,
                  14 tzx_re,15 tzx_im,16 tzy_re,17 tzy_im]   (18 columns; tip_mag kept for compat)
To change a column: edit contract/columns.json, run `python contract/generate.py`, then data-files.md. APPEND, never reorder.
Data files are produced by the AusMT engine. By default they are served from the portal's own
./data/ directory; a deployment may instead point at a remote base (AUSMT_CONFIG.data_base_url,
e.g. the engine's gh-pages URL) so the portal and its data can live in separate repos.
```

#### Hydration fetches carry the low priority hint: they share the ...

```text
Hydration fetches carry the low priority hint: they share the connection with anything the user
does next (a drawer open, a tile fetch), and none of them is awaited on the first-paint path.
Browsers without priority hints ignore the field; the value must stay a VALID hint ("low"), as
supporting browsers throw on an unknown one.
```

#### ---- PHASE 1: the first-paint set ...

```text
---- PHASE 1: the first-paint set ---------------------------------------------------------------
Everything the map dots, the filter rail and the survey/collection views need, and nothing else:
catalogue.json (~320KB, REQUIRED: it IS the dots) + surveys.json (REQUIRED: the per-survey metadata
every card and drawer header reads) + the four SMALL optionals. All SIX are issued together.
The split is what keeps first paint off the big product: tf.json is 3.2MB raw / ~1MB gzipped, ~3.1s on
a live load, so awaiting it in the same Promise.all would hold the dots behind it, and issuing the five
optionals sequentially would stack five round trips on top of that wait. The dots must not wait on the
transfer functions, and the optionals must not wait on each other.
```

#### Build.json (build_id/engine_commit/source_commit/generated), optional ...

```text
Build.json (build_id/engine_commit/source_commit/generated), optional and tolerant of absence
(older builds predate it); the footer only renders the "data build …" line when this resolves.
No skew-handshake check here yet (comparing this against a contract hash the portal itself
carries); that waits on the contract-hash plumbing.
```

#### Optional coordinate-policy markers (ausmt_id -> ...

```text
Optional coordinate-policy markers (ausmt_id -> 'generalised'|'withheld'), emitted
by the engine ONLY when a survey has a non-exact station. Absent for an all-exact corpus (the common
case) => {} => no badges. Same tolerant-of-absence pattern as collections/build above.
```

#### ---- PHASE 2: background hydration ...

```text
---- PHASE 2: background hydration --------------------------------------------------------------
The heavy products, issued AFTER phase 1 settles (they would otherwise contend with the catalogue
for the same connection) and awaited by NOBODY on the first-paint path.
Each assigns its global and settles its own gate, so a consumer waits only for the product it actually
reads (a station drawer's plots need tf; the Files tab needs the manifest; neither needs the other).
Returns the four gates so a caller (and the headless drivers) can observe hydration.
```

#### A tf/sci FAILURE is not absence

```text
A tf/sci FAILURE is not absence. First paint must not depend on them, so a failure is recorded
as "failed" and the products fall back to EMPTY arrays; the empty array keeps every positional deref
safe, and hydrFailed() is what the consumers render, so a broken build is never mistaken for a station
that genuinely has no curves.
```

#### ts_access.json is OPTIONAL by contract - the engine writes it only when ...

```text
ts_access.json is OPTIONAL by contract - the engine writes it only when the
register projects at least one open, verified route, so a 404 IS the honest absence and there
is no "failed" state to report. The fallback is {} rather than null so every consumer reads one
shape, and the difference the Availability controls render is TSACC===null (still in flight)
against an empty object (this deployment publishes no download index).
```

#### ---- download manifest resolver: the distribution backbone ...

```text
---- download manifest resolver: the distribution backbone -----------------------------------
manifest.json indexes every downloadable artifact: per-station files (EDI/EMTF-XML) and per-survey
bundles (EDI zip / survey MTH5), each with a portal-RELATIVE url + size + sha256 + tier. The portal
joins each url onto data_base_url via dataUrl() - so migrating a tier to NCI later is a manifest
change with zero consumer edits. tier=nci rows carry an ABSOLUTE NCI fileServer url that dataUrl()
passes through unchanged and renders as a live download link (url is null only if a row is unresolvable).
```

#### ONE ausmt_id -> served-rows index over files[], built once per manifest ...

```text
ONE ausmt_id -> served-rows index over files[], built once per manifest and shared by every consumer.
Filtering the whole files[] array per call is nothing for a drawer opened once and quadratic for the
selection panel: paintExportSizes asks it per selected station on every keystroke, so at corpus scale
(3k stations selected, ~9k manifest rows) one repaint walks ~27M rows and takes 670ms, on the input
path. Measured 18ms at 500 stations, 77ms at 1000, 290ms at 2000: the cost grows with the SQUARE of the
corpus, so it is invisible in every fixture and worst on the full selection.

The cache is keyed on the MANIFEST OBJECT ITSELF, not on a "loaded" flag or a reset call. MANIFEST is
assigned whole (data.js hydration, and the drivers/harnesses that poke it directly) and never mutated in
place, so identity is exactly the invalidation signal, and a caller that swaps the manifest cannot forget
to invalidate a cache it does not know exists. A cache that had to be reset by hand would go stale
silently, showing one manifest's files under another's, which is worse than the cost it saves.

The returned array is SHARED and must be treated as read-only: every caller reads it with find/some/
filter. Copying per call would defeat the point on the very path this exists for.
```

#### ---- the time-series hand-off index ...

```text
---- the time-series hand-off index ---------------------------------------------------------------
ts_access.json indexes the archive routes this deployment may hand a reader off to:
{ausmt_id: {level token: {bytes, url_path}}}. MEMBERSHIP IS THE ACCESS DECISION and it was made in
the build - a withheld, coordinate-gated, adjudication-pending or retired station is absent, and
level_2 (which holds transfer functions, not time series) never appears at all. So no consumer
here re-derives availability from survey metadata; it reads this index and nothing else.
```

#### The archive's own address for one register url_path (the reference ...

```text
The archive's own address for one register url_path (the reference field beside the route).
MIRRORS _stationcheck.ts_access_url (quote(url_path, safe="/")): encodeURIComponent alone eats
`/` and leaves !'()* unescaped where Python escapes them, so the set is spelled out. A mirror,
not a caller, so the agreement is held by the shared vector file
(engine/tests/fixtures/ts_url_vectors.json) pinning both sides; `C5 [REMOTE].zip` is the case.
```

#### The `u` flag is load-bearing, not tidiness: without it the class ...

```text
The `u` flag is load-bearing, not tidiness: without it the class matches per UTF-16 CODE UNIT, so
a code point above the BMP arrives as a lone surrogate and encodeURIComponent throws URIError -
which, from #dlTs, would abort the whole hand-off export with no file and no message. With it the
replacer receives whole code points and encodes their UTF-8 bytes, which is what the Python leaf
does. Pinned by the astral vector in the shared file.
```

## portal/src/doi_harvest.js

#### AusMT DOI citation-harvest core - the SINGLE SOURCE shared by the ...

```text
AusMT DOI citation-harvest core - the SINGLE SOURCE shared by the public Add Survey form
(add-survey.html) and the curator metadata editor (served by the gateway at
/gateway/curator/doi-harvest.js). CONTRIBUTOR-CREDIT-SPEC (§6, curator DOI harvest): the curator
publications rows reuse THIS code rather than duplicating it, so a fix to the registry parsing lands
on both surfaces at once. Both consumers load it as a classic external script tag (it attaches to
window.AusmtDoiHarvest); node tests require() it (module.exports). It is PURE of the DOM and, for
harvestDoi, of a live network (the fetch implementation is injected), so the whole module is unit-
tested with a stubbed fetch and never touches the real registries in CI.

The gateway ships a BYTE-IDENTICAL copy at gateway/static/doi_harvest.js (the gateway app image is
content-blind - it cannot read portal/ at runtime); a gateway parity test pins the two equal so the
shared code cannot drift between the two served copies.
```

#### DOI normalisation: fold a pasted resolver URL down to the bare DOI the ...

```text
DOI normalisation: fold a pasted resolver URL down to the bare DOI the validator records. Strips
an http/https doi.org or dx.doi.org (optional www.) resolver prefix and returns the bare 10.x/y
suffix; a bare DOI (no resolver prefix) and any non-DOI string are returned UNCHANGED. Only doi.org
resolver URLs are folded, a URL-typed identifier row keeps its URL.
```

#### Fold a registry author/creator record ([{family|familyName ...

```text
Fold a registry author/creator record ([{family|familyName, given|givenName, name}]) into a compact
"Family I, Family I" string (family name + given initials). An organisation author (no family/given, a
bare `name`) rides through verbatim. The FULL author list is kept (no data loss); formatCitation does
the "et al." truncation for the compact preview only.
```

#### Parse a Crossref /works/<doi> payload ({message:{...}}) to the emission ...

```text
Parse a Crossref /works/<doi> payload ({message:{...}}) to the emission shape {author,year,title,
journal,doi}. Best-effort and total: a missing key yields "" for that field, a non-object payload
yields null (a miss, not a crash). Journal is container-title; year is issued.date-parts[0][0].
```

#### Parse a DataCite /dois/<doi> payload ({data:{attributes:{...}}}) to the ...

```text
Parse a DataCite /dois/<doi> payload ({data:{attributes:{...}}}) to the same emission shape.
titles[].title -> title, creators[] -> author, publicationYear -> year, container.title or publisher
-> journal (dataset DOIs carry a publisher, not a journal). Same total/guarded posture as parseCrossref.
```

#### Compact human citation for a read-only preview line: "Kay B, Heinson G ...

```text
Compact human citation for a read-only preview line: "Kay B, Heinson G, et al. (2023). Title. Journal."
Three or more authors collapse to the first two + "et al." (the stored author field keeps the full
list). Omits any empty segment cleanly; falls back to the bare DOI when there is nothing else to show.
```

#### Harvest one DOI's metadata: Crossref first (journal papers), DataCite ...

```text
Harvest one DOI's metadata: Crossref first (journal papers), DataCite on any Crossref miss/404
(dataset DOIs). Async and PURE of the DOM; the fetch implementation is INJECTED so tests stub it and
never touch the real network. Returns {ok:true, source, pub} when a registry yields a record WITH A
TITLE (the citation's human anchor -> a confident preview). A thin record (no title) or a total miss
returns {ok:false, reason, pub}, where pub carries whatever partial data exists (at least the DOI) so
the row can expand the manual fields PREFILLED. A non-DOI string never fetches. Every fetch is
try/caught so a network error, a non-JSON body, or a blocked request degrades to a graceful miss.
```

## portal/src/drawer.js

#### drawer.js - station/survey/provenance/citation/download rendering for ...

```text
drawer.js - station/survey/provenance/citation/download rendering for the detail drawer.
A station/survey/provenance file split is a tracked deferred refactor:
feasible (classic scripts, hoisted globals) but low-priority churn for one cohesive concern, and the
no-build smoke harness can't fully verify drawer rendering, so it's its own task - not a loose marker.
```

#### Station drawer (science first), survey cards, survey story, citations

```text
Station drawer (science first), survey cards, survey story, citations. All event handling is
delegated (no inline onclick): .close buttons, [data-act] card actions, [data-cite] citation
copy, [data-prod] product tiles. Cross-module calls (setView/map/refresh) happen at event
time only. Citations live here because this is the only consumer.
```

#### The drawer is a dialog

```text
The drawer is a dialog. role + a base aria-label are set here (index.html's #drawer
element is declared in index.html, so the ARIA is stamped from JS); openStation/openSurvey refine the
aria-label per subject. tabindex=-1 lets us move focus onto the container as a fallback. This does not
disturb the tab keyboard nav (its handler is scoped to [role="tab"] descendants).
```

#### preventScroll: on the FIRST open the drawer is still ...

```text
preventScroll: on the FIRST open the drawer is still transform:translateX(102%) off-screen mid-slide,
so focusing its .close button makes the browser scroll documentElement ~428px left to reveal the
off-screen target, then snap back when the .16s slide settles - a visible page-wide bounce. preventScroll
keeps focus (accessibility) without that scroll-into-view. Guarded fallback for engines lacking the option.
```

#### A dim backdrop shown behind the drawer while it is open on the Surveys ...

```text
A dim backdrop shown behind the drawer while it is open on the Surveys /
Collections / collection-detail views (where the drawer floats over full-width content). NOT on the
map view: there the drawer sits side-by-side with the map, so no scrim. Clicking the backdrop closes
the drawer. It lives in #content BENEATH the drawer and the drawer's left-edge resize handle
(both higher z-index in index.html), so the resizer keeps working. Guarded for the headless harness.
```

#### Two-phase boot: WHAT the drawer is currently showing ...

```text
Two-phase boot: WHAT the drawer is currently showing: {kind:"station",i} | {kind:"survey",sv} | null,
so a phase-2 product landing can re-render exactly that subject in place (rehydrateOpenDrawer). null means
"nothing that reads a phase-2 product is on screen": the drawer is shut, or something that builds its own
markup (the strike rose) owns it.
```

#### ---- two-phase boot: the loading surfaces ...

```text
---- two-phase boot: the loading surfaces ------------------------------------------------------
The drawer is the densest consumer of the PHASE 2 products (tf.json -> the response curves; sci.json ->
the processing/screening rows; manifest.json -> every served-artifact row, badge and download tile), and
almost every one of those surfaces has an HONEST-ABSENCE rendering: "not currently available", "not
recorded", "not stated in EDI", "none currently served", "not evaluated". Each of those is a CLAIM about
the corpus. None of them may be shown for a product that is merely still in flight, so every such site
below routes through hydrGate(): pending -> a loading state; failed -> an explicit could-not-load line;
ready -> the untouched pre-existing rendering. The open drawer re-renders when each gate settles
(rehydrateOpenDrawer), so nothing that showed a loading state stays showing one.
```

#### A hydration re-render rewrites the whole drawer, which would otherwise ...

```text
A hydration re-render rewrites the whole drawer, which would otherwise snap every expander shut under a
reader who opened one, up to three times (once per gate) across a multi-second hydration window. Record
which <details> are open by their summary text (stable across a re-render, and the only key that survives
an innerHTML rewrite) and put them back. A summary whose text legitimately CHANGES with hydration simply
fails to match and reverts to its default state, which is the pre-fix behaviour, never worse. Guarded for
the stubbed-DOM smoke harness (querySelectorAll -> []).
```

#### Activate one drawer tab (ARIA roving-tabindex + hidden toggle)

```text
Activate one drawer tab (ARIA roving-tabindex + hidden toggle). Degrades to a no-op under the smoke
harness (stubbed drawer with querySelectorAll()->[]). Falls back to the first tab for an unknown name.
Two-phase boot: the active tab is remembered so a hydration re-render (rehydrateOpenDrawer) puts the
reader back on the panel they were reading, not back on the default Response tab.
```

#### The display gate, factored: the served-EDI descriptor for a station ...

```text
The display gate, factored: the served-EDI descriptor for a station, {sub,st,d}. When access REFUSES
(a non-open survey with no served EDI artifact) d is null, so neither the header Download action, the
Overview primary-download tile, nor the Files "Transfer function" tile offers a download affordance - 
they say "embargoed"/"metadata only" instead. An OPEN survey keeps today's exact tile text (byte-for-
byte), including the "EDI (via source archive)" fallback the pins assert is ABSENT when embargoed.
```

#### Two-phase boot: the manifest is a PHASE 2 product, so before it lands ...

```text
Two-phase boot: the manifest is a PHASE 2 product, so before it lands there is no honest answer here:
the served-artifact branch and BOTH fallbacks ("EDI (via source archive)" / the embargo wording) are
claims about what this deployment serves. Report the pending state with NO download affordance (d:null,
so headerDownloadBtn renders nothing at all rather than a button that might resolve to the wrong route),
and let MANIFEST_READY re-render the drawer into the real descriptor.
```

#### The sticky-header Download EDI action

```text
The sticky-header Download EDI action. Renders NOTHING where the gate refuses (no download
affordance for an embargoed/metadata-only station) - otherwise a primary button routed through the
same [data-prod] dispatch as the product tiles.
Two-phase boot: rendering NOTHING is precisely this function's embargo signal, so an in-flight manifest
must not be allowed to borrow it. ediDescriptor returns d:null while the manifest is pending (correctly:
it cannot yet know the route), which would silently render an OPEN-access station as embargoed for the
whole flight: absence by omission, the same defect surveyBundleTiles gets a loading tile for. Say what
is happening instead, and claim nothing either way about availability.
```

#### (The Overview "primary download" tile - overviewDownload(), the gated ...

```text
(The Overview "primary download" tile - overviewDownload(), the gated
descriptor rendered as a single product tile inside the Station summary - is REMOVED. It
duplicated the Files tab's Level 2 EDI row and blurred the summary-vs-downloads separation the tabs draw.
ediDescriptor() above is unaffected and still gates BOTH surviving download surfaces: the sticky-header
Download EDI action and the Files tab's EDI sub-row.)
```

#### The DISPLAY-ONLY APA citation rendered inside the Cite box

```text
The DISPLAY-ONLY APA citation rendered inside the Cite box. Identical to apa() except the trailing
DOI is a resolution-aware HYPERLINK: ok/unknown/absent (uncached) -> a doi.org anchor; reserved -> plain
text (never a dead link, honouring the r2 reserved-sweep posture). The COPY/EXPORT path stays apa()
(plain text) - a citation string that lands on a clipboard must remain text, not markup.
```

#### Licence class/badge routed through the CANONICAL contract tables ...

```text
Licence class/badge routed through the CANONICAL contract tables (contract.js LICENSES) - never
a `startsWith('CC')` guess (which mis-classed CC0/ODbL/ODC-BY and every non-CC open licence, and would
have passed a hostile "CCwhatever"). licCanon normalises aliases + case exactly like exports.canonLic.
licIsOpen = "redistributable" (openly licensed - the 'Open licence' facet + the 'Licence verified' star).
licBadgeState maps the canonical id: redistributable -> ok, recognised-but-not-open -> part, else unk.
```

#### This row is CHROME, not a data slot, and it sits on the same drawer as ...

```text
This row is CHROME, not a data slot, and it sits on the same drawer as the licence /
access row, so it takes the human form. licCanon still does the canonicalisation (aliases, case);
licHuman only decides how the canonical id is READ. The SPDX identifier stays untouched wherever a
machine reads it: the exports, the GeoJSON properties and the citation builder.
```

#### A survey's access.level is authoritative for whether the portal has its ...

```text
A survey's access.level is authoritative for whether the portal has its DISPLAY data. "open" (or
absent, which this reader defaults to open) => served, curves present. The producer emits only the three
ACCESS_LEVELS values. Anything else (embargoed | metadata_only | an unknown value)
=> NON-OPEN: the engine emits EMPTY tf series for these stations (the response curves ARE the embargoed
data), so the drawer must render an ACCESS PANEL in place of the four plots rather than four blank frames.
```

#### Withheld-download copy: the TRUTHFUL access reason for a survey with NO ...

```text
Withheld-download copy: the TRUTHFUL access reason for a survey with NO dataset DOI (so no honest
source-archive pointer exists). Embargo and licence are DISTINCT access states: a licence-restricted
station must never be blanket-labelled as embargoed (same access-integrity discipline as the Kalkaroo
Fix). No em/en dashes in this copy; plain punctuation only.
```

#### The boot-loaded coordinate policy for a station ('generalised' | ...

```text
The boot-loaded coordinate policy for a station ('generalised' | 'withheld' | null),
folded onto s by buildState() from coord_policy.json. The engine masks the VALUE (generalised => 0.1°
cell rendered verbatim, withheld => null lat/lon) AND - for a non-exact station - emits this policy
marker so the portal can badge honestly WITHOUT re-deriving precision client-side (forbidden by the
record). Pure (no DOM/Leaflet) so the jsdom driver exercises it.
```

#### The drawer's lat/lon cell

```text
The drawer's lat/lon cell. Withheld => the honest withheld line (no coords). Generalised => the masked
0.1° cell rendered VERBATIM (never re-rounded - the record forbids client-side re-derivation) PLUS the
"position generalised" badge, so a reader knows the ~0.1° number is a custodian generalisation, not a
precise fix. Exact => the verbatim 6-dp position.
```

#### The identity header for the full-station RESPONSE modal (the expand ...

```text
The identity header for the full-station RESPONSE modal (the expand affordance).
Station id, the source site name when it differs from the displayed id, and the data-type chip on the
first line; survey · organisation on the second; the honest coordinate line on the third. Reuses
coordCellHtml VERBATIM so a masked position is never printed raw here (custodian policy holds inside the
modal exactly as in the drawer), and orgNameLink so the ROR link styling matches the drawer header.
```

#### The location-publicity clause is only asserted when EVERY station's ...

```text
The location-publicity clause is only asserted when EVERY station's position is served exact.
When a custodian has generalised/withheld any station, "locations are public" is FALSE - say so.
(Disclosing that a location is generalised/withheld reveals POLICY, not POSITION.)
```

#### Dataset-maturity model

```text
Dataset-maturity model. Five RECORD-STEWARDSHIP dimensions - how completely a record is
archived, licensed and reproducible, NOT its scientific quality (said in the block's subline). Stars =
achieved count. PURE so the star count is unit-testable: flip m.doi / m.ts and the count changes.
"not recorded" / "not available" phrasing per the honesty rules (never "pending").
SPEC §5: the resolution state of the survey's dataset DOI, across BOTH the flat dataset_doi
(engine fallback, m.doi_resolution) and the typed related_identifiers DOI rows. Returns "ok" when at
least one DOI-typed identifier is live-or-uncached (ok / unknown / absent - anything not "reserved");
"reserved" ONLY when a DOI-typed identifier exists and EVERY one is reserved (doi.org's own 404); null
when none is recorded. A reserved DOI is not a working identifier, so it must NOT light the DOI star.
```

#### The AGGREGATE presentation is removed

```text
The AGGREGATE presentation is removed. The "Dataset maturity" heading, the
five-star summary row and the "Record-stewardship maturity ... Not a measure of scientific quality."
explainer are gone; what a reader gets is the ITEMISED list, where every row states its own dimension in
words. The model above is untouched and still drives the per-row stars and their honest notes, so this is
a change of presentation, not of information: the summary said in one number what the rows say in five
lines, and a single star count invited exactly the scientific-quality reading the explainer had to deny.
```

#### Two-phase boot: the "Reproducible" dimension reads sc[SC.sw] (sci.json ...

```text
Two-phase boot: the "Reproducible" dimension reads sc[SC.sw] (sci.json, PHASE 2). An unlit star is a
statement that the dimension was NOT achieved, so the whole LIST waits rather than under-stating a
dimension for a moment and then silently lighting it. With the heading gone the gate is anchored to the
surviving list, and names it in the reader's terms ("stewardship details") rather than by the retired
block title.
```

#### The raw-TS pointer

```text
The raw-TS pointer. A survey's OWN time_series.collection_pid (SMETA.ts_pid) is authoritative
when declared; TS_COLLECTION (the AusLAMP/NCI collection DOI) is only the DEPLOYMENT-WIDE default for
surveys that genuinely belong to that shared collection and declare no PID of their own - never a
stand-in for a survey's dataset DOI (see tsUrlFor's caller sites vs. fetchEdi/exports.js source-citation).
```

#### mth5BundleFor() lived here: the survey's <slug>-tf.h5 bundles[] row ...

```text
mth5BundleFor() lived here: the survey's <slug>-tf.h5 bundles[] row, looked up by slug. It is gone
because every surface that called it was STATION-scoped and therefore reading the wrong scope. The
survey bundle has exactly one surface left, the survey drawer's Downloads grid, and surveyBundleTiles
renders it straight off bundlesForSlug with its two sibling bundles; a second, MTH5-only accessor was
only ever a way for a station surface to reach a survey fact.
A manifest artifact url rendered as the ENDPOINT a reader can GET. A tier=repo row
carries a portal-relative path ("edi/<slug>/<file>.edi") which the hosted site serves under /data/;
a tier=nci row already carries the ABSOLUTE fileServer url, so it is shown verbatim; prefixing /data/
there would print a path that does not exist. Display only; the download path still goes through
dataUrl() (which honours a deployment's data_base_url).
```

#### The Files tab, structured to the NCI data-level standard as a SINGLE ...

```text
The Files tab, structured to the NCI data-level standard as a SINGLE COLUMN of full-width rows
(Packed raw / Level 0 / Level 1 time series -> Level 2 derived processed data with EDI/EMTF-XML/MTH5
sub-rows -> Level 3 models, when ever served -> Publication). Each row carries an explicit ORIGIN tag
("AusMT-derived" vs "source archive") so there is zero ambiguity about what AusMT computed vs what came
from the source. The Phase tensor tile is gone (it is a visual product; it lives in the Response tab).
```

#### Scheme guard: only an http(s) href becomes a product-tile open action ...

```text
Scheme guard: only an http(s) href becomes a product-tile open action (its data-url reaches
window.open). A URL-typed identifier is relatedIdHref's raw value, so a javascript:/data: value
would otherwise route straight into window.open - gate it here and fall through to the reserved /
tsOpen branches (escUrl still guards the block anchor edge).
```

#### THE JOIN RULE, binding

```text
THE JOIN RULE, binding. `m.ts_levels` above is CURATOR-DECLARED and SURVEY-scope;
ts_access.json is CRAWL-VERIFIED and STATION-scope, and the two answer different questions. Read
naively, hasLevel() would gate the hand-off too, so a station with a verified Level 1 file whose
curator never ticked `level1` would read NOT AVAILABLE for a level this deployment can hand it
straight to - exactly the falsehood the verified-at fieldnote exists to prevent. So the ACTION is
driven by the INDEX ALONE and never by hasLevel(); ts_levels keeps its own job, the survey-scope
"exists upstream" sub-text above, and where the two disagree the register wins the station row
while the curator census raises the levels_available gap.

Level 1 is ONE level row with TWO possible actions, format-labelled (the archive publishes MTH5
and NetCDF of the same product); level_2 reaches none of this by design.
```

#### The Level 2 MTH5 sub-row is THIS STATION's own transfer-function h5 ...

```text
The Level 2 MTH5 sub-row is THIS STATION's own transfer-function h5: the manifest files[] row with
format mth5 (the h5/<slug>/<station>.h5 family), read from the very same `arts` rows the EDI and
EMTF XML sub-rows beside it read. It must not read mth5BundleFor(m), the SURVEY-aggregated
<slug>-tf.h5 bundles[] row: with a per-station producer in the build (build_portal
emit_station_mth5) that row offers the WHOLE SURVEY under a station heading (reported:
SA026E showed the 1.74 MB survey bundle in place of its own 174,696 B file).
There is deliberately NO fallback to the bundle. A station with no row of its own gets none: the
engine emits no station h5 for a coordinate-generalised or withheld station, exactly as it serves no
EDI for one, so the honest not-available state the EMTF XML row uses is the truthful answer and the
survey bundle is not a substitute for it. That bundle keeps the surface it belongs to, the survey
drawer's Downloads grid (surveyBundleTiles). Download is wired exactly like the EMTF XML row
({prod:"fetch"}), so the pull is counted by the same masked front-door analytics, and the label
stays TF-only honest ("transfer functions").
```

#### Two-phase boot: all three Level 2 sub-rows resolve against the download ...

```text
Two-phase boot: all three Level 2 sub-rows resolve against the download manifest (PHASE 2), and each of
them degrades to a "not currently available" / "via source archive" line, i.e. statements about what the
build actually served. Render the loading state in place of the three rows until the manifest lands
(the time-series rows above and the publication row below read survey metadata from phase 1, so they
are honest immediately and are left alone).
```

#### The MOST SPECIFIC processing-software string available for a station

```text
The MOST SPECIFIC processing-software string available for a station. The
station-level string the source EDI carried (sc[SC.sw], e.g. "Geotools 4.0.5.12583") wins because it
is the one that names a VERSION; the survey-level declared software field (m.software, often the bare
product name) is the fallback; with neither, the honest "not stated in EDI" stands. No version is ever
synthesised. SINGLE SOURCE for the Provenance tab's own row AND the lineage graph node, so the two
surfaces in one tab cannot disagree about what processed this station.
Two-phase boot: the station-level string lives in sci.json (PHASE 2). The fallbacks are honest ONLY once
that row is known: "not stated in EDI" asserts the EDI carried no software field, and the survey-level
m.software would silently win over a station string that simply had not arrived. So while sci is
unresolved this says so instead. PURE (no DOM) as before; the caller escapes it.
```

#### LINEAGE: programs that WRITE transfer-function files they did not ...

```text
LINEAGE: programs that WRITE transfer-function files they did not process. MIRRORED from the engine's
_edi_catalog.KNOWN_WRITERS - keep the two in step. Matched as a case-insensitive substring, so
"WINGLINK EDI 1.0.22" and "Geotools 4.0.5.12583" both hit.
```

#### The lineage's "File written by" cell: the program that SERIALISED this ...

```text
The lineage's "File written by" cell: the program that SERIALISED this station's file, from
station.json's processing.file_written_by. It must not be shown under the heading "Processing software":
that tells the reader Geotools/WinGLink/MTpy processed the data when those tools only exported a file
somebody else's code had estimated. The exporter belongs under its own heading, and a known exporter is
annotated so the distinction is legible without the reader having to know the tool. PURE (no DOM); the
caller escapes it.
```

#### The formats AusMT actually distributes for THIS STATION, dot-separated ...

```text
The formats AusMT actually distributes for THIS STATION, dot-separated with no
ticks and no "(pipeline)" qualifier. It renders inside the station drawer's lineage graph, so every input
must be station-scoped. Availability comes from the SAME sources the Files tab reads: ediDescriptor for
the EDI (its manifest artifact first, then the served-here fallback, and "no" for an embargoed/
metadata-only station, so a withheld EDI is never listed), and this station's own manifest files[] rows
for the two AusMT-derived formats. A format that is not served is simply ABSENT from the list; the old
line asserted "EDI ✓ · EMTF XML (pipeline)" unconditionally, claiming an XML for the 8 surveys the build
pipeline never produced one for and an EDI for embargoed stations.
```

#### Two-phase boot: every input here is a manifest row (PHASE 2)

```text
Two-phase boot: every input here is a manifest row (PHASE 2). Pre-hydration the list would come back
empty and print "none currently served", a false claim about the corpus and exactly the overclaim in
the other direction that this function was written to remove. Say it is loading instead.
```

#### MTH5 reads the STATION's own files[] row, like its two neighbours

```text
MTH5 reads the STATION's own files[] row, like its two neighbours. Reading the survey's
bundles[] row (mth5BundleFor) makes one drawer contradict itself the moment the two disagree:
the Files tab, reading the station row, said "not currently available" while this line, reading the
survey bundle, listed MTH5 as distributed for the station. Nothing on the screen told the reader
which of the two was about their station.
```

#### A publication reduced to a short lineage cite, "FirstAuthor et al. ...

```text
A publication reduced to a short lineage cite, "FirstAuthor et al. (Year)".
Never fabricates a co-author: names split on "; " when the row uses that separator, else on "," where
THREE or more parts prove a real list (a single "Last, First" name splits into exactly two, so it is
kept verbatim, as does a two-name comma list). Falls back to the title, then the bare DOI, so a row
with no author still says something true. Mirrors doi_harvest.formatCitation's ">2 parts" convention.
```

#### The lineage PUBLICATION cell, read from the survey's related ...

```text
The lineage PUBLICATION cell, read from the survey's related publications
(pubs[], the same list the survey card renders). It must not read the dataset DOI (m.doi), which is the
identifier of the DATA, not an interpretation publication: a survey with a real paper in pubs[] and no
dataset DOI then reads "none recorded" (Newer Volcanic Province 2019 and its 2023 paper). The
first publication renders as a short cite, DOI-linked when it carries one, with a "+N more" tail.
```

#### "Method" renders only where the source file actually states an ...

```text
"Method" renders only where the source file actually states an algorithm or a remote reference, or
while sci.json is still in flight, where the honest answer is that the answer is not known yet. The
structured fields it draws on are empty for most EDI dialects, so an unconditional row would say
"not stated" on nearly the whole corpus: noise in a six-row graph, crowding out the rows that do
carry lineage.
```

#### The file-WRITER, under its own heading, next to the processor it is not

```text
The file-WRITER, under its own heading, next to the processor it is not. Read from station.json
(loadStationFrameLine's fetch), so the cell is a placeholder the async resolve fills in; on a re-render
the cache answers synchronously. Rendered only where that fetch actually runs: for a non-open survey
no station.json science is served, and a permanent loading cell would be its own small lie.
```

#### Titled "AusMT Provenance", not "Processing provenance"

```text
Titled "AusMT Provenance", not "Processing provenance". Every row below is about the
AUSMT PIPELINE's own run (extractor, pipeline version, build date, build commit), not the custodian's
MT data processing, and readers took the old title to mean the latter. The MT processing software the
custodian used has its own row at the top of this tab (and its own lineage node).
```

#### The engine serves impedances AS STORED in the source's declared ...

```text
The engine serves impedances AS STORED in the
source's declared acquisition frame and NEVER de-rotates. When that frame is non-trivial we report
it to the READER - terse, honest, no interpretation. frameLineText is PURE (DOM-free) so a Node pin
(tools/frame_line_test.js) can drive it. Inputs are the VERBATIM station.json `frame` block values:
  declared_azimuth_deg - the recorded acquisition-frame angle (0 => served in the
                                declared-zero / geographic reference; no line by itself).
  tipper_declared_azimuth_deg: present ONLY when the tipper's uniform declared frame DIVERGES
                                from the impedance's declared azimuth (the engine omits it when
                                equal or undeclared), so presence itself is the trigger.
  survey_frame_note - the arm-B "mixed declared frames across stations" note (present only
                                for an inconsistent survey).
Trigger: a non-zero declared angle, a divergent tipper frame, or a survey mixed-frames note.
```

#### Per-station frame facts live ONLY in the per-station station.json (the ...

```text
Per-station frame facts live ONLY in the per-station station.json (the positional catalogue has no
frame column, and adding one would need a contract change). So fetch it lazily at drawer-open - the
SAME product the curator workbench reads - and inject the line if the drawer still shows this station.
Best-effort: an absent/withheld station.json (older builds, no --products, or a file:// portal) just
yields no line, never an error. Only called for OPEN-access surveys (a withheld survey serves no
impedances, so a "served in frame X" line would be false).
Two-phase boot: a hydration re-render calls this again for the SAME station (the innerHTML rewrite blanks
the #frameline placeholder, so it does have to be re-injected), and with three gates that is up to four
identical station.json requests per drawer open. Cache the RESOLVED LINE per station instead: "" covers
every no-line outcome (absent station.json, no frame block, nothing worth saying, an offline/file:// error)
so a station that produced no line is not re-requested either.
The SAME fetch also resolves the lineage's "File written by" cell (station.json
processing.file_written_by), for the same reason and at the same cost: it is a per-station fact with no
catalogue column. One request answers both; the cache holds {line, writer} so a re-render re-injects both
without re-requesting. The entry appears only once the request SETTLES, and it settles either way: an
unreadable/absent station.json resolves `writer` to the honest failure cell, so the placeholder the graph
renders can never stand as a permanent loading state - which would be its own false claim.
```

#### The five Screening indicators, each derived ONLY from a quantity the ...

```text
The five Screening indicators, each derived ONLY from a quantity the pipeline already computes.
PURE (no DOM) so the field->indicator->threshold mapping is falsifiable: flip one input and exactly one
indicator flips state. Each row is {key,label,state,word}; state ∈ green|amber|red|na and `word` is the
plain-language state so meaning never rides on colour alone. A NOT-computable input renders the neutral
grey 'not evaluated' - never a fabricated green. Thresholds echo PROV.parameters where the pipeline
records one (phase-tensor consistency uses PROV pct_periods_3d_threshold, passed in as pctThr); the
others use the documented screen thresholds below.
  d.q          completeness/smoothness check (0..5), null on a tipper-only station -> Smoothness  green>=4  amber>=3
  d.azR/azN    circular resultant length + count of low-skew PT azimuths -> Strike stability  green>=.9 amber>=.75 (need >=3)
  d.beta,betaThr median |β| (deg) vs its PROV threshold skew_3d_deg -> Phase tensor consistency  green<=thr amber<=2*thr
  d.phaseSplit median |φxy − φyx| separation (deg) -> Phase split           green<=15 amber<=35
  d.decades    period band width in decades -> Coverage              green>=4  amber>=2
```

#### The "Transfer function / Download" tile is REMOVED from this summary ...

```text
The
"Transfer function / Download" tile is REMOVED from this summary group. It duplicated the Files tab's
Level 2 EDI row and blurred the summary-vs-downloads separation the tabs exist to draw: a summary
states facts, the Files tab serves bytes. overviewDownload() is deleted with its only call site (dead
code is the trap tests/test_no_dead_prov_feature.py enforces against); the EDI stays downloadable from
the sticky header action and the Files tab. _ssGroup keeps its optional `extra` slot for future groups.
```

#### Two-phase boot: `opts.rehydrate` marks a re-render driven by a phase-2 ...

```text
Two-phase boot: `opts.rehydrate` marks a re-render driven by a phase-2 product LANDING (main.js
wireHydration -> rehydrateOpenDrawer), not by a reader opening the drawer. Such a re-render must not
re-capture the opener, must not pull focus back into the dialog, must not rewrite the hash, and must leave
the reader exactly where they were (same scroll offset, same tab), so the only visible change is the
section that was showing a loading state filling in.
```

#### Sc[SC.dim] (dimensionality) is not surfaced in the drawer screening ...

```text
Sc[SC.dim] (dimensionality) is not surfaced in the drawer screening grid: it is inferable from the
phase tensor + skew, which are shown (strike/|β|/3-D-periods line below). The sc.json field itself
carries it either way, and the map's colour-by-dim mode reads s.dim, so `dim` is deliberately not
destructured here.
```

#### ---- Panel content ...

```text
---- Panel content -------------------------------------------------------------------------------
Response (default) - the four plots FIRST (the centerpiece; all four always shown - phase tensor +
induction arrows are never collapsed and carry no minimise control), then the collapsible "Station
Summary" which absorbs the former Overview
facts. A non-open station shows the
access panel here INSTEAD of the plots (curves ARE the withheld data). #pt_anchor is kept so the
"Phase tensor" related-product scroll target never dangles; the frame line is populated lazily.
The response section carries exactly ONE expand control, on this heading
row, instead of a ⤢ button per plot block (all four opened the same full-station modal). It is rendered
only for an open-access station: without curves openStationModal has no panels to show and would open
nothing, so a control there would be a dead affordance over the access panel.
```

#### Two-phase boot: the curves live in tf.json (PHASE 2)

```text
Two-phase boot: the curves live in tf.json (PHASE 2). An empty TF row renders NO plot at all (plotBlock
guards on an empty series), so painting the plots pre-hydration would show an open-access station as
having no response functions, the loudest absence claim in the drawer. While tf is in flight the panel
carries a loading state instead, and the expand control is withheld with it (openStationModal would find
no panels and open an empty overlay). TF_READY re-renders this section with the curves in place.
```

#### NO SCREENING SURFACE RENDERS in the drawer: the automated indicators ...

```text
NO SCREENING SURFACE RENDERS in the drawer: the automated indicators are not public, so there is no
"screening" panel and no ["screening","Screening"] TABS entry. The pure model behind them
(screeningIndicators) stays defined and is pinned by tools/interaction_test.js, so it cannot rot
while it is unrendered; screeningIndicatorList, _inds and strikeClause are the render side of the
same model and stay with it.
The check screens an impedance, so sc[SC.q] is null on every tipper-only station; the line says so
from the components column rather than showing a bare "n/a" a reader could mistake for a missing
value. A null q on a station that DOES carry Z is the access gate withholding it, and reads
"not available" instead: the two absences have two reasons and must not share one sentence.
Files: the NCI data-level product list. The section-level role chip is dropped; each product row
now carries its OWN origin tag (AusMT-derived vs source archive), so a single section chip would be
wrong (the list spans both source-archive time series and AusMT-derived deliverables).
```

#### Provenance: three source-data rows visible (processing software ...

```text
Provenance: three source-data rows visible (processing software, transfer function
source file+sha · source archive), then the Dataset-maturity stars, then EVERYTHING ELSE
(lineage graph, full provenance table, identifiers, format availability, record metadata, API)
behind collapsed <details>. Nothing is dropped, only demoted; the API box is the last, small expander.
```

#### This station's served artifact rows (manifest `files`), read once and ...

```text
This station's served artifact rows (manifest `files`), read once and reused by the format-availability
badge and the API section below. Empty for a withheld/embargoed survey: the engine emits no manifest
rows for one, so absence here IS the embargo, never a "row we failed to find".
Two-phase boot: that reading of an empty list only holds once the manifest has LANDED, so both consumers
below gate on _manGate first: pre-hydration an empty list means "not received yet", not "not served".
```

#### The same question for MTH5, off the same station rows

```text
The same question for MTH5, off the same station rows. It must not be answered by the SURVEY's
<slug>-tf.h5 bundle (mth5BundleFor), which puts a survey fact under a station heading: a station with
no h5 of its own inside a survey that has a bundle then shows a green MTH5 badge two tabs from a Files
row reading "not currently available". A badge in a station drawer answers about the station.
```

#### The writer row rides alongside the processing-software row for the same ...

```text
The writer row rides alongside the processing-software row for the same reason it does in the lineage
graph: this table is the OTHER surface in this tab that names software, and leaving the exporter out of
it would put the two back in disagreement - the failure processingSoftwareText was factored to prevent.
Same cache, same async fill, own element id (two injection targets, one fetch).
```

#### Coordinate access: a custodian-withheld station carries null lat/lon ...

```text
Coordinate access: a custodian-withheld station carries null lat/lon (masked VALUE), so show the
honest withheld line instead of null-derefing .toFixed. A generalised station carries the 0.1° cell,
rendered VERBATIM (no client-side re-rounding) with a "position generalised" badge driven by the
engine's coord_policy marker. coordCellHtml encapsulates all three; hasPosition is the shared predicate.
```

#### The Metadata & API box collapses to a single small "API" expander at ...

```text
The Metadata & API box collapses to a single small "API" expander at the tab's foot.
No /api tier has ever existed on any AusMT deployment, so the section must never advertise one.
What the site serves is read-only static JSON under /data/, and the section lists that LIVE public
surface for the station in front of the reader.
The only public metadata contracts are mtcat.json
and station.json (survey-metadata.json to come); manifest.json is the download index; everything
else under /data is portal-internal and carries no contract, so the drawer must not advertise it.
The rows are therefore:
  * this station's station.json, keyed by the survey slug + the station id (the same path
    loadStationFrameLine() already fetches, so it is provably the real product location).
    station.json is emitted for EVERY station: a non-served one gets a withheld stub that states
    the access level, so the line resolves and is worth pointing at. dimensionality.json is NOT
    listed: it is served alongside station.json but is not a contract (its fate, folding into
    station.json or staying a feature file, is undecided), and it 404s for every
    embargoed / metadata_only station;
  * this station's OWN served EDI, taken from its manifest artifact row. The url is READ, never
    templated: the served filename is genuinely not derivable from the station id (live corpus:
    station A1 of vulcan-2022 is served as edi/vulcan-2022/Vulcan_A1.edi). No row => no line,
    which is exactly the embargo case (withheld by construction, so there is nothing to link);
  * /data/manifest.json, the download index every artifact is located through. The former
    /data/products/manifest.json twin and /data/surveys.json rows are gone: the twin is retired and
    surveys.json is portal-internal (superseded as a contract by survey-metadata.json).
The trailing pointer sends a reader to the docs site's API reference, where the worked patterns
(per-station manifest fetch, bounding box, checksum verification) live; About carries the quickstart
alone. It is the same stable RTD path About links, so the two surfaces agree on where depth lives.
tests/test_drawer_api_endpoints.py pins the URL string against About's.
```

#### Two-phase boot: the per-station EDI line is READ from a manifest row ...

```text
Two-phase boot: the per-station EDI line is READ from a manifest row, and "no row => no line" is a
deliberate embargo signal. Before the manifest lands there is no row for ANY station, so the list would
silently under-state itself; the loading line says which line is still to come rather than omitting it
in silence. The station.json and manifest.json rows above are static and stay listed immediately.
```

#### The badge set tells the DISTRIBUTED-FORMATS story - EDI, EMTF XML (via ...

```text
The badge set tells the DISTRIBUTED-FORMATS story - EDI, EMTF XML (via pipeline), MTH5, time
series (from the levels metadata) and the licence badge. The bare "DOI" badge is dropped (it failed
as communication; dataset-DOI presence is already conveyed by the DOI stewardship row and the identifiers
block). States stay honest (ok/unknown/no). EMTF XML is ok when a served artifact exists, else part.
Two-phase boot: the EMTF XML and MTH5 badge STATES are manifest-derived, so the whole badge row waits
rather than briefly showing "part"/"unknown" for formats that are in fact served.
```

#### Cite - the citation box

```text
Cite - the citation box. A no-cite survey is EXPLICIT ("custodian citation not recorded - cite
the survey package") rather than a silent AUSMT_SELF masquerade, and the captured attribution statement
(verbatim, else org(year) synthesis) renders alongside. The copy buttons keep their assembly helpers.
```

#### The hash prefixes that describe SOMETHING OPEN IN THE DRAWER, and which ...

```text
The hash prefixes that describe SOMETHING OPEN IN THE DRAWER, and which a
close must therefore hand back to the plain root. #/collection is deliberately absent: it addresses a
full-width PAGE that outlives the drawer (openCollectionPage closes the drawer on its way in), so clearing
it on close would blank the URL of a view still on screen.
```

#### Two-phase boot: re-render whatever the drawer is currently showing, IN ...

```text
Two-phase boot: re-render whatever the drawer is currently showing, IN PLACE, because a phase-2 product
just landed and one of its sections was rendering a loading state. A no-op when the drawer is closed, or
when it is showing something that reads no phase-2 product (the strike rose writes its own markup and
clears the subject). Scroll offset and the active tab are preserved, so nothing jumps under the reader.
```

#### The SURVEY hash is cleaned up on exactly the same terms the station ...

```text
The SURVEY hash is cleaned up on exactly the same terms the station hash
always was. Leaving it behind means the address bar still claims
#/survey/<slug> while nothing is open: reload or Back re-opens a drawer the reader deliberately
shut, and a copied URL shares a state the page is not in. One list, both prefixes, so the two routes
cannot drift apart again. Every close path goes through here (the close control, the map-background
click, the scrim, Escape, a view switch), so this is the single seam that has to be right.
```

#### This EDI isn't redistributable here

```text
This EDI isn't redistributable here. Its dataset DOI (m.doi), when the survey has one, is the
TF source archive and is safe to open. There is NO honest substitute when no dataset DOI is
recorded - TS_COLLECTION is the raw TIME-SERIES collection, not a transfer-function source archive,
and silently opening it mislabels a different dataset as "the source archive" (the pre-C7 defect).
```

#### SLIM survey card

```text
SLIM survey card. Field set is deliberately reduced to: title · organisation ·
collection chip · acquisition year · station count · data-type mixbar · period range · licence + DOI
badges · short description · two actions (View survey, Download). The heavier blocks - the
persistent-identifiers rollup (identifiersHtml), the APA citation (.cite), the spatial extent, the
coordinate-QC flag tally, and the per-format availability matrix (EDI/time-series/MTH5 badges) - do
NOT belong on the card; they render in the survey DETAIL (openSurvey) and the station drawer. The automated completeness/smoothness check is intentionally OMITTED from the
card (it must never read as a card-level verdict) and stays in the detail + drawer with its framing.
```

#### The RATIFIED display order for a person's role phrases when they hold ...

```text
The RATIFIED display order for a person's role phrases when they hold several (SPEC §3.1). Pinned
explicitly (not left to object-key order) so a grouped person's phrases read in ONE stable sequence
regardless of the order their contributor rows were declared in. Keyed against CONTRIBUTOR_ROLE_LABELS.
```

#### One contributor's NAME cell (no role phrase): an organisation links to ...

```text
One contributor's NAME cell (no role phrase): an organisation links to its ROR, a person carries the
ORCID icon-link. Shared by the grouped Contributors list. "" for a nameless row (blank-over-placeholder,
so the caller drops it silently rather than printing an empty placeholder).
```

#### Credit model (SPEC §3/§6): the survey's contributors[] as a COLLAPSED ...

```text
Credit model (SPEC §3/§6): the survey's contributors[] as a COLLAPSED <details> (styled like the
Persistent-identifiers rollup), GROUPED by person. The old surface printed one line per (person, role)
row; a survey with 7 people across 15 role rows printed 15 lines. Now rows dedupe by ORCID (case /
URL-form-insensitive) else by exact name + name_type, preserving first-appearance order, and each distinct
person renders ONE line: the name (ORCID/ROR link as before) then their role phrases comma-joined in the
RATIFIED role order. An unknown/absent role adds no phrase (never a raw token); a nameless row is dropped
silently and never counted. The summary counts the DISTINCT people/orgs. Returns "" (no section, no
placeholder) when the list is absent or empty, matching sourcesListHtml/instrumentPidsHtml.
```

#### Credit model (SPEC §2.1): the survey's ORDERED creators[], the ...

```text
Credit model (SPEC §2.1): the survey's ORDERED creators[], the attribution-author list. Order IS the
attribution order; a person carries the ORCID icon-link, an organisation's name links to its ROR. No role
phrase (that is the contributors[] surface). Reads the pinned seam field verbatim; a creator row is the
same {name, name_type, orcid, ror} shape as a contributor minus the role. "" for a nameless row.
```

#### ONE attribution box, never two

```text
ONE attribution box, never two. The engine builds cite.au from creators[] (CONTRIBUTOR-CREDIT-SPEC
§2.1, names joined "; "), so a second .attn box for the creator names would carry the SAME names
twice. The single box renders the ONE attribution sentence with each creator name ORCID/ROR-linked IN
PLACE (creatorRow), keeping the "; " separators and the "(year)" tail of the plain sentence.
The links are substituted ONLY when the creators reconstruct the sentence's own name string (the §2.1
guarantee: cite.au IS the "; "-joined creators). A verbatim custodian attribution.statement is never
rewritten, and a survey whose recorded citation names someone else keeps that recorded string: in both
cases the flat escaped sentence renders exactly as today, in the SAME single box. That keeps the drawer
byte-identical in TEXT to exports.attributionLine (the CSV / citation-pack / Cite-tab attribution).
Returns "" when the survey has no attribution sentence at all, so the caller omits the whole section.
```

#### When the organisation carries a ROR, its NAME is the link to the ...

```text
When the organisation carries a ROR, its NAME is the link to the ror.org landing page
(replacing the separate ROR logo badge). No ROR -> plain escaped name. esc/escUrl keep a hostile org/ror value inert.
```

#### PID-schema: an instrument's `pid` is a persistent identifier for an ...

```text
PID-schema: an instrument's `pid` is a persistent identifier for an instrument SYSTEM (the AuScope
Instrument Registry URL/handle). It is curator-asserted free text - render it as a link ONLY through
the same escUrl guard the other PID links use (a non-http(s)/mailto/relative value -> href "#", inert),
so a hostile `javascript:...` / `<img onerror=...>` value can never become an executable/anchor. A bare
handle falls back to the handle-resolver host, mirroring pidLink. Absent pid -> no link (caller omits it).
```

#### PID-schema: the per-instrument PID line, shown only when SMETA carries ...

```text
PID-schema: the per-instrument PID line, shown only when SMETA carries the structured `instruments`
list (the engine attaches it ONLY when at least one instrument declares a pid - see _instruments_of).
Each instrument prints its manufacturer/model label with its registry PID as a trailing link; an
instrument WITHOUT a pid in that list prints just the (escaped) label. Returns "" when no list -> the
existing "Instrument model:" line above remains the sole instrument row (byte-identical old surveys).
```

#### D-L1/D-L4 (SPEC §9): `identifies` states WHAT the identifier points at ...

```text
D-L1/D-L4 (SPEC §9): `identifies` states WHAT the identifier points at, in NCI Table 1 data-level terms.
When present it labels the row by LEVEL (e.g. "Raw time series", "Collection", "Entire dataset"),
falling back to the DataCite relation label for a legacy row that carries no identifies. Table 1 order.
```

#### §2a: a typed provenance identifier -> a link whose resolver host is ...

```text
§2a: a typed provenance identifier -> a link whose resolver host is chosen by identifier_type, ALWAYS
through the escUrl guard (a hostile identifier value can never become an executable/relative anchor - 
same posture as pidLink/instrumentPidLink). DOI -> doi.org (unless already a URL); Handle ->
hdl.handle.net; URL -> itself. ANY OTHER type (RAiD, an unknown, or none) -> escaped PLAIN TEXT with NO
anchor: we will not invent a resolver for a type we do not model, and an unlinked value stays inert.
§2a: the resolver URL for a typed identifier, chosen by identifier_type. DOI -> doi.org (unless already
a URL); Handle -> hdl.handle.net; URL -> itself. ANY OTHER type (RAiD, unknown, none) -> null: we do not
invent a resolver for a type we do not model. Shared by relatedIdLink (the block anchor) and the files
tab (which needs the raw URL for a product tile's data-url). escUrl still guards at the anchor/attr edge.
```

#### Render an identifier HONESTLY given its resolution facet from the ...

```text
Render an identifier HONESTLY given its resolution facet from the pid_status
cache (attached by build_portal.apply_pid_resolution). "reserved" = doi.org's OWN 404, a reserved-but-
not-yet-active DOI (e.g. a freshly-minted NCI PID whose handle mapping is not live) -> plain escaped
text + a muted "(reserved - not yet active)" note, NEVER an anchor: we do not ship a dead link. "ok" /
"unknown" / absent (no cache) -> the caller's normal link, byte-for-byte as today (unknown = today).
```

#### The Provenance-tab "Source archive" cell

```text
The Provenance-tab "Source archive" cell. Preference: the related_identifier that IDENTIFIES the source
data by NCI data level (raw_packed, then collection, then entire), rendered with the SAME resolution
honesty the Files tab / identifiers block use (reserved -> plain text + note, else a typed link); then
the flat dataset DOI; then the raw-TS collection cell; else the honest "not recorded". Derives from the
same typed provenance the Files tab keys off, so an identifier-bearing survey shows its real archive
instead of "not recorded". Pure (reads m only) so the derivation is unit-testable.
```

#### §2a: the related-identifiers block - one line per typed relation ...

```text
§2a: the related-identifiers block - one line per typed relation (SMETA.related_identifiers, served by
the engine mapper as always-a-list). The relation prints as a human label, the identifier as a
type-linked value, the custodian (when present) in muted text. Empty list -> "" (the section simply
does not render, mirroring instrumentPidsHtml). Non-mapping entries are skipped defensively.
```

#### §2a: "a persistent dataset identifier exists in this survey's ...

```text
§2a: "a persistent dataset identifier exists in this survey's provenance chain" - the ratified reading
of the DOI maturity badge. TRUE when a minted dataset DOI is set OR any typed related_identifier is a
DOI, so a curator survey (dataset_doi null, the DOI living in the typed provenance list) still lights
the badge. Shared by BOTH badge sites (station format-availability + survey card) via this one predicate.
```

#### The rollup renders ONLY the rows that carry a value

```text
The rollup renders ONLY the rows that
carry a value. No "not recorded", no "(no PID)", no "not recorded in source metadata" noise; an instrument
with a model but no PID shows just the model; a group with no content is omitted (heading included). The
underlying keys are still SERVED - only the empty ROWS are dropped, and the retired Survey-PID row
stays gone.
```

#### One related-publication citation

```text
One related-publication citation. Robust to two real-corpus shapes: (1) a DOI value that is already a
full https://doi.org/ URL (the NVP harvester emits URL-form DOIs); the prefix is stripped before the
href/label so the resolver gets a single prefix (no doi.org/https://doi.org/ double-prefix) and the
label reads doi:<id>; (2) a row missing author/year/journal, the empty "(). ." skeleton is skipped and
only the present pieces (title + link) render.
```

#### Discovery controls for the Surveys view

```text
Discovery controls for the Surveys view. State lives in this module (the controls are
static in index.html; the coordinator/rail filters are untouched). FORBIDDEN by contract: sorting or
faceting by the automated completeness/smoothness check - the screen must never become a ranking, so
none of the sort modes or facets below reference s.q / the check.
```

#### The survey-level reading of ONE rule, which lives in filters.js ...

```text
The survey-level reading of ONE rule, which lives in filters.js (passesYearWindow); this is not a
second verbatim copy of it. Only the field names differ between the two surfaces, so only the field
names belong here. Guarded like the other cross-module calls: a harness that loads drawer.js without
filters.js has no filter UI either, which is the same no-op the rule itself returns.
```

#### "View on map" from the survey drawer header

```text
"View on map" from the survey drawer header. It must not CHECK ONLY this survey in the rail tree
and refresh(): that removes every other survey from the map, so the reader loses all context for where
the survey sits in the national coverage, and closing the drawer leaves the map still filtered. Other
surveys STAY VISIBLE BUT DIMMED, so this touches neither the tree nor the filter
state; it dims (opacity only, see setSurveyDim in map.js) and frames. Nothing to reload on close.
```

#### The drawer is position:absolute over the RIGHT of the map (index.html ...

```text
The drawer is position:absolute over the RIGHT of the map (index.html #drawer, z-index 1100), so a plain
fitBounds centres the survey in the full container and lands half of it under the panel. Pad the fit's
bottom-right by the drawer's CURRENT rendered width (it is user-resizable, so this is measured, never the
420px default) to frame the extent in the map area the drawer does NOT cover. Returns a plain array
padding, which Leaflet's toPoint accepts, so the value is inspectable by the jsdom driver. Width 0 (drawer
shut, or the headless DOM's zero-size boxes) degrades to today's unpadded fit.
```

#### Stage B (selection-state isolation): scoping the map to one survey is a ...

```text
Stage B (selection-state isolation): scoping the map to one survey is a TEMPORARY LENS. Snapshot the
tree BEFORE mutating it (enterSelectLens, filters.js) and enter Select & download so the downloads this
selection enables are visible (they live in the Select pane). The lens is restored when the visitor
returns to Browse or leaves the map. The Surveys catalogue reads none of this tree state
(surveyVisible), so the scoping can never empty it; the snapshot keeps the MAP tree honest too.
```

#### Survey footprint mini-scatter

```text
Survey footprint mini-scatter. The in-plot corner label is gone; instead the plot box carries OUTSIDE
axis ticks: 3 latitude labels down the left margin, 3 longitude labels along the bottom (1 dp, degree
suffix, monospace 9px), with a small tick mark on the box edge at each. The SVG is responsive (viewBox +
width:100%) so it scales inside the resizable drawer. A degenerate/withheld-coords bbox (0° box) draws
no dots and repeated 0.0° labels but never crashes (dx/dy carry the ||1 guard; bbox is empty-safe).
```

#### The "Related surveys" section and its relatedSurveys() scorer are ...

```text
The "Related surveys" section and its relatedSurveys() scorer are REMOVED
. The score mixed same-org, bbox-overlap and same-country into one unexplained ranking, so the
section asserted a relationship the corpus does not record; a reader could not tell why a survey was
listed. Related PUBLICATIONS (a declared, citable relation) stay exactly as they were. Deleted rather
than commented out because nothing else called it and a dead scorer is a maintenance trap (the same
posture tests/test_no_dead_prov_feature.py enforces for dead survey-metadata branches).
Survey-level summary (10-second view): aggregates of already-computed per-station values + survey metadata only
```

#### The "dimensionality mix (screening only)" row was removed from this ...

```text
The "dimensionality mix (screening only)" row was removed from this table (dimensionality
is inferable from the phase tensor + skew). The per-station dim tally that fed it (dimCount/nClass/
dimPct) is gone with it; sc[SC.dim] itself is untouched (data products unchanged - display only).
Two-phase boot: the remote-reference tally and the derived processing-software mode come from sci.json
(PHASE 2). "not recorded" and the m.software fallback are claims about the source EDIs, so those two
rows wait for SCI_READY; every other row here is catalogue/survey metadata and is honest immediately.
```

#### Pre-built per-survey download bundles from the manifest (EDI zip + ...

```text
Pre-built per-survey download bundles from the manifest (EDI zip + EMTF-XML zip always when served;
survey MTH5 only when the survey_h5_enabled flag produced one). Empty string when the survey isn't
served. The MTH5 bundle holds TRANSFER FUNCTIONS ONLY (never time series), and the label says so,
matching the engine's <slug>-tf.h5 filename.
```

#### ---- the survey DATA AT EVERY LEVEL tile grid ...

```text
---- the survey DATA AT EVERY LEVEL tile grid ---------------------------
The block is a DATA-LEVEL grid: six fixed slots, always all six, rendered in the Downloads tile styling.
A collapsed <details> of whatever single-value identifier rows happen to be recorded varies in LENGTH
per survey, which hides from the reader what a survey has NOT deposited; six fixed slots cannot.
The vocabulary is the citable NCI scheme of Rees et al. 2019 - the same family the STATION Files tab
already speaks - and the slot keys ARE the shipped `identifies` enum (engine/schema/mtcat.schema.json),
so a slot can never drift from what the survey validator permits to publish. There is deliberately no
"Level 4 / models" slot: models ARE level3 in the canonical scheme.
```

#### [identifies key, tile name, one-line description]

```text
[identifies key, tile name, one-line description]. WORDING RULE: where a slot names the
same level as a station Files-tab row (relatedProducts -> tsLevelRow/level2), the description carries that
row's gloss VERBATIM, so the two surfaces read as one vocabulary rather than two paraphrases:
  level0 -> "instrument-recorded, full resolution"   level1 -> "calibrated, resampled, filtered"
  level2 -> "transfer functions"
Level 1 names its MTH5 TIME-SERIES holding explicitly, because the Downloads grid separately offers
"Survey MTH5 (transfer functions) / TFs only" - level-2 CONTENT in the same container format. The two
must never read as the same object, so one says "time series" and the other keeps saying "TFs only".
```

#### SLOT ALIASES

```text
SLOT ALIASES. `entire` - ONE record covering all levels, the
shape the survey template gives a state-survey landing page - IS the umbrella record the Collection
slot names, so it FILLS that slot instead of falling through to the extra-tile bucket. Gawler Phase 2
is the case that forced this: its only umbrella identifier is the GSSA/SARIG record (identifies:
entire), so the drawer read "1 of 6 recorded" with an empty Collection tile and an orphan hanging
under the grid, when the survey plainly HAS deposited its umbrella record.
COLLISION RULE: when a survey carries BOTH `collection` and `entire`, the EXACT key takes the slot and
the alias renders as an EXTRA tile below the six. Two properties this preserves, in order: nothing is
ever silently dropped (the extra-tile rule is the section's one answer to "recorded, but not one of the
six"), and "N of 6" counts SLOTS, so a colliding pair tallies one, never two. Declaration order in the
survey.yaml is irrelevant - the exact match wins wherever it sits in the list.
```

#### One tile

```text
One tile. UNRECORDED is explicit: muted BUT VISIBLE (.prod.dis + a hollow dot +
"not yet recorded"), never omitted, so the deposit chain has the same shape on every survey and a gap is
legible as a gap. RECORDED renders the identifier with the SAME resolution honesty every other identifier
surface in this file uses (reserved -> inert plain text + note, never a dead link) and the custodian as
the repository tag. SCHEME GUARD, mirroring the Files tab: only an http(s) href becomes the tile's ACTION,
because a URL-typed identifier is relatedIdHref's raw value and a javascript:/data: value would otherwise
route straight into window.open; such a row still SHOWS its value, it simply carries no action.
```

#### The whole section: the six fixed slots, then any identifier NO slot ...

```text
The whole section: the six fixed slots, then any identifier NO slot claimed (directly or through
SLOT_ALIASES) as an EXTRA tile below them. Nothing is ever silently dropped - the `identifies`
vocabulary may grow, and a row this build does
not model must still be visible rather than vanishing between releases. "N of 6" counts the six FIXED
slots only (an extra tile is not one of the six), per the slot mapping.
```

#### Resolve the six slots ONCE, recording which rows they consumed

```text
Resolve the six slots ONCE, recording which rows they consumed. With aliases in play, "this row's
identifies is not a slot key" is not a safe proxy for "no slot took it", and getting that wrong
would either drop a row or render it twice - so the consumed set is tracked explicitly and the extras
bucket is derived from it. `taken` also makes single-consumption structural: no row can fill two slots.
```

#### Unclaimed rows: an out-of-slot `identifies`, the alias that LOST a ...

```text
Unclaimed rows: an out-of-slot `identifies`, the alias that LOST a collision (a survey declaring both
`collection` and `entire`), or a legacy row that predates the level model and carries only a DataCite
relation. Labelled by the same tables the retired Related-identifiers block used, so the label
vocabulary is unchanged for these rows.
```

#### The survey drawer OWNS its route the way openStation always has

```text
The survey drawer OWNS its
route the way openStation always has. Without this, opening survey B over survey A left #/survey/<A> in
the address bar - the same stale-URL defect the close path had, one step further along. Skipped on a
hydration re-render (which must never rewrite the URL) and on a survey with no slug to address.
```

#### Section order - (1) title+description, (2) geographic footprint, (3) ...

```text
Section order - (1) title+description, (2) geographic footprint, (3) station count +
period-range stats, (4) licence + downloads, (5) acquisition + processing, (6) contributors + funding,
(7) publications, (8) identifiers (the rollup), (9) release history. Content is unchanged from before -
only the order. Acquisition/processing are carried inside the survey-summary table (sections 3/5 share
That atomic block). Contributors (credit model, SPEC §3) do not trail
below Downloads, they sit inside the ATTRIBUTION block directly beneath the attribution box.
Downloads move up ahead of funding/publications/identifiers; release history moves last.
```

#### The captured attribution statement rendered where the survey's ...

```text
The captured attribution statement rendered where the survey's attribution lives (verbatim
custodian statement, else the org(year) synthesis). That sentence is ONE box
(attributionBoxHtml) carrying the creator names ORCID/ROR-linked in place, never a second names box,
and the collapsed "Contributors (N)" details moves UP to sit directly beneath it (credit reads as one
block: who to attribute, then who did what) instead of trailing below Downloads. The upstream
"Source datasets" list follows.
```

#### The identifiers rollup is the always-open DATA-LEVEL tile grid

```text
The identifiers rollup is the always-open DATA-LEVEL tile grid. The
Organisation ROR row is gone with it - the custodian's ROR still reaches the reader as the
link on the organisation name in the header subline above (orgNameLink) and on the About page.
identifiersHtml() itself is untouched and still serves the STATION drawer's identifiers expander.
```

#### Collections INDEX (the "Collections" tab): one rich card per collection ...

```text
Collections INDEX (the "Collections" tab): one rich card per collection in COLL, opening the
full-width collection page. A collection appears automatically when surveys share a collection.id.
The participating organisations of a collection, derived from its member surveys' SMETA (deduped, sorted).
```

#### ONE rich collection card at ANY count, with no compact variant beside it

```text
ONE rich collection card at ANY count, with no compact variant beside it.
Title + type/status, the FULL abstract (no 240-char truncation, no Show more), the footprint
scatter, rollup stats, participating organisations, and a prominent Explore action. Rendered into a
responsive auto-fit grid (index.html .collfeature-grid) so it reads from one collection today to
several (WA-MT, Vulcan) soon. Keeps the .scard.collfeature class the styling + tests key off.
```

#### Collection footprint

```text
Collection footprint. Fixed-Australia extent with a simplified coastline + state-
boundary outline (vendor/au-outline.js - public-domain Natural Earth, see that file's header) drawn
BENEATH the station dots; dots are COLOURED BY MEMBER SURVEY with a small legend. Degrades cleanly when
AU_OUTLINE is absent (e.g. the headless harness doesn't load the vendor asset) - dots + legend still
render. The projection is a plain equirectangular fit of the fixed AU box, so the outline and the dots
stay registered; the canvas aspect matches the box to avoid squashing.
```

#### Fluid (viewBox + width:100%) so it scales inside its container; `maxW` ...

```text
Fluid (viewBox + width:100%) so it scales inside its container; `maxW` optionally raises the max-width
cap (the detail-page hero gives it more room than a list card). W stays the viewBox coordinate space so
the geometry is identical regardless of rendered size.
`mark` puts the AuScope mark in the panel's bottom-left corner, matching the static collection page's
figure. Off by default: the list card is a thumbnail with no corner to spare, and the detail hero is the
full-size map this belongs on. The mark is a sibling of the SVG inside a panel capped at the same width,
never an <image> in the SVG, so the geometry stays what the colour and dot pins measure.
```

#### The members that PLOT, which is the engine's `present` list (_pages.py ...

```text
The members that PLOT, which is the engine's `present` list (_pages.py _collection_scatter assigns
colours over the members that have positioned stations) expressed with the SPA's own predicate. A
wholly coordinate-withheld member is a live corpus state; counting it here gives this ramp a
different n from the page's and moved every later member's colour one step along it.
```

#### A two-column HERO on wide screens: the abstract (+ the ...

```text
A two-column HERO on wide screens: the abstract (+ the type/status/counts subline) on the left, the
fluid footprint scatter on the right; the stat tiles span full-width below and the member table
breathes to full width. No .collnote explainer renders. Single column on narrow screens
(index.html .collhero).
```

#### Yield to an open plot-expand modal - its own Esc handler (plots.js) ...

```text
Yield to an open plot-expand modal - its own Esc handler (plots.js) closes it, so the drawer
must NOT also close underneath it. Otherwise Escape closes the drawer as before.
...and to an open wget/curl dialog, for the same reason: it is aria-modal, its own Esc handler closes
it, and without this yield Escape closed the drawer BEHIND an open dialog. Tested by not-hidden rather
than by existence: unlike the plot modal, that dialog's markup is always in the document.
```

#### Discovery-controls wiring for the Surveys view

```text
Discovery-controls wiring for the Surveys view. Static registrations - the controls
live in index.html's #surveysview and exist at parse time (drawer.js loads after them). Each handler
mutates this module's discovery state then re-renders the cards; the container listener on #facetChips
survives its own innerHTML re-render (the container element is stable, only its children change).
```

## portal/src/exports.js

#### Scope-following downloads + toast/snackbar

```text
Scope-following downloads + toast/snackbar. Every download acts on scopeSel() (the selection,
else the filtered corpus); paintDownloadRows() owns the Download block's scope line, priced rows
and disabled states. Citation/EDI helpers are referenced at click time only.
CSV/GeoJSON columns are built from the station object + the positional sci row sc[] (sc[SC.q]=q,
sc[SC.qb]=qb, sc[SC.rr]=rr, sc[SC.sw]=sw, sc[SC.dim]=dim) - see the legend in data.js / data-files.md before
reordering export columns.
```

#### ---- the hand-off snackbar ------------------------------------------ ...

```text
---- the hand-off snackbar ------------------------------------------
PROGRESS BELONGS TO THE BROWSER: a hand-off is a 302, the bytes travel browser-to-archive, and
CORS forbids fetching the payload in-page. No progress bar, no download panel, no completion
claim - the page says only what it handed over. It differs from toast() in exactly one way, which is why it is a second element and not a
second use of the first: it can carry ONE action, the wget command for a whole list.
```

#### CSV rows (header + one per station)

```text
CSV rows (header + one per station). Derefs the positional sci row sc[SC.q/qb/rr/dim/sw] at THE export
call site - extracted from the click handler so it is unit-testable: tests/test_populated_portal_smoke.py
value-binds these columns, which is the ONLY coverage of the qb/rr/sw call sites (buildState/drawer
don't expose them). Output is unchanged from the inline version.
```

#### `license`, `license_url` (the deed URL keyed off the canonical id) and ...

```text
`license`, `license_url` (the deed URL keyed off the canonical id) and `attribution` (the
rendered attribution line - the custodian's verbatim statement when declared, else the org(year)
synthesis) travel with the exported rows so the rights don't get stripped when a CSV of the selection
is shared.
The station CSV DROPS six columns - quality, quality_basis, remote_ref,
dimensionality, software and file - leaving a lean identity/geometry/rights row. (These derived-screen
and per-station-file fields stay in the GeoJSON export; the smoke test's column value-binds moved to
the reduced set.) The rights columns license/license_url/attribution stay.
```

#### The LICENSE.txt content that travels inside the client-side ...

```text
The LICENSE.txt content that travels inside the client-side bulk-download zip, mirroring the
engine's _license_text.license_instrument_text EXACTLY - the two implementations are pinned to a shared
vector file (engine/tests/fixtures/license_instrument_vectors.json), consumed by both an engine pytest
AND portal/tests/license_text_vectors.test.js, so they cannot drift silently. Deed URLs + attribution
PROFILES come from the generated LICENSES and PROFILES tables, keyed by the canonical id.
Signature MIRRORS the Python leaf (lic, licensor, year, attribution, sources, changes) so the shared
vectors drive both sides with identical inputs; the m -> (who, yr, attn) derivation lives at the call
site below (as it does in build_portal), not inside the renderer.
```

#### Each custodian profile's s.5 disclaimer once (dedup, first-seen), the ...

```text
Each custodian profile's s.5 disclaimer once (dedup, first-seen), the final paragraph(s)
of the Source-datasets block - a profile-level legal notice, so it renders even under a verbatim
statement. Byte-inert when no source's profile carries a disclaimer. Pinned to the Python leaf.
```

#### Two-phase boot: quality/dimensionality/remote_ref ride each GeoJSON ...

```text
Two-phase boot: quality/dimensionality/remote_ref ride each GeoJSON feature and come from sci.json, a
PHASE 2 product. An export is a FILE that outlives the page, so it must never carry a value the portal
simply had not received yet. AWAIT the gate (already-resolved in the normal case, so the click is
unchanged once hydration is done) rather than degrade.
If sci.json FAILED, awaiting settles on nothing: sciRow returns [] for every station, and the
quality/dimensionality/remote_ref keys would vanish as undefined (JSON.stringify drops them) with no
trace of why. remote_ref carries its own per-row guard besides: a station with no usable sci row
omits the key rather than claiming false, matching its two siblings. So when the product is not usable the
three screening properties are omitted DELIBERATELY and the FILE ITSELF carries the reason: a toast does
not travel with the download, and whoever opens this file next has no other way to learn the difference
between "not screened" and "the screening data never loaded".
```

#### `quality` is the completeness/smoothness diagnostic (sci.json column ...

```text
`quality` is the completeness/smoothness diagnostic (sci.json column q), never a quality ranking; the
property keeps the name it shipped under because renaming it would break every saved GIS project
joined on it. It screens an impedance, so it is null on a tipper-only station (`components` without
`Z`) and on a station whose survey withholds its science, and it is ABSENT rather than null when the
screening product failed to load, which is the distinction GEO_SCI_UNAVAILABLE above exists to state.
Extracted from the click handler for the same reason csvRows was (see above): the honesty rule now has a
branch here, and a branch that only exists inside an onclick is a branch no test can reach.
```

#### POINTERS: the merged provenance-and-hand-off document, one per scope ...

```text
POINTERS: the merged provenance-and-hand-off document, one per scope station. It is
the union of the two files it replaces: EVERY station in scope appears (the archive-pointers
rule), and stations with verified open files carry actionable levels[] rows (the fetch-list
rule), including explicit gap rows where a route could not be built. source_doi is the survey's
OWN dataset DOI or null with the reason - never the time-series collection DOI standing in for a
TF source archive (the pre-C7 mislabel the EDI zip's gap file already refuses).
```

#### ---- the time-series HAND-OFF list ...

```text
---- the time-series HAND-OFF list ---------------------------------------------------------------
The offer is a POINTER FILE, never a server-built zip or a fourth exportSelectionFormat:
AusMT holds none of these bytes, and packaging them would make
this portal a proxy for an archive that already serves them properly.

PORTAL-GENERATED, not gateway-generated. A fifth public gateway route would touch two
independent allowlists, their parity test, both deny-by-default blocks and the route table; the
/go/ts/ path shape already carries survey, station and level, which is the whole of what the
measurement needs. That is also why nothing here calls track(): the request the reader actually
makes is counted at the front door, from the route it names.

Each row states the ROUTE, because that is the string to fetch, and the archive's own address
alongside as an inert reference - so the file still names its bytes if AusMT is down, without
pretending that address is what you were asked to fetch.
```

#### The output PATH for one fetched level: <survey slug>/<level>/<archive ...

```text
The output PATH for one fetched level: <survey slug>/<level>/<archive basename>. The bare basename is
NOT unique - across the corpus a station's level0 and level1_mth5 can carry the same one, and basenames
repeat across surveys - so writing by basename alone lets a second product overwrite (or, with curl -C -,
RESUME INTO and corrupt) the first. Keying by slug+level is collision-free over every corpus row, and
mirrors the selection zips' own survey-slug namespacing.
```

#### POSIX single-quote a token so a register-derived path segment is ...

```text
POSIX single-quote a token so a register-derived path segment is LITERAL in bash/zsh: inside single
quotes $( ), backticks, ", ; and space are all inert, and an embedded ' is close-escape-reopen'd. The
filename is the one field taken VERBATIM from third-party ts-index registers with no charset gate
upstream, so it is quoted at the client (belt-and-braces; the url is already per-segment encoded).
```

#### Windows curl.exe may be pasted into PowerShell OR cmd, which quote ...

```text
Windows curl.exe may be pasted into PowerShell OR cmd, which quote INCOMPATIBLY (PowerShell interpolates
$()/backtick/$var inside "", cmd expands %VAR%; single quotes are literal text in cmd, not quoting), so
no one wrap is both safe and faithful in both. The built path is therefore restricted to a
metacharacter-free charset (others -> _), which leaves double quotes inert in either shell. The bytes
are unchanged; only the LOCAL name is normalised, and WGET_OS_NOTES.win says so.
```

#### The unix form

```text
The unix form. One `wget` per file, not a single --content-disposition -i - here-doc: the header
filename lands in the CURRENT dir, so two files that share a Content-Disposition name would collide and
wget silently forks the loser to name.1. -P <slug>/<level> gives each its own directory - wget creates
the tree and the collision cannot happen. -c makes a re-run RESUME (a completed file is skipped, a
partial continues; the archive serves ranges). -q --show-progress keeps one clean bar per file. Single
quotes keep the prefix and the route literal. It fetches the ROUTES, never the archive addresses beside
them, because the route is what the front door counts.
```

#### The curl form, for macOS and Windows: curl is PREINSTALLED on both ...

```text
The curl form, for macOS and Windows: curl is PREINSTALLED on both (Apple ships it; Microsoft ships a
real curl.exe on Windows 10+), so neither platform is sent to a third-party binary. Output names are
explicit -o paths (which is also what lets -C - resume coexist with names: curl's header-naming -J
refuses -C), namespaced by slug+level so no two collide, with --create-dirs building the tree. -L
follows the 302s. The name is shell-quoted at the client: single quotes on macOS (POSIX, verbatim), a
safe-charset restriction on Windows (curl.exe is pasted into PowerShell or cmd, which quote
incompatibly). The url stays double-quoted - it is already per-segment encoded, so it carries no
metacharacter. On Windows the exe is named in full: PowerShell aliases bare curl to a different command.
```

#### One level's hand-off for the current scope, from the Download block's ...

```text
One level's hand-off for the current scope, from the Download block's time-series rows. The row
names its own level, so no hidden chooser state can narrow it (the defect it replaced: a collapsed
accordion's level toggles silently scoped the old Time-series list export).

A SMALL scope gets its FILES, not a file about them: each route is
handed to the browser exactly as the drawer's single-station tile hands one, and the browser
Owns the downloads and their progress; AusMT still hosts and fetches nothing, because the
302s do the pointing. The gate is the TOTAL SIZE, not the file count: up to the gate the
browser is the best tool, and beyond it the offer is the TERMINAL
COMMAND, which is resumable and verifiable at a scale where browser downloads quietly are not.
5 GB, lowered from 10: raw_packed files run 0.2-1.2 GB each, so 10 GB could
hand a browser two dozen large transfers at once, which is where the browser stops being the
better tool. 5 GB keeps the direct path to a handful of files.
```

#### The wget dialog: show the command (scrollable), say where to run it ...

```text
The wget dialog: show the command (scrollable), say where to run it, THEN offer the copy - a
reader should see what lands on their clipboard. Per-platform tabs, with the DETECTED platform
pre-selected (detection only picks the default tab; researchers copy commands for other
machines, so all three stay one click away). Guarded binds like every other control.
One line per platform: what to run it with, and nothing the shared instructions above already say
.
```

#### Over the gate the terminal command IS the offer, so the dialog opens ...

```text
Over the gate the terminal command IS the offer, so the dialog opens straight away rather than
behind a snackbar action: an intermediate "Show terminal command" step is a click between the
reader and the only thing that can serve them at this size. No standalone list file either -
the metadata pack already carries the same document as handoff.json, so saving it twice put an
Unwanted .json at the head of the reader's downloads.
```

#### The human-readable CITATIONS.txt line for ONE entry

```text
The human-readable CITATIONS.txt line for ONE entry. When the entry has NO DOI the
pack SAYS SO explicitly - "[no DOI assigned]" - rather than silently omitting the field, because a
reference pack should state the absence. The .bib/.ris twins simply OMIT their doi=/DO/UR
fields (drawer.js apa/bibtex/ris already guard on a falsy doi, d2bc616); emitting placeholder text there
would be ingested by reference managers as real bibliographic data - the pre-C22 defect, where
AUSMT_SELF.pb carried "(DOI to be minted per release via Zenodo)" into every no-DOI publisher field.
```

#### An EXPLICIT fallback - a survey with no custodian cite block must not ...

```text
An EXPLICIT fallback - a survey with no custodian cite block must not be SILENTLY rendered as
the AusMT brand, which a bare `m.cite||AUSMT_SELF` does. The human line SAYS the custodian
citation is unrecorded and points at the AusMT package citation instead; the .bib/.ris twins keep
the package fallback but under a survey-slug key, never claiming to BE the custodian's own citation.
```

#### The acknowledgement is DATA-DRIVEN, assembled from the ACTUAL selection ...

```text
The acknowledgement is DATA-DRIVEN, assembled from the ACTUAL selection - the custodians of
record (attribution.custodian, else the organisation) plus each unique source-dataset attribution
(verbatim statement, else the profile-rendered form). The AusLAMP/AuScope/NCI sentence is included
ONLY when the selection references that archive (a survey's ts_pid or a source pointing at NCI/AuScope
/ the collection DOI), never a hardcoded paragraph on every pack.
```

#### Every data download travels with its metadata: the citation files, the ...

```text
Every data download travels with its metadata: the citation files, the
station table and the geometry for the SAME station set, written beside the data - the licence
rights-travel principle extended from LICENSE.txt to citation and context. Awaits the sci gate
so the GeoJSON keeps its honesty rules (the omission note when screening never loaded).
```

#### The BULK-EXPORT LABEL

```text
The BULK-EXPORT LABEL. The multi-file export below marks each file fetch it
issues with this query flag, so the server-log aggregator can tell a drag-selected bulk export from a
single station download. It is a LABEL on a request that already happens: no extra request, no beacon,
nothing about who is asking. The flag rides the QUERY and never the path, because the aggregator strips
the query before attributing a download, so a flagged and an unflagged fetch of the same file are still
one file (see deploy/scripts/aggregate_stats.py: the dedupe key is the query-stripped path).

ONLY this flow labels anything. The drawer's own single-station downloads go through drawer.js
downloadUrl() and stay unlabelled, which is the whole point: an unlabelled fetch is exactly what
"single" means downstream, so leaking the flag onto that path would reclassify every single download
as a bulk one. The gate is therefore the CALL SITE, not the shared dataUrl() helper both use.
```

#### Rights travel with the bytes: one LICENSE.txt per included survey ...

```text
Rights travel with the bytes: one LICENSE.txt per included survey, beside that survey's files
(same slug namespace). Built entirely from client-side SMETA (no fetch), mirroring the served-zip
instrument. The m -> (who, yr, attn) derivation mirrors build_portal's LICENSE.txt call site;
sources/changes ride on SMETA when present (dormant until a survey carries an attribution/sources
block). Extracted from the EDI flow, byte for byte, when the EMTF XML and MTH5 selection zips arrived:
three archives of the same custodian's files must carry the same instrument, and a second copy of this
derivation is exactly how they would come to differ. `included` maps survey name -> zip subdirectory.
```

#### The SELECTION-ZIP EVENT SHAPE, shared by all three bulk buttons

```text
The SELECTION-ZIP EVENT SHAPE, shared by all three bulk buttons. `format` is what the reader receives
and `files` is what is inside it, so the three flows are one comparable series: an operator can ask "how
often is a selection taken as an archive" and "which format is asked for" separately, and the answers
still add up. The three must not disagree: an EDI zip reporting format:"zip" beside derived-format
zips reporting format:"emtfxml"/"mth5" puts ONE action in two vocabularies. Nothing downstream can
tell a naming difference from a behaviour difference, so a chart of "zip exports" would silently
exclude two of the three buttons and a chart by format would double-count the third against the
single-file downloads, which report their own extension through the drawer's dispatchProd.
Bounded-concurrency fetch for the bulk zips. Results keep the INPUT order (zip entries stay
deterministic across runs) and a failure lands as null in its slot, so per-file accounting is
the caller's, unchanged. Six in flight matches a browser's per-host default; the sequential
loop this replaces serialised ~300 round trips behind one another.
```

#### M.doi (the survey's OWN dataset DOI) is the honest TF source archive

```text
M.doi (the survey's OWN dataset DOI) is the honest TF source archive. There is no substitute
when it is absent (TS_COLLECTION is the raw time-series collection, not a TF source archive, and
citing it here would mislabel a different dataset as "the source archive", the pre-C7 defect); so
when no DOI is recorded we state the ACTUAL access reason (embargo vs licence) via withheldReason().
```

#### ---- selection exports for the two AusMT-derived formats ...

```text
---- selection exports for the two AusMT-derived formats ------------------
A reader who has drawn a box around forty stations can take their EDIs in one click. AusMT also serves
a per-station EMTF XML and a per-station MTH5, and until now the only way to collect those over a
selection was forty visits to forty drawers. These two flows are the EDI flow over a different format:
same per-station manifest rows, same bulk label on every fetch, same LICENSE.txt beside the bytes.

One thing genuinely differs, and it drives the honesty rules below. An EDI is the custodian's own file,
so "is it served here?" is a LICENCE question (s.ediAvail) with a legacy flat path to fall back on. A
derived file exists only where the build produced one: eight surveys have no served XML at all, and a
coordinate-generalised or withheld station gets neither format. So availability here is simply "does
this station have a manifest row of this format", there is no fallback path to guess at, and a
selection will routinely contain stations that must be skipped. Skipping them quietly would hand back
an archive of 31 files for 40 stations with nothing to say which nine went missing or why.
```

#### Size honesty: each zip button states what THIS selection would cost ...

```text
Size honesty: each zip button states what THIS selection would cost before it is
clicked, so nobody starts a multi-hundred-megabyte MTH5 pull to find out. It counts only the rows the
export will actually fetch, so it is the estimate for the archive that will arrive, not for the
selection: an EDI whose station has no manifest row (the legacy flat path) contributes no size, which
is why every figure is prefixed "~". No manifest, no figure: a total of 0 would render "~0 B", a claim
that the selection costs nothing, when the truth is that nothing is known yet.

This runs on EVERY KEYSTROKE (filters.js refresh() calls it after re-filtering), so it is a hot path and
is written as ONE pass over the selection that sums all three formats at once, reading each station's
rows through the manifest index (data.js mfFileIndex) rather than rescanning files[] per station per
format. Three passes, each doing a linear scan of the whole manifest per station, cost 670ms per
repaint at 3000 selected stations against a 9000-row manifest, on the input path. The one indexed pass
is ~0.3ms there, and flat in the manifest size.
```

#### The time-series rows: one per level token, priced over the scope ...

```text
The time-series rows: one per level token, priced over the scope, action = that level's fetch
list. Two-phase honesty carries over from the retired chooser: in flight is busy-and-disabled
with the pending hint; a settled-empty deployment says so in the note (a curation state, never a
load error); membership in ts_access.json is the access decision.
```

#### The gap file

```text
The gap file. A station can be absent from this archive for two DIFFERENT reasons and they are not
interchangeable: its survey is not redistributable here at all (licence/embargo, the same wording and
the same archive pointers the EDI zip writes), or the survey IS served but this format was never
produced for that station. A third list records files that were served but did not come back, which
is a transport failure and not a statement about the corpus at all.
```

## portal/src/filters.js

#### Shared station filter (drives both Map and Surveys) + the hierarchy tree

```text
Shared station filter (drives both Map and Surveys) + the hierarchy tree. buildTree() is
data-dependent and called by main after ST is built. recolor lives in map.js and is
referenced only inside event handlers (runtime), never at load time.
```

#### up here so renderFind() (which resets it) is never in its temporal dead ...

```text
up here so renderFind() (which resets it) is never in its temporal dead zone.
The period-window control is retired; the predicate is HEADLESS like qMin below - the
bounds live in state.js (periodLo/periodHi, full-range by default) and are drivable by harnesses.
A revival note: the old heading said "cover this period window" while the predicate is an OVERLAP
test; any returning control must state the overlap semantics.
Year-range predicate. A station passes when its SURVEY's [year_start,year_end] overlaps the
typed [from,to] range; either input may be blank (an open end on that side). Unknown years
(survey declares no dates) PASS when both inputs are empty (no filter in effect) but FAIL as soon
as either is set - a modeller who typed a year range is asking for DATED data, so silently
including undated stations would misrepresent the range as covering them.
The rule itself, over a record's OWN two years. It is read on two surfaces - the map filters stations
(passesYearRange below) and the survey grid filters surveys (drawer.js _surveyPassesYears) - and it
lived as two verbatim copies in two files, differing only in the field names each surface spells its
years with. That is the shape a rule drifts in: one copy gets corrected and the other does not. One
definition, two callers, and the harness pins the two readings against each other.
```

#### Two-phase boot: s.q comes from sci.json, a PHASE 2 product

```text
Two-phase boot: s.q comes from sci.json, a PHASE 2 product. Until that product is USABLE this predicate
is INERT: a completeness value that has not arrived is not a FAILING one, and applying it would hide
every station on the map (and empty the counts) over data the portal does not have. hydrUsable, not
!hydrating: a FAILED sci.json leaves s.q undefined exactly as an in-flight one does, so a pending-only
gate would go live on a broken build and report "0 of 5 shown", which reads as a screening outcome.
SCI_READY re-runs refresh() the moment the values land, so a filter set early still takes effect.
No completeness THRESHOLD control is offered with the Availability group; the predicate
is kept because qMin is still drivable (the headless drivers set it) and because deleting a
screening rule is a curation decision, not a rail-layout one.
```

#### "Downloadable here" is the s.ediAvail licence predicate (the retired ...

```text
"Downloadable here" is the s.ediAvail licence predicate (the retired tickbox's, then the Data
available dropdown's "tf" option, the same flag the selection exports read for their not-included
honesty). The CONTROL was promoted to the discovery bar and the predicate stayed exactly here, so
the map filters on it as it always did; only where a reader sets it has changed.
```

#### Data available: the single-select TIME-SERIES level chooser in Browse

```text
Data available: the single-select TIME-SERIES level chooser in Browse. A level token
filters on ts_access.json membership and is INERT until the index has landed: a route that has not
arrived is not a missing one, and filtering on it would empty the map over data the portal does not
have. paintAvailSelect disables the level options across the same window (belt and braces), and
TSACC_READY re-runs refresh() so a choice made early still takes effect. Membership in the index IS
the access decision: nothing here re-derives availability, and no filter state can surface a
station the build gated out.
```

#### Surveys-view search: a case-insensitive substring across the survey ...

```text
Surveys-view search: a case-insensitive substring across the survey name, org,
region and blurb. Reads the discovery-bar #surveySearch input (NOT the rail #find; the rail is
hidden on the Surveys view, so the discovery search REPLACES #find as that view's search). Empty
query (or no input present, e.g. a bare fixture) matches everything.
```

#### Stage B (selection-state isolation): the Surveys CATALOGUE is filtered ...

```text
Stage B (selection-state isolation): the Surveys CATALOGUE is filtered ONLY by its own discovery
controls, the #surveySearch box (surveyMatchesSearch) plus the discovery facets (surveyPassesFacets,
applied by renderCards / updateCounts). It must not read passesCore, so the map rail's tree / type /
period / year / selection state can never hide a card. Coupling passesCore here lets the All-EDIs tile,
which checks a single tree box to scope the MAP, empty the whole catalogue with the rail (its only undo)
hidden on this view. The MAP still filters on passesCore via passes() / `visible`; only the catalogue is
cut loose.
```

#### Make the live results keyboard-usable

```text
Make the live results keyboard-usable. The container is role="listbox" (index.html);
tag each REAL result (a data-find row, not the "no matches" filler) as an option with a stable id so
the input can point aria-activedescendant at the highlighted one. Matching logic above is untouched.
```

#### Coordinate access: a custodian-withheld station has null lat/lon (no ...

```text
Coordinate access: a custodian-withheld station has null lat/lon (no position). It must NOT be
spatially selectable - without this guard null coerces to 0 and a polygon over (0,0) would phantom-
select it. It stays in ST/visible (counted, findable by name/text), just never in a bbox/shape hit.
```

#### The header counter is ONE shell with a CONTEXTUAL slot

```text
The header counter is ONE shell with a CONTEXTUAL slot. A fixed
"N shown / M selected / T total" describes what the reader is looking at only on the map: on the
Surveys view it counts stations while the screen shows survey cards, and on the Collections views it
counts something not on screen at all. The shell never moves; only
this slot's content changes, and where nothing true can be said about what is on screen it says
nothing rather than leaving a stale number standing.
```

#### The WORKSPACE LINE

```text
The WORKSPACE LINE. Its first number mirrors the discovery-filtered catalogue (#surveyCount) - the
search box AND the discovery facets - never the map rail's tree / type / period / year. Its second
counts STATIONS, because stations are what a selection holds and what the download builder takes.
With nothing selected the clause is hidden: "0 stations selected" is true and is noise.
```

#### MAP: the three station counts, rebuilt into the form index.html ships ...

```text
MAP: the three station counts, rebuilt into the form index.html ships (ids included, since other
surfaces paint them by id). The three numbers are plain integers; _countN belongs to the workspace
line beside them. The counts pin drives a 1,200-station window, because at the fixture's five the
two formats are the same string.
```

#### ONE call paints the visible set into the map's single dot container ...

```text
ONE call paints the visible set into the map's single dot container; map.js owns the layer and this
stays the caller it always was. Nothing collapses, so a filter change is the only thing that can alter
what is on the map: only POSITIONED stations reach the layer, and a withheld-coordinate station has
no marker (buildMarkers skipped it). It remains in `visible` (counted), just not on the map.
```

#### Downloads follow the SCOPE (scopeStations), so the metadata buttons ...

```text
Downloads follow the SCOPE (scopeStations), so the metadata buttons enable whenever the
scope is non-empty - with nothing selected they act on the filtered corpus, and the scope line
says so. Guarded per element: a renamed button must not abort every later line of this function
on each selection change (the bind-time console.error is the loud signal).
```

#### The Download block (scope line, the three Level 2 rows, the time-series ...

```text
The Download block (scope line, the three Level 2 rows, the time-series rows) is owned by
exports.js, which owns the packaging the metas must agree with; re-painted here, where the
selection is known to have changed. Guarded like the other cross-module calls: a harness that
loads filters.js without exports.js still updates the counts.
```

#### Tree disclosure state

```text
Tree disclosure state. Collapse is IN-MEMORY only (no persistence - polish item), keyed
"c:<country>" / "o:<country||org>" / "k:<collection id>" (the || separator is the tree's existing
org-namespacing convention). Visibility is applied by WALKING the flat rows: a row hides when ANY
ancestor key is collapsed, so re-expanding a country keeps a collapsed org's surveys hidden.
INVARIANT (test-pinned): collapse/expand touches ONLY row visibility - never a checkbox, never the
filter result (passesCore reads `input[value]:checked`, and a hidden row's checkbox still matches),
so checked-but-hidden surveys stay on the map.
```

#### Caret factory - its OWN click target INSIDE the label-wrapped row

```text
Caret factory - its OWN click target INSIDE the label-wrapped row. preventDefault stops
the label from activating its checkbox (the click-target hazard, test-pinned); stopPropagation
keeps the click out of any delegated handlers. Glyph is synced by applyTreeVisibility above.
```

#### Collections toggle group - FIRST, above all countries, only when the ...

```text
Collections toggle group - FIRST, above all countries, only when the boot data has
collections (same non-empty gating as the Collections tab). Collections are CROSS-CUTTING (a
programme can span orgs) so this is NOT a nesting level: the checkbox is a PUSH-ONLY bulk toggle
with the country/org semantics - on change it sets every MEMBER survey's checkbox (matched by
LABEL: COLL[cid].surveys holds labels and survey checkboxes use value=<label>) and refreshes. No
Derived/indeterminate state (country/org don't either). The row is
just name + survey count + station count: no nested member list, no caret (per-survey toggling
lives in the org hierarchy). Org rows/counts below are untouched: member surveys still live under their orgs.
The Collections group is mounted in its OWN block (#collGroup) ABOVE the country/org/survey
tree, not first-within #tree. Only the mount point changed - the heading, the row label, the push-only
bulk-toggle semantics and the member-survey sync (still matched against #tree's value checkboxes) are
unchanged. Fallback to `tree` keeps any harness without the #collGroup element working as before.
```

#### static control wiring (registrations only; functions resolved at event ...

```text
static control wiring (registrations only; functions resolved at event time)
The SINGLE data-type state path. Both ends of the type filter reach it: the rail's own checkboxes, and
the map legend's type rows (which proxy those checkboxes and dispatch this very event - see
toggleLegendType/syncLegendTypes in main.js). syncLegendTypes repaints the legend FROM the checkbox
state, so a rail flip dims the legend row and a legend flip confirms itself, off one function. Guarded
on typeof for the same reason every other handler here resolves late: main.js loads after this file.
```

#### Activation is shared between a mouse click and a keyboard Enter ...

```text
Activation is shared between a mouse click and a keyboard Enter (below), so both take
the identical path. `it` is a .fitem option element (has data-find). Kept verbatim from the old click
handler body - no routing change, only extracted so Enter can reuse it.
```

#### Keyboard path for the Find dropdown

```text
Keyboard path for the Find dropdown. ArrowUp/Down move an active-descendant highlight,
Enter activates the highlighted option (same activateFindItem as a click), Esc clears the query. No CSS
Rule is added to index.html for the highlight - the active option is
styled inline to match the existing :hover look (copper fill, dark ink), and un-styled on move-off.
(findActive is declared at the top of this file to avoid a temporal-dead-zone hazard in renderFind.)
```

#### ---- Availability > Time series: the per-level chooser ...

```text
---- Availability > Time series: the per-level chooser ------------------------------------------
The access posture, restated where the level filter reads it (passesCore) and where the Download
rows price it (exports.js paintDownloadRows): which stations appear in ts_access.json was decided
in the build - open access, a verified register row, never level_2 - so nothing in the portal
re-derives availability from survey metadata, and no control state can bring back a station the
build gated out. The two-phase hints are shared by the Data available options and the Download
rows; in flight and settled-empty are NOT the same fact (one resolves itself, one is a statement
about the build), so each surface names which it is in.
```

#### The current DOWNLOAD SCOPE: the selection when one exists, else the ...

```text
The current DOWNLOAD SCOPE: the selection when one exists, else the filtered corpus -
exactly what "Select all filtered" would take. One rule, no modes; the scope line in the Download
block states which. exports.js reads this for every download and every priced row.
```

#### Rail Browse and Select-and-download mode

```text
Rail Browse and Select-and-download mode. Browse (default) is
every map filter (find, data type, Data available, year, tree); Select & download is the
map-selection box and the Download/Metadata blocks
(advanced). It is a pure show/hide of the two mode panes - it never touches data-views (view/mode are
orthogonal: a section is visible iff its mode pane is shown AND its own data-views allows the view).
```

#### Stage B (selection-state isolation): the All-EDIs / survey "Download" ...

```text
Stage B (selection-state isolation): the All-EDIs / survey "Download" tile (selectSurvey, drawer.js)
enters Select & download mode and scopes the MAP by checking ONLY its own survey in the tree. That map
scoping is a TEMPORARY LENS, not a durable filter: snapshot the survey checkboxes it is about to mutate
on entry (enterSelectLens) and put them back when the visitor leaves the lens - returns to Browse
(setSidebarMode below) or navigates off the map (setView, main.js). The snapshot is taken ONLY by the
tile flow, so a visitor hand-toggling tree boxes in Browse mode is NEVER captured or restored (their
state stands). Scope is tight: only the `input[value]` survey checkboxes selectSurvey touches are
captured / restored; country / org parents and every other control are left exactly as they are.
```

#### Stage B: leaving Select & download for Browse ends any All-EDIs lens - ...

```text
Stage B: leaving Select & download for Browse ends any All-EDIs lens - restore the survey checkboxes the
tile scoped so the Browse pane shows the visitor's own tree again, never the single-survey scoping the
tile applied. Guarded on the select->browse transition so repeated setSidebarMode("browse") calls and a
visitor's plain Browse use are untouched.
```

#### "Select all filtered" makes a selection, so auto-switch to Select & ...

```text
"Select all filtered" makes a selection, so auto-switch to Select & download for discoverability of
the exports it just enabled: the same nudge the draw-created handler in map.js makes.
It also CLEARS any drawn shape: refresh() re-derives the selection from shapes, so a stale shape
would silently discard the select-all on the next filter change.
```

#### Availability > Transfer functions: the #tfAvail CHECKBOX is gone ...

```text
Availability > Transfer functions: the #tfAvail CHECKBOX is gone, folded into the Browse
"Data available" single-select (#availSel, its "tf" option).
The PREDICATE s.ediAvail outlived the control exactly as this comment always said it would: it is
read in passesCore() above and by the selection exports' three-way not-included honesty.
```

## portal/src/main.js

#### Fold the boot-loaded coordinate policy onto each station (generalised | ...

```text
Fold the boot-loaded coordinate policy onto each station (generalised | withheld), keyed by
the authoritative ausmt_id just derived; null when exact/unmarked. Positions are already masked in the
catalogue - this signals POLICY, not position - so the drawer can badge a generalised station honestly
without re-deriving precision client-side (forbidden by the record). Tolerant of an absent artifact.
```

#### slug -> survey label, for the #/survey/<slug> route (the published ...

```text
slug -> survey label, for the #/survey/<slug> route (the published /surveys/<slug> path URLs
The sitemap now emits 301 into this route at the front door - path-URL contract;
ausmt_id is
au.<slug>.<station> - mirrors the engine's own slug_of derivation in extract/build_portal.py
rather than re-slugifying the label, so it stays correct even if a label's slugification is
irregular). Prefer the authoritative SMETA[survey].slug; fall back to deriving it from a
station's own ausmt_id (strip "au." and the trailing ".<station>") for older data without it.
```

#### Two-phase boot: the ONLY two station fields that come from sci.json

```text
Two-phase boot: the ONLY two station fields that come from sci.json. buildState() runs at first paint,
before sci.json has landed, so it derives them from an empty row; this re-folds them from the real data
the moment SCI_READY settles. Identical expressions to buildState's own (sciRow keeps the deref shared),
so a hydrated station is byte-for-byte what a single-phase boot produced.
```

#### Build AUSLAMP_SET (survey SLUGS in the `auslamp` collection) from the ...

```text
Build AUSLAMP_SET (survey SLUGS in the `auslamp` collection) from the boot data. The
collections.json member list (COLL.auslamp.surveys) holds survey LABELS, not slugs (the engine keys
_group_collections by the survey.yaml name; see build_portal.py); the portal's partition/colour
predicates key off s.slug, so each label is resolved through SMETA[label].slug here - the SAME
authoritative slug the engine wrote (no re-derivation). Absent collection / absent slug => empty set
(graceful degrade). Rebuildable (not a boot-only const) so a test can repopulate COLL and re-run it.
```

#### UX feedback round 1 (#2): corpus-wide year hints on the two Year range ...

```text
UX feedback round 1 (#2): corpus-wide year hints on the two Year range inputs - placeholder + min/max
attrs from the min year_start / max year_end across ALL of SMETA (not just ST, so an undated-in-CAT
survey with declared dates still counts), plus the range appended to the section label, e.g.
"Year range (2019-2022)". Values themselves stay EMPTY on load - deliberately NOT defaulted to the
corpus range: passesYearRange() treats a set input as "a range WAS requested" and hides undated
surveys, so pre-filling the inputs would immediately (and silently) drop every undated survey the
moment the page loads. These are hints for what values are meaningful, not a default filter.
```

#### ---- "Recently added" ...

```text
---- "Recently added" -------------------------------------------------------------------------
LOCKSTEP RULE (keep identical to the engine's _survey_latest_date at
engine/extract/build_portal.py:467-489): a survey's "latest date" is the max well-formed
YYYY-MM-DD among all release_notes[].date PLUS attribution.declared_date when present; else
Dec-31 of (year_end||year_start); else null. Expressed here in JS, not shared code (Python vs
JS), so the portal strip and the Atom feed can never name a different "latest" survey; when the
rule changes on either side, change BOTH. The 30-day window and 3-item cap below are PORTAL-ONLY
display rules for the strip; feed.xml keeps every dated survey.
```

#### Brief 9, Option A: ONE concise horizontal line, wrapping - "Recently ...

```text
Brief 9, Option A: ONE concise horizontal line, wrapping - "Recently added: Vulcan 2022 (interpunct)
AusLAMP Queensland Phase 3" - not a heading over a column of rows. The old block form left a large
sparse box of mostly empty space between the reader and the catalogue, which is precisely what the
brief says not to keep just because the information exists. The date is what makes an entry recent, so
it is not dropped: it rides each link as its title rather than spending a second line.
```

#### ONE surface only (the surveys-view #recentStrip)

```text
ONE surface only (the surveys-view #recentStrip). The map-rail #recentSideSection/#recentSide was
deleted: rendering it here un-hid its section on EVERY view whenever any survey was dated (the
data-views toggle in setView un-hid it for the map view, and this render then un-hid it wholesale),
which leaked the section onto the Surveys/Collections views. Hidden entirely when empty.
```

#### Stage B (selection-state isolation): navigating OFF the map ends any ...

```text
Stage B (selection-state isolation): navigating OFF the map ends any All-EDIs selection lens - the lens
is a map-scoped view and its rail is hidden on other views, so it must not persist. Restore BEFORE
curView flips so restoreSelectLens's refresh() runs against the outgoing view. Entering the map
(v==="map") is deliberately excluded, so selectSurvey's own setView("map") never undoes the scoping it
just applied. (The only mode-exit path, the Browse button, is covered in setSidebarMode; Escape and the
export / done actions change neither the mode nor the view, so there is nothing to restore for them.)
```

#### The left filter rail (+ its resize handle) belong to the MAP view

```text
The left filter rail (+ its resize handle) belong to the MAP view. On Surveys and
Collections the rail's controls don't apply (search + facet chips live in the discovery bar there),
so hide both and let the content span the width. The map view restores them, and the invalidateSize
on its setTimeout below reclaims the space. openCollectionPage mirrors this on its manual path.
```

#### Only Map switches a view in place

```text
Only Map switches a view in place. Surveys and
Collections real links to the served hub pages, and a click handler on a control that is
navigating away would run a view switch the page is about to leave: a visible flash of the wrong
view on a slow load, and dead work otherwise. setView("surveys"/"collections") stays the way IN to
the in-app grids for routeFromHash, the tour and the drawer's own back-navigation.
```

#### The PLURAL routes

```text
The PLURAL routes. Published HTML has pointed at #/surveys since the entity pages shipped (every
survey page's back-nav, plus 404.html's recovery link) and no branch matched it, so the hash fell
through and the reader stayed on whatever view was showing. Those links now target the served
/surveys and /collections index pages, but the hash form is out in the wild for good, so it lands
where its name promises. Listed first, and matched EXACTLY, so neither shadows the singular
entity routes below (the strings share a prefix).
```

#### The entity page's button for this route is labelled "View all stations ...

```text
The entity page's button for this route is labelled "View all stations on the main map", so the
route must FRAME the survey: openSurvey rewrites the hash and renders but frames nothing, and the
setView above is on the station branch only. focusSurvey is the seam the drawer's own "View on
map" control uses, so the route delivers the same framing and the same Option-A dim. Called AFTER
openSurvey so the fit padding measures the drawer that is actually open.
Called directly, as filters.js does: focusSurvey is a top-level declaration in drawer.js,
which index.html loads before this file, so a typeof guard here could never be false and
would only turn a real regression into a silent no-op.
```

#### "View all stations on main map" from a collection page - switch to the ...

```text
"View all stations on main map" from a collection page - switch to the map view and
fit the map to the collection's extent. Prefers the collection's declared bbox; falls back to the
bounds of its member stations' positions. Uses the same setView/map seams the rest of the app does.
```

#### Drawer left-edge drag handle

```text
Drawer left-edge drag handle. It reuses the resizer pattern but is created HERE
(never in drawer.js) and parented to .content - NOT #drawer, whose innerHTML drawer.js rewrites on every
open (which would wipe a child handle). A MutationObserver mirrors the drawer's open state onto the
handle's visibility + left-edge position, so drawer.js internals stay untouched. min 420px, max 60vw;
invalidateSize on drag end.
```

#### Load-error copy distinguishes the two real causes rather than always ...

```text
Load-error copy distinguishes the two real causes rather than always blaming file:// (which was
this message's original, pre-container diagnosis): over HTTP a failed data load almost always
means the deployment simply has no published data build yet (e.g. site-data/current absent on a
fresh server) - an operator hint, phrased so a visitor still understands the portal is fine.
```

#### --- First-visit welcome popup ...

```text
--- First-visit welcome popup -----------------------------------------------------------
The first-visit surface is a small centred MODAL popup (#introWelcome).
It offers exactly: "Take the 2-minute tour" (starts the tour),
"Browse immediately" (close), and a "Don't show this again" checkbox that
GATES persistence - ticked, every close path (tour / browse / Esc / click-out) persists the dismissal
via the existing localStorage key; unticked, the popup may return next visit. Esc and click-out behave
as "Browse immediately". First-visit show fires from runInit() (populated AND empty-data paths).
There is no header "How to use AusMT" item and no #introOverlay "How AusMT works" panel, so there is
no on-demand tour button either.
The tour is reached by the ?tour=1 query parameter handled in maybeShowIntro() below, which About links as
"start the guided tour". It is checked BEFORE the seen flag on purpose: someone who ticked "don't show
this again" months ago is exactly the person who follows that link, so the flag must not swallow it.
```

#### ?tour=1 (About's "start the guided tour" link) starts the tour outright ...

```text
?tour=1 (About's "start the guided tour" link) starts the tour outright and shows no popup. Anything
else falls back to the first-visit rule: show the welcome popup unless the visitor dismissed it.
The parameter is dropped from the address bar once the tour is running (same replaceState pattern the
drawer and the tour itself use for their hashes), so a later reload browses the portal rather than
replaying the tour at someone who has finished it.
```

#### Static map legend (bottom-left): a coloured dot per data type, and ...

```text
Static map legend (bottom-left): a coloured dot per data type, and nothing else, since
a dot is the only thing the map draws. The dots read the LIVE --lpmt/--bbmt/--amt/--gds tokens via var(),
so they track any future colour change automatically. Built once (idempotent). Collapsible on small
widths (the toggle only shows there via CSS); starts collapsed on a narrow viewport.
The legend is parented INTO the Leaflet map container (#map), not to .content. As a
child of #content it was a sibling of #map in that flex row - an absolutely-positioned box, but living
in the same positioned/flex context as the map, so it participated in that layout and could nudge the
map's framing at load. Inside #map (which Leaflet keeps position:relative) it is an overlay that can
NEVER affect the map container's own size or centre: #map's box is measured before this child is
appended and an absolute child adds nothing to it. It also rides #map's display toggle for free.

INTERACTIVE LEGEND: a visitor tried to CLICK the data-type rows to show/hide sites, which
is the reasonable reading - the rail's DATA TYPE checkboxes use the identical dot+label visual language
and ARE toggles, and mapping tools conventionally make a legend a layer switch. So the four TYPE rows are
real toggle buttons that PROXY the rail's #typeBoxes checkboxes. There is deliberately NO second state
store: a legend click flips the SAME checkbox the rail owns and dispatches its change event, so the one
existing #typeBoxes path (filters.js) runs every consumer - passesCore, the map redraw, the header
counts, the surveys-view decoupling and the select-lens semantics - exactly as a rail click does.
There is no survey-badge row: the legend may not key an object the
map does not draw, and the map draws nothing but the four data types.

Resolve a rail type checkbox by its type key (LPMT / BBMT / AMT / GDS - the keys passesCore compares
against s.type). Read live from the DOM on each call: the rail is the single source of truth.
```

#### Two-way sync: repaint the legend FROM the checkboxes

```text
Two-way sync: repaint the legend FROM the checkboxes. Called from the one #typeBoxes change path, so a
rail flip and a legend flip both land here. An off type renders dimmed (the .legoff opacity covers the
dot AND the label together) and reports aria-pressed=false.
```

#### The metric scale bar, RE-PARENTED into the legend body

```text
The metric scale bar, RE-PARENTED into the legend body. Leaflet drops a control into one of the
map's own corners, where a scale would sit apart from the key it belongs with and over the dots;
moving its container is the smallest change that puts it where a reader already looks. Constructing a
Leaflet control deliberately has one precedent here, map.js's layer control.
IT TAKES ITS OWN CLASS, and that is load-bearing rather than tidy: the legend's own pins count
`.legrow .dot` and assert #mapLegend is a child of #map, so a scale bar that borrowed either would
break a claim about the data-type key. Metric only (this is an Australian corpus) and capped at
120px so it cannot outgrow the legend it now sits in.
```

#### Explicit keyboard activation

```text
Explicit keyboard activation. A <button> already activates on Enter/Space in a browser, but the
default action is CANCELLED here so the browser cannot then synthesise its own click on top of this
handler (one keypress must be one flip, not two). It also makes the keyboard path directly drivable
in the headless jsdom harness, which does not synthesise clicks from key events.
```

#### "data build <short id> · <date>" footer text, or "" when build.json ...

```text
"data build <short id> · <date>" footer text, or "" when build.json didn't resolve (older
builds predate it - BUILDID is null - so the placeholder must stay empty, not show stale/undefined
text). Split from the DOM write below so a test can assert the VALUE binding (BUILDID -> text)
without needing a real DOM (mirrors buildState()'s station0/export0 value-binding pattern).

UX feedback round 1 (#6): the emitter (build_identity() in engine/extract/build_portal.py) is
already fixed to never fold Python's None into build_id - an unresolved source_commit renders as
the WORD "unknown" there, never "None". This function still must not display either literal word
to a visitor: a build_id containing "None" (an older/foreign build predating that fix) or
"unknown" (the legitimate no-surveys-commit case) is display-DEFENDED here by dropping the short-id
segment entirely, keeping only the date (when known) - the full raw id still goes in a title attr
for anyone who needs to trace it, via renderBuildId() below.
```

#### ---- two-phase boot ...

```text
---- two-phase boot ------------------------------------------------------------------------------
HYDRATION_DONE settles once every phase-2 product has landed AND its late-render work has run. It is not
on any user-facing path (nothing awaits it to paint); it exists so a headless driver can say "now the app
is in the state a single-phase boot produces" without racing the continuations.
```

#### Late hydration must never leave a stale render standing

```text
Late hydration must never leave a stale render standing. Each gate re-runs EXACTLY the surfaces that read
its product, and nothing else:
  sci -> re-folds s.q/s.dim (applySciToStations), re-enables the completeness/dimensionality
              colour modes, then refresh() so the map/counts/cards reflect a completeness predicate
              that was inert until now.
  tf -> the open station drawer (its response plots and the sci/tf-derived summary rows).
  manifest -> the open drawer again (Files rows, format badges, download tiles), station OR survey.
Re-rendering the open drawer is the deliberate simplest correct answer: it is one innerHTML rewrite of a
panel the user is already looking at, and rehydrateOpenDrawer preserves scroll position and the selected
tab so the only visible change is the section that was showing a loading state.
```

#### ts_access.json settles the availability facet: until it lands nothing ...

```text
ts_access.json settles the availability facet: until it lands nothing on the page knows which
stations this deployment can hand off, so the Download rows and the Data available options are
repainted here (counts, sizes, the disabled state that was in-flight a moment ago) and
refresh() re-applies a level filter chosen while it was inert. It never rejects - absence is
the honest answer - so there is no failure branch to mirror sci's.
```

#### Hydration starts only AFTER phase 1 has its bytes: the phase-2 products ...

```text
Hydration starts only AFTER phase 1 has its bytes: the phase-2 products are large (tf.json
alone is most of the page weight) and share one connection with the catalogue the dots need,
so issuing them earlier delays the exact first paint the two-phase split exists to protect.
Nothing on the first-paint path awaits these gates, and no consumer can read them before
runInit attaches the UI below, so the later start is invisible everywhere but the network.
```

## portal/src/map.js

#### Map + layers + markers

```text
Map + layers + markers. Data-dependent work (markers, footprints) is in buildMarkers()/
buildFootprints(), called by main after ST is built. No direct call into drawer/filters at
load time; the only cross-module reference is the marker click -> openStation (one-way).
UX feedback round 1: default to a fixed Australia extent on load (was an arbitrary centre/zoom pair
that didn't reliably frame the continent on typical viewport sizes). Bounds: [[south,west],[north,east]]
chosen to cover the AU mainland + Tasmania with a small margin.
buildMarkers() must NOT re-fit to the tight station-marker extent once data loads: no station sits
north of ~-22.5 lat, so that fit drops the view SOUTH (centre ~-33.6) and clips northern Australia.
The home view is ALWAYS this fixed box (below): every station (lon 115.85..148.17,
lat -43.44..-22.48) falls inside it, so it shows all dots AND frames the whole continent. Defined ONCE
here as AU_HOME_BOUNDS and shared by the initial fit and buildMarkers()'s HOME_BOUNDS so the two frames
cannot drift apart.
```

#### THE ATTRIBUTION CONTROL IS MOUNTED BELOW, not here

```text
THE ATTRIBUTION CONTROL IS MOUNTED BELOW, not here. Leaflet's default control is the one that
carries the flag and the word "Leaflet", which is a courtesy to a library rather than a licence
term and is what came off the map, so the map is created without one and
src/mapattrib.js mounts a control with prefix:false in its place, collapsed behind a small (i).
The CREDIT itself stays on the map: it is a licence obligation, and only the layer that is
actually drawing knows which provider to name.
```

#### The basemap is config-driven

```text
The basemap is config-driven. provider "pmtiles" serves OUR OWN files through the vendored
protomaps-leaflet renderer, ending the portal's last runtime third party: the world file
carries low zooms globally (zoomed out still shows the whole globe) and the region file
carries full detail for Australia and its surrounds; the z7 crossover is where the region
bbox has data the world file lacks. "carto" is the hosted fallback while the files roll out
(or if the renderer failed to load); CARTO watermarks un-keyed raster requests, so the
deployment's key (config, public by nature) rides the tile URL when set.
EACH BRANCH STATES ITS OWN CREDIT, and the control prints whichever layer is on the map. This is
what a single fixed line of prose elsewhere on the page could not do: a deployment running on the
fallback serves CARTO tiles, and a fixed line would credit Protomaps for them. Both are rendered from
OpenStreetMap data, so both name OSM; the second name is the provider that built the tiles.
The links open the way every outbound anchor on this site opens.
```

#### Mounted after the basemap so the control collects the layer already on ...

```text
Mounted after the basemap so the control collects the layer already on the map, which is the
order Leaflet's own default control is created in. Reached through window, the way every shared
module on this site is (src/doi_harvest.js sets the precedent): the headless harnesses build a
context where window is an object of their own rather than the global, and a bare identifier
would resolve in the browser and nowhere else.
```

#### SITE LOCATIONS ONLY, at every zoom

```text
SITE LOCATIONS ONLY, at every zoom. The per-survey badge bubbles that
replaced proximity clustering are removed with it - no badge, no leader tail, no decoration pane, no
zoom threshold. A compact survey now overlaps into a tight group of dots at national zoom and the
click-to-open-survey affordance the badge carried is gone. The
drawer's own survey route (#/survey/<slug>) and a dot click are what remain.
ONE dot container. Two containers - a never-clustered plain layer for AusLAMP members and a
markerClusterGroup for everything else - are only needed while clustering has to be withheld from the
national LP grid. Nothing collapses, so every station dot on the map is on the map the same way.
```

#### AusLAMP membership is COLLECTION membership, not a data type - a ...

```text
AusLAMP membership is COLLECTION membership, not a data type - a station is AusLAMP iff its
survey slug is a member of the collection with id `auslamp` in collections.json. AUSLAMP_SET (a Set of
member SLUGS) is built once at boot from COLL/SMETA (buildAuslampSet, main.js); the pure predicate here
takes it explicitly so it stays Leaflet-free and unit-testable (jsdom can't load Leaflet).
NO MAP PATH READS IT now the map is dots-only: its one consumer was the badge rule's
never-collapse privilege, and nothing collapses now. Kept (with AUSLAMP_SET and buildAuslampSet) because
it is collection membership rather than map furniture; retiring the three is a separate decision,
and the boot resolution of labels to slugs is pinned on its own.
```

#### Coordinate access: a station whose custodian WITHHELD its coordinates ...

```text
Coordinate access: a station whose custodian WITHHELD its coordinates carries null lat/lon in the
served catalogue - the engine masks the VALUE (there is no separate policy field; withheld => null,
generalised => a 0.1° cell rendered verbatim). hasPosition is the ONE pure predicate every map path
uses to skip a position-less station: no marker, no footprint vertex, no fitBounds point, no spatial
selection. It stays in ST (counted, findable by name); it simply is not ON the map. PURE + Leaflet-free
so jsdom drives it directly (same idiom as isAuslampSurvey).
```

#### Paint the currently-visible stations into the ONE dot container

```text
Paint the currently-visible stations into the ONE dot container. Called by refresh() (a filter changed).
`visible` (filters.js) is already the filtered set; only POSITIONED stations reach the layer, because a
coordinate-withheld station has no marker and no place on the map. Every one of them is a dot: the
set depends on neither zoom nor the sidebar mode, so nothing else has to trigger a re-route.
Returns what this pass painted. The app ignores the value; the jsdom driver calls the pass directly and
reads it, because under a stubbed Leaflet the layer contents are unreadable Proxies.
```

#### Explicit aria-labels on the draw + zoom toolbar anchors, set AFTER the ...

```text
Explicit aria-labels on the draw + zoom toolbar anchors, set AFTER the controls
are on the map (their DOM exists by then). leaflet.draw already writes the title from L.drawLocal above;
the aria-label makes the accessible name unambiguous for AT. No-op where the anchors aren't rendered
(e.g. the jsdom/smoke harness, which stubs Leaflet) - querySelectorAll simply returns nothing.
```

#### Discoverability: the SELECTION panel gained "Draw rectangle"/"Draw ...

```text
Discoverability: the SELECTION panel gained "Draw rectangle"/"Draw polygon"
buttons that ARM the SAME leaflet.draw handlers the map's top-left toolbar icons arm - the panel used
to point users to a tool at the opposite corner. We REUSE the control's own mode handlers
(drawControl._toolbars.draw._modes[mode].handler - the exact object each toolbar icon enables), never
a second draw invocation. Panel button, toolbar icon and armedDrawMode mirror ONE state: enabling a
handler fires DRAWSTART (whatever the source) and disabling/completing/cancelling fires DRAWSTOP, so
the armed reflection below stays true no matter which surface armed it.
```

#### Arm a mode FROM THE PANEL by enabling the control's own handler - ...

```text
Arm a mode FROM THE PANEL by enabling the control's own handler - identical to clicking the toolbar
icon (leaflet.draw binds each icon to _modes[type].handler.enable). Setting armedDrawMode here gives
immediate feedback and covers the L-stubbed harness, where the real DRAWSTART event never fires;
production reconciles via the listeners below.
```

#### The LPMT colour split was REMOVED - all LPMT renders the flagship teal ...

```text
The LPMT colour split was REMOVED - all LPMT renders the
flagship teal (TYPE_COL.LPMT) in type mode regardless of AusLAMP membership, and every colour mode
Is membership-blind. Now the map is dots-only NO map surface carries the AusLAMP/legacy
distinction at all: it was last held by the clustering split, which the badge rule inherited and
Which is now gone.
The colour-by control is retired; markers carry the data-type colour, a
phase-1 fact (the legend is the surviving colour surface). qColor lives on for the drawer's
completeness dot.
```

#### ---- the survey FOCUS DIM ...

```text
---- the survey FOCUS DIM --------------------------------------------------------
"View on map" with a survey open frames that survey while the rest of the catalogue STAYS ON THE MAP,
dimmed. The rejected alternative (what shipped before) filtered every other survey out of the layers, so
the reader lost the national context that makes a survey's position meaningful, and the map stayed
filtered after the drawer shut. This is OPACITY ONLY: no layer is added, removed, cleared or rebuilt, so
there is nothing to reload when the focus lifts - clearSurveyDim just puts the opacities back.
The focused survey, or null when nothing is focused. Read by applySurveyDim on every re-application.
```

#### Apply the current focus to every marker

```text
Apply the current focus to every marker. Markers are canvas circleMarkers (preferCanvas), so setStyle
carries their opacity; it passes ONLY the opacity keys, so it composes with recolor()/restyleForZoom()
(colour and radius) instead of fighting them. Every map object is a station dot now, so this one loop is
the whole dim: the per-survey panes existed because a badge was a divIcon setStyle could not reach.
```

#### Zoom-scaled marker geometry

```text
Zoom-scaled marker geometry. PURE step functions (unit-tested, monotone non-decreasing in z),
the SINGLE source for both the initial draw (buildMarkers) and the zoomend restyle below - markers read
too large at national zoom but right when zoomed in, so they grow with zoom. Values are the starting
points; the final table is recorded in the design doc.
Every radius tier shifted ONE STEP SMALLER - each tier takes the next-smaller
tier's old value (z5 4.5->3.5, z6 5->4.5, z>=7 6->5) and the smallest tier drops by the bottom step
(z<=4 3.5->2.5, the 1.0 gap that separated it from the z5 tier). Still monotone non-decreasing in z.
weightForZoom left as-is: a 1.0 stroke does not overwhelm a 2.5 fill.
Change 6: CONTINUOUS dot radii, replacing the four-step ladder (2.5 / 3.5 / 4.5 / 5). A step ladder
jumps: a zoom notch changed every dot's size by a visible 1px in one frame. A linear ramp in zoom is
continuous across the range and monotone non-decreasing (the pinned property).
UNIFORM SITE DOT SIZE: "the same size as the icons set for the AusLAMP sites". The
per-type base split change 6 introduced (LP 2.0 / everything else 3.0) is REMOVED, because it cost the map
a second visual variable encoding the same fact as colour. Data type is carried by COLOUR; size carries
ZOOM. One variable, one meaning. The surviving base is the LP one, so BB/AMT/GDS come DOWN to the AusLAMP
texture size rather than the fabric coming up.
FLOOR and CEILING are both load-bearing and mean different things. The floor stops a dot going sub-pixel
at far-out zooms, where an invisible dot reads as "no coverage here" - a false claim about the corpus.
The ceiling stops close zooms growing discs that overlap into one blob and hide the site spacing, which
at site zoom IS the information. Between them the ramp is 0.5px per zoom level.
```

#### PURE, and a function of ZOOM ALONE

```text
PURE, and a function of ZOOM ALONE. A caller that still passes a data type is harmless: the argument is
not read, so a call site missed in the removal cannot quietly resurrect the per-type split. That
inertness is itself pinned (tools/map_dots_test.js) rather than left as an accident of JS arity.
```

#### The home frame buildMarkers fits to, remembered module-level so the ...

```text
The home frame buildMarkers fits to, remembered module-level so the setView("map") 60ms
corrector can re-fit to it (null until data is in). This is the FIXED Australia frame
(AU_HOME_BOUNDS), NOT the tight station extent - see buildMarkers. _fitWasDegenerate records whether that
primary fit landed at a degenerate container size (see buildMarkers).
```

#### A marker click OPENS that station and must never ALSO read as a ...

```text
A marker click OPENS that station and must never ALSO read as a
background click that closes the drawer. L.Path defaults bubblingMouseEvents to TRUE, so without this
a marker click would fire the marker handler and then bubble to the map's click handler below - the
drawer would open and immediately close. DOM-target discrimination cannot do this job here: the map is
preferCanvas, so every marker and the background share ONE canvas element as e.target. Leaflet's own
layer hit-testing is the discriminator, and this flag is how it is expressed.
```

#### Home frame once data is in: re-fit to the FIXED Australia box ...

```text
Home frame once data is in: re-fit to the FIXED Australia box
(AU_HOME_BOUNDS), NOT the tight positioned-station extent. The tight extent dropped the view south and
clipped northern Australia; every station falls inside AU_HOME_BOUNDS, so this frames the continent AND
shows every dot. Guarded on there being at least one positioned station so an all-withheld catalogue
simply keeps the map-create fit (identical box) rather than re-running the size/timing repair for nothing.
```

#### Reclaim the true container size BEFORE fitting: on first load the map's ...

```text
Reclaim the true container size BEFORE fitting: on first load the map's cached size can be stale/0x0
(its container was unlaid-out at map-create), which makes fitBounds compute against a degenerate box
and land at zoom 0 / the wrong centre. invalidateSize repairs the cached size first; the fit is the
PRIMARY attempt (the 60ms timer is only the corrector). We record whether the size was still degenerate
at fit time so the corrector runs exactly when it is needed.
```

#### One-shot corrector, called from the setView("map") 60ms timer AFTER ...

```text
One-shot corrector, called from the setView("map") 60ms timer AFTER invalidateSize has
repaired the container size. Re-fits HOME_BOUNDS when the gate allows (user hasn't taken control and the
primary fit was degenerate), then clears the flag so it runs at most once - a later return to the map, or
a programmatic collection fit, is never clobbered.
```

#### The ACTUAL off-centre-on-load fix

```text
The ACTUAL off-centre-on-load fix. The one-shot corrector above only re-fits when the primary fit was
DEGENERATE (0x0). But on a real page load the flex layout has not settled at fit time, so the container
size is NONZERO-BUT-WRONG: the fit lands off-centre yet the degenerate gate never trips, and the bad fit
STICKS. (Dispatching a window 'resize' - which triggers the app's unconditional invalidateSize + re-layout
 -  snaps it to correct framing every time; this is that same correction, done once, automatically.) This
deferred re-fit re-claims the true size and re-fits HOME_BOUNDS UNCONDITIONALLY - it is NOT gated on the
degenerate flag (that gate is the bug). It is gated ONLY on the user not having taken control, so it never
fights a deliberate pan/zoom. Because HOME_BOUNDS is remembered, the re-fit is idempotent when the fit was
already correct and corrective when it was wrong.
```

#### Schedule the deferred re-fit AFTER layout settles

```text
Schedule the deferred re-fit AFTER layout settles. Double requestAnimationFrame: a single rAF can still
run before the browser has performed the final layout+paint, so we wait one more frame - by the second
frame the container is at its settled flex size and the re-fit measures the RIGHT box. Falls back to a
small timeout where rAF is absent (e.g. a non-visual headless host).
```

#### Mark that the USER has taken control of the map, so the corrector never ...

```text
Mark that the USER has taken control of the map, so the corrector never fights a deliberate pan/zoom.
Gated on genuine user gestures ONLY: Leaflet's dragstart is user-initiated (a programmatic setView/
fitBounds does NOT fire it), and the container wheel/touch listeners catch scroll- and pinch-zoom.
movestart is deliberately NOT used - it also fires on the app's own programmatic moves.
```

#### A click on the MAP BACKGROUND closes an open drawer (survey OR station)

```text
A click on the MAP BACKGROUND closes an open drawer (survey OR station).
Leaflet only routes a click here when its hit-testing found no interactive layer under the pointer:
station markers set bubblingMouseEvents:false (buildMarkers) and a drawn shape is an L.Path target that
consumes its own click, so "reached this handler" IS "landed on the background". PURE decision split
out as _bgClickShouldClose so the jsdom driver can pin the RULE; note that the pointer/capture semantics
themselves are Leaflet's and are only exercised in a real browser.
An ARMED DRAW is excluded: mid-rectangle the click is placing a corner, not dismissing a panel.
```

#### Leaflet renders an attribution as HTML, and the source half of this ...

```text
Leaflet renders an attribution as HTML, and the source half of this line is FILE CONTENT (a fetched
layers/*.geojson), so both halves are escaped. The guard is here while the path is DORMANT (the layer
control below is not mounted, so the fetch never runs) precisely so re-enabling the control cannot
re-open the sink by omission: a later change must not have to rediscover this.
The guard on the control existing stays: a document that failed to load src/mapattrib.js draws a
map with no control at all, and a layer added there must toast rather than throw.
```

#### The selection-feedback toast copy

```text
The selection-feedback toast copy. PURE (unit-tested) so the exact string -
proper singular/plural, the word "stations" (never "sites"), and the shape word - is pinned. Any
layerType other than "rectangle" reads as "polygon" (the only two draw modes enabled above).
```

#### One active selection shape: a new box replaces the previous one rather ...

```text
One active selection shape: a new box replaces the previous one rather than stacking. refresh()
recomputes `selected` from the new shape, THEN we toast the fresh count and surface the exports by
auto-switching the rail to Select & download. Named (not inline) so the jsdom driver can invoke it.
```

## portal/src/mapattrib.js

#### The map's attribution, collapsed to one glyph in the corner

```text
The map's attribution, collapsed to one glyph in the corner. Shared by every map this site draws:
the SPA's, and add-survey's picker, station preview and confirmation maps.

THE CREDIT IS A LICENCE TERM, not a courtesy. The basemap is OpenStreetMap data under ODbL and
each tile provider asks for credit of its own, so what leaves the corner is the LINE and the
Leaflet flag and word beside it, which are the courtesy. The control stays, with prefix:false.

IT READS THE LAYERS, and that is why the credit is here rather than in a fixed line elsewhere on
the page: map.js keeps a fallback to a different tile provider, and only the layer that is
actually on the map knows which one is drawing. Leaflet's own control collects each layer's
declared attribution, so the text is always what the reader is looking at.

THE TOGGLE GOES IN A WRAPPER AROUND THE CONTROL, never inside it. Leaflet rewrites the
attribution container's innerHTML on every attribution update, which is every time a layer is
added or removed, so anything placed inside it is discarded the next time a layer changes.

No dependency and no asset: the glyph is a text node and the rules live in the document that
mounts this.
```

#### Decorate a mounted control's container

```text
Decorate a mounted control's container. `el` is Leaflet's own container; the wrapper this
returns is what the page's rules style. Returns null when there is nothing real to decorate:
the headless harnesses stub Leaflet, and a stub's container is not a node.
```

#### THREE WAYS IN and the same three ways out, so the control can never be ...

```text
THREE WAYS IN and the same three ways out, so the control can never be left open with no way
to close it and never left closed with no way to open it without a pointer.

A CLICK TOGGLES FROM THE STATE THE POINTER FOUND, not from the state at the moment of the
click, and that distinction is the whole of this code rather than a nicety. A mouse click on
a hovered control arrives AFTER the hover and the focus have already opened it, so a plain
toggle read "open" and closed it; measured in Chrome, clicking the glyph collapsed a control
the pointer had just expanded. A tap has the opposite problem: there is no hover, focus lands
on the button as part of the tap, and a plain toggle then closed what the tap had opened, so
a tap did nothing at all. Reading the state from pointerdown, which precedes both, gets a
pointer and a tap right; a keyboard activation fires no pointerdown, so it falls back to the
current state, which is the state a reader who tabbed in is looking at.
```

#### Mount the control on `map` and collapse it

```text
Mount the control on `map` and collapse it. No credit is passed in: each tile layer declares
its own and the control collects them, which is what keeps the text honest about the provider.
The caller creates the map with attributionControl:false, because the control Leaflet mounts by
default is the one carrying the flag and the word.
```

## portal/src/plots.js

#### Pure SVG transfer-function plotters (no data/DOM dependency): ρ, φ ...

```text
Pure SVG transfer-function plotters (no data/DOM dependency): ρ, φ, phase tensor, induction arrows.
Each plotter takes a TF entry `t` (one per station, from tf.json). Columns are POSITIONAL - see
the legend in data.js / docs developer/data-files.md (TF_COLUMNS):
  t[T.periods] periods · t[T.rho_xy] ρ_xy · t[T.rho_yx] ρ_yx · t[T.phs_xy] φ_xy · t[T.phs_yx_adj] φ_yx(+180°) · t[T.tip_mag] |T| ·
  t[T.pt_min] pt_min · t[T.pt_max] pt_max · t[T.pt_az] pt_az · t[T.pt_beta] pt_β ·
  t[T.rho_xy_err]/t[T.rho_yx_err] ρ errors · t[T.phs_xy_err]/t[T.phs_yx_err] φ errors (°) ·
  t[T.tzx_re]/t[T.tzx_im] Tx (Hz/Hx) · t[T.tzy_re]/t[T.tzy_im] Ty (Hz/Hy)
Source-data frame: x = north, y = east (so Tx couples Hz to the north field, Ty to the east field).
The SVG builders are viewBox-responsive. svgOpen emits the DESIGN size
as width/height AND the same design coordinates as the viewBox, so ONE plotter serves both surfaces: the
drawer renders it at 1:1 and the expand modal CSS-stretches the identical markup to fill its capped
content column. No geometry is recomputed and every pinned <line/rect/path> signature is untouched. The
former `_k` display-scale argument (a fixed 2x pixel blow-up in the modal, which grew with the monitor
rather than with the layout) is gone: modal sizing is CSS now. Series markers are shape-differentiated
(xy = circle, yx = square) so the copper/teal pair is not colour-only. The curve COLOURS are frozen.
```

#### Open an <svg> whose viewBox carries the design coordinates and whose ...

```text
Open an <svg> whose viewBox carries the design coordinates and whose width/height carry that
SAME design size (the viewBox is purely additive, so every pinned coordinate signature still matches).
Consumers do the resizing in CSS: the drawer leaves it at 1:1, the expand modal stretches it to
width:100% of a capped column, and the viewBox keeps the render crisp at whatever size it lands on.
```

#### Vertical error bars

```text
Vertical error bars. For each period draw a whisker between y(lo(v,e)) and y(hi(v,e)),
only where BOTH the value and its error are present. `lo`/`hi` let the caller clip the low end
(rho lives in the log domain and cannot go <=0, so it clips at a small positive floor). No bar is
emitted for absent errors, so a survey without errors renders exactly as before.
```

#### Phase error bars in DEGREES (symmetric ± the propagated error)

```text
Phase error bars in DEGREES (symmetric ± the propagated error). The yx error rides its
+180°-adjusted value (the error is orientation-independent). Bars only where the error is present.
```

#### Induction-arrow panel - REPLACES the |T|-magnitude plot, rendered below ...

```text
Induction-arrow panel - REPLACES the |T|-magnitude plot, rendered below the phase tensor.
One vector arrow pair per thinned period, from a baseline on the log-period axis:
  REAL (Parkinson convention): (east, north) = (-tzy_re, -tzx_re), solid copper - real arrows point
    TOWARD conductors.
  IMAGINARY (unreversed):      (east, north) = ( tzy_im,  tzx_im), lighter.
Screen mapping is the standard map view: east -> +x (right), north -> +y (UP, i.e. screen -y). A
|T| = 0.5 reference arrow is drawn in the corner at the SAME scale. Absent/masked tippers (all four
components null) render the "no tipper" state - the panel simply does not appear (as the old |T|
plot did when tip_mag was absent). The x=north / y=east source frame is documented in data-files.md.
```

#### Plot kind registry

```text
Plot kind registry. Each kind has a heading, an always-visible subline (the convention /
axis-key text that must survive VISIBLY, not hover-only, for the arrows), and an svg builder that
takes only the TF row. plotBlock renders the always-shown in-drawer form (all four panels); plotCollapsible
renders the collapsed-by-default <details> form (phase tensor + induction arrows) with the heading +
subline living in the ALWAYS-VISIBLE <summary> so the convention never hides behind a closed panel.
```

#### ONE expand control for the WHOLE response section

```text
ONE expand control for the WHOLE response section. Every plot block used to
carry its own ⤢ button and all four opened the SAME full-station modal, so the drawer showed four controls
for one action. The per-plot buttons are gone; the drawer puts this single control on the "Response
functions" section heading row instead (same affordance style, section-level label). It is a real
<button>, so it is tab-reachable and Enter/Space activate it, and the delegated [data-act="expand"]
handler in drawer.js is unchanged.
```

#### Collapsed <details> block: the heading + subline sit in the summary ...

```text
Collapsed <details> block: the heading + subline sit in the summary (always visible); the svg + axis unit
are the collapsible body. Empty svg -> "". Retained as the reversible collapsed form; unused since the
pt and arrows are always shown.
```

#### The expand affordance opens ONE full-station RESPONSE modal, not a ...

```text
The expand affordance opens ONE full-station RESPONSE modal, not a single-plot
popup. It carries a station-identity header (built by the drawer, which owns the honest coordCellHtml /
orgNameLink) plus ALL response panels: apparent resistivity, phase, phase tensor, and the induction
arrows ONLY when the station carries tipper (arrowSvg returns "" otherwise, so that panel is simply
absent, exactly as in the drawer). The overlay is appended to <body>, scrolls, and
closes on Esc, click-out, or the close button, with focus returned to the opener. The drawer's own Esc
handler yields while the modal is open (it checks for #plotmodal) so Esc closes the modal, not the
drawer. All data is already client-side (the stashed TF row); no fetches.

SIZING. A fixed STATION_MODAL_SCALE pixel blow-up sizes the modal to the MONITOR rather than to the
layout, so there is no such constant.
The panels are emitted at design size and stretched by CSS to FILL a CAPPED content column
(.plotmodal-capw in index.html: max-width min(92vw,760px), centred, with the overlay's viewport margin;
.plotmodal-svg svg{width:100%;min-width:372px}). So the modal is comfortably larger than the drawer
plots (~1.95x at the cap) but never wall-sized, the svg never renders NARROWER than the drawer's 372px
design width (axis/label text can never end up smaller than in the drawer), and the height keeps the
box's existing internal scroll.
```

#### One modal panel: title + optional convention subline + svg + axis unit

```text
One modal panel: title + optional convention subline + svg + axis unit. An empty svg
(arrowSvg for a non-tipper station, or any uncollected panel) yields "" so the panel is ABSENT, no empty
box, mirroring plotBlock's guard. No expand button here (the modal IS the expansion).
```

## portal/src/security.js

#### HTML-escaping helpers

```text
HTML-escaping helpers. ALL survey/station metadata is escaped through these before it
reaches innerHTML. esc -> text nodes; escAttr -> quoted attribute values; escUrl -> hrefs.
```

#### The "/" branch is a SAME-ORIGIN path and nothing else

```text
The "/" branch is a SAME-ORIGIN path and nothing else. A second slash starts an off-site authority
(//host), and a backslash is folded to a slash while an http(s) URL is parsed, so /\host reaches the
same authority; both collapse to "#" like every other off-allowlist form. Third-party field values
arrive here raw (a related identifier of type URL), so this branch is an allowlist, not a shorthand.
```

## portal/src/state.js

#### ---- two-phase boot: background hydration gates ...

```text
---- two-phase boot: background hydration gates ------------------------------------------------
The boot paints from the SMALL products (catalogue + surveys, plus the four small optionals). The heavy
ones (tf.json ~3.2MB raw, sci.json and the download manifest) stream in AFTERWARDS, so between first
paint and their arrival TFD/SCI/MANIFEST are simply NOT LOADED YET. That is a THIRD state, distinct both
from "loaded and empty" and from "this deployment does not serve it", and the honesty rule of this
codebase forbids collapsing it into either: no consumer may render "not recorded" / "not currently
available" / "not evaluated" / "none currently served" for a product that is merely still in flight.
  HYDR[k] === "ready" -> assigned; render exactly as before
  HYDR[k] === "pending" -> in flight; render an unobtrusive LOADING state, NEVER absence
  HYDR[k] === "failed" -> the fetch resolved not-ok / unparseable; say THAT, never dress it as absence
TF_READY / SCI_READY / MANIFEST_READY are the awaitable gates for consumers that cannot degrade (the
exports read TFD/SCI; the bulk EDI zip reads the manifest). The defaults are the SETTLED values so every
harness that assigns TFD/SCI/MANIFEST directly (the coord-access and bundle-tile drivers do) behaves
byte-for-byte as it did before phasing: only a boot that actually starts phase 2 flips them to pending.
```

#### A product is USABLE only when it is loaded

```text
A product is USABLE only when it is loaded. "pending" and "failed" are two different REASONS for one
fact: the values are not here. A surface that can name the reason (the drawer, which renders a loading
line or a could-not-load line) distinguishes them; a surface that cannot (a filter predicate, a marker
fill, a property written into an exported file) must gate on THIS, because a failed sci.json leaves s.q
undefined for every station exactly as a pending one does. Gating those on hydrating() alone would resume
claiming "fails the threshold" / "not evaluated" / "remote_ref: false" the instant the fetch errored,
which is the same dishonesty one state later. Phase 2 made a tf/sci failure survivable (before the split
it was fatal and the portal blanked), so this state is reachable and has to be answered here.
```

#### The set of survey SLUGS that belong to the `auslamp` collection, built ...

```text
The set of survey SLUGS that belong to the `auslamp` collection, built once at boot
(buildAuslampSet, main.js) from COLL[auslamp].surveys (which holds survey LABELS) resolved through
SMETA[label].slug. Empty when collections.json is absent or has no auslamp collection, in which case
IsAuslampSurvey() returns false for everything. NO MAP PATH READS IT since the dots-only
Its one consumer was the badge rule's never-collapse privilege, and nothing collapses now. Kept
because it is collection membership rather than map furniture; retiring it is a separate decision.
```

#### ausmt_id -> coordinate policy ('generalised' | 'withheld') for ...

```text
ausmt_id -> coordinate policy ('generalised' | 'withheld') for NON-EXACT stations,
loaded at boot from the OPTIONAL coord_policy.json (absent for an all-exact corpus => empty => no
badges - graceful degrade, same tolerant-of-absence pattern as collections/manifest). buildState()
folds it onto each station as s.coordPolicy; the drawer badges from that. It carries POLICY, never a
coordinate - positions are already masked in the catalogue (generalised => 0.1° cell, withheld => null).
```

#### The hand-off index: ausmt_id -> {level token: {bytes, url_path}} for ...

```text
The hand-off index: ausmt_id -> {level token: {bytes, url_path}} for stations with a VERIFIED route
into the NCI archive, loaded at phase 2 from the OPTIONAL ts_access.json. `null` means the fetch
has not settled; `{}` means it settled on absence, which is the honest answer for a deployment
that publishes no download index (a corpus with no verified routes ships no file). Membership is
the access rule: a withheld or coordinate-gated station is simply not in it.
```

#### BBMT stays off the copper action hex (#EF7256), and GDS off the ...

```text
BBMT stays off the copper action hex (#EF7256), and GDS off the
ok/status green (#5BAE6A), so a data-type marker cannot be mistaken for the selection accent or a
"good" status. LPMT teal is pinned (interaction test).
The four data-type hues are pulled further apart. BBMT #3F6FC4 -> #5E5ED6
(indigo) and AMT #A85CC4 -> #CDA1EC (light violet); LPMT teal and GDS magenta unchanged. The old AMT
purple sat only ΔE00≈10 from the GDS magenta (confusable); the new pair is ΔE00≈21 with a ~20 L*
lightness gap, and every data-type pair is now ΔE00≥21 (the four types are the four most mutually
distinct hues in the palette). These are the map-marker colours; the index.html --lpmt/--bbmt/--amt/
--gds tokens carry the SAME hexes so the filter legend, the type-filter swatches and the map agree
byte-for-byte. (plots.js TF-curve colours are independent and unchanged.) DIM_COL is a NON-STATUS
palette (a cool→warm violet/magenta ramp): dimensionality (1-D/2-D/3-D) is not a quality ranking, so it
must not borrow the red/amber/green status colours.
LP/BB SEPARABILITY: "Long Period and Broadband icon colours are
too similar". The earlier pair was ΔE00 26.1 on paper and still unreadable at site-dot size, because it
separated almost entirely by HUE (teal 222° vs indigo 299°) across only 9 L* - and small marks are
discriminated by VALUE, not hue. BBMT #5E5ED6 -> #3730B8: deeper and more saturated, which buys a 24.6 L*
gap and a 55.7 C* gap and lifts the pair to ΔE00 34.2. LPMT is deliberately UNCHANGED - the teal is the
established fabric colour across this portal and its atlases, so the other one moves.
The number that actually mattered is the DEUTAN one: simulated deuteranopia collapsed the old pair to
ΔE00 15.3 (protan 19.2); the new pair holds 25.3 / 30.1. That is the point of separating by lightness
and along the blue-yellow axis rather than by hue - a red-green deficient reader loses the hue argument
entirely, so a pair that leans on it is a pair that vanishes for them. The new BB also moves AWAY from
the AMT light violet (ΔE00 27.2 -> 44.0), so "deeper blue" did not buy LP/BB at AMT's expense.
All of it is recomputed and gated in tests/test_type_palette_separability.py; the floors are stated
there, not here, so a future edit cannot re-converge the pair by editing a comment.
```

#### The INK a type chip needs, which is not one colour for all four ...

```text
The INK a type chip needs, which is not one colour for all four: .chip's default near-black sits at
2.03:1 on BBMT's deep indigo (below WCAG AA's 4.5 and visibly muddy), where white reaches 9.22:1.
The other three are the other way round - white on AMT's light violet is 2.12:1 against 8.85:1 for
the default - so this is a per-type override, never a blanket flip. Measured, not judged by eye.
```

#### The time-series level vocabulary, [token, label, gloss], IN THE ORDER ...

```text
The time-series level vocabulary, [token, label, gloss], IN THE ORDER IT RENDERS.
These tokens ARE ts_access.json's keys, so the chooser, the drawer rows and the hand-off pointer
file all name a level the same way and none of them re-derives the list. `level2` is absent BY
BY DESIGN, not by omission: the archive's level_2 tree holds transfer functions,
not time series, so it opens no route, takes no button and gets no row here.
```

#### UX feedback round 1: "Go to place" (+ its AU_PLACES quick-zoom list) ...

```text
UX feedback round 1: "Go to place" (+ its AU_PLACES quick-zoom list) was removed as redundant - 
operator decision from the first live session; see index.html/filters.js for the rest of the removal.
Pb is the HONEST plain "AusMT". The pre-C22 value - "AusMT (DOI to be minted per
release via Zenodo)" - leaked into EVERY no-DOI citation's publisher/PB field of the exported .bib/.ris
Packs (hostile review: reference managers ingest that placeholder as real bibliographic
data). Absence of a DOI is expressed by OMISSION in .bib/.ris (drawer.js apa/bibtex/ris guard on a
falsy doi, since d2bc616) and EXPLICITLY in CITATIONS.txt ("[no DOI assigned]", exports.js citeLine) - 
never by placeholder text in a bibliographic field.
```

#### ---- display grammar: one period, one range and one licence, printed ...

```text
---- display grammar: one period, one range and one licence, printed one way ------------------
These three are JS TWINS of the engine's reference implementations (engine/extract/_pages.py:
_fmt_period, _range, _cc_human/_fmt_licence). A reader meets the same values on a static entity
page and in the workspace, so the two surfaces owe each other the same output; the parity is held
by tests/display_grammar.test.js against the worked examples the engine suite pins the Python leaf
against. Change one side and the other must move with it.
```

#### Round `v` to `d` decimals the way Python's format() does

```text
Round `v` to `d` decimals the way Python's format() does. The reason this is not a bare toFixed:
the two runtimes break an EXACT .5 tie differently - Python to the even neighbour, JS away from
zero - so a 1.25 s period read "1.3" in the workspace and "1.2" on the survey page. A tie is
exactly a decimal expansion that terminates in a 5 one place past the target, which is detectable
on the expansion itself; every other value toFixed already rounds correctly.
```

#### A period in seconds as a READER sees it; the stored value never changes

```text
A period in seconds as a READER sees it; the stored value never changes. Under 100: two
significant figures, trailing zeros stripped. At or above 100: a thousands-separated integer.
Never exponent notation, whatever the magnitude - "9.6e-05 s" is a number a processing log can
carry and a survey card cannot. The unit belongs to the caller's slot, not to this string.
```

#### ---- collection member colours: the same ramp the static collection ...

```text
---- collection member colours: the same ramp the static collection pages lay ------------------
A collection is drawn twice, as the static page's scatter and as the SPA's collScatter, and a reader
moving between them is entitled to find the same survey the same colour. This is the JS twin of
engine/extract/_pages.py _member_colours; tests/collection_colours.test.js holds the two to the same
lists. The palette leads while it can, so the common case matches exactly.
```

#### `n` distinct colours, deterministic in MEMBER ORDER and with no ...

```text
`n` distinct colours, deterministic in MEMBER ORDER and with no randomness anywhere. Past the
palette's eight the set stops CYCLING - which gave two surveys one colour and made the legend
useless - and becomes an evenly spaced hue ramp instead: hue i/n for the widest gap possible at this
many members, with lightness alternating between two bands so neighbouring hues still separate on the
dark ground.
```

#### The human form of a Creative Commons identifier, DERIVED from the ...

```text
The human form of a Creative Commons identifier, DERIVED from the identifier's own grammar rather
than from a hand-kept map: the prefix, the clause letters (which keep their internal hyphens:
BY-NC-SA), the version, and a jurisdiction port where one exists. A map covering only today's
corpus goes wrong silently - a 3.0, -AU, NC or ND id added to the instrument would print
"CC-BY-3.0-AU" on one card beside "CC BY 4.0" on the next, and display_grammar.test.js walks
contract.js's own tables to prove no recognised id is missing a form.
The DERIVATION runs over the identifiers the INSTRUMENT recognises, which is the engine's domain
exactly: _pages.py builds _LICENCE_DISPLAY from redistributable + recognised_only and _fmt_licence
echoes anything else. An id outside those tables is echoed here for the same reason - the SPA
saying "CC BY 2.0" where the survey page says "CC-BY-2.0" is one identifier read two ways across
two surfaces, and the badge beside it already tells the reader this licence is not recognised.
Non-CC ids (PUBLIC DOMAIN, ODBL-1.0, ALL RIGHTS RESERVED...) have no published reader's form and
are printed verbatim too, because guessing one would be inventing metadata.
The SPDX identifier itself stays untouched in exports, data slots and citation output.
```

#### CVD amendment: the completeness ramp is a CVD-safe SEQUENTIAL ...

```text
CVD amendment: the completeness ramp is a CVD-safe
SEQUENTIAL dark→light progression (viridis principle) - dark slate-blue #2A3B66 → olive #6E7F46 → pale
warm yellow #F2E27E - because the old red→green endpoints measured dE76≈9.6 under a deuteranopia
simulation (indistinguishable for red-green CVD readers). LIGHTNESS carries the signal (relative
luminance rises monotonically 0.046 → 0.75 along the lerp path), so the ramp survives all three
dichromacies: simulated low↔high separation deutan 106.8 / protan 103.1 / tritan 69.1 dE76. The olive
mid keeps the ramp off the lpmt teal and the ok green (every stop ≥17 dE00 from the data-type and
status colours), and the null/"not evaluated" grey #5A6E7D stays clearly apart from the dark low end
(dE00 20, L* 45 vs 26). The dark low end is marker-fill/dot material, so drawer text must not take
qColor as a text colour; it renders a .qvdot swatch beside plain readable text instead.
```

## portal/src/tour.js

#### Tour.js - 11-step spotlight tour

```text
Tour.js - 11-step spotlight tour. Classic script, zero deps,
loads LAST (after main.js) so it can call setView()/openStation()/other globals, but nothing in
main.js depends on it (a missing/broken tour.js must never break the intro panel or the app - see
the typeof guard in main.js).

Behaviour: never auto-starts (only "Take the tour" in the intro panel or the header link fires
it); steps whose target element is absent (e.g. empty-data state, or an enter action that found
nothing to open) render centred with no spotlight instead of crashing or silently skipping; Esc
closes; ArrowRight/ArrowLeft navigate; all controls are real <button>s with aria-labels; nothing is
persisted - the tour is stateless and re-runnable from either entry point on every visit.

Round 2 (operator feedback): the tour now NAVIGATES - it spotlights the header view buttons and
actually switches to the Surveys view, then returns to the map at the end, so a first-timer learns
the app's two views by watching them happen. Enter actions (run when the tour ARRIVES at a step,
forward or back) make that work in both directions: map-view steps force the map view back (so
stepping BACK from the Surveys steps re-shows map-only targets like .selbox). _tourOpened records
ONLY what the tour itself opened (drawer / hash), so stopTour() from ANY step - including
mid-Surveys - returns to the map and closes only tour-opened drawers, never state the visitor had
open before starting.

Two DEMO steps after the filter-rail overview - Find (types "AusLAMP"
with a real input event so the live dropdown + map filter run) and tree browse (scrolls one survey
row into view; kalkaroo-2022 preferred, first survey otherwise). Demo steps get an EXIT hook, run
on ALL three ways of leaving a step (Next, Back, and stopTour for close/Esc/Done), so demo state
(the typed query, the tree scroll) never leaks past the step - the same restore discipline as
_tourOpened, extended per-step.
Short step copy - the visible text is the authored deck,
VERBATIM. Selectors + enter/exit hooks are UNCHANGED (the Find demo still types "AusLAMP", the selbox
step still switches rail mode, etc. - only the visible copy changed).
```

#### Surveys-view step enter action

```text
Surveys-view step enter action. Named by SELECTOR, not by index: a step inserted mid-deck left every
numbered comment in this file one behind, so the numbers are gone. It actually switches to the Surveys
view, because the navigation IS the lesson. setView closes any open drawer itself; _tourOpened.drawer
is left as-is because closeDrawer() is a safe no-op double-close at restore time.
```

#### The .selbox step's target lives in the rail's Select & download mode ...

```text
The .selbox step's target lives in the rail's Select & download mode pane,
which is hidden in the default Browse mode (zero rect => the step would fall back to the centred
no-spotlight card). Enter: force the map view, save the visitor's rail mode, and switch to
Select & download so the target is visible and spotlit. Exit (Next/Back/close - the same three-path
discipline as the Find/tree demos): put the saved mode back, so the tour never leaks a mode change.
Guarded so a build without the mode split degrades to the plain centred-card behaviour, no crash.
```

#### Find demo

```text
Find demo. Enter: save the visitor's own query (restore discipline - only undo what the
tour did), type "AusLAMP" and dispatch a REAL bubbling input event so the live wiring in filters.js
(refresh() + renderFind()) filters the map and renders the actual dropdown - the demo is the real
code path, not a mock. Exit: restore the saved value with another input event (so the filter state
is genuinely restored) and hide the dropdown, matching the click-away behaviour in filters.js.
```

#### Tree browse demo

```text
Tree browse demo. Enter: save the tree scroll AND
the expand/collapse state, EXPAND the target row's ancestors (country + org, via the same
treeSetCollapsed API the carets use - a collapsed rail must never hide the demo), then bring the
row into view - kalkaroo-2022 preferred (via SLUG_TO_SURVEY, the authoritative slug->label map),
degrading to the FIRST survey present so a data-dependent id can never crash the tour (empty
portal: no-op, step renders centred per the absent-target pattern). No checkbox is touched. Exit:
put back the saved scrollTop and the saved collapse set - on all three exit paths (Next/Back/close).
```

#### Station-drawer step enter action: open the first VISIBLE station's ...

```text
Station-drawer step enter action: open the first VISIBLE station's drawer (reuse openStation), same
as clicking its marker - forcing the map view first so it also works stepping back from the Surveys
steps. No-op (step renders centred, no spotlight) when nothing is visible - e.g. the empty-data
state or every station filtered out - matching the existing "absent target" pattern below.
```

#### Final map step enter action (by selector, not index): close whatever ...

```text
Final map step enter action (by selector, not index): close whatever drawer the tour opened and
land back on the map. The loop's
closing beat. Uses the same restore path as stopTour() so behaviour is identical whether a visitor
reaches step 8 by stepping through or jumps back to it.
```

#### The LEADER is an SVG overlay spanning the viewport; a line + arrowhead ...

```text
The LEADER is an SVG overlay spanning the viewport; a line + arrowhead connect the centred
card to the spotlight. Its z-order sits BETWEEN the spot (which carries the dim) and the card (see CSS),
so the line reads over the dim and the card stays on top. The line element is held directly (not looked
up) so it is robust in jsdom, which does not render SVG; the arrowhead marker is browser-only cosmetics.
```

#### SETTLE-UNTIL-STABLE re-layout

```text
SETTLE-UNTIL-STABLE re-layout. Some steps' enter hooks trigger layout changes on their
OWN target that keep going AFTER _tourLayout first measures it. The station-drawer step (index 4) is the
worst case: openStation (a) renders the facts panel synchronously, then adds .open, which (b) SLIDES the
drawer in via a CSS transform transition (index.html: transform translateX(102%) -> none, .16s ease) so its
getBoundingClientRect().left travels leftward over ~160ms; then (c) an ASYNC station.json fetch injects the
frame line (drawer.js loadStationFrameLine) and reflows the drawer's HEIGHT; and (d) the deferred map home
re-fit can reflow the map column under it. The drawer box therefore MOVES and RESIZES several times across
~1s. A single transitionend re-measure fires after the SLIDE only (stage b) and leaves the spotlight on a
Stale early box. The robust
fix: after entering a step, POLL the target rect each animation frame; on ANY change - position OR size (a
size-only ResizeObserver misses the slide, which MOVES the box) - re-run _tourLayout so the spotlight tracks
the box; stop once the rect has held STABLE for _TOUR_SETTLE_STABLE_MS, or after a hard _TOUR_SETTLE_CAP_MS.
General, not a step-5 special case: a static target reads stable on the first frame and the watcher stands
down immediately; the map steps re-measure an unchanging box harmlessly. The transitionend hook is KEPT as
a cheap extra nudge (it re-lays-out the instant a transition ends) but is not relied on alone. The
watcher is ATTACHED on arrival and DETACHED on EVERY departure (Next/Back/close/teardown) - the rAF handle
is cancelled and the listener removed - so no poll loop or listener leaks past the step or the tour.
jsdom has no layout engine and its rAF is driver-controllable, so the pin drives synthetic rect changes +
a stubbed clock through the queue to prove the re-run/stop/detach wiring; the sub-second proof is a browser
run. _tourLayoutRuns is bumped by _tourLayout purely so the pin (and the browser probe) can observe re-runs.
```

#### The tour card is CENTRED for EVERY step (the pattern formerly used only ...

```text
The tour card is CENTRED for EVERY step (the pattern formerly used only as the no-target
fallback, now generalised). This PURE fn returns the card's fixed-position box. Base = the viewport
centre. OVERLAP RULE: when a target rect would sit under the centred card, nudge the card by the MINIMAL
vertical offset so it clears the target by _TOUR_CLEAR - deterministically DOWNWARD when that still fits
the viewport (bottom margin _TOUR_M), else UPWARD. No-DOM so the driver pins centred-always + the nudge on
synthetic rects (jsdom has no layout engine), exactly as the retired _tourPlace was.
```

#### Geometry of the LEADER from the centred card to the spotlight

```text
Geometry of the LEADER from the centred card to the spotlight. PURE - the endpoints are the
boundary points where the card-centre<->spot-centre axis crosses each rect, so the line leaves the card
edge nearest the target and lands on the spot edge nearest the card (arrowhead at the spot end). visible
is false when suppressed - the map steps (the spotlight over the map IS the cue) and the no-target
fallback. No-DOM so the driver pins the endpoints + suppression on synthetic rects.
```

#### A COLLAPSED rail hides every child but the collapse button, so the rail ...

```text
A COLLAPSED rail hides every child but the collapse button, so the rail steps (Find, the tree, the
Select and Download boxes) would spotlight nothing and narrate controls that are not on screen -
exactly what a returning visitor who collapsed the rail gets from About's ?tour=1 link. Expand it
for the run and record that WE did, so _tourRestore puts the visitor's own choice back.
```
