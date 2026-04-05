"""
poller.py — SQS poller for USB backup slash commands.

Polls the SQS queue for commands sent from Slack via Lambda,
executes them, and posts results back to Slack via notify_slack.py.

Supported commands:
    run    — trigger backup-usb
    status — show last backup result from journalctl
"""

import json
import logging
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import os
from dotenv import load_dotenv
import boto3

load_dotenv(Path(__file__).parent / ".env")

QUEUE_URL = "https://sqs.us-east-2.amazonaws.com/864899860638/backup-commands"
REGION = "us-east-2"
POLL_INTERVAL = 10  # seconds between polls
BACKUP_CMD = "/home/fewill/.local/bin/backup-usb"
REPO_DIR = Path(__file__).parent.resolve()
PYTHON = REPO_DIR / ".venv/bin/python"
NOTIFY = REPO_DIR / "notify_slack.py"

_log_path = REPO_DIR / "logs" / "poller.log"
_log_path.parent.mkdir(exist_ok=True)
_file_handler = RotatingFileHandler(_log_path, maxBytes=1_000_000, backupCount=5)
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log = logging.getLogger("poller")
log.setLevel(logging.INFO)
log.addHandler(_file_handler)
log.addHandler(_console_handler)

sqs = boto3.client("sqs", region_name=REGION)


def notify(message: str, urgency: str = "normal") -> None:
    subprocess.run(
        [str(PYTHON), str(NOTIFY), "--urgency", urgency, message],
        check=False,
    )


def run_backup() -> None:
    log.info("Running backup...")
    notify(":arrows_counterclockwise: Backup started.")
    result = subprocess.run(["sudo", BACKUP_CMD], capture_output=True, text=True)
    if result.returncode == 0:
        log.info("Backup completed successfully.")
        notify("Backup completed successfully (USB + S3).")
    else:
        log.error(f"Backup failed: {result.stderr}")
        notify(f"Backup failed. Error: {result.stderr[-200:]}", urgency="critical")


def get_status() -> None:
    log.info("Fetching backup status...")
    result = subprocess.run(
        ["journalctl", "-u", "backup-usb.service", "-n", "50", "--no-pager", "--output=short"],
        capture_output=True,
        text=True,
    )
    lines = result.stdout.strip().splitlines()

    # Extract only the key summary lines
    keywords = ("Starting backup", "Backup complete", "Syncing to S3", "S3 sync complete",
                 "Done. Safe", "Failed", "failed", "error", "Consumed", "total size")
    summary = [l for l in lines if any(k in l for k in keywords)]

    if not summary:
        output = "No recent backup logs found."
    else:
        output = "\n".join(summary)

    notify(f"Last backup status:\n```{output}```")


def handle(command: str, user: str) -> None:
    log.info(f"Received command '{command}' from @{user}")
    if command == "run":
        run_backup()
    elif command == "status":
        get_status()
    else:
        log.warning(f"Unknown command: {command}")


def poll() -> None:
    log.info("Poller started. Listening for commands...")
    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=10,
            )
            messages = response.get("Messages", [])
            for msg in messages:
                body = json.loads(msg["Body"])
                handle(body.get("command", ""), body.get("user", "unknown"))
                sqs.delete_message(
                    QueueUrl=QUEUE_URL,
                    ReceiptHandle=msg["ReceiptHandle"],
                )
        except Exception as e:
            log.error(f"Poller error: {e}")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    poll()
