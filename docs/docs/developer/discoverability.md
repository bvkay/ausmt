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

Five kinds of document, written under `<out>/pages/` and served at the path-URL contract's shapes.

| Kind | Written to | Served at | Indexed |
|---|---|---|---|
| survey | `pages/surveys/<slug>.html` | `/surveys/<slug>` | yes |
| surveys hub | `pages/surveys/index.html` | `/surveys` | yes |
| collection | `pages/collections/<id>.html` | `/collections/<id>` | yes |
| collections hub | `pages/collections/index.html` | `/collections` | yes |
| station | `pages/stations/<ausmt_id>.html` | `/stations/<ausmt_id>` | no, `robots noindex` |

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

Three card families, all 1200 by 630 PNGs on one ground, all declared as `og:image` on the page they
belong to. The ground is the root card artwork's own, so the three families a link preview can land
on read at one brightness rather than as two slightly different dark blues.

| Card | Written to | Served at | Drawn by |
|---|---|---|---|
| survey | `pages/og/<slug>.png` | `/data/pages/og/<slug>.png` | `_og_card` |
| collection | `pages/og/collections/<id>.png` | `/data/pages/og/collections/<id>.png` | `_og_collection_card` |
| root | not generated per build | `/vendor/social-card.png` | `portal/tools/gen_social_card.py`, hand-run |

The collection cards take a subdirectory of their own: `pages/og/` is flat, and a collection id equal
to a survey slug would otherwise overwrite that survey's card, silently and only for the pair that
collided.

The cards live in the data volume, which is served under `/data/*`. The `pages/` tree has no bare
route of its own, so `{base}/data/pages/og/...` is the only URL at which a card is reachable; a
`{base}/pages/...` form advertises a 404 to every preview fetcher there is.

A page is handed its card URL only after the file is on disk. The survey pages used to derive the URL
from "is Pillow importable", which is a claim about the environment rather than about the file, so a
failed write shipped an `og:image` that resolved to nothing. A card that was drawn but not written
now fails the build; a page with no card falls back to the root card.

### What each card shows

The survey card carries the survey's title, its station count and type, its region and years, its
period band and extent, a footprint panel of its stations and an Australia locator inset. The inset
is composited at 70 per cent over the footprint it explains, so the stations it covers still show
through it; only its centre marker, the one mark that says WHERE, is drawn at full strength.

The collection card is a preview of the collection page's own map: every member station, coloured by
member survey in the collections hub's palette and member order, so one survey is the same colour on
the hub, on the collection page and on the card. It carries no locator inset, because a grouping of
surveys spanning a continent has no single place to point at. Two things differ from the hub's SVG on
purpose: the dot radius follows the survey card's raster rule, because a preview is resampled to
about a third of its width by the clients that show it and the SVG's radius would vanish there; and
the dots are drawn opaque, because this card has neither a legend nor a hover, so translucency buys
nothing and costs contrast. A collection whose members disclose no position at all gets no card,
rather than a bare coastline that would read as a collection with no coverage.

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

### The AusMT mark in the corner

The survey and collection cards carry the AusMT mark in the top-left corner, on the same text margin
the title sits on. The root card does not: its artwork IS the mark, at full size.

The engine draws the corner mark from a small pinned derivative,
`portal/vendor/brand/ausmt-mark-168.png`, emitted by `gen_brand.py` from the same lattice as every
other brand export and gated by `gen_brand.py --check`. It exists because the engine image ships no
portal tree and so must carry its own copy of whatever it draws with; the 1024 px mark would put a
third of a megabyte in that image to be shown at a fraction of the size. 168 is a whole multiple of
the height the card draws at, so the resample is a clean box rather than an arbitrary ratio.

### The signature row

Every card is signed the same way: the AuScope mark, then a gap of half the mark's width, then the
address `ausmt.auscope.org.au`, all on the card's own text margin. The mark's height is the address's
line height and it is centred on the address's ink, so the pair reads as one line of type rather than
as a logo with a caption beside it.

The address is set in Inter Bold on all three families. The root card's artwork is set in that face,
so the generated cards adopting it is what makes the three signature rows one row rather than three
that happen to say the same thing; the rest of a generated card's type stays in Pillow's bundled
face, which ships with the library and so cannot go missing.

The engine ships its own copy of everything it draws with, beside the emitter and pinned
byte-identical to the portal's copy in tests: `engine/extract/_auscope_mark.png` against
`portal/vendor/auscope-icon-white.png`, `engine/extract/_ausmt_mark.png` against
`portal/vendor/brand/ausmt-mark-168.png`, and `engine/extract/_inter_bold.ttf` against
`portal/tools/brand_font/Inter-Bold.ttf`, whose Open Font Licence ships beside it. The engine image
carries no portal tree, so an emitter that reached across to the portal would draw an unsigned card
in exactly the environment that serves the corpus. These four files are listed under
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
