#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${CONTAINER:-tenda-b104-native-httpd}"
ARCHIVE="${FIRMWARE_ARCHIVE:-/firmware/downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip}"
ROOTFS="${ROOTFS:-}"
CONTAINER_ROOTFS="${CONTAINER_ROOTFS:-}"
LINES="${LINES:-80}"
DISCOVERY_INTERVAL="${DISCOVERY_INTERVAL:-2}"
PROXY_LOG="${PROXY_LOG:-$PWD/work/native_webui_proxy.log}"
PROXY_ERR_LOG="${PROXY_ERR_LOG:-$PWD/work/native_webui_proxy.stderr.log}"

ROOTFS_NAME="$(basename "${ARCHIVE}")"
ROOTFS_NAME="${ROOTFS_NAME//[^A-Za-z0-9_.-]/_}"

if [[ -z "${ROOTFS}" ]]; then
  ROOTFS="$PWD/work/extracted/${ROOTFS_NAME}/rootfs_0"
fi

if [[ -z "${CONTAINER_ROOTFS}" ]]; then
  CONTAINER_ROOTFS="/work/extracted/${ROOTFS_NAME}/rootfs_0"
fi

if [[ ! -d "${ROOTFS}" ]]; then
  echo "rootfs not found: ${ROOTFS}" >&2
  echo "start the native environment first: ./scripts/launch_native_httpd.sh" >&2
  exit 1
fi

if ! docker inspect "${CONTAINER}" >/dev/null 2>&1; then
  echo "container not found: ${CONTAINER}" >&2
  echo "start the native environment first: ./scripts/launch_native_httpd.sh" >&2
  exit 1
fi

echo "Container: ${CONTAINER}"
docker ps --filter "name=${CONTAINER}" --format 'Status: {{.Status}}  Ports: {{.Ports}}'
echo "Rootfs: ${ROOTFS}"
echo "Container rootfs: ${CONTAINER_ROOTFS}"
echo
echo "Firmware processes/listeners:"
docker exec "${CONTAINER}" /bin/sh -lc \
  'ps -ef | grep -E "[h]ttpd|[u]busd|[l]ogd|[t]d_server|[n]vram|[n]etifd|[d]nsmasq|[u]httpd"; echo; ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null || true' \
  || true
echo
echo "Existing ubus objects:"
docker exec "${CONTAINER}" chroot "${CONTAINER_ROOTFS}" /bin/sh -lc 'ubus list 2>/dev/null | sort | sed -n "1,120p"' || true
echo
echo "Streaming firmware log files. Press Ctrl-C to stop."
echo

declare -A SEEN=()
TAIL_PIDS=()

cleanup() {
  for pid in "${TAIL_PIDS[@]:-}"; do
    kill "${pid}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

start_tail() {
  local file="$1"
  local rel="${file#${ROOTFS}/}"

  SEEN["${file}"]=1
  echo "==> ${rel} <=="
  tail -n "${LINES}" -F "${file}" 2>/dev/null | sed -u "s|^|[${rel}] |" &
  TAIL_PIDS+=("$!")
}

discover_logs() {
  local dirs=()
  [[ -d "${ROOTFS}/tmp" ]] && dirs+=("${ROOTFS}/tmp")
  [[ -d "${ROOTFS}/var/log" ]] && dirs+=("${ROOTFS}/var/log")
  [[ -d "${ROOTFS}/data" ]] && dirs+=("${ROOTFS}/data")

  [[ "${#dirs[@]}" -gt 0 ]] || return 0

  while IFS= read -r -d '' file; do
    [[ -n "${SEEN[${file}]:-}" ]] && continue
    start_tail "${file}"
  done < <(
    find "${dirs[@]}" -maxdepth 1 -type f \
      \( \
        -name '*.log' -o \
        -name '*.strace' -o \
        -name '*.trace' -o \
        -name '*log*' -o \
        -name 'messages' -o \
        -name 'messages.*' -o \
        -name 'device_logs.txt' -o \
        -name 'loginLockStatus' \
      \) \
      ! -name '*.so' \
      ! -name '*.bin' \
      -print0 2>/dev/null | sort -z
  )

  if [[ -f "${PROXY_LOG}" && -z "${SEEN[${PROXY_LOG}]:-}" ]]; then
    start_tail "${PROXY_LOG}"
  fi
  if [[ -s "${PROXY_ERR_LOG}" && -z "${SEEN[${PROXY_ERR_LOG}]:-}" ]]; then
    start_tail "${PROXY_ERR_LOG}"
  fi
}

while true; do
  discover_logs
  sleep "${DISCOVERY_INTERVAL}"
done
