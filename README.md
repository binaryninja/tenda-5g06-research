# Tenda 5G06 V1.0 Firmware Research

This repository contains PoCs, notes, and reproduction tooling for research on
Tenda 5G06 V1.0 firmware `V05.06.01.29`.

## Scope

Tested target:

```text
Device:        Tenda 5G06 V1.0
Firmware:      V05.06.01.29 multi TDE01
Archive:       795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip
Product line:  V05.06.01.XX
```

Vendor product page:

```text
https://www.tendacn.com/product/5G06
```

Firmware source:

```text
https://static.tenda.com.cn/document/2026/04/21/ce00116cc4fa4b8ca49bac94950959a6/US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip
```

Checksums:

```text
zip sha256: db00552932228e40d040c1765ec552e65a0da87f60e0dace40c24aa995324903
bin sha256: d27f23d2c31cd7e864429a2a6adaba6a60a71bdcff827c6d5261cb6b2a65030d
zip bytes:  74412042
bin bytes:  74308003
```

The release note bundled by Tenda says the firmware is only applicable to
`5G06`, hardware version `V1.0`, and current firmware must be
`V05.06.01.XX`.

## Repository Layout

```text
docs/       Research notes, findings, validation logs, worklog
pocs/       Standalone Python PoCs
scripts/    Firmware download, extraction, QEMU launch, proxy helpers
tools/      Small analysis helpers
metadata/   Tenda manifest and URL metadata captured during research
repro/      Reproduction notes
```

Firmware blobs, extracted root filesystems, decoded config backups, logs, and
generated PoC output are intentionally excluded.

## Key Findings

The strongest validated issue is **unauthenticated root command execution over
the web management interface** on a password-configured Tenda 5G06 V1.0. Plain
protected routes redirect to login, but the same handlers are reachable without
a session when the request path appends `%00.js`.

Highest impact vector:

```text
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H = 9.8
```

| ID | Severity | Finding | Impact | Details | Primary PoC |
| --- | --- | --- | --- | --- | --- |
| F01 | Critical | ZeroTier auth-bypass RCE | Unauthenticated attacker supplies `zerotier.tar`; firmware extracts it and executes `start_zerotier.sh` as `uid=0(root)`. Full confidentiality, integrity, and availability impact. | [`AUTH_DEEP_DIVE.md`](docs/AUTH_DEEP_DIVE.md), [`ATTACK_SURFACE_DEEP_DIVE.md`](docs/ATTACK_SURFACE_DEEP_DIVE.md), [`POC_RESULTS.md`](docs/POC_RESULTS.md) | [`pocs/poc_zerotier_unauth_rce.py`](pocs/poc_zerotier_unauth_rce.py) |
| F02 | Critical | Generic NUL-suffix web auth bypass | Protected handlers are dispatched without a valid session by appending `%00.js`. This is the primitive behind RCE, config theft, log theft, telnet enablement, ATE enablement, and protected API access. | [`AUTH_DEEP_DIVE.md`](docs/AUTH_DEEP_DIVE.md), [`ROUTE_PROBE_RESULTS.md`](docs/ROUTE_PROBE_RESULTS.md) | [`pocs/poc_auth_bypass_telnet.py`](pocs/poc_auth_bypass_telnet.py), [`pocs/poc_auth_bypass_ate.py`](pocs/poc_auth_bypass_ate.py), [`pocs/poc_auth_bypass_getmodules.py`](pocs/poc_auth_bypass_getmodules.py), [`pocs/poc_auth_bypass_setmodules.py`](pocs/poc_auth_bypass_setmodules.py) |
| F03 | High | Config backup disclosure and offline decode | Unauthenticated download of protected config backup; static AES-128-ECB key allows offline extraction of Wi-Fi PSKs, password hashes, WireGuard key material, CWMP credentials, and network configuration. | [`CONFIG_BACKUP_DEEP_DIVE.md`](docs/CONFIG_BACKUP_DEEP_DIVE.md), [`AUTH_DEEP_DIVE.md`](docs/AUTH_DEEP_DIVE.md) | [`pocs/poc_auth_bypass_download_cfg.py`](pocs/poc_auth_bypass_download_cfg.py), [`tools/decode_tenda_config_backup.sh`](tools/decode_tenda_config_backup.sh) |
| F04 | High | Log archive disclosure | Unauthenticated download of protected log archive. Logs may expose operational state, network identifiers, diagnostics, and sensitive event history. | [`AUTH_DEEP_DIVE.md`](docs/AUTH_DEEP_DIVE.md), [`ROUTE_PROBE_RESULTS.md`](docs/ROUTE_PROBE_RESULTS.md) | [`pocs/poc_auth_bypass_download_log.py`](pocs/poc_auth_bypass_download_log.py) |
| F05 | High | WFA/Sigma command injection | rc.d starts WFA/Sigma test daemons. Direct frames to stock `wfa_dut:8000` can inject shell metacharacters into command handlers; `wfa_ca` is not required if DUT port is reachable. | [`FINDING_R07_WFA_DUT_UNAUTH_RCE.md`](docs/FINDING_R07_WFA_DUT_UNAUTH_RCE.md), [`R07_WFA_COMMAND_INJECTION_POC.md`](docs/R07_WFA_COMMAND_INJECTION_POC.md), [`RCD_BOOT_PROBE_RESULTS.md`](docs/RCD_BOOT_PROBE_RESULTS.md) | [`pocs/poc_wfa_direct_dut_cmd_injection.py`](pocs/poc_wfa_direct_dut_cmd_injection.py), [`pocs/poc_wfa_sta_get_mac_cmd_injection.py`](pocs/poc_wfa_sta_get_mac_cmd_injection.py), [`pocs/poc_wfa_sta_get_ip_config_cmd_injection.py`](pocs/poc_wfa_sta_get_ip_config_cmd_injection.py), [`pocs/poc_wfa_sta_set_ip_config_cmd_injection.py`](pocs/poc_wfa_sta_set_ip_config_cmd_injection.py) |
| F06 | Medium | Session and CSRF weaknesses | Login cookie lacks `HttpOnly`, `Secure`, and `SameSite`; selected state-changing routes accept authenticated requests without a referer. These increase exploitability but are not needed for the unauthenticated RCE chain. | [`AUTH_DEEP_DIVE.md`](docs/AUTH_DEEP_DIVE.md), [`ATTACK_SURFACE_DEEP_DIVE.md`](docs/ATTACK_SURFACE_DEEP_DIVE.md), [`POC_RESULTS.md`](docs/POC_RESULTS.md) | [`pocs/poc_cookie_missing_security_flags.py`](pocs/poc_cookie_missing_security_flags.py), [`pocs/poc_csrf_missing_referer_ate.py`](pocs/poc_csrf_missing_referer_ate.py) |

