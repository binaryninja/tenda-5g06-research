# Standalone PoC Validation Results

Date: 2026-04-22

All scripts live under `pocs/` and use only the Python standard library.
Scripts refuse public targets unless `--allow-nonlocal` is passed.

## Validated Critical Findings

| Script | Finding | Result | Evidence |
| --- | --- | --- | --- |
| `poc_auth_bypass_telnet.py` | NUL-suffix auth bypass reaches hidden telnet route | PASS | Baseline `/goform/telnet` redirected to `/login.html`; `/goform/telnet%00.js` spawned `telnetd`, opened tcp/23, and a manual `telnet 172.17.0.3 23` reached the firmware `login:` prompt. |
| `poc_auth_bypass_ate.py` | NUL-suffix auth bypass reaches ATE route | PASS | Baseline `/goform/ate` redirected; `/goform/ate%00.js` spawned `td_ate` and opened udp/7329. |
| `poc_auth_bypass_download_cfg.py` | Unauthenticated config backup download | PASS | `/cgi-bin/DownloadCfg%00.js` returned 16,720 bytes, sha256 `5534dc4502743cd0006594f089c1abb675108661e723d71513e9543a371e7231`. |
| `poc_auth_bypass_download_log.py` | Unauthenticated log download | PASS | `/cgi-bin/DownloadLog%00.js` returned 310,272 bytes, sha256 `fd42c51dfb4600d420d7482074e6cce5b28dde1aeca532a20f4826ab5eecc9c8`. |
| `poc_auth_bypass_getmodules.py` | Broad read API reached without auth | PASS | Baseline returned `{"errCode":1000}`; bypass route returned `{}`. |
| `poc_auth_bypass_setmodules.py` | Broad write API reached without auth | PASS | Baseline returned `{"errCode":1000}`; bypass route returned `{"errCode":""}` for the intentionally invalid module body. |
| `poc_zerotier_unauth_rce.py` | Unauthenticated archive download/extract/execute | PASS | `/goform/zerotier%00.js?...` fetched PoC archive and executed `/var/zerotier/start_zerotier.sh` as `uid=0(root)`. |
| `poc_wfa_sta_get_mac_cmd_injection.py` | WFA Sigma text command injection | PASS | `sta_get_mac_address` returned `status,COMPLETE` and created `/tmp/wfa_inj_iface` with `WFA_IFACE`. |
| `poc_wfa_sta_get_ip_config_cmd_injection.py` | WFA Sigma text command injection | PASS | `sta_get_ip_config` returned `status,COMPLETE` and created `/tmp/wfa_inj_ipcfg` with `WFA_IPCFG`. |
| `poc_wfa_sta_set_ip_config_cmd_injection.py` | WFA Sigma text command injection | PASS | `sta_set_ip_config` returned `status,COMPLETE` and created `/tmp/x`. |
| `poc_wfa_direct_dut_cmd_injection.py` | Direct raw TLV injection into `wfa_dut` | PASS | Little-endian TLV tag `0x000c`, len `0x0274` sent to tcp/8000 created `/tmp/direct_8000` with `DIRECT8000`. |

The highest impact validated paths support a CVSS v3.1 vector candidate of
`AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H` when the affected service is reachable
from an attacker-controlled network path.

## Validated Supporting Findings

| Script | Finding | Result | Evidence |
| --- | --- | --- | --- |
| `poc_cookie_missing_security_flags.py` | Login cookie missing hardening flags | PASS | `Set-Cookie: password=...; path=/` lacked `HttpOnly`, `Secure`, and `SameSite`. |
| `poc_csrf_missing_referer_ate.py` | State-changing authenticated GET lacks CSRF guard | PASS | Authenticated `/goform/ate` with no `Referer` spawned `td_ate`; script cleaned it up. |

## Validation Notes

- The ZeroTier route calls `td_common_get_current_network_status()` before
  launching `/usr/sbin/td_zerotier`. The emulation shim returns connected
  network status so this production network-gated path can be exercised.
- The WFA reverse-shell test can leave child processes inheriting the
  `wfa_dut` listening socket. When that happened, Sigma text commands returned
  only `status,RUNNING`. Restarting only `wfa_dut` and `wfa_ca` restored normal
  `status,COMPLETE` behavior and preserved the rest of the firmware container.
- Manual telnet validation initially accepted TCP and then closed because the
  QEMU/chroot runtime lacked `/dev/ptmx` inside the firmware rootfs and had
  restrictive `devpts` `ptmx` permissions. Adding `dev/ptmx -> pts/ptmx` and
  remounting `devpts` with `ptmxmode=666` allowed BusyBox `telnetd` to allocate
  a pty and present the `5ec0d2e4ac27 login:` prompt.
- At the end of the earlier automated PoC pass, the native-httpd cleanup check
  showed only `httpd` listening on ports 80 and 443; no leftover `telnetd`,
  `td_ate`, `td_zerotier`, or `zerotier-one` processes were present. Later
  manual telnet checks intentionally used `--no-cleanup`, so `telnetd` may be
  left running for interactive testing.
