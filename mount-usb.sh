#!/usr/bin/env bash
set -euo pipefail

DEVICE="/dev/sdc1"
MAPPER_NAME="encrypted_usb"
MAPPER_DEV="/dev/mapper/$MAPPER_NAME"
MOUNT_POINT="/mnt/usb"

# Unlock if not already open
if [ ! -e "$MAPPER_DEV" ]; then
    echo "Unlocking $DEVICE..."
    sudo cryptsetup open "$DEVICE" "$MAPPER_NAME"
else
    echo "Device already unlocked."
fi

# Mount if not already mounted
if ! mountpoint -q "$MOUNT_POINT"; then
    echo "Mounting $MAPPER_DEV to $MOUNT_POINT..."
    sudo mount "$MAPPER_DEV" "$MOUNT_POINT"
    echo "Mounted successfully."
else
    echo "Already mounted at $MOUNT_POINT."
fi
