from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from zoneinfo import ZoneInfo

from .db import UsageRecord, connect_db, upsert_usage_record
from .utils import local_date_for


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


@dataclass(slots=True)
class ProxyConfig:
    host: str
    port: int
    upstream_base_url: str
    db_path: Path
    tz: ZoneInfo
    app_name: str = "kaku"


class TokkitProxyServer(ThreadingHTTPServer):
    def __init__(self, config: ProxyConfig) -> None:
        self.config = config
        self.db = connect_db(config.db_path)
        self.db_lock = threading.Lock()
        super().__init__((config.host, config.port), TokkitProxyHandler)


class TokkitProxyHandler(BaseHTTPRequestHandler):
    server: TokkitProxyServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy_request()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy_request()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _proxy_request(self) -> None:
        if self.path == "/healthz":
            body = json.dumps({"ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        raw_body = self._read_request_body()
        upstream_url = _build_upstream_url(self.server.config.upstream_base_url, self.path)
        req_headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
        }
        req = request.Request(
            upstream_url,
            data=raw_body if self.command in {"POST", "PUT", "PATCH"} else None,
            headers=req_headers,
            method=self.command,
        )

        try:
            with request.urlopen(req, timeout=120) as resp:
                status_code = resp.status
                resp_headers = dict(resp.headers.items())
                resp_body = resp.read()
        except error.HTTPError as exc:
            status_code = exc.code
            resp_headers = dict(exc.headers.items())
            resp_body = exc.read()

        self.send_response(status_code)
        for key, value in resp_headers.items():
            if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == "content-length":
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

        self._record_usage(
            upstream_url=upstream_url,
            status_code=status_code,
            request_body=raw_body,
            response_body=resp_body,
            response_headers=resp_headers,
        )

    def _read_request_body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length") or 0)
        if content_length <= 0:
            return b""
        return self.rfile.read(content_length)

    def _record_usage(
        self,
        *,
        upstream_url: str,
        status_code: int,
        request_body: bytes,
        response_body: bytes,
        response_headers: dict[str, str],
    ) -> None:
        content_type = response_headers.get("Content-Type", "")
        if "application/json" not in content_type:
            return
        try:
            payload = json.loads(response_body.decode("utf-8"))
        except Exception:
            return
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return

        req_model = None
        if request_body:
            try:
                request_payload = json.loads(request_body.decode("utf-8"))
            except Exception:
                request_payload = {}
            req_model = request_payload.get("model")
        else:
            request_payload = {}

        input_tokens = _pick_first_int(
            usage,
            "input_tokens",
            "prompt_tokens",
        )
        output_tokens = _pick_first_int(
            usage,
            "output_tokens",
            "completion_tokens",
        )
        cached_input_tokens = _nested_int(
            usage,
            ("prompt_tokens_details", "cached_tokens"),
            ("input_tokens_details", "cached_tokens"),
        )
        reasoning_tokens = _nested_int(
            usage,
            ("completion_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "reasoning_tokens"),
        )
        total_tokens = _pick_first_int(usage, "total_tokens")
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

        timestamp = self.date_time_string()
        started_at = _http_date_to_iso(timestamp)
        record = UsageRecord(
            source=f"{self.server.config.app_name}-proxy",
            app=self.server.config.app_name,
            external_id=f"proxy:{uuid.uuid4()}",
            started_at=started_at,
            local_date=local_date_for(started_at, self.server.config.tz),
            measurement_method="exact",
            model=payload.get("model") or req_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            category=parse.urlsplit(upstream_url).path,
            metadata={
                "upstream_url": upstream_url,
                "status_code": status_code,
                "response_id": payload.get("id"),
                "request_model": req_model,
            },
        )
        with self.server.db_lock:
            upsert_usage_record(self.server.db, record)
            self.server.db.commit()


def serve_proxy(config: ProxyConfig) -> None:
    server = TokkitProxyServer(config)
    print(
        f"tokkit proxy listening on http://{config.host}:{config.port} "
        f"-> {config.upstream_base_url}"
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
        server.db.close()


def _build_upstream_url(base_url: str, request_path: str) -> str:
    base = parse.urlsplit(base_url)
    incoming = parse.urlsplit(request_path)
    base_path = base.path.rstrip("/")
    incoming_path = incoming.path or "/"

    if base_path.endswith("/v1") and incoming_path.startswith("/v1/"):
        incoming_path = incoming_path[3:]

    if base_path and not incoming_path.startswith(base_path + "/") and incoming_path != base_path:
        joined_path = f"{base_path}{incoming_path}" if incoming_path.startswith("/") else f"{base_path}/{incoming_path}"
    else:
        joined_path = incoming_path

    return parse.urlunsplit(
        (
            base.scheme,
            base.netloc,
            joined_path,
            incoming.query,
            incoming.fragment,
        )
    )


def _pick_first_int(mapping: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        return int(value)
    return None


def _nested_int(mapping: dict[str, Any], *paths: tuple[str, str]) -> int | None:
    for outer, inner in paths:
        bucket = mapping.get(outer)
        if not isinstance(bucket, dict):
            continue
        value = bucket.get(inner)
        if value is None:
            continue
        return int(value)
    return None


def _http_date_to_iso(value: str) -> str:
    from email.utils import parsedate_to_datetime

    return parsedate_to_datetime(value).isoformat()
