#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-18080}"
ARCHIVE="${FIRMWARE_ARCHIVE:-/firmware/downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip}"
ROOTFS_NAME="$(basename "${ARCHIVE}")"
ROOTFS_NAME="${ROOTFS_NAME//[^A-Za-z0-9_.-]/_}"
ROOTFS="/work/extracted/${ROOTFS_NAME}/rootfs_0"
WWW="${ROOTFS}/www"
HOST_WWW="$PWD/work/extracted/${ROOTFS_NAME}/rootfs_0/www"

docker rm -f tenda-b104-fw tenda-b104-webui >/dev/null 2>&1 || true

docker run -d --name tenda-b104-fw --privileged \
  -v "$PWD/downloads:/firmware/downloads" \
  -v "$PWD/work:/work" \
  -e "FIRMWARE_ARCHIVE=${ARCHIVE}" \
  -e WORKDIR=/work \
  -e "FIRMWARE_CMD=mkdir -p /var/run/ubus /var/log /tmp; /sbin/ubusd >/tmp/ubusd.log 2>&1 & /sbin/logd >/tmp/logd.log 2>&1 & /usr/bin/nvram_daemon >/tmp/nvram_daemon.log 2>&1 & /usr/sbin/td_server >/tmp/td_server.log 2>&1 & while true; do sleep 3600; done" \
  tenda-b104-qemu:latest >/dev/null

for _ in $(seq 1 120); do
  [[ -f "${HOST_WWW}/login.html" ]] && break
  sleep 1
done

if [[ ! -f "${HOST_WWW}/login.html" ]]; then
  echo "timed out waiting for extracted web UI at ${HOST_WWW}" >&2
  exit 1
fi

docker run -d --name tenda-b104-webui \
  -p "127.0.0.1:${PORT}:18080" \
  -v "$PWD/work:/work:ro" \
  -v "$PWD/scripts:/opt/tenda-b104/scripts:ro" \
  --entrypoint python3 \
  tenda-b104-qemu:latest \
  /opt/tenda-b104/scripts/webui_compat_server.py \
  --www "${WWW}" \
  --host 0.0.0.0 \
  --port 18080 >/dev/null

echo "Firmware userspace container: tenda-b104-fw"
echo "Web UI compatibility container: tenda-b104-webui"
echo "URL: http://127.0.0.1:${PORT}/login.html"
