# Hosting and serving

How the public portal is hosted, who holds what, and how a finished build reaches the public site. The
design and its arithmetic are recorded in
[`maintainer/C48-NectarTopology.md`](https://github.com/bvkay/ausmt/blob/main/maintainer/C48-NectarTopology.md);
the step-by-step procedure is
[`deploy/nectar/RUNBOOK-NECTAR.md`](https://github.com/bvkay/ausmt/blob/main/deploy/nectar/RUNBOOK-NECTAR.md).

## Two roles

AusMT runs on the Nectar Research Cloud as two instances with separate jobs.

**The serving host** (`ausmt-serve`) is the only machine with a public address, and it opens only
the web ports. It runs the public front door (TLS, the masked access log, the allowlist of public
routes) and the portal's static server, and it holds the built portal tree on a storage volume. It
holds nothing that is not already public: no survey repository credential, no submission gateway, no
curation database and no build cache. It never builds; it receives builds.

**The curation host** has no public address and is reached only over the project's private network
(the tailnet). It runs everything that curates and builds: the submission gateway and its antivirus
scanner, the survey repository checkout and its publish credential, the curation database, and the
reconcile agent that rebuilds the corpus when the survey repository moves. Curators reach its
workbench over the tailnet and nowhere else.

Until the curation host is created, the home box holds the curation role, and it publishes to the
serving host in exactly the same way.

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
  answered by the gateway, which runs on the curation host; how the serving host forwards them is an
  open item in the design record. The curator workbench is never on the public name.
- The curation host reaches the serving host over the tailnet as two restricted accounts: one that
  can only receive builds, and one that can only read the masked access log for the usage statistics.
- Curators join the tailnet by invitation (a passkey or institutional sign-in), reach only the
  workbench port on the curation host, and then sign in to the workbench with a named key and a
  second factor.
