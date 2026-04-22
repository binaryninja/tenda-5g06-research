# Tenda B104 Firmware Attack Surface Deep Dive

Date: 2026-04-22

## Scope

This pass follows the externally reachable web routes into the native code that
handles attacker-controlled data. It focuses on `httpd`, the ubus backend
`td_server`, helper binaries started by hidden routes, and the shell scripts
that parse uploaded VPN/config files.

This pass now includes `radare2 6.1.5` with the `r2dec` plugin. The main
binaries are stripped AArch64 ELF executables, so function names below are
descriptive labels with virtual addresses from the binary.

Current emulated baseline after cleanup:

- `httpd` is the only running process in the native container.
- Listeners are `0.0.0.0:80` and `0.0.0.0:443`.
- `telnetd`, `td_ate`, `td_zerotier`, and `zerotier-one` are not running by
  default.

## Highest-Risk Findings

| Priority | Surface | Status | Why it matters |
| --- | --- | --- | --- |
| Critical | Route-confusion auth bypass | Runtime confirmed | Appending `%00.js` or another whitelisted static suffix to protected routes skips auth but dispatches the NUL-truncated protected handler. Confirmed for telnet, ATE, config download, log download, and `setModules`. |
| Critical | `/goform/zerotier` | r2dec path verified; bypass likely | Web query parameters become a remote `zerotier.tar` URL. The helper downloads it, extracts it under `/var`, then runs `start_zerotier.sh`. On download failure it still attempts to execute the extract/start path against any existing `/var/zerotier.tar`. |
| Critical | `/goform/telnet` | Runtime confirmed unauth via bypass | The route starts `telnetd &`; runtime testing opened `:::23/tcp`. |
| Critical | `/goform/ate` | Runtime confirmed unauth via bypass | The route starts a manufacturing daemon. `td_ate` binds UDP port `7329`, decrypts datagrams, and dispatches a 23-entry command table including reboot, factory default, NVRAM, and shell-backed network commands. |
| Critical | Upload routes | Static code path verified; bypass likely | File uploads are written to fixed privileged paths and handed to config restore, firmware upgrade, OpenVPN, WireGuard, APN, and shell-script parsers. The same auth gate protects these CGI routes. |
| High | OpenVPN client import | Static script review | Imported `.ovpn` content is only partially cleaned. The client service starts OpenVPN with `--script-security 2`, so preserved OpenVPN directives need focused validation. |
| High | WireGuard import | Static code and script review | Uploaded config is parsed into UCI and can drive route/firewall changes, watchdog cron entries, `ifup`, and `wireguard.sh`. |
| Critical | `/cgi-bin/DownloadCfg` and log downloads | Runtime confirmed unauth via bypass | Unauthenticated `%00.js` requests downloaded router config backup and logs. |
| High | Default Wi-Fi and backhaul config | Config verified | `ra0`/`rai0` ship open; hidden `rai2` backhaul uses static PSK `12345678`. |

## Web Router and Auth Gate

Primary binary: `work/test-extract/rootfs_0/usr/sbin/httpd`

Important imports:

- Process execution: `system`, `fork`, `execve`.
- Upload/file handling: `open`, `read`, `write`, `mmap`, `ftruncate`,
  `munmap`.
- Web JSON handling: `cJSON_Parse`, `cJSON_Delete`, cJSON builders.
- Backend bridge: `td_common_get_ubus_info`, `td_common_set_ubus_info`,
  `td_common_send_ubus_msg_info`, `td_common_get_wifi_scan`.
- Console/test controls: `km_console_control`, `td_copy_encry_apn_list_to_default`.

Main request/router/auth function starts at `httpd:0x418378`.

Key behavior:

- The URL is copied to a stack buffer with `strncpy(..., 0xff)` and truncated at
  `?` before route checks.
- Static assets and selected pre-login endpoints bypass the user check.
- The static suffix check happens before dynamic route authorization. A request
  such as `/goform/telnet%00.js` is classified as a static `.js` asset by the
  auth gate, but the dispatcher resolves the decoded C string as
  `/goform/telnet`.
