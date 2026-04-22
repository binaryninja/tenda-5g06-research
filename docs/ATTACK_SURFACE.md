# Tenda 5G06 Firmware Attack Surface and Risk Inventory

Date: 2026-04-21

This inventory covers the extracted B104 sample currently used by the QEMU
user-mode environment:

- Archive: `downloads/795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip`
- Extracted rootfs: `work/test-extract/rootfs_0`
- Running container: `tenda-b104-native-httpd`
- Public emulation URL: `http://127.0.0.1:18080/login.html`

The live emulation is not a full board boot. It runs a narrow native web stack
under QEMU user-mode. The "expected stock boot" inventory below is inferred
from `/etc/inittab`, `/etc/rc.d`, `/etc/init.d`, UCI config, web assets, and
binary strings.

## Firmware Identity

- Product: `5G06V1.0-TDE01`
- Firmware version: `V05.06.01.29`
- SVN version: `949`
- OpenWrt base: `OpenWrt 21.02.7 r16847-f8282da11e`
- Target: `gem6xxx/evb6890v1_600lxx_cpe_emmc`
- Architecture: `aarch64_cortex-a55_neon-vfpv4`
- Build timestamp in `etc/td_version`: `2026-04-07 19:05:18 CST`

Notable component versions from package metadata:

| Component | Version | Notes |
| --- | --- | --- |
| BusyBox | `1.33.2-230417.47736` | Base utilities and login/telnet implementation |
| dnsmasq | `2.85-230417.47736` | LAN DNS/DHCP |
| OpenSSL | `1.1.1t-2` | Used by web, VPN, CWMP, MQTT components |
| curl/libcurl | `8.13.0-230417.47736.1` | Used by cloud/update paths |
| OpenVPN | `2.4.11-1` | Server/client support installed |
| ipsec-tools | `0.8.2-9` | Racoon/IPsec support |
| miniupnpd | `1.9.20150609-1` | Tenda UPnP daemon package |
| Mosquitto library | `2.0.15-1` | Broker binary/config present |
| Dropbear | `2020.81-2` | Package installed, no enabled init script found |

## Boot And Startup Model

Stock boot path:

1. `/etc/inittab` runs `/etc/init.d/rcS S boot`.
2. `rcS` walks `/etc/rc.d/S*`.
3. Most vendor services are `procd` services and respawn as root.

The enabled stock rc.d set includes the following high-value services:

| Area | Enabled services and evidence |
| --- | --- |
| Network core | `network`, `firewall`, `dnsmasq`, `odhcpd`, `rpcd`, `log`, `log2`, `ucitrack` |
| Web/admin | `httpd` (`S99httpd`), dynamic `dhttpd` launcher in `td_server` |
| Vendor control plane | `msgd`, `td_server`, `td_multigrade`, `td_client`, `td_net_detec`, `td_auto_event`, `cpe_control` |
| Cloud/remote management | `td_mqtt_ucloud`, conditional `td_cwmpd`, `td_ddns` |
| Cellular/modem | `ccci_fsd`, `ccci_mdinit`, `ql_ril_service`, `ql_netd`, `ql_powerd`, `atcid`, `atci_service`, `mnld`, `scd`, `lppe_service`, `mtk_agpsd` |
| Wi-Fi/mesh/test | `steerd`, `wfa_dut`, `sigma`, `xmesh.init`, `mesh_lldp.init`, `td_repeater`, `td_wifi_protect` |
| VPN/NAT | `miniupnpd`, `racoon`, `racoonmtc`, `xl2tpd`, `openvpn`, `openvpn_client`, `vpnbypass` |
| Diagnostics/logging | `collectd`, `sysstat`, `mdlogger`, `aee_aed`, `log_controld`, `thermal_core` |

Current emulated launcher subset:

- `/sbin/ubusd`
- `/sbin/logd`
- `/usr/bin/nvram_daemon`, if executable
- `/usr/sbin/td_server`
- `/usr/sbin/httpd`
- Local host proxy `scripts/native_webui_proxy.py`

Live listener check in the container shows only native `httpd`:

