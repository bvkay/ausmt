# Standards and Alignment

AusMT does not invent new formats or identifier systems. It is built to align with established
research-data and magnetotelluric-domain standards so that its records interoperate with the
identifier infrastructure, repositories and software the community already uses.

This page is the authoritative statement of that alignment; the portal's About page carries the
same material in summary form.

## Persistent identifiers

AusMT records and carries through the persistent identifiers that make research objects findable
and citable:

- **DOI** — dataset and publication identifiers.
- **ORCID** — researcher identifiers.
- **ROR** — organisation identifiers.
- **RAiD** — project (research activity) identifiers.

Where a survey supplies these, they travel with the record into discovery so that custodians,
investigators and funders are credited.

## FAIR and CARE

- **FAIR** — Findable, Accessible, Interoperable, Reusable. AusMT's discovery, metadata and
  provenance model is designed against these principles.
- **CARE** — the Indigenous data governance principles (Collective benefit, Authority to control,
  Responsibility, Ethics).

On CARE specifically: a survey's CARE fields are **recorded and reviewed by a curator during
publication** — there is **no automated enforcement**, and nothing in the pipeline blocks
publication based on their content. Machine-checked CARE gating is an aspiration, not a shipped
mechanism (see also [Scientific Philosophy → CARE](scientific-philosophy.md)).

## MT-domain standards

AusMT adopts the community's existing MT formats and metadata models rather than project-specific
alternatives:

- **mt_metadata** — the community MT metadata model.
- **MTH5** — the community MT data container.

These are described further under [What is AusMT? → Relationship to Existing Standards](what-is-ausmt.md)
and in the [Data Model](../data-model/metadata-model.md).

## Interoperability between portals

For interoperability between portals, AusMT emits an **MTCAT** discovery document — the **MTCAT
v1.0** specification. MTCAT is AusMT's machine-readable catalogue format: one JSON file describing
every survey, so that another repository can discover AusMT's holdings without exchanging the
scientific data itself. See [Data Model → MTCAT](../data-model/mtcat.md) and the
[MTCAT Schema reference](../reference/mtcat-schema.md).
