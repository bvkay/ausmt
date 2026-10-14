# Hosting and serving

How the public portal is hosted, who holds what, and how a finished build reaches the public site. The
design and its arithmetic are recorded in
[`maintainer/C48-NectarTopology.md`](https://github.com/bvkay/ausmt/blob/main/maintainer/C48-NectarTopology.md);
the step-by-step procedure is
[`deploy/nectar/RUNBOOK-NECTAR.md`](https://github.com/bvkay/ausmt/blob/main/deploy/nectar/RUNBOOK-NECTAR.md).

## Where it stands

Since 14 October 2026 the public site is served from the Nectar Research Cloud. Both public names,
`ausmt.auscope.org.au` and the redirect name `ausmt.au`, point by DNS at the serving host,
`ausmt-serve`. The home box no longer serves visitors: it holds the curation role, builds, publishes
each build to the serving host, answers the Add Survey routes over the tailnet, and collects the
access log for the usage statistics.

Nectar gives each instance a fixed public address for its life; nothing is moved between instances.
So the move to the serving host was a DNS change: both names' A records went from the earlier
front-door instance's address (203.101.226.191) to the serving host's (203.101.226.53), with a
five-minute TTL, after the serving host had been checked by name against its own address. Until the
earlier instance is deleted, pointing the records back is the rollback; deleting it releases its
address.

## Two roles

AusMT runs on Nectar as two roles. The serving host is live; the home box holds the curation role
until a Nectar curation host (`ausmt-curate`) takes it over.

**The serving host** (`ausmt-serve`) is the only machine the internet can reach, and it opens only
the web ports. It runs the public front door (TLS, the masked access log, the allowlist of public
routes) and the portal's static server, and it holds the built portal tree, for now on its own disk
at one kept build, later on a storage volume. It
holds nothing that is not already public: no survey repository credential, no submission gateway, no
curation database and no build cache. It never builds; it receives builds.

**The curation host** admits no traffic from the internet and is reached only over the tailnet (a
private overlay network). It runs everything that curates and builds: the submission gateway and its antivirus
scanner, the survey repository checkout and its publish credential, the curation database, and the
reconcile agent that rebuilds the corpus when the survey repository moves. Curators reach its
workbench over the tailnet and nowhere else.

The home box, while it holds the curation role, publishes to the serving host in exactly the same way.

## How a build reaches the public site

1. A curator publishes a survey; the reconcile agent on the curation host sees the survey repository
   move and rebuilds, verifies and swaps in the new build locally, as it always has.
2. The same pass **publishes** the served build to the serving host over the tailnet: a checksum list
   of every file travels beside the build, and only files that changed are stored again (an unchanged
   file is hard-linked to the copy already served).
3. The serving host **verifies** the build against its checksum list, file by file, and only then
   swaps it in atomically, so a visitor never sees a half-copied or altered tree. It records which
   build it serves and when it received it in `published.json`.
4. A build that fails verification is refused and the previous build keeps serving; the failure
   reaches the operator through the reconcile status and the external alert.

A curator's rollback to an earlier build travels the same path, so the public site follows it.

## Who can reach what

- The public reaches the serving host's web ports only, and through them the reader, the data files
  and the Add Survey contribution page with its four submission routes. The submission routes are
  answered by the gateway, which runs on the curation host: the serving host's front door forwards
  exactly those four over the tailnet to the curation host's public-subset listener, which checks them
  against its own allowlist. The curator workbench is never on the public name.
- The serving host reaches the curation host over the tailnet on that one listener port only.
- The curation host reaches the serving host over the tailnet as two accounts without a shell: one
  that receives builds, and one that pulls the masked access log for the usage statistics. Neither
  can reach a secret on the serving host.
- Curators join the tailnet by invitation (a passkey or institutional sign-in), reach only the
  workbench, served over HTTPS on the curation host's tailnet name, and then sign in to it with a
  named key and a second factor.
