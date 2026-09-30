# C18 — Incremental build: content-addressed station-product cache

**Status: FROZEN 2026-07-06 (chief-architect design, adjudicating the measured design-scout
proposal of the same date). Implementation must not deviate without an amendment recorded here.**

## §0 Problem, measured (scout findings, verified per-phase on the real 1,105-station corpus)

A full build costs ≈ 8 min and a metadata-only survey.yaml edit pays all of it. The cost is NOT
the surveys validator (0.5 s/corpus); it is inside the engine: mt_metadata primary parse
~67 ms/EDI × 1,105, and — dominant at ~84% — the `normalize()` served-XML round-trip
~457 ms/EDI × 869 served stations (`_emit_served_xml` → `ausmt_science/ingest/normalize.py`,
which re-parses the source EDI redundantly and re-reads its own outputs as QC). At
national scale this becomes ~30 min per one-line edit.

Remedy: a content-addressed cache of per-station products, so unchanged stations skip the parse
and the round-trip. **The post-build gate does not move: `scripts/verify.py` stays full,
byte-re-hashing, and cache-blind — the cache may only ever change build speed, never what the
gate checks.** Any diff to `verify.py` in this contract is a STOP condition.

## §1 Flags and defaults

- `--incremental` (engine `build_portal.py`, default **OFF**): consult + populate the cache.
- `--cache-dir PATH`: cache root. Unset ⇒ `--incremental` is a no-op (safe default).
- `--cache-mode {rw,ro,refresh}`: normal / read-only (CI reproducibility) / ignore-hits-and-rewrite
  (forced full rebuild, the escape hatch).
- Switched ON in exactly one place: the production `deploy/Makefile` `rebuild-data` build-runner
  invocation (`--incremental --cache-dir /out/cache --cache-mode rw`). Engine default stays off;
  the gateway runner stays non-incremental (untrusted-upload path; it skips `--bundle-edi` and
  never pays normalize anyway); CI stays full (§5).
- **Validation is never skipped.** The in-build validator (0.5 s) runs on every build, incremental
  or not, alongside surveys CI — deliberate defence in depth; document it as such.

## §2 Cache key (the whole ballgame)

Key = sha256 over the concatenation of:

1. `edi_sha256` — sha256 of the **source EDI bytes**. Never mtime (git rewrites mtimes on every
   sync; content sha is the only key that can neither spuriously miss nor hide an edit).
2. `engine_code_sha`: **coarse salt = the engine SOURCE digest** (`cache.engine_source_digest`:
   sha256 over path + content of every file under `engine/extract`, `engine/ausmt_science`,
   `engine/schema` and the sibling `contract/columns.json`; bytecode, caches and tests excluded).
   Any edit to product-producing code busts the whole cache; a commit that changes only deploy
   scripts, docs or tests keys identically, so a new image built from it stays warm. The v1 salt
   was `BUILD_ID["engine_commit"]`, which colded the cache on every image regardless of what the
   commit touched. **Integrity rule (unchanged, an identity gate rather than a key input): if the
   engine commit is unknown/None, OR the checkout is dirty (`git status --porcelain` non-empty
   where a checkout exists), OR no digestable engine tree exists, incremental is silently DISABLED
   for that build (treated as full, no cache reads or writes).** A degenerate or ambiguous salt
   must never key a cache.
3. `mt_metadata_version` (+ mth5 version when consulted) — a library upgrade invalidates every
   cached XML and round-trip verdict.
4. `schema_version` of the positional/product contract (mtcat/manifest schema + a hash of
   `contract/columns.json` — a column append changes cached row shapes).
5. `survey_meta_digest` — **v1 = sha256 of the entire `survey.yaml`** (provably over-invalidating:
   any yaml edit re-derives that one survey, never the corpus). Narrowing to the
   `condition_tf`-consumed field subset is a LATER contract, gated on a test proving the subset
   exhaustive.

Cached value per station: the verified XML output, derived EDI, round-trip verdict + conditioning
notes, and the parsed record/tf/sci rows — i.e. what `process_edis` + `_emit_served_xml` produce.
Entries are content-addressed files (`cache/<k[:2]>/<k>.*`), written temp-then-atomic-rename;
concurrent/interrupted builds cannot corrupt an entry.

## §3 Storage + lifecycle

`${AUSMT_DATA_DIR}/site-data/cache/` — sibling of `builds/`, owned by uid 10001. Survives the
`builds/` prune (`tail -n +6`) and the `mv -T current` swap; container-writable; rides the
existing restic coverage; safe to lose entirely (one slow rebuild). It must NOT live under
`builds/<ts>/` (pruned), `surveys-live/` (read-only mount, operator-owned), or the surveys repo.

Prune policy, run at the end of a successful build: drop entries not touched for 20 builds or
90 days, and enforce a size cap `AUSMT_CACHE_MAX_MB` (env, default 2048) oldest-first. Numbers
are operator-tunable; defaults live in one place.

## §4 Tests (the gate must be able to fail)

1. **Stale-cache refusal (the contract test):** build with `--incremental` (cache populated);
   mutate one impedance value in a source EDI; rebuild incremental; assert the served XML reflects
   the NEW value. This test fails if a byte-changed EDI is ever served from cache.
