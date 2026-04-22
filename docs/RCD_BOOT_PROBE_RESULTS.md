# rc.d Boot Probe Results

Date: 2026-04-21 local / 2026-04-22 UTC

Target:

- Archive: `downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip`
- Best probe container: `tenda-b104-rcd-procd-20260421_214544`
- Best probe rootfs: `work/rcd-procd-20260421_214544/extracted/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip/rootfs_0`
- Container IP: `172.17.0.6`
- Host ports: none published

## Method

Three boot approaches were tried.

1. Direct `/sbin/procd rcS S boot`
   - Container: `tenda-b104-rcd-probe-20260421_213332`
   - Result: hung immediately after the start marker. No service progress was
     logged. This mode appears unsuitable outside normal PID-1 startup.

2. Bounded `/etc/rc.d/S* boot` walker without ubus/procd
   - Container: `tenda-b104-rcd-walk-20260421_213515`
   - Result: walked the rc.d tree, but most `USE_PROCD=1` services failed with
     `Failed to connect to ubus`. It still proved that `S90wfa_dut` can launch
     a persistent `wfa_dut` listener.

3. Bounded `/etc/rc.d/S* boot` walker with `ubusd` and `procd` prestarted
   - Container: `tenda-b104-rcd-procd-20260421_214544`
   - Setup:

```text
/sbin/ubusd &
/sbin/procd -S -d 2 &
for s in /etc/rc.d/S*; do "$s" boot; done
```

   - Each init script was bounded to 8 seconds so missing board hardware could
     not block the whole pass.
   - This produced the closest result so far: real `ubus service` registration,
     persistent procd-managed daemons, and the stock WFA boot behavior.

## Final Listener State

Final listeners in `tenda-b104-rcd-procd-20260421_214544` after the procd-backed
pass and a manual `wfa_ca` start:

```text
tcp  172.17.0.6:53    LISTEN dnsmasq
udp  172.17.0.6:53            dnsmasq
udp  0.0.0.0:67               dnsmasq
tcp  0.0.0.0:17171    LISTEN atcid
tcp  0.0.0.0:1883     LISTEN mosquitto
tcp6 :::1883          LISTEN mosquitto
tcp  0.0.0.0:8000     LISTEN wfa_dut
tcp  0.0.0.0:9000     LISTEN wfa_ca, manually added after stock boot
udp  0.0.0.0:11112            td_mqtt_ucloud
```

`httpd` and `td_server` both started as processes. `httpd` did not expose
`80/tcp` in this close-to-stock pass because the native LAN-IP/bind shim was not
used.

## Persistent Processes

The procd-backed pass kept a broad set of services running, including:

```text
ubusd
procd
urngd
logd
rpcd
netifd
dnsmasq
odhcpd
crond
collectd
mosquitto
ql_key_controller
ql_powerd
mtk_netagent
adbd_usb
thermal_core
lppe_service
mnld
scd
speech_daemon
libmodem-afe-ctrl-server-bin
audio-ctrl-service
ql_netd
ql_ril_service
auto_event
td_client
td_net_detec
racoonmtc
td_server
td_netctrl
wfa_dut
failover
atci_service
atcid
cpe_control
httpd
log_controld
mipc_submonitor
td_mqtt_ucloud
```

Several board-dependent services either exited quickly or were partially stuck
on missing hardware state. Examples include missing `/dev/block/*`, missing
MediaTek Wi-Fi interfaces such as `ra0`/`rai0`, missing GPIO/sysfs nodes, and
iptables/kernel module failures.

## WFA/Sigma Findings

`S90wfa_dut` ran during the procd-backed rc.d pass:

```text
== START 56 S90wfa_dut ... ==
== END S90wfa_dut rc=1 elapsed=1s ==
run sigama-daemon wfa_dut......
File wfa_dut.c, Line 137: Usage:  /sbin/wfa_dut <command interface> <Local Control Port>
wfa_wmm_thread::begin while loop for each send/rcv before mutex lock
wfa_driver_mtk_sock_int(AF_INET)::  sock = 5.
```

Despite the rc.d script returning non-zero because the second empty-interface
launch prints usage, the first launch remains running:

```text
/sbin/wfa_dut ra0;rai0 8000
0.0.0.0:8000/tcp LISTEN
```

`S92sigma` did not run in the procd-backed pass because `S90wfa_dut` removed the
`S92sigma` symlink before the walker reached it. That confirms the practical
stock boot behavior: `wfa_dut` starts, `sigma` is disabled.

For command probing, `wfa_ca` was manually added after the stock boot:

```text
WFA_ENV_AGENT_IPADDR=172.17.0.6 WFA_ENV_AGENT_PORT=8000 /sbin/wfa_ca br-lan 9000
```

The container-side interfaces had been left administratively down by the boot
scripts, so `lo` and `eth0` were brought back up for local probing. With that
done, benign Sigma CAPI requests to `wfa_ca:9000` worked:

```text
ca_get_version
-> status,RUNNING
-> status,INVALID

sta_get_mac_address,interface,ra0
-> status,RUNNING
-> status,COMPLETE,mac,00:00:00:00:00:00

sta_get_ip_config,interface,ra0
-> status,RUNNING
-> status,COMPLETE,dhcp,1,ip,,mask,,primary-dns,::1,secondary-dns,0
```

This confirms the network command path:

```text
Sigma text command -> wfa_ca:9000 -> wfa_dut:8000 -> WFA handler
```

Follow-up command-injection probing confirmed that this live path reaches shell
commands in `wfa_dut`. Marker payloads in the `interface` value for
`sta_get_mac_address` and `sta_get_ip_config` created files under `/tmp`, and a
short `ip` value payload in `sta_set_ip_config` created `/tmp/x`. Probes against
`sta_verify_ip_connection` and `traffic_send_ping` did not create markers and
instead crashed `wfa_ca` in this harness.

## Limitations

- This is still QEMU user-mode in Docker, not full board emulation.
- `procd` was prestarted manually because `procd rcS S boot` did not progress
  outside normal PID-1 startup.
- Real Wi-Fi, modem, GPIO, USB gadget, block devices, and kernel modules are
  absent.
- Several scripts were timeout-bounded; this preserves boot progress but is not
  identical to an unbounded hardware boot.
- No host ports were published. The listeners are in the Docker container
  namespace unless explicitly accessed through Docker networking.

## Current Running Probe Containers

At the end of this pass, these Tenda containers were left running for follow-up:

```text
tenda-b104-native-httpd
tenda-b104-rcd-probe-20260421_213332
tenda-b104-rcd-walk-20260421_213515
tenda-b104-rcd-procd-20260421_214544
```

The best target for additional rc.d/WFA probing is:

```text
tenda-b104-rcd-procd-20260421_214544
```
