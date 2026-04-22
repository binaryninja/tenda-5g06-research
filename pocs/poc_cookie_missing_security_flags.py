#!/usr/bin/env python3
"""
PoC: login cookie lacks HttpOnly, Secure, and SameSite attributes.
"""

import argparse
import hashlib
import http.cookiejar
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--password", default="Tenda_888888")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    cookiejar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar))
    payload = {"username": "admin", "password": hashlib.md5(args.password.encode()).hexdigest()}
    req = urllib.request.Request(
        args.target.rstrip("/") + "/login/Auth",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json; charset=UTF-8"},
    )
    try:
        resp = opener.open(req, timeout=5)
        body = resp.read().decode(errors="replace")
        headers = resp.headers
        status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        headers = exc.headers
        status = exc.code

    set_cookie = headers.get_all("Set-Cookie") or []
    joined = "\n".join(set_cookie)
    missing = [flag for flag in ("HttpOnly", "Secure", "SameSite") if flag.lower() not in joined.lower()]
    vulnerable = status == 200 and "password=" in joined and len(missing) == 3

    print("[login] POST /login/Auth")
    print(f"  status={status} body={body}")
    print("[cookie]")
    print(joined)
    print(f"  missing={','.join(missing)}")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  cvss evidence: session hardening weakness; supports theft/CSRF chains but is not standalone PR:N RCE")
    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()

