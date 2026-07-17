# CLAUDE.md — usb-encrypt

## Project Overview

Encrypted SSD backup system for a Linux laptop (fewill-fw13). Backs up local directories to a LUKS-encrypted Samsung Extreme SSD and AWS S3, with Slack notifications and two-way slash command control.

## Key Files

| File | Purpose |
|------|---------|
| `mount-ssd.sh` | Unlock and mount SSD by UUID → `/media/fewill/Extreme SSD` |
| `umount-ssd.sh` | Unmount and lock the SSD |
| `mount-usb.sh` | Legacy — unlock/mount old USB flash drive (`/dev/sdc1`) |
| `umount-usb.sh` | Legacy — unmount/lock old USB flash drive |
| `backup-usb.sh` | Full backup: rsync → SSD, rclone → S3, Slack notify |
| `backup-usb.service` | systemd service (runs as root) |
| `backup-usb.timer` | systemd timer (daily at midnight, persistent) |
| `backup-poller.service` | systemd service for SQS poller (runs as fewill) |
| `poller.py` | Polls SQS for Slack slash commands, executes them |
| `notify_slack.py` | Posts messages to #opn-backup via Slack bot (quiet hours aware) |
| `parse_backup_log.py` | Parses backup log and produces a Slack-ready summary |
| `get_credentials.py` | Resolves credentials from 1Password via credentialsmanager |
| `credentials.yml` | 1Password secret references for Slack, LUKS, and AWS |
| `update-scripts.py` | CLI to sync repo files to install locations |
| `lambda/handler.py` | AWS Lambda — receives /backup slash commands from Slack |
| `requirements.txt` | Python dependencies |
| `.env` | Local secrets (not committed) — only `OP_SERVICE_ACCOUNT_TOKEN` needed |

## Hardware

- **SSD device:** `/dev/disk/by-uuid/6f57da7c-0823-47ae-b9d3-cd98c1573dac` (Samsung Extreme SSD, LUKS encrypted)
- **Preferred mapper:** `/dev/mapper/encrypted_ssd` (used when the script opens the device itself)
- **Preferred mount point:** `/media/fewill/Extreme SSD`
- **Backup destination:** `<active_mount>/backups/` (determined dynamically — see Notes)

## Install Locations

- Scripts: `~/.local/bin/` (backup-usb)
- systemd units: `/etc/systemd/system/`

## AWS Infrastructure

- **S3 bucket:** `opn-usb-backup` (us-east-2, versioning enabled, public access blocked, lifecycle rule: retain 3 noncurrent versions — transition to Standard-IA after 30 days, expire after 7 years)
- **SQS queue:** `backup-commands` (us-east-2)
- **Lambda:** `backup-slack-handler` (us-east-2, python3.12)
- **API Gateway:** `backup-slack-api` (id: 888rs3f9x2, us-east-2)
- **API endpoint:** `https://888rs3f9x2.execute-api.us-east-2.amazonaws.com/prod/backup`
- **IAM role:** `usb-backup-role` — scoped to `opn-usb-backup` (S3: List/Get/Put/Delete/multipart) and `backup-commands` (SQS: Receive/Delete/GetQueueAttributes/GetQueueUrl) only. Assumed via IAM Roles Anywhere (self-managed CA, cert at `~/.config/usb-backup/aws-roles-anywhere/`) — no long-lived AWS keys on disk. `backup-usb.sh` mints short-lived creds via `aws_signing_helper credential-process` before each rclone sync; `poller.py` picks it up automatically via `AWS_PROFILE=usb-backup` (set in `backup-poller.service`), through boto3's default credential chain.
  - Trust anchor: `arn:aws:rolesanywhere:us-east-2:864899860638:trust-anchor/5b296f8a-2747-4257-99f6-d3c71a533c81`, profile: `arn:aws:rolesanywhere:us-east-2:864899860638:profile/6e3e4653-dd8e-4062-a59a-f543d89f890a`
  - **Session duration: 12 hours (43200s)** — set on both the Roles Anywhere profile's `durationSeconds` and the role's `MaxSessionDuration`, *and* passed explicitly via `--session-duration 43200` on the `aws_signing_helper` call in `backup-usb.sh`. All three must agree; `aws_signing_helper` defaults to 3600s regardless of the profile/role config if the flag is omitted. The original 1-hour default caused a backup failure on 2026-07-16 — the S3 sync routinely takes 3-4 hours to walk ~1M objects, so the token expired mid-run and the sync spent ~20 hours retrying against an expired token before giving up.
- **IAM role:** `backup-lambda-role` (AWSLambdaBasicExecutionRole, AmazonSQSFullAccess) — Lambda's own execution role, unrelated to the above
- **Retired:** IAM user `usb-backup` (AmazonS3FullAccess, AmazonSQSFullAccess) — replaced by `usb-backup-role` above. Deactivate/delete this user's access key once the new setup is confirmed stable (also closes an earlier leak: this key had ended up in plaintext in `../opn-support/.claude/settings.local.json`).

