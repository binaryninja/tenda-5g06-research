#!/usr/bin/env bash
set -euo pipefail

CONTAINER="${CONTAINER:-tenda-5g06-rcd-procd}"
ARCHIVE="${FIRMWARE_ARCHIVE:-/firmware/downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip}"
SETTLE_SECONDS="${RCD_SETTLE_SECONDS:-45}"
SERVICE_TIMEOUT="${RCD_SERVICE_TIMEOUT:-8}"

docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true

FIRMWARE_CMD=$(cat <<'SH'
set +e
mkdir -p /var/run/ubus /var/log /var/state /var/lock /tmp /tmp/rcd-procd
: > /tmp/rcd-procd/walk.log
: > /tmp/rcd-procd/snapshot.log
ip link set lo up >/tmp/rcd-procd/ip-link-lo.log 2>&1

/sbin/ubusd >/tmp/rcd-procd/ubusd.log 2>&1 &
sleep 1
/sbin/procd -S -d 2 >/tmp/rcd-procd/procd.log 2>&1 &
sleep 2

echo "== preflight ubus $(date) ==" >> /tmp/rcd-procd/walk.log
ubus list >> /tmp/rcd-procd/walk.log 2>&1

idx=0
for s in /etc/rc.d/S*; do
  [ -x "$s" ] || continue
  name=${s##*/}
  idx=$((idx + 1))
  echo "== START $idx $name $(date) ==" | tee -a /tmp/rcd-procd/walk.log
  ( "$s" boot ) >"/tmp/rcd-procd/$name.log" 2>&1 &
  pid=$!
  elapsed=0
  limit=${RCD_SERVICE_TIMEOUT:-8}
  while kill -0 "$pid" 2>/dev/null && [ "$elapsed" -lt "$limit" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "== TIMEOUT $name pid=$pid after ${limit}s ==" | tee -a /tmp/rcd-procd/walk.log
    kill "$pid" 2>/dev/null
    sleep 1
    kill -9 "$pid" 2>/dev/null
  else
    wait "$pid"
    rc=$?
    echo "== END $name rc=$rc elapsed=${elapsed}s ==" | tee -a /tmp/rcd-procd/walk.log
  fi
  tail -n 10 "/tmp/rcd-procd/$name.log" >> /tmp/rcd-procd/walk.log
  echo >> /tmp/rcd-procd/walk.log
done

sleep ${RCD_SETTLE_SECONDS:-45}
{
  echo "== snapshot $(date) =="
  echo "== ps =="; ps w
  echo "== listeners =="; netstat -lntup
  echo "== ubus list =="; ubus list 2>&1
  echo "== timed out =="; grep "== TIMEOUT" /tmp/rcd-procd/walk.log
  echo "== wfa =="; grep -n "S90wfa_dut\|S92sigma\|wfa\|sigma" /tmp/rcd-procd/walk.log
  echo "== walk tail =="; tail -n 260 /tmp/rcd-procd/walk.log
  echo "== procd log =="; sed -n "1,220p" /tmp/rcd-procd/procd.log
  echo "== logs =="; ls -l /tmp/rcd-procd | sed -n "1,280p"
} >/tmp/rcd-procd/snapshot.log 2>&1
cat /tmp/rcd-procd/snapshot.log

while true; do sleep 3600; done
SH
)

docker run -d --name "${CONTAINER}" --privileged \
  -v "$PWD/downloads:/firmware/downloads" \
  -v "$PWD/work:/work" \
  -e "FIRMWARE_ARCHIVE=${ARCHIVE}" \
  -e WORKDIR=/work \
  -e "RCD_SETTLE_SECONDS=${SETTLE_SECONDS}" \
  -e "RCD_SERVICE_TIMEOUT=${SERVICE_TIMEOUT}" \
  -e "FIRMWARE_CMD=${FIRMWARE_CMD}" \
  tenda-b104-qemu:latest >/dev/null

echo "rc.d/procd firmware container: ${CONTAINER}"
echo "archive: ${ARCHIVE}"
echo "snapshot will be printed by: docker logs ${CONTAINER}"
