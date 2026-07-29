# Using the data

AusMT was not built to replace repositories, archives or community standards. Australian MT
data already exists in universities, agencies, geological surveys, research infrastructure
facilities and industry, held in institutional repositories, national archives, project
websites and local systems. The problem is rarely that the data are missing. It is that they
are hard to find, understand and reuse.

So the operating principle is:

> Repositories remain independent. Discovery becomes shared.

An organisation keeps its own infrastructure, governance and practices, and still participates
in a shared discovery layer. What gets exchanged is descriptions of datasets, not the datasets
themselves. That is what makes participation cheap enough to be worth it, and it is why AusMT
adopts existing formats and identifier systems instead of defining its own; see
[Standards and alignment](../introduction/standards.md).

## The three practical pages

**[How AusMT serves data](api-overview.md)** is the serving model. Read-only static JSON behind
an ordinary file server, what that means for caching, CORS and integrity, how access levels and
embargoes appear to a consumer, and what deliberately does not exist.

**[Data reference](api-reference.md)** lists every served document, its shape, and worked fetch
patterns: whole-survey bundles, per-station downloads through the manifest, and bounding-box
selection.

**[Tool integration](tool-integration.md)** covers reading the three distributed formats in MT
software, harvesting MTCAT, and the gotchas that will otherwise cost you an afternoon.

Alongside them, **[External archives](external-archives.md)** covers what AusMT deliberately
does not hold and how it records links to the repositories that do.

## Where the layers sit

Transfer-function formats say what is *in* a dataset. MTCAT says what datasets *exist*. The two
are different jobs, and keeping them separate is what lets a repository publish discovery
records without publishing its data.

```text
EDI / EMTF XML / MTH5   ->   what is in the dataset?
MTCAT                   ->   what datasets exist?
```

A repository can take part regardless of which transfer-function formats its holdings use. The
goal is interoperable products, not uniform implementations. The discovery document AusMT emits
is specified in the [MTCAT schema reference](../reference/mtcat-schema.md).

## The wider context

AusMT is one part of an international ecosystem that includes EarthScope, EPOS, mt_metadata,
MTH5, international MT archives and national geophysical repositories. The point is not an
isolated Australian platform. It is that a dataset which can only be read inside one repository
or one piece of software is harder to preserve, and a researcher should be able to find a
dataset, understand its context and use its products without knowing where it came from or how
the repository holding it is built.
