"""The serving replica's first-boot configuration (deploy/nectar/cloud-init-serve.yaml) and the
provisioning script it hands over to (deploy/nectar/provision-serve.sh).

Read, never run: both act on a fresh Nectar instance. What is pinned is what the files may and may
not carry. The user-data is pasted into a dashboard and the script is committed to a public
repository, so neither may hold a credential of any kind; the serve role holds no curation duty, so
neither may install the timers that belong to the curation host; and the two must between them
mount the data volume by label, lay the tree down with the ownership deploy/README.md specifies for
site-data, and restrict the publish account to its gate.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_NECTAR = _REPO / "deploy" / "nectar"
_CLOUD_INIT = _NECTAR / "cloud-init-serve.yaml"
_PROVISION = _NECTAR / "provision-serve.sh"

yaml = pytest.importorskip("yaml")

# Shapes a real credential takes: a Tailscale auth key, GitHub tokens, a private key block, a cloud
# access key, a password hash, and a real ssh public key body (a placeholder names itself instead).
SECRET_SHAPES = (
    re.compile(r"tskey-[A-Za-z0-9-]{8,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\$[1256y]\$[^\s:]{8,}"),
    re.compile(r"\bAAAA[0-9A-Za-z+/]{40,}"),
    re.compile(r"^\s*(?:passwd|password|hashed_passwd|chpasswd)\s*:", re.M),
)
# Units and scripts that belong to the curation role.
CURATE_ONLY = ("ausmt-reconcile", "ausmt-backup", "ausmt-drill", "ausmt-stats", "ausmt-actions",
               "ausmt-alert", "reconcile.sh", "backup.sh", "restore-drill.sh", "actions.sh",
               "aggregate_stats.py", "--profile gateway", "clamd")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _doc() -> dict:
    return yaml.safe_load(_text(_CLOUD_INIT))


def test_the_user_data_is_cloud_config_and_parses():
    text = _text(_CLOUD_INIT)
    assert text.startswith("#cloud-config\n"), "cloud-init reads the file as cloud-config only then"
    assert isinstance(_doc(), dict)


@pytest.mark.parametrize("path", [_CLOUD_INIT, _PROVISION], ids=lambda p: p.name)
def test_nothing_secret_is_committed(path):
    text = _text(path)
    hits = [p.pattern for p in SECRET_SHAPES if p.search(text)]
    assert not hits, f"{path.name} carries a credential-shaped string: {hits}"


@pytest.mark.parametrize("path", [_CLOUD_INIT, _PROVISION], ids=lambda p: p.name)
def test_no_curation_timer_or_service_is_installed(path):
    text = _text(path)
    found = [name for name in CURATE_ONLY if name in text]
    assert not found, f"{path.name} names curation-role machinery: {found}"


def test_the_volume_is_mounted_by_label_with_an_fstab_entry():
    mounts = _doc().get("mounts") or []
    rows = [m for m in mounts if isinstance(m, list) and m and str(m[0]).startswith("LABEL=")]
    assert rows, "the data volume must be mounted by filesystem label"
    row = rows[0]
    assert row[1] == "/srv/ausmt"
    assert "nofail" in row[3], "an absent volume must not stop the instance booting"


def test_the_host_gets_docker_compose_tailscale_and_unattended_upgrades():
    doc = _doc()
    packages = set(doc.get("packages") or [])
    assert {"docker.io", "docker-compose-v2", "unattended-upgrades", "rsync", "git",
            "python3"} <= packages, packages
    text = _text(_CLOUD_INIT)
    assert "tailscale" in text
    assert "Unattended-Upgrade" in text, "unattended-upgrades must be switched on, not only installed"


def test_the_publish_account_is_uid_10001_behind_its_gate():
    text = _text(_CLOUD_INIT)
    assert re.search(r"useradd\b[^\n]*-u 10001\b[^\n]*\bpublish\b", text), \
        "the publish account must be uid 10001, the uid that owns site-data"
    assert re.search(r'command="[^"]*ausmt-publish-gate[^"]*",restrict ', text), \
        "the key placeholder must carry the forced command and restrict"
    assert "REPLACE_WITH" in text, "the key must be a placeholder filled at launch"
    prov = _text(_PROVISION)
    assert "usermod -s /usr/local/bin/ausmt-publish-gate publish" in prov, \
        "the gate must also be the account's login shell, which a Tailscale SSH session runs"


def test_the_log_account_is_behind_its_own_gate():
    """The curation host pulls the masked front-door log from this host, so the log account exists
    here, reads /var/log/caddy only, and has the read-only rrsync gate as its login shell."""
    prov = _text(_PROVISION)
    assert "deploy/nectar/caddylog-gate.sh" in prov
    assert "usermod -s /usr/local/bin/ausmt-caddylog-gate caddylog" in prov
    assert re.search(r"setfacl\b[^\n]*u:caddylog:rX[^\n]*/var/log/caddy", prov), prov


def test_first_boot_hands_over_to_the_provisioning_script():
    text = _text(_CLOUD_INIT)
    assert "deploy/nectar/provision-serve.sh" in text
    runcmd = "\n".join(str(c) for c in (_doc().get("runcmd") or []))
    assert "provision-serve.sh" in runcmd


def test_the_tree_and_its_ownership_follow_the_deploy_readme():
    """site-data is written only by uid 10001 (deploy/README.md, First-run checklist). The serve
    role runs no gateway, so the 10002 gateway tree is deliberately not laid down here."""
    prov = _text(_PROVISION)
    assert re.search(r"-o 10001 -g 10001\b[^\n]*site-data", prov) or \
        re.search(r"chown\b[^\n]*10001:10001[^\n]*site-data", prov), prov
    assert "10002" not in prov and "gateway/state" not in prov
    for d in ("site-data/builds", "basemap", "logs/caddy"):
        assert d in prov, d
    assert "mountpoint -q" in prov, "the tree must never be laid down on the root disk"


def test_provisioning_installs_the_receiver_and_starts_the_serve_stack():
    prov = _text(_PROVISION)
    for fragment in ("deploy/scripts/receive-build.sh", "/usr/local/bin/receive-build.sh",
                     "deploy/nectar/publish-gate.sh", "install-frontdoor.sh",
                     "AUSMT_BOX_READER_UPSTREAM=http://127.0.0.1:8445", "fetch-basemap.sh",
                     "make up", "pull --ff-only"):
        assert fragment in prov, fragment
