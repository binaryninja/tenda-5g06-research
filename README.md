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

- NUL-suffix route confusion bypasses auth for protected web routes.
- `/goform/zerotier%00.js` can fetch, extract, and execute an attacker-supplied
  `zerotier.tar` script as `uid=0(root)`.
- `/cgi-bin/DownloadCfg%00.js` downloads the protected config backup without a
  valid session in the password-configured state.
- The config backup is decryptable offline with a static AES-128-ECB key and
  contains sensitive config material including Wi-Fi keys and password hashes.
- WFA/Sigma test daemons are launched by rc.d and expose command-injection
  paths, including direct raw TLV injection into stock `wfa_dut:8000`.

The strongest validated web finding supports:

```text
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H = 9.8
```

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

- [docs/AUTH_DEEP_DIVE.md](docs/AUTH_DEEP_DIVE.md)
- [docs/CONFIG_BACKUP_DEEP_DIVE.md](docs/CONFIG_BACKUP_DEEP_DIVE.md)
- [docs/POC_RESULTS.md](docs/POC_RESULTS.md)
- [docs/FINDING_R07_WFA_DUT_UNAUTH_RCE.md](docs/FINDING_R07_WFA_DUT_UNAUTH_RCE.md)
- [docs/WORKLOG.md](docs/WORKLOG.md)
