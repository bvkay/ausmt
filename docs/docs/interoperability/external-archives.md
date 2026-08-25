# External Archives

AusMT publishes transfer functions, survey metadata, provenance and derived products. Everything else
that belongs to a survey stays where it already is, and the survey package records a pointer to it.

## What stays outside

**Time series.** Native instrument files, calibrated series, continuous recordings, intermediate
processing products, observational MTH5 datasets. They are large, often governed by different access
conditions, and belong in repositories built for them (NCI, universities, agencies, project archives).
This is the boundary the whole design turns on; it is stated once here and referenced elsewhere.

**Publications and reports.** No PDFs, theses, posters or presentations; the package records references
to them.

**Site photographs and field material.** Lightweight structured notes that improve interpretation or
provenance (deployment notes, site conditions, known acquisition issues) can sit in the package as small
text or metadata fields; image and PDF collections live elsewhere.

## How the links are recorded

```yaml
time_series:                 # pointers ONLY - AusMT never hosts time series
  pid: 10.25914/example      # persistent identifier of the time-series collection

publications:
  - author: Example, A.
    year: 2024
    title: An example interpretation paper
    journal: Exploration Geophysics
    doi: 10.xxxx/example
```

Prefer a persistent identifier (DOI, Handle, ARK, RAiD, an institutional or NCI collection identifier)
over a URL; an ordinary link does not survive a site reorganisation. A dataset identifier also states
which data level it points at, so a reader can tell a parent collection from the raw packed time series
inside it; see [Identifiers by data level](../reference/survey-yaml.md#6-identifiers-by-data-level).
Each reference should carry enough for a user to understand the relationship: resource type, title,
identifier, holding repository, access conditions.

## Finding what is available now

Recording a pointer says the data exists somewhere. It does not say whether a given station's files can
be fetched today. The portal answers that in two places, because the two halves of the answer are
different questions:

* **The Data available filter** (Browse pane) decides what the map shows. Its options are the licence
  question (*Transfer functions downloadable here*: whether AusMT is allowed to serve that station's
  processed files itself) and the route question per time-series level (whether the archive holds a
  verified file for that station at that level and serves it openly). Selecting a level keeps the
  stations whose files are ready to fetch.
* **The Download block** (Select & download pane) prices what the current scope can take. Every row
  reflects the selection when one exists, else the filtered corpus, and the scope line above the rows
  says which. Level 2 rows (EDI, EMTF XML, MTH5 zips) are served by AusMT; the time-series rows
  (packed raw, Level 0, Level 1 MTH5, Level 1 NetCDF) are hand-offs, each stating how many stations in
  scope it covers and what they total.

The list behind the time-series rows is built from the survey packages' verified-resource registers,
so a station whose access is embargoed, whose position is withheld, or whose match is still awaiting
curator adjudication is simply not in it: there is no setting that reveals one. A deployment whose
registers verify nothing publishes no list at all, and the panel says exactly that rather than
reporting an error.

## The hand-off

Each time-series row's action is scoped to that row's level. For a small scope (up to ten files) it
hands each file straight to your browser: every download is an AusMT route answering with a redirect
to the archive holding the file, so the browser fetches from the archive directly and its own
downloads list carries the progress. Beyond that, the action writes a pointer file instead - one
entry per station, route plus the archive's own address for reference - because feeding dozens of
multi-gigabyte downloads to a browser at once helps nobody; `wget` follows the redirects on its own
(`curl` needs `-L`). The **Pointers (JSON)** export in the Metadata block is the full-provenance
form: every station in scope appears (with its dataset DOI or the reason none is recorded), routable
stations carry their per-level rows, and the document records its own scope. A station's own drawer
offers the same route per level directly.

**Progress belongs to your browser, not to this page.** The redirect hands the bytes from your browser
to the archive, so the portal never sees the transfer and shows no progress bar and no completion
message: your browser's own downloads list is where the transfer appears, and it is the only place that
can report it. Nothing is copied through AusMT, and nothing is repackaged.

## What "verified" means, and what it does not

Every published row carries the same fieldnote: **verified against NCI THREDDS on `<date>`**. That
date is when an out-of-band crawl read the file in the archive's catalogue and recorded its path, its
stated size and its last-modified stamp. It is not "verified at build time": a build
makes no network call, so a build cannot have checked anything, and a
timestamp that moved on every rebuild would say less rather than more.

So the note is a statement about a past reading. It does
not promise the file is reachable this second. If a route fails, that is an outage, and an outage
changes nothing here on its own: a claim about what exists must not follow a server's health, or every
maintenance window would look like a withdrawal.

Withdrawing a row is therefore a curation act, not an automatic one. It takes the same URL failing on
two separate out-of-band runs at least a fortnight apart AND a curator recording the retirement with
its date and reason. The row then stops appearing anywhere a reader can see while staying on file as
evidence of what was once held. Where it was a station's last verified row, the station's
availability goes with it, which is the only way that ever happens.

## Access conditions

An external resource may have different access conditions from the AusMT package: open, embargoed,
restricted, mediated or unavailable. Do not imply that referenced material is openly available unless
that has been confirmed. Record the conditions and any governance requirements in the metadata, which a
curator reviews at [review](../operations/review.md) time. These links are part of the
[provenance record](../data-model/provenance.md): they preserve the connection between the observations
and the published products even where AusMT does not hold the observations.
