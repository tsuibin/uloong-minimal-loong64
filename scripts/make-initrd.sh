#!/usr/bin/env bash
# Pack a rootfs directory into a gzip cpio initramfs with a custom /init.
# Usage: KVER=6.6.0-example ./scripts/make-initrd.sh ./work/rootfs ./work/initrd.img
set -euo pipefail

ROOTFS=${1:-./work/rootfs}
INITRD=${2:-./work/initrd.img}
KVER=${KVER:-}
MODULE_DIR=${MODULE_DIR:-/lib/modules/$KVER/kernel}
ASSETS=$(cd "$(dirname "$0")/.." && pwd)/assets

if [ -z "$KVER" ]; then
    echo "ERROR: set KVER to the exact kernel version (uname -r)" >&2
    exit 2
fi
if [ ! -d "$ROOTFS" ]; then
    echo "ERROR: rootfs not found: $ROOTFS" >&2
    exit 2
fi

# Kernel modules must match the kernel exactly. Copy only what you need; the
# QEMU/ virtio set below is enough for the standard virt machine.
if [ -d "$MODULE_DIR" ]; then
    target="$ROOTFS/usr/lib/modules/$KVER/kernel"
    mkdir -p "$target"
    for m in \
        drivers/virtio/virtio_pci_modern_dev.ko \
        drivers/virtio/virtio_pci_legacy_dev.ko \
        drivers/virtio/virtio_pci.ko \
        drivers/virtio/virtio_console.ko; do
        if [ -f "$MODULE_DIR/$m" ]; then
            install -D -m644 "$MODULE_DIR/$m" "$target/$m"
        fi
    done
else
    echo "WARN: module dir not found: $MODULE_DIR (init will skip insmod)"
fi

# Install /init, substituting the kernel version.
sed "s/__KVER__/$KVER/g" "$ASSETS/init" > "$ROOTFS/init"
chmod 755 "$ROOTFS/init"
chmod 600 "$ROOTFS/etc/shadow" 2>/dev/null || true

# -R 0:0 makes every archive entry root-owned; the kernel preserves uid/gid
# when unpacking the initramfs.
mkdir -p "$(dirname "$INITRD")"
( cd "$ROOTFS" && find . -print0 | \
    cpio --null -o -H newc -R 0:0 --quiet | gzip -9 ) > "$INITRD"

echo "[initrd] wrote $INITRD ($(du -h "$INITRD" | cut -f1))"
