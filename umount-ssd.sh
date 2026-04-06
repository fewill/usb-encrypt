#!/usr/bin/env bash
set -euo pipefail

MAPPER_NAME="encrypted_ssd"
MAPPER_DEV="/dev/mapper/$MAPPER_NAME"
MOUNT_POINT="/media/fewill/Extreme SSD"

# Unmount if mounted
if mountpoint -q "$MOUNT_POINT"; then
    echo "Unmounting $MOUNT_POINT..."
    sudo umount "$MOUNT_POINT"
    echo "Unmounted."
else
    echo "Not mounted, skipping unmount."
fi

# Lock if open
if [ -e "$MAPPER_DEV" ]; then
    echo "Locking $MAPPER_NAME..."
    sudo cryptsetup close "$MAPPER_NAME"
    echo "Locked."
else
    echo "Device already locked."
fi
