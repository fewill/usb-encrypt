#!/usr/bin/env bash
set -euo pipefail

LUKS_UUID="6f57da7c-0823-47ae-b9d3-cd98c1573dac"
DEVICE="/dev/disk/by-uuid/$LUKS_UUID"
MAPPER_NAME="encrypted_ssd"
MAPPER_DEV="/dev/mapper/$MAPPER_NAME"
MOUNT_POINT="/media/fewill/Extreme SSD"
BACKUP_DEST="$MOUNT_POINT/backups"
USER_HOME="/home/fewill"
NOTIFY_USER="fewill"
S3_REMOTE="fw-fw13:opn-usb-backup"
REPO_DIR="/home/fewill/code/usb-encrypt"
PYTHON="$REPO_DIR/.venv/bin/python"
LOG_DIR="$REPO_DIR/logs"
LOG_FILE="$LOG_DIR/backup-$(date '+%Y-%m-%d_%H-%M-%S').log"

mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG_FILE") 2>&1
find "$LOG_DIR" -name "backup-*.log" -mtime +30 -delete

# Directories to back up
SOURCES=(
    "$USER_HOME/code"
    "$USER_HOME/Documents"
    "$USER_HOME/Pictures"
    "$USER_HOME/Downloads"
    "$USER_HOME/Desktop"
    "$USER_HOME/.ssh"
    "$USER_HOME/.config"
    "$USER_HOME/.local/share"
    "$USER_HOME/.mozilla"
    "$USER_HOME/.zoom"
    "/etc"
)

notify() {
    local urgency="$1"
    local message="$2"
    sudo -u "$NOTIFY_USER" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u $NOTIFY_USER)/bus" \
        notify-send -u "$urgency" "USB Backup" "$message" || true
    sudo -u "$NOTIFY_USER" "$PYTHON" "$REPO_DIR/notify_slack.py" \
        --urgency "$urgency" "$message" || true
}

# A USB re-enumeration (the SSD dropping off the bus and coming back as a new
# device) leaves the old mount listed in /proc/mounts with its backing device
# gone. Every read then returns EIO, but nothing unmounts it — so a probe has
# to actually touch the filesystem, not just check that it is still mounted.
# The probe lives outside "$BACKUP_DEST" so rclone never sees it.
dest_alive() {
    mountpoint -q "$CURRENT_MOUNT" 2>/dev/null \
        && touch "$CURRENT_MOUNT/.backup-alive" 2>/dev/null \
        && rm -f "$CURRENT_MOUNT/.backup-alive" 2>/dev/null
}

require_dest_alive() {
    if ! dest_alive; then
        notify critical "SSD at $CURRENT_MOUNT stopped responding ($1) — it likely dropped off the USB bus. Backup aborted."
        exit 1
    fi
}

trap 'notify critical "Backup failed. Check: journalctl -u backup-usb.service"' ERR

# --- Mount ---
LUKS_OPENED_BY_US=false
MOUNTED_BY_US=false

# Check if the LUKS device is already open under any mapper name
DEVICE_BASENAME=$(basename "$(readlink -f "$DEVICE" 2>/dev/null || echo "$DEVICE")")
ACTIVE_MAPPER=$(lsblk -rno NAME "$DEVICE" 2>/dev/null | grep -v "^${DEVICE_BASENAME}$" | head -1) || true

if [ -z "$ACTIVE_MAPPER" ]; then
    if [ ! -b "$DEVICE" ]; then
        notify critical "SSD not found. Is it plugged in?"
        exit 1
    fi
    echo "Fetching LUKS passphrase from 1Password..."
    LUKS_PASSPHRASE=$(sudo -u "$NOTIFY_USER" "$PYTHON" "$REPO_DIR/get_credentials.py" --section luks_creds | grep LUKS_PASSPHRASE | cut -d"'" -f2) || {
        notify critical "Failed to retrieve LUKS passphrase from 1Password."
        exit 1
    }
    echo "Unlocking $DEVICE..."
    printf '%s' "$LUKS_PASSPHRASE" | cryptsetup open --key-file - "$DEVICE" "$MAPPER_NAME" || {
        notify critical "Failed to unlock SSD. Wrong passphrase?"
        exit 1
    }
    unset LUKS_PASSPHRASE
    ACTIVE_MAPPER="$MAPPER_NAME"
    LUKS_OPENED_BY_US=true
else
    echo "SSD already unlocked as /dev/mapper/$ACTIVE_MAPPER"
fi

ACTIVE_MAPPER_DEV="/dev/mapper/$ACTIVE_MAPPER"

# Find existing mount point or mount it ourselves
CURRENT_MOUNT=$(lsblk -rno MOUNTPOINT "$ACTIVE_MAPPER_DEV" 2>/dev/null | head -1)
if [ -z "$CURRENT_MOUNT" ]; then
    echo "Mounting $ACTIVE_MAPPER_DEV..."
    mkdir -p "$MOUNT_POINT"
    mount "$ACTIVE_MAPPER_DEV" "$MOUNT_POINT"
    CURRENT_MOUNT="$MOUNT_POINT"
    MOUNTED_BY_US=true
else
    echo "SSD already mounted at $CURRENT_MOUNT"
fi

BACKUP_DEST="$CURRENT_MOUNT/backups"

require_dest_alive "before starting"

mkdir -p "$BACKUP_DEST"

# --- Sync ---
echo ""
echo "Starting backup — $(date '+%Y-%m-%d %H:%M:%S')"
echo "----------------------------------------"