Configured-state evidence:

```text
GET /goform/zerotier            -> 302 /login.html
GET /goform/zerotier%00.js?...  -> executes supplied script as root

GET /cgi-bin/DownloadCfg        -> 302 /login.html
GET /cgi-bin/DownloadCfg%00.js  -> 200 config backup
```

See the full mapping in
[`docs/FINDINGS_SUMMARY.md`](docs/FINDINGS_SUMMARY.md) and the validation log in
[`docs/POC_RESULTS.md`](docs/POC_RESULTS.md).

For the full chronological research trail, including command history,
intermediate hypotheses, validation notes, and raw reproduction context, see the
detailed worklog:
[`docs/WORKLOG.md`](docs/WORKLOG.md).

## Quick Start

Install Docker and run from the repository root.

```bash
make download-5g06
make verify-firmware
make build
make launch-native
```

The native web UI proxy listens on:

```text
http://127.0.0.1:18080/
```

Complete first-run setup in the UI and set a password. The original validation
used password `Tenda_888888`, which stores:

```text
fbcd4667f4d4f5d27f4b1250fc051126
```

Then run the web PoCs:

```bash
python3 pocs/poc_auth_bypass_download_cfg.py
python3 pocs/poc_zerotier_unauth_rce.py
```

For WFA/rc.d reproduction:

```bash
make launch-rcd
python3 pocs/poc_wfa_direct_dut_cmd_injection.py
```

## Safety Notes

PoCs default to local/private targets and refuse public targets unless
`--allow-nonlocal` is passed. They are intended for a controlled lab running the
emulated firmware container.

Do not commit generated artifacts from real devices. Config backups and decoded
archives can contain Wi-Fi credentials, password hashes, VPN keys, CWMP
credentials, and other secrets.

## Main References

- [docs/WORKLOG.md](docs/WORKLOG.md) - detailed chronological worklog and
  validation trail
- [docs/AUTH_DEEP_DIVE.md](docs/AUTH_DEEP_DIVE.md)
- [docs/CONFIG_BACKUP_DEEP_DIVE.md](docs/CONFIG_BACKUP_DEEP_DIVE.md)
- [docs/POC_RESULTS.md](docs/POC_RESULTS.md)
- [docs/FINDING_R07_WFA_DUT_UNAUTH_RCE.md](docs/FINDING_R07_WFA_DUT_UNAUTH_RCE.md)
