# usb-encrypt

Encrypted USB drive backup system for Linux. Mounts, syncs, and locks a LUKS-encrypted USB drive with daily automated backups to both USB and AWS S3. Includes two-way Slack integration via slash commands.

## Architecture

```
Local machine
├── mount-usb / umount-usb    — manual mount/unmount scripts
├── backup-usb                — rsync to USB + rclone to S3 + Slack notification
├── backup-usb.timer          — systemd timer (daily at midnight)
├── poller.py                 — SQS poller, executes Slack slash commands
└── notify_slack.py           — posts messages to #opn-backup

AWS
├── SQS: backup-commands      — command queue
├── Lambda: backup-slack-handler — receives /backup slash commands
└── API Gateway               — public HTTPS endpoint for Slack
└── S3: opn-usb-backup        — offsite backup destination

Slack
└── /backup [run|status]      — trigger backup or check status
```

## Backup Strategy (3-2-1)

| Copy | Location | Method |
|------|----------|--------|
| 1 | Main machine | Source |
| 2 | Encrypted USB (`/dev/sdc1`) | `rsync` → `/mnt/usb/backups/` |
| 3 | AWS S3 (`opn-usb-backup`, us-east-2) | `rclone sync` |

## Backed Up Directories

- `~/code`
- `~/Documents`
- `~/Pictures`
- `~/.ssh`
- `~/.config`

## Requirements

**System packages:**
- `cryptsetup` — LUKS encryption
- `rsync` — local USB sync
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
- LUKS-encrypted USB partition at `/dev/sdc1`
- Mount point: `sudo mkdir -p /mnt/usb`

## Installation

```bash
git clone git@github.com:fewill/usb-encrypt.git
cd usb-encrypt
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create `.env`:
```
OP_SERVICE_ACCOUNT_TOKEN=your_token
AWS_ACCESS_KEY_ID=your_key_id
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

Update specific targets:
```bash
.venv/bin/python update-scripts.py mount-usb umount-usb backup-usb
.venv/bin/python update-scripts.py backup-usb.service backup-usb.timer backup-poller.service
```

List all targets:
```bash
.venv/bin/python update-scripts.py --list
```

## Manual Usage

```bash
mount-usb       # unlock and mount
umount-usb      # unmount and lock
backup-usb      # full backup (USB + S3 + Slack notification)
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
journalctl -u backup-usb.service -n 50     # last 50 lines of backup log
journalctl -u backup-usb.service -f        # follow backup log live
journalctl -u backup-poller.service -n 50  # last 50 lines of poller log
journalctl -u backup-poller.service -f     # follow poller log live
```

## Credentials

Credentials are stored in 1Password and referenced in `credentials.yml`. Resolved at runtime via `get_credentials.py`.

| Credential | 1Password Item | Used By |
|-----------|---------------|---------|
| Slack bot token | `USB Backup / slack_bot_token` | `notify_slack.py` |
| AWS keys | `.env` file | `poller.py`, `rclone` |
| 1Password token | `.env` file | `get_credentials.py` |

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
