#!/usr/bin/env python3
import argparse
import datetime as dt
import http.client
import http.server
import json
import socketserver
import sys
import urllib.parse


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}

DROP_UPSTREAM_HEADERS = {
    "origin",
    "referer",
}

SIMWAN_DEFAULT = {
    "slot": 1,
    "internetStatus": "disconnected",
    "connectType": "4G",
    "profileIndex": "0",
    "action": "0",
    "list": [{"profileName": "Default", "isDefault": "true"}],
    "isAutoApn": "true",
    "operator": "SIM1",
    "dataOptions": "auto",
    "dataRoaming": "false",
    "ttl_en": "false",
    "hl_en": "false",
    "sim2_profile": {
        "internetStatus": "disconnected",
        "profileIndex": "0",
        "action": "0",
        "list": [{"profileName": "Default", "isDefault": "true"}],
        "isAutoApn": "true",
        "dataOptions": "auto",
        "dataRoaming": "false",
    },
}


def utc_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge_defaults(value, defaults):
    if not isinstance(value, dict):
        value = {}
    merged = dict(defaults)
    merged.update(value)
    if not isinstance(merged.get("sim2_profile"), dict):
        merged["sim2_profile"] = dict(defaults["sim2_profile"])
    else:
        sim2 = dict(defaults["sim2_profile"])
        sim2.update(merged["sim2_profile"])
        merged["sim2_profile"] = sim2
    if not isinstance(merged.get("list"), list) or not merged["list"]:
        merged["list"] = list(defaults["list"])
    if not isinstance(merged["sim2_profile"].get("list"), list) or not merged["sim2_profile"]["list"]:
        merged["sim2_profile"]["list"] = list(defaults["sim2_profile"]["list"])
    return merged


def should_patch_simwan(path):
    parsed = urllib.parse.urlsplit(path)
    if parsed.path != "/goform/getModules":
        return False
    modules = urllib.parse.parse_qs(parsed.query).get("modules", [])
    return any("simWan" in item.split(",") for item in modules)


def normalize_upstream_path(path):
    return path.replace("%2C", ",").replace("%2c", ",")


def should_forward_header(key):
    lower = key.lower()
    return (
        lower not in HOP_BY_HOP_HEADERS
        and lower not in DROP_UPSTREAM_HEADERS
        and lower != "host"
        and not lower.startswith("sec-")
    )


def rewrite_location(value, request_host, upstream_host, upstream_port):
    if not request_host:
        return value
    upstreams = [
        f"http://{upstream_host}:{upstream_port}",
        f"https://{upstream_host}:{upstream_port}",
        f"http://{upstream_host}",
        f"https://{upstream_host}",
        f"//{upstream_host}:{upstream_port}",
        f"//{upstream_host}",
    ]
    for upstream in upstreams:
        if value.startswith(upstream):
            return "http://" + request_host + value[len(upstream) :]
    return value


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_line(self, message):
        self.server.log.write(f"{utc_now()} {message}\n")
        self.server.log.flush()

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def do_PUT(self):
        self.forward()

    def do_DELETE(self):
        self.forward()

    def forward(self):
        upstream_path = normalize_upstream_path(self.path)
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        request_body = self.rfile.read(content_length) if content_length else b""
        headers = {
            key: value
            for key, value in self.headers.items()
            if should_forward_header(key)
        }
        if request_body:
            headers["Content-Length"] = str(len(request_body))

        connection = http.client.HTTPConnection(
            self.server.upstream_host,
            self.server.upstream_port,
            timeout=self.server.timeout_seconds,
        )

        try:
            connection.request(self.command, upstream_path, body=request_body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            status = response.status
            reason = response.reason
            response_headers = response.getheaders()
        except Exception as exc:
            self.log_line(f"ERROR {self.command} {self.path} upstream={exc!r}")
            body = json.dumps({"errCode": 1, "error": "proxy upstream error"}).encode()
            self.send_response(502, "Bad Gateway")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        finally:
            connection.close()

        patched = False
        if should_patch_simwan(upstream_path):
            try:
                data = json.loads(response_body.decode("utf-8"))
                before = data.get("simWan")
                after = merge_defaults(before, SIMWAN_DEFAULT)
                if before != after:
                    data["simWan"] = after
                    response_body = json.dumps(data, separators=(",", ":")).encode("utf-8")
                    patched = True
            except Exception as exc:
                self.log_line(f"WARN {self.command} {self.path} simWan_patch_failed={exc!r}")

        self.log_line(
            f"{self.command} {self.path} upstream_path={upstream_path} -> {status} "
            f"bytes={len(response_body)} patched_simWan={int(patched)}"
        )
        if status >= 400:
            snippet = response_body[:180].decode("utf-8", "replace").replace("\n", " ")
            self.log_line(f"BODY {self.command} {self.path} {snippet}")

        try:
            self.send_response(status, reason)
            for key, value in response_headers:
                lower = key.lower()
                if lower in HOP_BY_HOP_HEADERS or lower == "content-length":
                    continue
                if lower == "location":
                    original = value
                    value = rewrite_location(
                        value,
                        self.headers.get("Host", ""),
                        self.server.upstream_host,
                        self.server.upstream_port,
                    )
                    if value != original:
                        self.log_line(f"REWRITE Location {original} -> {value}")
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except (BrokenPipeError, ConnectionResetError) as exc:
            self.log_line(f"WARN {self.command} {self.path} client_closed={exc!r}")

    def log_message(self, format, *args):
        return


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    parser = argparse.ArgumentParser(description="Tenda native Web UI proxy with minimal runtime state patches.")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=18080)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=18081)
    parser.add_argument("--log-file", default="-")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    log = sys.stdout if args.log_file == "-" else open(args.log_file, "a", buffering=1)
    server = ThreadingHTTPServer((args.listen_host, args.listen_port), ProxyHandler)
    server.upstream_host = args.upstream_host
    server.upstream_port = args.upstream_port
    server.timeout_seconds = args.timeout
    server.log = log
    log.write(
        f"{utc_now()} proxy listening {args.listen_host}:{args.listen_port} "
        f"upstream={args.upstream_host}:{args.upstream_port}\n"
    )
    log.flush()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if log is not sys.stdout:
            log.close()


if __name__ == "__main__":
    main()
