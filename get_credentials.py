"""
get_credentials.py — Resolve USB backup credentials from 1Password.

Resolves Slack and AWS credentials and writes them to stdout as
shell export statements, suitable for sourcing in bash:

    eval $(python3 get_credentials.py)

Usage:
    python3 get_credentials.py           # export all credentials
    python3 get_credentials.py --section slack_creds
    python3 get_credentials.py --section aws_creds
"""

import asyncio
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from onepassword.client import Client
from credentialsmanager import read_yaml_section, resolve_creds_section

load_dotenv(Path(__file__).parent / ".env")

CREDENTIALS_PATH = Path(__file__).parent / "credentials.yml"

SECTIONS = {
    "slack_creds": {
        "bot_token": "SLACK_BOT_TOKEN",
    },
    "luks_creds": {
        "passphrase": "LUKS_PASSPHRASE",
    },
    "aws_creds": {
        "access_key_id": "AWS_ACCESS_KEY_ID",
        "secret_access_key": "AWS_SECRET_ACCESS_KEY",
        "default_region": "AWS_DEFAULT_REGION",
    },
}


async def resolve_section(section: str, client: Client) -> dict:
    raw = read_yaml_section(section, str(CREDENTIALS_PATH))
    return await resolve_creds_section(raw, client)


async def main(sections: list[str]) -> None:
    op_token = os.environ.get("OP_SERVICE_ACCOUNT_TOKEN")
    if not op_token:
        print("ERROR: OP_SERVICE_ACCOUNT_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)

    client = await Client.authenticate(
        auth=op_token,
        integration_name="USB Backup",
        integration_version="1.0.0",
    )

    for section in sections:
        resolved = await resolve_section(section, client)
        mapping = SECTIONS[section]
        for yaml_key, env_var in mapping.items():
            value = resolved.get(yaml_key, "")
            # Escape single quotes in value for safe shell export
            value = value.replace("'", "'\\''")
            print(f"export {env_var}='{value}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resolve USB backup credentials from 1Password.")
    parser.add_argument(
        "--section",
        choices=list(SECTIONS.keys()),
        help="Resolve a specific section only. Defaults to all sections.",
    )
    args = parser.parse_args()

    sections = [args.section] if args.section else list(SECTIONS.keys())
    asyncio.run(main(sections))