| Scope | Listener | Process |
| --- | --- | --- |
| Container | `0.0.0.0:80/tcp` | `/usr/sbin/httpd` |
| Container | `0.0.0.0:443/tcp` | `/usr/sbin/httpd` |
| Host | `127.0.0.1:18080/tcp` | Python proxy to native `httpd` |

The native upstream is not host-published by default. The browser should only
use `127.0.0.1:18080`.

## Network And Service Surface

| Service | Expected exposure | Default state | Risk |
| --- | --- | --- | --- |
| `httpd` | LAN `80/tcp`, `443/tcp`; WAN if remote web is enabled | Enabled | Main privileged web management API |
| `dhttpd` | Captive/error/portal HTTP service | Not rc.d-enabled; started/stopped by `td_server` | Additional HTTP parser and auth implementation |
| `dnsmasq` | LAN DNS `53/tcp,udp`, DHCP `67/udp` | Enabled | DNS/DHCP parser; DNS rebinding protection is disabled in UCI |
| `odhcpd` | IPv6 RA/DHCPv6 | Enabled | IPv6 LAN control plane |
| `mosquitto` | MQTT `1883/tcp`; config has `listener 1883` | Enabled by `S80mosquitto` | Root-run broker with password file |
| `miniupnpd` | LAN UPnP/NAT-PMP/PCP, config port `5000` plus SSDP | Enabled by config | LAN clients can request WAN mappings |
| `cwmpd` | TR-069 connection request `7547/tcp` | UCI disabled, binary/config present | Remote management if enabled |
| `racoon` | IPsec/IKE `500/udp`, `4500/udp`; firewall allows ISAKMP/ESP | Enabled by rc.d | Example tunnels and weak test secrets in config |
| `racoonmtc` | Vendor IPsec helper | Enabled | Additional privileged IPsec control path |
| `openvpn` | Usually `1194/udp` when enabled | Disabled examples present | VPN server/client attack surface if enabled |
| `openvpn_client` | Outbound VPN client, uploaded config | Disabled | Uploaded config parsing and route hooks |
| `xl2tpd` | L2TP `1701/udp` when enabled | Disabled | VPN parser if enabled |
| WireGuard | `wg` interface and peer endpoint port when configured | Empty config | Config/import parser and route scripts |
| `wfa_dut` | Test ports `8000`, `8080`; `wfa_ca` uses `9000` | Enabled by rc.d | Wi-Fi test command/control interface |
| `sigma` | Wi-Fi Alliance test controller | Enabled by rc.d but disabled by `wfa_dut` script | Test command/control interface |
| `atcid`, `atci_service` | Modem/AT command sockets | Enabled by rc.d | AT/diagnostic command execution paths |
| `telnetd` | `23/tcp` if started | Init script disabled, web route can start it | Interactive shell exposure if enabled |
| `adbd_usb` | ADB, firewall explicitly drops `5555/tcp` | Package present | Physical/USB or misconfiguration risk |
| Dropbear SSH | SSH if configured | Package present, no enabled init script found | Latent service if enabled |

## Web Management Surface

Native web server:

- Binary: `/usr/sbin/httpd`
- Init: `/etc/init.d/httpd`
- Runs as root.
- Listens on HTTP and HTTPS.
- Uses `/www` static assets and native handlers.
- Talks to `td_server` and other services over ubus.

Literal routes recovered from `httpd`:

| Route | Purpose/risk |
| --- | --- |
| `/login/Auth`, `/logout/Auth`, `/login/Usernum` | Login/session handling and lockout state |
| `/goform/getModules` | Broad read API for UI modules |
| `/goform/setModules` | Broad write API for UI modules |
| `/goform/WifiApScan` | Wi-Fi scan action |
| `/goform/telnet` | Starts `telnetd &` according to binary strings |
| `/goform/ate` | Manufacturing/test hook |
| `/goform/zerotier` | ZeroTier hook; binary references `/usr/sbin/td_zerotier` |
| `/cgi-bin/upgrade` | Firmware upload/upgrade path |
| `/cgi-bin/UploadCfg` | Router config restore upload |
| `/cgi-bin/DownloadCfg` | Router config backup download |
| `/cgi-bin/DownloadLog`, `/cgi-bin/DownloadSyslog` | Log archive download |
| `/cgi-bin/exportCapture` | Packet capture/export path |
| `/cgi-bin/uploadApnList` | APN list upload |
| `/cgi-bin/Uploadclient_ovpn` | OpenVPN client config upload |
| `/cgi-bin/Uploadca_file` | OpenVPN CA upload |
| `/cgi-bin/UploadWireGuardClientCfg` | WireGuard config upload |

