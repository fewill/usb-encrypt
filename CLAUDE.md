# CLAUDE.md — usb-encrypt

## Project Overview

Encrypted SSD backup system for a Linux laptop (fewill-fw13). Backs up local directories to a LUKS-encrypted Samsung Extreme SSD and AWS S3, with Slack notifications and two-way slash command control.

## Key Files

| File | Purpose |
|------|---------|
| `mount-ssd.sh` | Unlock and mount `/dev/sda1` → `/media/fewill/Extreme SSD` |
| `umount-ssd.sh` | Unmount and lock the SSD |
| `mount-usb.sh` | Legacy — unlock/mount old USB flash drive (`/dev/sdc1`) |
| `umount-usb.sh` | Legacy — unmount/lock old USB flash drive |
| `backup-usb.sh` | Full backup: rsync → SSD, rclone → S3, Slack notify |
| `backup-usb.service` | systemd service (runs as root) |
| `backup-usb.timer` | systemd timer (daily at midnight, persistent) |
| `backup-poller.service` | systemd service for SQS poller (runs as fewill) |
| `poller.py` | Polls SQS for Slack slash commands, executes them |
| `notify_slack.py` | Posts messages to #opn-backup via Slack bot |
| `get_credentials.py` | Resolves credentials from 1Password via credentialsmanager |
| `credentials.yml` | 1Password secret references for Slack, LUKS, and AWS |
| `update-scripts.py` | CLI to sync repo files to install locations |
| `lambda/handler.py` | AWS Lambda — receives /backup slash commands from Slack |
| `requirements.txt` | Python dependencies |
| `.env` | Local secrets (not committed) — only `OP_SERVICE_ACCOUNT_TOKEN` needed |

## Hardware

- **SSD device:** `/dev/sda1` (LUKS encrypted — Samsung Extreme SSD)
- **Mapper:** `/dev/mapper/encrypted_ssd`
- **Mount point:** `/media/fewill/Extreme SSD`
- **Backup destination:** `/media/fewill/Extreme SSD/backups/`

## Install Locations

- Scripts: `~/.local/bin/` (backup-usb)
- systemd units: `/etc/systemd/system/`

## AWS Infrastructure

- **S3 bucket:** `opn-usb-backup` (us-east-2, versioning enabled, public access blocked)
- **SQS queue:** `backup-commands` (us-east-2)
- **Lambda:** `backup-slack-handler` (us-east-2, python3.12)
- **API Gateway:** `backup-slack-api` (id: 888rs3f9x2, us-east-2)
- **API endpoint:** `https://888rs3f9x2.execute-api.us-east-2.amazonaws.com/prod/backup`
- **IAM user:** `usb-backup` (AmazonS3FullAccess, AmazonSQSFullAccess)
- **IAM role:** `backup-lambda-role` (AWSLambdaBasicExecutionRole, AmazonSQSFullAccess)

## Slack Integration

- **Channel:** `#opn-backup`
- **Slash command:** `/backup [run|status]`
- **Bot token:** stored in 1Password → `fw-fw13 ssd-encrypt backup / Slack App / bot_token`
- **Flow:** Slack → API Gateway → Lambda → SQS → poller.py → runs command → notify_slack.py

## Credentials

All credentials stored in 1Password and referenced via `credentials.yml`:

| Section | Keys | Used By |
|---------|------|---------|
| `slack_creds` | `bot_token` | `notify_slack.py` |
| `luks_creds` | `passphrase` | `backup-usb.sh` (unattended SSD unlock) |
| `aws_creds` | `access_key_id`, `secret_access_key`, `default_region` | `backup-usb.sh` → rclone |

- `.env` holds only `OP_SERVICE_ACCOUNT_TOKEN` (and optionally AWS keys for poller/SQS)
- rclone config at `~/.config/rclone/rclone.conf` uses `env_auth=true` (no hardcoded keys, remote: `fw-fw13`)

## Backed Up Directories

```
~/code
~/Documents
~/Pictures
~/Downloads
~/Desktop
~/.ssh
~/.config
~/.local/share
~/.mozilla
~/.zoom
/etc
```

**Key excludes:** Trash, 1Password logs, VSCode cache/history, Chrome cache, node_modules, Claude app binaries, Heroku CLI, wcbuild/.pypi, /etc/alternatives, Zoom IPC sockets

## Logs

- File logs: `~/code/usb-encrypt/logs/backup-YYYY-MM-DD_HH-MM-SS.log` (30-day retention)
- systemd: `journalctl -u backup-usb.service -f`

## Common Tasks

**Run a backup manually:**
```bash
sudo systemctl start backup-usb.service
journalctl -u backup-usb.service -f
```

**Check backup timer:**
```bash
systemctl list-timers backup-usb.timer
```

**Check poller:**
```bash
journalctl -u backup-poller.service -f
```

**Update installed scripts after changes:**
```bash
.venv/bin/python update-scripts.py
```

**Deploy Lambda changes:**
```bash
cd lambda && zip handler.zip handler.py && aws lambda update-function-code --function-name backup-slack-handler --zip-file fileb://handler.zip --region us-east-2
```

**Test Slack notification:**
```bash
.venv/bin/python notify_slack.py "Test message"
.venv/bin/python notify_slack.py "Test failure" --urgency critical
```

**Test credentials:**
```bash
.venv/bin/python get_credentials.py --section luks_creds
.venv/bin/python get_credentials.py --section aws_creds
.venv/bin/python get_credentials.py --section slack_creds
```

**Mount/unmount SSD manually:**
```bash
./mount-ssd.sh
./umount-ssd.sh
```

## Known Issues / Notes

- `backup-usb.service` runs as `root` (required for cryptsetup/mount). The backup script uses hardcoded `USER_HOME=/home/fewill` since `$HOME` would resolve to `/root`.
- rsync exit code 24 ("some files vanished") is treated as success — this is normal for active directories like `.config`.
- `sync` is called before unmounting to flush OS write buffers. On a full backup this can take several minutes.
- The SQS poller uses IAM user credentials from `.env` (not SSO) to avoid session expiry.
- The Lambda verifies Slack request signatures and decodes base64 body (API Gateway sends base64-encoded bodies).
- LUKS passphrase is passed via `printf '%s'` (not `echo`) to avoid a trailing newline mismatch.
- The SSD mount point `/media/fewill/Extreme SSD` is created with `mkdir -p` by the backup script when unlocking manually (the OS only creates it on auto-mount).

## Dependencies

- `credentialsmanager` installed from `../credentialsmanager` (local package)
- `rclone` configured with remote `fw-fw13` pointing to `opn-usb-backup` (env_auth=true)
