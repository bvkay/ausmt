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
2. `engine_code_sha` — **coarse v1 salt = `BUILD_ID["engine_commit"]`**. Any engine commit busts
   the whole cache: simple, correct, and engine commits are rare relative to survey edits.
   **Integrity rule: if the engine commit is unknown/None, OR the checkout is dirty
   (`git status --porcelain` non-empty where a checkout exists), incremental is silently DISABLED
   for that build (treated as full, no cache reads or writes).** A degenerate or ambiguous salt
   must never key a cache. (Note: the live box currently emits null commits in build.json — until
   that is healthy, the cache simply never fires there. Correct behaviour, not a bug.)
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
3. **Salt invalidation:** simulated engine-commit change ⇒ zero hits; mt_metadata version change ⇒
   zero hits; survey.yaml edit ⇒ that survey re-derives, other surveys still hit.
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

(c) **§4.5 — the equivalence contract, stated precisely.** mt_metadata's EMTF-XML writer stamps a
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