Frontend module names recovered from `/www/js/*.js`:

```text
addStatus advanceStatus algCfg apnListSizeLimit apnListVersion
autoMaintenance bandSearch cellLock clientList countryCode ddnsCfg dmzCfg
failover firewallCfg guestIpCfg imeiCfg internetStatus ipsecList ipsecTunnel
iptvCfg ipv6Enable ipv6Status ipv6StatusEth l2tpvpnClient lanCfg lanv6Cfg
ledCfg localhost loginAuth loginLockStatus macFilter meshAgentList meshCfg
meshClientList meshList meshOnboardStatus meshStatus messageCenter mobileData
netControlList neterrinfo networkIpMask onlineList onlineListNum onlineUpgrade
openVpn openVpnClients openvpnClientCfg parentControlList pinCode portList
powerSave readSimSmsStatus remoteWeb scanNodeList searchCell simInfo simLockBand
simSignal simSignalList simSmsList simStatus simSupportBand simWan smsList
smsPhoneList smsStatus staticIPList staticRouteCfg systemCfg systemLogList
systemStatus systemTime tr069 upnpCfg vpnClient vpnStatus wanCfg wanv6Cfg
wgConnected wifiAdvCfg wifiBasicCfg wifiBf wifiGuest wifiOfdma wifiPower
wifiRelay wifiScan wifiStatus wifiTime wifiWps wireguardClient workMode
```

Backend ubus-style object names in `httpd` and `td_server`:

```text
td_server.advance_alg td_server.advance_ddns td_server.advance_dmz
td_server.advance_firewall td_server.advance_ledcontrol
td_server.advance_macfilter td_server.advance_netcontrol
td_server.advance_portlist td_server.advance_static_route
td_server.advance_tr069 td_server.advance_upnp td_server.login_passwd
td_server.ltenet td_server.network_ipv6 td_server.network_wan
td_server.online_list td_server.openvpn td_server.openvpn_client
td_server.opmode td_server.parental_ctrl td_server.reboot_reset
td_server.status_inf td_server.system_lan td_server.system_log
td_server.system_remote_web td_server.system_static_ip td_server.system_time
td_server.system_upgrade td_server.upload_download td_server.vpn_client
td_server.vpn_ipsec td_server.vpn_ipsec_list td_server.wireguard
td_server.wireless td_server.xmesh_api
```

## Risk Inventory

### R01. Web admin API is the primary privileged attack surface

- Severity: Critical
- Exposure: LAN by default, WAN if remote management is enabled.
- Evidence: `/etc/init.d/httpd`, live `80/443` listeners, routes above.
- Details: `httpd` is root-run, non-PIE, native C, and handles authentication,
  file upload, configuration restore, firmware upgrade, Wi-Fi, SMS, VPN, IPsec,
  and router reboot/reset actions.
- Primary risks: auth bypass, session flaws, memory corruption, command
  injection through module fields, unsafe upload handling, CSRF if cookies are
  not adequately protected.

### R02. File upload and firmware/config restore endpoints can cross trust boundaries

- Severity: Critical
- Exposure: Web authenticated path; impact depends on auth strength.
- Evidence: `/cgi-bin/upgrade`, `/cgi-bin/UploadCfg`,
  `/cgi-bin/Uploadclient_ovpn`, `/cgi-bin/Uploadca_file`,
  `/cgi-bin/UploadWireGuardClientCfg`, `/cgi-bin/uploadApnList`.
- Details: Uploaded data feeds system upgrade, router config restore, APN list
  parsing, OpenVPN parsing, WireGuard parsing, and route/script generation.
- Primary risks: parser memory corruption, path traversal, arbitrary file
  write, command injection, config injection, downgrade/unsigned firmware
  acceptance.

### R03. Hidden telnet and ATE web routes are high-risk backdoor-like controls

