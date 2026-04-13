"""
notify_slack.py — Send USB backup status notifications to #backups.

Usage:
    python3 notify_slack.py "Backup completed successfully."
    python3 notify_slack.py "Backup failed." --urgency critical
"""

import asyncio
import os
import sys
import argparse
import logging
from datetime import datetime, time as dtime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dotenv import load_dotenv
from onepassword.client import Client
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from credentialsmanager import read_yaml_section, resolve_creds_section

load_dotenv(Path(__file__).parent / ".env")

_log_path = Path(__file__).parent / "logs" / "usb-backup.log"
_log_path.parent.mkdir(exist_ok=True)
_file_handler = RotatingFileHandler(_log_path, maxBytes=1_000_000, backupCount=5)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter("%(message)s"))
log = logging.getLogger("notify_slack")
log.setLevel(logging.INFO)
log.addHandler(_file_handler)
log.addHandler(_console_handler)

CHANNEL = "#opn-backup"
CREDENTIALS_PATH = Path(__file__).parent / "credentials.yml"

URGENCY_EMOJI = {
    "normal": ":white_check_mark:",
    "critical": ":rotating_light:",
}

# Quiet hours: messages sent between QUIET_START and QUIET_END are scheduled
# for DELIVER_AT instead of sent immediately. Critical messages always send now.
QUIET_START = dtime(22, 0)   # 10:00 PM
QUIET_END   = dtime(7, 0)    # 7:00 AM
DELIVER_AT  = dtime(7, 0)    # 7:00 AM


def next_delivery_time() -> int:
    """Return Unix timestamp for the next 7 AM delivery."""
    now = datetime.now()
    target = now.replace(hour=DELIVER_AT.hour, minute=0, second=0, microsecond=0)
    if now.time() >= DELIVER_AT:
        # Already past 7 AM today — schedule for tomorrow
        from datetime import timedelta
        target += timedelta(days=1)
    return int(target.timestamp())


def in_quiet_hours() -> bool:
    t = datetime.now().time()
    if QUIET_START < QUIET_END:
        return QUIET_START <= t < QUIET_END
    # Overnight window (e.g. 22:00 – 07:00)
    return t >= QUIET_START or t < QUIET_END


async def get_bot_token() -> str:
    op_token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if not op_token:
        raise EnvironmentError("OP_SERVICE_ACCOUNT_TOKEN not set in .env")
    client = await Client.authenticate(
        auth=op_token,
        integration_name="USB Backup",
        integration_version="1.0.0",
    )
    creds = await resolve_creds_section(
        read_yaml_section("slack_creds", str(CREDENTIALS_PATH)), client
    )
    return creds["bot_token"]


def send_message(bot_token: str, text: str) -> None:
    slack = WebClient(token=bot_token)
    try:
        if in_quiet_hours():
            post_at = next_delivery_time()
            resp = slack.chat_scheduleMessage(channel=CHANNEL, text=text, post_at=post_at)
            deliver = datetime.fromtimestamp(post_at).strftime("%H:%M")
            log.info(f"Slack message scheduled for {deliver} (ts={resp['scheduled_message_id']})")
        else:
            resp = slack.chat_postMessage(channel=CHANNEL, text=text)
            log.info(f"Slack message sent to {CHANNEL} (ts={resp['ts']})")
    except SlackApiError as e:
        log.error(f"Slack message failed: {e.response['error']}")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a backup status notification to #backups.")
    parser.add_argument("message", help="Message text")
    parser.add_argument(
        "--urgency",
        choices=["normal", "critical"],
        default="normal",
        help="Notification urgency (default: normal)",
    )
    args = parser.parse_args()

    emoji = URGENCY_EMOJI.get(args.urgency, "")
    text = f"{emoji} *USB Backup* — {args.message}"
    bot_token = asyncio.run(get_bot_token())
    send_message(bot_token, text)


if __name__ == "__main__":
    main()
