# CLAUDE.md — usb-encrypt

## Project Overview

Encrypted USB backup system for a Linux laptop (fewill-fw13). Backs up local directories to a LUKS-encrypted USB drive and AWS S3, with Slack notifications and two-way slash command control.

## Key Files

| File | Purpose |
|------|---------|
| `mount-usb.sh` | Unlock and mount `/dev/sdc1` → `/mnt/usb` |
| `umount-usb.sh` | Unmount and lock the USB drive |
| `backup-usb.sh` | Full backup: rsync → USB, rclone → S3, Slack notify |
| `backup-usb.service` | systemd service (runs as root) |
| `backup-usb.timer` | systemd timer (daily at midnight, persistent) |
| `backup-poller.service` | systemd service for SQS poller (runs as fewill) |
| `poller.py` | Polls SQS for Slack slash commands, executes them |
| `notify_slack.py` | Posts messages to #opn-backup via Slack bot |
| `get_credentials.py` | Resolves credentials from 1Password via credentialsmanager |
| `credentials.yml` | 1Password secret references for Slack |
| `update-scripts.py` | CLI to sync repo files to install locations |
| `lambda/handler.py` | AWS Lambda — receives /backup slash commands from Slack |
| `requirements.txt` | Python dependencies |
| `.env` | Local secrets (not committed) |

## Hardware

- **USB device:** `/dev/sdc1` (LUKS encrypted)
- **Mapper:** `/dev/mapper/encrypted_usb`
- **Mount point:** `/mnt/usb`
- **Backup destination:** `/mnt/usb/backups/`

## Install Locations

- Scripts: `~/.local/bin/` (mount-usb, umount-usb, backup-usb)
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
- **Bot token:** stored in 1Password → `USB Backup / slack_bot_token`
- **Flow:** Slack → API Gateway → Lambda → SQS → poller.py → runs command → notify_slack.py

## Credentials

- `.env` holds `OP_SERVICE_ACCOUNT_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`
- `credentials.yml` holds 1Password references for Slack bot token
- rclone config at `~/.config/rclone/rclone.conf` holds AWS credentials for S3 sync (remote: `fw-fw13`)

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
.venv/bin/python get_credentials.py
```

## Known Issues / Notes

- `backup-usb.service` runs as `root` (required for cryptsetup/mount). The backup script uses hardcoded `USER_HOME=/home/fewill` since `$HOME` would resolve to `/root`.
- rsync exit code 24 ("some files vanished") is treated as success — this is normal for active directories like `.config`.
- `sync` is called before unmounting to flush OS write buffers. On a full backup (~13GB) this can take several minutes — the drive light will flash during this time.
- The SQS poller uses IAM user credentials from `.env` (not SSO) to avoid session expiry.
- The Lambda verifies Slack request signatures and decodes base64 body (API Gateway sends base64-encoded bodies).

## Dependencies

- `credentialsmanager` installed from `../credentialsmanager` (local package)
- `rclone` configured with remote `s3-backup` pointing to `opn-usb-backup`