- Severity: Critical
- Exposure: Web API. Runtime testing showed unauthenticated requests redirect
  to login, but authenticated requests activate the hidden controls.
- Evidence: `httpd` strings include `/goform/telnet`, `/goform/ate`, and
  `telnetd &`; `/etc/init.d/telnetd` exists but has `START` commented out.
- Details: Telnet is not part of the normal rc.d boot, but the web binary can
  launch it. The telnet daemon uses `/bin/login`.
- Runtime confirmation:
  - Before probing, the emulated image only listened on `80/tcp` and
    `443/tcp`; no `telnetd` or `td_ate` process was running.
  - Unauthenticated `GET /goform/telnet` and `GET /goform/ate` returned
    redirects to `/login.html` and did not start new processes.
  - After JSON login to `/login/Auth`, authenticated `GET /goform/telnet`
    spawned `/usr/sbin/telnetd` and opened `:::23/tcp`; host-side
    `nc -vz 172.17.0.3 23` succeeded over the Docker bridge.
  - Authenticated `GET /goform/ate` spawned `/usr/sbin/td_ate`. In this
    emulation it did not expose a new TCP listener, but it did load a
    persistent manufacturing/test daemon.
  - Both handlers return bare strings such as `load telnetd success.` and
    `load mfg success.` instead of valid HTTP responses, so the local proxy
    records them as upstream `BadStatusLine` errors.
- Primary risks: unauthenticated or weakly authenticated shell enablement,
  manufacturing/test functions reachable in production, and authenticated web
  session compromise becoming an interactive shell or factory-test foothold.

### R04. Stock Wi-Fi defaults are open or weak

- Severity: High
- Exposure: Radio proximity.
- Evidence: `/etc/config/wireless`.
- Details: `ra0` and `rai0` default to `encryption 'none'` with SSIDs
  `Tenda_888888` and `Tenda_888888_5G`. Hidden backhaul `rai2` uses static
  PSK `12345678`.
- Primary risks: local attacker can join management LAN before quick setup;
  static hidden backhaul credential reuse.

### R05. MQTT broker and Tenda cloud control create a second management plane

- Severity: High
- Exposure: Broker on `1883/tcp`; outbound cloud client.
- Evidence: `S80mosquitto`, `/etc/mosquitto/mosquitto.conf`, `td_mqtt_ucloud`.
- Details: Mosquitto config has `listener 1883`, `password_file
  /etc/mosquitto/broker_passwd.conf`, and `user root`. `td_mqtt_ucloud`
  references `dev-cloud.tenda.com.cn`, MQTT publish/subscribe handlers, cloud
  mesh actions, cloud upgrade handlers, and `wget -cO %s %s &`.
- Primary risks: broker credential weakness, unauthorized local MQTT control,
  cloud account or update channel compromise, command injection in upgrade URL
  or file handling paths.

### R06. TR-069/CWMP is present with weak default credentials if enabled

- Severity: High
- Exposure: `7547/tcp` when `cwmp.manage.enable=1`.
- Evidence: `/etc/init.d/td_cwmpd`, `/etc/config/cwmp`, `/etc/cwmp.conf`,
  `/usr/sbin/cwmpd`.
- Details: UCI disables CWMP by default, but the binary and config are present.
  Config includes CPE credentials `hgw/hgw`, ACS credentials `itms/itms`, and
  fallback `cwmp/cwmp` in `/etc/cwmp.conf`.
- Primary risks: WAN-side management takeover if enabled, command/config
  changes through CWMP RPCs, upload/download/reboot/factory reset operations.

### R07. Wi-Fi Alliance/Sigma test daemons are enabled in rc.d

- Severity: High
- Exposure: Test control ports, normally LAN/radio lab side.
- Evidence: `/etc/init.d/wfa_dut`, `/etc/init.d/sigma`, `S90wfa_dut`,
  `S92sigma`, `/sbin/wfa_dut`, `/sbin/wfa_ca`.