2. **Poisoned-cache is caught downstream:** hand-corrupt a cached XML entry so its bytes no longer
   match what the build manifest will claim; run the build + `verify.py --data-dir`; assert
   VERIFY: FAIL and (in the Makefile flow) no swap. Proves the authoritative gate is cache-blind.
3. **Salt invalidation:** simulated engine-source change ⇒ zero hits; engine-commit change over
   unchanged sources ⇒ all hits; mt_metadata version change ⇒ zero hits; survey.yaml edit ⇒ that
   survey re-derives, other surveys still hit.
4. **Degenerate-salt refusal:** engine commit unknown ⇒ cache neither read nor written (assert via
   hit/write counters), build completes full.
5. **Equivalence (CI guard):** warm `--incremental` build vs `--cache-mode refresh` build ⇒
   byte-identical `manifest.json`, `mtcat.json`, `catalogue.json`, and every served XML.
6. **Determinism instead of wall-clock:** the build emits hit/miss/write counters (log + build
   report); a no-change incremental rebuild asserts hits == expected served-station count and
   misses == 0. (No wall-clock assertions in CI — a >10× local timing check is a manual/dev-only
   script note, not a test.)
7. **Lifecycle survival:** simulate prune + atomic swap; cache still present and still hits.

## §5 What stays full forever

- surveys `validate.yml` (validator + ClamAV) — unchanged.
- Engine CI product builds: at least one `--cache-mode refresh` full build + the §4.5 equivalence
  test; CI-published products are never cache-derived.
- `verify.py --data-dir` in `rebuild-data` — full, byte-independent, cache-blind, unchanged.

## §6 Scope guards

- No change to `verify.py`, the gateway runner, `contract/columns.json`, or any portal file.
- Non-goals: speeding the cold build, parallelizing normalize, de-duplicating the two validator
  runs, incremental verify. The `normalize()` internal redundancy (~67 of its 457 ms is a
  re-parse of a TF already parsed upstream) is flagged as a possible later contract, not this one.
- New non-test code ≈ one `engine/extract/cache.py` module + two seam integrations + flags +
  Makefile/README notes; target ≤ ~400 net non-test lines.

## Amendment A1 (2026-07-06) — adjudicated post-adversarial-review corrections

**Recorded per the freeze rule above. Review verdict: RELEASE-WITH-FIXES; every item below was
adjudicated by the maintainer before implementation. Each behaviour change landed
proven-failing-first (the failing evidence is in the fix commits).**

(a) **§1 — raw-mode exclusion (was a CONFIRMED HIGH).** In `--raw` builds survey metadata comes
    from `--seed-meta` JSON, which NO key component covers (`survey_meta_digest` is empty when
    there is no survey.yaml): a warm raw rebuild served the PREVIOUS seed's DOI/authors/title in
    the served XML while the same build's surveys.json showed the new values. Adjudicated fix (do
    NOT key the seed-meta): `--raw` builds are EXCLUDED from caching entirely — the cache is inert
    exactly like a degenerate salt (no reads, no writes, one log line). Raw is the rare
    seed-regeneration path, not the hot path; conservative doctrine over-invalidates.

(b) **§4.2 REWRITTEN — the integrity split (was a CONFIRMED HIGH; the original §4.2 rationale was
    wrong).** A poisoned CACHE entry flows into the manifest and verifies self-consistently: the
    manifest sha is computed FROM the served bytes, so `verify.py` cannot see a poison that flowed
    through the build (reviewers proved it: poison marker in served XML, verify rc=0). Corrected
    doctrine: content-addressed KEYS derive from inputs; VALUE integrity is the CACHE'S OWN JOB —
    every entry embeds a sha256 of its payload (`<64-hex digest>\n<payload>`, in the same
    atomically-renamed file), verified on every read. A mismatch deletes the entry, counts in a
    `corrupt` counter, tallies as a MISS, and the build recomputes (fail-safe to recompute, never
    to serve). The same discipline fixes the torn-pair phantom hit (an xml-blob hit whose meta
    sibling misses now revokes the phantom hit and recomputes both blobs). `verify.py` guards
    POST-BUILD tampering of the served tree only — that is all it ever guarded. Entry-format
    version tag bumped to `ausmt-c18-cache-v2` (v1-format entries are orphaned and age out via
    the prune).

(c) **§4.5, the equivalence contract, stated precisely. SUPERSEDED BY AMENDMENT A5: its premise
    was a defect, not a property, and independent full builds ARE byte-identical.**
    mt_metadata's EMTF-XML writer stamps a
    wall-clock `<CreateTime>` in every written XML, so two INDEPENDENT full builds are NOT
    byte-identical (the XML sha difference cascades into manifest.json). The equivalence guarantee
    — and the CI test — is: a warm all-hits build is byte-identical to THE BUILD THAT POPULATED
    ITS CACHE (manifest.json, catalogue.json, tf.json, sci.json + every served XML; mtcat.json
    modulo its `generated_at`). Corollary: a legitimately RECOMPUTED entry (corrupt/torn)
    re-stamps `<CreateTime>`; equivalence for those stations is byte-identity modulo that one line.

