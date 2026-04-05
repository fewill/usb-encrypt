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