- Details: `wfa_dut` has `START=90` and attempts to start `/sbin/wfa_dut`
  on ports `8000` and `8080`, then disables the later `sigma` init script.
  `sigma` has `START=92` and, when manually started or if not disabled, starts
  `wfa_dut` on `8000` plus `wfa_ca` on `9000`. In the current image,
  `/etc/wireless/l1profile.dat` only defines `INDEX0_main_ifname=ra0;rai0`,
  so the second `wfa_dut` invocation may be malformed unless board scripts
  rewrite the wireless profile at runtime.
- Runtime confirmation: a controlled QEMU/chroot launch of `/sbin/wfa_dut lo
  8000` opened `127.0.0.1:8000/tcp`. A controlled launch of `/sbin/wfa_ca lo
  9000` with `WFA_ENV_AGENT_IPADDR=127.0.0.1` and
  `WFA_ENV_AGENT_PORT=8000` opened `0.0.0.0:9000/tcp` and connected back to
  the DUT port. A later procd-backed stock-order `/etc/rc.d/S* boot` walk
  launched `/sbin/wfa_dut ra0;rai0 8000` and left it listening on
  `0.0.0.0:8000/tcp`; `S92sigma` did not run because `S90wfa_dut` removed its
  symlink first. With `wfa_ca` manually added on `9000/tcp`, benign Sigma CAPI
  commands such as `sta_get_mac_address,interface,ra0` and
  `sta_get_ip_config,interface,ra0` reached `wfa_dut` and returned structured
  `status,COMPLETE` responses.
- Live command-injection confirmation: through the procd-backed `rc.d` probe,
  Sigma text commands sent to `wfa_ca:9000` reached the stock-started
  `wfa_dut:8000` and created marker files via shell metacharacters in parsed
  parameters. Confirmed paths include `sta_get_mac_address` `interface`,
  `sta_get_ip_config` `interface`, and `sta_set_ip_config` `ip` with a short
  payload. A follow-up direct binary-TLV probe sent to the stock/default
  `wfa_dut:8000` listener also created `/tmp/direct_8000`, proving `wfa_ca` is
  not required for exploitation.
- Binary evidence: both binaries are stripped AArch64 `EXEC` files. `wfa_dut`
  imports `system`, `popen`, socket APIs, `strcpy`, `sprintf`, and
  `strncat`. Strings show WFA/Sigma handlers for `sta_*`, `traffic_*`, and
  `dev_send_frame`; shell templates using `ifconfig`, `route`, `ping`,
  `wfaping.sh`, `wfaping6.sh`, `iwpriv`, `wpa_cli`, `sed`, `wappctrl`, and
  `/usr/bin/wfa_con`; and a `wfa_cli_cmd`/`wfaStaCliCommand` path controlled
  by `/etc/WfaEndpoint/wfa_cli.txt`.
- Local command allowlist: `/etc/WfaEndpoint/wfa_cli.txt` enables
  `sta_reset_parm` and `dev_send_frame`; `wfa_test_cli` is present but
  commented out. That narrows the obvious generic CLI-exec surface, but the
  enabled WFA handlers still mutate Wi-Fi state and launch shell commands from
  parsed network test parameters.
- Primary risks: unauthenticated test command execution, Wi-Fi configuration
  changes, traffic generation abuse, command injection in test commands.

### R08. AT command services expose modem and platform diagnostics

- Severity: High
- Exposure: Local/control sockets; `17171/tcp` in the procd-backed boot probe.
- Evidence: `/etc/init.d/atcid`, `/etc/init.d/atci_service`, `/usr/bin/atcid`,
  `/usr/bin/atci_service`.
- Details: Strings show `bind`, `listen`, AT command execution, USB AT command
  support, GPIO/LED/LCD/PCIe/eMMC/NAND command handlers, and `popen`/`execv`.
- Runtime note: `AT+GMM` on `17171/tcp` returned `RG600L-EU`. A quick
  semicolon marker probe returned `CME ERROR: 6666` and created no marker;
  strings show a special-character denylist containing ``;|&<>$``.
- Primary risks: modem command injection, platform diagnostic abuse, hardware
  state changes, privilege escalation from local socket access.

### R09. IPsec/racoon appears enabled with example secrets

- Severity: High
- Exposure: WAN `500/udp`, `4500/udp`, ESP/AH if firewall and WAN are live.
- Evidence: `S60racoon`, `S90racoonmtc`, firewall rules allowing ISAKMP/ESP,
  `/etc/config/racoon`.