for SOURCE in "${SOURCES[@]}"; do
    if [ -e "$SOURCE" ]; then
        echo "Syncing $SOURCE..."
        rsync -ah --delete \
            --exclude='.Trash*' \
            --exclude='Trash' \
            --exclude='.config/1Password/logs' \
            --exclude='.config/Code/User/History' \
            --exclude='.config/Code/Cache' \
            --exclude='.config/Code/CachedData' \
            --exclude='.config/Code/CachedExtensionVSIXs' \
            --exclude='node_modules' \
            --exclude='.local/share/claude' \
            --exclude='.local/share/heroku' \
            --exclude='wcbuild/.pypi' \
            --exclude='.config/google-chrome/Default/Cache' \
            --exclude='.config/google-chrome/Default/GPUCache' \
            --exclude='.config/google-chrome/Default/Code Cache' \
            --exclude='etc/alternatives' \
            --exclude='.zoom/data/com.zoom.ipc*' \
            --exclude='.zoom/data/WebViewHostMgr*' \
            "$SOURCE" "$BACKUP_DEST/" || { rc=$?; [ $rc -eq 24 ] || exit $rc; }
    else
        echo "Skipping $SOURCE (not found)"
    fi
done

echo "----------------------------------------"
echo "Backup complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

require_dest_alive "after rsync, before S3 sync"

# --- S3 Sync ---
# Cert-based auth via IAM Roles Anywhere — no long-lived AWS keys on disk.
# usb-backup-role is scoped to only opn-usb-backup (S3) and backup-commands (SQS).
echo "Fetching AWS credentials via IAM Roles Anywhere..."
AWS_RA_CERT_DIR="/home/fewill/.config/usb-backup/aws-roles-anywhere"
CREDS_JSON=$(/home/fewill/.local/bin/aws_signing_helper credential-process \
    --certificate "$AWS_RA_CERT_DIR/client.crt" \
    --private-key "$AWS_RA_CERT_DIR/client.key" \
    --trust-anchor-arn arn:aws:rolesanywhere:us-east-2:864899860638:trust-anchor/5b296f8a-2747-4257-99f6-d3c71a533c81 \
    --profile-arn arn:aws:rolesanywhere:us-east-2:864899860638:profile/6e3e4653-dd8e-4062-a59a-f543d89f890a \
    --role-arn arn:aws:iam::864899860638:role/usb-backup-role \
    --session-duration 43200) || {
    notify critical "Failed to retrieve AWS credentials via IAM Roles Anywhere."
    exit 1
}
AWS_ACCESS_KEY_ID=$(echo "$CREDS_JSON" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['AccessKeyId'])")
AWS_SECRET_ACCESS_KEY=$(echo "$CREDS_JSON" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['SecretAccessKey'])")
AWS_SESSION_TOKEN=$(echo "$CREDS_JSON" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['SessionToken'])")
echo "Syncing to S3..."
AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
    AWS_DEFAULT_REGION=us-east-2 \
    rclone --config "/home/fewill/.config/rclone/rclone.conf" \
    sync "$BACKUP_DEST" "$S3_REMOTE" --progress -vv &
    # -vv: temporary, to catch the actual HTTP method/pacer detail behind the
    # 2026-09-01 spike to 30,835 "Forbidden" errors in one sync (usually ~1-15k).
    # Remove once a cause is confirmed — this can add hundreds of MB per run.
RCLONE_PID=$!

# Watchdog: the S3 sync walks ~1M objects over several hours. If the SSD drops
# off the bus partway through, rclone reads EIO forever and burns the whole
# retry budget against a dead mount (2026-08-10: 5,240 errors over 10 hours).
# Probe once a minute and kill the sync as soon as the source stops responding.
DEST_DIED=false
while kill -0 "$RCLONE_PID" 2>/dev/null; do
    sleep 60
    kill -0 "$RCLONE_PID" 2>/dev/null || break
    if ! dest_alive; then
        echo "ERROR: SSD at $CURRENT_MOUNT stopped responding — killing S3 sync."
        DEST_DIED=true
        kill -TERM "$RCLONE_PID" 2>/dev/null || true
        sleep 5
        kill -KILL "$RCLONE_PID" 2>/dev/null || true
        break
    fi
done

RCLONE_RC=0
wait "$RCLONE_PID" || RCLONE_RC=$?
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_DEFAULT_REGION

if [ "$DEST_DIED" = true ]; then
    notify critical "SSD dropped off the USB bus during the S3 sync. Local backup to SSD completed; S3 is stale. Re-run once the drive is stable."
    exit 1
fi
if [ "$RCLONE_RC" -ne 0 ]; then
    echo "rclone exited with status $RCLONE_RC"
    exit "$RCLONE_RC"
fi
echo "S3 sync complete."

# --- Unmount (only if we mounted/unlocked it) ---
if [ "$MOUNTED_BY_US" = true ]; then
    echo "Flushing buffers..."
    sync
    echo "Unmounting $CURRENT_MOUNT..."
    umount "$CURRENT_MOUNT"
fi
if [ "$LUKS_OPENED_BY_US" = true ]; then
    echo "Locking SSD..."
    cryptsetup close "$ACTIVE_MAPPER"
    echo "Done. Safe to remove SSD."
fi
if [ "$MOUNTED_BY_US" = false ] && [ "$LUKS_OPENED_BY_US" = false ]; then
    echo "SSD was already mounted before backup — leaving it mounted."
fi

SUMMARY=$(sudo -u "$NOTIFY_USER" "$PYTHON" "$REPO_DIR/parse_backup_log.py" "$LOG_FILE" "$CURRENT_MOUNT" 2>/dev/null || true)
notify normal "Backup completed successfully (USB + S3).${SUMMARY:+
$SUMMARY}"
