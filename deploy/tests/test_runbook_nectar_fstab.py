"""The fstab edits RUNBOOK-NECTAR.md step 4A prints, run against the fstab lines they must edit.

Step 4A parks the volume line cloud-init wrote and later restores it. cloud-init writes its
`mounts:` entries tab-separated, and the runbook's own fallback in 4.2 writes them space-separated,
so a pattern that names one separator leaves the other line active and the bind mount fails.

The commands are taken from the runbook text itself, not copied here, so the procedure an operator
pastes and the procedure this file checks cannot drift apart. Each `sudo sed -i ... /etc/fstab` line
of step 4A runs as `sed <its expressions>` over stdin, which behaves the same under GNU and BSD sed.
"""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_RUNBOOK = _REPO / "deploy" / "nectar" / "RUNBOOK-NECTAR.md"
_SED = shutil.which("sed")

pytestmark = pytest.mark.skipif(_SED is None, reason="no sed on PATH")

_VOLUME_FIELDS = ["LABEL=ausmt-data", "/srv/ausmt", "ext4",
                  "defaults,nofail,x-systemd.device-timeout=30s", "0", "2"]
CLOUD_INIT_LINE = "\t".join(_VOLUME_FIELDS)
FALLBACK_LINE = " ".join(_VOLUME_FIELDS)
BIND_LINE = "/var/lib/ausmt-proof /srv/ausmt none bind 0 0"
ROOT_LINE = "LABEL=cloudimg-rootfs\t/\text4\tdiscard,errors=remount-ro\t0\t1"


def _step_4a() -> str:
    text = _RUNBOOK.read_text(encoding="utf-8")
    m = re.search(r"^4A\.(.*?)^---", text, flags=re.M | re.S)
    assert m, "RUNBOOK-NECTAR.md must keep its step 4A"
    return m.group(1)


def _fstab_seds() -> list[list[str]]:
    """Every `sudo sed -i ... /etc/fstab` of step 4A as a stdin-to-stdout sed argv, in order."""
    out = []
    for line in _step_4a().splitlines():
        if not line.lstrip().startswith("sudo sed"):
            continue
        argv = shlex.split(line, comments=True)
        assert argv[:3] == ["sudo", "sed", "-i"] and argv[-1] == "/etc/fstab", argv
        out.append([_SED, *argv[3:-1]])
    assert len(out) == 2, f"step 4A parks the volume line and restores it, found {out}"
    return out


def _run(argv: list[str], fstab: str) -> str:
    r = subprocess.run(argv, input=fstab, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


@pytest.mark.parametrize("volume_line", [CLOUD_INIT_LINE, FALLBACK_LINE], ids=["tab", "space"])
def test_the_park_comments_out_the_volume_line_whatever_its_separator(volume_line):
    """FAILS IF the park leaves the volume line active, which keeps the volume and the bind mount
    competing for /srv/ausmt, or touches any other line."""
    park, _restore = _fstab_seds()
    after = _run(park, f"{ROOT_LINE}\n{volume_line}\n").splitlines()
    assert after == [ROOT_LINE, "#" + volume_line], after


@pytest.mark.parametrize("volume_line", [CLOUD_INIT_LINE, FALLBACK_LINE], ids=["tab", "space"])
def test_the_restore_reverses_the_park_and_drops_the_bind_line(volume_line):
    """FAILS IF moving to the volume leaves the line parked or the bind line in place."""
    _park, restore = _fstab_seds()
    parked = f"{ROOT_LINE}\n#{volume_line}\n{BIND_LINE}\n"
    assert _run(restore, parked).splitlines() == [ROOT_LINE, volume_line]


def test_the_park_leaves_a_longer_label_alone():
    """FAILS IF the pattern stops at the label's last letter, so a second volume labelled
    ausmt-data-old would be parked with it."""
    park, _restore = _fstab_seds()
    other = CLOUD_INIT_LINE.replace("LABEL=ausmt-data", "LABEL=ausmt-data-old", 1)
    assert _run(park, other + "\n").splitlines() == [other]