- `/goform/telnet`, `/goform/ate`, and `/goform/zerotier` are checked at
  approximately `0x4186d8` to `0x418718`.
- Runtime probes showed plain unauthenticated hidden-route requests redirect to
  `/login.html`, but `%00.js` suffixes bypass auth and reach the native
  handlers.
- Login handling inside the same function parses JSON from the POST body,
  extracts `username` and `password`, copies username with limit `0xff`, and
  copies password with limit `0x7f`.
- `r2dec` confirmed the same function also handles `/logout/Auth`,
  `/login/Usernum`, `/goform/getModules`, `/goform/setModules`, and the
  pre-auth exceptions for static resources and selected setup/status routes.

Observed login/session details:

- `/login/Auth` expects JSON, not form encoding:
  `{"username":"admin","password":"<md5(password)>"}`.
- Bad form-encoded attempts increment lockout state in `/tmp/loginLockStatus`.
- The session cookie is named `password` and contains the password hash plus a
  suffix.
- `httpd` contains `check_CSRF_attack`. r2dec showed it permits missing
  `Referer` or missing `Host`, so it is weak even for valid sessions. The
  `%00.js` route-confusion bypass does not require a valid session.
- `/goform/setModules` has an explicit pre-auth exception when the POST body
  contains `updateLoginoption`.
- `/goform/getModules` has an explicit pre-auth exception for
  `loginLockStatus`.

## Hidden Telnet Route

Route: `/goform/telnet`

Native handler:

- Route string: `httpd:0x440630`.
- Handler: `httpd:0x4220d8`.
- Code path:
  - Calls a console helper around `0x422048`.
  - The helper references `system.@system[0].console_switch`, `system`, and
    console-open/close status strings.
  - Calls `system("telnetd &")` with string at `httpd:0x4420f0`.
  - Writes `load telnetd success.`.
- `r2dec` decompilation of `httpd:0x4220d8` confirms the handler sequence is:
  `fcn_00422048(1)`, `system("telnetd &")`, then response write.

Runtime result:

- Before route activation: no `telnetd`, no port `23`.
- Authenticated `GET /goform/telnet`: spawned `/usr/sbin/telnetd` and opened
  `:::23/tcp`.
- Unauthenticated `GET /goform/telnet%00.js`: also spawned
  `/usr/sbin/telnetd` and opened `*:23/tcp`.
- Manual `telnet 172.17.0.3 23` reached the firmware BusyBox login prompt:
  `5ec0d2e4ac27 login:`.
- The local proxy reported `BadStatusLine('load telnetd success.')` because
  `httpd` wrote a bare string instead of a normal HTTP response line.
- Emulation note: initial manual telnet attempts accepted TCP and then closed
  because the chroot lacked `/dev/ptmx` and had restrictive `devpts` `ptmx`
  permissions. After adding `dev/ptmx -> pts/ptmx` inside the firmware rootfs
  and remounting `devpts` with `ptmxmode=666`, BusyBox `telnetd` allocated a
  pty and displayed the login prompt. This is a lab runtime issue, not a route
  reachability limitation.

Risk:

- Any path to the management web interface can become shell-service enablement
  when the route-confusion bypass is available.
- The route uses GET and has no user confirmation.
- If CSRF protections are incomplete, a browser session could be enough to open
  telnet on the LAN.

## Hidden ATE Manufacturing Route

Route: `/goform/ate`

Native handler:

- Route string: `httpd:0x440640`.
- Handler: `httpd:0x41f1a8`.
- Code path:
  - `system("killall -9 td_ate")`.
  - `system("td_ate &")`.
  - Writes `load mfg success.`.
- `r2dec` decompilation of `httpd:0x41f1a8` confirms the two direct `system`
  calls followed by the `load mfg success.` response.

Runtime result:

- Authenticated `GET /goform/ate` spawned `/usr/sbin/td_ate`.
- No new TCP listener was observed.

`td_ate` static behavior:

- Binary: `work/test-extract/rootfs_0/usr/sbin/td_ate`.
- Imports `socket`, `setsockopt`, `bind`, `select`, `recvfrom`, `sendto`,
  `AesCbcDecrypt128`, `AesCbcEncrypt128`, `system`, `td_common_popen`.
