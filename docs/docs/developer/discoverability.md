# Discoverability: pages, structured data, sitemap and cards

How a survey, a collection or the portal itself is found, and what each served document says about
itself. This is the field reference for the tier-3 pages, the JSON-LD nodes they carry, the sitemap's
membership rule and the link-preview cards.

## Normative artifact

| | |
|---|---|
| Normative artifact | `engine/extract/_pages.py` and the sitemap block of `engine/extract/build_portal.py` |
| Static pages | `portal/*.html`, which the engine does not write |
| Version | none declared; every surface here is additive |

Where this page and the build disagree, the build is right.

## One flag turns the whole tier on

```text
python -m extract.build_portal --surveys <dir> --out <data> --sitemap-base https://ausmt.auscope.org.au
```

Without `--sitemap-base` the build writes no `pages/` tree, no cards and no `sitemap.xml`; the product
set is byte-identical either way. The flag is the URL base every absolute address on those pages is
built from, so a staging build advertises staging addresses and nothing has to be rewritten later.

`portal/robots.txt` names the sitemap at the institutional address and keeps crawlers off
`/gateway`. It is a shipped static file, not a generated one.

## The pages tier

Six kinds of document, written under `<out>/pages/` and served at the path-URL contract's shapes.

| Kind | Written to | Served at | Indexed |
|---|---|---|---|
| survey | `pages/surveys/<slug>.html` | `/surveys/<slug>` | yes |
| surveys hub | `pages/surveys/index.html` | `/surveys` | yes |
| collection | `pages/collections/<id>.html` | `/collections/<id>` | yes |
| collections hub | `pages/collections/index.html` | `/collections` | yes |
| station | `pages/stations/<ausmt_id>.html` | `/stations/<ausmt_id>` | no, `robots noindex` |
| survey hand-off | `pages/fetch/<slug>.json` | `/data/pages/fetch/<slug>.json` | not a page: the document a survey page's download cards fetch, written only for a survey with a routed time-series row |

A survey's abstract may run to several paragraphs; the corpus writes one line per paragraph, and
the survey page renders one prose element per line (the SPA's drawer keeps the breaks with
`white-space: pre-line`). The lede is still the abstract's first sentence and the meta
description stays one line.

A survey page's download cards open the portal's "Fetch from your terminal" dialog in the page:
each card's "Build a download script" fetches `/data/pages/fetch/<slug>.json` and composes the wget
or curl command with the portal's own modules (`/src/fetchcmd.js`, `/src/fetchdialog.js`,
`/src/page-fetch.js`, loaded at the end of the body; the pages carry no inline script). The card's
href is the SPA deep link `#/survey/<slug>?fetch=<level>`, which opens the same dialog, and the card
also links the document itself as "Pointers file (JSON)".

The surveys hub can be searched, filtered and sorted in the browser. The page renders its controls
hidden, with option lists drawn from the rows it lists and each card's facts as data attributes,
and loads one script, `/src/surveys-hub.js`, at the end of the body to reveal and drive them; the
view rides the URL query (`/surveys?type=GDS&sort=newest`), and without script the page is the
whole list in title order.

Station pages are deliberately unadvertised but served. Thousands of templated documents would read
as thin content at scale and dilute the survey and collection pages that carry the ranking, so they
declare `noindex` and stay out of the sitemap; they keep working for anyone following a published
link, which is what the URL contract promises.

Every page is rendered from the already-served public documents alone, so a page can never disclose
anything the gated products do not already publish.

## Page chrome and appearance

Every engine-written page wears the portal's own header, footer, icon links and appearance, so a
reader arriving on a survey page from a search result meets the same site the map shows. The
appearance is the AuScope house style, and it is the only one (Owner decision 2026-10-15): no page
offers a choice, loads an appearance script or declares a second set of colours.

### The token block

The pages are served under a CSP whose `script-src` is `'self'`, so they carry no inline script and
no inline event handler, and a page without a time-series card or the hub's controls loads no script
at all. The stylesheet opens with the portal's token block in `:root`, the house style. Every chrome
colour on a page is one of these tokens; the fetch dialog's scrim and drop shadow are the only
colour values written outside the block.

