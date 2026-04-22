#!/usr/bin/env python3
"""Serve the extracted Tenda web UI with minimal API compatibility stubs."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


DEFAULTS = {
    "loginLockStatus": {"authErrNum": 0, "lockRemainTime": 0},
    "loginAuth": {"hasLoginPwd": "true"},
    "workMode": {"workMode": "router"},
    "simWan": {
        "connectType": "wire",
        "slot": 1,
        "mobileData": "true",
        "dataRoaming": "false",
        "mtu": "1500",
        "ttl_en": "false",
        "hl_en": "false",
        "dataOptions": "5",
        "bandAggregation": "false",
    },
    "systemCfg": {"productModel": "5G06", "systemVersion": "V05.06.01.29"},
    "systemStatus": {
        "lanIP": "192.168.0.1",
        "staticIP": "false",
        "syncInternetTime": "true",
        "firmware": "V05.06.01.29",
        "remoteEn": "false",
        "autoMaintenanceEn": "false",
        "apClientConnect": "false",
    },
    "simStatus": {
        "slot": 1,
        "simStatus": "1",
        "sim2Status": "1",
        "sim_operator": "SIM1",
        "sim2_operator": "SIM2",
    },
    "smsStatus": {"status": "idle"},
    "onlineList": {"list": []},
    "wifiBasic": {
        "wifiEn": "true",
        "wifiName": "Tenda_5G06",
        "wifiPwd": "",
        "security": "wpapsk",
    },
    "guestNetwork": {"guestEn": "false"},
    "mobileData": {
        "dataLimit": "false",
        "monthlyStatistics": "false",
        "totalUsed": "0",
        "unit": "GB",
        "usageAlert": "80",
        "startDate": "1",
        "timeUp": "true",
    },
    "rebootStatus": {"status": "0"},
    "getRebootStatus": {"status": "0"},
}


def module_payload(names: str) -> dict[str, object]:
    payload: dict[str, object] = {"errCode": 0}
    for raw in names.split(","):
        name = raw.strip()
        if not name:
            continue
        payload[name] = DEFAULTS.get(name, {})
    return payload


class Handler(BaseHTTPRequestHandler):
    www_root: Path

    server_version = "TendaWebUICompat/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - - %s" % (self.address_string(), fmt % args), flush=True)

    def send_json(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/goform/getModules", "/goform/getModules/"):
            modules = parse_qs(parsed.query).get("modules", [""])[0]
            self.send_json(module_payload(modules))
            return
        if path == "/login/Usernum":
            self.send_json({"errCode": 0})
            return
        if path == "/":
            path = "/login.html"
        self.serve_file(path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length) if length else b""
        if parsed.path == "/login/Auth":
            self.send_json({"errCode": 0, "authErrNum": 0, "lockRemainTime": 0})
            return
        if parsed.path.endswith("/setModules") or parsed.path == "/goform/setModules":
            self.send_json({"errCode": 0})
            return
        self.send_json({"errCode": 0, "bodyLength": len(body)})

    def serve_file(self, request_path: str) -> None:
        rel = unquote(request_path).lstrip("/")
        if not rel:
            rel = "login.html"
        candidate = (self.www_root / rel).resolve()
        try:
            candidate.relative_to(self.www_root)
        except ValueError:
            self.send_error(403)
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--www", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=18080, type=int)
    args = parser.parse_args()

    Handler.www_root = args.www.resolve()
    if not (Handler.www_root / "login.html").exists():
        raise SystemExit(f"login.html not found under {Handler.www_root}")

    os.chdir(Handler.www_root)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"serving {Handler.www_root} on http://{args.host}:{args.port}", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