(d) **§3 — prune policy v1 accepted as shipped.** The implemented policy is 90-day mtime-age +
    `AUSMT_CACHE_MAX_MB` size cap, oldest-first. The "not touched for 20 builds" window is NOT
    implemented (the cache keeps no per-build ledger); the dead constant was removed.

(e) **§2.2 production-salt note corrected.** The parenthetical "the live box currently emits null
    commits in build.json — until that is healthy, the cache simply never fires there" is WRONG as
    a production claim: `docker/engine.Dockerfile` bakes `ARG GIT_SHA` → `ENV AUSMT_ENGINE_COMMIT`
    and `deploy-images.yml` passes `github.sha`, so a CURRENT image always resolves its engine
    commit and the cache fires in production. The observed nulls came from a stale
    pre-`GIT_SHA`-bake image; pulling a current image heals them. The degenerate-salt gate itself
    is unchanged and correct.

## Amendment A2 (2026-07-06) — key namespace binds the post-disambiguation station id

Recorded retroactively (chief-architect adjudication; the change predated the adversarial review,
which probed exactly this coupling and produced no finding). The served-XML cache entries are keyed
with a `kind` namespace of `"xml:<final-station-id>"`, where the final id is the
post-`_disambiguate` identity — a SIXTH key component beyond §2's five. Rationale: station-id
disambiguation depends on the whole build set, so a station's final id (and therefore its served
XML content and filename) can change when a *different* station enters or leaves the corpus; the
survey.yaml digest cannot capture that. Binding the final id into the key makes such a change a
guaranteed MISS. The parse-row entries use `kind="parse"` (pre-disambiguation content, unaffected).

## Amendment A3 (2026-07-07) — cache-staleness defence: digest stamps + a cache-INDEPENDENT product-consistency gate (C18b)

**Recorded per the freeze rule (§ header) as the chief-architect-authorised amendment path.** This
amendment is triggered by a CONFIRMED production incident and is the sole sanctioned reason `verify.py`
— declared FROZEN by this design ("full + cache-blind; STOP if touched") — is extended.

### The incident (2026-07-07)

Build `20260707T002709Z` on the deployment box warm-served a STALE Olympic Dam canonical XML (its
citation org from BEFORE a `survey.yaml` edit) beside a FRESH `surveys.json` (post-edit), with the C18
counters reporting `hits=3017 misses=0` across a `survey.yaml` change that should have busted 58
stations' keys. The IDENTICAL-input build ~10 minutes later busted correctly; three exact local
replications (flat / nested / box-exact layouts) all bust correctly. The defect is INTERMITTENT and
UNEXPLAINED — the cache keys that would have explained it were deleted in incident containment. The
existing C18 test battery is blind to it: every §4 test exercises the key derivation and the counters,
none compares a SERVED product against the LIVE source that should have keyed it. A build can therefore
serve a product keyed under a stale digest while every counter and every self-consistent manifest sha
reports green — exactly the incident's shape.

### What C18b adds (design, frozen here)

1. **Digest stamps (build_portal).** Every served survey emits a sidecar
   `out/products/survey_digests.json` mapping `slug -> {yaml_digest_current, xml_digest_stamped}`:
   - `yaml_digest_current` = sha256 of the `survey.yaml` bytes READ AT EMISSION TIME from the package
     dir (`pkgdir`), i.e. the live source digest at the moment the products were written. For `--raw`
     surveys (no `survey.yaml`) it is the empty-digest marker, exactly as the cache key uses.
   - `xml_digest_stamped` = `{station_id: <the survey_digest the served XML was KEYED/PRODUCED under>}`.
     On the FRESH path this is the digest `_emit_served_xml` was called with (stamped directly). On the
     CACHE-HIT path it is the digest carried in the entry's own meta blob — so a hit propagates the
     digest the entry was written under, and a stale entry surfaces its stale digest here.
   - Mechanics: the served-XML cache meta blob (previously `{"conditioned": [...]}`) gains a
     `survey_digest` field. The entry-format version tag is bumped `ausmt-c18-cache-v2 ->
     ausmt-c18-cache-v3` so pre-bump entries (which carry no `survey_digest` in their meta) MISS
     cleanly rather than being read with a missing field — a clean miss, counted as a miss, never a
     misread. (The bump rides the existing `_fixed_salt` version tag, so it also re-keys the parse and
     xml blobs; that is acceptable — a one-time full re-derive on first build after this lands.)