| Token | Used for |
|---|---|
| `--bg` | the page ground |
| `--surface` | the header, the footer, cards and dialogs |
| `--surface-2` | inputs, inactive tabs, chips and raised rows |
| `--line` | rules and borders |
| `--text`, `--muted` | body text and secondary text |
| `--heading` | headings and the AusMT wordmark |
| `--accent`, `--accent-ink` | links, the active tab, selection and focus rings, and text set on the accent |
| `--lpmt`, `--bbmt`, `--amt`, `--gds` | the data-type ramp, a data encoding rather than chrome |
| `--map-panel`, `--map-line`, `--coast-fill`, `--coast-line` | the map panels and the coastline |
| `--dot-edge` | the edge every station mark is stroked with |
| `--ok` | the time-series availability marks |
| `--part` | the embargo notice's border |

A card is a `--surface` box with a 1px `--line` border, a 4px corner radius and the `--shadow`
token, a soft shadow. The type stack is `--sans`, which names Libre Franklin first; the face is not
bundled, so the stack falls through to Inter and the system faces, which is intended. The header's
wordmark alone leads with Calibre, AuScope's typeface, over `--sans`: AuScope's licence covers it on
this site, but no page declares an `@font-face` and no font file is served yet, so a reader without
the face installed sees `--sans`.

### Header

The header is the portal's header with two declared differences: the identity is a link to the
root rather than the map page's heading, and the three tabs are links with the current page's tab
active.

- Left: the AuScope mark, then the AusMT wordmark linking the root. The mark is the brand kit's
  vector icon, `/vendor/auscope/auscope-mark.svg`, drawn 36px square. The wordmark is set at the
  AuScope logo's own proportions scaled to that mark: the zone's 12px gap from mark to name, 24.5px
  type whose cap height is 0.48 of the mark, and "Aus" at weight 900 against "MT" at 300, tracked
  at .02em. The mark is the header's only fetched asset.
- Centre: Map, Surveys and Collections, then About. There is no Contribute control in any header;
  `add-survey.html` stays served and About links it from its body.
- Right: the tagline, "Magnetotelluric Data Discovery & Access", at 14px on one line. Where its
  zone is narrower than the line, from 761px to about 976px of viewport, it ends in an ellipsis
  inside the zone rather than spilling over the About control.

The header is 57px tall from 761px of viewport up. The site draws the 2025 AuScope brand kit's own
files, which carry Tasmania (Owner decision 2026-10-13). The mark opens every header, the tagline
closes it and the AuScope and NCRIS lock-up moved to the footer (Owner decision 2026-10-13).

### Footer

Three regions, the same on every page apart from the status slot.

- Left: `MTCAT JSON ↗`, linking `/data/mtcat.json`.
- Centre: "AusMT is enabled by AuScope · Data licences vary by survey". "AuScope" is the region's
  one link, opening `https://www.auscope.org.au` in a new tab with `rel="noopener noreferrer"`; the
  address is not printed (Owner decision 2026-10-13).
- Right: the page's status, then the AuScope and NCRIS lock-up (Owner decision 2026-10-13). The
  status is what the page can state about itself: the surveys hub states its catalogue counts, and
  every other page has none, so its right zone is the lock-up alone. The lock-up is the brand kit's
  own colour PNG, `/vendor/auscope-ncris-colour.png`, declared at its intrinsic 1919 by 325 and
  drawn 30px tall, linking `https://www.auscope.org.au` in a new tab with
  `rel="noopener noreferrer"`. A negative block margin makes its margin box one footer text line, so
  it does not make the sticky footer taller. The footer carries no control.

The footer fetches the lock-up and nothing else, and carries two anchors to AuScope, the
centre's name and the lock-up. Its box, its regions and its narrow-width states are one rule set
with the portal's documents, held by `portal/tests/test_footer_regions.py`. On the surveys hub the
counts wrap beside the lock-up from 557px to 890px of viewport, which makes that footer one line
taller there.

### Icons

Every page links the same three icons as the portal's documents, in this order: `/favicon.ico`,
`/vendor/favicon.svg` and the 180 px app icon `/vendor/auscope/icon-180.png`.

### Maps