## Slack Integration

- **Channel:** `#opn-backup`
- **Slash command:** `/backup [run|status]`
- **Bot token:** stored in 1Password → `fw-fw13 ssd-encrypt backup / Slack App / bot_token`
- **Flow:** Slack → API Gateway → Lambda → SQS → poller.py → runs command → notify_slack.py
- **Quiet hours:** 10 PM – 7 AM. Messages sent during this window are scheduled for 7 AM delivery via `chat.scheduleMessage`. All messages (including critical failures) are deferred — there is no bypass.
- **Completion summary:** `parse_backup_log.py` parses the backup log and appends SSD free space, files transferred, S3 stats, and total elapsed time to the success notification.

## Credentials

All credentials stored in 1Password and referenced via `credentials.yml`:

| Section | Keys | Used By |
|---------|------|---------|
| `slack_creds` | `bot_token` | `notify_slack.py` |
| `luks_creds` | `passphrase` | `backup-usb.sh` (unattended SSD unlock) |

`aws_creds` (in `credentials.yml`) is unused/legacy — AWS auth is now cert-based via IAM Roles Anywhere (see AWS Infrastructure above), not resolved from 1Password. Left in place for reference but not read by any script.

- `.env` holds only `OP_SERVICE_ACCOUNT_TOKEN` — AWS auth for both `backup-usb.sh` and `poller.py` is cert-based via IAM Roles Anywhere, not `.env`
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
sudo systemctl start backup-usb.service --no-block
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
.venv/bin/python get_credentials.py --section slack_creds
```

**Test AWS Roles Anywhere credentials:**
```bash
aws_signing_helper credential-process \
    --certificate ~/.config/usb-backup/aws-roles-anywhere/client.crt \
    --private-key ~/.config/usb-backup/aws-roles-anywhere/client.key \
    --trust-anchor-arn arn:aws:rolesanywhere:us-east-2:864899860638:trust-anchor/5b296f8a-2747-4257-99f6-d3c71a533c81 \
    --profile-arn arn:aws:rolesanywhere:us-east-2:864899860638:profile/6e3e4653-dd8e-4062-a59a-f543d89f890a \
    --role-arn arn:aws:iam::864899860638:role/usb-backup-role \
    --session-duration 43200
```

**Mount/unmount SSD manually:**
```bash
./mount-ssd.sh
./umount-ssd.sh
```

## Known Issues / Notes

- `backup-usb.service` runs as `root` (required for cryptsetup/mount). The backup script uses hardcoded `USER_HOME=/home/fewill` since `$HOME` would resolve to `/root`.
- `ConditionPathExists=/dev/disk/by-uuid/6f57da7c-...` is set on the service — if the SSD is not plugged in, systemd skips the run silently (no failed state). `WantedBy=timers.target` ensures the service is only activated by the timer, not at every boot independently.
- `Persistent=true` on the timer means a missed midnight run is caught at next boot — but only runs if the SSD is present (ConditionPathExists guards this).
- rsync exit code 24 ("some files vanished") is treated as success — this is normal for active directories like `.config`.
- `sync` is called before unmounting to flush OS write buffers. On a full backup this can take several minutes.
- The SQS poller authenticates via IAM Roles Anywhere (`AWS_PROFILE=usb-backup`, set in `backup-poller.service`) — same cert-based short-lived session as `backup-usb.sh`, not IAM user keys.
- The Lambda verifies Slack request signatures and decodes base64 body (API Gateway sends base64-encoded bodies).
- LUKS passphrase is passed via `printf '%s'` (not `echo`) to avoid a trailing newline mismatch.
- The SSD is referenced by UUID (`/dev/disk/by-uuid/6f57da7c-...`) rather than `/dev/sda1` to survive USB re-enumeration.
- If the system auto-mounts the SSD before the backup runs (e.g., a desktop session is active), the LUKS mapper will have a different name (e.g., `luks-6f57da7c-...`) and a different mount point. The backup script detects this via `lsblk` and uses whatever mount is active — `BACKUP_DEST` is set dynamically, not hardcoded.
- rclone runs as root (not `sudo -u fewill`) with `--config /home/fewill/.config/rclone/rclone.conf` so it can read root-owned files backed up from `/etc`.
- `backup-usb.service` is `Type=oneshot` — `systemctl start` blocks until completion. Use `--no-block` to return immediately.

## Dependencies

- `credentialsmanager` installed from `../credentialsmanager` (local package)
- `rclone` configured with remote `fw-fw13` pointing to `opn-usb-backup` (env_auth=true)