2. **Consistency gate (verify.py) — cache-INDEPENDENT.** `verify.py` gains a `--surveys` argument
   (default-OFF). It NEVER reads the cache dir; it compares the served-product sidecar against the LIVE
   `survey.yaml` SOURCES:
   - **When `--surveys` is ABSENT** (all existing call sites, incl. `--data-dir` mode invoked without
     it): the gate SKIPS with a LOUD note and changes nothing — every existing `verify.py` behaviour
     and test is preserved.
   - **When `--surveys` is PRESENT** (and the Makefile's `rebuild-data` verify step now passes it): for
     each served slug the gate recomputes sha256 of the LIVE `survey.yaml` under the surveys root and
     FAILS (nonzero, `VERIFY: FAIL`) if any station's `xml_digest_stamped != recomputed live digest`,
     OR if the sidecar's own `yaml_digest_current != recomputed` (internal self-consistency). The
     failure message names the slug, the affected station count, both digests, and instructs:
     "stale cache product — do NOT clear the cache before snapshotting it (tar) for forensics".

   **Why this STRENGTHENS rather than weakens cache-blindness (the freeze-rule reconciliation).** The
   frozen contract forbids `verify.py` reading the cache. This gate does NOT read the cache — it reads
   the served PRODUCTS (the sidecar it emitted) and the SOURCE `survey.yaml` files, and asserts they
   agree. The C18 manifest-sha check cannot catch a cache-flowed staleness because the manifest sha is
   computed FROM the served bytes (Amendment A1b established this): a stale product verifies
   self-consistently. Comparing products against SOURCES is the independent observable A1b's analysis
   showed was missing. `verify.py` remains cache-blind in the sense the freeze meant (it never trusts
   or reads cache state); it gains an orthogonal source-vs-product check.

3. **Per-survey instrumentation (build_portal stderr).** One line per served survey:
   `C18 survey <slug>: digest=<first12> hits=<h> misses=<m> writes=<w>`, from a per-survey counter tally
   keyed by the survey digest. The corpus-total `C18 cache [...]` line is UNCHANGED (tests pin it).

4. **Makefile.** `deploy/Makefile`'s `rebuild-data` verify step gains `--surveys /srv/surveys/surveys`
   (the same root the build used), so the gate is ARMED in production. This is the one allowed line in
   `deploy/`.

### Failure criterion

The gate FAILS iff a served survey's XML was produced under a digest that differs from its live
`survey.yaml` — i.e. the exact incident shape (served product keyed under a pre-edit digest while the
source is post-edit). The incident-replay test (`test_build_cache.py`) forces a stale stamp and proves
the gate goes RED with the named message; the absent-`--surveys` test proves the skip note and that all
existing verify behaviour is unchanged. The sidecar is a NEW products file: no golden/manifest
file-count pin lists directory contents (verified), so no golden re-minting is required.

## Amendment A4 (2026-07-10) — the incident ROOT CAUSE (single-read coherence) + salt/I-O forensics

**Recorded per the freeze rule as the chief-architect-authorised amendment path.** Closes the
2026-07-07 incident A3 documented as "INTERMITTENT and UNEXPLAINED", and the C18c test-flake
investigation (task #21). Root-caused by a four-lens investigation (code audit x2, live
reproduction, incident mechanics) with adversarial refutation of the surviving candidates.

### The incident mechanism (M1: a straddled build poisons the cache)

`survey.yaml` was read TWICE per build: metadata at `discover_work` (feeding `surveys.json` AND the
citation `normalize()` bakes into served XML), and the cache-key digest at that survey's per-survey
loop iteration — a window spanning every preceding survey's work, minutes on the full corpus. An
edit landing in that window (the gateway publish writes into the same surveys-live tree builds
read, unserialised even post-C40) produced a build whose served XML embedded PRE-edit metadata
KEYED under the POST-edit digest. The NEXT build then legitimately warm-hit every poisoned entry:
`hits=3017 misses=0`, stale Olympic Dam citation beside a fresh `surveys.json` — the incident
build itself did nothing wrong; the damage was done by its predecessor. The A3 gate was BLIND to
this shape: the poisoned entry's stamp EQUALS the live digest. (A3's replay tests force the
MISMATCHED-stamp shape — the other staleness class — which is why they pass while this poisoning
walked through.) Olympic Dam was the first survey through the then-new gateway publish path, the
day before the incident: consistent, though on-box attribution remains unverified (cache keys were
deleted in containment; see "residual" below).

### What A4 changes (all landed in the `fix/c18-cache-coherence` lane)

1. **Single-read coherence (the structural fix).** `discover_work` reads each survey.yaml's bytes
   ONCE and derives BOTH the parsed metadata and the sha256 digest from them; the digest rides the
   work tuple; the loop-time re-read is DELETED, as is `cache.survey_yaml_digest` itself (a
   reappearing read-the-yaml-again call site is the incident window reopening). Coherent by
   construction: no edit can split what a build's products embed from what they are keyed under.
2. **The A3 gate is thereby ARMED against straddles.** `yaml_digest_current` is now the
   discovery-time digest, so a straddled build fails verify.py's existing live-compare leg at the
   `rebuild-data` verify step — in the act, not silently. No verify.py change was needed.
3. **Salt stability (the C18c test flake).** The engine commit feeding the salt was re-resolved via
   a live `git rev-parse` inside every in-process build; concurrent git activity (2026-07-07 was
   the force-push/merge-queue day on the dev machine) or a transient rev-parse failure between a
   test's two builds flipped the key space — a nondeterministic counter failure, green on rerun.
   `_git_commit_at` now memoises SUCCESSFUL resolutions per process (failures are retried, never
   memoised); the `clean_salt` fixture pins the commit and clears `AUSMT_ENGINE_COMMIT` /
   `AUSMT_CACHE_MAX_MB`. The originally recorded "in-process global state" suspect is EXONERATED
   (two independent audits; 39/39 targeted reproduction runs).
