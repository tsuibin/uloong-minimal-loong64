#!/usr/bin/env bash
# Build a FAT32 UEFI image with the standard fallback boot path.
# Usage: ./scripts/make-uefi-image.sh out.img /boot/vmlinuz-X work/initrd.img \
#            path/to/BOOTLOONGARCH64.EFI [assets/grub.cfg]
set -euo pipefail

IMAGE=${1:?usage: make-uefi-image.sh IMAGE VMLINUZ INITRD GRUB_EFI [GRUB_CFG]}
VMLINUZ=${2:?missing vmlinuz}
INITRD=${3:?missing initrd.img}
GRUB_EFI=${4:?missing BOOTLOONGARCH64.EFI}
GRUB_CFG=${5:-$(cd "$(dirname "$0")/.." && pwd)/assets/grub.cfg}
SIZE=${SIZE:-192M}

for t in mformat mmd mcopy; do
    command -v "$t" >/dev/null || { echo "ERROR: mtools ($t) not installed" >&2; exit 2; }
done
for f in "$VMLINUZ" "$INITRD" "$GRUB_EFI" "$GRUB_CFG"; do
    [ -f "$f" ] || { echo "ERROR: file not found: $f" >&2; exit 2; }
done

rm -f "$IMAGE"
truncate -s "$SIZE" "$IMAGE"
mformat -i "$IMAGE" -F -v LOONG64_MIN ::
mmd -i "$IMAGE" ::/EFI ::/EFI/BOOT ::/boot-assets
mcopy -i "$IMAGE" -o "$GRUB_EFI" ::/EFI/BOOT/BOOTLOONGARCH64.EFI
mcopy -i "$IMAGE" -o "$GRUB_CFG" ::/EFI/BOOT/grub.cfg
mcopy -i "$IMAGE" -o "$VMLINUZ" ::/boot-assets/vmlinuz
mcopy -i "$IMAGE" -o "$INITRD" ::/boot-assets/initrd.img

echo "[image] wrote $IMAGE ($(du -h "$IMAGE" | cut -f1))"
echo "[image] UEFI fallback: EFI/BOOT/BOOTLOONGARCH64.EFI"