- Details: The config is marked as an example, but contains enabled sample
  tunnels, `pre_shared_key 'testitnow'`, username `testuser`, and password
  `testW0rD`.
- Primary risks: unintended WAN listener, weak default IPsec credentials,
  parser exposure in `racoon` and Tenda's `racoonmtc`.

### R10. UPnP is enabled and can alter WAN firewall state

- Severity: Medium/High
- Exposure: LAN.
- Evidence: `S94miniupnpd`, `/etc/config/upnpd`.
- Details: UPnP and NAT-PMP are enabled by default. `secure_mode` is enabled,
  but LAN clients can still request mappings within configured ranges.
- Primary risks: LAN malware exposing internal services, firewall state
  manipulation, old miniupnpd parser exposure.

### R11. Remote web and DMZ helpers can intentionally publish services to WAN

- Severity: High when enabled
- Exposure: WAN.
- Evidence: `/bin/firewall.remote_web.user`, `/bin/firewall.dmz.user`,
  `/etc/config/advance`.
- Details: Remote web is disabled by default but maps WAN `advance.remweb.port`
  to LAN `:80`; default remote port is `8888`. DMZ rules DNAT all TCP, UDP, and
  ICMP to a configured LAN host when enabled.
- Primary risks: accidental WAN exposure of web management, broad DNAT from
  weak UI settings, firewall script injection through UCI values.

### R12. DNS/DHCP has relaxed DNS rebinding protection

- Severity: Medium
- Exposure: LAN.
- Evidence: `/etc/config/dhcp` sets `rebind_protection 0`.
- Details: dnsmasq is otherwise scoped to local service, but disabled rebind
  protection can help browser-based attacks against LAN services.
- Primary risks: DNS rebinding into the admin UI or other LAN-only services.

### R13. Credentials, keys, and certificates are embedded in the image

- Severity: High
- Exposure: Static firmware extraction; local compromise.
- Evidence:
  - `/etc/shadow` contains root and guest password hashes.
  - `/www/pem/server.key`, `/www/pem/privkeySrv.pem`, `/www/pem/server.pem`
    are shipped in the web root and executable.
  - `/etc/easy-rsa/pki/private/*.key` contains OpenVPN CA/server/client keys.
  - `/etc/config/cwmp` includes `hgw/hgw` and `itms/itms`.
  - `/etc/mosquitto/broker_passwd.conf` contains an `admin` password hash.
  - `/etc/td_version` includes `FW_PASSWORD`.
- Primary risks: credential reuse, TLS private key extraction, VPN PKI reuse,
  offline cracking of local hashes, weak service defaults.

### R14. Vendor daemons are root-run native C with limited hardening

- Severity: High
- Exposure: Any parser reachable through web, ubus, MQTT, CWMP, WFA, AT, or VPN.
- Evidence: `readelf` on `httpd`, `td_server`, `td_mqtt_ucloud`, `dhttpd`,
  `wfa_dut`, `wfa_ca`, `atci_service`.
- Details: Key vendor daemons are non-PIE `EXEC` binaries. They generally have
  NX stacks and RELRO, but several lack `BIND_NOW`, making RELRO partial. They
  are stripped and run as root.
- Primary risks: memory corruption impact is full device compromise; exploit
  mitigations are weaker than PIE/full RELRO builds.

### R15. `td_server` bridges web input to shell scripts and UCI/system commands

- Severity: High
- Exposure: Web API through `httpd` and ubus.
- Evidence: `td_server` strings reference `td_common_do_system_cmd`,
  `doSystemCmd`, `td_common_popen`, `sysupgrade -T %s`, firewall restarts,
  `openvpn_restart.sh`, `td_server_ipsec.sh`, `wireguard.sh`, and many UCI
  setters.
- Details: `td_server` is the privileged backend for most web modules. It
  writes config, restarts services, generates VPN/IPsec configs, and invokes
  shell scripts.
- Primary risks: shell injection, unsafe UCI value handling, command injection
  through VPN/IPsec/static route/DDNS/remote web fields.

### R16. VPN import paths expand the attack surface