4. **I/O attributability (the other flake candidate — Windows AV/indexer locks).** `put_bytes`
   retries the atomic rename (3 attempts, backoff) and counts exhausted failures in
   `write_errors`; `get_bytes` separates FileNotFoundError (true cold miss) from other OSErrors
   (`read_errors`, still tallied as misses — §4.6 arithmetic unchanged). `counters()` additionally
   exposes `salt_fp` (sha256 of the full fixed salt, first 12). The load-bearing counter asserts
   dump both builds' counters + the cache listing on failure — any recurrence names its class in
   one glance: degenerate/salt_fp drift -> salt; write_errors/read_errors -> environment; plain
   drift -> content.
5. **Belt-and-braces:** `main()` resets `_ediparse.read_norm`'s lru_cache beside `_SHA_CACHE` (the
   last cross-build content memo in a reused process; latent, no observed incident).

### New failure criteria (Invariant 10 — each test states how it fails)

* `test_straddled_build_cannot_poison_the_cache` — FAILS IF a mid-build survey.yaml edit lets a
  warm rebuild serve pre-edit citations from cache, or verify.py blesses the straddled build.
  Observable: the citation INSIDE served XML bytes vs the on-disk yaml. Proven failing at pre-fix
  HEAD on both legs.
* `test_salt_stable_across_in_process_builds` (+ injection companion) — FAILS IF two same-source
  in-process builds key differently (salt_fp) or degenerate; companion proves the observable fires
  under a moving commit.
* `test_git_commit_memoised_per_process_success_only` — FAILS IF the memo is gone (per-build
  rev-parse back) or a failure is memoised (permanent in-process degeneracy).
* Lock/read-error pins — FAIL IF a transient rename failure drops an entry, a persistent one goes
  uncounted, or unreadable-vs-absent entries become indistinguishable.

### Residual (recorded, deliberately NOT in this lane)

