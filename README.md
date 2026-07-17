# usb-encrypt — daily encrypted backup to LUKS SSD and AWS S3 with Slack slash command control

Encrypted SSD backup system for Linux. Mounts, syncs, and locks a LUKS-encrypted Samsung Extreme SSD with daily automated backups to both SSD and AWS S3. Includes two-way Slack integration via slash commands.

## Architecture

```
Local machine
├── mount-ssd / umount-ssd    — manual mount/unmount scripts for SSD
├── backup-usb                — rsync to SSD + rclone to S3 + Slack notification
├── backup-usb.timer          — systemd timer (daily at midnight)
├── poller.py                 — SQS poller, executes Slack slash commands
└── notify_slack.py           — posts messages to #opn-backup

AWS
├── SQS: backup-commands      — command queue
├── Lambda: backup-slack-handler — receives /backup slash commands
├── API Gateway               — public HTTPS endpoint for Slack
└── S3: opn-usb-backup        — offsite backup destination

Slack
└── /backup [run|status]      — trigger backup or check status
```

## Backup Strategy (3-2-1)

| Copy | Location | Method |
|------|----------|--------|
| 1 | Main machine | Source |
| 2 | Encrypted SSD (by UUID) | `rsync` → `<active_mount>/backups/` |
| 3 | AWS S3 (`opn-usb-backup`, us-east-2) | `rclone sync` |

## Backed Up Directories

- `~/code`
- `~/Documents`
- `~/Pictures`
- `~/Downloads`
- `~/Desktop`
- `~/.ssh`
- `~/.config`
- `~/.local/share`
- `~/.mozilla`
- `~/.zoom`
- `/etc`

**Excluded:** Trash, caches (VSCode, Chrome, 1Password logs), node_modules, Claude app binaries, Heroku CLI, wcbuild/.pypi, /etc/alternatives, Zoom IPC sockets

## Requirements

**System packages:**
- `cryptsetup` — LUKS encryption
- `rsync` — local SSD sync
- `rclone` — S3 sync
- `python3` — scripts and poller
- `notify-send` — desktop notifications (optional)

**Python packages** (installed via `.venv`):
- `boto3` — AWS SQS access
- `slack-sdk` — Slack notifications
- `credentialsmanager` — 1Password credential resolution
- `onepassword-sdk` — 1Password SDK
- `python-dotenv` — `.env` loading
- `pyyaml` — credentials YAML parsing

**Infrastructure:**
- AWS account with IAM role `usb-backup-role` (S3 + SQS access), assumed via IAM Roles Anywhere with a client cert — no long-lived AWS keys
- 1Password service account with `OP_SERVICE_ACCOUNT_TOKEN`
- Slack app with bot token in `#opn-backup`
- LUKS-encrypted SSD partition at `/dev/sda1`

## Installation

```bash
git clone git@github.com:fewill/usb-encrypt.git
cd usb-encrypt
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create `.env` (only the 1Password token is required — LUKS and Slack credentials are resolved via 1Password):
```
OP_SERVICE_ACCOUNT_TOKEN=your_token
```

AWS auth is cert-based (IAM Roles Anywhere), not `.env` keys — place the client cert/key at `~/.config/usb-backup/aws-roles-anywhere/` and add the `usb-backup` profile to `~/.aws/config` (see AWS Infrastructure below).

Add `~/.local/bin` to PATH if needed:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

Install scripts and systemd units:
```bash
.venv/bin/python update-scripts.py
```

Enable services:
```bash
sudo systemctl enable --now backup-usb.timer
sudo systemctl enable --now backup-poller.service
```

## Updating

```bash
git pull && .venv/bin/python update-scripts.py
```

## Manual Usage

```bash
./mount-ssd.sh    # unlock and mount SSD
./umount-ssd.sh   # unmount and lock SSD
backup-usb        # full backup (SSD + S3 + Slack notification)
```

## Slack Commands

In any channel where the bot is present:

| Command | Action |
|---------|--------|
| `/backup run` | Queue a backup immediately |
| `/backup status` | Show last backup result |

Results are posted to `#opn-backup`.

