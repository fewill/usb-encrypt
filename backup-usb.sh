#!/usr/bin/env bash
set -euo pipefail

DEVICE="/dev/sdc1"
MAPPER_NAME="encrypted_usb"
MAPPER_DEV="/dev/mapper/$MAPPER_NAME"
MOUNT_POINT="/mnt/usb"
BACKUP_DEST="$MOUNT_POINT/backups"
USER_HOME="/home/fewill"

# Directories to back up
SOURCES=(
    "$USER_HOME/code"
    "$USER_HOME/Documents"
    "$USER_HOME/Pictures"
    "$USER_HOME/.ssh"
    "$USER_HOME/.config"
)

# --- Mount ---
MOUNTED_BY_US=false

if [ ! -e "$MAPPER_DEV" ]; then
    echo "Unlocking $DEVICE..."
    cryptsetup open "$DEVICE" "$MAPPER_NAME"
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