The survey hero map, the station-grid zoom, the hub card maps and the collection map carry no
colour of their own beyond the data. The panel is a `<rect class="mm-panel mm-rule">` (ground
`--map-panel`, frame `--map-line`), the coast rings are `mm-coast` (`--coast-fill` and
`--coast-line`), the state borders and the zoom's coastline are `mm-line`, and the locator ring and
the scale bar are `mm-note` and `mm-label` in `--muted`.

Station marks keep their literal fills, because the ramp is a data encoding and not chrome: LPMT
`#3F88C8`, BBMT `#FFC14F`, AMT `#9FCB5A` and GDS `#CE348A` (`_TYPE_COL`, byte for byte the portal's
`TYPE_COL` and the `--lpmt` to `--gds` tokens), and the collection member palette unchanged. Every
mark sits in a `.mm-dots` group that strokes it in `--dot-edge`, which keeps the lighter hues
legible on the light panel.

The collection map's corner mark is the AuScope mark, the file every header opens with, placed and
sized as before.

The link-preview cards are PNGs and read no stylesheet. They keep their navy ground, the one their
white wordmark and tagline inks are chosen for, and the collection card's map states its own colours
(`_MAP_PANEL`, `_MAP_PANEL_LINE`, `_COAST_FILL` and `_COAST_LINE`).

### Deploy order