* **Publish-vs-build serialisation** (deploy): the gateway publish still mutates surveys-live
  while a build may be reading it. Single-read closes the poisoning path, and a straddled build now
  goes verify-RED and self-heals next tick, but an EDI-seam analogue (sha at key time vs
  normalize's own re-read) remains a theoretical window; the durable close is host-side
  serialisation (flock the publish/sync against `rebuild-data`) or snapshot-read builds — an
  operator/deploy design decision (Ben's call, queued in the decisions bundle).
* **On-box attribution of the 2026-07-07 incident** (optional forensics, Ben-only): hunt the
  straddler build P in `builds/` retention (pre-edit OD org in its `surveys.json`, ~116 OD misses
  in its log), gateway sqlite/audit + `git -C surveys-live reflog --date=iso` for the edit instant,
  `findmnt` on AUSMT_DATA_DIR (a non-local mount would reopen the fs-incoherence alternative).
  M1 stands as root cause structurally regardless; these would settle the historical attribution.

## Amendment A5 (2026-09-02): A1c's premise retired, independent full builds ARE the baseline

A1c stated the equivalence contract around a defect rather than around the design. Its premise was
that mt_metadata's EMTF-XML writer stamps a wall-clock `<CreateTime>` in every written XML, so two
INDEPENDENT full builds could not be byte-identical and the guarantee had to be narrowed to "a warm
all-hits build equals THE BUILD THAT POPULATED ITS CACHE".

That narrowing had a cost the amendment did not name: it made the cache the only thing standing
between the corpus and a churning published digest. With the cache cold or a station legitimately
recomputed, the served EMTF XML and the whole per-survey EMTF-XML zip published a new SHA-256 for
unchanged inputs, so the manifest digest a consumer was invited to check was a function of which
build happened to populate the cache. The cache MASKED the defect; it did not cause it, and it was
never the right place to fix it.

The stamp is now pinned at the write site (`ausmt_science/ingest/normalize.py::_pin_create_time`):
the served `<CreateTime>` carries the creation date the source document declares as mt_metadata reads
it, which for an EDI source is the `INFO` block's declared creation time where it has one and the
`FILEDATE` otherwise. A station whose EDI this build generates is pinned to that same value, so its
two served renditions agree; a copied custodian EDI keeps the `FILEDATE` its custodian wrote. No
served artifact except the MTH5 carries a build clock.

Consequences for this contract:

* **§4.5 / A1c superseded.** The equivalence guarantee is the plain one: three INDEPENDENT full
  builds of the same inputs produce byte-identical served artifacts and bundles, and a warm all-hits
  build is byte-identical to any of them. A recomputed entry (corrupt/torn) is byte-identical too,
  not "identical modulo one line".
* **The cache's own invariant is unchanged** and is now checkable without an exemption: the cache may
  only ever change build SPEED, never output bytes.
* **Tests.** `engine/tests/test_bundle_determinism.py` pins the independent-build baseline and the
  matching sensitivity leg (a changed impedance value must move the digest). The `<CreateTime>`
  normalisations in `test_build_cache.py` and `test_build_parallel.py` are removed, so the served XML
  and the xml-zip are byte-compared like everything else and a regression fails loudly.

## Amendment A6 (2026-09-30): both MTH5 tiers are cache entries, reused by hardlink

The build profile (`AusMT_2026/BUILD-PERF-PROFILE-2026-08-27.md`) measured a warm rebuild at 73.9
min, 99.1% of it `_write_tf_mth5`, and a cold build at ~68% `_write_tf_mth5` with the round-trip
gate `mth5_survey_roundtrip_ok` inside that share. The cache covered none of it: §2's cached value
was the parse rows and the served XML. This amendment admits the two MTH5 tiers.

### What is admitted

Two new entry kinds, both written by `_write_tf_mth5`:

* `station_h5`: the tier-1 station file `h5/<slug>/<station>.h5` (`emit_station_mth5`);
* `survey_h5`: the tier-2 survey bundle `bundles/<slug>-tf.h5` (`emit_survey_mth5`, and the
  pool build's deferred-bundle path in `_main_build`).

HIT: the stored file is placed in the build tree by hardlink, and neither the MTH5 write nor its
round-trip gate runs. MISS: the file is written and gated exactly as without a cache, and stored
only if the gate passed (a withheld write, `n == 0`, stores nothing and is written again next
build). Every cache read and write stays in the main process; the pool only ever sees misses. The
tier-3 collection file is not admitted (it is disabled by construction and not on the production
invocation).

### Equality: semantic, not byte

Two writes of the same inputs are not byte-identical. They differ in the root `file.access.time`
attribute and in the address bytes of HDF5 object references (the profile's "multi-TF bundle size
wiggle", adjudicated there to internal reference addresses with every value column identical). So
the claim for a cached MTH5 is:

* **claimed:** a cached file is SEMANTICALLY equal to a fresh write of the same inputs: every
  attribute and dataset equal, object references compared by the name they resolve to, the one
  write-clock attribute excluded. `test_semantic_comparator_sees_value_changes_but_not_the_write_clock`
  pins that the comparator is not blind in either direction.
* **claimed:** a warm build serves the bytes of the write that populated the entry, so an MTH5
  manifest SHA-256 holds across warm builds and moves whenever the file is written again
  (`test_warm_build_hardlinks_both_tiers_and_skips_write_and_gate` compares the warm and populating
  `manifest.json` byte for byte).
* **not claimed:** byte identity with an independent full build. A5's baseline ("three independent
  full builds produce byte-identical served artifacts") already excludes the MTH5, the one served
  artifact that carries a build clock; this amendment does not change that exclusion and the
  cache does not widen it. A5's cache invariant becomes, for these two kinds: the cache may only
  change build speed and which of several semantically equal writes is served.

Why a hit is trustworthy without re-running the gate: the stored file is the very file the miss
build gated against its own source EDIs, and the key binds every input that reaches it (below),
so a hit's inputs are the gated write's inputs. `test_warm_h5_files_pass_the_roundtrip_gate_against_this_builds_stations`
runs the gate over every warm file of two surveys against the warm build's own served EDIs.

### File-payload entry format

A file entry is two files under the key's shard, `<root>/<k[:2]>/`:

* `<k>.<kind>`: the RAW payload, so it can be hardlinked;
* `<k>.<kind>.ref`: a sidecar in the existing self-verifying format (`<sha256-hex>\n<payload>`)
  whose payload is JSON `{"sha256", "size", "meta"}`; `meta` is `{"n", "err", "rows"}`, the
  station count, the captured file-level stderr and the per-station failure rows the populating
  write produced, which a hit replays so the build log and the `build_report.json` ledger are the
  same on a hit as on the miss (`test_a_hit_replays_the_populating_writes_diagnostics`).

Write (`put_file`): link (copy on refusal) the gated file to a temporary name in the shard, hash
that inode, rename it over `<k>.<kind>`, and only then write the sidecar, so no sidecar ever names
a payload that is not in place. Read (`link_file`): verify the sidecar's own checksum and JSON,
link the payload to a temporary name BESIDE the destination, re-hash THAT inode against the
sidecar, and only then rename it into place: what was hashed is what is served. A malformed
sidecar, a missing payload or a digest mismatch deletes both files and counts `corrupt` and a
miss, and the seam recomputes (`test_corrupt_payload_is_deleted_counted_and_recomputed`,
`test_corrupt_sidecar_is_deleted_counted_and_recomputed`). A stored meta the seam cannot use is
rejected the same way (`reject_file`). The cache stays a passive store: `key_parts` binds the
fixed salt and the kind, and the seam owns which parts it passes.

### Key components

Every input that reaches the writer, per tier, and where each is bound. Common to both tiers:
the fixed salt (`ausmt-c47-cache-v7`, the engine source digest, `lib_versions` = mt_metadata and
mth5, the contract digest), then `"parts"` and the kind, so no kind shares a key with another.

**Station tier** (`_station_h5_key`), in order:

1. `mth5-entry-v1`, the entry-format tag;
2. the h5py and HDF5 versions (`_mth5_lib_fingerprint`): both shape the file and `lib_versions`
   names neither (`test_station_key_moves_with_the_hdf5_stack`);
3. sha256 of the source file bytes, and its file NAME (the extension selects the reader);
4. the survey.yaml digest (the same single-read digest §2 item 5 and A4 use);
5. slug and label;
6. the FINAL station id, after `_disambiguate`; the sanitisation `_sanitise_station_id` applies
   inside the writer is a pure function of that id and of engine code, which the salt binds;
7. the record's `source_provenance`, which `_stamp_mth5_source_provenance` writes into the station
   comments;
8. the SMETA projection `_mth5_survey_fields`: the fields the survey_metadata mapping reads
   (title, blurb, DOI, organisation, licence, first publication, project lead, first funder).
   `_apply_mth5_survey_metadata` reads SMETA only through that projection, so a field outside it
   cannot reach an MTH5 byte without first entering the projection and so the key.

`test_station_key_moves_with_every_component` moves each one in turn.

**Survey tier** (`_survey_h5_key`): the tag, the h5py/HDF5 versions, the survey.yaml digest, slug,
label, the SMETA projection, then the SORTED member station keys. Each member key binds that
member's inputs, so an edit to any member, or a member added or dropped, moves the bundle, and
member order does not (mth5 addresses stations by name)
(`test_survey_key_is_the_sorted_member_keys_plus_digest_and_salt`,
`test_one_byte_edi_edit_moves_its_station_and_survey_files_only`).

**Inputs that are deliberately not key parts, and why:**

* *Coordinate access generalisation, the `channels_recorded` impedance mask
  (`derived_rendition_withheld`), the per-station `station_channels` masks.* They decide
  MEMBERSHIP, before any key is derived: a withheld or generalised station reaches no writer and
  gets no entry, and the survey key binds membership through its member keys. The writer re-reads
  the source file, never the masked record; `test_record_fields_outside_the_key_cannot_reach_the_h5`
  writes a record carrying nulled coordinates, masks, run facts and other fields and gets a
  semantically equal file and an equal key. All three declarations live in survey.yaml, so the
  survey digest moves every key of that survey when one changes in any case. (The tipper mask is
  not a withhold and a masked tipper is republished in both MTH5 tiers; that is the recorded
  policy gap in `derived_rendition_withheld`, not a cache matter: the cache serves exactly what a
  fresh write would.)
* *Run facts* (`run-metadata.csv`, the >INFO dialect facts in the parse row). `_write_tf_mth5`
  reads the record in two places only, `r["id"]` and `source_provenance`; run facts reach
  station.json, not the MTH5 (same test).
* *The --pid-status resolution facets.* The one file outside the survey package that feeds SMETA
  (`/out/cache/pid_status.json` on the box) adds `doi_resolution` and related facets. They are not
  in the projection, and `test_pid_status_and_unread_smeta_fields_cannot_reach_the_h5` writes the
  full resolved SMETA and its projection and gets semantically equal files and equal keys. The DOI
  VALUE itself is in the projection, so an injected or changed DOI moves the key.
* *--seed-meta.* Only a `--raw` build reads it, and A1a keeps `--raw` builds out of the cache
  entirely; `test_raw_seed_meta_build_never_caches_an_mth5` pins that for the MTH5 kinds with both
  h5 flags on.
* *failure_rows.* An OUTPUT of the writer, never an input: it is stored in the entry's meta and
  replayed on a hit.
* *The source file's directory.* It never reaches the file
  (`test_source_directory_is_not_a_key_part_because_it_never_reaches_the_h5`).
* *numpy and other transitive libraries, the lock file.* Not key parts, the same stance the parse
  and XML entries have always taken; a lock change that should re-derive the corpus is a
  `--cache-mode refresh` build.

### Hardlink discipline and prune

The cache payload, the file in the build that populated it, and the file in every warm build since
are ONE inode. That is safe only because nothing ever writes into an existing MTH5 inode:

* a build writes a new file: `_write_tf_mth5` unlinks any file at its path BEFORE `open_mth5(mode="w")`,
  because mode "w" truncates in place and would write through into the cache and every tree that
  links the inode. That unlink is load-bearing and commented as such;
  `test_rewriting_a_served_tree_never_writes_through_to_the_cache` rebuilds, without a cache, into a
  tree whose files are cache links and asserts every payload keeps its bytes (removing the unlink
  turns it red: "a write into a served tree changed a cache payload");
* the cache stores or replaces an entry by renaming a new file over the old name, and places a hit
  by renaming a verified link into place; neither ever opens an existing payload for writing;
* served trees are never mutated in place; the box prunes old builds with `rm -rf`, which unlinks
  names; a release (`cut_release._copy_tree`) is a `shutil.copy2` byte copy, a new inode that shares
  nothing with the cache.

So unlinking a cache entry (prune, eviction, corrupt drop, refresh replacement) never changes a
served tree: the tree keeps its name on the same inode and the bytes it verified with
(`test_evicting_every_entry_leaves_the_served_tree_intact` evicts every entry under a zero cap and
reruns `verify.py` on the warm tree). The corollary: bit rot in a shared inode is rot in every tree
that links it, which is why every read re-hashes before placing, and why `verify.py` stays the full,
cache-blind, byte-re-hashing gate §0 made it.

A filesystem that refuses a hardlink (cross-device EXDEV, no link support, a link-count limit) gets
a byte copy, counted in `link_fallbacks`; a copy is a new inode, so the discipline above holds
trivially (`test_failed_hardlink_falls_back_to_a_counted_copy`). On the box `/out/cache` and
`/out/builds` are siblings on one volume, so links are expected to succeed there.

The prune now works on ENTRIES, not files: an entry is every file of one key inside its
two-character shard, aged and evicted together, so a payload and its sidecar live and die as one,
and anything else in the cache root (the Makefile keeps `pid_status.json` there) is never counted,
aged or evicted (`test_file_entry_roundtrip_and_prune_keeps_foreign_files`). A hit touches the
sidecar only: the payload's mtime is also the served file's mtime and must not move with cache
bookkeeping; an entry's age is the newest mtime of its files.

### The cap, sized from measured sizes

§3's default of 2048 MB is superseded: `CACHE_MAX_MB_DEFAULT = 8192`, and `deploy/compose.yaml`
forwards the same default (`test_compose_default_cap_matches_the_engine_default` pins them equal).
Measured on the locked stack (mt_metadata 1.0.10, mth5 0.6.8, h5py 3.16.0, HDF5 2.0.0):

* the fixture (2 sample stations, one cold build): parse 10,615 B for 2 entries, XML 121,069 B
  for 2, station MTH5 208,487 B each, the 2-station survey MTH5 276,327 B, sidecars 190 B each;
* the corpus (`ausmt-surveys-base`: 27 surveys, 2,631 EDIs): one-station MTH5 files for a
  first/middle/last sample of every survey, 79 written, 170,429 / 201,445 / 194,573 / 240,294 B
  (min / median / mean / max); full survey bundles of 20, 36 and 100 stations at 57,640, 70,038
  and 68,431 B per station; the 2,605 served XML of a full-corpus build tree
  (`sm/tip-battery-b9/base-out`) total 177,369,754 B.

Projected over 2,631 stations: station MTH5 488 MiB at the mean (603 MiB at the max), survey MTH5
176 MiB at 70,038 B per station, XML 169 MiB, parse 13 MiB: one key generation of the corpus is
846 to 961 MiB. The old 2048 cap holds 2.1 generations of the high estimate; 8192 holds 8.5. A
generation larger than the cap would evict live entries on every build and turn every warm build
cold without a word, which is the failure the cap must not produce; 8192 leaves room for the
corpus to grow several-fold, or for several key generations (an engine-source change re-keys
everything; the old generation is aged out after 90 days or evicted oldest-first) before that
happens.

The cap counts the cache's own file sizes, so a payload hardlinked into retained builds is counted
in full although the disk holds it once: the cap bounds what the cache would cost if every build
sharing it were pruned. Disk use of the whole data volume goes DOWN with this amendment: the box
retains 5 builds (`tail -n +6`), each of which held its own ~664 MiB of MTH5 (the projection
above); warm builds now share one inode per file with the cache.

When the size cap does evict, the build says so: `C18 cache WARN: the size cap
(AUSMT_CACHE_MAX_MB=...) evicted N entries, M of them used by this build`. `M` counts evicted
entries whose mtime is at or after the build's start, which the next build misses; a repeating
warning with `M > 0` means the cap is too small for the corpus
(`test_size_cap_eviction_warns_and_is_counted`).

### Counters

`build_provenance.json`'s `cache` block keeps the corpus totals `hits`, `misses`, `writes`,
`corrupt` as the parse + XML tally, so their meaning under the per-survey lines and the deploy
alerting does not move, and adds `max_mb`, `prune` (`pruned_age`, `pruned_size`, `evicted_live`,
`kept`, `bytes`) and `kinds`: for each of `parse`, `xml`, `station_h5`, `survey_h5` the integer
counters `hits`, `misses`, `writes`, `corrupt`, `link_fallbacks`, `evicted`. The block is rewritten
after the end-of-build prune, because evictions are only final then, and the build prints one
`C18 cache kind <kind>: ...` line per kind to stderr
(`test_build_provenance_carries_per_kind_counters_and_the_log_prints_them`). Counters stay
deterministic; none is a timing.

### Modes and the degenerate salt

* `rw`: read, place hits, write misses, prune at the end of a successful build.
* `ro`: reads and places hits exactly as `rw`; never stores an entry, and does not prune. As for
  the parse and XML entries, a hit still refreshes the entry's mtime and a read that fails its
  checksum still deletes the bad entry (`test_refresh_rewrites_and_ro_never_writes`: ro against an
  empty cache leaves it empty; ro against a populated one hits everything and leaves the listing of
  names and inodes unchanged).
* `refresh`: every MTH5 read is a miss, every file is written and gated, and every entry is
  replaced by a new inode; builds that linked the old inode keep it.
* degenerate salt, or the `--raw` policy exclusion: the cache is inert, no MTH5 key is even
  derived, every file is written and gated fresh, and every per-kind counter is zero
  (`test_degenerate_salt_writes_fresh_and_never_touches_the_cache`).

The parallel build (`--workers`) keys, links and populates exactly as the serial one
(`test_parallel_build_hits_the_same_entries`). All of the above is in
`engine/tests/test_build_cache_mth5.py`; `docs/docs/developer/build-lifecycle.md` and
`portal-documents.md` carry the operator- and consumer-facing parts.