## Scheduling

The timer runs daily at midnight. `Persistent=true` ensures it runs at next boot if the machine was off at midnight.

The service has `ConditionPathExists=/dev/disk/by-uuid/6f57da7c-...` — if the SSD is not plugged in, systemd silently skips the run (no failure). Boot-time runs where the SSD is absent are skipped cleanly rather than erroring.

```bash
systemctl list-timers backup-usb.timer
```

## Notifications

Success and failure notifications are posted to `#opn-backup`. Messages sent between **10 PM and 7 AM** are scheduled for 7 AM delivery via Slack's `chat.scheduleMessage` API — no overnight alerts.

Completion notifications include a summary parsed from the backup log:

```
✅ USB Backup — Backup completed successfully (USB + S3).
• SSD: 12 dirs synced in 7s — 817 GiB free
• S3: 1.1 GiB transferred, 1,629 files uploaded, 969,494 checked, 1,214 deleted
• Total time: 2h54m
```

## Logs

```bash
# File logs (30-day retention)
ls ~/code/usb-encrypt/logs/
cat ~/code/usb-encrypt/logs/backup-YYYY-MM-DD_HH-MM-SS.log

# systemd journal
journalctl -u backup-usb.service -n 50     # last 50 lines of backup log
journalctl -u backup-usb.service -f        # follow backup log live
journalctl -u backup-poller.service -n 50  # last 50 lines of poller log
journalctl -u backup-poller.service -f     # follow poller log live
```

## Credentials

Slack and LUKS credentials are stored in 1Password and referenced in `credentials.yml`, resolved at runtime via `get_credentials.py`.

| Section | Credential | Used By |
|---------|-----------|---------|
| `slack_creds` | Slack bot token | `notify_slack.py` |
| `luks_creds` | LUKS passphrase | `backup-usb.sh` (unattended SSD unlock) |

AWS credentials are **not** in 1Password. `backup-usb.sh` mints a short-lived session via IAM Roles Anywhere (`aws_signing_helper credential-process`, cert at `~/.config/usb-backup/aws-roles-anywhere/`) and exports it as env vars before calling rclone; `poller.py` picks up the same role via `AWS_PROFILE=usb-backup`. rclone is configured with `env_auth=true` — it reads whatever AWS env vars are already set, rather than storing keys in `~/.config/rclone/rclone.conf`.

## AWS Infrastructure

| Resource | Name | Region |
|----------|------|--------|
| S3 bucket | `opn-usb-backup` | us-east-2 |
| SQS queue | `backup-commands` | us-east-2 |
| Lambda | `backup-slack-handler` | us-east-2 |
| API Gateway | `backup-slack-api` | us-east-2 |
| IAM role | `usb-backup-role` | — |
| IAM role | `backup-lambda-role` | — |

`usb-backup-role` is assumed via IAM Roles Anywhere (self-managed CA) — scoped to `opn-usb-backup` (S3) and `backup-commands` (SQS) only, no long-lived keys. Session duration is 12 hours (both the Roles Anywhere profile and the role's `MaxSessionDuration` are set to 43200s) so it comfortably outlasts a full S3 sync, which routinely takes 3–4 hours.

### S3 Versioning & Retention

Versioning is enabled on `opn-usb-backup`. The lifecycle policy for noncurrent versions:

| Phase | Duration | Storage Class |
|-------|----------|---------------|
| Recent | Days 0–30 | Standard |
| Archive | Days 30–2555 | Standard-IA |
| Expiry | After 7 years (2555 days) | Deleted |

A maximum of 3 noncurrent versions are retained per object. This aligns with a 7-year retention standard for financial services (SOX / NACHA).

API Gateway endpoint:
```
https://888rs3f9x2.execute-api.us-east-2.amazonaws.com/prod/backup
```