- Severity: Medium/High
- Exposure: Authenticated web upload paths.
- Evidence: `/cgi-bin/Uploadclient_ovpn`, `/cgi-bin/Uploadca_file`,
  `/cgi-bin/UploadWireGuardClientCfg`, `/usr/sbin/parse_ovpn_file.sh`,
  `/usr/sbin/check_ovpn_file.sh`, `/usr/sbin/wireguard.sh`.
- Details: OpenVPN client service runs with `--script-security 2` and a route
  hook; WireGuard import updates UCI and calls route scripts.
- Primary risks: parser bugs, unsafe config directives, route/firewall command
  injection, private key handling failures.

### R17. SMS, USSD, SIM, IMEI, and band-lock pages expose cellular modem controls

- Severity: Medium/High
- Exposure: Web authenticated path; modem backend.
- Evidence: frontend pages `sms*.js`, `IMEI_change.js`, `advMobileData.js`,
  `antennaSettings.js`; modules `smsList`, `smsStatus`, `ussdCmd`, `imeiCfg`,
  `simLockBand`, `searchCell`, `bandSearch`.
- Details: These UI flows call into modem/AT/Quectel services.
- Primary risks: SMS/USSD abuse, modem state changes, APN manipulation,
  command injection in modem-facing parameters.

### R18. ADB/debug artifacts exist even though port 5555 is blocked by default

- Severity: Medium
- Exposure: Physical/USB or misconfiguration.
- Evidence: `/sbin/adbd_usb`, `/etc/firewall.user` drops TCP `5555`.
- Details: The firewall explicitly blocks ADB, which confirms the image
  contains an ADB-related service path.
- Primary risks: accidental enablement, USB attack path, debug mode persistence.

### R19. Local `rpcd`/ubus permissions are broad

- Severity: Medium
- Exposure: Local Unix socket; post-compromise pivot.
- Evidence: `/etc/config/rpcd` grants root and guest read/write `*`.
- Details: `rpcd` listens on `/var/run/ubus/ubus.sock`, not a TCP port by
  default. It becomes important after any web or local code execution.
- Primary risks: privilege retention and lateral movement across router
  subsystems after initial foothold.

### R20. Package age and known-vulnerability backlog need a dedicated CVE pass

- Severity: Medium/High
- Exposure: All network-facing packages.
- Evidence: component versions listed above.
- Details: The image includes OpenWrt 21.02-era packages plus vendor forks.
  `miniupnpd` is based on a 2015-era package, OpenVPN is 2.4.x, dnsmasq is
  2.85, Dropbear is 2020.81, and OpenSSL 1.1.1 is an old branch.
- Primary risks: known CVEs in reachable third-party components, plus vendor
  backports that are difficult to validate without source or package patches.

## Current Emulation Gaps

These items cannot be fully confirmed in the current QEMU user-mode chroot:

- Exact port bindings for all rc.d-enabled daemons under full board boot.
- Firewall zone behavior with real LTE `ccmni`, Ethernet WAN, Wi-Fi, bridge,
  and modem devices.
- Whether WFA/Sigma/AT services bind only to local/control sockets or to
  routable interfaces.
- Whether CWMP remains disabled after first-boot provisioning on hardware.
- Whether firmware upgrade images are signed and how signature checks fail.
- Kernel/driver attack surface for MediaTek Wi-Fi, Quectel modem, NAT offload,
  USB, and cellular interfaces.

## Priority Follow-Up Work

1. Start a fuller rc.d boot in a disposable container and log every successful
   `bind()` with `strace`/QEMU tracing.
2. Build an authenticated web API map by replaying frontend modules through the
   native proxy and logging `goform` payloads.
3. Fuzz `httpd` routes with auth preserved, starting with upload handlers,
   `/goform/setModules`, and hidden `/goform/telnet`/`/goform/ate` routes.
4. Audit `td_server` command construction for UCI values that reach shell
   scripts.
5. Confirm whether `wfa_dut`, `sigma`, `atcid`, and `atci_service` listen on
   routable interfaces on real board boot.
6. Run a CVE/backport review for OpenWrt 21.02.7 packages and Tenda forks.
7. Extract and compare older B104 images for recurring keys, credentials,
   certificates, and route handlers.
