#!/usr/bin/env bash
# Boot the image under QEMU's LoongArch virt machine with UEFI firmware.
# Usage: ./scripts/verify-qemu.sh ./work/minimal-uefi.img
set -euo pipefail

IMAGE=${1:?usage: verify-qemu.sh IMAGE}
BIOS=${BIOS:-/usr/share/qemu/edk2-loongarch64-code.fd}

if [ ! -f "$BIOS" ]; then
    echo "ERROR: LoongArch UEFI firmware not found: $BIOS" >&2
    echo "Install your distro's edk2-loongarch64 / qemu-uefi package." >&2
    exit 2
fi

exec qemu-system-loongarch64 \
    -M virt -m 2048 -smp 2 \
    -bios "$BIOS" \
    -drive file="$IMAGE",format=raw \
    -nographic -serial mon:stdio
