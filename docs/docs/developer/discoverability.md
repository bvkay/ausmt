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

A survey page's download cards open the portal's "Fetch from your terminal" dialog in the page:
each card's "Build a download script" fetches `/data/pages/fetch/<slug>.json` and composes the wget
or curl command with the portal's own modules (`/src/fetchcmd.js`, `/src/fetchdialog.js`,
`/src/page-fetch.js`, loaded at the end of the body; the pages carry no inline script). The card's
href is the SPA deep link `#/survey/<slug>?fetch=<level>`, which opens the same dialog, and the card
also links the document itself as "Pointers file (JSON)".

Station pages are deliberately unadvertised but served. Thousands of templated documents would read
as thin content at scale and dilute the survey and collection pages that carry the ranking, so they
declare `noindex` and stay out of the sitemap; they keep working for anyone following a published
link, which is what the URL contract promises.

Every page is rendered from the already-served public documents alone, so a page can never disclose
anything the gated products do not already publish.

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
acknowledgement. It is drawn no taller than the AusMT mark above it, which is how the acknowledgement
is kept from outweighing the resource identity it acknowledges.

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
