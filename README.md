# usb-encrypt

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
| 2 | Encrypted SSD (`/dev/sda1`) | `rsync` → `/media/fewill/Extreme SSD/backups/` |
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
- AWS account with IAM user `usb-backup` (S3 + SQS access)
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

Create `.env` (only the 1Password token is required — all other credentials are resolved via 1Password):
```
OP_SERVICE_ACCOUNT_TOKEN=your_token
AWS_ACCESS_KEY_ID=your_key_id      # needed for poller.py / SQS only
AWS_SECRET_ACCESS_KEY=your_secret
AWS_DEFAULT_REGION=us-east-2
```

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

The timer runs daily at midnight. `Persistent=true` ensures it runs at next boot if the machine was off.

```bash
systemctl list-timers backup-usb.timer
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

All credentials are stored in 1Password and referenced in `credentials.yml`. Resolved at runtime via `get_credentials.py`.

| Section | Credential | Used By |
|---------|-----------|---------|
| `slack_creds` | Slack bot token | `notify_slack.py` |
| `luks_creds` | LUKS passphrase | `backup-usb.sh` (unattended SSD unlock) |
| `aws_creds` | AWS access key, secret, region | `backup-usb.sh` → rclone |

rclone is configured with `env_auth=true` — credentials are injected at runtime from 1Password, not stored in `~/.config/rclone/rclone.conf`.

## AWS Infrastructure

| Resource | Name | Region |
|----------|------|--------|
| S3 bucket | `opn-usb-backup` | us-east-2 |
| SQS queue | `backup-commands` | us-east-2 |
| Lambda | `backup-slack-handler` | us-east-2 |
| API Gateway | `backup-slack-api` | us-east-2 |
| IAM user | `usb-backup` | — |
| IAM role | `backup-lambda-role` | — |

API Gateway endpoint:
```
https://888rs3f9x2.execute-api.us-east-2.amazonaws.com/prod/backup
```