`/vendor/*` and `/src/*` are served from the portal image and the pages tree from the data volume,
so the two can be a deploy apart. A pages tree that names a file the running image does not serve
shows alt text in place of its images, so the portal image goes out first;
`/vendor/auscope/auscope-mark.svg` (every header's mark and the collection map's corner mark) and
`/vendor/auscope-ncris-colour.png` (every footer's lock-up) each answering 200 is the check before
the pages tree is swapped.

## Structured data, by page kind

Each node is emitted as its own `<script type="application/ld+json">` element, in the order below.
The entity node stays first wherever a page has one, so anything reading "the page's structured
data" gets the record the page is about rather than its breadcrumb.

| Page | Nodes |
|---|---|
| `portal/index.html` | `DataCatalog`, then `WebSite` |
| survey page | `Dataset`, then `BreadcrumbList` |
| collection page | `Dataset`, then `BreadcrumbList` |
| surveys hub | `BreadcrumbList` |
| collections hub | `BreadcrumbList` |
| station page | none |

`WebSite` names the site itself: `AusMT`, with `alternateName` "Australia's Magnetotelluric Data
Portal" and AuScope as publisher. Before it existed the only site-level name anywhere in the markup
was the publisher's, inside the catalogue node, and search results labelled the whole portal
"AuScope". The two nodes are separate blocks rather than a `@graph`: a graph would put both behind
one array and hide the catalogue from anything that reads the first block.

`BreadcrumbList` names match the page's VISIBLE crumb word for word, because that is what Google
requires of the markup. The hub crumbs read `AusMT / surveys` and `AusMT / collections` in lower
case, so the markup says `surveys` and `collections`; changing the rich result means changing the
visible crumb first.

Station pages carry no structured data at all. A breadcrumb on a `noindex` page describes a rich
result that can never be rendered, and this is the one tier where a block per document is worth
counting.

Every engine-written page declares `og:site_name` = `AusMT`, station pages included: an inbound link
lands on those most often, and a preview card that names the wrong site is wrong wherever it is
shared.

## What a link preview says

Every page that carries the Open Graph set carries `twitter:title`, `twitter:description` and
`twitter:image` beside `twitter:card`. X, Slack and Teams read those names before falling back to
`og:*`, and a consumer reading only that namespace found a card type and an image with no title and
no summary. The mirrors are emitted from the same strings the og tags take, in one block, so a title
that changes cannot go stale on one surface and not the other.

The collections hub titles itself `Collections - Australian magnetotelluric data - AusMT` and each
collection page `<name> - Australian magnetotelluric data - AusMT`. Both name the national holding
the page belongs to, which is what a search result and a preview print. The surveys hub and the
survey pages keep their own wording, which names the kind of record the page is.

A collection's preview line is its record's FIRST sentence and nothing after it. Where the record
carries no description the page emits neither description tag, in either vocabulary: `content=""`
tells a crawler the page has no summary, where a missing tag lets it build one from the document.
The JSON-LD node keeps a fallback sentence, because a `Dataset` with no description is an invalid
item to a search engine.

Survey and collection preview lines are bounded at 160 characters, cut at a sentence end where
whole sentences fit and at a word boundary otherwise, and wear a trailing ellipsis only where
text was actually dropped. A station's line is one constructed sentence naming the station and
its survey, so it is carried whole.

## The sitemap's membership rule

`sitemap.xml` is written at the data root and carries, in this order:

* the site root,
* the two hub pages,
* one URL per survey page and one per collection page,
* the static portal pages `about.html`, `releases.html` and `add-survey.html`.

Two exclusions are deliberate. Station pages are `noindex`, so they are reconciled from the served
station documents instead of from the sitemap. `brand.html` is an asset shelf reached from About by
anyone who needs a logo file; it declares its own `robots noindex`, and a sitemap entry for a page
that refuses indexing asks the crawler for work it must then discard. `brand.html` is deliberately
NOT disallowed in `robots.txt`, because blocking the crawl would stop the crawler ever reading the
noindex.

Every non-root sitemap URL is reconciled against a document this build actually wrote
(`_reconcile_pages_with_sitemap`), and any mismatch fails the build. An advertised 404 is a build
error, not a warning.

The static pages carry no `<lastmod>`. None of them has an honest change signal, and the contract is
that the field is emitted only where it is true.

## Link-preview cards

Four card families, all 1200 by 630 PNGs on one ground, all declared as `og:image` on the page they
belong to. The ground is the root card artwork's own, so the families a link preview can land on read
at one brightness rather than as several slightly different dark blues.

| Card | Written to | Served at | Drawn by |
|---|---|---|---|
| survey | `pages/og/<slug>.png` | `/data/pages/og/<slug>.png` | `_og_card` |
| collection | `pages/og/collections/<id>.png` | `/data/pages/og/collections/<id>.png` | `_og_collection_card` |
| hub | `pages/og/surveys.png`, `pages/og/collections.png` | `/data/pages/og/surveys.png`, `/data/pages/og/collections.png` | `_og_hub_card` |
| root | not generated per build | `/vendor/social-card.png` | `portal/tools/gen_social_card.py`, hand-run |

The collection cards take a subdirectory of their own: `pages/og/` is flat, and a collection id equal
to a survey slug would otherwise overwrite that survey's card, silently and only for the pair that
collided. The two hub cards share that flat tree by name, so a survey slugged `surveys` or
`collections` is refused before the build writes anything: it would replace a hub's card, and the hub
page would then advertise a survey.

The cards live in the data volume, which is served under `/data/*`. The `pages/` tree has no bare
route of its own, so `{base}/data/pages/og/...` is the only URL at which a card is reachable; a
`{base}/pages/...` form advertises a 404 to every preview fetcher there is.

A page is handed its card URL only after the file is on disk. The survey pages used to derive the URL
from "is Pillow importable", which is a claim about the environment rather than about the file, so a
failed write shipped an `og:image` that resolved to nothing. A card that was drawn but not written
now fails the build; a page with no card falls back to the root card.

Pillow is required wherever the corpus has surveys, and the build refuses without it. Gated on
importability alone the loss was silent: every card vanished, every page fell back to the root card
and the build still returned 0, so the whole preview surface could regress into a deployment with
nothing failing. A corpus with no surveys draws no card and builds without Pillow, which is what a
machine that only needs the products needs.

### What each card shows

The survey card carries the survey's title, its station count and type, its region and years, its
period band, a footprint panel of its stations and an Australia locator inset. The inset is
composited at 70 per cent over the footprint it explains, so the stations it covers still show
through it; only its centre marker, the one mark that says WHERE, is drawn at full strength. The
footprint's kilometres are a number the survey PAGE carries: on a card they crowd out the period
band a reader can actually use.

The footprint panel is the same box on every survey card, and the station extent is fitted into it:
one scale on both axes, so a traverse arrives as a traverse rather than stretched to fill the frame;
ten per cent of the panel kept clear on every side, so no station sits on the rule; and the whole
extent centred on both axes. A panel fitted to its own data instead would change the card's
composition per survey, and an east-west traverse would collapse it to a strip against the top of
the card with the rest of the frame left empty. What the fit optimises is the viewport and never the
data: no station is moved, merged, thinned or dropped to make a footprint read better.

The collection card is a preview of the collection page's own map: every member station, coloured by
member survey in the collections hub's palette and member order, so one survey is the same colour on
the hub, on the collection page and on the card. It carries no locator inset, because a grouping of
surveys spanning a continent has no single place to point at. Two things differ from the hub's SVG on
purpose: the dot radius follows the survey card's raster rule, because a preview is resampled to
about a third of its width by the clients that show it and the SVG's radius would vanish there; and
the dots are drawn opaque, because this card has neither a legend nor a hover, so translucency buys
nothing and costs contrast. A collection whose members disclose no position at all gets no card,
rather than a bare coastline that would read as a collection with no coverage.

The collection card's facts are its member and station counts, its type and status, and its temporal
coverage. The coverage comes from the collection record and from nowhere else: a record still taking
members has no end year to give, so its coverage runs to the present; a record that makes no such
claim states its start alone, because a closed range needs an end year the record does not hold and
the date it was last maintained is not one. A record carrying no start year gets no coverage line.

The hub cards preview a catalogue rather than a place, so their artwork is the site's identity and
not a map of data: the full pixelated Australia, DRAWN from the same coastline the brand mark is
derived from on a lattice finer than the mark's, with the palette stops, the ramp positions, the
clear fraction and the dot radius all read from `contract/brand.json` at draw time. Run at the mark's
own grid the lattice reproduces that file's dot list cell for cell, which is what makes the card the
same silhouette at a second resolution rather than a second silhouette; the mark stays the simplified
figure that has to survive a browser tab. No vendored image is read: the engine image ships no portal
tree, and a card that reached for one would go blank exactly where the corpus is served.

A hub card's lines are its title, the tagline the brand file declares, and the counts this build
computed, summed from the same rows the hub page renders from. A corpus that grows renders its own
numbers, and the artwork is drawn large and resampled down so the dots are round rather than stepped,
which is also what makes these the heaviest cards the build writes: they carry a declared byte budget
for that reason.

### The text column

Every card declares the width its left column may use, and no ink crosses it. The title walks the
size ladder, first as a single line and then at each further line the card has room for, and takes
the largest size that holds the whole title; the fact lines below it wrap rather than run past the
column edge, and each block starts at the later of where the block above ended and its own slot, so
a card whose text all fits keeps the baselines the design was drawn on and a card whose text wraps
pushes what follows down instead of overprinting it. Truncation is the last resort and it is marked:
a silently cut title is a title the card gets wrong.

The survey card's column stops well short of its footprint panel, because the gutter between a title
and a bordered panel has to read as space rather than as a near miss. The collection card's column
is narrower, and is derived rather than declared: its map is drawn at 1.2 times the survey card's
panel width, because a collection map is read for the SHAPE of a programme's coverage and that shape
arrives at about a third of this width in a feed, and the column is whatever that enlarged panel
leaves at the same air it keeps against the card's own edge.

### The left column

Every generated card carries one column on the text margin, top to bottom: the AusMT lockup, the
kind label, the title and its facts, the address, the AuScope lockup. The root card carries no
lockup of its own: its artwork IS the mark, at full size.

The AusMT lockup is the mark with the word beside it. The word's size, its gap from the mark and its
ink are read from `contract/brand.json` at draw time and scaled by the mark's height, so the lockup
on a card and the lockup on every other surface are one set of proportions rather than two that
happen to agree; no number of the lockup's is restated in the emitter. `contract/` is a sibling of
`engine/` and the engine image ships it, so the read resolves in the image as well as in a source
tree.

The kind label names what the reader has landed on before the title does: tracked caps in a muted
ink, saying SURVEY, COLLECTION, or the plural a hub carries. The card emitters take that word as an
argument rather than knowing it, so a further card family takes the same column by passing its own.

Below the label the title walks the size ladder, then the facts: the station count and type joined
by an interpunct, the region and years, the period band. An absent value is skipped rather than
reserved, and the period band follows the block instead of standing on a slot of its own, so a
survey that discloses no region closes the gap instead of leaving a hole. The block also has a
ceiling: the address and the AuScope lockup close the column on fixed lines, and the block keeps a
declared clear space above the address's own first ink row, measured on the glyphs the face sets
rather than on the nominal point size.

A value that does not fit is not an absent value, so nothing the survey disclosed is given up to
make room under that ceiling. The title has a ladder and the block's sizes are declared, so the step
comes out of the title: under each title step the block closes its leading, and when that is not
enough the title takes the next step rather than setting a fact line below its declared size. Only
after the title's whole ladder has run out does the block's type give, which is the last resort that
still fits everything on the card. The title and the block are therefore chosen together, and the
last step of both ladders holds the most a card can carry, so the walk always has an answer.

The engine draws the mark from a small pinned derivative,
`portal/vendor/brand/ausmt-mark-168.png`, emitted by `gen_brand.py` from the same lattice as every
other brand export and gated by `gen_brand.py --check`. It exists because the engine image ships no
portal tree and so must carry its own copy of whatever it draws with; the 1024 px mark would put a
third of a megabyte in that image to be shown at a fraction of the size. 168 is a whole multiple of
the height the card draws at, so the resample is a clean box rather than an arbitrary ratio.

### The address and the AuScope lockup

The address `ausmt.auscope.org.au` closes the block on a line of its own, on the card's text margin,
in the coral accent read from `contract/brand.json`. It carries no mark beside it: the column
already opens with one lockup and closes with another, and a third mark on that line reads as a logo
with a caption.

The AuScope lockup is last, on the same margin, keeping a declared clear space against the card's
bottom edge so the column ends on one line across every family whatever the block above it does. It
is the AuScope half of `portal/vendor/auscope-ncris-white.png`, cut at column 1200 of that 1919 by
325 image and trimmed to its alpha bbox: the columns to the right carry a second organisation's mark
and a descriptor line that is unreadable at card height, and the site footer already carries the full
lock-up. It is drawn no taller than the AusMT mark above it, which is how the acknowledgement is kept
from outweighing the resource identity it acknowledges. The site's chrome draws the colour twin of
that PNG, `portal/vendor/auscope-ncris-colour.png`, on its light ground; the white file ships for
the cards alone.

The address is set in Inter Bold on all three families. The root card's artwork is set in that face,
so the generated cards adopting it is what makes the three addresses one line rather than three that
happen to say the same thing; the rest of a generated card's type stays in Pillow's bundled face,
which ships with the library and so cannot go missing.

The engine ships its own copy of everything it draws with, beside the emitter and pinned against the
portal's copy in tests: `engine/extract/_auscope_lockup.png` against the crop of
`portal/vendor/auscope-ncris-white.png` described above, `engine/extract/_ausmt_mark.png` against
`portal/vendor/brand/ausmt-mark-168.png`, and `engine/extract/_inter_bold.ttf` against
`portal/tools/brand_font/Inter-Bold.ttf`, whose Open Font Licence ships beside it. The lockup's pin
compares DECODED pixels, because a re-encoded crop's bytes move between Pillow builds while its
picture does not; the other two are byte pins on files nothing re-encodes. The engine image carries
no portal tree, so an emitter that reached across to the portal would draw an unsigned card in
exactly the environment that serves the corpus. These four files are listed under
`[tool.setuptools.package-data]` in `engine/pyproject.toml`: the repository installs the engine
editable everywhere it runs, so the list declares the intent rather than repairing a live break, but
a card asset added beside the emitter belongs on it.

### The root card is a composite, not a render

`portal/vendor/social-card.png` is hand-made artwork. Nothing in this repository draws its
dot-Australia, so the signature row could not be changed by re-rendering the card.
`portal/tools/gen_social_card.py` clears the one band the address occupies, sets the address again
in the artwork's own face at the size the design asks for, and composites the mark onto the text
margin beside it; the untouched artwork ships beside the card as
`portal/vendor/social-card-source.png` and is what `gen_brand.py` records as the palette's source.

The tool verifies its assumptions before it writes: it refuses if the band it is about to clear
carries anything but address ink, or if the row it is about to draw would not fit inside that band.
It is hand-run and deliberately not wired into `gen_brand.py --check`, which compares pixels exactly; a
resampled paste is the one artefact whose bytes could legitimately move under a Pillow upgrade with
no brand decision behind it. `portal/tests/test_social_card.py` holds it with the same
tolerance-based geometry pins the generated cards answer to, and runs
`gen_social_card.py --check` so the committed card and its generator cannot drift apart in silence.

## Static portal pages

`portal/*.html` are shipped, not generated. `index.html`, `about.html`, `releases.html` and
`add-survey.html` each carry a canonical, a meta description and the Open Graph set; `brand.html`
carries a canonical, a description and `robots noindex`.

Descriptions are the page's own lede, word for word, and `og:title` is the page's own `<title>`. An
invented summary is a second wording of the page that nobody maintains and that drifts the first time
the page is edited. `portal/tests/test_page_metadata.py` pins both rules against the page bodies.

### Site icons

Every page, the static ones and the generated ones alike, links the same three icons in its head, in
this order and in this form:

```html
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/vendor/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/vendor/auscope/icon-180.png">
```

The hrefs are root-anchored, because a generated page served at `/surveys/<slug>` cannot resolve a
relative vendor path, and none carries a query: a search engine keeps the icon URL it found on the
home page, so a change to an icon replaces the bytes at the same path. No web manifest and no
pinned-tab mask icon ship. `portal/tests/test_favicon_and_app_icons.py` holds the block on every
static page and in the engine's page shell.

The icons are the AuScope mark, Royal Blue with its lighter swoosh, not the AusMT mark
(Owner ruling 2026-10-12). `portal/tools/gen_auscope_icons.py` renders all five files from
`portal/vendor/auscope/auscope-mark.svg` and from nothing else. That file is derived from the
AuScope brand kit's own vector icon, with the fills the kit states, `#272472` and `#A7A2C5`
(Owner decision 2026-10-13), so a change to the mark is a change to that file and a rerun of the
tool:

| File | What it is |
|---|---|
| `portal/vendor/favicon.svg` | The mark's own path elements, verbatim, in a viewBox cropped to the ink, with a title of AuScope. Transparent. |
| `portal/favicon.ico` | 16, 32 and 48 px frames of the mark, edge to edge on its longer side, on a transparent ground. A browser that reads no SVG icon asks the site root for this file by name. |
| `portal/vendor/auscope/icon-180.png` | The apple-touch-icon: the mark centred at 70 percent of the width on an opaque white square. A home screen fills transparency with black, so the ground is opaque. |
| `portal/vendor/auscope/icon-192.png`, `icon-512.png` | The same at the two sizes a web manifest names, so that adding one later costs no regeneration. |

The tool renders with Pillow alone: each path of the mark is flattened to a polygon (64 line pieces
per curve), the polygons are filled in source order at eight times the icon's size, and the result is
resampled down with Lanczos, which keeps the edges of the 16 px frame clean. Pillow is in the lock
environment and in CI, so `python3 tools/gen_auscope_icons.py --check` and every pin in
`portal/tests/test_favicon_and_app_icons.py` run wherever the portal tests do. The check compares
`favicon.svg` byte for byte and each raster as its decoded picture: the PNGs by mode, size and pixels,
and `favicon.ico` by its frame sizes and each frame's pixels. A different Pillow can encode the same
picture as different bytes, so a byte comparison would go red on an encoder upgrade, while a
one-pixel edit goes red under the picture comparison.

The icon URLs are stable, so the edge serves them with `Cache-Control: no-cache` and revalidates the
bytes (`@iconAssets` in `deploy/docker/caddy/Caddyfile`, which names `/vendor/favicon.svg` and
`/vendor/auscope/icon-*.png` and excludes them from the thirty-day `vendor/` cache). A replaced mark
reaches a home screen on its next fetch instead of a month later.

The AusMT mark stays the product mark. `portal/tools/gen_brand.py` writes every AusMT export
under `portal/vendor/brand/`, held by `gen_brand.py --check` in CI; the brand page offers them and
the link-preview cards carry the mark. Its three app icons (`ausmt-icon-180.png`, `-192.png` and
`-512.png`, the mark on a navy disc) remain brand-kit files for anyone placing the AusMT mark on a
tile, and no page links them.