- Socket setup in `td_ate:0x402f08`:
  - `socket(AF_INET, SOCK_DGRAM, 0)`.
  - `setsockopt(..., SO_REUSEADDR, ...)`.
  - `htons(7329)`.
  - `bind(..., 0.0.0.0:7329)`.
- Receive loop around `td_ate:0x4031a8`:
  - Receives up to `0x1000` bytes from UDP.
  - Decrypts with `AesCbcDecrypt128`.
  - Parses command text and dispatches through a table of roughly `0x17`
    manufacturing commands.
- The command table starts at `td_ate:0x4182d8` and has 23 entries:
  - `Tenda_mfg USB`, `USB3.0`, `WiFiButton`, `ResetButton`, `reboot`,
    `default`, `htmlVersionInfo`, `LanWanInfo`, `SIM`, `SIM2`, `4GModule`,
    `4GIMEI`, `Phone1`, `SimButton`, `TftpDail`, `DailComplete`, `WPSButton`,
    and `PowerkeyButton`.
  - Standalone commands: `ledtest`, `nvram set`, `nvram get`, `iwpriv`, and
    `ifconfig`.
- High-risk native handlers:
  - `reboot` at `td_ate:0x4047c0` calls `td_common_reboot()`.
  - `default` at `td_ate:0x404828` calls `td_common_restore()`.
  - `nvram set` at `td_ate:0x402ad4` parses attacker-controlled `name=value`
    text with multiple `strcpy` calls into stack buffers, then dispatches into
    `ApmibSetValue`/typed NVRAM setters through `td_ate:0x4023c0`.
  - `ifconfig` at `td_ate:0x405180` prepends `ifconfig` to attacker-controlled
    text using `strcpy`, logs the resulting command, and calls `system()` on
    it.

Risk:

- The web route enables a separate manufacturing protocol on UDP `7329`.
- Once enabled, the UDP service is not tied to the web session.
- The command plane includes hardware, modem, Wi-Fi, NVRAM, and reboot/default
  operations.
- `ifconfig` is a concrete shell-command sink after AES-CBC protocol access.
- `nvram set` is both a persistent configuration write surface and a stack
  copying surface.
- The protocol appears encrypted, but the daemon and its command surface still
  belong in the critical inventory because a single web action exposes it.

## ZeroTier Route

Route: `/goform/zerotier`

Native handler:

- Route string: `httpd:0x440650`.
- Handler: `httpd:0x4221f8`.
- Child-launch helper: `httpd:0x422120`.

Attacker-controlled input:

- Query string at request offset `[request + 0xc8]`.
- Requires both `proto=` and `url=` substrings.
- Checks `td_common_get_current_network_status(2)`.
- Extracts `proto` and `url`.
- Accepts/normalizes `ftp`, `ftp://`, `https://`, and HTTP-style input.
- Builds `"%s%s/zerotier.tar"` into a stack buffer.
- Forks and `execve`s `/usr/sbin/td_zerotier` with the constructed URL as an
  argument.
- `r2dec` confirms the child launcher passes environment
  `PATH=/bin:/usr/bin:/usr/sbin` and argv `["td_zerotier", url, NULL]`.

Helper behavior:

- Binary: `work/test-extract/rootfs_0/usr/sbin/td_zerotier`.
- Uses `libcurl`.
- Downloads to `/var/zerotier.tar`.
- `td_zerotier:0x400b20`:
  - Copies argv URL into a local context buffer.
  - Uses curl to fetch remote size.
  - Rejects sizes above `0x500000` bytes.
  - Downloads to `/var/zerotier.tar`.
  - Runs `system("tar -xvf /var/zerotier.tar -C /var")`.
  - Runs
    `system("chmod -R +x /var/zerotier && sh /var/zerotier/start_zerotier.sh &")`.
- The code sets curl options that correspond to disabling HTTPS verification
  for HTTPS URLs. In the HTTPS branch of the downloader at
  `td_zerotier:0x401368`, options `0x51` and `0x40`
  (`CURLOPT_SSL_VERIFYHOST` and `CURLOPT_SSL_VERIFYPEER`) are both set to `0`.
