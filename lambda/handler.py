"""
handler.py — Slack slash command receiver for USB backup control.

Validates Slack request signatures, parses slash commands,
and enqueues them to SQS for the laptop poller to execute.

Supported commands:
    /backup run    — trigger a backup
    /backup status — show last backup status
"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import boto3

SQS_QUEUE_URL = os.environ["SQS_QUEUE_URL"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]

sqs = boto3.client("sqs", region_name="us-east-2")

VALID_COMMANDS = {"run", "status"}


def verify_slack_signature(headers: dict, body: str) -> bool:
    timestamp = headers.get("x-slack-request-timestamp", "")
    slack_signature = headers.get("x-slack-signature", "")

    if not timestamp or not slack_signature:
        return False

    # Reject requests older than 5 minutes
    if abs(time.time() - int(timestamp)) > 300:
        return False

    sig_basestring = f"v0:{timestamp}:{body}"
    expected = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, slack_signature)


def lambda_handler(event, context):
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")

    if not verify_slack_signature(headers, body):
        return {"statusCode": 403, "body": "Invalid signature"}

    params = dict(urllib.parse.parse_qsl(body))
    text = params.get("text", "").strip().lower()
    user_name = params.get("user_name", "unknown")

    if text not in VALID_COMMANDS:
        return {
            "statusCode": 200,
            "body": json.dumps({
                "response_type": "ephemeral",
                "text": f"Unknown command `{text}`. Valid commands: `run`, `status`.",
            }),
            "headers": {"Content-Type": "application/json"},
        }

    sqs.send_message(
        QueueUrl=SQS_QUEUE_URL,
        MessageBody=json.dumps({"command": text, "user": user_name}),
    )

    messages = {
        "run": ":arrows_counterclockwise: Backup queued. You'll get a notification when it completes.",
        "status": ":mag: Fetching backup status...",
    }

    return {
        "statusCode": 200,
        "body": json.dumps({
            "response_type": "in_channel",
            "text": messages[text],
        }),
        "headers": {"Content-Type": "application/json"},
    }
