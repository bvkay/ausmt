# Collection IDs

A collection groups related surveys (a programme, a release, an institutional holding, a
compilation). Membership is declared per survey in `survey.yaml`:

```yaml
collection:
  id: auslamp                 # the collection id (see policy below)
  title: AusLAMP
  type: programme             # programme | release | institutional | compilation | other
  status: completed           # active | completed | archived
  start_year: 2013            # programme start, rolled up to the collection page
  last_updated: "2026-01-01"  # date of the most recent member release
  description: >-             # ONE paragraph shown on the collection card and page
    What the programme is, who runs it, and what the coverage looks like.
  prose:                      # optional long-form page copy, one array per page section
    about:
      - "The first paragraph of the About section."
      - "# A subheading"
      - "The first paragraph under it."
```

`id` does the grouping. `start_year`, `last_updated`, `description` and `prose` are optional
presentation fields. The roll-up takes each programme-level field from the first member that declares
it, so keeping the whole block identical across members is what stops one survey's stale wording
becoming the collection's. The build rolls members up into `collections.json` and the MTCAT
`collections` section (`build_portal._group_collections`).

`description` stays one flat paragraph: it is the discovery text every single-line surface summarises.
Long-form page copy goes in `prose`, whose sections and `# ` subheading convention are documented in
[survey.yaml section 12.1](../reference/survey-yaml.md). `prose` is not editable in the curator
console; reconcile it by editing the member `survey.yaml` files. Omit a prose key you have nothing to
say in rather than writing an empty one, because an empty value still counts as declared and blocks
later members.

## Type vocabulary

`type` says what kind of grouping a collection is. It is not validator-enforced; this list is the
vocabulary, and the hub chip renders whatever value the corpus carries.

- `programme`: a funded field programme.
- `release`: a data release.
- `institutional`: an institutional holding.
- `compilation`: a grouping AusMT assembled from independent surveys.
- `other`: anything the four above do not describe.

## ID policy

- Lowercase, hyphenated ASCII: `^[a-z0-9]+(-[a-z0-9]+)*$` (`auslamp`, `wamt`, `sa-heat-flow`). The
  validator (`_validation/validate_survey.py`) emits a WARNING for anything else.
- Stable: never change an id once published; it is the grouping key.
- Shared verbatim across all member surveys, the same `id` and `title` on every member.
- A survey with no collection omits the `collection` block; `collections.json` is then empty.

## Known collection IDs

The de-facto registry; add a row when a curator confirms a new collection id.

| id | title | type |
|---|---|---|
| `auslamp` | AusLAMP | programme |
| `australia-legacy-gds` | Australia legacy GDS | compilation |
