#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-18080}"
ENABLE_WEBUI_PROXY="${ENABLE_WEBUI_PROXY:-1}"
NATIVE_PORT="${NATIVE_PORT:-$((PORT + 1))}"
EXPOSE_NATIVE_UPSTREAM="${EXPOSE_NATIVE_UPSTREAM:-0}"
ARCHIVE="${FIRMWARE_ARCHIVE:-/firmware/downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip}"
PROXY_PID_FILE="$PWD/work/native_webui_proxy.pid"
PROXY_LOG="$PWD/work/native_webui_proxy.log"
PROXY_ERR_LOG="$PWD/work/native_webui_proxy.stderr.log"

docker rm -f tenda-b104-native-httpd tenda-b104-fw tenda-b104-webui >/dev/null 2>&1 || true
if [[ -f "${PROXY_PID_FILE}" ]]; then
  kill "$(cat "${PROXY_PID_FILE}")" >/dev/null 2>&1 || true
  rm -f "${PROXY_PID_FILE}"
fi

FIRMWARE_CMD=$(cat <<'SH'
set -eu
mkdir -p /var/run/ubus /var/log /var/state /tmp
for log_file in \
  /tmp/httpd.log \
  /tmp/ubusd.log \
  /tmp/logd.log \
  /tmp/nvram_daemon.log \
  /tmp/td_server.log \
  /tmp/httpd.qemu-strace.log \
  /tmp/device_logs.txt \
  /tmp/hideSsid.log \
  /tmp/loginLockStatus \
  /var/log/messages; do
  : > "${log_file}"
done
ip link set lo up 2>/dev/null || true
/sbin/ubusd >/tmp/ubusd.log 2>&1 &
sleep 1
(/sbin/logd >/tmp/logd.log 2>&1 || true) &
([ ! -x /usr/bin/nvram_daemon ] || /usr/bin/nvram_daemon >/tmp/nvram_daemon.log 2>&1 || true) &
([ ! -x /usr/sbin/td_server ] || /usr/sbin/td_server >/tmp/td_server.log 2>&1 || true) &
sleep 1
if [ "${ENABLE_HTTPD_QEMU_STRACE:-0}" = "1" ]; then
  (QEMU_STRACE=1 LD_PRELOAD=/tmp/libtenda-httpd-shim.so /usr/sbin/httpd 2>&1 | tee -a /tmp/httpd.qemu-strace.log >>/tmp/httpd.log) &
else
  LD_PRELOAD=/tmp/libtenda-httpd-shim.so /usr/sbin/httpd >/tmp/httpd.log 2>&1 &
fi
tail -n +1 -f \
  /tmp/httpd.log \
  /tmp/ubusd.log \
  /tmp/logd.log \
  /tmp/nvram_daemon.log \
  /tmp/td_server.log \
  /tmp/httpd.qemu-strace.log \
  /tmp/device_logs.txt \
  /tmp/hideSsid.log \
  /tmp/loginLockStatus \
  /var/log/messages &
while true; do sleep 3600; done
SH
)

DOCKER_PORT_ARGS=()
if [[ "${ENABLE_WEBUI_PROXY}" == "1" ]]; then
  if [[ "${EXPOSE_NATIVE_UPSTREAM}" == "1" ]]; then
    DOCKER_PORT_ARGS=(-p "127.0.0.1:${NATIVE_PORT}:80")
  fi
else
  DOCKER_PORT_ARGS=(-p "127.0.0.1:${PORT}:80")
fi

docker run -d --name tenda-b104-native-httpd --privileged \
  "${DOCKER_PORT_ARGS[@]}" \
  -v "$PWD/downloads:/firmware/downloads" \
  -v "$PWD/work:/work" \
  -e "FIRMWARE_ARCHIVE=${ARCHIVE}" \
  -e "ENABLE_HTTPD_QEMU_STRACE=${ENABLE_HTTPD_QEMU_STRACE:-0}" \
  -e WORKDIR=/work \
  -e "FIRMWARE_CMD=${FIRMWARE_CMD}" \
  tenda-b104-qemu:latest >/dev/null

if [[ "${ENABLE_WEBUI_PROXY}" == "1" ]]; then
  if [[ "${EXPOSE_NATIVE_UPSTREAM}" == "1" ]]; then
    PROXY_UPSTREAM_HOST="127.0.0.1"
    PROXY_UPSTREAM_PORT="${NATIVE_PORT}"
  else
    PROXY_UPSTREAM_HOST="$(docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' tenda-b104-native-httpd)"
    PROXY_UPSTREAM_PORT="80"
  fi
  mkdir -p "$PWD/work"
  : > "${PROXY_LOG}"
  : > "${PROXY_ERR_LOG}"
  setsid python3 "$PWD/scripts/native_webui_proxy.py" \
    --listen-host 127.0.0.1 \
    --listen-port "${PORT}" \
    --upstream-host "${PROXY_UPSTREAM_HOST}" \
    --upstream-port "${PROXY_UPSTREAM_PORT}" \
    --log-file "${PROXY_LOG}" < /dev/null >>"${PROXY_ERR_LOG}" 2>&1 &
  echo "$!" > "${PROXY_PID_FILE}"
fi

READY=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/login.html" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 1
done

echo "Native firmware httpd container: tenda-b104-native-httpd"
echo "URL: http://127.0.0.1:${PORT}/login.html"
if [[ "${ENABLE_WEBUI_PROXY}" == "1" ]]; then
  if [[ "${EXPOSE_NATIVE_UPSTREAM}" == "1" ]]; then
    echo "Native upstream: http://127.0.0.1:${NATIVE_PORT}/login.html"
  else
    echo "Native upstream: ${PROXY_UPSTREAM_HOST}:${PROXY_UPSTREAM_PORT} (not host-published)"
  fi
  echo "Web UI proxy log: ${PROXY_LOG}"
fi
if [[ "${READY}" != 1 ]]; then
  echo "warning: native httpd did not pass the readiness check yet; inspect with docker logs tenda-b104-native-httpd" >&2
fi