- Important bug: the `curl_easy_perform` failure path still falls through to
  `curl_global_cleanup`, `tar -xvf /var/zerotier.tar -C /var`, and
  `sh /var/zerotier/start_zerotier.sh &`. That makes any stale or attacker-won
  `/var/zerotier.tar` state dangerous even if the current download fails.

Risk:

- Authenticated web input can select a remote archive URL.
- The archive is extracted and a script from it is executed as root.
- HTTPS integrity is weakened by disabled certificate/host verification.
- Download failure does not stop the extract/execute sequence, so cleanup of
  `/var/zerotier.tar` before use is missing.
- This is the most direct code-backed route from web input to remote code
  execution found in this pass. Runtime with no parameters returned
  `invalid zerotier link.` and did not spawn `td_zerotier`; a full positive
  test requires a controlled archive and network state.

## Generic `/goform` Module Bridge

Routes:

- `/goform/getModules`
- `/goform/setModules`
- `/goform/WifiApScan`

Native behavior:

- Route strings at `httpd:0x440768`, `httpd:0x440868`, and `httpd:0x440838`.
- The router forwards module-style UI requests into `td_server` through ubus
  helper APIs.
- `td_server` imports broad mutation primitives: `SetValue`, `SetValueInt`,
  `CfgCommit`, `td_common_set_ubus_info`, `td_common_do_system_cmd`,
  `td_common_popen`, `popen`, JSON parsers, and UCI accessors.

Runtime notes:

- `/goform/getModules?modules=systemStatus` returned `{"errCode":1000}`
  without auth and `{}` for `systemStatus` with auth.
- The benign `POST /goform/setModules` body `{"updateLoginoption":"click"}`
  was accepted without auth and with auth. This only proves that specific
  pre-login action is allowed; it does not prove arbitrary module writes are
  unauthenticated.
- `/goform/WifiApScan` exists, but the minimal probe returned an HTML
  "Form WifiApScan is not defined" response in this emulation.
- `r2dec` of the auth/router function shows:
  - `/goform/getModules` can pass the gate while setup/session state is active.
  - `/goform/getModules` with module `loginLockStatus` is explicitly logged as
    "no check".
  - `/goform/setModules` bypasses the normal redirect path only for request
    bodies containing `updateLoginoption`.
  - `/goform/WifiApScan` has a special-case branch that writes a simple
    `HTTP/1.0 200 OK` response with an `errCode` JSON body before normal form
    dispatch.

Risk:

- The web binary is a broad ubus bridge.
- The dangerous behavior depends on which module methods are reachable after
  auth and whether any pre-login exceptions exist beyond `updateLoginoption`.
- Current native evidence supports two intentional pre-auth module/status
  exceptions, not a blanket unauthenticated `/goform` write primitive.
- The next useful fuzzing target is authenticated module/method enumeration with
  structured logging on `td_common_set_ubus_info`.

## CGI Upload and Download Pipeline

Primary `httpd` functions:

- Multipart body parser: `httpd:0x41be70`.
- File download response helper: `httpd:0x41c2d0`.
- Download dispatcher: `httpd:0x41c3c8`.
- Upload-to-file wrapper: `httpd:0x41c610`.

Multipart parser behavior:

- Uses request content length from `[request + 0x158]`.
- Calls `have_enough_mem(content_len)`.
- Creates/truncates a fixed output file and `mmap`s it.
- Reads request body in `0x800` byte chunks.
- Uses a custom multipart boundary state machine and copies payload bytes into
  the mapped output.
- Error codes include `-4` and `-5` for parser/read/memory failures.
- `r2dec` confirms:
  - `httpd:0x41c610` removes the fixed target path, opens it with mode `0777`,
    truncates it to the request content length, mmaps it, calls the multipart
    parser, truncates to the parsed payload length, and removes the file on
    backend failure.
  - `httpd:0x41be70` implements the multipart state machine and copies bytes
    from HTTP chunks into the mapped output buffer.
  - `httpd:0x41c3c8` streams backend-selected download files back to the HTTP
    client in `0x400` byte chunks.

Route-to-sink map:

