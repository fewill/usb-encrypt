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

trap 'notify critical "Backup failed. Check: journalctl -u backup-usb.service"' ERR

# --- Mount ---
LUKS_OPENED_BY_US=false
MOUNTED_BY_US=false

# Check if the LUKS device is already open under any mapper name
DEVICE_BASENAME=$(basename "$(readlink -f "$DEVICE" 2>/dev/null || echo "$DEVICE")")
ACTIVE_MAPPER=$(lsblk -rno NAME "$DEVICE" 2>/dev/null | grep -v "^${DEVICE_BASENAME}$" | head -1)

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
AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION" \
    rclone --config "/home/fewill/.config/rclone/rclone.conf" \
    sync "$BACKUP_DEST" "$S3_REMOTE" --progress
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION
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
