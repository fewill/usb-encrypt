# usb-encrypt

Scripts to mount, unmount, and back up to a LUKS-encrypted USB drive on Linux, with a systemd timer for daily automated backups.

## Requirements

- `cryptsetup`
- `rsync`
- `systemd`
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

Copy scripts to `~/.local/bin` and ensure it is on your `PATH`:

```bash
mkdir -p ~/.local/bin
cp mount-usb.sh ~/.local/bin/mount-usb
cp umount-usb.sh ~/.local/bin/umount-usb
cp backup-usb.sh ~/.local/bin/backup-usb
```

Add to `~/.bashrc` if `~/.local/bin` is not already on your PATH:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Scheduling (systemd timer)

Install the service and timer for daily automated backups:

```bash
sudo cp backup-usb.service /etc/systemd/system/
sudo cp backup-usb.timer /etc/systemd/system/
sudo systemctl daemon-reload
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