| Route | `httpd` file target | Backend sink |
| --- | --- | --- |
| `/cgi-bin/UploadCfg` | `/tmp/RouterCfm.cfg` | `td_server.upload_download.set_cfg_system_upload` |
| `/cgi-bin/DownloadCfg` | streams backend-selected file | `td_server.upload_download.get_cfg_system_backup` |
| `/cgi-bin/DownloadLog` | streams `/tmp/log/syslog.tar` style archive | `td_server.upload_download.get_log_system_export` |
| `/cgi-bin/upgrade` | `/var/image` | `td_server.system_upgrade.set_cfg_system_upgrade` |
| `/cgi-bin/uploadApnList` | `/tmp/en_default_apn.json` | `td_copy_encry_apn_list_to_default`, then `td.cpe.updataDefaultApn` |
| `/cgi-bin/Uploadclient_ovpn` | `/tmp/vpn_client.ovpn` | `td_server.openvpn_client.updateOvpnFile` |
| `/cgi-bin/Uploadca_file` | `/tmp/client_ca.crt` | `td_server.openvpn_client.updateCaFile` |
| `/cgi-bin/UploadWireGuardClientCfg` | `/tmp/wireguard.conf` | `td_server.wireguard.upload_wireguard_cfg` |

Risk:

- This is a high-value parser boundary: HTTP multipart parser, then vendor
  parser or shell script parser, then privileged config/service changes.
- File names are mostly fixed, which reduces direct path-injection risk at the
  HTTP layer.
- File content remains attacker-controlled and reaches privileged parsers.

## Config Backup and Restore

Backend object: `td_server.upload_download`.

Important methods:

- `set_cfg_system_upload`: `td_server:0x410670`.
- `get_cfg_system_backup`: `td_server:0x410d68`.
- `get_log_system_export`: `td_server:0x410e90`.

Key strings:

- `/tmp/RouterCfm.cfg`
- `/tmp/RouterCfm.cfg.bak`
- `sysbackup -b %s %s`
- `sysbackup -r %s %s`
- `td_server.upload_download`

Upload flow:

- Uploaded config lands at `/tmp/RouterCfm.cfg`.
- `td_server` invokes `sysbackup` restore logic and commits multiple UCI
  values.
- Successful restore path calls reboot logic.

Download flow:

- Authenticated `/cgi-bin/DownloadCfg` asks the backend for a generated config
  backup path and streams it back to the client.
- Runtime probing confirmed a binary config backup response.
- Authenticated `/cgi-bin/DownloadLog` returns a log archive.

Risk:

- Config restore is a full-device trust boundary. Any weakness in `sysbackup`
  parsing can become persistent config overwrite or code execution through
  service configuration.
- Config/log download can expose admin hashes, Wi-Fi keys, VPN keys, APNs,
  cloud identifiers, and local diagnostics.

## Firmware Upgrade

Route: `/cgi-bin/upgrade`

Backend method:

- `td_server.system_upgrade.set_cfg_system_upgrade`: `td_server:0x430ca8`.

Attacker-controlled input:

- Uploaded image at `/var/image`.

Code path:

- Parses ubus blob for `upgradeCfg`.
- Calls `td_common_image_del_head`.
- Uses strings `check_fw`, `upgradeCfg`, and `image_decompress_check failed!`.
- Runs system-command helpers on the fixed uploaded image path.

Risk:

- Firmware image parsing is a privileged binary parser surface.
- Direct command injection via filename is not obvious because the path is fixed.
- The main risks are parser memory corruption, signature/check bypass, and
  unsafe upgrade-side effects.

## OpenVPN Uploads

Routes:

- `/cgi-bin/Uploadclient_ovpn`
- `/cgi-bin/Uploadca_file`

HTTP targets:

- `/tmp/vpn_client.ovpn`
- `/tmp/client_ca.crt`

Backend methods:

- `td_server.openvpn_client.updateCaFile`: `td_server:0x42bae8`.
- `td_server.openvpn_client.updateOvpnFile`: `td_server:0x42d908`.

Backend command strings:

