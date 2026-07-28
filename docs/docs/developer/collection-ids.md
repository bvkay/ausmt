# Collection IDs

A *collection* groups related surveys (a programme, a release, an institutional holding). Membership
is declared per survey in `survey.yaml`:

```yaml
collection:
  id: auslamp                 # the collection id (see policy below)
  title: AusLAMP
  type: programme             # programme | release | institutional | other
  status: completed           # active | completed | archived
  start_year: 2013            # programme start, rolled up to the collection page
  last_updated: "2026-01-01"  # date of the most recent member release
  description: >-             # one paragraph shown on the collection card and page
    What the programme is, who runs it, and what the coverage looks like.
```

`id` does the grouping. `start_year`, `last_updated` and `description` are optional presentation
fields for the collection card and page. The roll-up takes each programme-level field from the
first member that declares it, so keeping the whole block identical across members is what stops
one survey's stale wording becoming the collection's.

The build rolls members up into `collections.json` and the MTCAT `collections` section
(`build_portal._group_collections`).

## ID policy

- **Lowercase, hyphenated**, ASCII: `^[a-z0-9]+(-[a-z0-9]+)*$` (e.g. `auslamp`, `wamt`,
  `sa-heat-flow`). The validator (`_validation/validate_survey.py`) emits a WARNING for anything else.
- **Stable** — never change an id once published; it is the federation/grouping key.
- **Shared verbatim** across all member surveys — the same `id` *and* `title` on every member, so the
  roll-up groups them correctly.
- A survey with no collection simply omits the `collection` block (`collections.json` is then empty).

## Known collection IDs

Keep this list current as programmes are added (it is the de-facto registry).

| id | title | type |
|---|---|---|
| `auslamp` | AusLAMP | programme |

(Add new rows here when a curator confirms a new programme id.)
