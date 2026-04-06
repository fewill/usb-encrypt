#!/usr/bin/env bash
set -euo pipefail

DEVICE="/dev/sda1"
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

trap 'notify critical "Backup failed. Check: journalctl -u backup-usb.service"' ERR

# --- Mount ---
MOUNTED_BY_US=false

if [ ! -e "$MAPPER_DEV" ]; then
    echo "Fetching LUKS passphrase from 1Password..."
    LUKS_PASSPHRASE=$(sudo -u "$NOTIFY_USER" "$PYTHON" "$REPO_DIR/get_credentials.py" --section luks_creds | grep LUKS_PASSPHRASE | cut -d"'" -f2) || {
        notify critical "Failed to retrieve LUKS passphrase from 1Password."
        exit 1
    }
    echo "Unlocking $DEVICE..."
    printf '%s' "$LUKS_PASSPHRASE" | cryptsetup open --key-file - "$DEVICE" "$MAPPER_NAME" || {
        notify critical "USB not found or failed to unlock. Is it plugged in?"
        exit 1
    }
    unset LUKS_PASSPHRASE
fi

if ! mountpoint -q "$MOUNT_POINT"; then
    echo "Mounting $MAPPER_DEV..."
    mkdir -p "$MOUNT_POINT"
    mount "$MAPPER_DEV" "$MOUNT_POINT"
    MOUNTED_BY_US=true
fi

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

# --- S3 Sync ---
echo "Fetching AWS credentials from 1Password..."
eval $(sudo -u "$NOTIFY_USER" "$PYTHON" "$REPO_DIR/get_credentials.py" --section aws_creds) || {
    notify critical "Failed to retrieve AWS credentials from 1Password."
    exit 1
}
echo "Syncing to S3..."
sudo -u "$NOTIFY_USER" \
    AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
    rclone sync "$BACKUP_DEST" "$S3_REMOTE" --progress
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
echo "S3 sync complete."

# --- Unmount (only if we mounted it) ---
if [ "$MOUNTED_BY_US" = true ]; then
    echo "Flushing buffers..."
    sync
    echo "Unmounting and locking..."
    umount "$MOUNT_POINT"
    cryptsetup close "$MAPPER_NAME"
    echo "Done. Safe to remove SSD."
else
    echo "SSD was already mounted before backup — leaving it mounted."
fi

notify normal "Backup completed successfully (USB + S3)."