- `/usr/sbin/check_ovpn_file.sh 1`
- `/usr/sbin/check_ovpn_file.sh 2`
- `/usr/sbin/parse_ovpn_file.sh 1 &`
- `/usr/sbin/parse_ovpn_file.sh 2 &`
- `/usr/sbin/parse_ovpn_file.sh 3 &`
- `/etc/openvpn/vpn_client.ovpn`
- `/etc/init.d/openvpn_client restart &`

Script review:

- `check_ovpn_file.sh` checks the first and last line of the CA file and
  checks for `remote` and `dev` lines in the `.ovpn`.
- `check_ovpn_file.sh` has a shell-test bug:
  `[ ""$has_ca" -gt 0" ]` is a single non-empty test argument, so that branch
  is effectively always taken.
- `parse_ovpn_file.sh` extracts inline `<ca>`, `<cert>`, `<key>`, `<secret>`,
  `<crl-verify>`, and auth blocks into `/etc/openvpn/*`.
- It removes certificate/key/auth directives, but leaves unrelated OpenVPN
  directives intact.
- `/etc/init.d/openvpn_client` starts OpenVPN with:
  - `--config /etc/openvpn/vpn_client.ovpn`
  - `--script-security 2`
  - `--up /usr/sbin/openvpn_client_route.sh`

Risk:

- Uploaded `.ovpn` content survives into the active OpenVPN config after only
  partial cleaning.
- Because script security is enabled, OpenVPN directives that trigger helper
  scripts or plugin behavior require focused validation.
- Certificate/key material is stored in UCI and files under `/etc/openvpn`,
  increasing sensitive-data exposure through config backup or filesystem reads.

## WireGuard Upload

Route: `/cgi-bin/UploadWireGuardClientCfg`

HTTP target:

- `/tmp/wireguard.conf`

Backend method:

- Registered method name: `td_server.wireguard.upload_wireguard_cfg`.
- Parser/decode path: `td_server:0x4329e8`.

Key strings and behavior:

- Parses `/tmp/wireguard.conf`.
- `r2dec` and disassembly show `ini_gets` lookups against `/tmp/wireguard.conf`
  for `PrivateKey`, `Address`, `DNS`, `MTU`, `PublicKey`, `PresharedKey`,
  `AllowedIPs`, `Endpoint`, and `PersistentKeepalive`.
- Uses `sscanf`, `fscanf`, and UCI setters.
- Runs `wg | grep latest` in status logic.
- Uses `ifup %s &`.
- Uses `wireguard.sh up %d &`.
- Adds/removes a watchdog cron entry:
  `* * * * * /usr/bin/wireguard_watchdog`.
- The parser returns a nested `wireguardClient` result blob on success and
  unlinks `/tmp/wireguard.conf` on parse failures.

Script review:

- `/usr/sbin/wireguard.sh` reads `wireguard.route.allowedIps`.
- It expands allowed IPs into `ip rule` and `ip route` commands.
- It uses `eval "$(ipcalc.sh "$ip")"` for each non-default allowed IP.
- It also manipulates policy routing and hardware NAT marks.

Risk:

- The direct shell-command strings use mostly fixed formats, so a simple command
  injection is not proven from this pass.
- The combination of uploaded `AllowedIPs`, shell word splitting, `ipcalc.sh`,
  and `eval` is still a high-priority validation target.
- Even without injection, a malicious config can alter routing, policy rules,
  DNS, and tunnel behavior after import.

## APN Upload

Route:

- `/cgi-bin/uploadApnList`

HTTP target:

- `/tmp/en_default_apn.json`

Native sink:

- `td_copy_encry_apn_list_to_default`.
- ubus call to `td.cpe` method `updataDefaultApn`.

Risk:

- APN file parsing touches modem connectivity and carrier settings.
- The upload is a privileged JSON/encrypted-list parser surface.

## Wi-Fi Defaults and Backhaul

Config file:

- `work/test-extract/rootfs_0/etc/config/wireless`

Verified defaults:

- `ra0`: `ssid 'Tenda_888888'`, `encryption 'none'`, enabled.
- `rai0`: `ssid 'Tenda_888888_5G'`, `encryption 'none'`, enabled.
- `rai2`: hidden SSID `backhual-5g`, `encryption 'psk-mixed+ccmp'`,
  key `12345678`, enabled.
