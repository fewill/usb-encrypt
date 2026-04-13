#!/usr/bin/env python3
"""Update installed scripts and systemd units from the repo."""

import argparse
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).parent.resolve()
BIN_DIR = Path.home() / ".local/bin"
SYSTEMD_DIR = Path("/etc/systemd/system")

BIN_SCRIPTS = {
    "mount-ssd":  (REPO_DIR / "mount-ssd.sh",      BIN_DIR / "mount-ssd"),
    "umount-ssd": (REPO_DIR / "umount-ssd.sh",     BIN_DIR / "umount-ssd"),
    "mount-usb":  (REPO_DIR / "mount-usb.sh",      BIN_DIR / "mount-usb"),
    "umount-usb": (REPO_DIR / "umount-usb.sh",     BIN_DIR / "umount-usb"),
    "backup-usb": (REPO_DIR / "backup-usb.sh",     BIN_DIR / "backup-usb"),
}

SYSTEMD_UNITS = {
    "backup-usb.service": (REPO_DIR / "backup-usb.service", SYSTEMD_DIR / "backup-usb.service"),
    "backup-usb.timer":   (REPO_DIR / "backup-usb.timer",   SYSTEMD_DIR / "backup-usb.timer"),
}

ALL_TARGETS = list(BIN_SCRIPTS) + list(SYSTEMD_UNITS)


def copy_bin(name, src, dest):
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if dest.exists() and filecmp.cmp(src, dest, shallow=False):
        print(f"  {name}: up to date")
        return False
    shutil.copy2(src, dest)
    dest.chmod(0o755)
    print(f"  {name}: updated")
    return True


def copy_systemd(name, src, dest):
    if dest.exists() and filecmp.cmp(src, dest, shallow=False):
        print(f"  {name}: up to date")
        return False
    result = subprocess.run(["sudo", "cp", str(src), str(dest)])
    if result.returncode != 0:
        print(f"  {name}: failed (sudo cp exited {result.returncode})", file=sys.stderr)
        return False
    print(f"  {name}: updated")
    return True


def reload_systemd():
    print("  Reloading systemd daemon...")
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)


def update(targets):
    bin_changed = False
    systemd_changed = False

    for name in targets:
        if name in BIN_SCRIPTS:
            src, dest = BIN_SCRIPTS[name]
            bin_changed |= copy_bin(name, src, dest)
        elif name in SYSTEMD_UNITS:
            src, dest = SYSTEMD_UNITS[name]
            systemd_changed |= copy_systemd(name, src, dest)

    if systemd_changed:
        reload_systemd()


def main():
    parser = argparse.ArgumentParser(description="Update installed scripts and systemd units from the repo.")
    parser.add_argument(
        "targets",
        nargs="*",
        choices=ALL_TARGETS + [[]],
        metavar="TARGET",
        help=f"One or more targets to update: {', '.join(ALL_TARGETS)}. Defaults to all.",
    )
    parser.add_argument(
        "--list", action="store_true", help="List available targets and exit."
    )
    args = parser.parse_args()

    if args.list:
        print("Available targets:")
        for name in ALL_TARGETS:
            print(f"  {name}")
        return

    targets = args.targets if args.targets else ALL_TARGETS
    print(f"Updating: {', '.join(targets)}")
    update(targets)
    print("Done.")


if __name__ == "__main__":
    main()
