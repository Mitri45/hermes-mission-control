#!/usr/bin/env python3
"""Restricted LAN HTTP proxy for local-only Hermes services.

Use this to expose selected localhost services to a trusted LAN subnet without
changing the real service bind addresses.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from http import client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _parse_cidrs(raw: str) -> list[ipaddress._BaseNetwork]:
    cidrs = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        cidrs.append(ipaddress.ip_network(part, strict=False))
    return cidrs


class _Config:
    bind_host = _env("HERMES_LAN_PROXY_BIND_HOST", "0.0.0.0")
    bind_port = int(_env("HERMES_LAN_PROXY_BIND_PORT", "8768"))
    upstream = _env("HERMES_LAN_PROXY_UPSTREAM", "http://127.0.0.1:8767")
    allow_cidrs = _parse_cidrs(_env("HERMES_LAN_PROXY_ALLOW_CIDRS", "192.168.0.0/24"))
    allowed_prefixes = [p for p in _env("HERMES_LAN_PROXY_ALLOWED_PATH_PREFIXES", "/").split(",") if p.strip()]
    request_timeout = float(_env("HERMES_LAN_PROXY_TIMEOUT_SECS", "30"))


_UPSTREAM = urlsplit(_Config.upstream)
if _UPSTREAM.scheme not in {"http", "https"}:
    raise SystemExit(f"Unsupported upstream scheme: {_UPSTREAM.scheme!r}")
if not _UPSTREAM.hostname:
    raise SystemExit("Upstream hostname is required")


def _client_allowed(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in _Config.allow_cidrs)


def _path_allowed(path: str) -> bool:
    return any(path.startswith(prefix.strip()) for prefix in _Config.allowed_prefixes)


def _hop_by_hop_headers() -> set[str]:
    return {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    }


class _ProxyHandler(BaseHTTPRequestHandler):
    server_version = "HermesLanProxy/1.0"

    def do_GET(self):  # noqa: N802
        self._handle()

    def do_POST(self):  # noqa: N802
        self._handle()

    def do_PUT(self):  # noqa: N802
        self._handle()

    def do_PATCH(self):  # noqa: N802
        self._handle()

    def do_DELETE(self):  # noqa: N802
        self._handle()

    def do_OPTIONS(self):  # noqa: N802
        self._handle()

    def _handle(self) -> None:
        client_ip = self.client_address[0]
        if not _client_allowed(client_ip):
            self.send_error(403, "client ip not allowed")
            return
        if not _path_allowed(self.path):
            self.send_error(403, "path not allowed")
            return

        content_length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(content_length) if content_length > 0 else b""

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in _hop_by_hop_headers()
        }
        headers["Host"] = _UPSTREAM.netloc
        headers["X-Forwarded-For"] = client_ip

        connection_cls = client.HTTPSConnection if _UPSTREAM.scheme == "https" else client.HTTPConnection
        upstream = connection_cls(_UPSTREAM.hostname, _UPSTREAM.port, timeout=_Config.request_timeout)
        try:
            upstream.request(self.command, self.path, body=body or None, headers=headers)
            response = upstream.getresponse()
            payload = response.read()

            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() in _hop_by_hop_headers():
                    continue
                self.send_header(key, value)
            self.end_headers()
            if payload:
                self.wfile.write(payload)
        except Exception as exc:  # pragma: no cover - runtime proxy path
            self.send_error(502, f"upstream request failed: {exc}")
        finally:
            upstream.close()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


def main() -> int:
    server = ThreadingHTTPServer((_Config.bind_host, _Config.bind_port), _ProxyHandler)
    print(
        f"Hermes LAN proxy listening on {_Config.bind_host}:{_Config.bind_port} "
        f"-> {_Config.upstream} (cidrs={','.join(str(c) for c in _Config.allow_cidrs)})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