- Steering config references backhaul `wlan1.2`.

Risk:

- On real hardware before setup, a nearby attacker may be able to join the open
  management WLAN.
- The hidden backhaul is not secret in practice and uses a static weak PSK.
- If the backhaul network bridges management or mesh control traffic, radio
  proximity becomes a management-plane attack path.

## Route Auth Matrix Summary

Detailed request/response results are in `ROUTE_PROBE_RESULTS.md`.

Important runtime outcomes:

- Hidden routes are not running by default.
- Unauthenticated `/goform/telnet`, `/goform/ate`, and `/goform/zerotier`
  redirect to login.
- Unauthenticated `/goform/telnet%00.js` starts telnet.
- Unauthenticated `/goform/ate%00.js` starts `td_ate`.
- Unauthenticated `/cgi-bin/DownloadCfg%00.js` returns the protected config
  backup.
- Unauthenticated `/cgi-bin/DownloadLog%00.js` returns the protected log
  archive.
- Unauthenticated `POST /goform/setModules%00.js` reaches the broad write route
  instead of returning auth-expired.
- Authenticated `/goform/telnet` starts telnet.
- Authenticated `/goform/ate` starts `td_ate`.
- Authenticated `/goform/zerotier` with no query returns
  `invalid zerotier link.` and does not spawn the helper.
- Authenticated config/log downloads return data.
- Upload routes were not destructive-tested with real payloads in this pass.

## Recommended Next Validation

1. Positive-test `/goform/zerotier%00.js` with a controlled benign archive in the
   emulation, while logging `td_zerotier` process creation and `/var` writes.
2. Instrument `td_common_set_ubus_info` and enumerate unauthenticated
   `/goform/setModules%00.js` methods using harmless reads/writes first.
3. Non-destructively test whether upload routes such as
   `/cgi-bin/UploadCfg%00.js` and `/cgi-bin/upgrade%00.js` reach file parsing
   without a session.
4. Verify whether CSRF checks block authenticated GET requests to
   `/goform/telnet`, `/goform/ate`, and `/goform/zerotier` from a browser
   origin mismatch. This is secondary to the unauthenticated bypass.
5. Run parser fuzzing against `httpd:0x41be70` multipart upload handling.
6. Test OpenVPN import with harmless non-certificate directives to determine
   what survives `parse_ovpn_file.sh` and whether OpenVPN executes or rejects it.
7. Test WireGuard import with malformed `AllowedIPs`, `Endpoint`, and key fields
   while monitoring UCI, `ip rule`, `ip route`, cron, and shell errors.
8. Build a small `td_ate` protocol harness only if the AES-CBC key/IV can be
   recovered cleanly, then validate whether the `ifconfig` command handler
   accepts shell metacharacters after decryption.
9. Extract and analyze `sysbackup`, `check_fw`, `ipcalc.sh`, and the ubus common
   libraries because several high-risk paths delegate final parsing there.

## Radare2 Commands Used

Representative commands from this pass:

```text
r2 -q -e scr.color=0 -A -c 's 0x4220d8; af; pdd; q' work/test-extract/rootfs_0/usr/sbin/httpd
r2 -q -e scr.color=0 -A -c 's 0x4221f8; af; pdd; q' work/test-extract/rootfs_0/usr/sbin/httpd
r2 -q -e scr.color=0 -A -c 's 0x400b20; af; pdd; q' work/test-extract/rootfs_0/usr/sbin/td_zerotier
r2 -q -e scr.color=0 -A -c 's 0x402f08; af; pdd; q' work/test-extract/rootfs_0/usr/sbin/td_ate
r2 -q -e scr.color=0 -A -c 's 0x402ad4; af; pdd; q' work/test-extract/rootfs_0/usr/sbin/td_ate
r2 -q -e scr.color=0 -A -c 's 0x405180; af; pdd; q' work/test-extract/rootfs_0/usr/sbin/td_ate
r2 -q -e scr.color=0 -A -c 's 0x4329e8; af; pdd; q' work/test-extract/rootfs_0/usr/sbin/td_server
```
