# usb-encrypt

Scripts to mount, unmount, and back up to a LUKS-encrypted USB drive on Linux, with a systemd timer for daily automated backups.

## Requirements

- `cryptsetup`
- `rsync`
- `systemd`
- `python3`
- An encrypted USB partition at `/dev/sdc1` (created with `cryptsetup luksFormat`)
- A mount point at `/mnt/usb` (`sudo mkdir -p /mnt/usb`)

## Scripts

### `mount-usb`
Unlocks and mounts the encrypted USB drive.
```bash
mount-usb
```

### `umount-usb`
Unmounts and locks the encrypted USB drive. Safe to run even if already unmounted.
```bash
umount-usb
```

### `backup-usb`
Mounts the drive, syncs the configured directories, flushes buffers, then unmounts and locks. Safe to run while the drive is already mounted — it will leave it mounted when done.
```bash
backup-usb
```

**Backed up directories:**
- `~/code`
- `~/Documents`
- `~/Pictures`
- `~/.ssh`
- `~/.config`

All synced to `/mnt/usb/backups/`.

## Installation

Clone the repo and create the virtual environment:

```bash
git clone git@github.com:fewill/usb-encrypt.git
cd usb-encrypt
python3 -m venv .venv
```

Add `~/.local/bin` to your PATH if not already present:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

Run the update script to install everything:
```bash
.venv/bin/python update-scripts.py
```

## Updating

Pull the latest changes and re-run the update script:

```bash
git pull && .venv/bin/python update-scripts.py
```

To update specific targets only:
```bash
.venv/bin/python update-scripts.py mount-usb umount-usb
.venv/bin/python update-scripts.py backup-usb.service backup-usb.timer
```

List all available targets:
```bash
.venv/bin/python update-scripts.py --list
```

The update script only copies files that have changed, and automatically runs `sudo systemctl daemon-reload` if any systemd units were updated.

## Scheduling (systemd timer)

Enable the timer for daily automated backups:

```bash
sudo systemctl enable --now backup-usb.timer
```

Verify the timer is active:
```bash
systemctl list-timers backup-usb.timer
```

The timer runs daily at midnight. `Persistent=true` ensures it runs at next boot if the machine was off at midnight.

View backup logs:
```bash
journalctl -u backup-usb.service -n 50 --no-pager
```

## Backup Strategy

These scripts cover the **local backup** leg of a 3-2-1 strategy:

| Copy | Location | Method |
|------|----------|--------|
| 1 | Main machine | Source |
| 2 | Encrypted USB | `rsync` (this repo) |
| 3 | Offsite (planned) | AWS S3 via `rclone` |
