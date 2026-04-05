#!/usr/bin/env bash
set -euo pipefail

DEVICE="/dev/sdc1"
MAPPER_NAME="encrypted_usb"
MAPPER_DEV="/dev/mapper/$MAPPER_NAME"
MOUNT_POINT="/mnt/usb"
BACKUP_DEST="$MOUNT_POINT/backups"
USER_HOME="/home/fewill"
NOTIFY_USER="fewill"
S3_REMOTE="s3-backup:opn-usb-backup"
REPO_DIR="/home/fewill/code/usb-encrypt"
PYTHON="$REPO_DIR/.venv/bin/python"

# Directories to back up
SOURCES=(
    "$USER_HOME/code"
    "$USER_HOME/Documents"
    "$USER_HOME/Pictures"
    "$USER_HOME/.ssh"
    "$USER_HOME/.config"
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
    echo "Unlocking $DEVICE..."
    cryptsetup open "$DEVICE" "$MAPPER_NAME" || {
        notify critical "USB not found or failed to unlock. Is it plugged in?"
        exit 1
    }
fi

if ! mountpoint -q "$MOUNT_POINT"; then
    echo "Mounting $MAPPER_DEV..."
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
        rsync -avh --delete "$SOURCE" "$BACKUP_DEST/" || [ $? -eq 24 ]
    else
        echo "Skipping $SOURCE (not found)"
    fi
done

echo "----------------------------------------"
echo "Backup complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# --- Unmount (only if we mounted it) ---
if [ "$MOUNTED_BY_US" = true ]; then
    echo "Flushing buffers..."
    sync
    echo "Unmounting and locking..."
    umount "$MOUNT_POINT"
    cryptsetup close "$MAPPER_NAME"
    echo "Done. Safe to remove USB."
else
    echo "USB was already mounted before backup — leaving it mounted."
fi

# --- S3 Sync ---
echo "Syncing to S3..."
sudo -u "$NOTIFY_USER" rclone sync "$BACKUP_DEST" "$S3_REMOTE" --progress
echo "S3 sync complete."

notify normal "Backup completed successfully (USB + S3)."
