# Scientific Philosophy

AusMT exists because of practical problems in reusing MT datasets, and most of those problems
are not technical. Data, metadata, processing history and scientific context are usually
preserved separately, when they are preserved at all. The decisions below follow from trying
to keep them together.

The survey, not the file, is the unit AusMT publishes and cites; the reasoning is on the
[home page](../index.md#why-the-survey-not-the-file).

## Transfer functions, not time series

This is a practical decision. Time-series archives are large and need infrastructure built for
them, which national facilities such as NCI and institutional repositories already provide.
Transfer functions are what the MT community exchanges, interprets, publishes and reuses, and
for many older surveys they are the only surviving products. Concentrating on them lets AusMT
cover a wide span of historical and current datasets without duplicating archival
infrastructure it would then have to maintain.

## Metadata is data

The line between data and metadata is largely artificial. Where the station was, when it was
recorded, which instruments were used, whether remote reference was applied, which software
processed it and at what version: without those, a transfer function may be impossible to
interpret. Metadata is a first-class product here, and so is
[provenance](../data-model/provenance.md).

## Reproducibility where possible

Reproducibility is a goal with real limits. Historical datasets were processed with software
that no longer runs, on systems that no longer exist, through workflows nobody wrote down.
AusMT does not require perfect reproducibility. It requires enough recorded information that a
future researcher can understand the products and regenerate them where that is still
possible.

## Interoperability over reinvention

The MT community already maintains EDI, EMTF XML, MTH5 and mt_metadata. Creating a format is
easy; maintaining one for decades is not. Where an established standard solves a problem
adequately, AusMT adopts it rather than inventing an alternative. See
[Standards and alignment](standards.md).

## Curation over open upload

An archive accumulates value when its contents can be trusted, so AusMT is curated rather than
an unrestricted upload service. Submissions pass validation and human review before
publication, which is how metadata completeness, discoverability, provenance, licensing and
collection consistency are actually kept. The purpose is not to restrict access; it is to make
what is published usable later.

## CARE

AusMT supports both FAIR and CARE. FAIR concerns making data findable and reusable; CARE
concerns the rights, interests and governance expectations of Indigenous Peoples and
communities, and the project addresses both through its metadata, provenance and publication
workflows.

> **Implementation status (current).** CARE support today means `survey.yaml`'s `care.*` fields
> are recorded and surfaced to reviewers. There is no automated enforcement. A curator reads
> and acts on them during review; nothing in the pipeline blocks publication based on their
> content. Machine-checked CARE gating is an aspiration, not a shipped mechanism.
