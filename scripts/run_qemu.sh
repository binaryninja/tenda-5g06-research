#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:-${FIRMWARE_ARCHIVE:-}}"
shift || true

if [[ -z "${ARCHIVE}" ]]; then
  echo "usage: run_qemu.sh <firmware.zip|firmware.bin|rootfs> [command...]" >&2
  exit 2
fi

WORK_ROOT="${WORKDIR:-/work}"
mkdir -p "${WORK_ROOT}"

if [[ -d "${ARCHIVE}" && -x "${ARCHIVE}/bin/sh" ]]; then
  ROOTFS="$(realpath "${ARCHIVE}")"
  ARCH_JSON="{\"rootfs\":\"${ROOTFS}\",\"arch\":\"unknown\"}"
else
  NAME="$(basename "${ARCHIVE}")"
  NAME="${NAME//[^A-Za-z0-9_.-]/_}"
  EXTRACT_DIR="${WORK_ROOT}/extracted/${NAME}"
  ARCH_JSON="$(python3 /opt/tenda-b104/scripts/extract_firmware.py "${ARCHIVE}" --workdir "${EXTRACT_DIR}" --json)"
  ROOTFS="$(printf '%s\n' "${ARCH_JSON}" | jq -r '.rootfs')"
fi

ARCH="$(printf '%s\n' "${ARCH_JSON}" | jq -r '.arch // "unknown"')"
if [[ "${ARCH}" == "unknown" ]]; then
  ARCH="$(python3 - "${ROOTFS}" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, "/opt/tenda-b104/scripts")
from extract_firmware import detect_arch
print(detect_arch(Path(sys.argv[1]))[0])
PY
)"
fi

case "${ARCH}" in
  aarch64) QEMU=/usr/bin/qemu-aarch64-static ;;
  arm) QEMU=/usr/bin/qemu-arm-static ;;
  mips) QEMU=/usr/bin/qemu-mips-static ;;
  mipsel) QEMU=/usr/bin/qemu-mipsel-static ;;
  i386) QEMU=/usr/bin/qemu-i386-static ;;
  x86_64) QEMU= ;;
  *) echo "unsupported or undetected rootfs architecture: ${ARCH}" >&2; exit 1 ;;
esac

register_binfmt() {
  [[ -n "${QEMU}" ]] || return 0
  local name="qemu-${ARCH}"
  local conf="/usr/lib/binfmt.d/${name}.conf"
  [[ -r "${conf}" ]] || return 1
  mkdir -p /proc/sys/fs/binfmt_misc 2>/dev/null || true
  if [[ ! -e /proc/sys/fs/binfmt_misc/register ]]; then
    mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc 2>/dev/null || true
  fi
  [[ -w /proc/sys/fs/binfmt_misc/register ]] || return 1
  if [[ -e "/proc/sys/fs/binfmt_misc/${name}" ]]; then
    return 0
  fi
  cat "${conf}" > /proc/sys/fs/binfmt_misc/register 2>/dev/null || return 1
}

mkdir -p "${ROOTFS}/proc" "${ROOTFS}/sys" "${ROOTFS}/dev" "${ROOTFS}/tmp" "${ROOTFS}/run"
chmod 1777 "${ROOTFS}/tmp" || true

cleanup() {
  umount -l "${ROOTFS}/proc" 2>/dev/null || true
  umount -l "${ROOTFS}/sys" 2>/dev/null || true
  umount -l "${ROOTFS}/dev/pts" 2>/dev/null || true
  umount -l "${ROOTFS}/dev" 2>/dev/null || true
}
trap cleanup EXIT

mountpoint -q "${ROOTFS}/proc" || mount -t proc proc "${ROOTFS}/proc" 2>/dev/null || true
mountpoint -q "${ROOTFS}/sys" || mount -t sysfs sysfs "${ROOTFS}/sys" 2>/dev/null || true
mountpoint -q "${ROOTFS}/dev" || mount -t tmpfs tmpfs "${ROOTFS}/dev" 2>/dev/null || true
mkdir -p "${ROOTFS}/dev/pts"
mountpoint -q "${ROOTFS}/dev/pts" || mount -t devpts devpts "${ROOTFS}/dev/pts" 2>/dev/null || true

mknod -m 666 "${ROOTFS}/dev/null" c 1 3 2>/dev/null || true
mknod -m 666 "${ROOTFS}/dev/zero" c 1 5 2>/dev/null || true
mknod -m 666 "${ROOTFS}/dev/random" c 1 8 2>/dev/null || true
mknod -m 666 "${ROOTFS}/dev/urandom" c 1 9 2>/dev/null || true
mknod -m 666 "${ROOTFS}/dev/tty" c 5 0 2>/dev/null || true

if [[ -n "${QEMU}" ]]; then
  cp "${QEMU}" "${ROOTFS}/$(basename "${QEMU}")"
  if [[ -f /opt/tenda-b104/libtenda-httpd-shim.so ]]; then
    cp /opt/tenda-b104/libtenda-httpd-shim.so "${ROOTFS}/tmp/libtenda-httpd-shim.so"
  fi
  if register_binfmt; then
    CHROOT_CMD=()
  else
    echo "warning: binfmt_misc registration failed; direct qemu mode cannot run child ELF commands from a shell" >&2
    CHROOT_CMD=("/$(basename "${QEMU}")")
  fi
else
  CHROOT_CMD=()
fi

if [[ "$#" -gt 0 ]]; then
  CMD=("$@")
elif [[ -n "${FIRMWARE_CMD:-}" ]]; then
  CMD=("/bin/sh" "-lc" "${FIRMWARE_CMD}")
else
  CMD=("/bin/sh")
fi

echo "rootfs=${ROOTFS}"
echo "arch=${ARCH}"
echo "command=${CMD[*]}"

exec chroot "${ROOTFS}" "${CHROOT_CMD[@]}" "${CMD[@]}"
